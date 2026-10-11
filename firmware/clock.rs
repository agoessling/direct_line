//! Fixed 48 MHz HF and 32.768 kHz LF crystals; CPU boots on RCOSC HF.
//! Sequence rationale follows TI SDK 8.33 setup.c, setup_rom.c and osc.h.
use crate::ddi;
use crate::poll::wait_for;
use cc1354p10_registers as r;
use core::arch::asm;

unsafe extern "C" {
    // ti_rom.c exposes TI rom.h's HapiHFSourceSafeSwitch macro.
    fn ti_hf_source_safe_switch();
}

/// Check only the CCFG choices used by this driver and the fixed-rate RTC.
/// Safety: called once by startup before TI setup consumes CCFG.
pub(crate) unsafe fn validate_configuration() {
    // TI hw_ccfg.h MODE_CONF field encodings, unshifted for the generated getters.
    const CCFG_XOSC_FREQ_48M: u32 = 2;
    const CCFG_SCLK_LF_OPTION_XOSC_LF: u32 = 2; // 32.768 kHz crystal.

    // SAFETY: read-only configuration flash, before any clock driver is exposed.
    let config = unsafe { r::CCFG.mode_conf.read() };
    assert_eq!(
        config.xosc_freq(),
        CCFG_XOSC_FREQ_48M,
        "requires 48 MHz HF crystal"
    );
    assert_eq!(
        config.sclk_lf_option(),
        CCFG_SCLK_LF_OPTION_XOSC_LF,
        "requires 32.768 kHz LF crystal"
    );
}

/// Sole HF clock-control handle. Constructed by Board; no LF or shutdown setters.
/// Both HF sources are nominally 48 MHz; RCOSC does not have crystal accuracy.
pub struct Clocks {
    pub(crate) _private: (),
}

impl Clocks {
    /// Start the crystal asynchronously. Repeated requests are harmless.
    /// The regulator remains on RCOSC until a successful switch.
    /// TI OSCClockSourceSet separates request and switch because crystal startup
    /// can take hundreds of microseconds; the CPU can do other work meanwhile.
    pub fn request_hf_crystal(&mut self) {
        const SCLK_HF_SRC_SEL: u32 = 1 << 0;
        // SAFETY: sole clock owner; DDI SET writes only the HF request field.
        unsafe { ddi::set_bits(r::AUX_DDI0_OSC.ctl0.address(), SCLK_HF_SRC_SEL) };
    }

    /// True when the crystal can be selected, or is already the active source.
    pub fn hf_crystal_ready(&self) -> bool {
        // SAFETY: read-only status, independent of other register fields.
        unsafe {
            let status = r::AUX_DDI0_OSC.stat0.read();
            status.sclk_hf_src() || status.pendingsclkhfswitching()
        }
    }

    /// Try to commit a previously requested switch. False means not ready.
    ///
    /// Once ready, briefly masks configurable interrupts around TI's synchronous
    /// ROM switch. The ROM call has no software timeout; hardware readiness is
    /// checked first. A repeated call after switching succeeds without calling ROM.
    /// There is no switch-back API, so a later RF owner cannot lose its reference.
    pub fn try_switch_to_hf_crystal(&mut self) -> bool {
        const CLK_DCDC_SRC_SEL: u32 = 1 << 24;
        // SAFETY: sole clock owner, no other code switches or disables XOSC.
        unsafe {
            let status = r::AUX_DDI0_OSC.stat0.read();
            if status.sclk_hf_src() {
                return true;
            }
            if !status.pendingsclkhfswitching() {
                return false;
            }

            let primask: u32;
            asm!("mrs {}, primask", "cpsid i", out(reg) primask, options(nostack, preserves_flags));
            // TI OSCHfSourceSwitch: a switch can stretch the clock high or low
            // for several cycles. A coincident flash read may freeze the device,
            // so the switch itself executes in ROM and returns only when done.
            // Faults/NMI are terminal; ordinary interrupt handlers cannot run here.
            ti_hf_source_safe_switch();
            // Return DC/DC to automatic selection only after the HF switch.
            ddi::clear_bits(r::AUX_DDI0_OSC.ctl0.address(), CLK_DCDC_SRC_SEL);
            asm!("msr primask, {}", in(reg) primask, options(nostack, preserves_flags));
            true
        }
    }
}

/// Safety: startup owns clocks, after requesting the LF crystal.
pub(crate) unsafe fn finish_lf_startup() {
    // TI hw_ddi_0_osc.h STAT0.SCLK_LF_SRC encoding for the 32.768 kHz crystal.
    const SCLK_LF_SRC_XOSC_LF: u32 = 3;

    // CTL0 fields from TI hw_ddi_0_osc.h.
    const BYPASS_XOSC_LF_CLK_QUAL: u32 = 1 << 29;
    const BYPASS_RCOSC_LF_CLK_QUAL: u32 = 1 << 28;

    unsafe {
        // TI OSCClockSourceSet also forbids powerdown/shutdown until XOSC_LF
        // is running. We finish startup here; no sleep-entry API is exposed.
        wait_for(48_000_000, || {
            r::AUX_DDI0_OSC.stat0.read().sclk_lf_src() == SCLK_LF_SRC_XOSC_LF
        });
        // TI PowerCC26X2_oscDisableQualifiers bypasses both LF qualifiers after source selection.
        // The TRM marks the qualifier fields internal; this sequence follows TI's power driver.
        ddi::set_bits(
            r::AUX_DDI0_OSC.ctl0.address(),
            BYPASS_XOSC_LF_CLK_QUAL | BYPASS_RCOSC_LF_CLK_QUAL,
        );
        enable_clock_loss_reset();
    }
}

/// Enable clock-loss detection and reset the chip on a detected loss.
/// Safety: startup owns oscillator and RESETCTL configuration; TI setup and LF selection are complete.
unsafe fn enable_clock_loss_reset() {
    const CLK_LOSS_EN: u32 = 1 << 9; // Oscillator CTL0 detector enable.

    unsafe {
        ddi::set_bits(r::AUX_DDI0_OSC.ctl0.address(), CLK_LOSS_EN);
        let mut reset = r::AON_PMCTL.resetctl.read();
        reset.set_clk_loss_en(true);
        r::AON_PMCTL.resetctl.write(reset);
        crate::rtc::sync();
    }
}

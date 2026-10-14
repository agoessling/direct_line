//! Explicit board test: fixed setup, HF switch, interrupt-mask preservation.

use crate::device::Board;
use crate::poll::wait_for;
use cc1354p10_registers as r;
use core::arch::asm;

fn primask() -> u32 {
    let value;
    // SAFETY: architectural status read; no memory or processor state changes.
    unsafe { asm!("mrs {}, primask", out(reg) value, options(nomem, nostack, preserves_flags)) };
    value
}

pub fn run(masked_switch: bool, boot_rtc_seconds: u32) {
    let mut board = Board::take().unwrap();
    // Reject switching before a crystal request.
    assert!(!board.clocks.try_switch_to_hf_crystal());
    // SAFETY: test image owns the board; no other users of these peripherals.
    unsafe {
        // Startup selects LF XOSC while keeping HF and DC/DC on RCOSC.
        assert_eq!(r::AUX_DDI0_OSC.stat0.read().sclk_lf_src(), 3);
        assert!(!r::AUX_DDI0_OSC.stat0.read().sclk_hf_src());
        assert!(r::AUX_DDI0_OSC.ctl0.read().clk_dcdc_src_sel());

        // Clock-loss detection and its system-reset response are both enabled.
        assert!(r::AUX_DDI0_OSC.ctl0.read().clk_loss_en());
        assert!(r::AON_PMCTL.resetctl.read().clk_loss_en());

        // RTC uses the 32.768 kHz increment, runs from a fresh epoch, and leaves channels disabled.
        assert_eq!(r::AON_RTC.subsecinc.read().bits(), 0x80_0000);
        assert_eq!(r::AON_RTC.ctl.read().bits(), 1 << 0); // EN; no radio/channel outputs.
        assert_eq!(r::AON_RTC.chctl.read().bits(), 0);
        assert_eq!(boot_rtc_seconds, 0); // LF qualification happened before epoch.
        // TIME is a live, coherent 16.16 sample (TRM 18.4.1.13). SUBSEC alone
        // is a snapshot latched by reading SEC, so polling it would never advance.
        let start = r::AON_RTC.time.read().bits();

        // A crystal request must reach readiness within the polling budget.
        board.clocks.request_hf_crystal();
        wait_for(2_000_000, || board.clocks.hf_crystal_ready());

        // Each case checks that the first switch preserves its initial interrupt mask.
        if masked_switch {
            asm!("cpsid i", options(nostack, preserves_flags));
        }
        let before = primask();
        assert!(board.clocks.try_switch_to_hf_crystal());
        assert_eq!(primask(), before);
        // The completed switch selects HF XOSC and returns DC/DC to automatic clock selection.
        assert!(r::AUX_DDI0_OSC.stat0.read().sclk_hf_src());
        assert!(!r::AUX_DDI0_OSC.ctl0.read().clk_dcdc_src_sel());
        asm!("cpsie i", options(nostack, preserves_flags));
        // Already-active path must be harmless and preserve the unmasked state.
        assert!(board.clocks.try_switch_to_hf_crystal());
        assert_eq!(primask(), 0);

        // Observe RTC progress relative to the sample taken before crystal startup.
        let mut elapsed = 0;
        wait_for(1_000_000, || {
            elapsed = r::AON_RTC.time.read().bits().wrapping_sub(start);
            elapsed != 0
        });
    }
}

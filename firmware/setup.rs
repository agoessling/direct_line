//! One-time chip setup. Ordering is explicit; drivers own their register protocols.
//! TI SDK 8.33 owns the reset-time silicon sequence; Rust completes fixed-board
//! LF/RTC startup before main. A selected LF crystal and running RTC are board
//! defaults; applications configure RTC channels and radio synchronization later.
//! This is not a reinitialization or sleep-resume API.
use crate::{clock, rtc};
use cc1354p10_registers as r;

unsafe extern "C" {
    // SDK driverlib/setup.h: void SetupTrimDevice(void), renamed by the header.
    // Bind the compiled implementation explicitly; no generated binding is needed
    // for this argument-free function. Helpers still use TI's normal ROM policy.
    fn NOROM_SetupTrimDevice();
}

/// Complete silicon setup and LF selection, then start a fresh RTC epoch.
/// Blocks before main; returns with RTC channels/interrupts/radio sync disabled.
///
/// Safety: called once after RAM initialization, with interrupts masked.
pub(crate) unsafe fn initialize() {
    // TI SDK chipinfo.c, ChipInfo_GetChipFamily: WAFER_ID identifies the
    // CC13x4/CC26x4 die family.
    const CC13X4_CC26X4_WAFER_ID: u32 = 0xbb78;

    // FCFG1.USER_ID factory identity bits (SDK hw_fcfg1.h): CC13 selects the CC13x4
    // family; PA reports support for the integrated 20 dBm power amplifier.
    const CC13_WITH_PA: u32 = (1 << 23) | (1 << 25); // CC13 and PA.

    unsafe {
        let identity = r::FCFG1.icepick_device_id.read();
        let user = r::FCFG1.user_id.read().bits();
        assert_eq!(
            identity.wafer_id(),
            CC13X4_CC26X4_WAFER_ID,
            "unsupported silicon family"
        );
        assert_eq!(user & CC13_WITH_PA, CC13_WITH_PA, "requires CC1354P");
        clock::validate_configuration();
        // EXT_REG_MODE reports externally supplied VDDR with the internal DC/DC and GLDO bypassed
        // (TI hw_aon_pmctl.h). This board requires internal regulation.
        assert!(
            !r::AON_PMCTL.pwrctl.read().ext_reg_mode(),
            "unsupported supply wiring"
        );
        // SAFETY: initialized RAM/FPU, exclusive secure startup after ROM boot,
        // supported silicon/board configuration, interrupts still masked. TI's
        // entry consumes factory FCFG and generated CCFG, with no C runtime.
        NOROM_SetupTrimDevice();
        // TI returns before LF crystal selection completes and temporarily uses
        // a 31.25 kHz RTC increment. Complete these steps without its power driver.
        clock::finish_lf_startup();
        rtc::initialize();
    }
}

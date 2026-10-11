//! Board timebase started before main on the fixed LF crystal.
//! Applications choose channel/interrupt/radio use; setup leaves these disabled.
use crate::poll::wait_for;
use cc1354p10_registers as r;
use r::aux_sysif::rtcsubsecincctl::Value as IncrementControl;

/// Safety: exclusive startup access to AON; also drains prior AON writes.
pub(crate) unsafe fn sync() {
    // SAFETY: TRM 18.3.3, synchronization read stalls until AON writes complete.
    unsafe {
        let _ = r::AON_RTC.sync.read();
    }
}

/// Safety: startup owns RTC/AUX update handshake; the clock driver has checked
/// the 32.768 kHz LF crystal configuration and waited for its selection.
pub(crate) unsafe fn initialize() {
    unsafe {
        // TI SetupTrimDevice starts RTC while LF is still HF-derived (31.25 kHz),
        // temporarily adjusts SUBSECINC, then its power driver restores it when
        // XOSC_LF takes over. We complete that handoff before main, without an
        // oscillator ISR. A fresh epoch excludes the LF startup interval.
        // Stop first; keep radio sync and all channel outputs disabled.
        r::AON_RTC.ctl.write(0.into());
        sync();
        // TI SetupSetAonRtcSubSecInc's five steps (TRM 20.8.9.31-33): write
        // increment bits [15:0], write [23:16], set REQ, await ACK, clear REQ.
        // 2^38 / 32768 = 0x800000, exact; this is not a variable-frequency API.
        r::AUX_SYSIF.rtcsubsecinc0.write(0.into());
        r::AUX_SYSIF.rtcsubsecinc1.write(0x80.into());
        let mut request: IncrementControl = 0.into();
        request.set_upd_req(true);
        r::AUX_SYSIF.rtcsubsecincctl.write(request);
        wait_for(48_000_000, || r::AUX_SYSIF.rtcsubsecincctl.read().upd_ack());
        request.set_upd_req(false);
        r::AUX_SYSIF.rtcsubsecincctl.write(request);
        // We additionally await ACK release to finish the handshake before reset.
        wait_for(48_000_000, || {
            !r::AUX_SYSIF.rtcsubsecincctl.read().upd_ack()
        });
        // Establish the epoch only after the final clock/increment are installed.
        let mut control: r::aon_rtc::ctl::Value = 0.into();
        control.set_reset(true);
        r::AON_RTC.ctl.write(control);
        sync();
        wait_for(48_000_000, || !r::AON_RTC.ctl.read().reset());
        r::AON_RTC.chctl.write(0.into());
        // Write one to clear each channel's event flag (CH0, CH1, CH2).
        r::AON_RTC
            .evflags
            .write(((1 << 0) | (1 << 8) | (1 << 16)).into());
        sync();
        // RTC IRQ 4 (TRM Table 5-2); no channel is armed during startup.
        r::CPU_NVIC.icpr0.write((1 << 4).into());
        control.set_reset(false);
        control.set_en(true);
        r::AON_RTC.ctl.write(control);
        sync();
    }
}

//! Shared peripheral power and clock-control operations.
use crate::poll::wait_for;
use cc1354p10_registers as r;

/// Power the shared PERIPH domain and wait until it is available.
/// Panics if the polling budget is exhausted. The domain stays powered afterward.
///
/// # Safety
/// Caller must exclusively own PRCM configuration after chip trim, with interrupts masked.
pub(crate) unsafe fn power_periph() {
    // SAFETY: caller owns the shared power controls; preserve the other domain requests.
    unsafe {
        let mut power = r::PRCM.pdctl0.read();
        power.set_periph_on(true);
        r::PRCM.pdctl0.write(power);
        wait_for(1_000_000, || r::PRCM.pdstat0.read().periph_on());
    }
}

/// Apply pending PRCM clock settings and wait for LOAD_DONE.
/// Panics if the polling budget is exhausted.
///
/// # Safety
/// Caller must exclusively own PRCM configuration during interrupt-masked initialization.
pub(crate) unsafe fn apply_clock_settings() {
    // SAFETY: the caller owns the staged settings and the LOAD handshake.
    unsafe {
        r::PRCM.clkloadctl.write((1 << 0).into()); // LOAD.
        wait_for(1_000_000, || r::PRCM.clkloadctl.read().load_done());
    }
}

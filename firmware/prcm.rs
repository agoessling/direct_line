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

/// Enable the GPIO run-mode clock.
///
/// # Safety
/// PERIPH must be powered. Caller must own PRCM configuration with interrupts masked.
/// Call once per reset before configuring pins; keep power and clocks enabled afterward.
pub(crate) unsafe fn enable_gpio_clock() {
    // SAFETY: PERIPH is powered and the caller owns clock configuration during startup.
    unsafe {
        let mut gpio = r::PRCM.gpioclkgr.read();
        gpio.set_clk_en(true);
        r::PRCM.gpioclkgr.write(gpio);
        apply_clock_settings();
    }
}

/// Enable selected GPT clocks with the board-wide, undivided system-clock source.
///
/// # Safety
/// Caller must own PRCM with PERIPH powered and CPU interrupts masked, before initializing any GPT.
pub(crate) unsafe fn enable_timer_clocks(mask: u32) {
    assert_eq!(mask & !0xf, 0, "only GPT0–GPT3 exist");
    // SAFETY: caller owns the shared divider and gate configuration during board initialization.
    unsafe {
        let mut clocks = r::PRCM.gptclkgr.read();
        clocks.set_clk_en(clocks.clk_en() | mask);
        r::PRCM.gptclkgr.write(clocks);
        r::PRCM.gptclkdiv.write(0.into());
        apply_clock_settings();
    }
}

/// Apply pending PRCM clock settings and wait for LOAD_DONE.
/// Panics if the polling budget is exhausted.
///
/// # Safety
/// Caller must exclusively own PRCM configuration during interrupt-masked initialization.
unsafe fn apply_clock_settings() {
    // SAFETY: the caller owns the staged settings and the LOAD handshake.
    unsafe {
        r::PRCM.clkloadctl.write((1 << 0).into()); // LOAD.
        wait_for(1_000_000, || r::PRCM.clkloadctl.read().load_done());
    }
}

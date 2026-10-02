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

/// Power the shared SERIAL domain and wait until it is available.
/// Panics if the polling budget is exhausted. The domain stays powered afterward.
///
/// # Safety
/// Caller must exclusively own PRCM configuration after chip trim, with interrupts masked.
pub(crate) unsafe fn power_serial() {
    // SAFETY: caller owns the shared power controls; preserve the other domain requests.
    unsafe {
        let mut power = r::PRCM.pdctl0.read();
        power.set_serial_on(true);
        r::PRCM.pdctl0.write(power);
        wait_for(1_000_000, || r::PRCM.pdstat0.read().serial_on());
    }
}

/// Enable selected UART0–UART3 run-mode clocks.
///
/// # Safety
/// Caller must own PRCM with CPU interrupts masked, before initializing the selected UARTs.
/// SERIAL must be powered for UART0, PERIPH for UART1–UART3 (TRM SWCU194 §7.8.1.43).
pub(crate) unsafe fn enable_uart_clocks(mask: u32) {
    assert_eq!(mask & !0xf, 0, "only UART0–UART3 exist");
    // SAFETY: caller owns clock configuration during board initialization.
    unsafe {
        let mut clocks = r::PRCM.uartclkgr.read();
        clocks.set_clk_en(clocks.clk_en() | mask);
        r::PRCM.uartclkgr.write(clocks);
        apply_clock_settings();
    }
}

/// Enable the GPIO run-mode clock.
///
/// # Safety
/// PERIPH must be powered. Caller must own PRCM configuration with interrupts masked.
/// Keep power and clocks enabled afterward; repeated calls preserve existing GPIO configuration.
pub(crate) unsafe fn enable_gpio_clock() {
    // SAFETY: PERIPH is powered and the caller owns clock configuration during startup.
    unsafe {
        let mut gpio = r::PRCM.gpioclkgr.read();
        gpio.set_clk_en(true);
        r::PRCM.gpioclkgr.write(gpio);
        apply_clock_settings();
    }
}

/// Set the shared GPT0–GPT3 divider to the undivided system clock (TRM SWCU194 §7.8.1.34).
///
/// # Safety
/// Caller must own PRCM after chip trim with CPU interrupts masked. Call once before any GPT
/// is initialized; retain this setting for every timer handle's lifetime.
pub(crate) unsafe fn initialize_timer_clock() {
    // SAFETY: no timer is running; caller owns the shared divider and LOAD handshake.
    unsafe {
        r::PRCM.gptclkdiv.write(0.into());
        apply_clock_settings();
    }
}

/// Enable selected GPT run-mode clocks without changing the shared divider.
///
/// # Safety
/// Caller must own PRCM with PERIPH powered and CPU interrupts masked, before initializing the
/// selected GPTs. The shared divider must already be configured.
pub(crate) unsafe fn enable_timer_clocks(mask: u32) {
    assert_eq!(mask & !0xf, 0, "only GPT0–GPT3 exist");
    // SAFETY: caller owns the gate configuration; preserve clocks of previously initialized GPTs.
    unsafe {
        let mut clocks = r::PRCM.gptclkgr.read();
        clocks.set_clk_en(clocks.clk_en() | mask);
        r::PRCM.gptclkgr.write(clocks);
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

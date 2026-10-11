//! Board wiring and one-time assembly of the concrete peripheral drivers.
use crate::gpio::{self, OutputPin};
use crate::prcm;
use cc1354p10_registers as r;
use core::arch::asm;
use core::sync::atomic::{AtomicBool, Ordering};

static TAKEN: AtomicBool = AtomicBool::new(false);

pub struct Board {
    pub red_led: OutputPin,
    pub green_led: OutputPin,
    pub clocks: crate::Clocks,
}

impl Board {
    /// Acquire this board once per reset. Configures DIO6/7 LEDs, then enables
    /// CPU interrupts; no peripheral interrupt source is armed.
    /// Panics on a failed hardware handshake. This is foreground initialization.
    pub fn take() -> Option<Self> {
        if TAKEN.swap(true, Ordering::Relaxed) {
            return None;
        }
        // SAFETY: uniqueness claim excludes competing initialization. Startup has
        // initialized chip trim and still masks interrupts. No driver exists yet.
        let board = unsafe {
            const RED_LED_DIO: usize = 6;
            const GREEN_LED_DIO: usize = 7;
            prcm::power_periph();
            gpio::initialize();
            let red_led = gpio::configure_output(RED_LED_DIO);
            let green_led = gpio::configure_output(GREEN_LED_DIO);

            // Release global retention after all board pins have their intended configuration.
            // TI SetupTrimDevice leaves pad sleep enabled after shutdown until pins are restored.
            let mut sleep = r::AON_PMCTL.sleepctl.read();
            sleep.set_io_pad_sleep_dis(true);
            r::AON_PMCTL.sleepctl.write(sleep);
            let mut latch: r::aon_ioc::ioclatch::Value = 0.into();
            latch.set_en(true); // Open latches frozen before retained powerdown.
            r::AON_IOC.ioclatch.write(latch);

            Self {
                red_led,
                green_led,
                clocks: crate::Clocks { _private: () },
            }
        };
        // SAFETY: GPIO initialization is complete; no interrupt source is armed.
        unsafe { asm!("cpsie i", options(nostack, preserves_flags)) };
        Some(board)
    }
}

//! Board wiring and one-time assembly of the concrete peripheral drivers.
use crate::gpio::{self, OutputPin};
use crate::prcm;
use crate::timer::{Counter, Instance, Timer};
use cc1354p10_registers as r;
use core::arch::asm;
use core::sync::atomic::{AtomicBool, Ordering};

static TAKEN: AtomicBool = AtomicBool::new(false);

pub struct Board {
    pub red_led: OutputPin,
    pub green_led: OutputPin,
    pub clocks: crate::Clocks,
    pub counter: Counter,
    pub timer: Timer,
}

impl Board {
    /// Acquire this board once per reset. Configures DIO6/7 LEDs, starts GPT1,
    /// and initializes GPT0 stopped, then enables CPU interrupts.
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
            const COUNTER_GPT: Instance = Instance::Gpt1;
            const TIMER_GPT: Instance = Instance::Gpt0;
            prcm::power_periph();
            prcm::enable_gpio_clock();
            let red_led = gpio::configure_output(RED_LED_DIO);
            let green_led = gpio::configure_output(GREEN_LED_DIO);
            prcm::enable_timer_clocks(COUNTER_GPT.clock_mask() | TIMER_GPT.clock_mask());
            let counter = Counter::initialize(COUNTER_GPT);
            let timer = Timer::initialize(TIMER_GPT);

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
                counter,
                timer,
            }
        };
        // SAFETY: peripheral initialization is complete; GPT0's interrupt remains disabled.
        unsafe { asm!("cpsie i", options(nostack, preserves_flags)) };
        Some(board)
    }
}

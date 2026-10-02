//! Board wiring and one-time assembly of the concrete peripheral drivers.
use crate::gpio::{self, OutputPin};
use crate::interrupts;
use crate::ioc;
use crate::prcm;
use crate::timer::{Counter, Instance, Timer};
use crate::uart::{self, Uart};
use core::sync::atomic::{AtomicBool, Ordering};

static TAKEN: AtomicBool = AtomicBool::new(false);

pub struct Board {
    pub red_led: OutputPin,
    pub green_led: OutputPin,
    pub clocks: crate::Clocks,
    pub counter: Counter,
    pub timer: Timer,
    pub uart: Uart,
}

impl Board {
    /// Acquire this board once per reset. Configures DIO6/7 LEDs, starts GPT1,
    /// and initializes GPT0 stopped and DIO12/13 UART0, then enables CPU interrupts.
    /// Panics on a failed hardware handshake. This is foreground initialization.
    pub fn take() -> Option<Self> {
        if TAKEN.swap(true, Ordering::Relaxed) {
            return None;
        }
        // SAFETY: uniqueness claim excludes competing initialization. Startup has
        // initialized chip trim and still masks interrupts. No driver exists yet.
        unsafe {
            prcm::initialize_timer_clock();
            let board = Self::configure();
            ioc::release_retention();
            interrupts::enable();
            Some(board)
        }
    }

    /// Safety: exclusive board initialization after trim, with the GPT divider set and IRQs masked.
    unsafe fn configure() -> Self {
        // SAFETY: each peripheral and pin is assigned once; constructors serialize PRCM accesses.
        unsafe {
            const RED_LED_DIO: usize = 6;
            const GREEN_LED_DIO: usize = 7;
            const UART_RX_DIO: usize = 12;
            const UART_TX_DIO: usize = 13;
            const UART: uart::Instance = uart::Instance::Uart0;
            const UART_BAUD: u32 = 115_200;
            const COUNTER_GPT: Instance = Instance::Gpt1;
            const TIMER_GPT: Instance = Instance::Gpt0;
            let red_led = gpio::configure_output(RED_LED_DIO);
            let green_led = gpio::configure_output(GREEN_LED_DIO);
            let counter = Counter::initialize(COUNTER_GPT);
            let timer = Timer::initialize(TIMER_GPT);
            let uart = Uart::initialize(UART, UART_RX_DIO, UART_TX_DIO, UART_BAUD)
                .expect("invalid board UART baud rate");

            Self {
                red_led,
                green_led,
                clocks: crate::Clocks { _private: () },
                counter,
                timer,
                uart,
            }
        }
    }
}

#![no_std]
#![no_main]
//! Hardware tests: shared reset checks and explicit harness failure controls.
mod board_test;
mod clock;
mod clock_test;
mod ddi;
mod device;
mod gpio;
mod gpio_test;
mod interrupts;
mod ioc;
mod mmio;
mod poll;
mod prcm;
mod rtc;
mod setup;
mod startup;
mod timer;
mod timer_test;
mod uart;
mod uart_test;

use clock::Clocks;
use core::sync::atomic::{AtomicU32, Ordering};

static INITIALIZED_DATA: AtomicU32 = AtomicU32::new(0x1234_abcd);
static ZEROED_DATA: AtomicU32 = AtomicU32::new(0);
static BOOT_RTC_SECONDS: AtomicU32 = AtomicU32::new(u32::MAX);

#[embedded_test::setup]
fn before_host_handshake() {
    // Capture the fresh epoch before semihosting halts; the RTC runs while the debugger waits.
    // SAFETY: startup initialized RTC; this status read has no side effects.
    let boot_rtc_seconds = unsafe { cc1354p10_registers::AON_RTC.sec.read().bits() };
    BOOT_RTC_SECONDS.store(boot_rtc_seconds, Ordering::Relaxed);
    // Every case must enter through reset, restoring RAM even after a panic, fault, or timeout.
    assert_eq!(INITIALIZED_DATA.load(Ordering::Relaxed), 0x1234_abcd);
    assert_eq!(ZEROED_DATA.load(Ordering::Relaxed), 0);
    INITIALIZED_DATA.store(0x5678_ef01, Ordering::Relaxed);
    ZEROED_DATA.store(1, Ordering::Relaxed);
}

/// RTC epoch captured before debugger communication can delay test entry.
pub(crate) fn boot_rtc_seconds() -> u32 {
    BOOT_RTC_SECONDS.load(Ordering::Relaxed)
}

#[embedded_test::tests(default_timeout = 3)]
mod harness {
    use crate::interrupts;

    #[test]
    fn pass() {}

    #[test]
    #[should_panic]
    fn panic() {
        panic!("intentional harness panic");
    }

    #[test]
    #[ignore]
    fn unexpected_panic() {
        panic!("unexpected panic negative control");
    }

    #[test]
    #[ignore]
    #[should_panic]
    fn missing_panic() {}

    // The framework treats these terminal outcomes as failures; run them separately to check detection.
    #[test]
    #[ignore]
    #[timeout(1)]
    fn fault() {
        // SAFETY: intentional terminal UsageFault; no peripheral IRQs have been enabled.
        unsafe {
            interrupts::enable();
            core::arch::asm!("udf #0", options(noreturn));
        }
    }

    #[test]
    #[ignore]
    #[timeout(1)]
    fn timeout() {
        loop {
            core::hint::spin_loop();
        }
    }
}

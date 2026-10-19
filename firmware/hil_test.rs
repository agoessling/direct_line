#![no_std]
#![no_main]
//! One case per reset. The host selects a case at hil_ready and observes completion at hil_done.
mod board_test;
mod clock;
mod clock_test;
mod ddi;
mod device;
mod gpio;
mod gpio_test;
mod hil_registry;
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
use core::arch::asm;
use core::sync::atomic::{AtomicU32, Ordering};
use hil_registry::{TestContext, hil_tests};

// Shared debugger ABI; keep values in sync with tools/debug/protocol.py.
const PROTOCOL_VERSION: u32 = 1;
const INVALID_CASE_ID: u32 = u32::MAX;
const NO_TOKEN: u32 = 0;

#[repr(u32)]
enum Status {
    Idle = 0,
    Running = 1,
    Pass = 2,
}

hil_tests! {
    "harness/pass" => {
        run: |_| (),
        suites: [harness, smoke],
        timeout_ms: 1000,
    },
    "harness/panic" => {
        run: |_| panic!("intentional harness panic"),
        suites: [harness],
        timeout_ms: 1000,
        expect: Panic,
    },
    "harness/fault" => {
        run: |_| intentional_fault(),
        suites: [harness],
        timeout_ms: 1000,
        expect: Fault,
    },
    "harness/timeout" => {
        run: |_| loop { core::hint::spin_loop(); },
        suites: [harness],
        timeout_ms: 1000,
        expect: Timeout,
    },
    "clock/unmasked" => {
        run: |context| clock_test::run(false, context.boot_rtc_seconds),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "clock/masked" => {
        run: |context| clock_test::run(true, context.boot_rtc_seconds),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "gpio/outputs" => {
        run: |_| gpio_test::run(),
        suites: [drivers, smoke],
        timeout_ms: 3000,
    },
    "timer/gpt0" => {
        run: |_| timer_test::run(0),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "timer/gpt1" => {
        run: |_| timer_test::run(1),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "timer/gpt2" => {
        run: |_| timer_test::run(2),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "timer/gpt3" => {
        run: |_| timer_test::run(3),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "uart/uart0" => {
        run: |_| uart_test::run(0),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "uart/uart1" => {
        run: |_| uart_test::run(1),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "uart/uart2" => {
        run: |_| uart_test::run(2),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "uart/uart3" => {
        run: |_| uart_test::run(3),
        suites: [drivers],
        timeout_ms: 3000,
    },
    "board/bringup" => {
        run: |_| board_test::run(),
        suites: [integration, smoke],
        timeout_ms: 3000,
    },
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct Request {
    case_id: u32,
    token: u32,
}

#[repr(C)]
pub struct Result {
    version: u32,
    case_id: u32,
    token: u32,
    // Failures leave BOOT_DIAGNOSTIC intact.
    status: Status,
}

#[unsafe(no_mangle)]
pub static mut HIL_REQUEST: Request = Request {
    case_id: INVALID_CASE_ID,
    token: NO_TOKEN,
};

#[unsafe(no_mangle)]
pub static mut HIL_RESULT: Result = Result {
    version: PROTOCOL_VERSION,
    case_id: INVALID_CASE_ID,
    token: NO_TOKEN,
    status: Status::Idle,
};

const _: () = {
    assert!(core::mem::size_of::<Request>() == 8);
    assert!(core::mem::size_of::<Result>() == 16);
};

/// Host breakpoint: RAM and startup are initialized; no peripheral handles exist yet.
#[unsafe(no_mangle)]
#[inline(never)]
pub extern "C" fn hil_ready() {
    // SAFETY: explicit instruction keeps a distinct executable breakpoint location.
    unsafe { asm!("nop", options(nostack, preserves_flags)) };
}

/// Host breakpoint: HIL_RESULT has been published and this case must not run again without reset.
#[unsafe(no_mangle)]
#[inline(never)]
pub extern "C" fn hil_done() -> ! {
    loop {
        // SAFETY: the test is complete; wait for the host to reset the device.
        unsafe { asm!("wfi", options(nomem, nostack)) };
    }
}

#[unsafe(no_mangle)]
pub extern "C" fn main() -> ! {
    // Capture the epoch before the host halts at hil_ready: RTC continues during debugger halts.
    // SAFETY: startup has initialized the RTC; this status read has no side effects.
    let boot_rtc_seconds = unsafe { cc1354p10_registers::AON_RTC.sec.read().bits() };
    // Every reset must restore .data/.bss, including after a panic, fault, or timeout.
    assert_eq!(INITIALIZED_DATA.load(Ordering::Relaxed), 0x1234_abcd);
    assert_eq!(ZEROED_DATA.load(Ordering::Relaxed), 0);
    INITIALIZED_DATA.store(0x5678_ef01, Ordering::Relaxed);
    ZEROED_DATA.store(1, Ordering::Relaxed);
    loop {
        hil_ready();
        // SAFETY: the host writes this word only while halted at hil_ready.
        if unsafe { (&raw const HIL_REQUEST.token).read_volatile() } != NO_TOKEN {
            break;
        }
        core::hint::spin_loop();
    }
    // SAFETY: the host writes only while halted at hil_ready. No interrupt accesses these records.
    // Volatile reads also retain the discovery symbols through linker garbage collection.
    let request = unsafe {
        let request = (&raw const HIL_REQUEST).read_volatile();
        let count = (&raw const HIL_TEST_COUNT).read_volatile();
        assert!(request.case_id < count);
        let description = (&raw const HIL_TESTS)
            .cast::<hil_registry::TestDescription>()
            .add(request.case_id as usize);
        assert_eq!(
            (&raw const (*description).id).read_volatile(),
            request.case_id
        );
        (&raw mut HIL_RESULT).write_volatile(Result {
            version: PROTOCOL_VERSION,
            case_id: request.case_id,
            token: request.token,
            status: Status::Running,
        });
        request
    };
    TEST_FUNCTIONS[request.case_id as usize](&TestContext { boot_rtc_seconds });
    // SAFETY: sole writer, with the host observing only after hil_done is reached.
    unsafe { (&raw mut HIL_RESULT.status).write_volatile(Status::Pass) };
    hil_done()
}

static INITIALIZED_DATA: AtomicU32 = AtomicU32::new(0x1234_abcd);
static ZEROED_DATA: AtomicU32 = AtomicU32::new(0);

fn intentional_fault() -> ! {
    // SAFETY: intentional terminal UsageFault; no peripheral IRQs have been enabled.
    unsafe {
        interrupts::enable();
        asm!("udf #0", options(noreturn));
    }
}

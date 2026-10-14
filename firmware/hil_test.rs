#![no_std]
#![no_main]
//! One case per reset. The host selects a case at hil_ready and observes completion at hil_done.
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
use core::arch::asm;
use core::sync::atomic::{AtomicU32, Ordering};
use device::Board;
use poll::wait_for;
use timer::{GPT_CLOCK_HZ, ticks_from_us};

const PROTOCOL_VERSION: u32 = 1;
const EXPECT_PASS: u32 = 0;
const EXPECT_PANIC: u32 = 1;
const EXPECT_FAULT: u32 = 2; // UDF UsageFault.
const EXPECT_TIMEOUT: u32 = 3;
const STATUS_IDLE: u32 = 0;
const STATUS_RUNNING: u32 = 1;
const STATUS_PASS: u32 = 2;

/// Fixed little-endian debugger ABI; names are UTF-8, padded with zero bytes.
#[repr(C)]
pub struct TestDescription {
    id: u32,
    timeout_ms: u32,
    expected: u32,
    name: [u8; 52],
}

impl TestDescription {
    const fn new(id: u32, name: &str, timeout_ms: u32, expected: u32) -> Self {
        assert!(name.len() < 52);
        let mut bytes = [0; 52];
        let mut index = 0;
        while index < name.len() {
            bytes[index] = name.as_bytes()[index];
            index += 1;
        }
        Self {
            id,
            timeout_ms,
            expected,
            name: bytes,
        }
    }
}

#[unsafe(no_mangle)]
pub static HIL_TESTS: [TestDescription; 16] = [
    TestDescription::new(0, "harness/pass", 1000, EXPECT_PASS),
    TestDescription::new(1, "harness/panic", 1000, EXPECT_PANIC),
    TestDescription::new(2, "harness/fault", 1000, EXPECT_FAULT),
    TestDescription::new(3, "harness/timeout", 1000, EXPECT_TIMEOUT),
    TestDescription::new(4, "clock/unmasked", 3000, EXPECT_PASS),
    TestDescription::new(5, "clock/masked", 3000, EXPECT_PASS),
    TestDescription::new(6, "gpio/outputs", 3000, EXPECT_PASS),
    TestDescription::new(7, "timer/gpt0", 3000, EXPECT_PASS),
    TestDescription::new(8, "timer/gpt1", 3000, EXPECT_PASS),
    TestDescription::new(9, "timer/gpt2", 3000, EXPECT_PASS),
    TestDescription::new(10, "timer/gpt3", 3000, EXPECT_PASS),
    TestDescription::new(11, "uart/uart0", 3000, EXPECT_PASS),
    TestDescription::new(12, "uart/uart1", 3000, EXPECT_PASS),
    TestDescription::new(13, "uart/uart2", 3000, EXPECT_PASS),
    TestDescription::new(14, "uart/uart3", 3000, EXPECT_PASS),
    TestDescription::new(15, "board/bringup", 3000, EXPECT_PASS),
];

#[unsafe(no_mangle)]
pub static HIL_TEST_COUNT: u32 = HIL_TESTS.len() as u32;

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
    status: u32,
}

#[unsafe(no_mangle)]
pub static mut HIL_REQUEST: Request = Request {
    case_id: u32::MAX,
    token: 0,
};

#[unsafe(no_mangle)]
pub static mut HIL_RESULT: Result = Result {
    version: PROTOCOL_VERSION,
    case_id: u32::MAX,
    token: 0,
    status: STATUS_IDLE,
};

const _: () = {
    assert!(core::mem::size_of::<TestDescription>() == 64);
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
        if unsafe { (&raw const HIL_REQUEST.token).read_volatile() } != 0 {
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
            .cast::<TestDescription>()
            .add(request.case_id as usize);
        assert_eq!(
            (&raw const (*description).id).read_volatile(),
            request.case_id
        );
        (&raw mut HIL_RESULT).write_volatile(Result {
            version: PROTOCOL_VERSION,
            case_id: request.case_id,
            token: request.token,
            status: STATUS_RUNNING,
        });
        request
    };
    match request.case_id {
        0 => (),
        1 => panic!("intentional harness panic"),
        2 => {
            // SAFETY: intentional terminal UsageFault; no peripheral IRQs have been enabled.
            unsafe {
                interrupts::enable();
                asm!("udf #0", options(noreturn));
            }
        }
        3 => loop {
            core::hint::spin_loop();
        },
        4 | 5 => clock_test::run(request.case_id == 5, boot_rtc_seconds),
        6 => gpio_test::run(),
        7..=10 => timer_test::run((request.case_id - 7) as usize),
        11..=14 => uart_test::run((request.case_id - 11) as usize),
        15 => bringup(),
        _ => unreachable!(),
    }
    // SAFETY: sole writer, with the host observing only after hil_done is reached.
    unsafe { (&raw mut HIL_RESULT.status).write_volatile(STATUS_PASS) };
    hil_done()
}

static INITIALIZED_DATA: AtomicU32 = AtomicU32::new(0x1234_abcd);
static ZEROED_DATA: AtomicU32 = AtomicU32::new(0);

fn bringup() {
    let mut board = Board::take().unwrap();
    assert!(Board::take().is_none());
    board.clocks.request_hf_crystal();
    wait_for(2_000_000, || board.clocks.try_switch_to_hf_crystal());
    board.timer.start_periodic_us(1000).unwrap();
    let start = board.counter.now();
    wait_for(48_000_000, || {
        assert!(board.counter.elapsed_since(start) < GPT_CLOCK_HZ);
        board.timer.interrupts() >= 20
    });
    board.timer.stop();
    let stopped = board.timer.interrupts();
    let start = board.counter.now();
    let ten_ms = ticks_from_us(10_000).unwrap();
    wait_for(1_000_000, || board.counter.elapsed_since(start) >= ten_ms);
    assert_eq!(board.timer.interrupts(), stopped);
    assert!(board.timer.start_periodic_us(0).is_err());
    assert!(board.timer.start_periodic_us(u32::MAX).is_err());
    board.timer.start_once_us(1000).unwrap();
    let start = board.counter.now();
    wait_for(1_000_000, || board.counter.elapsed_since(start) >= ten_ms);
    assert_eq!(board.timer.interrupts(), stopped.wrapping_add(1));
    board.timer.stop();
    // Enqueueing exercises the board's transport wiring; physical serial checks are host-side.
    board
        .uart
        .write_timeout(b"RESULT PASS bringup\r\n", &board.counter, GPT_CLOCK_HZ)
        .unwrap();
}

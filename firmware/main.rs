#![no_std]
#![no_main]

mod poll;

use core::sync::atomic::{AtomicU32, Ordering};
use device::{Board, GPT_CLOCK_HZ, ticks_from_us};
use poll::wait_for;

static INITIALIZED_DATA: AtomicU32 = AtomicU32::new(0x1234_abcd);
static ZEROED_DATA: AtomicU32 = AtomicU32::new(0);

/// Observable progress for debugger checks before a serial driver exists.
#[unsafe(no_mangle)]
static BLINK_COUNT: AtomicU32 = AtomicU32::new(0);

/// 0 before checks, 1 while running, 2 after timer assertions pass.
#[unsafe(no_mangle)]
static TIMER_TEST_STATUS: AtomicU32 = AtomicU32::new(0);

#[unsafe(no_mangle)]
pub extern "C" fn main() -> ! {
    let mut board = Board::take().expect("board already taken");
    assert_eq!(INITIALIZED_DATA.load(Ordering::Relaxed), 0x1234_abcd);
    assert_eq!(ZEROED_DATA.load(Ordering::Relaxed), 0);
    INITIALIZED_DATA.store(0x5678_ef01, Ordering::Relaxed);
    ZEROED_DATA.store(1, Ordering::Relaxed);
    board.clocks.request_hf_crystal();
    wait_for(2_000_000, || board.clocks.try_switch_to_hf_crystal());

    TIMER_TEST_STATUS.store(1, Ordering::Relaxed);
    board.timer.start_periodic_us(1_000).unwrap();
    let start = board.counter.now();
    // Require repeated IRQ service within one nominal second of counter progress.
    wait_for(48_000_000, || {
        assert!(
            board.counter.elapsed_since(start) < GPT_CLOCK_HZ,
            "timer interrupt timeout"
        );
        board.timer.interrupts() >= 20
    });
    board.timer.stop();
    let stopped = board.timer.interrupts();
    let start = board.counter.now();
    let ten_ms = ticks_from_us(10_000).unwrap();
    wait_for(1_000_000, || board.counter.elapsed_since(start) >= ten_ms);
    assert_eq!(board.timer.interrupts(), stopped, "interrupt after stop");
    assert!(board.timer.start_periodic_us(0).is_err());
    assert!(board.timer.start_periodic_us(u32::MAX).is_err());

    // Wait well beyond the deadline: a one-shot must produce exactly one interrupt.
    board.timer.start_once_us(1_000).unwrap();
    let start = board.counter.now();
    wait_for(1_000_000, || board.counter.elapsed_since(start) >= ten_ms);
    assert_eq!(board.timer.interrupts(), stopped.wrapping_add(1));
    board.timer.stop();
    TIMER_TEST_STATUS.store(2, Ordering::Relaxed);

    board.timer.start_periodic_us(500_000).unwrap();
    let mut previous = board.timer.interrupts();
    loop {
        let current = board.timer.interrupts();
        if current != previous {
            previous = current;
            board.red_led.toggle();
            board.green_led.toggle();
            BLINK_COUNT.fetch_add(1, Ordering::Relaxed);
        }
        core::hint::spin_loop();
    }
}

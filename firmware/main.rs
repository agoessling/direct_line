#![no_std]
#![no_main]

use core::sync::atomic::{AtomicU32, Ordering};
use device::Board;

static INITIALIZED_DATA: AtomicU32 = AtomicU32::new(0x1234_abcd);
static ZEROED_DATA: AtomicU32 = AtomicU32::new(0);

/// Observable progress for debugger checks before a serial driver exists.
#[unsafe(no_mangle)]
static BLINK_COUNT: AtomicU32 = AtomicU32::new(0);

#[unsafe(no_mangle)]
pub extern "C" fn main() -> ! {
    let mut board = Board::take().expect("board already taken");
    assert_eq!(INITIALIZED_DATA.load(Ordering::Relaxed), 0x1234_abcd);
    assert_eq!(ZEROED_DATA.load(Ordering::Relaxed), 0);
    INITIALIZED_DATA.store(0x5678_ef01, Ordering::Relaxed);
    ZEROED_DATA.store(1, Ordering::Relaxed);
    // Demonstrate the one-way HF transition. Readiness polling is nonblocking;
    // this application chooses a bounded iteration budget for initial bring-up.
    board.clocks.request_hf_crystal();
    let mut switched = false;
    for _ in 0..2_000_000 {
        if board.clocks.try_switch_to_hf_crystal() {
            switched = true;
            break;
        }
        core::hint::spin_loop();
    }
    assert!(switched, "HF crystal startup timeout");
    loop {
        board.red_led.toggle();
        board.green_led.toggle();
        BLINK_COUNT.fetch_add(1, Ordering::Relaxed);
        // Deliberately approximate visible delay: no timer or calibrated timing.
        for _ in 0..1_000_000 {
            core::hint::spin_loop();
        }
    }
}

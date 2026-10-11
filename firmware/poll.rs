//! Bounded polling for hardware initialization handshakes.

/// Poll at most `iterations` times, panicking if the condition never becomes true.
/// The budget counts attempts; elapsed time depends on the condition and CPU clock.
#[track_caller]
pub(crate) fn wait_for(iterations: u32, mut ready: impl FnMut() -> bool) {
    for _ in 0..iterations {
        if ready() {
            return;
        }
        core::hint::spin_loop();
    }
    panic!("hardware handshake iteration budget exhausted");
}

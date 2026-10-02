#![no_std]
#![forbid(unsafe_code)]

/// True once a wrapping 32-bit counter reaches a deadline less than half a cycle away.
pub const fn deadline_reached(now: u32, deadline: u32) -> bool {
    now.wrapping_sub(deadline) < (1 << 31)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deadline_crosses_counter_wrap() {
        assert!(!deadline_reached(u32::MAX - 1, 2));
        assert!(!deadline_reached(1, 2));
        assert!(deadline_reached(2, 2));
        assert!(deadline_reached(3, 2));
    }
}

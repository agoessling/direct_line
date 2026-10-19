//! Full board assembly, timer sequencing, and UART enqueue checks.

#[embedded_test::tests(default_timeout = 3)]
mod board {
    use crate::device::Board;
    use crate::poll::wait_for;
    use crate::timer::{GPT_CLOCK_HZ, ticks_from_us};

    #[test]
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
}

//! Board acquisition and operation of its assembled clocks, timers, and UART.

#[embedded_test::tests(default_timeout = 3)]
mod board {
    use crate::device::Board;
    use crate::poll::wait_for;
    use crate::timer::GPT_CLOCK_HZ;

    #[test]
    fn bringup() {
        let mut board = Board::take().unwrap();
        assert!(Board::take().is_none());
        board.clocks.request_hf_crystal();
        wait_for(2_000_000, || board.clocks.try_switch_to_hf_crystal());
        board.timer.start_periodic_us(1000).unwrap();
        let start = board.counter.now();

        // Exercise UART enqueueing with timer interrupts enabled; this does not check external pins.
        board
            .uart
            .write_timeout(b"board test\r\n", &board.counter, GPT_CLOCK_HZ)
            .unwrap();

        // Board initialization must leave the counter advancing and the timer IRQ serviceable.
        wait_for(48_000_000, || {
            let elapsed = board.counter.elapsed_since(start);
            assert!(elapsed < GPT_CLOCK_HZ);
            elapsed != 0 && board.timer.interrupts() >= 20
        });
        board.timer.stop();
    }
}

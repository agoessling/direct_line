//! Board test for GPIO configuration, shared output handles, and pin isolation.

#[embedded_test::tests(default_timeout = 3)]
mod gpio {
    use crate::{device::Board, gpio::OutputPin};
    use cc1354p10_registers as r;

    fn output_levels() -> u32 {
        // SAFETY: Board has enabled GPIO; reading the output latch has no side effects.
        unsafe { r::GPIO.dout31_0.read().bits() }
    }

    fn require_sync<T: Sync>() {}

    #[test]
    fn output_levels_and_pin_isolation() {
        const RED: u32 = 1 << 6;
        const GREEN: u32 = 1 << 7;
        const LEDS: u32 = RED | GREEN;
        let board = Board::take().unwrap();
        require_sync::<OutputPin>();

        // Verify both LEDs are GPIO outputs with normal polarity, no pulls, inputs, or edge events.
        // SAFETY: board initialization is complete; this image only reads configuration registers.
        unsafe {
            for bits in [r::IOC.iocfg6.read().bits(), r::IOC.iocfg7.read().bits()] {
                let config = r::ioc::iocfg0::Value::from_bits(bits); // IOCFG fields share one layout.
                assert_eq!(config.port_id(), 0);
                assert_eq!(config.iomode(), 0);
                assert_eq!(config.pull_ctl(), 3);
                assert!(!config.ie());
                assert_eq!(config.edge_det(), 0);
                assert!(!config.edge_irq_en());
            }
            assert_eq!(r::GPIO.doe31_0.read().bits() & LEDS, LEDS);
            assert!(r::AON_PMCTL.sleepctl.read().io_pad_sleep_dis());
            assert!(r::AON_IOC.ioclatch.read().en());
        }

        // Both outputs start low; every subsequent operation must preserve unrelated output latches.
        let initial = output_levels();
        assert_eq!(initial & LEDS, 0);
        let untouched = initial & !LEDS;
        let red = &board.red_led;
        let shared_red = &board.red_led;
        let green = &board.green_led;

        for (red_high, green_high) in [(false, false), (false, true), (true, false), (true, true)] {
            let expected =
                untouched | if red_high { RED } else { 0 } | if green_high { GREEN } else { 0 };
            // Set either level twice to check idempotence, including use through shared references.
            let before = output_levels();
            green.set(green_high);
            assert_eq!(output_levels(), (before & !GREEN) | (expected & GREEN));
            red.set(red_high);
            assert_eq!(output_levels(), expected);
            shared_red.set(red_high);
            green.set(green_high);
            assert_eq!(output_levels(), expected);

            // Each toggle changes only its pin; a second toggle restores the preceding state.
            shared_red.toggle();
            assert_eq!(output_levels(), expected ^ RED);
            red.toggle();
            assert_eq!(output_levels(), expected);
            green.toggle();
            assert_eq!(output_levels(), expected ^ GREEN);
            green.toggle();
            assert_eq!(output_levels(), expected);
        }
    }
}

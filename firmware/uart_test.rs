#![no_std]
#![no_main]
//! Per-instance UART configuration and internal loopback checks; no external wiring required.
mod clock;
mod ddi;
mod interrupts;
mod ioc;
mod mmio;
mod poll;
#[expect(dead_code, reason = "this image does not enable the GPIO clock")]
mod prcm;
mod rtc;
mod setup;
mod startup;
#[expect(
    dead_code,
    reason = "this image uses a counter without arming interrupt timers"
)]
mod timer;
mod uart;

use cc1354p10_registers as r;
use core::arch::asm;
use core::sync::atomic::{AtomicU32, Ordering};
use poll::wait_for;
use timer::{Counter, GPT_CLOCK_HZ};
use uart::{Instance, Uart};

#[unsafe(no_mangle)]
static UART_TEST_RESULT: AtomicU32 = AtomicU32::new(0);

#[unsafe(no_mangle)]
pub extern "C" fn main() -> ! {
    let (instance, registers, baud, divisors, ports) = if cfg!(feature = "uart0") {
        (Instance::Uart0, &r::UART0, 9_600, (312, 32), (15, 16))
    } else if cfg!(feature = "uart1") {
        (Instance::Uart1, &r::UART1, 115_200, (26, 3), (19, 20))
    } else if cfg!(feature = "uart2") {
        (Instance::Uart2, &r::UART2, 1_000_000, (3, 0), (65, 66))
    } else {
        assert!(cfg!(feature = "uart3"));
        (Instance::Uart3, &r::UART3, 3_000_000, (1, 0), (69, 70))
    };

    // SAFETY: this image replaces Board initialization; startup still masks CPU interrupts.
    // GPT1 and the selected UART/pins are initialized once and remain powered.
    let (counter, mut uart) = unsafe {
        // Invalid requests must leave domain requests, clock gates, and pin routing untouched.
        // Do not read UART registers until the driver has powered the selected instance.
        let before = initialization_state();
        for invalid in [0, 45, 3_000_001, u32::MAX] {
            assert!(Uart::initialize(instance, 12, 13, invalid).is_err());
            assert_eq!(initialization_state(), before);
        }

        // Verify the constructor's domain selection before starting the test counter.
        let power_before = r::PRCM.pdstat0.read();
        let gates_before = r::PRCM.uartclkgr.read().clk_en();
        // Keep baud as a runtime input to exercise the integer division path.
        let uart = Uart::initialize(instance, 12, 13, core::hint::black_box(baud)).unwrap();
        let power = r::PRCM.pdstat0.read();
        assert_eq!(
            power.serial_on(),
            power_before.serial_on() || matches!(instance, Instance::Uart0)
        );
        assert_eq!(
            power.periph_on(),
            power_before.periph_on() || !matches!(instance, Instance::Uart0)
        );
        assert_eq!(
            r::PRCM.uartclkgr.read().clk_en(),
            gates_before | (1 << instance as u32)
        );
        prcm::initialize_timer_clock();
        let counter = Counter::initialize(timer::Instance::Gpt1);
        assert_eq!(registers.ibrd.read().divint(), divisors.0);
        assert_eq!(registers.fbrd.read().divfrac(), divisors.1);
        assert_eq!(r::IOC.iocfg12.read().port_id(), ports.0);
        assert_eq!(r::IOC.iocfg13.read().port_id(), ports.1);
        assert!(r::IOC.iocfg12.read().ie());
        assert!(!r::IOC.iocfg13.read().ie());
        assert_eq!(r::IOC.iocfg12.read().pull_ctl(), 3);
        assert_eq!(r::IOC.iocfg13.read().pull_ctl(), 3);
        assert_eq!(registers.lcrh.read().bits(), (3 << 5) | (1 << 4)); // 8N1 with FIFOs.
        assert_eq!(registers.imsc.read().bits(), 0);
        assert_eq!(registers.dmactl.read().bits(), 0);

        // Loopback must be selected while disabled (TRM SWCU194 §22.4.7).
        let mut control = registers.ctl.read();
        assert!(control.uarten() && control.rxe() && control.txe());
        control.set_uarten(false);
        registers.ctl.write(control);
        let mut format = registers.lcrh.read();
        format.set_fen(false); // Flush anything received from the external RX pin.
        registers.lcrh.write(format);
        format.set_fen(true);
        registers.lcrh.write(format);
        control.set_lbe(true);
        registers.ctl.write(control);
        control.set_uarten(true);
        registers.ctl.write(control);
        (counter, uart)
    };
    let mut clocks = clock::Clocks { _private: () };
    clocks.request_hf_crystal();
    wait_for(2_000_000, || clocks.hf_crystal_ready());
    wait_for(2_000_000, || clocks.try_switch_to_hf_crystal());

    // Empty RX is nonblocking; a zero timeout must not enqueue a byte.
    assert_eq!(uart.try_read(), Ok(None));
    assert_eq!(uart.write_timeout(&[0x55], &counter, 0), Err(uart::Timeout));

    // Exercise every byte value through the selected instance's TX and RX FIFOs.
    for byte in 0..=u8::MAX {
        uart.try_write(byte).unwrap();
        let start = counter.now();
        wait_for(GPT_CLOCK_HZ, || {
            assert!(counter.elapsed_since(start) < GPT_CLOCK_HZ);
            match uart.try_read().unwrap() {
                Some(received) => {
                    assert_eq!(received, byte);
                    true
                }
                None => false,
            }
        });
        assert_eq!(uart.try_read(), Ok(None));
    }

    UART_TEST_RESULT.store(0x5041_5353, Ordering::Relaxed);
    loop {
        // SAFETY: tests are complete; park for debugger inspection.
        unsafe { asm!("wfi", options(nomem, nostack)) };
    }
}

/// Safety: caller owns PRCM and DIO12/13 configuration after chip trim.
unsafe fn initialization_state() -> [u32; 4] {
    unsafe {
        [
            r::PRCM.pdctl0.read().bits(),
            r::PRCM.uartclkgr.read().bits(),
            r::IOC.iocfg12.read().bits(),
            r::IOC.iocfg13.read().bits(),
        ]
    }
}

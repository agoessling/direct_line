//! Polling UART0–UART3 with fixed 8N1 framing; board initialization selects pins and baud.
use crate::clock::HF_CLOCK_HZ;
use crate::ioc;
use crate::prcm;
use crate::timer::Counter;
use cc1354p10_registers as r;

/// Hardware identity, not an ownership token; initialization requires exclusive ownership.
#[derive(Clone, Copy)]
#[repr(u8)]
#[allow(dead_code)] // A board may select only one of the four UART instances.
pub(crate) enum Instance {
    Uart0,
    Uart1,
    Uart2,
    Uart3,
}

impl Instance {
    /// Power this UART's shared domain and wait until it is available.
    /// Panics if the polling budget is exhausted; the domain stays powered afterward.
    ///
    /// # Safety
    /// Caller must exclusively own PRCM configuration after chip trim, with interrupts masked.
    unsafe fn enable_power(self) {
        // SAFETY: caller serializes PRCM writes; UART0 uses SERIAL, UART1–3 use PERIPH
        // (TRM SWCU194 §7.8.1.43).
        unsafe {
            match self {
                Self::Uart0 => prcm::power_serial(),
                Self::Uart1 | Self::Uart2 | Self::Uart3 => prcm::power_periph(),
            }
        }
    }

    const fn registers(self) -> &'static r::uart::Peripheral {
        match self {
            Self::Uart0 => &r::UART0,
            Self::Uart1 => &r::UART1,
            Self::Uart2 => &r::UART2,
            Self::Uart3 => &r::UART3,
        }
    }

    const fn ports(self) -> (u32, u32) {
        match self {
            Self::Uart0 => (ioc::UART0_RX, ioc::UART0_TX),
            Self::Uart1 => (ioc::UART1_RX, ioc::UART1_TX),
            Self::Uart2 => (ioc::UART2_RX, ioc::UART2_TX),
            Self::Uart3 => (ioc::UART3_RX, ioc::UART3_TX),
        }
    }

    const fn clock_mask(self) -> u32 {
        1 << self as u32
    }
}

/// The requested baud is zero or outside the supported hardware divisor range.
#[derive(Debug, Eq, PartialEq)]
pub struct BaudError;

#[derive(Debug, Eq, PartialEq)]
pub struct WouldBlock;
#[derive(Debug, Eq, PartialEq)]
pub struct Timeout;
#[derive(Debug, Eq, PartialEq)]
pub struct RxError {
    pub framing: bool,
    pub parity: bool,
    pub break_detected: bool,
    pub overrun: bool,
}

pub struct Uart {
    registers: &'static r::uart::Peripheral,
}
impl Uart {
    /// Route and configure one UART at the nearest representable baud, with fixed 8N1 framing.
    /// Invalid baud returns `BaudError` before changing hardware; invalid pins panic.
    ///
    /// # Safety
    /// Caller must own this UART, both distinct DIO0–31 pins, and PRCM configuration after chip trim,
    /// with CPU interrupts masked. Initialize each instance at most once successfully
    /// per reset, while it is idle; rejected baud requests leave it uninitialized.
    /// Retain power and the nominal 48 MHz clock; release global I/O retention after configuring
    /// all board pins. No other handle or peripheral may use either pin.
    pub(crate) unsafe fn initialize(
        instance: Instance,
        rx_dio: usize,
        tx_dio: usize,
        baud: u32,
    ) -> Result<Self, BaudError> {
        let divisors = baud_divisors(baud).ok_or(BaudError)?;
        let rx_pin = ioc::config(rx_dio);
        let tx_pin = ioc::config(tx_dio);
        assert_ne!(rx_dio, tx_dio, "UART RX and TX need distinct pins");
        let (rx_port, tx_port) = instance.ports();
        let registers = instance.registers();

        // SAFETY: caller owns the UART and serializes PRCM and pin configuration.
        unsafe {
            instance.enable_power();
            prcm::enable_uart_clocks(instance.clock_mask());
            // Route pins before enabling UART; IOC selects their direction (TRM SWCU194 §22.6).
            let mut rx: r::ioc::iocfg0::Value = 0.into();
            rx.set_port_id(rx_port);
            rx.set_pull_ctl(ioc::NO_PULL);
            rx.set_ie(true);
            rx_pin.write(rx);
            let mut tx: r::ioc::iocfg0::Value = 0.into();
            tx.set_port_id(tx_port);
            tx.set_pull_ctl(ioc::NO_PULL);
            tx_pin.write(tx);
            configure_uart(registers, divisors);
        }
        Ok(Self { registers })
    }

    /// Enqueue one byte, or return `WouldBlock` if the transmit FIFO is full.
    #[inline]
    pub fn try_write(&mut self, byte: u8) -> Result<(), WouldBlock> {
        // SAFETY: this object owns the UART; no ISR or DMA accesses its FIFO.
        unsafe {
            if self.registers.fr.read().txff() {
                return Err(WouldBlock);
            }
            self.registers.dr.write(u32::from(byte).into());
        }
        Ok(())
    }

    /// Consume one received byte; an erroneous entry is consumed and its error flags returned.
    /// Returns `Ok(None)` if the receive FIFO is empty.
    #[inline]
    pub fn try_read(&mut self) -> Result<Option<u8>, RxError> {
        // SAFETY: this object owns the UART; DR read consumes one FIFO entry.
        unsafe {
            if self.registers.fr.read().rxfe() {
                return Ok(None);
            }
            let data = self.registers.dr.read();
            if data.fe() || data.pe() || data.be() || data.oe() {
                self.registers.ecr.write(0.into()); // Any write clears receive status (TRM §22.7.3).
                return Err(RxError {
                    framing: data.fe(),
                    parity: data.pe(),
                    break_detected: data.be(),
                    overrun: data.oe(),
                });
            }
            Ok(Some(data.data() as u8))
        }
    }

    /// Bound the entire enqueue operation by elapsed counter ticks. Success means
    /// bytes entered the FIFO, not that the final stop bit reached the wire.
    /// The timeout must be at most 2^31-1 ticks; larger values return Timeout.
    /// A timeout may leave a prefix enqueued. Requires a running counter and polling within one wrap.
    pub fn write_timeout(
        &mut self,
        bytes: &[u8],
        counter: &Counter,
        timeout_ticks: u32,
    ) -> Result<(), Timeout> {
        if timeout_ticks > i32::MAX as u32 {
            return Err(Timeout);
        }
        let start = counter.now();
        for &byte in bytes {
            loop {
                if counter.elapsed_since(start) >= timeout_ticks {
                    return Err(Timeout);
                }
                if self.try_write(byte).is_ok() {
                    break;
                }
                core::hint::spin_loop();
            }
        }
        Ok(())
    }
}

/// Safety: caller owns this idle UART with pins routed, power/clock enabled, and valid divisors.
unsafe fn configure_uart(registers: &r::uart::Peripheral, (integer, fraction): (u32, u32)) {
    const EIGHT_BITS: u32 = 3;
    // SAFETY: initialize owns this UART and validated the divisors before changing hardware.
    unsafe {
        registers.ctl.write(0.into()); // Disable before setting baud and format (TRM §22.6).
        registers.lcrh.write(0.into()); // Disable FIFOs while configuring.
        registers.dmactl.write(0.into()); // Polling owns the FIFOs; no DMA or interrupts.
        registers.imsc.write(0.into());
        registers.ibrd.write(integer.into());
        registers.fbrd.write(fraction.into());
        let mut format: r::uart::lcrh::Value = 0.into();
        format.set_wlen(EIGHT_BITS); // Eight data bits, no parity, one stop bit (§22.7.7).
        format.set_fen(true);
        registers.lcrh.write(format); // Commit both baud divisors with the format (§22.4.2).
        let mut control: r::uart::ctl::Value = 0.into();
        control.set_rxe(true);
        control.set_txe(true);
        control.set_uarten(true);
        registers.ctl.write(control);
    }
}

const fn baud_divisors(baud: u32) -> Option<(u32, u32)> {
    if baud == 0 || baud > HF_CLOCK_HZ / 16 {
        return None;
    }
    // Divisor = clock/(16*baud), with six fractional bits (TRM §22.4.2).
    // Round the combined value so fractional carry reaches the integer part.
    // At 48 MHz the numerator fits u32 even for the largest u32 baud input.
    let scaled = (HF_CLOCK_HZ * 4 + baud / 2) / baud;
    let integer = scaled / 64;
    let fraction = scaled % 64;
    // The permitted divisor range is 1 through 65535, inclusive (§22.7.5–22.7.6).
    if integer == 0 || integer > 65535 || (integer == 65535 && fraction != 0) {
        None
    } else {
        Some((integer, fraction))
    }
}

// Check fractional carry and invalid divisors at build time without executing MMIO on the host.
const _: () = {
    assert!(matches!(baud_divisors(115_200), Some((26, 3))));
    assert!(matches!(baud_divisors(9_600), Some((312, 32))));
    assert!(matches!(baud_divisors(1_500_001), Some((2, 0))));
    assert!(matches!(baud_divisors(46), Some((65217, 25))));
    assert!(matches!(baud_divisors(3_000_000), Some((1, 0))));
    assert!(baud_divisors(0).is_none());
    assert!(baud_divisors(45).is_none());
    assert!(baud_divisors(3_000_001).is_none());
    assert!(baud_divisors(u32::MAX).is_none());
};

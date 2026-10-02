//! Shared IOC register lookup and field encodings for DIO0–31.
#![allow(dead_code)] // Keep the hardware encodings available as drivers are added.

use cc1354p10_registers as r;

/// Release global pad and latch retention after configuring every board pin.
///
/// # Safety
/// Caller must own AON I/O configuration with interrupts masked. All pins must have their intended
/// configuration and output levels; releasing retention exposes them at the pads.
pub(crate) unsafe fn release_retention() {
    // SAFETY: caller has restored all pins before releasing the shared retention controls.
    unsafe {
        // Pad sleep remains enabled after shutdown until software restores pins (TRM §7.8.2.10).
        let mut sleep = r::AON_PMCTL.sleepctl.read();
        sleep.set_io_pad_sleep_dis(true);
        r::AON_PMCTL.sleepctl.write(sleep);
        // Open the I/O latches frozen before retained powerdown (§15.10.1.4).
        let mut latch: r::aon_ioc::ioclatch::Value = 0.into();
        latch.set_en(true);
        r::AON_IOC.ioclatch.write(latch);
    }
}

// IOCFG.PORT_ID signal selections (TRM SWCU194 §15.10.3.1).
pub(crate) const GPIO: u32 = 0;
pub(crate) const AON_CLK32K: u32 = 7;
pub(crate) const AUX_IO: u32 = 8;

pub(crate) const SPI0_RX: u32 = 9;
pub(crate) const SPI0_TX: u32 = 10;
pub(crate) const SPI0_CS: u32 = 11;
pub(crate) const SPI0_CLK: u32 = 12;
pub(crate) const I2C0_MSSDA: u32 = 13;
pub(crate) const I2C0_MSSCL: u32 = 14;
pub(crate) const UART0_RX: u32 = 15;
pub(crate) const UART0_TX: u32 = 16;
pub(crate) const UART0_CTS: u32 = 17;
pub(crate) const UART0_RTS: u32 = 18;
pub(crate) const UART1_RX: u32 = 19;
pub(crate) const UART1_TX: u32 = 20;
pub(crate) const UART1_CTS: u32 = 21;
pub(crate) const UART1_RTS: u32 = 22;

// General-purpose I/O events routed through the EVENT module, including GPT capture inputs.
pub(crate) const PORT_EVENT0: u32 = 23;
pub(crate) const PORT_EVENT1: u32 = 24;
pub(crate) const PORT_EVENT2: u32 = 25;
pub(crate) const PORT_EVENT3: u32 = 26;
pub(crate) const PORT_EVENT4: u32 = 27;
pub(crate) const PORT_EVENT5: u32 = 28;
pub(crate) const PORT_EVENT6: u32 = 29;
pub(crate) const PORT_EVENT7: u32 = 30;

pub(crate) const CPU_SWV: u32 = 32;
pub(crate) const SPI1_RX: u32 = 33;
pub(crate) const SPI1_TX: u32 = 34;
pub(crate) const SPI1_CS: u32 = 35;
pub(crate) const SPI1_CLK: u32 = 36;
pub(crate) const I2S_AD0: u32 = 37;
pub(crate) const I2S_AD1: u32 = 38;
pub(crate) const I2S_WCLK: u32 = 39;
pub(crate) const I2S_BCLK: u32 = 40;
pub(crate) const I2S_MCLK: u32 = 41;

pub(crate) const RFC_TRC: u32 = 46;
pub(crate) const RFC_GPO0: u32 = 47;
pub(crate) const RFC_GPO1: u32 = 48;
pub(crate) const RFC_GPO2: u32 = 49;
pub(crate) const RFC_GPO3: u32 = 50;
pub(crate) const RFC_GPI0: u32 = 51;
pub(crate) const RFC_GPI1: u32 = 52;
pub(crate) const RFC_SMI_DL_OUT: u32 = 53;
pub(crate) const RFC_SMI_DL_IN: u32 = 54;
pub(crate) const RFC_SMI_CL_OUT: u32 = 55;
pub(crate) const RFC_SMI_CL_IN: u32 = 56;

pub(crate) const SPI2_RX: u32 = 57;
pub(crate) const SPI2_TX: u32 = 58;
pub(crate) const SPI2_CS: u32 = 59;
pub(crate) const SPI2_CLK: u32 = 60;
pub(crate) const SPI3_RX: u32 = 61;
pub(crate) const SPI3_TX: u32 = 62;
pub(crate) const SPI3_CS: u32 = 63;
pub(crate) const SPI3_CLK: u32 = 64;
pub(crate) const UART2_RX: u32 = 65;
pub(crate) const UART2_TX: u32 = 66;
pub(crate) const UART2_CTS: u32 = 67;
pub(crate) const UART2_RTS: u32 = 68;
pub(crate) const UART3_RX: u32 = 69;
pub(crate) const UART3_TX: u32 = 70;
pub(crate) const UART3_CTS: u32 = 71;
pub(crate) const UART3_RTS: u32 = 72;
pub(crate) const I2C1_MSSDA: u32 = 73;
pub(crate) const I2C1_MSSCL: u32 = 74;

// IOCFG.PULL_CTL.
pub(crate) const PULL_DOWN: u32 = 1;
pub(crate) const PULL_UP: u32 = 2;
pub(crate) const NO_PULL: u32 = 3;

// IOCFG.IOMODE; AON/AUX signals use their own mode controls.
pub(crate) const MODE_NORMAL: u32 = 0;
pub(crate) const MODE_INVERTED: u32 = 1;
pub(crate) const MODE_OPEN_DRAIN: u32 = 4;
pub(crate) const MODE_OPEN_DRAIN_INVERTED: u32 = 5;
pub(crate) const MODE_OPEN_SOURCE: u32 = 6;
pub(crate) const MODE_OPEN_SOURCE_INVERTED: u32 = 7;

// IOCFG.EDGE_DET.
pub(crate) const EDGE_NONE: u32 = 0;
pub(crate) const EDGE_FALLING: u32 = 1;
pub(crate) const EDGE_RISING: u32 = 2;
pub(crate) const EDGE_BOTH: u32 = 3;

// IOCFG.IOCURR current modes; available drive also depends on the pin and IOSTR selection.
pub(crate) const CURRENT_LOW: u32 = 0;
pub(crate) const CURRENT_HIGH: u32 = 1;
pub(crate) const CURRENT_EXTENDED: u32 = 2;

// IOCFG.IOSTR: AUTO follows battery voltage; manual settings select AON_IOC drive-strength controls.
pub(crate) const DRIVE_AUTO: u32 = 0;
pub(crate) const DRIVE_MIN: u32 = 1;
pub(crate) const DRIVE_MED: u32 = 2;
pub(crate) const DRIVE_MAX: u32 = 3;

// IOCFG.WU_CFG shutdown wake: LOW/HIGH select polarity for GPIO and non-AON peripheral signals.
// For AON/AUX signals either enables wake; AON registers select polarity. Wake disables output drive.
// Encoding 1 also disables wake; use 0 consistently.
pub(crate) const WAKE_DISABLED: u32 = 0;
pub(crate) const WAKE_LOW: u32 = 2;
pub(crate) const WAKE_HIGH: u32 = 3;

/// Return a pin's configuration accessor; panics outside the supported DIO0–31 range.
/// No hardware is accessed here. Reads/writes require the caller to satisfy their unsafe contracts.
pub(crate) const fn config(dio: usize) -> r::ioc::iocfg0::Register {
    assert!(dio < 32, "only DIO0–31 are supported");
    const IOCFG_STRIDE: usize = 4;
    // IOCFG registers share one layout and are spaced four bytes apart.
    r::ioc::iocfg0::Register::at(r::IOC.iocfg0.address() + dio * IOCFG_STRIDE)
}

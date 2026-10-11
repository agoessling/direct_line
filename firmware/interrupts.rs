//! CC1354P10 peripheral IRQ indices, excluding the 16 core vectors (TRM Table 5-2).
//! Names follow the pinned SDK's cc13x4_cc26x4/inc/hw_ints.h, without the INT_ prefix.
//! All 47 peripheral slots are assigned; there are no reserved gaps.
//! Shared NVIC configuration for these peripheral interrupts lives here.

#![allow(dead_code)] // Keep the complete hardware map as drivers are added.

use cc1354p10_registers as r;

pub(crate) const AON_GPIO_EDGE: usize = 0;
pub(crate) const I2C_IRQ: usize = 1;
pub(crate) const RFC_CPE_1: usize = 2;
pub(crate) const PKA_IRQ: usize = 3;
pub(crate) const AON_RTC_COMB: usize = 4;
pub(crate) const UART0_COMB: usize = 5;
pub(crate) const AUX_SWEV0: usize = 6;
pub(crate) const SPI0_COMB: usize = 7;
pub(crate) const SPI1_COMB: usize = 8;
pub(crate) const RFC_CPE_0: usize = 9;
pub(crate) const RFC_HW_COMB: usize = 10;
pub(crate) const RFC_CMD_ACK: usize = 11;
pub(crate) const I2S_IRQ: usize = 12;
pub(crate) const AUX_SWEV1: usize = 13;
pub(crate) const WDT_IRQ: usize = 14;
pub(crate) const GPT0A: usize = 15;
pub(crate) const GPT0B: usize = 16;
pub(crate) const GPT1A: usize = 17;
pub(crate) const GPT1B: usize = 18;
pub(crate) const GPT2A: usize = 19;
pub(crate) const GPT2B: usize = 20;
pub(crate) const GPT3A: usize = 21;
pub(crate) const GPT3B: usize = 22;
pub(crate) const CRYPTO_RESULT_AVAIL_IRQ: usize = 23;
pub(crate) const DMA_DONE_COMB: usize = 24;
pub(crate) const DMA_ERR: usize = 25;
pub(crate) const FLASH: usize = 26;
pub(crate) const SWEV0: usize = 27;
pub(crate) const AUX_COMB: usize = 28;
pub(crate) const AON_PROG0: usize = 29;
pub(crate) const PROG0: usize = 30;
pub(crate) const AUX_COMPA: usize = 31;
pub(crate) const AUX_ADC_IRQ: usize = 32;
pub(crate) const TRNG_IRQ: usize = 33;
pub(crate) const OSC_COMB: usize = 34;
pub(crate) const AUX_TIMER2_EV0: usize = 35;
pub(crate) const UART1_COMB: usize = 36;
pub(crate) const BATMON_COMB: usize = 37;
pub(crate) const SPI2_COMB: usize = 38;
pub(crate) const SPI3_COMB: usize = 39;
pub(crate) const UART2_COMB: usize = 40;
pub(crate) const UART3_COMB: usize = 41;
pub(crate) const I2C1_IRQ: usize = 42;
pub(crate) const SWEV1: usize = 43;
pub(crate) const SWEV2: usize = 44;
pub(crate) const SWEV3: usize = 45;
pub(crate) const SWEV4: usize = 46;

/// Set a peripheral IRQ's priority from 0 (highest) to 7 (lowest).
/// Panics if the IRQ or priority is out of range.
///
/// # Safety
/// Caller must own this IRQ's configuration and mask CPU interrupts to serialize the shared
/// priority-register read-modify-write during initialization.
#[inline]
pub(crate) unsafe fn set_priority(irq: usize, priority: u32) {
    const IRQ_COUNT: usize = SWEV4 + 1;
    const PRIORITY_LEVELS: u32 = 8;
    assert!(irq < IRQ_COUNT, "peripheral IRQ out of range");
    assert!(
        priority < PRIORITY_LEVELS,
        "interrupt priority out of range"
    );

    // SAFETY: indices are checked; caller serializes access to the containing IPR word.
    unsafe {
        // IPR words hold four IRQ priorities in bytes; each priority uses its top three bits.
        let register = r::cpu_nvic::ipr0::Register::at(r::CPU_NVIC.ipr0.address() + (irq / 4) * 4);
        let shift = (irq % 4) * 8;
        let bits = (register.read().bits() & !(0xff << shift)) | ((priority << 5) << shift);
        register.write(bits.into());
    }
}

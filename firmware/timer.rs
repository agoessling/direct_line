//! Free-running counters and periodic/one-shot timers on GPT0–GPT3.
use crate::interrupts;
use cc1354p10_registers as r;
use core::arch::asm;
use core::sync::atomic::{AtomicU32, Ordering};

/// Nominal GPT frequency with the undivided clock configured by PRCM.
pub const GPT_CLOCK_HZ: u32 = crate::clock::HF_CLOCK_HZ;

/// Convert microseconds to GPT ticks, returning `None` if the count exceeds 32 bits.
pub const fn ticks_from_us(microseconds: u32) -> Option<u32> {
    microseconds.checked_mul(GPT_CLOCK_HZ / 1_000_000)
}

static TIMER_INTERRUPTS: [AtomicU32; 4] = [const { AtomicU32::new(0) }; 4];

/// Hardware identity, not an ownership token; constructors require exclusive ownership.
#[derive(Clone, Copy)]
#[repr(u8)]
pub(crate) enum Instance {
    Gpt0,
    Gpt1,
    Gpt2,
    Gpt3,
}

impl Instance {
    const fn registers(self) -> &'static r::gpt::Peripheral {
        match self {
            Self::Gpt0 => &r::GPT0,
            Self::Gpt1 => &r::GPT1,
            Self::Gpt2 => &r::GPT2,
            Self::Gpt3 => &r::GPT3,
        }
    }

    const fn irq(self) -> usize {
        match self {
            Self::Gpt0 => interrupts::GPT0A,
            Self::Gpt1 => interrupts::GPT1A,
            Self::Gpt2 => interrupts::GPT2A,
            Self::Gpt3 => interrupts::GPT3A,
        }
    }

    pub(crate) const fn clock_mask(self) -> u32 {
        1 << self as u32
    }
}

pub struct Counter {
    value: r::gpt::tav::Register,
}

impl Counter {
    /// Start this GPT as a free-running 32-bit up-counter.
    ///
    /// # Safety
    /// Caller must exclusively own the GPT with its clock enabled and CPU interrupts masked.
    /// Call once per reset; retain PERIPH power and the undivided 48 MHz timer clock.
    pub(crate) unsafe fn initialize(instance: Instance) -> Self {
        let registers = instance.registers();
        // SAFETY: caller owns the powered timer during board initialization.
        unsafe {
            // Disable both halves before changing configuration (TRM SWCU194, §17.4.1).
            registers.ctl.write(0.into());
            registers.cfg.write(0.into()); // Join A/B into one 32-bit timer (§17.5.1).
            registers.imr.write(0.into()); // Polled counter; no interrupts (§17.5.6).
            registers.iclr.write((1 << 0).into()); // Clear the timeout latch, W1C (§17.5.9).

            // Periodic up-counting restarts at zero on timeout (§17.3.2.1).
            const PERIODIC: u32 = 2;
            // Leave snapshot, match interrupt, and trigger-wait disabled (§17.5.2).
            let mut mode: r::gpt::tamr::Value = 0.into();
            mode.set_tamr(PERIODIC);
            mode.set_tacdir(true);
            registers.tamr.write(mode);
            // Maximum timeout gives a full 2^32-tick wrap; start at zero (§17.5.10, §17.5.20).
            registers.tailr.write(u32::MAX.into());
            registers.tav.write(0.into());
            // Enable A; TASTALL=0 keeps it counting through debugger halts (§17.5.4).
            registers.ctl.write((1 << 0).into());
        }
        Self {
            value: registers.tav,
        }
    }

    /// Ticks modulo 2^32, nominally 48 MHz; wraps about every 89.5 seconds.
    #[inline]
    pub fn now(&self) -> u32 {
        // SAFETY: counter clock is enabled once and never disabled or reconfigured.
        unsafe { self.value.read().bits() }
    }

    /// Valid as elapsed time only if fewer than 2^32 ticks passed since `start`.
    #[inline]
    pub fn elapsed_since(&self, start: u32) -> u32 {
        self.now().wrapping_sub(start)
    }
}

pub struct Timer {
    registers: &'static r::gpt::Peripheral,
    irq_mask: u32,
    count: &'static AtomicU32,
}

/// The requested interval is zero or exceeds the 32-bit timer's range.
#[derive(Debug, Eq, PartialEq)]
pub struct TimerError;

impl Timer {
    /// Leave this GPT stopped, with its interrupt disabled and priority set to 2 of 8.
    ///
    /// # Safety
    /// Caller must exclusively own the GPT and its NVIC configuration with its clock enabled
    /// and CPU interrupts masked. Call once per reset; retain PERIPH power and the undivided
    /// 48 MHz timer clock. The matching Timer A handler must be installed in the vector table.
    pub(crate) unsafe fn initialize(instance: Instance) -> Self {
        let irq = instance.irq();
        let mut timer = Self {
            registers: instance.registers(),
            irq_mask: 1 << irq, // All four GPT A IRQs are in NVIC bank 0.
            count: &TIMER_INTERRUPTS[instance as usize],
        };
        timer.stop();
        // SAFETY: board initialization serializes the shared four-priority NVIC register.
        unsafe { interrupts::set_priority(irq, 2) };
        timer
    }

    /// Replace the current interval; an invalid request leaves it unchanged.
    pub fn start_periodic_us(&mut self, microseconds: u32) -> Result<(), TimerError> {
        const PERIODIC: u32 = 2;
        self.arm(microseconds, PERIODIC)
    }

    /// Arm a single timeout; an invalid request leaves the current interval unchanged.
    pub fn start_once_us(&mut self, microseconds: u32) -> Result<(), TimerError> {
        const ONE_SHOT: u32 = 1;
        self.arm(microseconds, ONE_SHOT)
    }

    fn arm(&mut self, microseconds: u32, mode: u32) -> Result<(), TimerError> {
        let ticks = ticks_from_us(microseconds)
            .filter(|&ticks| ticks != 0)
            .ok_or(TimerError)?;
        self.stop();
        // SAFETY: owns this GPT; its NVIC IRQ is disabled while reconfiguring.
        unsafe {
            self.registers.cfg.write(0.into()); // Concatenated 32-bit timer.
            let mut config: r::gpt::tamr::Value = 0.into();
            config.set_tamr(mode);
            config.set_taild(true);
            self.registers.tamr.write(config);
            self.registers.tailr.write((ticks - 1).into());
            self.registers.imr.write((1 << 0).into()); // Timer A timeout.
            r::CPU_NVIC.iser0.write(self.irq_mask.into());
            self.registers.ctl.write((1 << 0).into()); // TAEN.
        }
        Ok(())
    }

    /// Stop counting and discard any pending timeout, preserving the acknowledgement count.
    pub fn stop(&mut self) {
        // SAFETY: owns this GPT; mask its ISR before touching shared status registers.
        unsafe {
            // Disable this NVIC source without masking unrelated interrupts.
            r::CPU_NVIC.icer0.write(self.irq_mask.into());
            // DSB completes the write; ISB synchronizes the pipeline with the disabled IRQ.
            // Arm DAI0321A §4.6; also used by CMSIS Cortex-M33 DisableIRQ.
            asm!("dsb", "isb", options(nostack, preserves_flags));
            self.registers.ctl.write(0.into()); // Stop counting (TRM §17.5.4).
            self.registers.imr.write(0.into()); // Mask peripheral interrupt sources (§17.5.6).
            // Clear the timeout at its source and allow deassertion to propagate.
            clear_timeout(self.registers);
            // Discard the NVIC's latched request after clearing the peripheral source.
            r::CPU_NVIC.icpr0.write(self.irq_mask.into());
        }
    }

    /// Acknowledged timeouts modulo 2^32; stopping/rearming preserves the count.
    /// Multiple hardware timeouts can coalesce while interrupts are masked.
    #[inline]
    pub fn interrupts(&self) -> u32 {
        self.count.load(Ordering::Relaxed)
    }
}

/// Caller owns acknowledgement of this powered GPT's timeout source.
#[inline]
unsafe fn clear_timeout(registers: &r::gpt::Peripheral) {
    // SAFETY: caller serializes access with the ISR or is the ISR itself.
    unsafe {
        registers.iclr.write((1 << 0).into());
        // TI TimerIntClear: read the source module, then allow two cycles for IRQ propagation.
        let _ = registers.mis.read();
        asm!("nop", "nop", options(nostack, preserves_flags));
    }
}

/// Enter only from the matching Timer A vector after initialization.
#[inline]
unsafe fn interrupt(instance: Instance) {
    // SAFETY: this ISR owns acknowledgement while enabled; reconfiguration masks its IRQ.
    unsafe { clear_timeout(instance.registers()) };
    // Each vector updates only its own count; no borrowed payload or other memory is published.
    TIMER_INTERRUPTS[instance as usize].fetch_add(1, Ordering::Relaxed);
}

// Each entry requires hardware exception entry for its initialized GPT.
pub(crate) unsafe extern "C" fn timer0_a() {
    unsafe { interrupt(Instance::Gpt0) };
}
pub(crate) unsafe extern "C" fn timer1_a() {
    unsafe { interrupt(Instance::Gpt1) };
}
pub(crate) unsafe extern "C" fn timer2_a() {
    unsafe { interrupt(Instance::Gpt2) };
}
pub(crate) unsafe extern "C" fn timer3_a() {
    unsafe { interrupt(Instance::Gpt3) };
}

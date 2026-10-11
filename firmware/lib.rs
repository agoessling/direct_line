#![no_std]
//! Concrete CC1354P10 board support. Raw registers stay inside this crate.

mod clock;
mod ddi;
mod device;
mod gpio;
mod interrupts;
mod mmio;
mod poll;
mod prcm;
mod rtc;
mod setup;
mod startup;
mod timer;

pub use clock::Clocks;
pub use device::Board;
pub use gpio::OutputPin;
pub use timer::{Counter, GPT_CLOCK_HZ, Timer, TimerError, ticks_from_us};

#![no_std]
//! Concrete CC1354P10 board support. Raw registers stay inside this crate.

mod clock;
mod ddi;
mod device;
mod gpio;
mod mmio;
mod poll;
mod prcm;
mod rtc;
mod setup;
mod startup;

pub use clock::Clocks;
pub use device::Board;
pub use gpio::OutputPin;

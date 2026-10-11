//! Fixed push-pull GPIO outputs, configured during board initialization.
use cc1354p10_registers as r;

/// Configure DIO0–31 as a push-pull output, initially low.
///
/// # Safety
/// GPIO power and its run-mode clock must be enabled. Caller must own this pin and serialize IOC/GPIO
/// configuration with interrupts masked. No existing handle or peripheral may use this pin.
/// Keep the pin configuration and GPIO power/clock available for the handle's lifetime.
pub(crate) unsafe fn configure_output(dio: usize) -> OutputPin {
    assert!(dio < 32, "only GPIO bank 0 is supported");
    let mask = 1 << dio;
    const NO_PULL: u32 = 3;
    const IOCFG_STRIDE: usize = 4;

    // IOCFG registers share one layout and are spaced four bytes apart.
    let config = r::ioc::iocfg0::Register::at(r::IOC.iocfg0.address() + dio * IOCFG_STRIDE);
    // Zero selects GPIO, normal polarity and slew rate, and automatic 2 mA drive.
    // Input, edge detection, interrupts, wakeup, and hysteresis remain disabled.
    let mut value: r::ioc::iocfg0::Value = 0.into();
    value.set_pull_ctl(NO_PULL);

    // SAFETY: caller owns pin configuration; shared output-enable RMW is serialized at startup.
    unsafe {
        r::GPIO.doutclr31_0.write(mask.into()); // Load the initial level before enabling output.
        config.write(value);
        r::GPIO
            .doe31_0
            .write((r::GPIO.doe31_0.read().bits() | mask).into());
    }
    OutputPin { mask }
}

/// A configured push-pull output. Shared references may change its level concurrently.
/// Operations affect only this pin; callers coordinate any required sequence on the same pin.
/// Configuration stays fixed, and dropping the handle leaves the hardware unchanged.
pub struct OutputPin {
    mask: u32,
}
impl OutputPin {
    /// Drive high or low with one hardware set/clear write.
    #[inline]
    pub fn set(&self, high: bool) {
        // SAFETY: configuration is fixed; set/clear aliases affect only this pin and permit sharing.
        unsafe {
            if high {
                r::GPIO.doutset31_0.write(self.mask.into());
            } else {
                r::GPIO.doutclr31_0.write(self.mask.into());
            }
        }
    }

    /// Invert the output latch with one hardware toggle write.
    #[inline]
    pub fn toggle(&self) {
        // SAFETY: configuration is fixed; the toggle alias atomically changes only this pin.
        unsafe {
            r::GPIO.douttgl31_0.write(self.mask.into());
        }
    }
}

//! Fixed push-pull GPIO outputs, configured during board initialization.
use crate::ioc;
use crate::prcm;
use cc1354p10_registers as r;

/// Configure DIO0–31 as a push-pull output, initially low.
///
/// # Safety
/// Caller must own this pin and serialize PRCM/IOC/GPIO configuration after chip trim with
/// interrupts masked. No existing handle or peripheral may use this pin.
/// Keep the pin configuration and GPIO power/clock available for the handle's lifetime.
/// Release global I/O retention only after all board pins have been configured.
pub(crate) unsafe fn configure_output(dio: usize) -> OutputPin {
    let config = ioc::config(dio);
    let mask = 1 << dio;
    // Zero selects normal polarity and slew rate, and automatic 2 mA drive.
    // Input, edge detection, interrupts, wakeup, and hysteresis remain disabled.
    let mut value: r::ioc::iocfg0::Value = 0.into();
    value.set_port_id(ioc::GPIO);
    value.set_pull_ctl(ioc::NO_PULL);

    // SAFETY: caller owns pin configuration; shared output-enable RMW is serialized at startup.
    unsafe {
        prcm::power_periph();
        prcm::enable_gpio_clock();
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

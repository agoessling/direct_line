//! Raw architectural and analog-register access, private to hardware support.

/// Caller must own a mapped, aligned register supporting this 32-bit write.
#[inline(always)]
pub(crate) unsafe fn write32(address: usize, value: u32) {
    unsafe { core::ptr::write_volatile(address as *mut u32, value) }
}

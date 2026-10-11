//! TI DDI bit operations. See SDK inc/hw_ddi.h for the SET/CLR address windows and
//! driverlib/ddi.h for DDI32BitsSet/Clear. Each write updates only the selected bits in hardware.
use crate::mmio::write32;

/// Set the selected register bits.
/// Safety: register must be a valid DDI direct-access address supporting a 32-bit SET write;
/// the caller owns the selected fields and must follow the peripheral's configuration sequence.
#[inline(always)]
pub(crate) unsafe fn set_bits(register: usize, bits: u32) {
    const SET: usize = 0x80;
    unsafe { write32(register + SET, bits) };
}

/// Clear the selected register bits.
/// Safety: register must be a valid DDI direct-access address supporting a 32-bit CLR write;
/// the caller owns the selected fields and must follow the peripheral's configuration sequence.
#[inline(always)]
pub(crate) unsafe fn clear_bits(register: usize, bits: u32) {
    const CLR: usize = 0x100;
    unsafe { write32(register + CLR, bits) };
}

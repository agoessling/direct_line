#![no_std]
#![no_main]

unsafe extern "C" {
    fn direct_line_c_add(left: f32, right: f32) -> f32;
}

#[unsafe(no_mangle)]
pub extern "C" fn ffi_link_check() -> ! {
    // SAFETY: the C function is pure arithmetic with the matching hard-float ABI.
    let result = unsafe { direct_line_c_add(1.25, 2.5) };
    assert!(result == 3.75);
    loop {
        core::hint::spin_loop();
    }
}

#[panic_handler]
fn panic(_: &core::panic::PanicInfo<'_>) -> ! {
    loop {
        core::hint::spin_loop();
    }
}

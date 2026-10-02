ENTRY(ffi_link_check)
SECTIONS {
    . = 0;
    .text : { *(.text*) }
    .rodata : { *(.rodata*) }
    .ARM.exidx : { *(.ARM.exidx*) }
    .data : { *(.data*) }
    .bss : { *(.bss*) }
}

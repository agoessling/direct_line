ENTRY(ResetHandler)

STACK_SIZE = 4K;

MEMORY {
  FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 1M
  CCFG (r) : ORIGIN = 0x50000000, LENGTH = 2K
  SRAM (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
}

/* Section starts and ends are word aligned to allow for word copies.
 * Specifying ALIGN_WITH_INPUT and . = ALIGN(4) is the only way to ensure minimum VMA and LMA
 * alignment */
SECTIONS {
  .isr_vector : ALIGN_WITH_INPUT {
    . = ALIGN(4);
    KEEP(*(.isr_vector))  /* Interrupt vector table */
  } >FLASH

  .text : ALIGN_WITH_INPUT {
    . = ALIGN(4);
    *(.text)
    *(.text*)
  } >FLASH

  .rodata : ALIGN_WITH_INPUT {
    . = ALIGN(4);
    *(.rodata)
    *(.rodata*)
  } >FLASH

  .ARM : ALIGN_WITH_INPUT {
    . = ALIGN(4);
    *(.ARM.exidx*)  /* Used for stack unwinding. */
  } >FLASH

  /* Used by __libc_init_array() for constructors and destructors. */
  .preinit_array : ALIGN_WITH_INPUT {
    . = ALIGN(4);
    __preinit_array_start = .;
    KEEP(*(.preinit_array*))
    __preinit_array_end = .;
  } >FLASH

  .init_array : ALIGN_WITH_INPUT {
    . = ALIGN(4);
    __init_array_start = .;
    KEEP(*(SORT(.init_array.*)))
    KEEP(*(.init_array*))
    __init_array_end = .;
  } >FLASH

  .fini_array : ALIGN_WITH_INPUT {
    . = ALIGN(4);
    __fini_array_start = .;
    KEEP(*(SORT(.fini_array.*)))
    KEEP(*(.fini_array*))
    __fini_array_end = .;
  } >FLASH

  .ccfg : {
    KEEP(*(.ccfg))
  } >CCFG

  /* Stack is allocated at beginning of RAM so a stack overflow will generate a fault. */
  .stack (NOLOAD) : ALIGN(8) {
    . += STACK_SIZE;
    . = ALIGN(8);  /* Stack start (end of memory segment) should be 8 byte aligned. */
    _estack = .;
  } >SRAM

  .data : ALIGN_WITH_INPUT {
    . = ALIGN(4);
    _sdata = .;
    *(.data)
    *(.data*)
    . = ALIGN(4);
    _edata = .;
  } >SRAM AT >FLASH
  _sidata = LOADADDR(.data);

  .bss (NOLOAD) : ALIGN(4) {
    _sbss = .;
    *(.bss)
    *(.bss*)
    *(COMMON)
    . = ALIGN(4);
    _ebss = .;
  } >SRAM

  /* Necessary for TI Driverlib interrupt library (unused). */
  .ramVecs (NOLOAD) : ALIGN_WITH_INPUT {
    KEEP(*(.ramVecs))
  } >SRAM

  /* Catch and error on any unassigned input sections. */
  .orphan (NOLOAD) : {
    INPUT_SECTION_FLAGS(SHF_ALLOC) *(*)
  }
  ASSERT(SIZEOF(.orphan) == 0, "Unassigned input sections!")
}

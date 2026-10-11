ENTRY(Reset)
MEMORY {
  /* One secure-state application uses the full flash; see config/board.syscfg and startup.rs. */
  FLASH (rx) : ORIGIN = 0x00000000, LENGTH = 1M
  CCFG (r) : ORIGIN = 0x50000000, LENGTH = 2K
  SRAM (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
}
SECTIONS {
  .vectors : ALIGN(256) { KEEP(*(.vectors)) } > FLASH
  .text : ALIGN(4) { *(.text .text.*) } > FLASH
  .rodata : ALIGN(4) { *(.rodata .rodata.*) } > FLASH
  .ccfg : ALIGN(4) { KEEP(*(.ccfg)) } > CCFG
  /* An independent emergency stack lets faults report main-stack exhaustion. */
  .fault_stack (NOLOAD) : ALIGN(8) {
    . += 512;
    _fault_stack_top = .;
  } > SRAM
  .stack (NOLOAD) : ALIGN(8) {
    _stack_bottom = .;
    . += 8K;
    _stack_top = .;
  } > SRAM
  .data : ALIGN(4) {
    _sdata = .;
    *(.data .data.*);
    . = ALIGN(4);
    _edata = .;
  } > SRAM AT > FLASH
  _sidata = LOADADDR(.data);
  .bss (NOLOAD) : ALIGN(4) {
    _sbss = .;
    *(.bss .bss.*);
    . = ALIGN(4);
    _ebss = .;
  } > SRAM
  .diagnostic (NOLOAD) : ALIGN(4) { KEEP(*(.diagnostic)) } > SRAM
  /DISCARD/ : {
    *(.comment) *(.note .note.*)
    /* No runtime unwinding (panic=abort). Keep DWARF for debugger backtraces. */
    *(.ARM.exidx .ARM.exidx.*) *(.ARM.extab .ARM.extab.*)
  }
  .orphan (NOLOAD) : { INPUT_SECTION_FLAGS(SHF_ALLOC) *(*) }
  ASSERT(SIZEOF(.orphan) == 0, "Unexpected allocated input section")
  ASSERT(SIZEOF(.vectors) == 252, "Expected 16 core and 47 peripheral vectors")
  ASSERT(SIZEOF(.ccfg) == 124, "CCFG must match the x4 31-word layout")
  ASSERT((_stack_top & 7) == 0, "Stack must be eight-byte aligned")
}

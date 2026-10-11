//! Reset owns the CPU and peripherals until it calls the application.
//!
//! References: TI CC13x4/CC26x4 TRM SWCU194 (https://www.ti.com/lit/pdf/swcu194)
//! and Arm Cortex-M33 Devices Generic User Guide 100235_0100_01, section 4.6.6
//! (https://documentation-service.arm.com/static/5f16e93d20b7cf4bc524af1d).
use cc1354p10_registers as r;
use core::arch::{asm, global_asm};
use core::panic::PanicInfo;

// CPACR is absent from TI's register XML; Arm 100235_0100_01, section 4.6.6.
const CPACR_ADDRESS: usize = 0xe000_ed88;

// Handlers use the Cortex-M exception ABI (C ABI entry/return with hardware stacking).
// They are unsafe to call as ordinary functions: driver state/exception entry is required.
type Handler = unsafe extern "C" fn();

/// Hardware layout: initial MSP, core exceptions, then IRQ0..46 (TRM Table 5-2).
#[repr(C)]
struct VectorTable {
    initial_sp: *const u32,
    reset: unsafe extern "C" fn() -> !,
    nmi: Handler,
    hard_fault: Handler,
    mem_manage: Handler,
    bus_fault: Handler,
    usage_fault: Handler,
    secure_fault: Handler,
    reserved_8_10: [Handler; 3],
    sv_call: Handler,
    debug_monitor: Handler,
    reserved_13: Handler,
    pend_sv: Handler,
    sys_tick: Handler,
    irqs: [Handler; 47],
}

// SAFETY: immutable flash metadata. The stack address is consumed by hardware;
// sharing the table does not grant Rust access to the pointed-to stack memory.
unsafe impl Sync for VectorTable {}

// 63 words total; peripheral IRQs follow the 16 core words (TRM Table 5-2).
// The linker supplies alignment and independently checks the emitted section size.
const _: () = {
    use core::mem::{offset_of, size_of};
    assert!(size_of::<VectorTable>() == 63 * 4);
    assert!(offset_of!(VectorTable, irqs) == 16 * 4);
};

// SAFETY: memory.ld keeps this exact hardware layout at address zero. Function
// pointer relocations preserve the Thumb bit; the stack symbol is only an address.
#[unsafe(link_section = ".vectors")]
#[used]
static VECTORS: VectorTable = VectorTable {
    initial_sp: &raw const _stack_top,
    reset: Reset,
    nmi: FaultEntry,
    hard_fault: FaultEntry,
    mem_manage: FaultEntry,
    bus_fault: FaultEntry,
    usage_fault: FaultEntry,
    secure_fault: FaultEntry,
    reserved_8_10: [FaultEntry; 3],
    sv_call: FaultEntry,
    debug_monitor: FaultEntry,
    reserved_13: FaultEntry,
    pend_sv: FaultEntry,
    sys_tick: FaultEntry,
    // Install peripheral handlers here at compile time using their named IRQ numbers.
    irqs: {
        let mut irqs = [FaultEntry as Handler; 47];
        irqs[crate::interrupts::GPT0A] = crate::timer::timer0_a;
        irqs[crate::interrupts::GPT1A] = crate::timer::timer1_a;
        irqs[crate::interrupts::GPT2A] = crate::timer::timer2_a;
        irqs[crate::interrupts::GPT3A] = crate::timer::timer3_a;
        irqs
    },
};

// Reset assembly executes before any Rust prologue or hard-float instruction.
global_asm!(
    r#"
.section .text.Reset,"ax",%progbits
.thumb_func
.global Reset
Reset:
    cpsid i                         // PRIMASK: mask configurable-priority exceptions.
    // Establish the downward-growing main stack and its lower bound (TRM 2.4.5).
    ldr r0, =_stack_top
    msr msp, r0
    ldr r0, =_stack_bottom
    msr msplim, r0
    ldr r0, ={vtor}                 // VTOR: use our vectors at flash address 0 (TRM 2.5.5.3).
    movs r1, #0
    str r1, [r0]
    // SAU CTRL: ENABLE=0, ALLNS=0 (TRM 2.5.7.1). One secure-state image.
    // The SAU's Secure attribution wins over IDAU NS/NSC (TRM Table 3-3).
    ldr r0, ={sau_ctrl}
    str r1, [r0]
    // CPACR: grant full CP10/CP11 access before hard-float Rust (Arm 100235, 4.6.6).
    ldr r0, ={cpacr}
    ldr r1, [r0]
    orr r1, r1, #((3 << 20) | (3 << 22))
    str r1, [r0]
    // CCR: allow compiler-generated unaligned Normal-memory accesses and trap
    // integer divide-by-zero (TRM 2.5.5.6). Device/MMIO alignment rules still apply.
    ldr r0, ={ccr}
    ldr r1, [r0]
    bic r1, r1, #(1 << 3)            // UNALIGN_TRP = 0.
    orr r1, r1, #(1 << 4)            // DIV_0_TRP = 1.
    str r1, [r0]
    // SHCSR: enable MemManage, BusFault, UsageFault (TRM 2.5.5.10).
    // PRIMASK remains set, so synchronous faults can still escalate to HardFault.
    ldr r0, ={shcsr}
    ldr r1, [r0]
    orr r1, r1, #((1 << 16) | (1 << 17) | (1 << 18))
    str r1, [r0]
    dsb                             // Complete system-register writes.
    isb                             // Execute subsequent instructions with the new settings.
    b rust_start                    // No return address: startup never returns.

.section .text.FaultEntry,"ax",%progbits
.thumb_func
.global FaultEntry
FaultEntry:
    cpsid i
    mrs r0, ipsr                     // Exception number becomes capture_fault's first argument.
    // The main stack may be exhausted. Switch before any Rust prologue uses it.
    // Clear its limit first: the emergency stack lies below the main stack.
    movs r1, #0
    msr msplim, r1
    ldr r1, =_fault_stack_top
    msr msp, r1
    b capture_fault                 // Terminal path; never attempt exception return.
"#,
    vtor = const r::CPU_SCB.vtor.address(),
    sau_ctrl = const r::CPU_SAU.ctrl.address(),
    cpacr = const CPACR_ADDRESS,
    ccr = const r::CPU_SCB.ccr.address(),
    shcsr = const r::CPU_SCB.shcsr.address(),
);

unsafe extern "C" {
    // Assembly entrypoints: reset establishes a stack; faults replace it.
    fn Reset() -> !;
    fn FaultEntry();
    // Addresses supplied by memory.ld, not ordinary Rust objects.
    static _stack_top: u32;
    static _sidata: u32;
    static mut _sdata: u32;
    static mut _edata: u32;
    static mut _sbss: u32;
    static mut _ebss: u32;
    static mut _stack_bottom: u32;
    fn main() -> !;
}

const DIAGNOSTIC_MAGIC: u32 = 0x444c_5253;
const STAGE_TRIM: u32 = 1;
const STAGE_APPLICATION: u32 = 2;
const STAGE_FAULT: u32 = 0xffff_0001;
const STAGE_PANIC: u32 = 0xffff_0002;

/// Fixed debugger layout: two header words and five fault- or panic-specific words.
#[repr(C)]
struct BootDiagnostic {
    magic: u32,
    stage: u32,
    details: DiagnosticDetails,
}

/// Interpret as `fault` for STAGE_FAULT, `panic` for STAGE_PANIC.
/// During normal boot the payload is zero; inspect terminal records with the CPU halted.
#[repr(C)]
union DiagnosticDetails {
    fault: FaultDetails,
    panic: PanicDetails,
}

#[derive(Clone, Copy)]
#[repr(C)]
struct FaultDetails {
    exception: u32,
    cfsr: u32,
    hfsr: u32,
    mmfar: u32,
    bfar: u32,
}

#[derive(Clone, Copy)]
#[repr(C)]
struct PanicDetails {
    line: u32,
    column: u32,
    filename_address: u32,
    filename_length: u32,
    reserved: u32,
}

const EMPTY_DIAGNOSTIC: BootDiagnostic = BootDiagnostic {
    magic: 0,
    stage: 0,
    details: DiagnosticDetails {
        fault: FaultDetails {
            exception: 0,
            cfsr: 0,
            hfsr: 0,
            mmfar: 0,
            bfar: 0,
        },
    },
};

const _: () = assert!(core::mem::size_of::<BootDiagnostic>() == 7 * 4);

/// Read by debugger through the stable BOOT_DIAGNOSTIC symbol and named fields.
/// NOLOAD storage outside .bss; rust_start initializes it explicitly.
// SAFETY: this is the sole definition of this exported symbol, in writable SRAM.
#[unsafe(no_mangle)]
#[unsafe(link_section = ".diagnostic")]
#[used]
static mut BOOT_DIAGNOSTIC: BootDiagnostic = EMPTY_DIAGNOSTIC;

#[unsafe(no_mangle)]
unsafe extern "C" fn rust_start() -> ! {
    // SAFETY: linker-defined aligned ranges are disjoint; interrupts are masked
    // and no Rust static has been accessed before memory initialization.
    unsafe {
        // Restore initialized statics from their flash load image into SRAM (.data).
        let mut source = &raw const _sidata;
        let mut destination = &raw mut _sdata;
        while destination < &raw mut _edata {
            destination.write_volatile(source.read_volatile());
            destination = destination.add(1);
            source = source.add(1);
        }
        // Zero statics without a stored initializer (.bss); leave stacks/diagnostics alone.
        destination = &raw mut _sbss;
        while destination < &raw mut _ebss {
            destination.write_volatile(0);
            destination = destination.add(1);
        }
        // Stack watermark stops below the live Rust frame. This is diagnostic,
        // not a proof of maximum stack usage or a replacement for MSPLIM.
        let current_sp: usize;
        asm!("mrs {}, msp", out(reg) current_sp, options(nomem, nostack, preserves_flags));
        destination = &raw mut _stack_bottom;
        while (destination as usize) < current_sp {
            destination.write_volatile(0xa5a5_a5a5);
            destination = destination.add(1);
        }
        // Start a fresh boot record; volatile stores keep each stage visible to JTAG.
        let diagnostic = &raw mut BOOT_DIAGNOSTIC;
        diagnostic.write_volatile(EMPTY_DIAGNOSTIC);
        (&raw mut (*diagnostic).magic).write_volatile(DIAGNOSTIC_MAGIC);
        (&raw mut (*diagnostic).stage).write_volatile(STAGE_TRIM);

        // Board defaults: finish LF selection and start RTC before entering main.
        crate::setup::initialize();

        (&raw mut (*diagnostic).stage).write_volatile(STAGE_APPLICATION);
        main() // Application takes ownership; interrupts remain masked here.
    }
}

#[unsafe(no_mangle)]
unsafe extern "C" fn capture_fault(exception: u32) -> ! {
    // Record only fixed-size status on the emergency stack; no logging or recovery.
    // SAFETY: independent emergency stack installed by FaultEntry; registers are
    // architectural fault status. No application memory references are created.
    unsafe {
        let diagnostic = &raw mut BOOT_DIAGNOSTIC;
        (&raw mut (*diagnostic).magic).write_volatile(DIAGNOSTIC_MAGIC);
        // CFSR/HFSR/MMFAR/BFAR: TRM 2.5.5.11/.12/.14/.15.
        // Address values are meaningful only when CFSR's corresponding VALID bit is set.
        // Individual stores avoid a volatile aggregate's temporary stack copy.
        let fault = &raw mut (*diagnostic).details.fault;
        (&raw mut (*fault).exception).write_volatile(exception);
        (&raw mut (*fault).cfsr).write_volatile(r::CPU_SCB.cfsr.read().bits());
        (&raw mut (*fault).hfsr).write_volatile(r::CPU_SCB.hfsr.read().bits());
        (&raw mut (*fault).mmfar).write_volatile(r::CPU_SCB.mmfar.read().bits());
        (&raw mut (*fault).bfar).write_volatile(r::CPU_SCB.bfar.read().bits());
        // Mark the terminal stage after writing its payload; the record is not atomic.
        (&raw mut (*diagnostic).stage).write_volatile(STAGE_FAULT);
        // Park for inspection. WFI may wake, so loop rather than resuming the application.
        loop {
            asm!("wfi", options(nomem, nostack));
        }
    }
}

#[panic_handler]
fn panic(info: &PanicInfo<'_>) -> ! {
    // Panics use the current stack; unlike FaultEntry, this is an ordinary Rust call.
    // SAFETY: terminal failure; stop all ordinary ISR mutation and leave a
    // debugger-readable marker. No formatting, allocation or breakpoint needed.
    unsafe {
        asm!("cpsid i", options(nostack, preserves_flags));
        let diagnostic = &raw mut BOOT_DIAGNOSTIC;
        let mut details = PanicDetails {
            line: 0,
            column: 0,
            filename_address: 0,
            filename_length: 0,
            reserved: 0,
        };
        if let Some(location) = info.location() {
            // The filename is static UTF-8; store its address/length without formatting.
            details.line = location.line();
            details.column = location.column();
            details.filename_address = location.file().as_ptr() as u32;
            details.filename_length = location.file().len() as u32;
        }
        (&raw mut (*diagnostic).magic).write_volatile(DIAGNOSTIC_MAGIC);
        let panic = &raw mut (*diagnostic).details.panic;
        (&raw mut (*panic).line).write_volatile(details.line);
        (&raw mut (*panic).column).write_volatile(details.column);
        (&raw mut (*panic).filename_address).write_volatile(details.filename_address);
        (&raw mut (*panic).filename_length).write_volatile(details.filename_length);
        (&raw mut (*panic).reserved).write_volatile(0);
        (&raw mut (*diagnostic).stage).write_volatile(STAGE_PANIC);
        // Leave the record intact for JTAG; no unwind or reset.
        loop {
            asm!("wfi", options(nomem, nostack));
        }
    }
}

# CC1354P10 startup and driver contracts

Startup runs as one secure Cortex-M33 image. Rust owns the runtime; a narrow
TI driverlib dependency supplies reset-time silicon initialization. There is no
C runtime, FreeRTOS, or allocator. Hardware boot ROM still performs the
silicon's normal boot process before entering the flash reset vector.

The initial implementation is restricted to CC1354P10 silicon (wafer ID `0xbb78`,
CC13 and PA identity flags), a 48 MHz HF crystal and 32.768 kHz LF crystal, no
external TCXO, no customer crystal-capacitance delta or oscillator-current
adjustment, cache enabled, and nonboost VDDR. SysConfig encodes these board defaults.
The clock driver checks the two source selections it requires, and startup rejects
external-regulator wiring; other CCFG fields are consumed by TI setup without a
duplicate Rust policy table. Supporting another configuration requires reviewing
the affected drivers and trim sequencing rather than changing CCFG alone.
Power support is limited to the LaunchPad's regulated supply; no battery-voltage
service, standby/shutdown entry, or external-regulator configuration is exposed.
SysConfig generates CCFG from `config/board.syscfg`; a host test checks the linked
block's address, 124-byte size, and loadable contents, without fixing its values.

## Hardware references and operating limits

The startup review used these device-family-specific references:

- [CC13x4x10 / CC26x4x10 TRM](https://www.ti.com/lit/pdf/swcu194), SWCU194, March 2023:
  registers, clock/power transitions, CCFG/FCFG, and AUX handshakes.
- [CC1354P10 datasheet](https://www.ti.com/lit/ds/symlink/cc1354p10.pdf), SWRS267B,
  December 2023: electrical, supply, and oscillator requirements.
- [CC1354P10 silicon errata](https://www.ti.com/lit/er/swrz132b/swrz132b.pdf), SWRZ132B,
  December 2023: silicon revision C / PG3.0 advisories.
- [LaunchPad design files](https://dr-download.ti.com/design-tools-simulation/design-tool/MD-Z9UTIvSKfH/01.00.00.00/sprr484.zip),
  SPRR484, package 01.00.00.00: LP-EM-CC1354P10-1 crystal and regulator wiring.

The pinned SDK's `source/ti/devices/cc13x4_cc26x4/driverlib` and `inc` directories provide the
setup sequence, ROM interfaces, and register definitions. Its `source/ti/drivers/power` directory
provides the reference LF completion and runtime power policies. Bazel builds the setup dependency
as `@ti_sdk//:setup`, defined in `third_party/ti/sdk.BUILD.bazel`.

TRM section 11.3 delegates factory calibration to TI software; some fields written by setup are
reserved in the register descriptions. The unmodified SDK sequence remains the authority for those
analog operations. Current tests verify firmware integration, not analog qualification across the
device's supply and temperature range.

Before extending the supported operating envelope:

- Battery operation needs a voltage-dependent DC/DC policy. Erratum Power_03 describes regulator
  ripple below 2.0 V; TI's power driver provides `SysCtrl_DCDC_VoltageConditionalControl` for the
  associated voltage policy. Successful regulated-supply boot does not validate battery operation.
- High-power RF needs review of Radio_02's LF-crystal failure conditions, including temperature,
  RF loading, and output power. Clock-loss detection is enabled, but is only part of the workaround.
- Determine errata applicability from the silicon revision using the family-specific `chipinfo`
  definitions. The wafer/product guards identify the family, and FCFG revision identifies the
  factory-data layout; neither alone establishes silicon revision.

## Reset and memory

`memory.ld` places the 63-entry vector table at zero and allows code and constants
across the full 1 MiB of flash. The separate 124-byte CCFG block stays at
`0x50000000`; it does not consume the end of main flash.

`startup.rs` defines the vector table as immutable Rust data with named core
exception fields and a 47-entry peripheral IRQ array. Adding a peripheral handler
means assigning its function pointer at its named IRQ index in the constant
initializer; no runtime registration or assembly edits are needed. Unimplemented
and reserved vectors use `FaultEntry`. Compile-time offset/size assertions and
the linker size assertion guard the hardware layout. Only the reset and fatal
exception entry sequences remain assembly so they can establish a stack before Rust.

The SRAM region is declared `rwx`; explicit section placement keeps application
code in flash. Linker region attributes do not configure MPU permissions.
The image uses `panic=abort` and has no runtime unwinder, so the linker discards
`.ARM.exidx` and `.ARM.extab`. DWARF debug information, including `.debug_frame`,
and `.ARM.attributes` remain in the ELF for debugging and ABI identification;
these nonallocated sections are not programmed into flash.

After removing the unwind tables, a JTAG snapshot on LS4500IY still resolved
`spin_loop` and `firmware_main` (now named `main`), matching the previous blink-loop backtrace;
boot stage was 2 and CFSR/HFSR were zero. This verifies that sampled application
path, not arbitrary fault or interrupt backtraces.

SysConfig's no-TrustZone template puts the IDAU NS watermark at 8 KiB and the
NSC watermark at zero (`TRUSTZONE_FLASH_CFG=0xfffe0400`). This replaces the
handwritten `0xfffffff8` word; the other 30 words are unchanged. Do not use the
hidden `markAllFlashSecure` setting: TI ignores it without its TrustZone module,
which is intended to select a separate secure image. We do not consume that module.
Reset writes `SAU_CTRL=0` (ENABLE=0, ALLNS=0), making the entire flash effectively
Secure to the CPU: SAU Secure wins over both IDAU Non-secure and Non-secure-callable,
as specified in [TI TRM SWCU194, Table 3-3](https://www.ti.com/lit/pdf/swcu194).
Non-CPU bus masters see the changed IDAU map; revisit that policy when introducing
DMA/RF access to flash. The final-flash board test validates CPU execution/readability.

SRAM retains its historical nonsecure IDAU attribution, with effective Secure
CPU attribution from the SAU. Non-CPU bus masters use the IDAU/bus-firewall
configuration, not the CPU's SAU. No nonsecure application, gateway, or firmware
signature authentication is installed; this is not a security boundary against
a second application.

`Reset` masks interrupts, installs MSP and MSPLIM, sets VTOR, and enables CP10/11.
Before entering Rust, it also configures CCR to allow supported unaligned
Normal-memory accesses and trap integer divide-by-zero, and enables MemManage,
BusFault, and UsageFault in SHCSR. DSB/ISB complete this CPU setup before any
compiler-generated startup code runs. PRIMASK remains set during initialization,
so synchronous faults can still escalate to HardFault despite those enables.
Rust copies `.data` and zeros `.bss`. A stack watermark fills the unused portion
of the 8 KiB main stack.
This is an observation aid, not a stack-bound proof. Fault entry switches to a
separate 512-byte emergency stack before recording architectural fault registers.

`BOOT_DIAGNOSTIC` is a 28-byte `#[repr(C)]` record outside `.bss`, explicitly
initialized by startup. Its exported symbol name stays fixed for the debugger:

- `magic`: `0x444c5253`.
- `stage`: 1 before trim, 2 before application, `0xffff0001` fault, `0xffff0002` panic.
- `details`: a five-word union interpreted according to the terminal stage.
  `details.fault` contains `exception`, `cfsr`, `hfsr`, `mmfar`, and `bfar`.
  `details.panic` contains `line`, `column`, `filename_address`, `filename_length`,
  and a zero `reserved` word. Missing panic locations produce zero fields.

The payload is zero during normal boot. Fault address fields are meaningful only
when their corresponding CFSR valid bits are set. Panic filenames are static
UTF-8 bytes described by address/length. Raw pointers and volatile stores avoid
creating references to mutable global storage. Terminal stage is written after
the payload, but the whole record is not atomic; inspect it with the CPU halted.
The seven-word binary layout is unchanged; debugger expressions now use named
fields, for example `BOOT_DIAGNOSTIC.stage` and `BOOT_DIAGNOSTIC.details.fault.cfsr`.

On 2026-10-02, JTAG on LS4500IY verified named-field reads for a deliberate
undefined-instruction fault (exception 6, CFSR `0x10000`) and a deliberate panic
(matching source line/column and filename length, zero reserved word).
Field-by-field volatile writes keep the fault handler at 60 bytes of code with
no temporary payload stack copy under the pinned optimized toolchain.

Both panic and fault stop with interrupts masked. Reserved and unused interrupt
vectors also take this diagnostic path. No dynamic vector replacement is exposed.

## TI startup boundary

Bazel compiles unmodified SDK **8.33.00.16** source, then Rust calls
`NOROM_SetupTrimDevice()` once after RAM/FPU setup with interrupts masked.
The C header declares `void SetupTrimDevice(void)` and renames its compiled
implementation; no bindgen, wrapper library, TI reset/vector code, or C runtime
is needed for this argument-free entry. The SDK's ordinary helper/ROM policy is
preserved. Despite its name, this family's `setup_rom.c` is compiled software;
`rom.h` supplies no Setup entrypoints.

The retained C sources are `setup.c`, `setup_rom.c`, `aux_sysif.c`, `chipinfo.c`,
`interrupt.c`, `ddi.c`, `osc.c`, and `ioc.c` under
`source/ti/devices/cc13x4_cc26x4/driverlib`. The IOC helper is reachable from TI's
external-LF branch, although our validated configuration does not select it.
We retain those dependencies rather than patch vendor code to remove branches;
function-section garbage collection drops unrelated helpers. Applications do
not call TI GPIO, UART, timers, board setup, or the runtime power manager.
SDK sources and their original comments/notices remain in the pinned external repository.

The call owns the interleaved silicon sequence:

- VIMS/cache setup and reset/retention discrimination.
- Regulator defaults and factory oscillator/bias/ADC calibration from FCFG.
- CCFG-dependent supply and initial clock choices, AUX state, and boot flags.
- TI's temporary RTC configuration and RF/SCE register-access permission tables.

Rust validates supported silicon, required clock sources, and supply wiring before
that call, then waits for the LF crystal, applies TI's qualifier/loss-detector
completion, and stops/reinitializes RTC with the final `0x800000` increment. RTC channels, combined
outputs, and radio synchronization are disabled again; `RTC_CTL=1`. The epoch is
this post-qualification enable, not entry to reset. Application HF switching and
GPIO remain concrete Rust drivers. The reset-time C entry has unbounded hardware
polling loops, as shipped by TI; Rust's subsequent waits use iteration budgets,
not measured wall-clock deadlines. Sleep/resume and arbitrary clock/voltage
configurations remain unsupported even though the vendor source contains branches.

Compared with the removed Rust translation, TI also installs the RF/SCE access
permission tables. They remain installed after startup; no RF/SCE master is
started by this image. Future drivers must account for that default and separately
enable RTC radio synchronization if needed. This is a deliberate acceptance of
TI's complete early setup sequence, rather than a claim that all of it is analog
trim or undocumented.

## Fixed clock control

LF completion and a running RTC are mandatory defaults of this supported board,
established before `main`, rather than optional application initialization.
Setup waits for LF selection and starts a fresh RTC epoch; the counter is already
advancing when `main` begins. Applications own the later choice of RTC channels,
interrupts, and radio synchronization, all initially disabled. Keeping this work
in setup gives every application the same baseline, at the cost of waiting before
any application work can run. There is no measured wall-clock bound on that wait.
TI's trim source remains unmodified, including its initial LF/RTC configuration.

LF setup selects the 32.768 kHz crystal and waits for selected-source status.
Afterward it applies TI's LF qualifier completion sequence and enables both the
OSC clock-loss detector and PMCTL's reset response. The qualifier bits remain a
vendor-dependent operation, despite being located in the clock driver.
RTC initialization performs the AUX request/acknowledgement handshake, clears
channel enables/events and the pending RTC IRQ, and leaves `RTC_CTL=1`.
Reading `SUBSEC` alone does not sample current time: `SEC` latches it. Future RTC
readers should use the coherent `TIME` register or the documented SEC/SUBSEC
protocol (TRM 18.4.1.3–4 and 18.4.1.13).

The CPU still enters the application on RCOSC HF. `Board::take()` returns the
unique `Clocks` handle alongside the LED pins. `request_hf_crystal()` initiates
startup; `hf_crystal_ready()` reads status; `try_switch_to_hf_crystal()` returns
false until a requested transition is ready. A successful call uses TI's
`HARD_API_T.HFSourceSafeSwitch` ROM entry, then restores automatic DC/DC clock
selection. Repeating the request or successful switch is harmless. There is no
switch-back or LF reconfiguration API.

`ti_rom.c` exposes TI SDK 8.33 `driverlib/rom.h`'s `HapiHFSourceSafeSwitch()` macro
through one C function. The compiler uses TI's `HARD_API_T` layout and function-pointer signature;
Rust declares the argument-free C entry and follows `osc.h::OSCHfSourceSwitch` around it.
Flash execution during the actual transition can freeze the CPU, so the switch
must remain in ROM. The Rust driver saves PRIMASK, masks configurable interrupts,
performs the switch, and restores the previous mask. Faults/NMI remain terminal.
The ROM operation is synchronous and has no software timeout; the Rust wrapper
checks the hardware's pending-switch readiness first. Crystal-startup polling
stays outside the masked interval and the application chooses its wait budget.
This does not claim a measured bound on interrupt masking or a complete audit of
the ROM implementation.

Assembly checked with Arm GNU 13.2.Rel1 on 2026-10-10: the C wrapper uses `mov.w`,
`ldr.w`, and `bx` to load the table entry and tail-branch to ROM, with no stack frame.
Rust calls it with `bl`; ROM returns directly to Rust. Compared with the previous manual
lookup, the call adds one branch and moves the table load into the masked interval.
Removing the pointer-validation path reduced the LED image's code/read-only data by 100 bytes.
These are static assembly observations; this change has not been rerun on hardware.

## GPIO bring-up

`Board::take()` claims the board once, powers PERIPH, enables GPIO and GPT clocks,
configures DIO6/7 as push-pull LED outputs, starts GPT1 with GPT0 stopped, releases IO retention,
and unmasks CPU
interrupts. No peripheral IRQ source is armed. Output operations use hardware
set/clear/toggle aliases instead of software read-modify-write.

`device.rs` owns LED pin assignments and releases global I/O retention after all board pin
configuration is complete. The GPIO driver configures fixed push-pull outputs in DIO0–31, initially
low, using TI's standard output settings (automatic 2 mA drive, no pulls or input/edge functions).
Board initialization constructs these handles. `OutputPin::set()` and `toggle()` take shared
references; hardware aliases isolate each pin's updates. Callers coordinate sequences on a shared
pin. Handles have no `Copy`, `Clone`, or drop-time hardware action, and no runtime reconfiguration
or GPIO power-down API is exposed.

Assembly inspection on 2026-10-10 confirmed both methods inline at their call sites. In `bringup`,
each LED toggle is a mask load followed by one MMIO store, with the register address prepared outside
the loop. The GPIO test's set/clear paths each issue one MMIO store. Output operations add no function
calls, output-register reads, or interrupt masking. Cycle counts have not been measured.

The application verifies initialized and zeroed RAM, requests and switches to the 48 MHz HF crystal,
then checks the timers and toggles both LEDs on timer events. `BLINK_COUNT` increments after each
pair of toggles and can be observed through a debugger. UART, logging, and RF remain later milestones.

Embedded compilation is required before flashing; compilation alone does not establish genuine
power-on behavior or electrical timing. Keep raw hardware results outside source control.

### GPIO board test

Build `bazel build --config=m33 --config=lint //firmware:gpio_test`. This image checks both LED pin
configurations, output enables, global retention release, and initial low levels. It exercises
set/clear and toggle operations across all four LED states, verifies unrelated output latches are
preserved, and uses multiple shared references to the same output. It also checks that `OutputPin`
implements `Sync`. The checks are sequential; they do not exercise interrupt interleavings or measure
electrical pad levels or timing.

Flash and inspect it with the same debugger workflow as the clock tests below, reading
`GPIO_TEST_RESULT` instead of `CLOCK_TEST_RESULT[0]`. `0x50415353` means every check passed;
panics/faults use `BOOT_DIAGNOSTIC`. As of 2026-10-10, this image has not been run on hardware.
Integrate it with the automated embedded-test runner after the rebase.

## Timers and interrupt bring-up

Board initialization assigns GPT1 to `Board::counter` and GPT0 to `Board::timer`. Either driver can
use any of GPT0–GPT3; crate-private constructors require exclusive ownership, and handles cannot
be copied or reassigned to another peripheral. The board enables selected clocks through PRCM
before constructing the handles, retaining the shared undivided clock setting for their lifetime.

`Board::counter` is a free-running 32-bit up-counter. `now()` reads its ticks;
`elapsed_since()` subtracts modulo 2^32 and is valid for intervals shorter than one wrap.
The undivided system clock is nominally 48 MHz on either HF source, giving about 89.5 seconds
per wrap. The driver exposes no counter reset, clock-divider change, or power-down operation.

`Board::timer` has mutable methods to arm a periodic or single timeout in microseconds,
or stop and clear pending activity. Zero and overflowing intervals are rejected before changing
the current configuration. Compile-time assertions in `timer_test.rs` check tick conversion boundaries
when building the timer test images. Timing accuracy has not been measured against an independent clock.

The Rust vector table installs all four GPT A handlers using the shared `interrupts.rs` map.
Each timer constructor sets its IRQ's priority to 2 of 8. Reconfiguration
disables only that NVIC source; DSB/ISB follow the Cortex-M33 CMSIS disable sequence. Timeout
acknowledgement follows the pinned SDK's `driverlib/timer.h` `TimerIntClear` guidance: clear,
read the same peripheral, then allow two CPU cycles for interrupt propagation. `interrupts()`
returns that instance's relaxed atomic count of acknowledged timeouts, preserved across stopping/rearming.
It carries no payload or synchronization guarantee; multiple timeouts can coalesce while masked.

The bring-up image uses bounded `wait_for()` polling to check repeated periodic interrupts,
no further interrupts after stopping, rejection of invalid intervals, and exactly one interrupt
from a one-shot. It then blinks on nominal 500 ms periodic events. Inspect `TIMER_TEST_STATUS`
through the debugger: 0 is before checks, 1 is in progress, and 2 means all timer assertions passed.
Also require boot stage 2, clear fault status, and increasing `BLINK_COUNT`. Panic/fault details
remain in `BOOT_DIAGNOSTIC`. These checks share the timer clock and do not establish absolute
accuracy. Fresh board execution of this replayed timer implementation remains pending;
move its checks into the common embedded-test framework after the rebase.

### GPT assignment and isolation tests

Build `bazel build --config=m33 --config=lint //firmware:timer_test_gpt{0,1,2,3}`. Each image uses
the named GPT as counter and the other three as concurrent interrupt timers. They check progress
from every source, invalid requests preserving an active timer, stopping one without stopping the
others, one-shot rearming, and absence of interrupts after stopping all three. The test image owns
initialization directly, instead of taking the default Board resources.

After flashing the selected image, inspect `TIMER_INSTANCE_TEST_RESULT` for `0x50415353` and
`BOOT_DIAGNOSTIC` for faults/panics, as with the other board tests. All four images build and lint;
hardware execution is pending. Include them in the post-rebase embedded-test framework migration.

### Instance selection cost

The M33 `Counter` handle stores one generated register address (4 bytes); `Timer` stores a register
block reference, IRQ mask, and count reference (12 bytes). Four acknowledgement counters use 16
bytes of static RAM. There are no trait objects or indirect handler calls. On 2026-10-10, assembly
inspection confirmed direct register accesses in each ISR, inlined counter reads with a handle
address load, and register-descriptor loads in timer reconfiguration. Count reads also inline.
Compared with the fixed GPT0/GPT1 implementation, the default bring-up ELF grew from 13,136 to
13,500 bytes of text/read-only data and gained 12 bytes of BSS. These totals include the additional
handlers and instance metadata; they are not a cycle measurement. Raw assembly and ELFs remain in
ignored `.results/timer-instances/`.

## Clock board tests

Build `bazel build --config=m33 --config=lint //firmware:clock_test
//firmware:clock_test_masked` (one command). These use the production startup and
CCFG. Both verify the initial RCOSC state, LF selection and loss detection,
RTC increment/epoch/progress, rejection of switching before a request, successful
HF switching, DC/DC automatic-clock restoration and repeated-call behavior.
The first starts the ROM switch with interrupts enabled; the second starts with
PRIMASK set. Both require the previous mask to be preserved.

After programming, verification and reset, inspect `CLOCK_TEST_RESULT[0]` with
the Bazel JTAG runner. `0x50415353` (PASS) is written only after every assertion
succeeds. Words 1–7 capture OSC status/control, RTC increment/control, reset
control, regulator control and the actual ROM entry. Word 8 is the initial RTC
seconds value (zero); word 9 is positive elapsed time in 16.16 units; word 10
records the initial mask (0 or 1), and word 11 is zero after the test unmasks.
Also require boot stage 2 and CFSR/HFSR zero. These tests do not measure absolute
crystal accuracy or deliberately stop a crystal to test fault recovery.

At this rebase stage, Bazel flash/JTAG runners are available in the later tooling
commit `f7a31b4`; use an isolated checkout of that commit and pass the absolute
ELF built here. For example, from that checkout:

```sh
bazel run //tools/debug:flash -- --probe LS4500IY --elf /absolute/clock_test.elf
bazel run //tools/debug:debug_target -- --probe LS4500IY --elf /absolute/clock_test.elf \
  --expression 'CLOCK_TEST_RESULT[0]' --expression 'CLOCK_TEST_RESULT[10]'
```

Repeat explicitly for both images and both probes; hardware runs are uncached.
Restore the normal `bringup` image after the tests.

On 2026-10-02, both LS4500IY and LS4500Q0 passed both clock images after flash
verification and probe reset. Each reported PASS, boot stage 2, CFSR/HFSR zero,
the expected initial mask, and positive RTC progress from initial seconds zero.
Observed `OSC_CTL0=0x3000020d`, `RTC_CTL=1`, `RTC_SUBSECINC=0x800000`, and
`PWRCTL=5` confirm the selected crystals, qualifier bypass/loss detection, disabled
radio sync, correct increment and DC/DC state. Both boards exposed ROM entry
`0x10003b53` via the table (the implementation does not embed that address).
Their raw identity fields were ICEPICK `0x1bb7802f`, MISC_CONF_1 `0xffffff01`, and
FCFG layout revision `0x2a`; these are observations, not a new silicon support
restriction. Raw JTAG and programming reports remain outside version control.
Both boards were then restored to the normal LED image and reached boot stage 2
on the HF crystal with clear fault status and nonzero `BLINK_COUNT.v.value`.
Physical power cycling has been requested and is not yet verified for this change.

## Historical full-flash boundary verification

The bring-up image and its `//firmware:flash_layout_test` target were removed on
2026-10-04. Their source is available at commit `8e41bc7` in `firmware/flash_test.rs`
and `firmware/flash_test.ld`; this section records past verification, not a current
test target.

The image used production reset, CCFG, and device code. A supplemental linker
script placed an assembly function at `0x000ffff0` and its literal at
`0x000ffffc`, with a linker assertion enforcing the final 16-byte placement.
The function loaded the literal and returned its value plus one. The test also
read the literal directly and checked effective Secure attribution with the Arm
`TT` instruction. This did not reserve space in normal application images.

JTAG inspection of `FLASH_LAYOUT_RESULT` required word 0 to be `0x50415353`
(PASS, written after all assertions) and word 1 to be `0x1354caff`. Words 2–5
recorded PRCM's NS and NSC watermark registers, SAU CTRL, and the TT result for
the last flash word. Acceptance also required SAU CTRL zero, TT bit 22 set,
`BOOT_DIAGNOSTIC.stage` 2, and CFSR/HFSR zero. Watermarks differed between the
original CCFG and TI-generated CCFG, as recorded below. This verified end-of-flash
execution/data access, not every flash cell or physical power-on behavior.

On 2026-10-02, both LS4500IY and LS4500Q0 passed after flash verification and
probe reset: result `0x1354caff`, NS/NSC registers `0x800fe000`, SAU CTRL zero,
TT `0x03cc0000`, and no CFSR/HFSR faults. The linker/CCFG/startup and test image
were built at this rebase stage; the Bazel flash and JTAG runners came from the
later debugger tooling at `f7a31b4` in an isolated checkout. Raw reports remain
outside version control. Both boards were restored to the normal LED image with
the same full-flash configuration and reached boot stage 2 without CFSR/HFSR
faults. Physical power cycling was not repeated for this change.

## TI integration verification (2026-10-03)

With SDK 8.33 setup and SysConfig 1.28.1 CCFG, fresh flash/verify/reset and DSS
snapshots passed on both LS4500IY and LS4500Q0:

| Image | Observation on each board |
| --- | --- |
| `clock_test` | PASS `0x50415353`; boot stage 2; HF/LF selection, loss detector, DC/DC and RTC assertions passed; PRIMASK before/after switch 0/0 |
| `clock_test_masked` | PASS; PRIMASK preserved at 1 during switch, explicitly cleared by test afterward |
| `flash_layout_test` | PASS; final-address execution returned `0x1354caff`; SAU CTRL 0, TT `0x03cc0000`; NS watermark `0x80002000`, NSC 0 |
| `bringup` | Restored LED image; boot stage 2 and source-resolved blink-loop backtrace |

CFSR/HFSR were zero in every snapshot; RTC SUBSECINC was `0x800000` and CTL 1.
The full-flash result checks the generated CCFG's changed IDAU policy on hardware.
These are probe resets, not a new physical power-cycle qualification. The former
Rust image's power-cycle evidence does not qualify this new SDK path. The user
is away from the setup and agreed to defer that check. Both boards connect directly
to host root-hub ports 3-8/3-9; read-only `uhubctl` inspection is blocked by hub
permissions, so remote VBUS switching has not been established. USB unbinding or
re-enumeration alone would not establish a power cycle. A future board-test fixture
should provide verified per-port VBUS control (see [uhubctl](https://github.com/mvp/uhubctl))
and avoid back-power through other board connections.

During the paused rebase, runners came from an isolated checkout of `master`
`f7a31b4`, invoked through `bazel run //tools/debug:flash` and
`bazel run //tools/debug:debug_target` with explicit probe, ELF, and output directory.
Its read-only expression parser was extended to allow diagnostic struct members.
Raw manifests, ELF hashes, and debugger reports are outside the source checkout
in `/home/agoessling/direct_line_results/ti-integration`; they are not committed.
The debugger tooling commit will reintroduce these runners in the current branch.

Host tests and both lint/build configurations passed. ELF inspection found no
undefined symbols and retained DWARF; the LED image has 10,880 bytes of text/rodata,
4 bytes of data, and 8,744 bytes of BSS/NOLOAD allocation (including stacks).
Neovim tests in the editor repository passed Rust/generated-register/Python/Starlark
navigation, generated CCFG-to-SDK navigation, and C/Rust/Python/Starlark save formatting.
Rust-to-C FFI semantic navigation remains a language-server limitation.

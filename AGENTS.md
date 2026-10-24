# Direct Line: project direction and agent handoff

This file records the agreed direction as of 2026-10-01. Read it before making
architectural changes. Update it as milestones are completed; distinguish planned
work from verified behavior.

## Goal

Build a simple, low-latency point-to-point wireless link with 2.4 GHz and roughly
900 MHz options. Typical packets are 10–50 bytes. The latency goal is on the order
of packet airtime (payload airtime is `8 * bytes / bitrate`, with additional PHY
overhead). Precise measurement endpoints and the warm-radio versus sleep/wakeup
budget remain to be established before RF benchmarking.

Equally important: create a clean, safe, readable foundation for future embedded
projects, with reproducible builds, deployment, host tests, and hardware tests.
Prefer explicit restrictions on hardware and application patterns over broad
generality. Verify performance rather than assuming abstractions are free.

## Agreed implementation direction

- Pursue a clean-sheet Rust firmware implementation for the CC1354P10 boards.
- Remove the existing C/C++ firmware, its targets, and obsolete dependencies when
  implementation begins. Do not maintain a parallel C++ implementation or port
  incrementally through C shims. Git history is the reference and fallback.
  **2026-10-03 exception:** use unmodified TI SDK early setup behind one Rust FFI
  call and SysConfig-generated CCFG; do not translate vendor analog initialization.
  Rust still owns reset/runtime, LF/RTC completion, and peripheral drivers.
  **2026-10-10 exception:** a small C wrapper exposes TI's ROM HF safe-switch macro using
  the SDK's function-table layout; Rust owns the surrounding clock sequence.
- Preserve useful language-independent documentation, probe
  tooling, and udev rules. A host-side tool written in C is not a firmware shim;
  assess it independently rather than deleting it solely because of its language.
  Keep raw test results outside version control; retain concise measurements and
  reproducible tests where they explain a design decision.
- Remove `lint_it_all` and replace its integration with explicit, pinned formatting
  and linting tools. The user considers that dependency a mistake. Preserve the
  useful checks, not the dependency or its architecture.
- Use `no_std`, static allocation, explicit initialization, and clear ownership.
  No heap is planned. Minimal assembly for architectural operations is appropriate.
- Keep application code safe. Concentrate audited `unsafe` operations in startup,
  low-level drivers, register access, and synchronization; explain their contracts.
- Do not inherit FreeRTOS or select a replacement scheduler prematurely. A
  foreground loop and interrupts suffice for initial bring-up. Critical RF work
  is expected to depend heavily on interrupts and autonomous hardware transfers.

## Register definitions (`reg_def`)

The source project is <https://github.com/agoessling/reg_def>. Extend its existing
TI XML parser and device model with Rust generation. The host generator can remain
Python; a Rust firmware does not require rewriting every development tool.
Develop generator changes and generic tests in `~/reg_def`, then consume a
published commit through a pinned Bzlmod dependency. Do not maintain a downstream
patch or generator fork. Device-specific integration tests belong here. Generate
a standalone `no_std` crate root and use it directly as the register library
source; no handwritten `include!` wrapper or source-path environment variable is
needed.

Rust generation now emits hover documentation from XML descriptions, field positions/access/reset
values, and named encodings. The shared parser retains `bitenum` metadata for documentation;
it does not introduce generated Rust enums or hardware-value validation. Neovim hover was verified
on 2026-10-11; its smoke test lives in `~/.config/nvim/tests/register_hover.lua`.

Preserve convenient named bitfield access. Generate integer-backed register-value
wrappers with field getters/setters and raw `from_bits()` / `bits()` access. Field
operations act on local values; explicit volatile reads/writes access hardware.
For example, the intended API shape is:

```rust
// Illustrative API, not an existing implementation.
unsafe {
    let mut mode = timer.tamr.read();
    mode.set_taild(true);
    mode.set_tamr(0x2);
    timer.tamr.write(mode);
}
```

The generator describes layout: addresses, access widths, offsets, masks, and
documented constants. Do not build a comprehensive type system for peripheral
semantics. The low-level driver is expected to understand write-one-to-clear,
read side effects, reserved bits, initialization sequences, and synchronization.
Avoid initially hiding read-modify-write inside generic convenience methods.

Keep raw register access internal to the device implementation. Safe public
driver operations must preserve hardware and memory-safety invariants. Volatile
access alone provides neither synchronization nor ownership. Test field encoding,
addresses, and access widths, and inspect representative embedded assembly.

## Driver design

The normal path should be `application -> concrete driver -> registers`.

- Prefer targeted drivers, including hardware-specific APIs when they simplify
  implementation. Start with the actual CC1354P10 and board capabilities needed.
- Keep configuration, ownership, clock requirements, interrupt priorities, and
  blocking behavior explicit. Avoid hidden allocation or interrupt masking.
- Use types where they enforce useful ownership or lifetime constraints, such as
  peripheral uniqueness and DMA buffer lifetime. Avoid elaborate type-state
  systems for every hardware configuration.
- Extensibility is welcome when runtime overhead is near zero and readability
  costs are low. Do not add trait layers or forwarding wrappers speculatively.
- The board module describes wiring and assembles resources; it should not
  forward every peripheral operation. Shared clock/interrupt support stays narrow.
- Driver constructors enable their own power domains and clock gates through PRCM. Board
  initialization sets the shared GPT divider once before constructing drivers, then releases
  global I/O retention and unmasks interrupts after all pins and handler state are configured.
- GPIO configuration is fixed during board initialization, which also releases global I/O retention
  after configuring the pins. Output handles allow shared `&self` set/toggle operations through
  hardware aliases. Keep construction restricted; callers coordinate sequences on the same pin.
  No runtime pin reassignment or GPIO power-down API is exposed.
- Existing crates are optional building blocks, not architectural requirements.
  Assess their scope and APIs before adopting them. Consistency and traceability
  matter more than assembling a stack of mismatched abstractions.
- Test pure logic on the host and hardware behavior on boards. Do not distort
  driver architecture solely to make every MMIO operation mockable.
- When replaying commits, reuse `poll::wait_for`, PRCM helpers, generated register access, and the
  Rust vector table. Preserve fixed initialization, explicit resource ownership, and narrow APIs.
  Explain hardware behavior tersely; cite TI functions for unusual sequences or undocumented policy,
  rather than ordinary register layout. Add barriers/readbacks only for a documented requirement.

## Build, Neovim, and CI requirements

Bazel is authoritative. Pin exact tool versions and fetch toolchains through the
build setup. A separate manually installed Rust toolchain must not be necessary.

Editor integration is part of the first milestone, not follow-up polish:

- Neovim go-to-definition should work throughout the codebase for each language
  present, including Rust, Python, and Starlark/Bazel. Account for assembly and
  linker scripts; explicitly identify any remaining navigation limitations.
- Rust-analyzer must understand Bazel targets, target configuration, dependencies,
  generated register sources, and Rust library sources. Derive editor metadata
  from the build rather than maintaining a divergent second project definition.
- Provide a documented way to refresh generated-source/editor metadata.
- Format on save must use the same pinned tools and configuration as command-line
  checks. Export editor-neutral metadata here. Neovim configuration and editor tests belong
  in `~/.config/nvim`; workstation installation belongs in `~/defaults`. Verify
  navigation and save formatting there without bundling editors or language
  servers into this repository.
- CI checks formatting, linting, host tests, and embedded builds. Formatting checks
  must report differences without silently modifying the checkout.
- Hardware tests require explicit boards and fresh execution; cached test success
  is not evidence that a device ran the current image.

## Milestones and acceptance criteria

1. **Repository reset and Rust/Bazel tooling.** Remove old firmware and obsolete
   build dependencies, including `lint_it_all`. Establish pinned host and embedded
   Rust builds, Neovim navigation, formatting, linting, and CI. Start with
   `thumbv8m.main-none-eabihf`, validating exact MCU features. Prefer the bundled
   LLD linker initially, subject to linker-script validation. Completion requires
   reproducible host tests and embedded compilation, plus a working editor setup.
2. **Register generation and core support.** Add the Rust `reg_def` backend and
   minimal Cortex-M33 interrupt/barrier facilities. Generate the registers needed
   for startup, power, clocks, IOC, and GPIO. Verify layout, field operations, and
   representative instructions; ensure generated definitions are navigable.
3. **Standalone startup.** Implement the linker script, vector table, reset entry,
   stack and memory initialization, FPU setup, fault/panic handling, customer
   configuration, and required chip initialization. Audit the TI trim/setup
   sequence early: replacing `SetupTrimDevice()` is a substantial risk, not just
   clearing `.bss`. Validate reset and genuine power-on behavior on both boards.
4. **GPIO and LED.** Implement the required clock/power, pin-mux, and output
   operations. Blink both boards using an explicitly approximate delay loop.
   This independent, cold-booting Rust image is the first substantial deliverable.
5. **Timers and interrupts.** Add a free-running counter and the periodic/one-shot
   behavior needed. Define ownership, acknowledgement, rearming, tick conversion,
   and wraparound. Verify timer-driven blinking and interrupt behavior, with compile-time
   checks for constant arithmetic or host tests as appropriate. Distinguish measured timing from
   assumed timing.
6. **UART.** Start with polling TX/RX and explicit nonblocking operations. Any
   blocking convenience has a clear name and timeout policy. Separate transport
   from formatting/logging. Pass scripted serial tests on both boards.
7. **Concurrency, logging, and scheduling.** Design owned event records and bounded
   communication around actual callers. Logging needs multiple producers,
   including interrupts; do not assume SPSC suffices for one shared logging queue.
   Compare short critical sections with atomic algorithms using correctness and
   measured latency, masking, stack, and RAM costs. Select scheduling at this stage.
8. **RF.** Implement a narrow, single-owner RF path using documented commands and
   required TI PHY configuration/patch data. A clean Rust host driver does not
   imply replacing the radio core's firmware. Measure latency and reliability
   between boards before broader abstraction or performance work.

## Current state and references

Clocks are fixed to the LaunchPad crystals, supply to regulated internal DC/DC/nonboost,
and cache enabled. See `firmware/STARTUP.md` for the supported scope and source references.
Startup validates silicon and supply wiring and delegates CCFG source checks to
the clock driver before calling SDK 8.33 SetupTrimDevice. It then completes LF/RTC
setup in Rust. SysConfig 1.28.1 generates CCFG through Bazel.
**2026-10-05 decision:** keep LF completion and a running RTC with a fresh epoch
as mandatory board defaults before `main`. Accept the startup wait; applications
choose RTC channels, interrupts, and radio synchronization later. Keep TI trim
unmodified rather than extracting its initial LF/RTC configuration.
The board owns one HF clock handle for request/readiness/one-way crystal switch;
its Rust implementation calls TI's ROM safe-switch entry through `firmware/ti_rom.c`.
LF qualification/loss detection and post-qualification RTC initialization are
implemented. No clock alternatives, analog tuning, battery service, switch-back,
or sleep-entry API is exposed. See `firmware/STARTUP.md` for the current contracts.
SysConfig is the sole CCFG configuration source. The linked-image test checks
address, size, and loadable placement, not a snapshot of configuration words.

The Rust/Bazel foundation and standalone LED image are implemented. Bazel 9.2.0
fetches the pinned Rust 1.90.0 and Python 3.14 toolchains. The image
uses the upstream Rust register generator, generated CCFG, TI factory trim, independent
reset/vector/linker support, GPIO, polling UART0, and timer-driven blinking after an explicit HF
crystal switch. Board initialization routes UART0 RX/TX to DIO12/13 before releasing I/O retention.
The bring-up image switches to the HF crystal before serial output, emits `RESULT PASS bringup`
after its checks, then echoes received bytes. The UART constructor enables power and clocks through
PRCM and owns pin routing, format, and FIFO access. Baud arithmetic stays in `uart.rs` with
compile-time checks.
UART0–UART3 are selectable during initialization, with configurable baud and fixed 8N1 framing.
The driver uses 32-bit divisor arithmetic and rejects unsupported rates before changing hardware.
UART0 needs SERIAL power; UART1–UART3 need PERIPH. The driver selects the domain internally and
delegates register writes and polling to PRCM. GPIO and UART share `ioc.rs` for checked pin register
lookup and IOC encodings; IOC also owns the global retention release called after board configuration.
GPT1 provides a free-running counter; GPT0 provides periodic and one-shot timeout interrupts.
This assignment lives in board initialization; either driver can use GPT0–GPT3 through private
construction. The shared GPT divider is set once before handle construction; each constructor powers
PERIPH and enables only its own clock gate. Each GPT A vector has its
own acknowledgement count. The complete peripheral IRQ map lives in `firmware/interrupts.rs`.
The bring-up image checks repeated interrupts, stopping, invalid intervals, and one-shot behavior.
The HIL suite includes these timer checks and clock switching with PRIMASK initially clear and set.
The linker exposes the full 1 MiB of flash; reset establishes all-secure CPU
attribution. A bring-up image verified execution and a literal read in the final
16 bytes on both boards. That image was removed after verification; its source
remains in Git history and results in `firmware/STARTUP.md`.
The production HIL runner uses pinned embedded-test 0.7.0 and probe-rs 0.32.0 through the onboard
XDS110 CMSIS-DAP interface. One explicit probe and one process execute each invocation, with full
system reset before every case. Routine checks use one board; use two for RF or occasional comparisons.
Preverification compares loadable flash bytes, including CCFG, before deciding whether to program;
every selected test still resets and runs. `--force-flash` exercises programming unconditionally.
The firmware preserves boot/fault diagnostics; its test-only panic path reports through semihosting.
UsageFault currently fails as a timeout, with a stack trace; automatic diagnostic decoding is not
implemented. The wrapper requires a completed, nonempty passing suite and records errors in JSON.
The custom CCS runner and its UniFlash dependency were removed; Git commit `75e1aab` preserves the
comparison implementation. TI SDK setup and SysConfig remain firmware build dependencies.
The HIL command supplies a pinned target description with CC1354P10 SRAM corrected to 256 KiB;
`third_party/probe_rs/README.md` explains the temporary upstream correction.
Event logging and RF remain subsequent milestones; UART electrical and external baud validation
remain separate from the suite's internal loopback checks.
Host layout/linked-CCFG tests, embedded compilation, and fresh clock/full-flash
board tests passed with TI setup on 2026-10-03; physical power-on behavior for
this SDK integration must still be checked on the boards. `BOOT_DIAGNOSTIC` reports
boot/fault state and `BLINK_COUNT` reports application progress to a debugger.

- Host tests: `bazel test //...`; complete checks: `tools/quality/check`.
- Repository-wide `//:build_files` and `//:c_format` discover sources across
  packages and run locally without caching; do not add per-package checks for
  these tools. Python checks declare sources per package and include pinned basedpyright checking.
- Rust formatting/lint: `bazel build --config=lint //...`; aspects cover existing
  Rust targets without per-library check targets.
- Embedded build/lint:
  `bazel build --config=m33 --config=lint //foundation/... //firmware/...`.
- Editor metadata: `bazel run //tools/metadata:refresh`.
- Arm GNU 13.2.Rel1 compiles only embedded C and links firmware without a C runtime.
  A pinned standalone clang-format 19 binary formats owned C sources; do not restore
  the old custom wheel-download rule. Metadata refresh exports compile_commands.json.
- Hardware tests: `bazel run //tools/debug:hil -- --probe SERIAL`; add `--filter 'clock::'` for one
  name substring. `--list` requires a probe and also verifies/programs the image. Run boards separately.
- `//firmware:hil_test` contains fourteen normal cases: both clock variants, GPIO, four GPT
  assignments, four UART instances, board bring-up, normal return, and expected panic. Four ignored
  controls deliberately fail: unexpected panic, missing panic, UsageFault, and timeout. Run each
  separately with `--ignored --filter harness::NAME`; expect a nonzero exit.
- Register cases beside their implementations in `firmware/*_test.rs`, inside inline modules marked
  `#[embedded_test::tests]`. The framework generates metadata and dispatch; there is no central list.
  Global setup and harness controls live in `firmware/hil_test.rs`. Keep fresh-RAM validation before
  the host handshake so setup failures cannot satisfy expected-panic tests.
- `//tools/debug:probe_rs` exposes the pinned CLI for explicit debugger operations. Host CI builds
  the HIL runner and checks the CLI version without accessing hardware. Editor metadata and strict
  Python checks no longer require TI's debugger runtime.
- See `docs/hardware_tests.md` for current validation status and measurement limits. Historical
  clock/full-flash evidence and the separate physical-power-cycle status remain in `firmware/STARTUP.md`.
- TI setup now installs RF/SCE NONSECWR/NONSECDDIACC permissions. When RF drivers
  are replayed, account for those defaults and enable RTC radio synchronization
  explicitly; Rust startup leaves it disabled.
- Previous C++ baseline: `8186f5e`; use Git history for reference.
- Hardware runs must remain explicit and uncached. Raw results belong in ignored
  `.results/` directories, not source control.
- The HIL runner streams readable test status and diagnostics live, with native flash bars on a
  terminal. It saves stdout, stderr, and a copy of target logs separately; malformed JSON event
  records fail the run. See `tools/debug/output.py` for bounded process streaming and cleanup.

When commits are requested, keep messages concise, with at most four body
sentences. Do not add coauthor or coding-agent attribution.

## Validation and follow-up

- **2026-10-23:** the user ordered a Digital Discovery for external UART latency measurements.
  See [the fixture handoff](docs/uart_latency_fixture.md) for proposed eight-output/sixteen-input
  wiring, finite DDR playback/capture budgets, sampling qualification, SDK/Bazel integration, and
  bring-up steps. Hardware has not arrived or been validated. Keep JTAG connected and plan to route
  test UARTs away from the debugger's DIO12/13 connection. Final MCU pin assignments remain open.
- The production migration passed all fourteen normal cases freshly on `LS4500Q0`, with forced
  programming and preverified unchanged flash. All four negative controls failed as intended,
  an unmatched filter failed, and the suite passed again after the terminal cases. The corrected
  target description was used throughout; the last SRAM word at `0x2003fffc` was readable.
  All seventeen host test/check targets, host and embedded lint/build checks, and editor metadata
  refresh passed.
- The 2026-10-18 prototype passed all fourteen normal cases repeatedly on `LS4500Q0`, verified main
  flash and CCFG programming, and rejected all four negative controls plus an unmatched filter.
  The same twelve driver checks took 21.70–21.73 s through CCS, 9.76–9.91 s through probe-rs with
  programming, and 6.45–6.65 s with unchanged flash verified first. See `docs/hardware_tests.md`.
- Keep physical power-on, external pin/baud accuracy, sleep recovery, and MCU latency measurements
  separate from debugger-reset functional tests. Host process timings do not measure MCU latency.
- Review code and comment wrapping repository-wide against the configured 100-column limit.
  Reflow unnecessarily narrow comments where it improves readability; do not extend every short line.
  Defer this cleanup until the current rebase is complete to avoid formatting-only merge conflicts.
  Keep it separate from functional changes and run the pinned formatting checks afterward.

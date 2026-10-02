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
patch or generator fork. Device-specific integration tests belong here.

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
- Existing crates are optional building blocks, not architectural requirements.
  Assess their scope and APIs before adopting them. Consistency and traceability
  matter more than assembling a stack of mismatched abstractions.
- Test pure logic on the host and hardware behavior on boards. Do not distort
  driver architecture solely to make every MMIO operation mockable.

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
   and wraparound. Verify timer-driven blinking and interrupt behavior, with host
   tests for arithmetic. Distinguish measured timing from assumed timing.
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

The Rust/Bazel foundation is implemented. Bazel 9.2.0 fetches Rust 1.90.0,
Python 3.12, and pinned formatting/lint tools. Host tests, Cortex-M33 library compilation, and a Rust/C FFI
link check run through the same CI checks. Editor metadata is generated from
Bazel; editor configuration belongs to the user's Neovim/defaults repositories.
No Rust firmware is present yet. Standalone startup/GPIO, timers, UART, board
testing, event logging, and RF remain subsequent milestones.

- Host tests: `bazel test //...`; complete checks: `tools/quality/check`.
- Rust formatting/lint: `bazel build --config=lint //...`; aspects cover existing
  Rust targets without per-library check targets.
- Embedded build/lint: `bazel build --config=m33 --config=lint //foundation/...`.
- Editor metadata: `bazel run //tools/metadata:refresh`.
- Arm GNU 13.2.Rel1 provides the embedded C compiler/linker for the Rust FFI link check.
  A pinned standalone clang-format 19 binary formats owned C sources; metadata refresh exports
  compile_commands.json. Repository-wide Buildifier and C format checks need no per-package targets.
- Previous C++ baseline: `8186f5e`; use Git history for reference.
- Hardware runs must remain explicit and uncached. Raw results belong in ignored
  `.results/` directories, not source control.

When commits are requested, keep messages concise, with at most four body
sentences. Do not add coauthor or coding-agent attribution.

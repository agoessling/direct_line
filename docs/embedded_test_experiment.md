# Embedded-test and probe-rs experiment

The optional `//tools/debug/experiments:embedded_test` target runs annotated Rust tests through
probe-rs 0.32.0 and the LaunchPad's existing XDS110 CMSIS-DAP interface. No probe driver was added.
CCS remains available through `//tools/debug:hil`; this experiment does not replace it.

## Implementation

`firmware/embedded_test.rs` registers tests with upstream attributes. It reuses the clock, GPIO,
timer, UART, and board checks used by the custom suite. The board check moved to `board_test.rs`
so both images execute the same assertions. Fourteen cases normally pass; four ignored controls
deliberately fail to exercise panic, missing-panic, UsageFault, and timeout reporting.

The image retains our reset/vector table, linker memory layout, TI setup, clock defaults, and fault
handler. Each case gets a full system reset. A global setup hook checks initialized and zeroed RAM
before the host handshake and captures the fresh RTC epoch. Only the test image reports a completed
panic through semihosting, after writing the existing diagnostic record. Faults keep their distinct
terminal handler, so a fault cannot satisfy an expected-panic test.

Bazel resolves the pinned framework and procedural-macro dependencies through `crate_universe` and
`Cargo.lock`. The unmodified upstream linker fragment retains non-allocated test metadata. No second
Cargo firmware build, allocator, scheduler, logging backend, or alternate runtime is introduced.
The host wrapper selects and locks one probe, bounds execution, and saves the console and timing
report under ignored `.results/`. It validates the terminal JSON suite summary and rejects empty
selections. Only one filter is accepted: probe-rs 0.32 joins multiple filters into one space-separated
substring, despite its help describing union behavior. See [commands and test selection](../tools/debug/experiments/README.md)
and [dependency details](../third_party/embedded_test/README.md).

## Validation and limits

Hardware validation uses only `LS4500Q0`, an LP-EM-CC1354P10-1. Probe-rs programs and verifies main
flash and the separate CCFG region, preserving unwritten bytes in affected sectors. The default
first compares the ELF's loadable flash bytes with the device and skips programming only on an exact
match; every test still resets and executes. A different installed image exercises programming and verification.
Use `--force-flash` for programming checks and comparisons with CCS, which always programs the image.

The built-in target describes only 64 KiB of SRAM, although this MCU has 256 KiB. The current image,
stacks, and flash algorithm fit in that lower range. Correct the upstream memory map before using
addresses above `0x20010000`; a custom target file was unnecessary for these tests.
[Pinned target definition](https://github.com/probe-rs/probe-rs/blob/v0.32.0/probe-rs/targets/CC13XX_CC26XX_Series.yaml#L281),
[TI device specification](https://www.ti.com/product/CC1354P10).

The framework correctly accepts an expected panic and rejects unexpected panic, missing panic,
and timeout. UsageFault also fails, but is reported as a timeout after one second; the stack trace
identifies the fault handler. A separate debugger read confirmed diagnostic stage `0xffff0001`,
exception 6, and CFSR `0x00010000` (undefined instruction). The existing CCS runner checks those
fields directly; this wrapper does not collect the diagnostic payload automatically.

Upstream `should_panic` accepts a semihosting failure exit, rather than proving that Rust's panic
handler ran. Our global setup executes before the command handshake, where failures abort the
framework instead of satisfying an expected panic. Do not move these reset checks into a per-test
initialization hook. HardFault/debugger errors can abort the whole invocation; they do not necessarily
produce an ordinary failed-case report. Test listing also attaches and verifies/programs as needed.
[Runner implementation](https://github.com/probe-rs/probe-rs/blob/v0.32.0/probe-rs-tools/src/bin/probe-rs/rpc/functions/test.rs),
[framework setup](https://github.com/probe-rs/embedded-test/blob/v0.7.0/src/export.rs).

These are debugger-reset functional tests. They do not establish physical power-on behavior,
electrical/baud accuracy, sleep recovery, or MCU execution latency.

## Timing comparison

Measurements include host tool startup, probe attachment, verified programming, all selected cases,
and cleanup. They exclude Bazel analysis/compilation. Both paths use one board and one debugger
session per invocation. The fair comparison selects the same twelve peripheral/board checks:

```sh
bazel run //tools/debug:hil -- --probe LS4500Q0 --suite drivers --suite integration
bazel run //tools/debug/experiments:embedded_test -- --probe LS4500Q0 --filter driver_ --force-flash
```

The complete custom suite has sixteen passing outcomes, including intentional fault and timeout.
The annotated suite has fourteen normal passing outcomes and separate negative controls, so their
default durations should not be presented as identical coverage. Expected panic also completes
immediately through semihosting, while CCS waits for its diagnostic deadline.

Local measurements on 2026-10-18:

| Same twelve checks | Host duration | Reduction from CCS |
| --- | ---: | ---: |
| CCS, always program/verify (two runs) | 21.70–21.73 s | — |
| Probe-rs, always program/verify (three runs) | 9.76–9.91 s | about 55% |
| Probe-rs, unchanged image verified before tests (two runs) | 6.45–6.65 s | about 70% |

The first CCS driver run spent 4.50 s connecting, 3.32 s programming/verifying, and 8.95 s resetting
between cases. Its remaining startup, request/execution, capture, and cleanup phases took about
4.49 s. Probe-rs's first equivalent run spent 4.65 s in its flash operation and 4.91 s in its test
phase, with about 0.20 s outside those intervals. Its test phase includes reset, startup, and debugger
communication; it is not a measurement of driver execution speed. The biggest saving is debugger
setup/reset overhead, not faster flash programming. Reusing an unchanged image reduces the flash
check to roughly 1.4 s without caching test results.

For context, complete default invocations took 28.77–29.06 s with CCS (sixteen outcomes),
10.32–10.37 s with probe-rs and unconditional programming (fourteen passing cases), and 7.20 s with
probe-rs verifying an unchanged image. The first default run after installing the CCS image took
10.51 s, exercising preverification mismatch and successful reprogramming. These are a few local
samples, not a statistical benchmark.

All fourteen normal cases passed repeatedly; each of the four negative controls returned nonzero
for its intended reason. A nonexistent filter was rejected despite upstream reporting exit zero.
The retained sixteen-case CCS suite also passed freshly, confirming both runners remain
usable. The final prototype also passes host tests, formatting, strict Python typing, Rust Clippy,
and embedded builds. Editor metadata was refreshed for the new target and procedural macros.

## Recommendation

Use this as the candidate for routine peripheral HIL: it is faster, removes manual test dispatch,
and delegates reset/execution to maintained tools. Keep the custom CCS path available during review.
Before replacing it completely, decide whether timeout failure plus a stack trace is sufficient for
faults, or whether to add focused collection of `BOOT_DIAGNOSTIC`. Correct the upstream SRAM map
before using higher RAM addresses. There is no need to implement an XDS110 driver or build another
host test framework to obtain the measured improvement.

Raw results remain in `.results/probe-framework-*-20261018/`; only concise measurements belong here.

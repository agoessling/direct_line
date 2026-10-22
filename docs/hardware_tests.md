# Hardware tests

Run routine HIL tests on one explicitly selected LP-EM-CC1354P10-1 through its XDS110 probe.
Bazel builds the test image and supplies pinned probe-rs and embedded-test dependencies. Hardware
execution is an explicit `bazel run` operation; a cached build never substitutes for a test run.
Use a second board for future RF link tests or occasional board/setup comparisons.

```sh
bazel run //tools/debug:hil -- --probe LS4500Q0
bazel run //tools/debug:hil -- --probe LS4500Q0 --list
bazel run //tools/debug:hil -- --probe LS4500Q0 --filter 'uart::'
bazel run //tools/debug:hil -- --probe LS4500Q0 --force-flash
```

`--filter` selects one test-name substring; empty selections fail. `--list` also accesses hardware
and verifies or programs the image before listing tests. There are no separate named suites.
`--ignored` selects intentional failure controls: these commands are expected to return nonzero.
Run each control separately so an earlier fault or timeout cannot prevent checking later controls:

```sh
bazel run //tools/debug:hil -- --probe LS4500Q0 --ignored --filter harness::unexpected_panic
bazel run //tools/debug:hil -- --probe LS4500Q0 --ignored --filter harness::missing_panic
bazel run //tools/debug:hil -- --probe LS4500Q0 --ignored --filter harness::fault
bazel run //tools/debug:hil -- --probe LS4500Q0 --ignored --filter harness::timeout
```

USB permissions come from `tools/debug/60-direct-line-xds110.rules`, including access to the
XDS110 CMSIS-DAP HID interface. Probe serial numbers remain stable across reconnection. The runner
locks the selected probe for the invocation; other debugger programs must avoid it during that run.
The host tools currently require Linux x86_64. No TI debugger installation is needed.

The runner supplies a checksum-pinned upstream target description with the CC1354P10 SRAM endpoint
corrected from 64 KiB to 256 KiB. Flash algorithms and other target settings are unchanged.
See [the target correction](../third_party/probe_rs/README.md); remove it when the pinned debugger
includes the correct memory map.

## Execution and results

The runner uses one probe-rs process to verify/program the image and execute the selected tests.
Its preverification reads back the ELF's loadable flash bytes and skips programming only when they
match. `--force-flash` always programs and verifies, including the separate CCFG region; unwritten
bytes in affected sectors are preserved. Every selected case resets and executes in either mode.

Each case runs the production reset/vector, memory initialization, TI setup, and clock defaults.
Global setup checks initialized and zeroed RAM before the debugger handshake and samples the initial
RTC epoch. Resetting between cases restores Rust statics, so tests can construct peripherals without
teardown or reclaiming `Board::take()`. Debugger reset is not a physical power cycle.

The upstream embedded-test protocol uses semihosting to announce tests and report completion.
Normal return passes; an assertion panic fails unless the case is marked `#[should_panic]`.
Only the test image's panic handler reports failure through semihosting, after writing
`BOOT_DIAGNOSTIC`. Fault handling retains its distinct diagnostic-and-park path, so a fault cannot
satisfy an expected-panic case. UsageFault currently appears as a timeout, with a stack trace into
the fault handler; the runner does not automatically decode `BOOT_DIAGNOSTIC`.

Upstream `should_panic` recognizes a semihosting failure exit, rather than proving that Rust's panic
handler ran. Keep reset checks in global setup, before the framework handshake, where failure aborts
the invocation. HardFault or debugger errors can abort the whole invocation instead of producing a
failed-case summary. Each case has a deadline, and the host bounds the entire process to 180 seconds.

The small Python wrapper validates a completed, nonempty passing suite rather than relying only on
probe-rs's exit status. Test status and diagnostics appear live. Terminal runs show probe-rs's native
flash progress bars; redirected runs use plain output without bars. A small stderr-only pseudo-terminal
preserves native progress rendering while stdout remains a separate test-event stream.
Test labels and suite outcomes use cyan for running, green for passing, red for failure, and yellow
for skipped cases. The report path is highlighted and elapsed time is dimmed. Wrapper colors are
disabled for redirected streams, `TERM=dumb`, or a nonempty `NO_COLOR` environment variable.

Each run saves these files under ignored `.results/`:

- `stdout.txt`: original test events and any debugger stack traces.
- `stderr.txt`: debugger diagnostics, including terminal control sequences when bars are enabled.
- `target.txt`: a copy of target logging through probe-rs's `--target-output-file` option.
- `report.json`: image hash, probe, command, duration, exit status, suite counts, and errors.

Ordinary failed tests are recorded in the suite counts and return a nonzero exit status. The report's
`error` field describes runner failures, such as timeouts, malformed output, or unexpected process
exits; it is null for a completed failed suite with the expected exit status. The wrapper does not
repeat that exit status as an additional error message.

Probe-rs 0.32 emits test events using libtest-mimic's JSON-lines format. The parser validates the
event kinds and suite counts, rejects malformed JSON-looking records, and permits plain debugger
stack traces. Upstream also prints target logs to the console; the file option copies rather than
redirects them. Reserve JSON-looking stdout lines for test events; use plain text for target logs.
A parsing error fails the run even if probe-rs exits successfully. Listing uses the
upstream plain-text list instead. See the pinned
[probe-rs CLI integration](https://github.com/probe-rs/probe-rs/blob/v0.32.0/probe-rs-tools/src/bin/probe-rs/cmd/run.rs).
Use `--output-dir` to choose a new directory beneath `.results/`. Keep raw reports out of version control.

Tests leave the suite installed on the board. The standalone application remains `//firmware:bringup`.

## Adding tests

Register cases beside their implementation in `firmware/*_test.rs`, inside an inline module marked
`#[embedded_test::tests]`. For example:

```rust
#[embedded_test::tests]
mod gpio {
    #[test]
    fn output_levels_and_pin_isolation() {
        // Configure the pins and assert their behavior here.
    }
}
```

The procedural macro emits registration metadata and dispatch. There is no central case list,
request/result mailbox, or hand-maintained match statement. Timer and UART modules keep shared
helpers for their parameterized instance checks, with named annotated cases beside them. New files
still need a module declaration in `firmware/hil_test.rs` and inclusion in the Bazel target's sources.
Global setup and harness controls live in `hil_test.rs`; peripheral checks stay with their modules.
See [framework dependencies](../third_party/embedded_test/README.md) for the pinned crates and linker
integration. Bazel remains the build system; Cargo files describe dependencies only.

## Measurement scope

UART cases use internal loopback and do not establish external pin timing or baud accuracy. GPIO
checks verify configuration and output latches, not pad voltages. Timer checks use the MCU's own
clock and do not calibrate it against an independent timebase. Initial RTC sampling occurs before
debugger communication, because the RTC continues advancing while the CPU is halted.

Host duration includes debugger startup, attachment, flash verification/programming, reset/startup,
execution, and cleanup. It excludes Bazel analysis/compilation and does not measure MCU execution
latency. Physical power-on, sleep recovery, electrical accuracy, and performance benchmarks remain
separate work.

## Migration evidence and timing

The production migration passed all fourteen normal cases freshly on `LS4500Q0`, both after forced
programming (10.36 s) and with unchanged flash verified first (7.25 s). All four ignored controls
failed for their intended reasons; the full suite passed again afterward. Listing and rejection of
an unmatched filter were checked through the production command. The corrected target description
also permitted reading the final SRAM word at `0x2003fffc`.
All seventeen host test/check targets, host and embedded lint/build checks, and editor metadata
refresh passed.

The prototype at Git commit `75e1aab` repeatedly passed fourteen normal cases on `LS4500Q0`:
two clock variants, GPIO, four GPT assignments, four UART instances, board bring-up, normal return,
and expected panic. Four separate ignored controls rejected unexpected panic, missing panic,
UsageFault, and timeout. An unmatched filter was also rejected. These are prototype measurements,
not new validation of subsequent changes.

The fair comparison selects the same twelve driver/board checks in both implementations:

| Method, measured 2026-10-18 on LS4500Q0 | Host duration | Reduction from CCS |
| --- | ---: | ---: |
| CCS, program and verify | 21.70–21.73 s | — |
| Probe-rs, program and verify | 9.76–9.91 s | about 55% |
| Probe-rs, verify unchanged firmware | 6.45–6.65 s | about 70% |

The main saving was debugger connection/reset overhead. Probe-rs's fourteen normal cases took
7.20 seconds with unchanged flash verified first. The old sixteen-case suite included intentional
fault and timeout outcomes, so its full duration is not a comparison of identical coverage. These
are a few local samples, not a statistical benchmark.

The CCS worker, custom metadata/mailbox protocol, ELF case decoder, and TI debugger runtime have
been retired. Their source and detailed timing experiments remain in Git history at `75e1aab`.
The TI SDK and SysConfig still supply silicon setup and CCFG; they are independent of the debugger.

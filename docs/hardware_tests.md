# Hardware tests

Run routine HIL tests on one explicitly selected LP-EM-CC1354P10-1 board through its XDS110 probe.
Use both boards for future RF link tests or occasional board/setup comparisons. Bazel builds the
test image and supplies the host tools. Tests are explicit `bazel run` operations; a cached build
never substitutes for hardware execution.

```sh
bazel run //tools/debug:hil -- --list
bazel run //tools/debug:hil -- --check-runtime
bazel run //tools/debug:hil -- --probe LS4500Q0
bazel run //tools/debug:hil -- --probe LS4500IY
bazel run //tools/debug:hil -- --probe LS4500Q0 --probe LS4500IY
bazel run //tools/debug:hil -- --probe LS4500Q0 --filter 'uart/*'
```

USB and serial permissions come from `tools/debug/60-direct-line-xds110.rules`. Probe serial numbers
remain stable across reconnection. The runner locks each selected probe for the duration of a run;
other debugger programs must also avoid that probe while tests are executing.

## Execution

One firmware image contains the clock, GPIO, GPT, UART, and bring-up checks. The runner programs and
verifies it once per board. Silicon identification, programming, verification, and all selected
cases share one CCS Scripting session:

1. Reset the board and execute the production startup path.
2. Halt at `hil_ready`, after RAM and chip setup but before test-specific driver construction.
3. Write the case identifier and a fresh execution token to `HIL_REQUEST`.
4. Resume until `hil_done`, `diagnostic_halt` after a panic/fault, or the case timeout.
5. Collect the result and boot/fault/panic diagnostics, then reset for the next case.

Resetting between cases restores Rust statics and permits each case to construct its peripherals
once. Tests do not need driver teardown or a way to reclaim `Board::take()`. Debugger reset is not
a physical power cycle; power-on and sleep/wakeup behavior require separate tests.

The suite owns flash while installed. Hardware tests leave the test firmware on the board.
The normal bring-up application remains `//firmware:bringup`.

## Test protocol

The Rust suite defines the case list once. `HIL_TESTS` contains fixed-size metadata records with a
case identifier, timeout, expected outcome, and name. The host discovers this metadata from the ELF.
Pinned pyelftools reads ELF sections and symbols; the runner decodes the project's test records.
`HIL_REQUEST` selects a case and carries an execution token; `HIL_RESULT` reports the protocol
version, case identifier, token, and execution status. The runner checks the identity of every
result, so a previous case's success cannot satisfy a new request.

Panic and fault details use the existing `BOOT_DIAGNOSTIC` layout. The runner's own timeout is
independent of the firmware timer under test. Dedicated harness cases exercise a normal return,
panic, undefined-instruction fault, and nonterminating test. Expected outcomes are explicit case
metadata; an unexpected failure still fails the suite. The failure breakpoint is reached only
after the production panic/fault handler has completed its diagnostic writes.
Every case retains its PC, result/token, and boot diagnostics. Extra registers and stack unwinding
are collected for unexpected outcomes and intentional panic/fault cases.

To add a case, write a function that returns after its assertions, then add its metadata and dispatch
entry in `firmware/hil_test.rs`. The host discovers the entry without a separate host-side test list.

Results and tool output belong under ignored `.results/`, or in a selected output directory.
Reports record the selected image, probe, per-case outcome, and diagnostics. Retain these as local
or CI artifacts rather than committing raw results.

## Measurement scope

UART cases use internal loopback and do not establish external pin timing or baud accuracy. GPIO
checks verify configuration and output latches; they do not measure voltage at the pads. Timer
checks use the MCU's own timebase and do not calibrate it against an independent clock.

The debugger halts at test boundaries. Clock tests sample the initial RTC epoch before the initial
halt so debugger command latency does not invalidate the startup check. No performance benchmarks
or statistical CPU profiler are implemented by this initial harness. Host-side phase timings include
debugger communication and are not measurements of firmware execution latency.

## Host tools

The backend uses CCS Scripting 21.0 bundled with pinned TI UniFlash 9.6. Bazel supplies Python 3.14,
TI's typed scripting package, its Node/CloudAgent runtime, and the pinned websockets dependency.
UniFlash stores CloudAgent separately; the repository rule exposes it at the path CCS Scripting
expects. Vendor code remains unmodified. No Java runtime or full CCS IDE installation is needed.
The TI native runtime requires Linux x86_64 and ordinary USB access.
The fetched distribution retains TI's licenses and software manifest under `distribution/docs/`.
`--check-runtime` starts and shuts down the debugger without connecting to a board; CI runs this
alongside ELF case discovery and host checks.
Reset reconnects ICEPick, DAP, and CPU explicitly. One failed reset/reconnect attempt may be retried
before a case starts; reports retain the error. Startup checks and test execution are not retried.
The host supervises detached TI helpers as a Linux child subreaper and kills/reaps any remaining
descendants when the worker exits or exceeds its deadline.

Host tests exercise protocol validation and runner failures without accessing boards. All owned Python
sources have basedpyright checks through Bazel. CI builds the
embedded suite and host runner; only explicitly invoked hardware runs claim on-target results.

## Validation status

On 2026-10-12, all 16 cases passed on both `LS4500Q0` and `LS4500IY` in a single invocation of the
CCS Scripting runner: 32 fresh case executions, one verified flash per board. Both runs exercised recovery after
the intentional panic, UsageFault, and timeout. The final runs required no reset/reconnect retries.
The 14 host runner tests, strict Python checks, formatting/lint checks, and embedded builds passed.
Editor metadata was refreshed. Physical power-on and external UART timing remain unverified by this
suite; these results establish debugger-reset functional behavior.

## Runtime profile

The runner prints each board's elapsed time and stores `duration_s` in the board report. The worker's
`debugger.json` records `timings_s` for connection, identification/programming/verification, cleanup,
and total time. Each case records reset/reconnect, ready/startup checks, execution, and capture times.
Execution includes request and breakpoint setup; it is not pure MCU execution time.

Reproduce a fresh single-board measurement with:

```sh
bazel run //tools/debug:hil -- --probe LS4500Q0
```

The host duration includes tool startup, verified flashing, all cases, and cleanup, but excludes
Bazel analysis/build time. Raw timing reports remain in ignored `.results/` directories.

On 2026-10-13, the snapshot `a181f8b` took approximately 48.49 seconds on `LS4500Q0`, measured from
per-board artifact timestamps in the earlier full run. Two optimized runs took 38.82 and 38.63 seconds
using the new monotonic timer (38.72-second mean): about 9.8 seconds or 20% faster. All 16 cases passed
in each run with no reset retries. End-to-end Bazel commands took 40.31 and 39.93 seconds with build
inputs cached. These are a few local samples, not a statistical benchmark.

Average optimized host-side breakdown:

| Phase | Seconds |
| --- | ---: |
| Debugger startup and connection | 4.54 |
| Silicon identification, programming, verification | 3.38 |
| Reset/reconnect across 16 cases | 22.52 |
| Ready/startup checks across 16 cases | 2.37 |
| Request setup and execution across 16 cases | 4.67 |
| Result/context capture across 16 cases | 0.40 |
| Debugger cleanup | 0.37 |

Worker launch and report handling account for the remaining roughly 0.5 seconds. Reset/reconnect
is the dominant remaining cost; the tested isolation sequence is retained. The improvements remove
repeated debugger connections, unnecessary stack/register capture, and timeout waits for completed
panic/fault diagnostics. Host tests cover stale-result rejection, conditional diagnostic capture,
wrong-silicon rejection, verification failure, and detached-process cleanup. The full 18-target Bazel
test set, host/embedded lint and builds, and editor Python diagnostics passed after these changes.

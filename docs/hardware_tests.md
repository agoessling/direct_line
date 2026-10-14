# Hardware tests

The HIL suite runs on the two LP-EM-CC1354P10-1 boards through their XDS110 probes. Bazel builds the
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
verifies it once per board, then keeps a debugger session open while running the selected cases:

1. Reset the board and execute the production startup path.
2. Halt at `hil_ready`, after RAM and chip setup but before test-specific driver construction.
3. Write the case identifier and a fresh execution token to `HIL_REQUEST`.
4. Resume until `hil_done` or the case timeout.
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
metadata; an unexpected failure still fails the suite.

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
or statistical profiler are implemented by this initial harness.

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

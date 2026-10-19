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
bazel run //tools/debug:hil -- --list --suite smoke
bazel run //tools/debug:hil -- --probe LS4500Q0 --suite drivers --filter 'timer/*'
```

USB and serial permissions come from `tools/debug/60-direct-line-xds110.rules`. Probe serial numbers
remain stable across reconnection. The runner locks each selected probe for the duration of a run;
other debugger programs must also avoid that probe while tests are executing.

Suites are named groups within the same image: `harness` checks the runner, `drivers` checks
peripherals, `integration` checks board bring-up, and `smoke` selects a short cross-section (normal
return, GPIO, and board bring-up). With no `--suite`, every case is selected. Repeat `--suite` to
select the union of groups; each case runs once in declaration order. `--filter` narrows that
selection. Unknown suites and empty selections fail before opening a probe. `--list` shows each
case's memberships and accepts the same selection options.

## Execution

One firmware image contains the clock, GPIO, GPT, UART, and bring-up checks. The runner programs and
verifies it once per board. Silicon identification, programming, verification, and all selected
cases share one CCS Scripting session:

1. Reset the board and execute the production startup path.
2. Halt at `hil_ready`, after RAM and chip setup but before test-specific driver construction.
3. Write the case identifier and a fresh execution token to `HIL_REQUEST`.
4. Resume until `hil_done` or the case timeout.
5. Collect the result and boot/fault/panic diagnostics, then reset for the next case.

Resetting between cases restores Rust statics and permits each case to construct its peripherals
once. Tests do not need driver teardown or a way to reclaim `Board::take()`. Debugger reset is not
a physical power cycle; power-on and sleep/wakeup behavior require separate tests.

Between cases, the runner disconnects CPU, DAP, and ICEPick, pulses nSRST for 50 ms using the pinned
TI `xds110reset` utility, then reconnects ICEPick, DAP, and CPU. CCS remains open throughout. The
utility receives the same explicit probe serial as the CCS configuration and has a five-second
process timeout. A failed reset/reconnect can be retried once before test execution. Fresh boot,
request, and result checks remain mandatory after reconnecting.

The suite owns flash while installed. Hardware tests leave the test firmware on the board.
The normal bring-up application remains `//firmware:bringup`.

## Test protocol

The `hil_tests!` declaration in `firmware/hil_test.rs` generates both the case metadata and function
table. `HIL_TESTS` contains 128-byte records with a case identifier, timeout, expected outcome, name,
and suite memberships. IDs are assigned from declaration order and are local to the image; use names
for selection. The host discovers this metadata from the ELF.
Pinned pyelftools reads ELF sections and symbols; the runner decodes the project's test records.
`HIL_REQUEST` selects a case and carries an execution token; `HIL_RESULT` reports the protocol
version, case identifier, token, and execution status. The runner checks the identity of every
result, so a previous case's success cannot satisfy a new request.

`tools/debug/protocol.py` names the shared version, status, expected-outcome, and boot-stage values.
Matching Rust definitions remain beside the firmware records, with comments identifying the Python
counterpart; there is no generated schema. Requests use typed dictionaries; mutable dataclasses
collect worker observations, timings, and run results. Reports use `dataclasses.asdict()` directly:
board reports contain a nested `run`, case records contain their selected metadata under `case`,
and uncollected fields are JSON null. Board success requires a successful run and no board-level
error; it is derived in Python rather than stored as another JSON flag. Incoming worker JSON is
validated before use and retains raw diagnostic words. Validation decodes result and boot records
into frozen dataclasses, selecting fault-register or panic-source-location fields according to the
boot stage. Invalid word counts,
out-of-range words, unknown status/stage values, and unsupported protocol versions fail validation.

Panic and fault details use the existing `BOOT_DIAGNOSTIC` layout. The runner's own timeout is
independent of the firmware timer under test. Dedicated harness cases exercise a normal return,
panic, undefined-instruction fault, and nonterminating test. Expected outcomes are explicit case
metadata; an unexpected failure still fails the suite. Panic/fault cases wait for their deadline,
then the host halts the CPU and checks the diagnostic record.
Every case retains its PC, result/token, and boot diagnostics. Extra registers and stack unwinding
are collected for unexpected outcomes and intentional panic/fault cases.

To add a case, write a function that returns after its assertions and add one registration:

```rust
"gpio/new_check" => {
    run: |_| gpio_test::new_check(),
    suites: [drivers, smoke],
    timeout_ms: 1000,
},
```

Normal return means pass. Add `expect: Panic,`, `expect: Fault,` (UDF UsageFault), or
`expect: Timeout,` only for intentional harness checks. The macro generates IDs, counts, and dispatch;
there is no separate match statement or host case list. A noncapturing closure adapts existing
functions and parameters to `fn(&TestContext)`; clock tests use the context's initial RTC epoch.
New source files still need a Rust `mod` declaration and inclusion in the Bazel target's `srcs`.

`firmware/hil_registry.rs` holds the macro and metadata layout. Names are ASCII (at most 51 bytes),
suite names are ASCII identifiers (at most 63 bytes including the generated spaces), and deadlines
are 1–60,000 ms. Expected outcomes use a `repr(u32)` enum; debugger-written requests stay integer
records. Registration is entirely static, with one function-pointer call per case. No procedural
macro, linker section, or runtime registration is involved. Suites select execution on the host;
they do not remove cases from the image. Rebuild the runner and image together when changing this ABI.

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

On 2026-10-17, the macro-generated registry passed all 16 cases freshly on `LS4500Q0` in 39.08 seconds.
A separate `--suite smoke` run passed its three cases in 13.75 seconds; both runs had no reset retries.
The 22 host runner tests include linked-image discovery, suite unions/filtering, and malformed metadata.
All 18 Bazel test targets, strict Python checks, formatting, and host/embedded lint and builds passed.
Editor metadata was refreshed for the registry module.
The subsequent named-value/decoded-record cleanup passed all four harness cases freshly on
`LS4500Q0`, covering normal completion, panic, UsageFault, and timeout. All 18 Bazel test targets
and host/embedded lint/build checks passed, including 28 runner and seven debugger-worker unit tests.

On 2026-10-12, all 16 cases passed on both `LS4500Q0` and `LS4500IY` in a single invocation of the
CCS Scripting runner: 32 fresh case executions, one verified flash per board. Both runs exercised recovery after
the intentional panic, UsageFault, and timeout. The final runs required no reset/reconnect retries.
The 14 host runner tests, strict Python checks, formatting/lint checks, and embedded builds passed.
Editor metadata was refreshed. Physical power-on and external UART timing remain unverified by this
suite; these results establish debugger-reset functional behavior.

## Runtime profile

The runner prints each board's elapsed time and stores `run.duration_s` in the board report. The
worker's `debugger.json` records connection, programming/verification, cleanup, and total timings.
Each case records reset/reconnect, ready/startup checks, execution, and capture times. These include
debugger communication and are not measurements of MCU latency. Bazel analysis/build time is excluded.

On 2026-10-18, using the pinned TI `xds110reset` utility reduced the complete 16-case suite on
`LS4500Q0` from 39.54 to 28.26 seconds (28.5%). All cases passed without reset retries, including
intentional panic, UsageFault, and timeout recovery. The disconnect/reconnect order and default
JTAG clock remain unchanged. The utility's hash is included in report provenance. Raw reports stay
in ignored `.results/` directories.

Reproduce a fresh measurement with:

```sh
bazel run //tools/debug:hil -- --probe LS4500Q0
```

Detailed reset measurements and the optional probe-rs benchmark are documented in
[Debugger timing experiments](debugger_experiments.md).

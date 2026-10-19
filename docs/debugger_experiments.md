# Debugger timing experiments

The subsequent [embedded-test experiment](embedded_test_experiment.md) verifies flashing and runs
the shared driver checks through probe-rs. The preflight limitations below describe the earlier stage.

## CCS measurements

The runner prints each board's elapsed time and stores `run.duration_s` in the board report. The worker's
`debugger.json` records `timings_s` for connection, identification/programming/verification, cleanup,
and total time. Each case records reset/reconnect, ready/startup checks, execution, and capture times.
Execution includes request and breakpoint setup; it is not pure MCU execution time.
Each case also records `reset_attempt_timings_s`, with one entry per reset attempt. These entries
split breakpoint removal, CPU/DAP/ICEPick disconnects, the reset pulse, and
ICEPick/DAP/CPU reconnects, and halt. Durations include synchronous CCS/GEL work inside each call;
failed calls retain their elapsed time. Retry delays remain part of the aggregate reset duration.

Reproduce a fresh single-board measurement with:

```sh
bazel run //tools/debug:hil -- --probe LS4500Q0
```

The host duration includes tool startup, verified flashing, all cases, and cleanup, but excludes
Bazel analysis/build time. Raw timing reports remain in ignored `.results/` directories.

On 2026-10-13, the snapshot `a181f8b` took approximately 48.49 seconds on `LS4500Q0`, measured from
per-board artifact timestamps in the earlier full run. The current implementation took 39.13 seconds
using the monotonic timer: about 9.4 seconds or 19% faster. All 16 cases passed without reset retries.
The end-to-end Bazel command took 40.58 seconds with build inputs cached. These are local samples,
not a statistical benchmark.

The earlier terminal-breakpoint variant averaged 38.72 seconds across two runs. We removed its
firmware symbol and host dependency to keep the startup/test interface simpler; the latest run was
only about 0.4 seconds slower. The original panic/fault parking loops are restored.

2026-10-13 host-side breakdown:

| Phase | Seconds |
| --- | ---: |
| Debugger startup and connection | 4.54 |
| Silicon identification, programming, verification | 3.39 |
| Reset/reconnect across 16 cases | 21.93 |
| Ready/startup checks across 16 cases | 2.42 |
| Request setup and execution across 16 cases | 5.69 |
| Result/context capture across 16 cases | 0.40 |
| Debugger cleanup | 0.32 |

Worker launch and report handling account for the remaining roughly 0.5 seconds. Reset/reconnect
is the dominant remaining cost; the tested isolation sequence is retained. The retained improvements
remove repeated debugger connections and unnecessary stack/register capture. Host tests cover
stale-result rejection, conditional diagnostic capture, wrong-silicon rejection, verification failure,
and detached-process cleanup. All 18 Bazel test targets and host/embedded lint and builds passed.

### Reset breakdown

On 2026-10-18, two instrumented full runs on `LS4500Q0` took 39.18 and 39.55 seconds. All 32 case
executions passed without reset retries. Reset/reconnect averaged 1.376 seconds per case, ranging
from 1.343 to 1.419 seconds. The sequence and reset type were unchanged.

| Reset operation | Mean per case |
| --- | ---: |
| Remove breakpoints | 11.9 ms |
| Disconnect CPU | 45.4 ms |
| Disconnect DAP | 256.3 ms |
| Disconnect ICEPick | 4.2 ms |
| Query reset availability | 3.4 ms |
| Board reset | 681.0 ms |
| Reconnect ICEPick | 305.5 ms |
| Reconnect DAP | 6.8 ms |
| Reconnect CPU | 58.2 ms |
| Halt CPU | 2.9 ms |

Board reset, ICEPick reconnect, and DAP disconnect account for about 90% of reset time. Their
observed ranges were 671–686 ms, 295–315 ms, and 248–265 ms respectively. These are host API
durations; they do not measure the physical reset pulse or establish which internal driver waits
are necessary. Removing the reset-availability query would save only about 55 ms across 16 cases.

The pinned TI package's `ccs_base/common/targetdb/devices/cc1354p10.xml` disables CPU reset and
`Support System Reset While Connected`, while enabling board reset. The relevant GEL sources under
`ccs_base/emulation/gel/` contain no explicit sleeps in this sequence:

- `cc26x4_xds.gel`: board reset disconnects CPU, DAP, and ICEPick; CPU reconnect initializes the
  debugger memory map and checks whether an engineering-device trim workaround is needed.
- `cc26xx_icepick.gel`: ICEPick reconnect sets `WAKEUPMCU` to keep the MCU domain active.
- `cc26xx_connect_util.gel`: connection helpers check state and invoke GEL connect/disconnect.

The source audit does not establish a safe way to omit the expensive calls. A future experiment
could compare TI's built-in `Board Reset (automatic connect/disconnect)` against our explicit
sequence, but it also restores debug state and uses a different connection-restoration order.
Batching may reduce host round trips; it does not inherently remove the underlying reset costs.
At that point, no alternate reset mode or shortened sequence had been validated. Worker unit tests,
formatting, lint, and strict Python type checking passed with the added instrumentation.

### Reset alternatives measured on 2026-10-18

The same 16-case suite ran on `LS4500Q0` with each configuration below. All cases passed without
reset retries. Durations include connection, one flash/verify, all cases, and cleanup; they exclude
Bazel startup/build time. The 8.5 MHz row describes the requested configuration, not a measured TCK.

| Configuration | Suite duration | Sum of case reset/reconnect durations |
| --- | ---: | ---: |
| Existing CCS Board Reset | 39.54 s | 22.16 s |
| CCS Board Reset (free run) | 37.49 s | 20.88 s |
| Existing Board Reset, configured 8.5 MHz TCLK | 38.71 s | 21.95 s |
| External 50 ms pin pulse, initial experiment | 28.91 s | 11.99 s |
| External 50 ms pin pulse, retained implementation | 28.26 s | 11.81 s |

The retained implementation saves 11.27 seconds (28.5%) against the fresh baseline. The worker's
reset call takes 64–67 ms including process startup/wait, compared with about 681 ms for CCS Board
Reset. Five standalone 50 ms pulses took 52.5–53.2 ms each. An invalid probe serial returned exit code 1;
unit tests also check process failure, timeout, explicit selection, and bounded retries.
The existing disconnect/reconnect order and default debug clock remain unchanged. The utility is
already part of the pinned TI runtime, and its hash is included in report provenance.

Raw reports are under ignored `.results/reset-*-20261018/` directories. Experimental source copies
are under `.results/reset-experiments-20261018/`; temporary Bazel targets were removed. TI documents
the reset utility and configurable pulse in [SPRUI94 §3.7.3.1](https://www.ti.com/lit/ug/sprui94/sprui94.pdf).

### Probe-rs preflight

The checksum-pinned Bazel experiment with probe-rs 0.32.0 recognizes the onboard XDS110
probes as CMSIS-DAP. On `LS4500Q0`, a bounded probe-only `DAP_Info` query reported CMSIS-DAP 1.2.0
and capabilities `0x33`, including JTAG and SWD. That query did not access the target. Initial
probe-rs access stopped at root-only HID-node permissions. Installing the repository's updated
udev rules enabled unprivileged access without unplugging the boards.

With those permissions, probe-rs attached to `LS4500Q0` over JTAG at a requested 1 MHz and read the
expected ICEPick ID (`0x1bb7802f`). Reset-and-halt, resume, and an instruction breakpoint at
`hil_ready` worked. At that breakpoint, the request was `[0xffffffff, 0]`, the result was
`[1, 0xffffffff, 0, 0]`, and boot diagnostics reported APPLICATION with zero fault fields. An
instruction breakpoint installed before reset was not effective afterward in this CLI experiment;
explicitly installing it after reset worked, matching the existing HIL runner's sequence.

Three paired CLI measurements compared otherwise identical sessions with zero versus ten reset
commands. The estimated incremental cost was 169.0, 160.9, and 164.6 ms per reset (median 164.6 ms).
All 30 reset commands completed without reported errors, and each session's final silicon-ID read
matched. Each reset halted in ROM; these timing loops did not execute driver tests or run through
application startup between resets. This measurement includes frontend scheduling and command
handling, excludes Bazel startup, and is not a reset-to-ready or MCU timing measurement. For context,
the retained CCS runner spends about 738 ms per case on pin reset plus disconnect/reconnect.

The experiment used probe-rs 0.32.0's existing CMSIS-DAP support; no XDS110 driver was added.
Flashing, CCFG programming, and a complete probe-rs HIL run remain unverified. The production runner
still uses CCS; migration would first need to preserve its fresh-state checks and failure capture.
Timing transcripts and paired results are in `.results/probe-rs-reset-benchmark-20261018/`.
Afterward, the CCS runner passed all six smoke/harness cases in 17.91 seconds without reset retries
(`.results/hil-after-probe-rs-20261018/`), including intentional panic, fault, and timeout recovery.

Upstream has a [CC1354P10 target and main-flash/CCFG algorithms](https://github.com/probe-rs/probe-rs/blob/v0.32.0/probe-rs/targets/CC13XX_CC26XX_Series.yaml#L281).
Its [TI reset sequence](https://github.com/probe-rs/probe-rs/blob/v0.32.0/probe-rs/src/vendor/ti/sequences/cc13xx_cc26xx.rs)
waits 1 ms before rebuilding the debug connection; this is not an end-to-end timing measurement.
The sequence uses full four-wire JTAG successfully with the present board wiring. The upstream
target describes only 64 KiB RAM, so its memory map needs checking before adoption. Historical preflight
inputs and reports remain under ignored `.results/probe-rs-preflight-2026-10-18/`; probe-rs is not a
production dependency.

The retained reproducer lives in `tools/debug/experiments/`. It uses the main repository's pinned
Bazel/Python setup and downloads the probe-rs binary only for explicitly selected experiment targets:

```sh
bazel run //tools/debug/experiments:benchmark -- \
  --serial LS4500Q0 --output-dir .results/probe-rs-reset-comparison
```

Use a fresh output directory for each run. Inspect the saved CLI transcripts for errors and the
expected silicon-ID read; a zero process exit alone does not validate each debugger command.
See [the experiment instructions](../tools/debug/experiments/README.md) for scope and limitations.

The retained Bazel target was rerun on 2026-10-18: all 30 resets completed and all six sessions read
the expected silicon ID, with a median incremental cost of 163.0 ms per reset. Raw transcripts and
results are in `.results/experiment-commit-validation-20261018/`. All 21 host check/test targets and
host/embedded lint and builds passed with the experiment package included.
The subsequent CCS smoke/harness selection passed all six cases in 18.03 seconds without reset
retries (`.results/experiment-commit-ccs-recovery-20261018/`).

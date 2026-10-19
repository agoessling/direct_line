# Debugger and test framework experiments

These opt-in Linux x86-64 targets evaluate probe-rs 0.32.0 with the onboard XDS110 CMSIS-DAP
interface. The production HIL runner remains `//tools/debug:hil` and does not depend on them.

Install `tools/debug/60-direct-line-xds110.rules` and reload/trigger udev as documented in
`docs/hardware_tests.md`. Stop other debugger sessions before running these commands.

## Annotated tests

The experimental image uses `embedded-test` attributes for registration and probe-rs for flashing,
resetting, and running cases in one session. It shares the production startup and peripheral checks.

```sh
# Run all 14 positive cases: 12 driver checks, normal return, and an expected panic.
bazel run //tools/debug/experiments:embedded_test -- --probe LS4500Q0

# Select the 12 driver checks for comparison with the CCS drivers/integration suites.
bazel run //tools/debug/experiments:embedded_test -- --probe LS4500Q0 --filter driver_ --force-flash

# Discovery runs through the device; this also verifies and, if needed, flashes the image.
bazel run //tools/debug/experiments:embedded_test -- --probe LS4500Q0 --list
```

Each run selects the probe explicitly and compares the ELF's loadable flash bytes, including CCFG.
A match skips programming; a mismatch programs and verifies the image, preserving unwritten sector bytes.
All selected tests reset and execute on every invocation. Use `--force-flash` to exercise programming
even when the image matches. The runner writes `console.txt` and `report.json` beneath an automatically named
`.results/embedded-test-*` directory. Use `--output-dir .results/NAME` to choose a fresh directory.
The report includes the ELF hash, command, process exit status, and host process duration; this timing
includes attachment, flashing, verification, and execution, but excludes Bazel work. It is not MCU
execution latency. The outer process deadline is 180 seconds.

One optional filter selects test names by substring. Multiple filters are rejected because the pinned
probe-rs joins them into one string. A successful test run requires a completed JSON suite report with
at least one passed case and no failures; selecting no cases fails. The default suite skips
four intentional failures: `harness_fault`, `harness_timeout`, `harness_unexpected_panic`, and
`harness_missing_panic`. Run these individually with `--ignored`; each must return a nonzero exit
status and produce its failure report:

```sh
bazel run //tools/debug/experiments:embedded_test -- \
  --probe LS4500Q0 --ignored --filter harness_fault
bazel run //tools/debug/experiments:embedded_test -- \
  --probe LS4500Q0 --ignored --filter harness_timeout
bazel run //tools/debug/experiments:embedded_test -- \
  --probe LS4500Q0 --ignored --filter harness_unexpected_panic
bazel run //tools/debug/experiments:embedded_test -- \
  --probe LS4500Q0 --ignored --filter harness_missing_panic
```

`firmware/embedded_test.rs` contains the annotated cases. `third_party/embedded_test/` defines the
pinned framework dependencies and Bazel integration. This image replaces the installed firmware;
rerun `//tools/debug:hil` to restore and validate the production test image.

## Reset transport benchmark

```sh
bazel run //tools/debug/experiments:probe_rs -- list
bazel run //tools/debug/experiments:benchmark -- \
  --serial LS4500Q0 --output-dir .results/probe-rs-reset-comparison
```

The benchmark attaches through four-wire JTAG at 1 MHz, halts the selected CC1354P10, and compares
three pairs of persistent CLI sessions: zero reset commands versus ten reset commands. Each session
ends by reading the silicon identification register. It writes transcripts and a JSON report to the
specified ignored results directory. Use a fresh output directory to preserve previous measurements.
The process lock coordinates probe ownership with the production runner on this machine.

This resets and halts the board but does not flash it. It leaves the existing firmware installed;
run the production HIL runner afterward to check recovery. The benchmark cannot establish flash/CCFG
programming support or validate the complete test suite.

The reported estimate is the paired wall-time difference divided by ten. It includes CLI, USB, and
debugger recovery overhead; it does not measure physical reset duration or reset-to-application-ready
latency. A successful process exit and identity read are useful transport checks, not evidence that
application startup completed after each reset. Inspect the transcripts for debugger errors.

# Debugger reset experiments

These opt-in Linux x86-64 targets evaluate probe-rs 0.32.0 with the onboard XDS110 CMSIS-DAP
interface. The production HIL runner remains `//tools/debug:hil` and does not depend on them.

Install `tools/debug/60-direct-line-xds110.rules` and reload/trigger udev as documented in
`docs/hardware_tests.md`. Stop other debugger sessions before running these commands.

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

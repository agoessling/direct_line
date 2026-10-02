# Direct Line

A targeted Rust foundation for a low-latency CC1354P10 point-to-point radio link.
The intended link uses 10–50-byte packets over sub-GHz and 2.4 GHz PHYs. Firmware
uses `no_std`, static ownership, and concrete drivers; no heap or scheduler is
required for the initial milestones.

The standalone image initializes memory, factory trim, clocks, GPIO, timers, and polling UART0
at 115200 8N1. It reports bring-up checks over serial, then echoes received bytes while blinking
both LEDs on timer events. Board runners, logging, and RF remain later milestones.
Required silicon initialization uses the pinned TI SDK behind one Rust FFI call; see the
[startup audit](firmware/STARTUP.md). The earlier C++ firmware remains in history.

```sh
bazel test //...
bazel build --config=lint //...
bazel build --config=m33 --config=lint //foundation/... //firmware/...
tools/quality/check
bazel run //tools/metadata:refresh
```

See [development instructions](docs/development.md) and [project direction](AGENTS.md).

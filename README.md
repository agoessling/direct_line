# Direct Line

A targeted Rust foundation for a low-latency CC1354P10 point-to-point radio link.
The intended link uses 10–50-byte packets over sub-GHz and 2.4 GHz PHYs. Firmware
uses `no_std`, static ownership, and concrete drivers; no heap or scheduler is
required for the initial milestones.

This first stage provides reproducible Rust/Bazel builds, host tests, formatting,
linting, CI, and editor-neutral metadata. Startup and peripheral drivers follow
in subsequent commits. The earlier C++ firmware remains available in Git history.

```sh
bazel test //...
bazel build --config=lint //...
bazel build --config=m33 --config=lint //foundation/...
tools/quality/check
bazel run //tools/metadata:refresh
```

See [development instructions](docs/development.md) and [project direction](AGENTS.md).

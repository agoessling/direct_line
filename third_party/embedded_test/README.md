# Annotated-test dependencies

This resolution-only Cargo manifest feeds Bazel `crate_universe`; firmware still builds through
`//firmware:embedded_test`. There is no parallel Cargo firmware project or handwritten crate source.
`Cargo.lock` pins the complete dependency graph and package checksums.

The experiment pins `embedded-test` 0.7.0, whose macro implementation uses Syn 2 and builds with the
repository's Rust 1.90 toolchain. Newer 0.7.2 selects the newer Syn 3 macro stack; adopting it is a
separate dependency update. Default features are disabled: only semihosting is enabled, and the
existing startup retains its panic diagnostic before the test-only semihosting abort.

The direct `embedded-test-linker-script` dependency exposes the unmodified upstream `embedded-test.x`
file to Bazel. The firmware linker target concatenates it before `memory.ld`, so metadata is retained
before the board script's orphan-section check. It adds no alternative startup or memory layout.

To update the lock after deliberately changing dependency versions:

```sh
CARGO_BAZEL_REPIN=1 bazel build --config=m33 //firmware:embedded_test
```

Review both Cargo and Bazel lock changes, then run `tools/quality/check` and fresh hardware tests.
Framework behavior and registration are documented in the upstream
[embedded-test README](https://github.com/probe-rs/embedded-test/tree/v0.7.0).

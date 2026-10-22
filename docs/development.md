# Development tools

Bazel is authoritative. Linux x86_64, Bazelisk, Git, and the documented host
prerequisites are required. Bazel fetches the Rust compiler, embedded standard
library, Python runtime, and CI formatting/lint tools. Their versions and hashes
are recorded in `MODULE.bazel`, `MODULE.bazel.lock`, and `.bazelversion`.
A separate rustup installation is unnecessary.

Hardware execution is an explicit `bazel run //tools/debug:hil -- --probe SERIAL` operation.
The runner builds its Cortex-M33 embedded-test suite through the existing platform transition,
verifies or programs it through probe-rs, and resets between cases. See
[hardware tests](hardware_tests.md) for test selection, debugger
dependencies, and the distinction between reset tests and physical power-on validation.

## Build and checks

```sh
bazel test //...
bazel build --config=lint //...
bazel build --config=m33 --config=lint //foundation/... //firmware/...
tools/quality/check
```

`tools/quality/check` runs the three commands above; CI uses the same entry point.
`bazel test //...` runs host tests, Ruff checks, basedpyright checks, and repository-wide Buildifier
and clang-format checks. `python_checks` adds formatting, lint, and type checks for each declared
Python source set, including the debugger runner, editor metadata generator, and CCFG image test.
`--config=lint` applies the upstream Rustfmt and Clippy aspects to existing Rust
targets, using their declared sources and dependencies. New Rust libraries,
binaries, and tests selected by `//...` participate without separate lint targets.
The configuration adds check outputs to the normal build outputs, so embedded
compilation still runs. Checks report failures without changing sources.

Host and M33 lint runs check their respective conditional compilation paths;
this does not enumerate every possible feature combination. As with ordinary
Bazel wildcard builds, incompatible targets are skipped and targets tagged
`manual` need explicit selection. The embedded invocation in `tools/quality/check`
covers both the foundation and firmware packages.

`//:build_files` uses `buildifier_prebuilt`'s workspace discovery to check BUILD,
MODULE.bazel, and other Starlark files across packages. `//:c_format` discovers
owned `.c` and `.h` files using a small shell runner. Both cover new packages and
untracked files without additional check declarations. They skip root hidden
directories and `bazel-*` outputs, and do not follow directory symlinks; the C
check also excludes `third_party`. Buildifier still checks our build integration
under `third_party`.

These two tests run locally and uncached because discovery reads the checkout
rather than a declared source list. This trades cached formatting results for
automatic coverage; the formatter executables remain pinned and Bazel-fetched.
Python checks use `bazel_skylib`'s `native_test` through `tools/quality/checks.bzl`.
They declare sources per package and remain cacheable; include new Python sources in those declarations.
Basedpyright 1.39.9 uses the same `pyrightconfig.json` as the editor, with recommended diagnostics
and warnings treated as failures. Its Bazel launcher reuses SysConfig's pinned Node and the pinned
Python interpreter. Run `bazel run //tools/quality:basedpyright` to check all owned Python files.
The editor's generated import paths still come from `.tools/project.json`.

To apply formatting, run the relevant tool with explicit file paths:

```sh
bazel run //tools/quality:rustfmt -- foundation/lib.rs
bazel run //tools/quality:ruff -- format tools/metadata/refresh.py
bazel run //tools/quality:buildifier -- BUILD tools/quality/BUILD.bazel
```

The Ruff and Rustfmt launchers resolve Bazel-provided tools and configuration,
then run in the workspace so relative paths work. The Ruff launcher disables
its own cache to avoid creating `.ruff_cache` in the checkout. Buildifier uses
its upstream launcher, which preserves the caller's working directory. All accept stdin using
each tool's normal arguments. The project pins Rustfmt, Ruff, and Buildifier
versions and configuration. Ruff uses the 0.16.0 binary packaged by
`ruff_prebuilt` 0.16.0.1; Buildifier remains at 10.1.0.

No editor configuration or language-server installation is maintained here.
Generated register output is validated through generator tests and compilation
rather than formatted as handwritten source.

## Editor-neutral metadata

```sh
bazel run //tools/metadata:refresh
```

Refresh after changing BUILD files, dependencies, toolchains, or register inputs.
The command generates ignored local files:

- `rust-project.json`: rules_rust's configured crate graph, M33 target, features,
  generated sources, dependencies, and matching Rust library source paths.
- `.tools/project.json`: metadata version 1, the pinned compiler path, Python
  import roots from Bazel runfiles, workspace scanning exclusions, and the
  project's per-language stdin formatting commands.

`tools/metadata/project.json` declares the static editor-neutral settings. The
refresh script adds build-derived, machine-local paths to this template.

`python_exclude_paths` contains workspace-relative glob patterns for Python
source discovery. Editors should append these to their normal exclusions.
The project excludes `bazel-*` output symlinks from scanning; imported libraries
remain available for definition lookup through the generated import roots.

The primary Rust view is the embedded configuration. Host-only configurations
are checked separately through Bazel. Refresh removes optional `flycheck`
runnable metadata unsupported by older analyzers without changing the crate
graph. CI verifies that this metadata can be generated.

Neovim configuration and language-server installation belong to `~/.config/nvim`
and workstation provisioning to `~/defaults`. Configure rust-analyzer to load
`rust-project.json` and disable Cargo-based check-on-save for this Bazel project.
Use the generated Python import roots for the Python language server and Starpls
for Starlark. Format-on-save selects an argv array from `format_commands` by
language (`rust`, `python`, or `starlark`), substitutes the absolute buffer
path for `{path}` within each argument, and passes source on stdin with this
checkout as the working directory. Commands return formatted source on stdout.
A nonzero exit must abort saving instead of silently accepting unformatted text.
Semantic language-server diagnostics supplement compiler and CI lint gates;
they are not additional CI requirements.

Tests of actual editor navigation/save behavior belong with the editor
configuration. This project tests metadata generation and provides the same
formatting commands to any editor. Generated register files are read-only build
products: change the generator or XML inputs instead. Assembly inside Rust strings
and linker-script symbols have no cross-language semantic navigation bridge;
use source search for those boundaries.

## Narrow embedded C boundary

`toolchains_arm_gnu` supplies Arm GNU 13.2.Rel1 only for the M33 platform
(about 171 MiB compressed on Linux x86_64). Its upstream Bazel 9 fix is pinned
until released. We use its configuration rule directly to retain DWARF in
optimized links; the convenience macro strips it unconditionally. No LLVM, Zig, or extra Java runtime is
introduced. Host compilation retains the existing host toolchain behavior.

C uses Cortex-M33 Thumb, FPv5 single precision, and the hard-float ABI matching
Rust's `thumbv8m.main-none-eabihf`. The final Rust link uses GNU via the selected C
toolchain with `-nostdlib`: no C runtime/startup, libc, or libgcc is added. The
rules_rust linker-preference flag also affects host tools, so forcing Rust LLD
with that global flag is unsuitable here. `//foundation/ffi:link_check` verifies
C archive extraction and a Rust-to-C float call; it is not a bootable image.

Owned C files use `//:c_format` and the pinned standalone clang-format 19
binary (about 4 MiB), fetched through Bazel's standard `http_file` rule. Vendor
and generated files are not reformatted. Apply formatting with
`bazel run //tools/quality:clang_format -- -i path/to/file.c`.

Metadata refresh also writes ignored `compile_commands.json` directly from
Bazel's `CppCompile` action graph, including target flags and generated sources.
This small translation avoids maintaining a separate compiler configuration;
the evaluated Hedron extractor still uses removed native Python rules on Bazel 9.
Clangd needs permission to query the pinned `arm-none-eabi-gcc` for its built-in
include paths (the editor's `--query-driver` setting). C formatting is exported
under `format_commands.c`. Cross-language Rust-FFI-to-C definition lookup is not
provided by rust-analyzer; navigate the external function name within C instead.

## TI configuration generation

`firmware/config/board.syscfg` selects the supported LaunchPad clock/power choices.
Bazel runs SysConfig 1.28.1.4785 against SimpleLink Low Power F2 SDK 8.33.00.16,
using the installer's bundled Node. Both downloads are checksum-pinned. Only
`ti_devices_config.c` enters the firmware; generated linker/library suggestions,
RTOS support, and TI board drivers are not consumed. Generation executes in the
Bazel sandbox with SDK metadata/templates declared as inputs. SysConfig reports
omitted RTOS components during discovery; this configuration selects `--rtos none`.

The SDK archive is about 714 MiB and SysConfig's installer about 161 MiB compressed.
These are the largest cold-download costs; subsequent builds use Bazel's cache.
This prototype uses TI's complete published distributions rather than maintaining
repacked subsets. No GUI, Java, or system Node installation is required, although
TI ships GUI files inside the installer. Build hosts are currently Linux x86_64.

`bazel test //firmware:ccfg_test` cross-builds the real LED ELF via a platform
transition and checks the section's fixed address, 124-byte size, and file-backed
loadable mapping. SysConfig owns its values; there is no golden word snapshot to
update when a board setting changes. Rust drivers check the specific fields their
implementation requires. Changes to boot/debug/security settings still need
configuration review and boot testing; the structural test cannot validate them.

# Probe-rs target correction

Probe-rs 0.32.0 describes CC1354P10 SRAM as 64 KiB. The device has 256 KiB at
`0x20000000..0x20040000`, matching `firmware/memory.ld`. Debugger memory metadata must cover the
whole region even when a small test image happens to fit inside the first 64 KiB.

`repositories.bzl` downloads the checksum-pinned
[upstream target family](https://github.com/probe-rs/probe-rs/blob/v0.32.0/probe-rs/targets/CC13XX_CC26XX_Series.yaml)
and changes only the CC1354P10 SRAM endpoint. It rejects an unexpected source layout and preserves
all other variants, flash algorithms, and configuration. The HIL runner supplies the generated
`@probe_rs_targets//:cc1354p10.yaml` to probe-rs as a target description override.

Remove this repository rule and runner override when the pinned probe-rs release has the correct
memory map. Review the upstream description when updating the debugger version; the source and
binary pins should move together.

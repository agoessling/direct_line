"""Pinned probe-rs target description with the CC1354P10 SRAM size corrected."""

def _probe_rs_targets_impl(ctx):
    ctx.download(
        url = "https://raw.githubusercontent.com/probe-rs/probe-rs/v0.32.0/probe-rs/targets/CC13XX_CC26XX_Series.yaml",
        output = "upstream.yaml",
        sha256 = "72b083dd5131119b3813c64fa86c10f8e00fd360c729b065f7da83ab583d7478",
    )
    source = ctx.read("upstream.yaml")
    marker = "- name: CC1354P10\n"
    if source.count(marker) != 1:
        fail("Expected one CC1354P10 variant in the pinned probe-rs target description")
    start = source.find(marker)
    end = source.find("\n- name:", start + len(marker))
    if end == -1:
        fail("Expected another variant after CC1354P10 in the pinned target description")
    variant = source[start:end]
    old_ram = """  - !Ram
    range:
      start: 0x20000000
      end: 0x20010000
"""
    if variant.count(old_ram) != 1:
        fail("Expected one 64 KiB SRAM region in the pinned CC1354P10 variant")
    variant = variant.replace(old_ram, old_ram.replace("0x20010000", "0x20040000"))
    ctx.file("cc1354p10.yaml", source[:start] + variant + source[end:])
    ctx.file("BUILD.bazel", 'exports_files(["cc1354p10.yaml"], visibility = ["//visibility:public"])\n')

probe_rs_targets = repository_rule(implementation = _probe_rs_targets_impl)

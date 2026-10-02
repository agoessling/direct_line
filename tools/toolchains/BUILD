load("@rules_cc//cc:defs.bzl", "cc_toolchain")
load("@toolchains_arm_gnu//toolchain:config.bzl", "cc_arm_gnu_toolchain_config")

_ARM = "@arm_none_eabi_linux_x86_64//:"

_ABI = [
    "-mcpu=cortex-m33",
    "-mthumb",
    "-mfloat-abi=hard",
    "-mfpu=fpv5-sp-d16",
]

# Use upstream configuration directly: its convenience macro hardcodes stripping
# DWARF in opt links. Debugger visibility is required even in optimized firmware.
cc_arm_gnu_toolchain_config(
    name = "config",
    abi_version = "eabi",
    copts = _ABI + [
        "-ffreestanding",
        "-ffunction-sections",
        "-fdata-sections",
        "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables",
        "-g",
    ],
    gcc_version = "13.2.1",
    host_system_name = "linux_x86_64",
    include_path = [_ARM + "include_path"],
    library_path = [_ARM + "library_path"],
    linkopts = _ABI + ["-nostdlib"],
    opt_link_flags = [],
    toolchain_bins = _ARM + "compiler_components",
    toolchain_identifier = "direct_line_m33",
    toolchain_prefix = "arm-none-eabi",
)

cc_toolchain(
    name = "compiler",
    all_files = _ARM + "compiler_pieces",
    ar_files = _ARM + "ar_files",
    as_files = _ARM + "as_files",
    compiler_files = _ARM + "compiler_files",
    dwp_files = ":empty",
    linker_files = _ARM + "linker_files",
    objcopy_files = _ARM + "objcopy",
    strip_files = _ARM + "strip",
    supports_param_files = 0,
    toolchain_config = ":config",
    toolchain_identifier = "direct_line_m33",
)

filegroup(name = "empty")

toolchain(
    name = "m33",
    exec_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
    toolchain = ":compiler",
    toolchain_type = "@bazel_tools//tools/cpp:toolchain_type",
)

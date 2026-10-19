load("@reg_def//:defs.bzl", "rust_register_definition")
load("@rules_cc//cc:cc_library.bzl", "cc_library")
load("@rules_python//python:defs.bzl", "py_test")
load("@rules_rust//rust:defs.bzl", "rust_binary", "rust_library")
load("//tools/platforms:artifact.bzl", "m33_artifact")
load("//tools/quality:checks.bzl", "python_checks")

_DEVICE_SOURCES = [
    "clock.rs",
    "ddi.rs",
    "device.rs",
    "gpio.rs",
    "interrupts.rs",
    "ioc.rs",
    "lib.rs",
    "mmio.rs",
    "poll.rs",
    "prcm.rs",
    "rtc.rs",
    "setup.rs",
    "startup.rs",
    "timer.rs",
    "uart.rs",
]

rust_register_definition(
    name = "generated_registers",
    data = ["//third_party/ti/targetdb:all_files"],
    definition_file = "//third_party/ti/targetdb:devices/cc1354p10.xml",
    standalone = True,
)

rust_library(
    name = "registers",
    srcs = [":generated_registers"],
    crate_name = "cc1354p10_registers",
    crate_root = ":generated_registers",
)

cc_library(
    name = "ti_rom",
    srcs = ["ti_rom.c"],
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
    deps = ["@ti_sdk//:headers"],
)

rust_library(
    name = "device",
    srcs = _DEVICE_SOURCES,
    crate_root = "lib.rs",
    link_deps = [
        ":ti_rom",
        "//firmware/config:ccfg",
        "@ti_sdk//:setup",
    ],
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
    deps = [":registers"],
)

rust_binary(
    name = "bringup",
    srcs = [
        "main.rs",
        "poll.rs",
    ],
    crate_root = "main.rs",
    linker_script = "memory.ld",
    rustc_flags = [
        "-Cpanic=abort",
        "-Cdebuginfo=2",
    ],
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
    deps = [":device"],
)

m33_artifact(
    name = "ccfg_image",
    target = ":bringup",
)

py_test(
    name = "ccfg_test",
    size = "small",
    srcs = ["ccfg_test.py"],
    args = ["$(rootpath :ccfg_image)"],
    data = [":ccfg_image"],
    target_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    deps = ["@python_deps//pyelftools"],
)

python_checks(
    name = "python",
    srcs = ["ccfg_test.py"],
)

# All cases share one image; the host resets before selecting each case.
rust_binary(
    name = "hil_test",
    srcs = _DEVICE_SOURCES + [
        "board_test.rs",
        "clock_test.rs",
        "gpio_test.rs",
        "hil_registry.rs",
        "hil_test.rs",
        "timer_test.rs",
        "uart_test.rs",
    ],
    crate_root = "hil_test.rs",
    link_deps = [
        ":ti_rom",
        "//firmware/config:ccfg",
        "@ti_sdk//:setup",
    ],
    linker_script = "memory.ld",
    rustc_flags = ["-Cdebuginfo=2"],
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
    visibility = ["//tools/debug:__pkg__"],
    deps = [":registers"],
)

# Keep the upstream metadata linker fragment alongside the board's existing memory layout.
genrule(
    name = "embedded_test_linker",
    srcs = [
        "@embedded_test_crates//:linker_script",
        "memory.ld",
    ],
    outs = ["embedded_test.ld"],
    cmd = "cat $(execpath @embedded_test_crates//:linker_script) $(execpath memory.ld) > $@",
)

rust_binary(
    name = "embedded_test",
    srcs = _DEVICE_SOURCES + [
        "board_test.rs",
        "clock_test.rs",
        "embedded_test.rs",
        "gpio_test.rs",
        "timer_test.rs",
        "uart_test.rs",
    ],
    crate_name = "embedded_test_image",
    crate_root = "embedded_test.rs",
    link_deps = [
        ":ti_rom",
        "//firmware/config:ccfg",
        "@ti_sdk//:setup",
    ],
    linker_script = ":embedded_test_linker",
    rustc_flags = [
        "-Cdebuginfo=2",
        "--cfg=embedded_test",
    ],
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
    visibility = ["//tools/debug/experiments:__pkg__"],
    deps = [
        ":registers",
        "@embedded_test_crates//:embedded-test",
    ],
)

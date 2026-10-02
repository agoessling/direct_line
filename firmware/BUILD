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
)

python_checks(
    name = "python",
    srcs = ["ccfg_test.py"],
)

rust_binary(
    name = "gpio_test",
    srcs = ["gpio_test.rs"],
    linker_script = "memory.ld",
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
    deps = [
        ":device",
        ":registers",
    ],
)

# Separate images test the first ROM switch with PRIMASK initially clear/set.
[
    rust_binary(
        name = name,
        srcs = [
            "clock_test.rs",
            "poll.rs",
        ],
        crate_features = features,
        crate_root = "clock_test.rs",
        linker_script = "memory.ld",
        target_compatible_with = [
            "@platforms//cpu:armv8-m",
            "@platforms//os:none",
        ],
        deps = [
            ":device",
            ":registers",
        ],
    )
    for name, features in [
        ("clock_test", []),
        (
            "clock_test_masked",
            ["masked_switch"],
        ),
    ]
]

# Each image assigns a different GPT as counter and the other three as interrupt timers.
[
    rust_binary(
        name = "timer_test_gpt{}".format(index),
        srcs = _DEVICE_SOURCES + ["timer_test.rs"],
        crate_features = ["counter_gpt{}".format(index)],
        crate_root = "timer_test.rs",
        link_deps = [
            ":ti_rom",
            "//firmware/config:ccfg",
            "@ti_sdk//:setup",
        ],
        linker_script = "memory.ld",
        target_compatible_with = [
            "@platforms//cpu:armv8-m",
            "@platforms//os:none",
        ],
        deps = [":registers"],
    )
    for index in range(4)
]

# Exercise each UART on the debug-probe pins at a different baud using internal loopback.
[
    rust_binary(
        name = "uart_test_uart{}".format(index),
        srcs = _DEVICE_SOURCES + ["uart_test.rs"],
        crate_features = ["uart{}".format(index)],
        crate_root = "uart_test.rs",
        link_deps = [
            ":ti_rom",
            "//firmware/config:ccfg",
            "@ti_sdk//:setup",
        ],
        linker_script = "memory.ld",
        target_compatible_with = [
            "@platforms//cpu:armv8-m",
            "@platforms//os:none",
        ],
        deps = [":registers"],
    )
    for index in range(4)
]

load("@reg_def//:defs.bzl", "register_definition")
load("//third_party/freertos:freertos.bzl", "freertos_library")
load("//tools/debug:flash.bzl", "flash_target")

cc_binary(
    name = "main",
    srcs = [
        "main.cc",
    ],
    features = ["generate_linkmap"],
    linkopts = [
        "-T $(execpath :cc13x4_cc26x4.ld)",
    ],
    target_compatible_with = [
        "//tools/platforms/cpu:cortex_m33",
        "@platforms//os:none",
    ],
    visibility = ["//visibility:public"],
    deps = [
        ":board",
        ":cc13x4_cc26x4.ld",
        ":ccfg",
        ":freertos_kernel",
        ":freertos_support",
        ":startup",
        ":uart",
    ],
)

cc_library(
    name = "freertos_support",
    srcs = ["freertos_support.c"],
    deps = [
        ":freertos_kernel",
    ],
    alwayslink = True,
)

cc_library(
    name = "clock",
    hdrs = ["clock.hh"],
    deps = [
        "@ti_simplelink//:driverlib",
    ],
)

cc_library(
    name = "board",
    srcs = ["board.cc"],
    hdrs = ["board.hh"],
    target_compatible_with = [
        "//tools/platforms/cpu:cortex_m33",
        "@platforms//os:none",
    ],
    deps = [
        "@ti_simplelink//:driverlib",
    ],
)

cc_library(
    name = "uart",
    srcs = ["uart.cc"],
    hdrs = ["uart.hh"],
    target_compatible_with = [
        "//tools/platforms/cpu:cortex_m33",
        "@platforms//os:none",
    ],
    deps = [
        ":cc1354p10_reg_def",
        ":clock",
    ],
)

cc_library(
    name = "startup",
    srcs = [
        "startup.c",
    ],
    target_compatible_with = [
        "//tools/platforms/cpu:cortex_m33",
        "@platforms//os:none",
    ],
    deps = [
        ":cc1354p10_reg_def",
        "@ti_simplelink//:driverlib",
    ],
)

flash_target(
    name = "main.flash",
    binary = ":main",
    ccxml = "//tools/debug:xds110_cc1354p10.ccxml",
)

register_definition(
    name = "cc1354p10_reg_def",
    out = "cc1354p10_reg_def.h",
    data = ["//third_party/ti/targetdb:all_files"],
    definition_file = "//third_party/ti/targetdb:devices/cc1354p10.xml",
    definition_type = "ti",
)

cc_library(
    name = "ccfg",
    srcs = ["ccfg.c"],
    deps = ["@ti_simplelink//:ccfg"],
    # This library defines the CCFG data structure which is required to be linked in the final
    # binary but is not referenced anywhere.
    alwayslink = True,
)

cc_library(
    name = "system_config",
    hdrs = ["system_config.h"],
)

cc_library(
    name = "freertos_config",
    hdrs = ["FreeRTOSConfig.h"],
    includes = ["."],
    deps = [":system_config"],
)

freertos_library(
    name = "freertos_kernel",
    freertos_config_lib = ":freertos_config",
    port = "gcc_cortex_m33",
)

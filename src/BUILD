load("@reg_def//:defs.bzl", "register_definition")

cc_binary(
    name = "main",
    srcs = [
        "main.cc",
    ],
    linkopts = [
        "-T $(execpath :cc13x4_cc26x4.ld)",
    ],
    target_compatible_with = [
        "//tools/platforms/cpu:cortex_m33",
        "@platforms//os:none",
    ],
    visibility = ["//visibility:public"],
    deps = [
        ":cc1354p10_reg_def",
        ":cc13x4_cc26x4.ld",
        ":startup",
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
)

register_definition(
    name = "cc1354p10_reg_def",
    out = "cc1354p10_reg_def.h",
    data = ["//third_party/ti/targetdb:all_files"],
    definition_file = "//third_party/ti/targetdb:devices/cc1354p10.xml",
    definition_type = "ti",
)

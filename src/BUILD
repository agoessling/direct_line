cc_binary(
    name = "main",
    srcs = [
        "main.cc",
        "startup.c",
    ],
    linkopts = [
        "-T $(execpath :cc13x4_cc26x4.ld)",
    ],
    visibility = ["//visibility:public"],
    target_compatible_with = [
        "//tools/platforms/cpu:cortex_m33",
        "@platforms//os:none",
    ],
    deps = [
        ":cc13x4_cc26x4.ld",
    ],
)

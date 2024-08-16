load("@//third_party/freertos:freertos.bzl", "freertos_port")

filegroup(
    name = "common_source",
    srcs = glob(
        ["*.c"],
        allow_empty = False,
    ),
    visibility = ["//visibility:public"],
)

cc_library(
    name = "common_include",
    srcs = glob(
        ["include/*.h"],
        allow_empty = False,
    ),
    includes = ["include"],
    visibility = ["//visibility:public"],
)

[filegroup(
    name = "heap_{}".format(i),
    srcs = ["portable/MemMang/heap_{}.c".format(i)],
    visibility = ["//visibility:public"],
) for i in range(1, 6)]

freertos_port(
    name = "gcc_cortex_m33",
    port_path = "portable/GCC/ARM_CM33_NTZ/non_secure",
    visibility = ["//visibility:public"],
)

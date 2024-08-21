filegroup(
    name = "cc13x4_cc26x4_includes",
    srcs = glob(["source/ti/devices/cc13x4_cc26x4/inc/*.h"], allow_empty=False),
)

cc_library(
    name = "driverlib",
    srcs = glob([
        "source/ti/devices/cc13x4_cc26x4/driverlib/*.c",
        "source/ti/devices/cc13x4_cc26x4/driverlib/*.h",
    ], allow_empty=False),
    hdrs = [
        ":cc13x4_cc26x4_includes",
        "source/ti/devices/DeviceFamily.h",
    ],
    includes = ["source"],
    defines = ["DeviceFamily_CC13X4"],
    visibility = ["//visibility:public"],
)

cc_library(
    name = "ccfg",
    srcs = [":cc13x4_cc26x4_includes"],
    textual_hdrs = ["source/ti/devices/cc13x4_cc26x4/startup_files/ccfg.c"],
    includes = ["source"],
    visibility = ["//visibility:public"],
)

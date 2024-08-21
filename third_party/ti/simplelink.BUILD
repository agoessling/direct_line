cc_library(
    name = "driverlib",
    srcs = glob([
        "source/ti/devices/cc13x4_cc26x4/driverlib/*.c",
        "source/ti/devices/cc13x4_cc26x4/driverlib/*.h",
        "source/ti/devices/cc13x4_cc26x4/inc/*.h",
        "source/ti/devices/DeviceFamily.h",
    ], allow_empty=False),
    includes = ["source"],
    defines = ["DeviceFamily_CC13X4"],
    visibility = ["//visibility:public"],
)

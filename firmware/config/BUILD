load("@rules_cc//cc:cc_library.bzl", "cc_library")
load("//third_party/ti:sysconfig.bzl", "ccfg")

ccfg(
    name = "generated",
    src = "board.syscfg",
    board = "/ti/boards/LP_EM_CC1354P10_1",
)

cc_library(
    name = "ccfg",
    srcs = [":generated"],
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
    visibility = ["//firmware:__pkg__"],
    deps = ["@ti_sdk//:headers"],
    alwayslink = True,
)

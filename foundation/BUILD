load("@rules_rust//rust:defs.bzl", "rust_library", "rust_test")

rust_library(
    name = "foundation",
    srcs = ["lib.rs"],
    visibility = ["//visibility:public"],
)

rust_test(
    name = "foundation_test",
    crate = ":foundation",
    target_compatible_with = select({
        "@platforms//os:none": ["@platforms//:incompatible"],
        "//conditions:default": [],
    }),
)

load("@rules_cc//cc:cc_library.bzl", "cc_library")
load("@rules_rust//rust:defs.bzl", "rust_binary")

cc_library(
    name = "ffi_c",
    srcs = ["smoke.c"],
    copts = [
        "-Wall",
        "-Wextra",
        "-Werror",
    ],
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
)

# A link check, not a bootable board image. Exercises archive retention and the
# hard-float C ABI without depending on the device startup or TI SDK.
rust_binary(
    name = "link_check",
    srcs = ["smoke.rs"],
    link_deps = [":ffi_c"],
    linker_script = "smoke.ld",
    target_compatible_with = [
        "@platforms//cpu:armv8-m",
        "@platforms//os:none",
    ],
)

load("@bazel_skylib//rules:native_binary.bzl", "native_binary")
load("@rules_python//python:defs.bzl", "py_binary", "py_test")
load("//tools/platforms:artifact.bzl", "m33_artifact")
load("//tools/quality:checks.bzl", "python_checks")

_HOST = [
    "@platforms//os:linux",
    "@platforms//cpu:x86_64",
]

native_binary(
    name = "probe_rs",
    src = "@probe_rs//:probe-rs",
    tags = ["manual"],
    target_compatible_with = _HOST,
)

m33_artifact(
    name = "hil_image",
    tags = ["manual"],
    target = "//firmware:hil_test",
)

_SOURCES = [
    "hil.py",
    "probe_lock.py",
]

py_binary(
    name = "hil",
    srcs = _SOURCES,
    data = [
        ":hil_image",
        "@probe_rs//:probe-rs",
        "@probe_rs_targets//:cc1354p10.yaml",
    ],
    env = {
        "PROBE_RS": "$(rlocationpath @probe_rs//:probe-rs)",
        "DIRECT_LINE_ELF": "$(rlocationpath :hil_image)",
        "DIRECT_LINE_TARGET": "$(rlocationpath @probe_rs_targets//:cc1354p10.yaml)",
    },
    main = "hil.py",
    tags = ["manual"],
    target_compatible_with = _HOST,
    deps = ["@rules_python//python/runfiles"],
)

py_test(
    name = "hil_test",
    size = "small",
    srcs = _SOURCES + ["hil_test.py"],
    deps = ["@rules_python//python/runfiles"],
)

python_checks(
    name = "python",
    srcs = _SOURCES + ["hil_test.py"],
)

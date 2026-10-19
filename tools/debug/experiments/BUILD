load("@bazel_skylib//rules:native_binary.bzl", "native_binary")
load("@rules_python//python:defs.bzl", "py_binary")
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

py_binary(
    name = "benchmark",
    srcs = ["benchmark.py"],
    data = ["@probe_rs//:probe-rs"],
    env = {"PROBE_RS": "$(rlocationpath @probe_rs//:probe-rs)"},
    tags = ["manual"],
    target_compatible_with = _HOST,
    deps = ["@rules_python//python/runfiles"],
)

python_checks(
    name = "python",
    srcs = ["benchmark.py"],
)

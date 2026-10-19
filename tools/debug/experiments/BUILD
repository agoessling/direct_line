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

py_binary(
    name = "benchmark",
    srcs = [
        "benchmark.py",
        "probe_lock.py",
    ],
    data = ["@probe_rs//:probe-rs"],
    env = {"PROBE_RS": "$(rlocationpath @probe_rs//:probe-rs)"},
    tags = ["manual"],
    target_compatible_with = _HOST,
    deps = ["@rules_python//python/runfiles"],
)

m33_artifact(
    name = "embedded_test_image",
    tags = ["manual"],
    target = "//firmware:embedded_test",
)

py_binary(
    name = "embedded_test",
    srcs = [
        "probe_lock.py",
        "run_tests.py",
    ],
    data = [
        ":embedded_test_image",
        "@probe_rs//:probe-rs",
    ],
    env = {
        "PROBE_RS": "$(rlocationpath @probe_rs//:probe-rs)",
        "EMBEDDED_TEST_IMAGE": "$(rlocationpath :embedded_test_image)",
    },
    main = "run_tests.py",
    tags = ["manual"],
    target_compatible_with = _HOST,
    deps = ["@rules_python//python/runfiles"],
)

py_test(
    name = "run_tests_test",
    size = "small",
    srcs = [
        "probe_lock.py",
        "run_tests.py",
        "run_tests_test.py",
    ],
    deps = ["@rules_python//python/runfiles"],
)

python_checks(
    name = "python",
    srcs = [
        "benchmark.py",
        "probe_lock.py",
        "run_tests.py",
        "run_tests_test.py",
    ],
)

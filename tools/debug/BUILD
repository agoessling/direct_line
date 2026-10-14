load("@rules_python//python:defs.bzl", "py_binary", "py_test")
load("//tools/platforms:artifact.bzl", "m33_artifact")
load("//tools/quality:checks.bzl", "python_checks")

exports_files(["xds110_cc1354p10.ccxml"])

py_binary(
    name = "ccs_script",
    srcs = [
        "ccs_script.py",
        "hil_types.py",
    ],
    main = "ccs_script.py",
    deps = ["@ti_debug_tools//:scripting"],
)

m33_artifact(
    name = "hil_image",
    tags = ["manual"],
    target = "//firmware:hil_test",
)

_SOURCES = [
    "elf.py",
    "hil.py",
    "hil_types.py",
    "process.py",
    "transport.py",
]

py_binary(
    name = "hil",
    srcs = _SOURCES,
    data = [
        "xds110_cc1354p10.ccxml",
        ":ccs_script",
        ":hil_image",
        "@ti_debug_tools//:dslite",
        "@ti_debug_tools//:runtime",
    ],
    env = {
        "DIRECT_LINE_DSLITE": "$(rlocationpath @ti_debug_tools//:dslite)",
        "DIRECT_LINE_ELF": "$(rlocationpath :hil_image)",
        "DIRECT_LINE_CCS_WORKER": "$(rlocationpath :ccs_script)",
    },
    main = "hil.py",
    tags = ["manual"],
    target_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    deps = [
        "@python_deps//pyelftools",
        "@rules_python//python/runfiles",
    ],
)

py_test(
    name = "hil_test",
    size = "small",
    srcs = _SOURCES + ["hil_test.py"],
    main = "hil_test.py",
    deps = [
        "@python_deps//pyelftools",
        "@rules_python//python/runfiles",
    ],
)

python_checks(
    name = "python",
    srcs = _SOURCES + [
        "ccs_script.py",
        "hil_test.py",
    ],
)

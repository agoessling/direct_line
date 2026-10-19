load("@rules_python//python:defs.bzl", "py_binary", "py_test")
load("//tools/platforms:artifact.bzl", "m33_artifact")
load("//tools/quality:checks.bzl", "python_checks")

exports_files(["xds110_cc1354p10.ccxml"])

py_binary(
    name = "ccs_script",
    srcs = [
        "ccs_script.py",
        "protocol.py",
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
    "protocol.py",
    "process.py",
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
    data = [":hil_image"],
    env = {"DIRECT_LINE_TEST_ELF": "$(rlocationpath :hil_image)"},
    main = "hil_test.py",
    deps = [
        "@python_deps//pyelftools",
        "@rules_python//python/runfiles",
    ],
)

py_test(
    name = "ccs_script_test",
    size = "small",
    srcs = [
        "ccs_script.py",
        "ccs_script_test.py",
        "protocol.py",
    ],
    main = "ccs_script_test.py",
    deps = ["@ti_debug_tools//:scripting"],
)

python_checks(
    name = "python",
    srcs = _SOURCES + [
        "ccs_script.py",
        "ccs_script_test.py",
        "hil_test.py",
    ],
)

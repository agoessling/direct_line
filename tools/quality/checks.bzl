"""Declared Python checks using standard Bazel test rules."""

load("@bazel_skylib//rules:native_binary.bzl", "native_test")

_HOST = ["@platforms//os:linux", "@platforms//cpu:x86_64"]
_RUFF_CONFIG = Label("//:.ruff.toml")

def python_checks(name, srcs):
    """Check Python formatting, lint, and types using explicit source labels.

    Args:
        name: Prefix for the format, lint, and typecheck test targets.
        srcs: Python source labels in this package.
    """
    for suffix, command in [("format", ["format", "--check"]), ("lint", ["check"])]:
        native_test(
            name = name + "_" + suffix,
            src = "@ruff_prebuilt//:ruff",
            args = command + ["--no-cache", "--config", "$(rootpath {})".format(_RUFF_CONFIG)] + ["$(rootpath {})".format(src) for src in srcs],
            data = srcs + [_RUFF_CONFIG],
            size = "small",
            target_compatible_with = _HOST,
        )
    native_test(
        name = name + "_typecheck",
        src = "//tools/quality:basedpyright",
        args = ["$(rootpath {})".format(src) for src in srcs],
        data = srcs,
        size = "small",
        target_compatible_with = _HOST,
    )

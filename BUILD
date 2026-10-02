load("@buildifier_prebuilt//:rules.bzl", "buildifier_test")
load("@rules_shell//shell:sh_test.bzl", "sh_test")

exports_files([
    "AGENTS.md",
    ".ruff.toml",
    ".clang-format",
    "rustfmt.toml",
])

alias(
    name = "rust_project",
    actual = "@rules_rust//tools/rust_analyzer:gen_rust_project",
)

# Workspace discovery covers new packages and untracked source files. These
# checks run locally and uncached because their source inputs are discovered.
buildifier_test(
    name = "build_files",
    size = "small",
    exclude_patterns = [
        "./.*",
        "./bazel-*",
    ],
    lint_mode = "warn",
    mode = "check",
    no_sandbox = True,
    tags = ["local"],
    target_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
    workspace = "MODULE.bazel",
)

sh_test(
    name = "c_format",
    size = "small",
    srcs = ["//tools/quality:c_format.sh"],
    args = [
        "$(rootpath :MODULE.bazel)",
        "$(rootpath @clang_format//file)",
        "$(rootpath :.clang-format)",
    ],
    data = [
        ".clang-format",
        "MODULE.bazel",
        "@clang_format//file",
    ],
    tags = [
        "external",
        "local",
        "no-cache",
    ],
    target_compatible_with = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
)

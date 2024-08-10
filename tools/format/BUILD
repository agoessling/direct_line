load("@aspect_rules_lint//format:defs.bzl", "format_multirun")

format_multirun(
    name = "format",
    c = "@llvm_toolchain_llvm//:bin/clang-format",
    cc = "@llvm_toolchain_llvm//:bin/clang-format",
    python = "//tools/lint:ruff",
    starlark = "@buildifier_prebuilt//:buildifier",
    visibility = ["//visibility:public"],
)

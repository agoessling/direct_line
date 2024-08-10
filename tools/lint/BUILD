load("@bazel_skylib//rules:native_binary.bzl", "native_binary")

native_binary(
    name = "clang_tidy",
    src = "@llvm_toolchain_llvm//:bin/clang-tidy",
    out = "clang_tidy",
    visibility = ["//visibility:public"],
)

native_binary(
    name = "ruff",
    src = "@ruff",
    out = "ruff",
    visibility = ["//visibility:public"],
)

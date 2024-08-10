load("@aspect_rules_lint//lint:clang_tidy.bzl", "lint_clang_tidy_aspect")
load("@aspect_rules_lint//lint:ruff.bzl", "lint_ruff_aspect")

clang_tidy = lint_clang_tidy_aspect(
    binary = "@@//tools/lint:clang_tidy",
    configs = ["@@//:.clang-tidy"],
)

ruff = lint_ruff_aspect(
    binary = "@@//tools/lint:ruff",
    configs = "@@//:.ruff.toml",
)

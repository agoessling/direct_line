load("@hedron_compile_commands//:refresh_compile_commands.bzl", "refresh_compile_commands")

refresh_compile_commands(
    name = "refresh_compile_commands",
    targets = {
      "//src:main": "--config=m33",
    },
)

# BEGIN ==================== lint_it_all ====================
exports_files([
    ".clang-tidy",
    ".ruff.toml",
])

alias(
    name = "format",
    actual = "//tools/format",
)
# END ==================== lint_it_all ====================

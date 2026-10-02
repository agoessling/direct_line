#!/usr/bin/env bash
# A local, uncached test: the MODULE runfile resolves back to the checkout.
set -euo pipefail
workspace="$(dirname "$(realpath "$1")")"
formatter="$(realpath "$2")"
config="$(realpath "$3")"
cd "$workspace"

# Do not follow symlinks into Bazel's external repositories or generated outputs.
# Hidden working directories and vendored C sources are outside this check.
find . \( -path './.*' -o -path './bazel-*' -o -path './third_party' \) -prune -o \
  -type f \( -name '*.c' -o -name '*.h' \) \
  -exec "$formatter" --dry-run --Werror "--style=file:$config" {} +

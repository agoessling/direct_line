#!/usr/bin/env bash
# Resolve declared runfiles before operating on caller-selected workspace files.
set -euo pipefail
tool="$(realpath "$1")"
config="$(realpath "$2")"
config_flag="$3"
shift 3
cd "${BUILD_WORKSPACE_DIRECTORY:?Run this formatter through bazel run}"
exec "$tool" "$config_flag$config" "$@"

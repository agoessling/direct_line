"""Run the pinned checker with Bazel's Node, Python, and import paths."""

import os
import subprocess
import sys
from pathlib import Path

import elftools
from python.runfiles import runfiles


def declared_path(name: str) -> str:
    files = runfiles.Create()
    if files is None:
        raise RuntimeError("Bazel runfiles are unavailable")
    path = files.Rlocation(name)
    if path is None:
        raise RuntimeError(f"Missing declared tool input: {name}")
    return path


def main() -> int:
    # Basedpyright asks this interpreter for its import paths. Add the declared dependencies;
    # the shared config supplies project imports from the checkout or the test's declared inputs.
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [
            str(Path(runfiles.__file__).parents[2]),
            str(Path(elftools.__file__).parent.parent),
        ]
    )
    workspace = os.environ.get("BUILD_WORKSPACE_DIRECTORY")
    config = (
        str(Path(workspace) / "pyrightconfig.json")
        if workspace
        else declared_path("direct_line/pyrightconfig.json")
    )
    command = [
        declared_path("ti_sysconfig/sysconfig/nodejs/node"),
        declared_path("basedpyright/index.js"),
        "--project",
        config,
        "--pythonpath",
        sys.executable,
        *sys.argv[1:],
    ]
    return subprocess.run(command, env=environment, cwd=workspace, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())

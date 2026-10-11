"""Generate build-derived project metadata without configuring an editor."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from python.runfiles import runfiles


def refresh_c_commands(root):
    # Ensure generated translation units exist even on a fresh checkout.
    subprocess.run(
        ["bazel", "build", "--config=m33", "//foundation/...", "//firmware/..."],
        cwd=root,
        check=True,
    )
    # aquery supplies the actual compiler arguments, including generated inputs.
    # No second compiler configuration or source discovery is maintained here.
    execution_root = subprocess.check_output(
        ["bazel", "info", "execution_root"], cwd=root, text=True
    ).strip()
    graph = json.loads(
        subprocess.check_output(
            [
                "bazel",
                "aquery",
                "--config=m33",
                "--output=jsonproto",
                'mnemonic("CppCompile", deps(//foundation/... + //firmware/...))',
            ],
            cwd=root,
            text=True,
        )
    )
    commands = []
    for action in graph.get("actions", []):
        arguments = action["arguments"]
        # CppCompile actions identify the translation unit with GCC's -c option.
        source = arguments[arguments.index("-c") + 1]
        commands.append({"directory": execution_root, "file": source, "arguments": arguments})
    (root / "compile_commands.json").write_text(json.dumps(commands, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rustc", required=True)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    rustc = str(Path(args.rustc).resolve())
    root = Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])
    subprocess.run(
        [
            "bazel",
            "run",
            "//:rust_project",
            "--",
            "--config",
            "m33",
            "//foundation/...",
            "//firmware/...",
        ],
        cwd=root,
        check=True,
    )
    refresh_c_commands(root)
    project_file = root / "rust-project.json"
    project = json.loads(project_file.read_text())
    # This optional runnable was introduced after the project's Rust 1.90 release.
    # Removing it keeps the build-derived crate graph usable by older analyzers.
    project["runnables"] = [
        item for item in project.get("runnables", []) if item.get("kind") != "flycheck"
    ]
    project_file.write_text(json.dumps(project, indent=2) + "\n")
    metadata = json.loads(Path(args.project).read_text())
    metadata.update(
        rustc=rustc,
        python_search_paths=[str(Path(runfiles.__file__).resolve().parents[2])],
    )
    destination = root / ".tools" / "project.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Wrote {project_file} and {destination}")


if __name__ == "__main__":
    main()

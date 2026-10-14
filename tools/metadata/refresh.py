"""Generate build-derived project metadata without configuring an editor."""

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import NotRequired, TypedDict, cast

import elftools
import scripting
import websockets
from python.runfiles import runfiles


class CompileAction(TypedDict):
    arguments: list[str]


class ActionGraph(TypedDict):
    actions: NotRequired[list[CompileAction]]


class CompileCommand(CompileAction):
    directory: str
    file: str


class Runnable(TypedDict):
    kind: NotRequired[str]


class RustProject(TypedDict):
    runnables: NotRequired[list[Runnable]]


class EditorMetadata(TypedDict):
    rustc: NotRequired[str]
    python_search_paths: NotRequired[list[str]]


@dataclass
class Arguments(argparse.Namespace):
    rustc: str = ""
    project: str = ""


def refresh_c_commands(root: Path) -> None:
    # Ensure generated translation units exist even on a fresh checkout.
    _ = subprocess.run(
        ["bazel", "build", "--config=m33", "//foundation/...", "//firmware/..."],
        cwd=root,
        check=True,
    )
    # aquery supplies the actual compiler arguments, including generated inputs.
    # No second compiler configuration or source discovery is maintained here.
    execution_root = subprocess.check_output(
        ["bazel", "info", "execution_root"], cwd=root, text=True
    ).strip()
    graph = cast(
        ActionGraph,
        json.loads(
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
        ),
    )
    commands: list[CompileCommand] = []
    for action in graph.get("actions", []):
        arguments = action["arguments"]
        # CppCompile actions identify the translation unit with GCC's -c option.
        source = arguments[arguments.index("-c") + 1]
        commands.append({"directory": execution_root, "file": source, "arguments": arguments})
    _ = (root / "compile_commands.json").write_text(json.dumps(commands, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--rustc", required=True)
    _ = parser.add_argument("--project", required=True)
    args = Arguments()
    _ = parser.parse_args(namespace=args)
    rustc = str(Path(args.rustc).resolve())
    root = Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])
    _ = subprocess.run(
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
    project = cast(RustProject, json.loads(project_file.read_text()))
    # This optional runnable was introduced after the project's Rust 1.90 release.
    # Removing it keeps the build-derived crate graph usable by older analyzers.
    project["runnables"] = [
        item for item in project.get("runnables", []) if item.get("kind") != "flycheck"
    ]
    _ = project_file.write_text(json.dumps(project, indent=2) + "\n")
    metadata = cast(EditorMetadata, json.loads(Path(args.project).read_text()))
    assert runfiles.__file__ is not None
    metadata["rustc"] = rustc
    metadata["python_search_paths"] = [
        str(Path(runfiles.__file__).resolve().parents[2]),
        str(Path(elftools.__file__).resolve().parent.parent),
        str(Path(scripting.__file__).resolve().parent.parent),
        str(Path(websockets.__file__).resolve().parent.parent),
    ]
    destination = root / ".tools" / "project.json"
    destination.parent.mkdir(exist_ok=True)
    _ = destination.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Wrote {project_file} and {destination}")


if __name__ == "__main__":
    main()

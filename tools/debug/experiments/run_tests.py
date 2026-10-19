"""Flash, verify, and run embedded-test through one pinned probe-rs process."""

import argparse
import hashlib
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

from python.runfiles import runfiles

from tools.debug.experiments.probe_lock import probe_lock


@dataclass
class Arguments(argparse.Namespace):
    probe: str = ""
    output_dir: Path | None = None
    filter: list[str] = field(default_factory=list)
    list: bool = False
    ignored: bool = False
    force_flash: bool = False


@dataclass(frozen=True)
class SuiteResult:
    passed: int
    failed: int
    ignored: int


@dataclass(frozen=True)
class Report:
    probe: str
    image_sha256: str
    command: list[str]
    duration_s: float
    exit_code: int | None
    timed_out: bool
    suite: SuiteResult | None


def command_line(executable: str, image: str, args: Arguments) -> list[str]:
    if len(args.filter) > 1:
        raise ValueError("Specify at most one --filter")
    command = [
        executable,
        "run",
        "--probe",
        f"0451:bef3-5:{args.probe}",
        "--chip",
        "CC1354P10",
        "--protocol",
        "jtag",
        "--speed",
        "1000",
        "--non-interactive",
        "--verify",
        "--restore-unwritten",
        "--disable-progressbars",
        "--format",
        "json",
    ]
    # Read back loadable flash bytes before deciding whether programming is necessary.
    if not args.force_flash:
        command.append("--preverify")
    if args.list:
        command.append("--list")
    if args.ignored:
        command.append("--ignored")
    # End option parsing so filters cannot introduce probe or flashing overrides.
    return command + ["--", image, *args.filter]


def suite_result(transcript: str) -> SuiteResult | None:
    # probe-rs emits libtest JSON events alongside ordinary debugger diagnostics.
    for line in reversed(transcript.splitlines()):
        try:
            value = cast(object, json.loads(line))
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        event = cast(dict[str, object], value)
        if event.get("type") != "suite" or event.get("event") not in ("ok", "failed"):
            continue
        counts = [event.get(key) for key in ("passed", "failed", "ignored")]
        if not all(type(count) is int and count >= 0 for count in counts):
            return None
        passed, failed, ignored = cast(list[int], counts)
        return SuiteResult(passed, failed, ignored)
    return None


def execute(command: list[str], transcript: Path, probe: str, image: Path) -> Report:
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    with transcript.open("wb") as output:
        start = time.monotonic()
        try:
            result = subprocess.run(
                command,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=False,
            )
            exit_code = result.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            # subprocess.run kills and reaps the CLI before returning control.
            exit_code = None
            timed_out = True
        duration = time.monotonic() - start
    suite = suite_result(transcript.read_text(errors="replace"))
    return Report(probe, digest, command, duration, exit_code, timed_out, suite)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", required=True, help="XDS110 serial number")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--filter", action="append", default=[], help="Test name substring")
    parser.add_argument("--list", action="store_true", help="List tests through the device")
    parser.add_argument("--ignored", action="store_true", help="Run intentional failure cases")
    parser.add_argument(
        "--force-flash", action="store_true", help="Program even when flash matches the image"
    )
    args = parser.parse_args(namespace=Arguments())
    if len(args.filter) > 1:
        parser.error("Specify at most one --filter")
    if not args.probe.isalnum():
        parser.error("Expected an alphanumeric probe serial")
    runtime = runfiles.Create()
    if runtime is None:
        raise RuntimeError("Bazel runfiles are unavailable")
    executable = runtime.Rlocation(os.environ["PROBE_RS"])
    image = runtime.Rlocation(os.environ["EMBEDDED_TEST_IMAGE"])
    if executable is None or image is None:
        raise RuntimeError("Pinned probe-rs executable or firmware image is unavailable")
    workspace = Path(os.environ["BUILD_WORKSPACE_DIRECTORY"]).resolve()
    default_output = Path(".results") / f"embedded-test-{time.time_ns()}"
    directory = (workspace / (args.output_dir or default_output)).resolve()
    if not directory.is_relative_to(workspace / ".results"):
        parser.error("Write reports beneath the checkout's ignored .results directory")
    directory.mkdir(parents=True, exist_ok=False)
    transcript = directory / "console.txt"
    with probe_lock(args.probe):
        report = execute(command_line(executable, image, args), transcript, args.probe, Path(image))
    (directory / "report.json").write_text(json.dumps(asdict(report), indent=2) + "\n")
    print(transcript.read_text(errors="replace"), end="")
    print(f"Host process time: {report.duration_s:.3f}s; report: {directory / 'report.json'}")
    if report.timed_out:
        raise SystemExit("probe-rs exceeded the 180 second deadline")
    if report.exit_code == 0 and not args.list:
        if report.suite is None or report.suite.passed == 0 or report.suite.failed:
            raise SystemExit("probe-rs did not report a completed, nonempty passing suite")
    raise SystemExit(report.exit_code)


if __name__ == "__main__":
    main()

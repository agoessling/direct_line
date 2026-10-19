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

from tools.debug.probe_lock import probe_lock


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
    error: str | None


def command_line(executable: str, image: str, target: str, args: Arguments) -> list[str]:
    if len(args.filter) > 1:
        raise ValueError("Specify at most one --filter")
    command = [
        executable,
        "run",
        "--probe",
        f"0451:bef3-5:{args.probe}",
        "--chip-description-path",
        target,
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
    # A terminal summary must account for every case announced by this run.
    expected: int | None = None
    result: SuiteResult | None = None
    for line in transcript.splitlines():
        try:
            value = cast(object, json.loads(line))
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        event = cast(dict[str, object], value)
        if event.get("type") != "suite":
            continue
        result = None
        if event.get("event") == "started":
            count = event.get("test_count")
            expected = count if type(count) is int and count >= 0 else None
            continue
        if expected is None or event.get("event") not in ("ok", "failed"):
            continue
        counts = [event.get(key) for key in ("passed", "failed", "ignored")]
        if not all(type(count) is int and count >= 0 for count in counts):
            continue
        passed, failed, ignored = cast(list[int], counts)
        if passed + failed + ignored != expected:
            continue
        if (event["event"] == "ok") != (failed == 0):
            continue
        result = SuiteResult(passed, failed, ignored)
        expected = None
    return result


def execute(
    command: list[str], transcript: Path, probe: str, image: Path, *, list_only: bool = False
) -> Report:
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    error: str | None = None
    timed_out = False
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
        except subprocess.TimeoutExpired:
            # subprocess.run kills and reaps the CLI before returning control.
            exit_code = None
            timed_out = True
            error = "probe-rs exceeded the 180 second deadline"
        except OSError as failure:
            exit_code = None
            error = str(failure)
        duration = time.monotonic() - start
    suite = suite_result(transcript.read_text(errors="replace"))
    if error is None:
        if exit_code != 0:
            error = f"probe-rs exited with status {exit_code}"
        elif not list_only and (suite is None or suite.passed == 0 or suite.failed):
            error = "probe-rs did not report a completed, nonempty passing suite"
    return Report(probe, digest, command, duration, exit_code, timed_out, suite, error)


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
    image = runtime.Rlocation(os.environ["DIRECT_LINE_ELF"])
    target = runtime.Rlocation(os.environ["DIRECT_LINE_TARGET"])
    if executable is None or image is None or target is None:
        raise RuntimeError("Pinned debugger, target description, or firmware image is unavailable")
    workspace = Path(os.environ["BUILD_WORKSPACE_DIRECTORY"]).resolve()
    default_output = Path(".results") / f"hil-{time.time_ns()}"
    directory = (workspace / (args.output_dir or default_output)).resolve()
    if not directory.is_relative_to(workspace / ".results"):
        parser.error("Write reports beneath the checkout's ignored .results directory")
    directory.mkdir(parents=True, exist_ok=False)
    transcript = directory / "console.txt"
    with probe_lock(args.probe):
        report = execute(
            command_line(executable, image, target, args),
            transcript,
            args.probe,
            Path(image),
            list_only=args.list,
        )
    (directory / "report.json").write_text(json.dumps(asdict(report), indent=2) + "\n")
    print(transcript.read_text(errors="replace"), end="")
    print(f"Host process time: {report.duration_s:.3f}s; report: {directory / 'report.json'}")
    if report.error is not None:
        raise SystemExit(report.error)
    raise SystemExit(0)


if __name__ == "__main__":
    main()

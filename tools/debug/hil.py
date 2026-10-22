"""Flash, verify, and run embedded-test through one pinned probe-rs process."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, TextIO, cast

from python.runfiles import runfiles

from tools.debug.output import stream_process
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


def command_line(
    executable: str,
    image: str,
    target: str,
    args: Arguments,
    target_output: Path,
    *,
    progress: bool = False,
) -> list[str]:
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
        "--format",
        "json",
        "--target-output-file",
        str(target_output),
    ]
    if not progress:
        command.append("--disable-progressbars")
    # Read back loadable flash bytes before deciding whether programming is necessary.
    if not args.force_flash:
        command.append("--preverify")
    if args.list:
        command.append("--list")
    if args.ignored:
        command.append("--ignored")
    # End option parsing so filters cannot introduce probe or flashing overrides.
    return command + ["--", image, *args.filter]


def test_event(line: str) -> dict[str, object] | None:
    # probe-rs 0.32 uses libtest-mimic JSON lines, but also prints stack traces on stdout.
    # Target logs are also copied to target.txt; JSON-looking stdout is reserved for test events.
    if not line.lstrip().startswith(("{", "[")):
        return None
    try:
        value = cast(object, json.loads(line))
    except json.JSONDecodeError as error:
        raise ValueError(f"Malformed test event: {error.msg}") from error
    if not isinstance(value, dict):
        raise ValueError("Test event must be a JSON object")
    event = cast(dict[str, object], value)
    kind, state = event.get("type"), event.get("event")
    if kind == "suite" and state in ("started", "ok", "failed"):
        return event
    if kind == "test" and state in ("started", "ok", "failed", "ignored"):
        if not isinstance(event.get("name"), str):
            raise ValueError("Test event is missing its name")
        if "stdout" in event and not isinstance(event["stdout"], str):
            raise ValueError("Test failure output must be a string")
        return event
    raise ValueError(f"Unsupported test event: type={kind!r}, event={state!r}")


def suite_result(transcript: str) -> SuiteResult | None:
    """Validate one completed suite; malformed events fail even after a valid summary."""
    expected: int | None = None
    result: SuiteResult | None = None
    for number, line in enumerate(transcript.splitlines(), start=1):
        try:
            event = test_event(line)
            if event is None:
                continue
            if result is not None:
                raise ValueError("Test event after suite completion")
            if event["type"] == "test":
                if expected is None:
                    raise ValueError("Test event before suite start")
                continue
            if event["event"] == "started":
                if expected is not None:
                    raise ValueError("Repeated suite start")
                count = event.get("test_count")
                if type(count) is not int or count < 0:
                    raise ValueError("Suite test_count must be a nonnegative integer")
                expected = count
                continue
            if expected is None:
                raise ValueError("Suite completion without a start")
            counts = [event.get(key) for key in ("passed", "failed", "ignored")]
            if not all(type(count) is int and count >= 0 for count in counts):
                raise ValueError("Suite counts must be nonnegative integers")
            passed, failed, ignored = cast(list[int], counts)
            if passed + failed + ignored != expected:
                raise ValueError("Suite counts do not match test_count")
            if (event["event"] == "ok") != (failed == 0):
                raise ValueError("Suite outcome disagrees with its failure count")
            result = SuiteResult(passed, failed, ignored)
        except ValueError as error:
            raise ValueError(f"stdout line {number}: {error}") from error
    return result


def styled(
    text: str,
    color: Literal["red", "green", "yellow", "cyan", "dim"],
    *,
    stream: TextIO | None = None,
) -> str:
    """Add terminal-only ANSI styling; never put display escapes in saved test events."""
    stream = sys.stdout if stream is None else stream
    if (
        stream is None
        or not stream.isatty()
        or os.environ.get("NO_COLOR")
        or os.environ.get("TERM") == "dumb"
    ):
        return text
    styles = {"red": "1;31", "green": "1;32", "yellow": "1;33", "cyan": "1;36", "dim": "2"}
    return f"\x1b[{styles[color]}m{text}\x1b[0m"


def display_line(line: str, *, list_only: bool = False) -> None:
    """Render test events for people while preserving raw stdout in the report directory."""
    try:
        event = None if list_only else test_event(line)
    except ValueError:
        event = None  # Preserve the offending text; final validation reports the parsing error.
    if event is None:
        print(line, flush=True)
    elif event["type"] == "test":
        labels = {
            "started": styled("RUN ", "cyan"),
            "ok": styled("PASS", "green"),
            "failed": styled("FAIL", "red"),
            "ignored": styled("SKIP", "yellow"),
        }
        print(f"{labels[str(event['event'])]} {event['name']}", flush=True)
        if event.get("stdout"):
            print(event["stdout"], flush=True)
    elif event["event"] == "started":
        count = event.get("test_count")
        noun = "test" if count == 1 else "tests"
        print(styled(f"Running {count} {noun}", "cyan"), flush=True)
    else:
        outcome = styled(f"Suite {event['event']}", "green" if event["event"] == "ok" else "red")
        print(
            f"{outcome}: {event.get('passed')} passed, "
            + f"{event.get('failed')} failed, {event.get('ignored')} ignored",
            flush=True,
        )


def execute(
    command: list[str],
    transcript: Path,
    probe: str,
    image: Path,
    *,
    list_only: bool = False,
    progress: bool = False,
) -> Report:
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    error: str | None = None
    timed_out = False
    exit_code: int | None = None
    start = time.monotonic()
    try:
        exit_code = stream_process(
            command,
            transcript,
            transcript.with_name("stderr.txt"),
            lambda line: display_line(line, list_only=list_only),
            progress=progress,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
        error = "probe-rs exceeded the 180 second deadline"
    except KeyboardInterrupt:
        error = "Hardware test interrupted"
    except OSError as failure:
        error = str(failure)
    duration = time.monotonic() - start
    suite: SuiteResult | None = None
    if not list_only and transcript.exists():
        try:
            suite = suite_result(transcript.read_text(errors="replace"))
        except ValueError as failure:
            error = str(failure) if error is None else f"{error}; {failure}"
    if error is None:
        # A failed suite already explains exit 1. Keep runner errors distinct from test failures.
        if suite is not None and suite.failed and exit_code == 1:
            pass
        elif exit_code != 0:
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
    required_environment = (
        "PROBE_RS",
        "DIRECT_LINE_ELF",
        "DIRECT_LINE_TARGET",
        "BUILD_WORKSPACE_DIRECTORY",
    )
    if any(not os.environ.get(name) for name in required_environment):
        parser.error(
            "Bazel environment is missing; run: bazel run //tools/debug:hil -- --probe SERIAL"
        )
    runtime = runfiles.Create()
    if runtime is None:
        parser.error(
            "Bazel runfiles are unavailable; run: bazel run //tools/debug:hil -- --probe SERIAL"
        )
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
    transcript = directory / "stdout.txt"
    progress = sys.stderr.isatty()
    with probe_lock(args.probe):
        report = execute(
            command_line(
                executable, image, target, args, directory / "target.txt", progress=progress
            ),
            transcript,
            args.probe,
            Path(image),
            list_only=args.list,
            progress=progress,
        )
    (directory / "report.json").write_text(json.dumps(asdict(report), indent=2) + "\n")
    duration = styled(f"Host process time: {report.duration_s:.3f}s", "dim")
    report_path = styled(str(directory / "report.json"), "cyan")
    print(f"{duration}\nReport: {report_path}", flush=True)
    if report.error is not None:
        raise SystemExit(styled(report.error, "red", stream=sys.stderr))
    raise SystemExit(1 if report.suite is not None and report.suite.failed else 0)


if __name__ == "__main__":
    main()

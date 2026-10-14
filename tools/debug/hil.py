"""Flash one suite per explicit board and run isolated cases through the TI debugger."""

import argparse
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import secrets
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from python.runfiles import runfiles

from tools.debug import process
from tools.debug.elf import Elf
from tools.debug.hil_types import BoardResult, Case, CaseResult, RunConfig, RunResult, SelectedCase
from tools.debug.transport import config_for_probe, program_image


@dataclass
class Arguments(argparse.Namespace):
    dslite: Path | None = None
    ccs_worker: Path | None = None
    elf: Path | None = None
    probe: list[str] = field(default_factory=list)
    list: bool = False
    check_runtime: bool = False
    filter: str = "*"
    output_dir: Path | None = None


def words(value: object) -> list[int]:
    """Decode unsigned target words from a debugger report."""
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for word in cast(list[object], value):
        if not isinstance(word, (int, float)) or not 0 <= word <= 0xFFFFFFFF or word != int(word):
            return []
        result.append(int(word))
    return result


def read_report(path: Path) -> tuple[list[dict[str, object]], str | None]:
    """Validate the JSON container before interpreting individual case records."""
    if not path.exists():
        return [], "Debugger did not write a report"
    value = cast(object, json.loads(path.read_text()))
    if not isinstance(value, dict):
        raise ValueError("Invalid debugger report object")
    raw = cast(dict[str, object], value)
    cases = raw.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Invalid debugger case list")
    observations: list[dict[str, object]] = []
    for case in cast(list[object], cases):
        if not isinstance(case, dict):
            raise ValueError("Invalid debugger case object")
        observations.append(cast(dict[str, object], case))
    errors = [str(raw[key]) for key in ("error", "cleanup_error", "stop_error") if raw.get(key)]
    return observations, "; ".join(errors) if errors else None


def address_equal(actual: object, expected: int) -> bool:
    """Compare instruction addresses with the Thumb bit cleared."""
    return (
        isinstance(actual, (int, float))
        and 0 <= actual <= 0xFFFFFFFF
        and actual == int(actual)
        and int(actual) & ~1 == expected & ~1
    )


def evaluate(case: SelectedCase, observation: dict[str, object], done: int) -> str | None:
    """Require a fresh matching result before interpreting any terminal state."""
    if observation.get("error"):
        return str(observation["error"])
    result = words(observation.get("result"))
    diagnostic = words(observation.get("diagnostic"))
    if len(result) != 4 or result[:3] != [1, case["id"], case["token"]]:
        return "Missing or stale case result"
    if len(diagnostic) != 7 or diagnostic[0] != 0x444C5253:
        return "Invalid boot diagnostic"
    status, stage = result[3], diagnostic[1]
    expected = case["expected"]
    if expected == 0:
        valid = (
            status == 2
            and stage == 2
            and not observation.get("timed_out", True)
            and address_equal(observation.get("pc"), done)
        )
    elif expected == 1:
        valid = status == 1 and stage == 0xFFFF0002
    elif expected == 2:
        valid = status == 1 and stage == 0xFFFF0001 and diagnostic[2:5] == [6, 1 << 16, 0]
    else:
        valid = status == 1 and stage == 2 and observation.get("timed_out") is True
    return None if valid else f"Unexpected terminal state: {observation}"


@contextmanager
def probe_lock(serial: str) -> Generator[None]:
    # Stable per-user lock path, independent of checkout/output directory.
    directory = Path(tempfile.gettempdir()) / f"direct-line-probes-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / serial).open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(f"Probe {serial} is in use by another runner") from error
        yield


def run_debugger(args: RunConfig, request: Path | str, directory: Path, timeout: float) -> int:
    command = [str(args.ccs_worker), str(args.dslite.parents[3]), str(request)]
    try:
        return process.run(command, directory / "debugger.log", timeout)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Debugger process deadline exceeded") from error


def execute(args: RunConfig, elf: Elf, cases: list[Case], directory: Path) -> RunResult:
    config = directory / "probe.ccxml"
    config_for_probe(args.probe, config)
    identity = program_image(args.dslite, args.elf, config, directory)
    selected: list[SelectedCase] = [
        {**case, "token": secrets.randbelow(0x7FFFFFFE) + 1} for case in cases
    ]
    report = directory / "debugger.json"
    request = directory / "request.json"
    addresses = {
        key: elf.address(symbol, size)
        for key, symbol, size in [
            ("ready", "hil_ready", None),
            ("done", "hil_done", None),
            ("request", "HIL_REQUEST", 8),
            ("result", "HIL_RESULT", 16),
            ("diagnostic", "BOOT_DIAGNOSTIC", 28),
        ]
    }
    _ = request.write_text(
        json.dumps(
            dict(
                config=str(config),
                elf=str(args.elf),
                report=str(report),
                cases=selected,
                **addresses,
            )
        )
    )
    process_error = None
    try:
        status = run_debugger(
            args, request, directory, 60 + sum(60 + case["timeout_ms"] / 1000 for case in selected)
        )
    except (OSError, RuntimeError) as error:
        status = None
        process_error = str(error)
    try:
        observed, report_error = read_report(report)
    except ValueError as error:
        observed, report_error = [], str(error)
    results: list[CaseResult] = []
    for index, case in enumerate(selected):
        observation: dict[str, object] = (
            observed[index] if index < len(observed) else {"error": "Case not executed"}
        )
        case_error = evaluate(case, observation, addresses["done"])
        results.append(
            {**case, "passed": case_error is None, "error": case_error, "observation": observation}
        )
    return RunResult(
        identity=identity,
        cases=results,
        process_exit_code=status,
        debugger_error=process_error or report_error,
        passed=status == 0
        and len(observed) == len(selected)
        and not report_error
        and all(case["passed"] for case in results),
    )


def junit(reports: list[BoardResult], destination: Path) -> None:
    suite = ET.Element("testsuite", name="direct_line_hil")
    for report in reports:
        cases = report.get("cases", [])
        for case in cases:
            node = ET.SubElement(suite, "testcase", classname=report["probe"], name=case["name"])
            if not case["passed"]:
                _ = ET.SubElement(node, "failure", message=case["error"] or "Case failed")
        if not report["passed"] and (
            report.get("error")
            or report.get("debugger_error")
            or not cases
            or all(case["passed"] for case in cases)
        ):
            node = ET.SubElement(suite, "testcase", classname=report["probe"], name="debugger")
            _ = ET.SubElement(
                node,
                "error",
                message=str(
                    report.get("error") or report.get("debugger_error") or "Debugger failed"
                ),
            )
    suite.set("tests", str(len(suite)))
    suite.set("failures", str(len(suite.findall("testcase/failure"))))
    suite.set("errors", str(len(suite.findall("testcase/error"))))
    ET.ElementTree(suite).write(destination, encoding="utf-8", xml_declaration=True)


def result_directory(path: Path | None, prefix: str) -> Path:
    """Keep raw run output outside versioned source, with a unique run directory."""
    if path is not None:
        return path.resolve()
    root = Path(".results").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix + "-", dir=root))


def provenance(dslite: Path, ccs_worker: Path) -> dict[str, str]:
    """Record selected tool overrides as well as the default pinned executables."""
    result: dict[str, str] = {}
    for name, path in (
        ("dslite", dslite),
        ("ccs_worker", ccs_worker),
        ("cloudagent_node", dslite.parents[2] / "cloudagent/node"),
    ):
        path = path.resolve(strict=True)
        result[name] = str(path)
        result[name + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> int:
    resolver = runfiles.Create()

    def declared_path(name: str) -> Path | None:
        value = os.environ.get(name)
        if value is None:
            return None
        if resolver is None or (resolved := resolver.Rlocation(value)) is None:
            raise RuntimeError(f"Cannot resolve declared Bazel input {name}={value}")
        return Path(resolved).resolve(strict=True)

    args = Arguments(
        dslite=declared_path("DIRECT_LINE_DSLITE"),
        ccs_worker=declared_path("DIRECT_LINE_CCS_WORKER"),
        elf=declared_path("DIRECT_LINE_ELF"),
    )
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "--dslite",
        type=Path,
        help="Override the pinned TI debugger (recorded in results)",
    )
    _ = parser.add_argument("--ccs-worker", type=Path)
    _ = parser.add_argument(
        "--probe",
        action="append",
        help="Explicit XDS110 serial; repeat for multiple boards",
    )
    _ = parser.add_argument("--elf", type=Path)
    _ = parser.add_argument(
        "--list", action="store_true", help="List ELF cases without accessing a probe"
    )
    _ = parser.add_argument(
        "--check-runtime", action="store_true", help="Check CCS Scripting without a probe"
    )
    _ = parser.add_argument("--filter", help="Case-name shell glob")
    _ = parser.add_argument("--output-dir", type=Path)
    _ = parser.parse_args(namespace=args)
    if workspace := os.environ.get("BUILD_WORKSPACE_DIRECTORY"):
        os.chdir(workspace)
    if args.dslite is None:
        parser.error("Use the Bazel target or provide --dslite")
    if args.elf is None:
        parser.error("Use the Bazel target or provide --elf")
    args.elf = args.elf.resolve(strict=True)
    image = args.elf.read_bytes()
    elf = Elf(image)
    cases = [case for case in elf.cases() if fnmatch.fnmatchcase(case["name"], args.filter)]
    if not cases:
        parser.error("Filter matched no cases")
    if args.list:
        for case in cases:
            print(f"{case['name']} ({case['timeout_ms']} ms, expected={case['expected']})")
        return 0
    if args.ccs_worker is None:
        parser.error("Use the Bazel target or supply --ccs-worker")
    if args.check_runtime:
        directory = result_directory(args.output_dir, "ccs-runtime")
        directory.mkdir(parents=True, exist_ok=True)
        config = RunConfig(
            "", args.elf, args.dslite.resolve(strict=True), args.ccs_worker.resolve(strict=True)
        )
        status = run_debugger(config, "--check-runtime", directory, 60)
        print((directory / "debugger.log").read_text())
        print(f"Reports: {directory}")
        return status
    if not args.probe or any(not re.fullmatch(r"[A-Za-z0-9_-]+", probe) for probe in args.probe):
        parser.error("Provide at least one explicit XDS110 serial with --probe")
    directory = result_directory(args.output_dir, "hil")
    directory.mkdir(parents=True, exist_ok=True)
    reports: list[BoardResult] = []
    probes = list(dict.fromkeys(args.probe))
    for probe in probes:
        config = RunConfig(
            probe, args.elf, args.dslite.resolve(strict=True), args.ccs_worker.resolve(strict=True)
        )
        board_directory = directory / probe
        board_directory.mkdir(exist_ok=False)
        result: BoardResult = BoardResult(
            probe=probe,
            elf_sha256=hashlib.sha256(image).hexdigest(),
            tools=provenance(config.dslite, config.ccs_worker),
            passed=False,
        )
        try:
            with probe_lock(probe):
                result = {**result, **execute(config, elf, cases, board_directory)}
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            result["error"] = str(error)
        reports.append(result)
        _ = (board_directory / "report.json").write_text(json.dumps(result, indent=2) + "\n")
        for case in result.get("cases", []):
            print(f"{probe} {'PASS' if case['passed'] else 'FAIL'} {case['name']}", flush=True)
        summary_error = result.get("error") or result.get("debugger_error")
        if not summary_error:
            summary_error = next(
                (case["error"] for case in result.get("cases", []) if case["error"]), None
            )
        if summary_error:
            print(f"{probe} ERROR {summary_error}", flush=True)
    _ = (directory / "report.json").write_text(json.dumps(reports, indent=2) + "\n")
    junit(reports, directory / "junit.xml")
    print(f"Reports: {directory}")
    return 0 if all(report["passed"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())

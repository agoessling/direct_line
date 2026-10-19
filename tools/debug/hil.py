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
import time
import xml.etree.ElementTree as ET
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

from python.runfiles import runfiles

from tools.debug import process
from tools.debug.elf import Elf
from tools.debug.protocol import (
    BOOT_DIAGNOSTIC_WORDS,
    REQUEST_WORDS,
    RESULT_WORDS,
    WORD_BYTES,
    BoardResult,
    Case,
    CaseResult,
    RunConfig,
    RunResult,
    SelectedCase,
    evaluate,
)


@dataclass
class Arguments(argparse.Namespace):
    probe: list[str] = field(default_factory=list)
    suite: list[str] = field(default_factory=list)
    list: bool = False
    check_runtime: bool = False
    filter: str = "*"
    output_dir: Path | None = None


def select_cases(cases: list[Case], suites: list[str], pattern: str) -> list[Case]:
    """Select the union of named suites, then apply the case-name glob."""
    known = {suite for case in cases for suite in case["suites"]}
    unknown = set(suites) - known
    if unknown:
        raise ValueError(
            f"Unknown suites: {', '.join(sorted(unknown))}; available: {', '.join(sorted(known))}"
        )
    selected = [
        case
        for case in cases
        if (not suites or any(suite in case["suites"] for suite in suites))
        and fnmatch.fnmatchcase(case["name"], pattern)
    ]
    if not selected:
        raise ValueError("Suite/filter selection matched no cases")
    return selected


def read_report(path: Path) -> tuple[list[dict[str, object]], str | None, dict[str, str]]:
    """Validate the JSON container before interpreting individual case records."""
    if not path.exists():
        return [], "Debugger did not write a report", {}
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
    identity: dict[str, str] = {}
    raw_identity = raw.get("identity")
    if raw_identity is None:
        raw_identity = {}
    if not isinstance(raw_identity, dict):
        raise ValueError("Invalid debugger identity object")
    for name, value in cast(dict[str, object], raw_identity).items():
        if not isinstance(value, str):
            raise ValueError("Invalid debugger identity value")
        identity[name] = value
    return observations, "; ".join(errors) if errors else None, identity


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


def run_debugger(args: RunConfig, request: Path | None, directory: Path, timeout: float) -> int:
    command = [str(args.ccs_worker), "--ccs-root", str(args.dslite.parents[3])]
    command += ["--check-runtime"] if request is None else ["--request", str(request)]
    try:
        return process.run(command, directory / "debugger.log", timeout)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Debugger process deadline exceeded") from error


def config_for_probe(serial: str, destination: Path) -> None:
    tree = ET.parse(Path(__file__).with_name("xds110_cc1354p10.ccxml"))
    connection = tree.find(".//connection")
    if connection is None:
        raise ValueError("Probe template lacks a connection")
    platform = connection.find("platform")
    if platform is None:
        raise ValueError("Probe template lacks a platform")
    selection = ET.Element(
        "property", {"Type": "choicelist", "Value": "1", "id": "Debug Probe Selection"}
    )
    choice = ET.SubElement(selection, "choice", {"Name": "Select by serial number", "value": "0"})
    ET.SubElement(
        choice,
        "property",
        {"Type": "stringfield", "Value": serial, "id": "-- Enter the serial number"},
    )
    connection.insert(list(connection).index(platform), selection)
    tree.write(destination, encoding="UTF-8", xml_declaration=True)


def execute(args: RunConfig, elf: Elf, cases: list[Case], directory: Path) -> RunResult:
    started = time.monotonic()
    config = directory / "probe.ccxml"
    config_for_probe(args.probe, config)
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
            ("request", "HIL_REQUEST", REQUEST_WORDS * WORD_BYTES),
            ("result", "HIL_RESULT", RESULT_WORDS * WORD_BYTES),
            ("diagnostic", "BOOT_DIAGNOSTIC", BOOT_DIAGNOSTIC_WORDS * WORD_BYTES),
        ]
    }
    request.write_text(
        json.dumps(
            dict(
                probe=args.probe,
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
        observed, report_error, identity = read_report(report)
    except ValueError as error:
        observed, report_error, identity = [], str(error), {}
    results: list[CaseResult] = []
    for index, case in enumerate(selected):
        observation: dict[str, object] = (
            observed[index] if index < len(observed) else {"error": "Case not executed"}
        )
        case_error = evaluate(case, observation, addresses["done"])
        results.append(
            CaseResult(case, passed=case_error is None, error=case_error, observation=observation)
        )
    return RunResult(
        duration_s=time.monotonic() - started,
        identity=identity,
        cases=results,
        process_exit_code=status,
        debugger_error=process_error or report_error,
        passed=status == 0
        and len(observed) == len(selected)
        and not report_error
        and all(case.passed for case in results),
    )


def result_directory(path: Path | None, prefix: str) -> Path:
    """Keep raw run output outside versioned source, with a unique run directory."""
    if path is not None:
        return path.resolve()
    root = Path(".results").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix + "-", dir=root))


def provenance(dslite: Path, ccs_worker: Path) -> dict[str, str]:
    """Record the paths and hashes of the pinned executables."""
    result: dict[str, str] = {}
    for name, path in (
        ("dslite", dslite),
        ("ccs_worker", ccs_worker),
        ("xds110reset", dslite.parents[2] / "common/uscif/xds110/xds110reset"),
        ("cloudagent_node", dslite.parents[2] / "cloudagent/node"),
    ):
        path = path.resolve(strict=True)
        result[name] = str(path)
        result[name + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    resolver = runfiles.Create()

    def declared_path(name: str) -> Path:
        value = os.environ.get(name)
        if value is None:
            parser.error("Run through bazel run //tools/debug:hil")
        if resolver is None or (resolved := resolver.Rlocation(value)) is None:
            raise RuntimeError(f"Cannot resolve declared Bazel input {name}={value}")
        return Path(resolved).resolve(strict=True)

    parser.add_argument(
        "--probe",
        action="append",
        help="Explicit XDS110 serial; repeat for multiple boards",
    )
    parser.add_argument(
        "--list", action="store_true", help="List ELF cases without accessing a probe"
    )
    parser.add_argument(
        "--check-runtime", action="store_true", help="Check CCS Scripting without a probe"
    )
    parser.add_argument("--filter", help="Case-name shell glob")
    parser.add_argument("--suite", action="append", help="Named suite; repeat to select a union")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(namespace=Arguments())
    if workspace := os.environ.get("BUILD_WORKSPACE_DIRECTORY"):
        os.chdir(workspace)
    elf_path = declared_path("DIRECT_LINE_ELF")
    image = elf_path.read_bytes()
    elf = Elf(image)
    try:
        cases = select_cases(elf.cases(), args.suite, args.filter)
    except ValueError as error:
        parser.error(str(error))
    if args.list:
        for case in cases:
            print(
                f"{case['name']} ({case['timeout_ms']} ms, expected={case['expected']}, "
                + f"suites={','.join(case['suites'])})"
            )
        return 0
    dslite = declared_path("DIRECT_LINE_DSLITE")
    ccs_worker = declared_path("DIRECT_LINE_CCS_WORKER")
    if args.check_runtime:
        directory = result_directory(args.output_dir, "ccs-runtime")
        directory.mkdir(parents=True, exist_ok=True)
        config = RunConfig("", elf_path, dslite, ccs_worker)
        status = run_debugger(config, None, directory, 60)
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
        config = RunConfig(probe, elf_path, dslite, ccs_worker)
        board_directory = directory / probe
        board_directory.mkdir(exist_ok=False)
        result: BoardResult = BoardResult(
            probe=probe,
            elf_sha256=hashlib.sha256(image).hexdigest(),
            tools=provenance(config.dslite, config.ccs_worker),
        )
        try:
            with probe_lock(probe):
                result.run = execute(config, elf, cases, board_directory)
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            result.error = str(error)
        reports.append(result)
        (board_directory / "report.json").write_text(json.dumps(asdict(result), indent=2) + "\n")
        summary_error = result.error
        if result.run is not None:
            for case in result.run.cases:
                print(
                    f"{probe} {'PASS' if case.passed else 'FAIL'} {case.case['name']}", flush=True
                )
            print(f"{probe} completed in {result.run.duration_s:.2f}s", flush=True)
            summary_error = (
                summary_error
                or result.run.debugger_error
                or next((case.error for case in result.run.cases if case.error), None)
            )
        if summary_error:
            print(f"{probe} ERROR {summary_error}", flush=True)
    (directory / "report.json").write_text(
        json.dumps([asdict(report) for report in reports], indent=2) + "\n"
    )
    print(f"Reports: {directory}")
    return 0 if all(report.passed for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run isolated HIL cases in one CCS Scripting session, bounded by the parent process."""

import argparse
import json
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal, TypedDict, cast

from scripting import DebuggerScripting, ScriptingOptions, initScripting
from scripting.generated_types.Scripting import DebugSession
from scripting.generated_types.Scripting.common import CallstackResult, VersionResult

from tools.debug.protocol import (
    BOOT_DIAGNOSTIC_WORDS,
    INVALID_CASE_ID,
    NO_TOKEN,
    PROTOCOL_VERSION,
    REQUEST_WORDS,
    RESULT_WORDS,
    THUMB_BIT,
    WORD_BITS,
    BootDiagnostic,
    BootStage,
    DebugRequest,
    ExpectedOutcome,
    Result,
    SelectedCase,
    Status,
    evaluate,
    words,
)

DEBUGGER_TIMEOUT_MS = 20_000
STARTUP_TIMEOUT_MS = 10_000
HALT_POLL_INTERVAL_S = 0.005
RESET_RETRY_DELAY_S = 0.1


type ResetStep = Literal[
    "remove_breakpoints",
    "disconnect_cpu",
    "disconnect_dap",
    "disconnect_icepick",
    "board_reset",
    "connect_icepick",
    "connect_dap",
    "connect_cpu",
    "halt",
]


@dataclass
class CaseTimings:
    reset: float | None = None
    ready: float | None = None
    execution: float | None = None
    capture: float | None = None


@dataclass
class RunTimings:
    connect: float | None = None
    identify_program_verify: float | None = None
    cleanup: float | None = None
    total: float | None = None


@dataclass
class CaseObservation:
    case: SelectedCase
    # Fields accumulate as the case runs; a debugger failure can leave a partial record.
    phase: str | None = None
    timings_s: CaseTimings | None = None
    reset_errors: list[str] | None = None
    reset_attempt_timings_s: list[dict[ResetStep, float]] | None = None
    timed_out: bool | None = None
    pc: int | None = None
    result: list[int] | None = None
    diagnostic: list[int] | None = None
    request: list[int] | None = None
    registers: dict[str, int] | None = None
    register_errors: dict[str, str] | None = None
    stack: CallstackResult | None = None
    stack_error: str | None = None
    error: str | None = None
    capture_error: str | None = None


class SiliconIdentity(TypedDict):
    user_id: str
    icepick_id: str


@dataclass
class WorkerReport:
    cases: list[CaseObservation] = field(default_factory=list)
    timings_s: RunTimings = field(default_factory=RunTimings)
    identity: SiliconIdentity | None = None
    version: VersionResult | None = None
    error: str | None = None
    cleanup_error: str | None = None
    stop_error: str | None = None


@dataclass
class Arguments(argparse.Namespace):
    ccs_root: Path | None = None
    request: Path | None = None
    check_runtime: bool = False


def read_words(session: DebugSession, address: int, count: int) -> list[int]:
    return [int(value) for value in session.memory.read(address, count, WORD_BITS)]


def hardware_breakpoint(session: DebugSession, address: int) -> None:
    # CCS Breakpoints.createProperties: use a comparator to avoid patching flash.
    HARDWARE_BREAKPOINT = 1
    properties = session.breakpoints.createProperties(HARDWARE_BREAKPOINT)
    session.breakpoints.setProperty(
        properties, "Hardware Configuration.Type.Location", hex(address)
    )
    if session.breakpoints.addWithProperties(properties) < 0:
        raise RuntimeError("Hardware breakpoint creation failed")


def wait_halted(session: DebugSession, timeout_ms: int) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    while not session.target.isHalted():
        if time.monotonic() >= deadline:
            return False
        time.sleep(HALT_POLL_INTERVAL_S)
    return True


def on_parent(expression: str) -> str:
    return f'GEL_EvalOnTarget("<parent>", {json.dumps(expression)}, 1)'


def reset(session: DebugSession, result: CaseObservation, reset_tool: Path, probe: str) -> None:
    MAX_ATTEMPTS = 2
    errors: list[str] = []
    result.reset_errors = errors
    attempts: list[dict[ResetStep, float]] = []
    result.reset_attempt_timings_s = attempts

    @contextmanager
    def measure(step: ResetStep) -> Generator[None]:
        started = time.monotonic()
        try:
            yield
        finally:
            # Preserve the duration of a failing call as well as successful attempts.
            timings[step] = time.monotonic() - started

    for attempt in range(MAX_ATTEMPTS):
        timings: dict[ResetStep, float] = {}
        attempts.append(timings)
        try:
            result.phase = "disconnect for board reset"
            with measure("remove_breakpoints"):
                session.breakpoints.removeAll()
            # TI cc26x4_xds.gel disconnects CPU, DAP, and ICEPick before board reset.
            cpu_disconnect = "DisconnectIfConnected()"
            dap_disconnect = on_parent(cpu_disconnect)
            icepick_disconnect = on_parent(dap_disconnect)
            with measure("disconnect_cpu"):
                session.expressions.evaluate(cpu_disconnect)
            with measure("disconnect_dap"):
                session.expressions.evaluate(dap_disconnect)
            with measure("disconnect_icepick"):
                session.expressions.evaluate(icepick_disconnect)
            result.phase = "board reset"
            with measure("board_reset"):
                # Pulse nSRST using TI's utility; CCS Board Reset adds about 600 ms here.
                subprocess.run(
                    [str(reset_tool), "--serial", probe, "--delay", "50"],
                    check=True,
                    timeout=5,
                )
            result.phase = "reconnect after reset"
            # ICEPick's connect hook wakes the MCU domain before DAP access.
            dap_connect = on_parent("ConnectIfDisconnected()")
            icepick_connect = on_parent(dap_connect)
            with measure("connect_icepick"):
                session.expressions.evaluate(icepick_connect)
            with measure("connect_dap"):
                session.expressions.evaluate(dap_connect)
            with measure("connect_cpu"):
                session.target.connect()
            with measure("halt"):
                session.target.halt()
            return
        except Exception as error:
            errors.append(str(error))
            if attempt + 1 == MAX_ATTEMPTS:
                raise
            # Retry transport setup only, before writing a test request.
            time.sleep(RESET_RETRY_DELAY_S)


def capture_details(session: DebugSession, result: CaseObservation) -> None:
    """Read expensive debugger context only when a case needs investigation."""
    registers: dict[str, int] = {}
    if result.pc is not None:
        registers["PC"] = result.pc
    errors: dict[str, str] = {}
    for name in ("SP", "LR", "xPSR"):
        try:
            registers[name] = int(session.registers.read(name))
        except Exception as error:
            errors[name] = str(error)
    result.registers = registers
    if errors:
        result.register_errors = errors
    try:
        result.stack = session.callstack.fetch()
    except Exception as error:
        result.stack_error = str(error)


def run_case(
    session: DebugSession,
    request: DebugRequest,
    case: SelectedCase,
    result: CaseObservation,
    reset_tool: Path,
) -> None:
    timings = CaseTimings()
    result.timings_s = timings
    started = time.monotonic()
    reset(session, result, reset_tool, request["probe"])
    timings.reset = time.monotonic() - started
    started = time.monotonic()
    ready, done = request["ready"] & ~THUMB_BIT, request["done"] & ~THUMB_BIT
    hardware_breakpoint(session, ready)
    result.phase = "run to ready"
    if int(session.registers.read("PC")) & ~THUMB_BIT != ready:
        # Resume asynchronously; the host enforces the startup deadline.
        session.target.run(False)
        if not wait_halted(session, STARTUP_TIMEOUT_MS):
            session.target.halt()
            raise RuntimeError("Startup timeout")
    pc = int(session.registers.read("PC")) & ~THUMB_BIT
    if pc != ready:
        raise RuntimeError(f"Unexpected startup halt at {pc:#x}")
    # Fresh .data/.bss state must precede every case, including after panic or fault.
    boot = BootDiagnostic.from_words(
        read_words(session, request["diagnostic"], BOOT_DIAGNOSTIC_WORDS)
    )
    initial_request = words(read_words(session, request["request"], REQUEST_WORDS), REQUEST_WORDS)
    if boot != BootDiagnostic(BootStage.APPLICATION, None) or initial_request != [
        INVALID_CASE_ID,
        NO_TOKEN,
    ]:
        raise RuntimeError("Request or diagnostic was not reinitialized by startup")
    initial_result = Result.from_words(read_words(session, request["result"], RESULT_WORDS))
    if initial_result != Result(PROTOCOL_VERSION, INVALID_CASE_ID, NO_TOKEN, Status.IDLE):
        raise RuntimeError("HIL result was not reinitialized by startup")
    timings.ready = time.monotonic() - started
    started = time.monotonic()
    result.phase = "select case"
    session.breakpoints.removeAll()
    session.memory.write(request["request"], [case["id"], case["token"]], WORD_BITS)
    hardware_breakpoint(session, done)
    result.phase = "run case"
    # Panic/fault handlers stay in their loops until the host deadline expires.
    session.target.run(False)
    completed = wait_halted(session, case["timeout_ms"])
    if not completed:
        session.target.halt()
    timings.execution = time.monotonic() - started
    started = time.monotonic()
    # The halted CPU leaves the multiword result and diagnostic records stable.
    result.timed_out = not completed
    result.pc = int(session.registers.read("PC"))
    result.result = read_words(session, request["result"], RESULT_WORDS)
    result.diagnostic = read_words(session, request["diagnostic"], BOOT_DIAGNOSTIC_WORDS)
    if (
        case["expected"] in (ExpectedOutcome.PANIC, ExpectedOutcome.FAULT)
        or evaluate(case, asdict(result), done) is not None
    ):
        capture_details(session, result)
    timings.capture = time.monotonic() - started


def program_image(session: DebugSession, image: str, report: WorkerReport) -> None:
    # TI SDK hw_memmap.h/hw_fcfg1.h define fields; chipinfo.c identifies the wafer.
    FCFG1_USER_ID = 0x50000A94
    FCFG1_ICEPICK_DEVICE_ID = 0x50000B18
    WAFER_ID_SHIFT = 12
    WAFER_ID_MASK = 0xFFFF
    CC13X4_CC26X4_WAFER_ID = 0xBB78
    PROTOCOL_SHIFT = 12
    PROTOCOL_MASK = 0xF
    ALL_PROTOCOLS = 0xF  # BLE, RF4CE, Zigbee/6LoWPAN, and proprietary.
    CC13 = 1 << 23
    POWER_AMPLIFIER = 1 << 25

    user = read_words(session, FCFG1_USER_ID, 1)[0]
    icepick = read_words(session, FCFG1_ICEPICK_DEVICE_ID, 1)[0]
    report.identity = {"user_id": f"0x{user:08x}", "icepick_id": f"0x{icepick:08x}"}
    wafer_id = (icepick >> WAFER_ID_SHIFT) & WAFER_ID_MASK
    protocols = (user >> PROTOCOL_SHIFT) & PROTOCOL_MASK
    if (
        wafer_id != CC13X4_CC26X4_WAFER_ID
        or protocols != ALL_PROTOCOLS
        or not user & CC13
        or not user & POWER_AMPLIFIER
    ):
        raise RuntimeError("Silicon IDs do not match the expected CC13x4 family and capabilities")
    # Use the complete ELF, including CCFG; the TI loader owns flash programming.
    session.memory.loadProgram(image)
    session.target.halt()
    session.memory.verifyProgram(image)


def cleanup_session(session: DebugSession) -> list[str]:
    errors: list[str] = []
    # A failed halt must not prevent breakpoint removal or disconnect.
    for name, action in (
        ("halt", session.target.halt),
        ("remove breakpoints", session.breakpoints.removeAll),
        ("disconnect", session.target.disconnect),
    ):
        try:
            action()
        except Exception as error:
            errors.append(f"{name}: {error}")
    return errors


def execute(ccs_root: Path, request: DebugRequest) -> int:
    reset_tool = ccs_root / "ccs_base/common/uscif/xds110/xds110reset"
    started = time.monotonic()
    timings = RunTimings()
    results: list[CaseObservation] = []
    report = WorkerReport(cases=results, timings_s=timings)
    destination = Path(request["report"])

    def save() -> None:
        # A killed debugger must leave the last completed report readable.
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(report), indent=2) + "\n")
        temporary.replace(destination)

    debugger: DebuggerScripting | None = None
    session: DebugSession | None = None
    status = 0
    try:
        debugger = initScripting(
            ScriptingOptions(ccsRoot=str(ccs_root), timeout=DEBUGGER_TIMEOUT_MS)
        )
        report.version = debugger.versionInfo()
        debugger.configure(request["config"])
        # TI's wrapper forwards members dynamically; its generated interface describes them.
        session = cast(DebugSession, cast(object, debugger.openSession("Cortex_M33_0")))
        # Keep execution under the runner's ready/done breakpoints after every reset.
        session.settings.set("AutoRunToLabelOnRestart", False)
        session.settings.set("AutoRunToLabelOnReset", False)
        session.target.connect()
        session.target.halt()
        timings.connect = time.monotonic() - started
        phase_started = time.monotonic()
        program_image(session, request["elf"], report)
        timings.identify_program_verify = time.monotonic() - phase_started
        save()
        for case in request["cases"]:
            result = CaseObservation(case)
            results.append(result)
            try:
                run_case(session, request, case, result, reset_tool)
            except Exception as error:
                result.error = str(error)
                try:
                    session.target.halt()
                    result.diagnostic = read_words(
                        session, request["diagnostic"], BOOT_DIAGNOSTIC_WORDS
                    )
                    result.result = read_words(session, request["result"], RESULT_WORDS)
                    result.request = read_words(session, request["request"], REQUEST_WORDS)
                    result.pc = int(session.registers.read("PC"))
                    capture_details(session, result)
                except Exception as capture_error:
                    result.capture_error = str(capture_error)
                status = 1
                save()
                break
            save()
    except Exception as error:
        report.error = str(error)
        status = 1
    finally:
        cleanup_started = time.monotonic()
        if session is not None:
            cleanup_errors = cleanup_session(session)
            if cleanup_errors:
                report.cleanup_error = "; ".join(cleanup_errors)
                status = 1
        if debugger is not None:
            try:
                debugger.shutdown()
            except Exception as error:
                report.stop_error = str(error)
                status = 1
        timings.cleanup = time.monotonic() - cleanup_started
        timings.total = time.monotonic() - started
        save()
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ccs-root", type=Path, required=True, help="TI CCS runtime directory")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--request", type=Path, help="JSON request written by the parent runner")
    mode.add_argument(
        "--check-runtime", action="store_true", help="Check the runtime without a probe"
    )
    args = parser.parse_args(namespace=Arguments())
    assert args.ccs_root is not None
    if args.check_runtime:
        debugger = initScripting(
            ScriptingOptions(ccsRoot=str(args.ccs_root), timeout=DEBUGGER_TIMEOUT_MS)
        )
        try:
            print(json.dumps(debugger.versionInfo()))
        finally:
            debugger.shutdown()
        return 0
    # The parent runner writes this request from validated ELF metadata.
    assert args.request is not None
    request = cast(DebugRequest, json.loads(args.request.read_text()))
    return execute(args.ccs_root, request)


if __name__ == "__main__":
    raise SystemExit(main())

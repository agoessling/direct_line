"""Run isolated HIL cases in one CCS Scripting session, bounded by the parent process."""

import json
import sys
import time
from pathlib import Path
from typing import cast

from scripting import DebuggerScripting, ScriptingOptions, initScripting
from scripting.generated_types.Scripting import DebugSession

from tools.debug.protocol import DebugRequest, SelectedCase, evaluate


def read_words(session: DebugSession, address: int, count: int) -> list[int]:
    return [int(value) for value in session.memory.read(address, count, 32)]


def hardware_breakpoint(session: DebugSession, address: int) -> None:
    # Type 1 selects a hardware comparator; the default breakpoint can patch flash.
    properties = session.breakpoints.createProperties(1)
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
        time.sleep(0.005)
    return True


def on_parent(expression: str) -> str:
    return f'GEL_EvalOnTarget("<parent>", {json.dumps(expression)}, 1)'


def reset(session: DebugSession, result: dict[str, object]) -> None:
    errors: list[str] = []
    result["reset_errors"] = errors
    for attempt in range(2):
        try:
            result["phase"] = "disconnect for board reset"
            session.breakpoints.removeAll()
            # TI cc26x4_xds.gel disconnects CPU, DAP, and ICEPick before board reset.
            disconnect = "DisconnectIfConnected()"
            for expression in (disconnect, on_parent(disconnect), on_parent(on_parent(disconnect))):
                _ = session.expressions.evaluate(expression)
            result["phase"] = "board reset"
            if not session.target.getResets().get("Board Reset"):
                raise RuntimeError("Board reset not allowed after disconnect")
            session.target.reset("Board Reset")
            result["phase"] = "reconnect after reset"
            # ICEPick's connect hook wakes the MCU domain before DAP access.
            connect = "ConnectIfDisconnected()"
            _ = session.expressions.evaluate(on_parent(on_parent(connect)))
            _ = session.expressions.evaluate(on_parent(connect))
            session.target.connect()
            session.target.halt()
            return
        except Exception as error:
            errors.append(str(error))
            if attempt == 1:
                raise
            # Retry transport setup only, before writing a test request.
            time.sleep(0.1)


def capture_details(session: DebugSession, result: dict[str, object]) -> None:
    """Read expensive debugger context only when a case needs investigation."""
    registers: dict[str, int | str] = {"PC": cast(int, result["pc"])}
    for name in ("SP", "LR", "xPSR"):
        try:
            registers[name] = session.registers.read(name)
        except Exception as error:
            registers[name] = str(error)
    result["registers"] = registers
    try:
        result["stack"] = session.callstack.fetch()
    except Exception as error:
        result["stack_error"] = str(error)


def run_case(
    session: DebugSession, request: DebugRequest, case: SelectedCase, result: dict[str, object]
) -> None:
    timings: dict[str, float] = {}
    result["timings_s"] = timings
    started = time.monotonic()
    reset(session, result)
    timings["reset"] = time.monotonic() - started
    started = time.monotonic()
    ready, done = request["ready"] & ~1, request["done"] & ~1
    hardware_breakpoint(session, ready)
    result["phase"] = "run to ready"
    if int(session.registers.read("PC")) & ~1 != ready:
        session.target.run(False)
        if not wait_halted(session, 10000):
            session.target.halt()
            raise RuntimeError("Startup timeout")
    pc = int(session.registers.read("PC")) & ~1
    if pc != ready:
        raise RuntimeError(f"Unexpected startup halt at {pc:#x}")
    # Fresh .data/.bss state must precede every case, including after panic or fault.
    boot = read_words(session, request["diagnostic"], 7)
    initial_request = read_words(session, request["request"], 2)
    if boot != [0x444C5253, 2, 0, 0, 0, 0, 0] or initial_request != [0xFFFFFFFF, 0]:
        raise RuntimeError("Request or diagnostic was not reinitialized by startup")
    if read_words(session, request["result"], 4) != [1, 0xFFFFFFFF, 0, 0]:
        raise RuntimeError("HIL result was not reinitialized by startup")
    timings["ready"] = time.monotonic() - started
    started = time.monotonic()
    result["phase"] = "select case"
    session.breakpoints.removeAll()
    session.memory.write(request["request"], [case["id"], case["token"]], 32)
    hardware_breakpoint(session, done)
    hardware_breakpoint(session, request["failure"] & ~1)
    result["phase"] = "run case"
    session.target.run(False)
    completed = wait_halted(session, case["timeout_ms"])
    if not completed:
        session.target.halt()
    timings["execution"] = time.monotonic() - started
    started = time.monotonic()
    result["timed_out"] = not completed
    result["pc"] = int(session.registers.read("PC"))
    result["result"] = read_words(session, request["result"], 4)
    result["diagnostic"] = read_words(session, request["diagnostic"], 7)
    if case["expected"] in (1, 2) or evaluate(case, result, done) is not None:
        capture_details(session, result)
    timings["capture"] = time.monotonic() - started


def program_image(session: DebugSession, image: str, report: dict[str, object]) -> None:
    user = read_words(session, 0x50000A94, 1)[0]
    icepick = read_words(session, 0x50000B18, 1)[0]
    report["identity"] = {"user_id": f"0x{user:08x}", "icepick_id": f"0x{icepick:08x}"}
    if (
        (icepick >> 12) & 0xFFFF != 0xBB78
        or (user >> 12) & 0xF != 0xF
        or not user & (1 << 23)
        or not user & (1 << 25)
    ):
        raise RuntimeError("Silicon IDs do not match the expected CC1354P10 target")
    # Use the complete ELF, including CCFG; the TI loader owns flash programming.
    session.memory.loadProgram(image)
    session.target.halt()
    session.memory.verifyProgram(image)


def execute(ccs_root: Path, request: DebugRequest) -> int:
    started = time.monotonic()
    timings: dict[str, float] = {}
    results: list[dict[str, object]] = []
    report: dict[str, object] = {"cases": results, "timings_s": timings}
    destination = Path(request["report"])

    def save() -> None:
        # A killed debugger must leave the last completed report readable.
        temporary = destination.with_suffix(".tmp")
        _ = temporary.write_text(json.dumps(report, indent=2) + "\n")
        _ = temporary.replace(destination)

    debugger: DebuggerScripting | None = None
    session: DebugSession | None = None
    status = 0
    try:
        debugger = initScripting(ScriptingOptions(ccsRoot=str(ccs_root), timeout=20000))
        report["version"] = debugger.versionInfo()
        _ = debugger.configure(request["config"])
        # TI's wrapper forwards members dynamically; its generated interface describes them.
        session = cast(DebugSession, cast(object, debugger.openSession("Cortex_M33_0")))
        session.settings.set("AutoRunToLabelOnRestart", False)
        session.settings.set("AutoRunToLabelOnReset", False)
        session.target.connect()
        session.target.halt()
        timings["connect"] = time.monotonic() - started
        phase_started = time.monotonic()
        program_image(session, request["elf"], report)
        timings["identify_program_verify"] = time.monotonic() - phase_started
        save()
        for case in request["cases"]:
            result: dict[str, object] = dict(case)
            results.append(result)
            try:
                run_case(session, request, case, result)
            except Exception as error:
                result["error"] = str(error)
                try:
                    session.target.halt()
                    result["diagnostic"] = read_words(session, request["diagnostic"], 7)
                    result["result"] = read_words(session, request["result"], 4)
                    result["request"] = read_words(session, request["request"], 2)
                    result["pc"] = int(session.registers.read("PC"))
                    capture_details(session, result)
                except Exception as capture_error:
                    result["capture_error"] = str(capture_error)
                status = 1
                save()
                break
            save()
    except Exception as error:
        report["error"] = str(error)
        status = 1
    finally:
        cleanup_started = time.monotonic()
        if session is not None:
            try:
                session.target.halt()
                session.breakpoints.removeAll()
                session.target.disconnect()
            except Exception as error:
                report["cleanup_error"] = str(error)
                status = 1
        if debugger is not None:
            try:
                debugger.shutdown()
            except Exception as error:
                report["stop_error"] = str(error)
                status = 1
        timings["cleanup"] = time.monotonic() - cleanup_started
        timings["total"] = time.monotonic() - started
        save()
    return status


def main() -> int:
    ccs_root = Path(sys.argv[1])
    if sys.argv[2] == "--check-runtime":
        debugger = initScripting(ScriptingOptions(ccsRoot=str(ccs_root), timeout=20000))
        try:
            print(json.dumps(debugger.versionInfo()))
        finally:
            debugger.shutdown()
        return 0
    # The parent runner writes this request from validated ELF metadata.
    request = cast(DebugRequest, json.loads(Path(sys.argv[2]).read_text()))
    return execute(ccs_root, request)


if __name__ == "__main__":
    raise SystemExit(main())

"""Check diagnostic capture without starting the TI runtime or accessing a board."""

import subprocess
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

from scripting.generated_types.Scripting import DebugSession

from tools.debug import ccs_script
from tools.debug.protocol import (
    BOOT_DIAGNOSTIC_MAGIC,
    CFSR_UNDEFINSTR,
    INVALID_CASE_ID,
    NO_TOKEN,
    PROTOCOL_VERSION,
    USAGE_FAULT_EXCEPTION,
    BootStage,
    DebugRequest,
    ExpectedOutcome,
    SelectedCase,
    Status,
)


class DiagnosticCaptureTest(unittest.TestCase):
    def check_capture(
        self,
        *,
        expected: int = ExpectedOutcome.PASS,
        token: int = 123,
        status: int = Status.PASS,
        diagnostic: list[int] | None = None,
        startup: list[list[int]] | None = None,
        completed: bool = True,
        capture: bool,
    ) -> None:
        case = SelectedCase(
            id=7, token=123, expected=expected, name="case", timeout_ms=100, suites=["harness"]
        )
        request = DebugRequest(
            probe="LS4500Q0",
            config="unused",
            elf="unused",
            report="unused",
            cases=[case],
            ready=0x100,
            done=0x200,
            request=0x20000000,
            result=0x20000008,
            diagnostic=0x20000018,
        )
        boot = [BOOT_DIAGNOSTIC_MAGIC, BootStage.APPLICATION, 0, 0, 0, 0, 0]
        terminal_diagnostic = diagnostic if diagnostic is not None else boot
        terminal_result = [PROTOCOL_VERSION, case["id"], token, status]
        if startup is None:
            startup = [
                boot,
                [INVALID_CASE_ID, NO_TOKEN],
                [PROTOCOL_VERSION, INVALID_CASE_ID, NO_TOKEN, Status.IDLE],
            ]
        read_register = MagicMock(side_effect=[request["ready"], request["ready"], request["done"]])
        debugger = MagicMock(registers=MagicMock(read=read_register))
        observation = ccs_script.CaseObservation(case)
        with (
            patch.object(ccs_script, "reset"),
            patch.object(ccs_script, "hardware_breakpoint"),
            patch.object(ccs_script, "wait_halted", return_value=completed),
            patch.object(
                ccs_script,
                "read_words",
                side_effect=[
                    *startup,
                    terminal_result,
                    terminal_diagnostic,
                ],
            ),
            patch.object(ccs_script, "capture_details") as details,
        ):
            ccs_script.run_case(
                cast(DebugSession, debugger), request, case, observation, Path("xds110reset")
            )
            if capture:
                details.assert_called_once_with(debugger, observation)
            else:
                details.assert_not_called()
        # The cheap path must still provide every record used to accept or reject a case.
        self.assertEqual(observation.result, terminal_result)
        self.assertEqual(observation.diagnostic, terminal_diagnostic)
        self.assertEqual(observation.pc, request["done"])
        self.assertEqual(observation.timed_out, not completed)

    def test_capture_preserves_registers_when_other_reads_fail(self) -> None:
        read_register = MagicMock(side_effect=[0x20001000, RuntimeError("unavailable"), 0x1000000])
        debugger = MagicMock(
            registers=MagicMock(read=read_register),
            callstack=MagicMock(fetch=MagicMock(side_effect=RuntimeError("cannot unwind"))),
        )
        observation = ccs_script.CaseObservation(
            case=SelectedCase(
                id=0,
                token=1,
                expected=ExpectedOutcome.PASS,
                name="case",
                timeout_ms=100,
                suites=["harness"],
            ),
            pc=0x200,
        )
        ccs_script.capture_details(cast(DebugSession, debugger), observation)
        self.assertEqual(observation.registers, {"PC": 0x200, "SP": 0x20001000, "xPSR": 0x1000000})
        self.assertEqual(observation.register_errors, {"LR": "unavailable"})
        self.assertEqual(observation.stack_error, "cannot unwind")

    def test_success_skips_expensive_context(self) -> None:
        self.check_capture(capture=False)

    def test_startup_rejects_stale_records(self) -> None:
        for index, stale in (
            (0, [BOOT_DIAGNOSTIC_MAGIC, BootStage.PANIC, 1, 1, 0, 0, 0]),
            (1, [INVALID_CASE_ID, 123]),
            (2, [PROTOCOL_VERSION, INVALID_CASE_ID, NO_TOKEN, Status.PASS]),
        ):
            startup = [
                [BOOT_DIAGNOSTIC_MAGIC, BootStage.APPLICATION, 0, 0, 0, 0, 0],
                [INVALID_CASE_ID, NO_TOKEN],
                [PROTOCOL_VERSION, INVALID_CASE_ID, NO_TOKEN, Status.IDLE],
            ]
            startup[index] = stale
            with self.subTest(index=index), self.assertRaisesRegex(RuntimeError, "reinitialized"):
                self.check_capture(startup=startup, capture=False)

    def test_stale_token_keeps_expensive_context(self) -> None:
        self.check_capture(token=122, capture=True)

    def test_timeout_context_depends_on_expected_outcome(self) -> None:
        self.check_capture(status=Status.RUNNING, completed=False, capture=True)
        self.check_capture(
            expected=ExpectedOutcome.TIMEOUT, status=Status.RUNNING, completed=False, capture=False
        )

    def test_expected_panic_and_fault_keep_expensive_context(self) -> None:
        for expected, diagnostic in (
            (ExpectedOutcome.PANIC, [BOOT_DIAGNOSTIC_MAGIC, BootStage.PANIC, 0, 0, 0, 0, 0]),
            (
                ExpectedOutcome.FAULT,
                [
                    BOOT_DIAGNOSTIC_MAGIC,
                    BootStage.FAULT,
                    USAGE_FAULT_EXCEPTION,
                    CFSR_UNDEFINSTR,
                    0,
                    0,
                    0,
                ],
            ),
        ):
            with self.subTest(expected=expected):
                self.check_capture(
                    expected=expected,
                    status=Status.RUNNING,
                    diagnostic=diagnostic,
                    completed=False,
                    capture=True,
                )


class ResetTest(unittest.TestCase):
    def observation(self) -> ccs_script.CaseObservation:
        return ccs_script.CaseObservation(
            SelectedCase(
                id=0, token=1, expected=ExpectedOutcome.PASS, name="case", timeout_ms=100, suites=[]
            )
        )

    def test_pin_reset_selects_the_requested_probe(self) -> None:
        connect = MagicMock()
        board_reset = MagicMock()
        debugger = MagicMock(target=MagicMock(connect=connect, reset=board_reset))
        with patch("tools.debug.ccs_script.subprocess.run") as pulse:
            ccs_script.reset(
                cast(DebugSession, debugger),
                self.observation(),
                Path("/tools/xds110reset"),
                "probe1",
            )
        pulse.assert_called_once_with(
            ["/tools/xds110reset", "--serial", "probe1", "--delay", "50"], check=True, timeout=5
        )
        connect.assert_called_once_with()
        board_reset.assert_not_called()

    def test_failed_pin_reset_is_bounded_and_prevents_reconnect(self) -> None:
        # A missing utility, nonzero exit, or hung process must not permit test execution.
        for error in (
            FileNotFoundError("missing reset tool"),
            subprocess.CalledProcessError(1, "xds110reset"),
            subprocess.TimeoutExpired("xds110reset", 5),
        ):
            with self.subTest(error=error):
                connect = MagicMock()
                debugger = MagicMock(target=MagicMock(connect=connect))
                observation = self.observation()
                with (
                    patch("tools.debug.ccs_script.subprocess.run", side_effect=error) as pulse,
                    patch("tools.debug.ccs_script.time.sleep"),
                    self.assertRaises(type(error)),
                ):
                    ccs_script.reset(
                        cast(DebugSession, debugger), observation, Path("xds110reset"), "probe1"
                    )
                self.assertEqual(pulse.call_count, 2)
                self.assertEqual(observation.reset_errors, [str(error), str(error)])
                connect.assert_not_called()


class ProgrammingTest(unittest.TestCase):
    def test_wrong_silicon_is_rejected_before_programming(self) -> None:
        load_program = MagicMock()
        debugger = MagicMock(memory=MagicMock(loadProgram=load_program))
        with patch.object(ccs_script, "read_words", side_effect=[[0], [0]]):
            with self.assertRaisesRegex(RuntimeError, "Silicon IDs"):
                ccs_script.program_image(
                    cast(DebugSession, debugger),
                    "suite.elf",
                    ccs_script.WorkerReport(),
                )
        load_program.assert_not_called()

    def test_verification_failure_propagates(self) -> None:
        load_program = MagicMock()
        verify_program = MagicMock(side_effect=RuntimeError("verify failed"))
        debugger = MagicMock(
            memory=MagicMock(loadProgram=load_program, verifyProgram=verify_program)
        )
        with patch.object(ccs_script, "read_words", side_effect=[[0x1287F000], [0x1BB7802F]]):
            with self.assertRaisesRegex(RuntimeError, "verify failed"):
                ccs_script.program_image(
                    cast(DebugSession, debugger),
                    "suite.elf",
                    ccs_script.WorkerReport(),
                )
        load_program.assert_called_once_with("suite.elf")
        verify_program.assert_called_once_with("suite.elf")


class CleanupTest(unittest.TestCase):
    def test_failed_actions_do_not_skip_remaining_cleanup(self) -> None:
        for failures in (("halt",), ("removeAll",), ("halt", "removeAll", "disconnect")):
            with self.subTest(failures=failures):
                halt = MagicMock(
                    side_effect=RuntimeError("halt failed") if "halt" in failures else None
                )
                remove = MagicMock(
                    side_effect=RuntimeError("remove failed") if "removeAll" in failures else None
                )
                disconnect = MagicMock(
                    side_effect=RuntimeError("disconnect failed")
                    if "disconnect" in failures
                    else None
                )
                debugger = MagicMock(
                    target=MagicMock(halt=halt, disconnect=disconnect),
                    breakpoints=MagicMock(removeAll=remove),
                )
                errors = ccs_script.cleanup_session(cast(DebugSession, debugger))
                halt.assert_called_once_with()
                remove.assert_called_once_with()
                disconnect.assert_called_once_with()
                expected = {
                    "halt": "halt: halt failed",
                    "removeAll": "remove breakpoints: remove failed",
                    "disconnect": "disconnect: disconnect failed",
                }
                self.assertEqual(errors, [expected[name] for name in failures])


if __name__ == "__main__":
    unittest.main()

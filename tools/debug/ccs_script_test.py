"""Check diagnostic capture without starting the TI runtime or accessing a board."""

import unittest
from typing import cast
from unittest.mock import MagicMock, patch

from scripting.generated_types.Scripting import DebugSession

from tools.debug import ccs_script
from tools.debug.protocol import DebugRequest, SelectedCase


class DiagnosticCaptureTest(unittest.TestCase):
    def check_capture(
        self,
        *,
        expected: int = 0,
        token: int = 123,
        status: int = 2,
        diagnostic: list[int] | None = None,
        completed: bool = True,
        capture: bool,
    ) -> None:
        case = SelectedCase(id=7, token=123, expected=expected, name="case", timeout_ms=100)
        request = DebugRequest(
            config="unused",
            elf="unused",
            report="unused",
            cases=[case],
            ready=0x100,
            done=0x200,
            failure=0x300,
            request=0x20000000,
            result=0x20000008,
            diagnostic=0x20000018,
        )
        boot = [0x444C5253, 2, 0, 0, 0, 0, 0]
        terminal_diagnostic = diagnostic if diagnostic is not None else boot
        terminal_result = [1, case["id"], token, status]
        read_register = MagicMock(side_effect=[request["ready"], request["ready"], request["done"]])
        debugger = MagicMock(registers=MagicMock(read=read_register))
        observation: dict[str, object] = {}
        with (
            patch.object(ccs_script, "reset"),
            patch.object(ccs_script, "hardware_breakpoint"),
            patch.object(ccs_script, "wait_halted", return_value=completed),
            patch.object(
                ccs_script,
                "read_words",
                side_effect=[
                    boot,
                    [0xFFFFFFFF, 0],
                    [1, 0xFFFFFFFF, 0, 0],
                    terminal_result,
                    terminal_diagnostic,
                ],
            ),
            patch.object(ccs_script, "capture_details") as details,
        ):
            ccs_script.run_case(cast(DebugSession, debugger), request, case, observation)
            if capture:
                details.assert_called_once_with(debugger, observation)
            else:
                details.assert_not_called()
        # The cheap path must still provide every record used to accept or reject a case.
        self.assertEqual(observation["result"], terminal_result)
        self.assertEqual(observation["diagnostic"], terminal_diagnostic)
        self.assertEqual(observation["pc"], request["done"])
        self.assertEqual(observation["timed_out"], not completed)

    def test_success_skips_expensive_context(self) -> None:
        self.check_capture(capture=False)

    def test_stale_token_keeps_expensive_context(self) -> None:
        self.check_capture(token=122, capture=True)

    def test_timeout_context_depends_on_expected_outcome(self) -> None:
        self.check_capture(status=1, completed=False, capture=True)
        self.check_capture(expected=3, status=1, completed=False, capture=False)

    def test_expected_panic_and_fault_keep_expensive_context(self) -> None:
        for expected, diagnostic in (
            (1, [0x444C5253, 0xFFFF0002, 0, 0, 0, 0, 0]),
            (2, [0x444C5253, 0xFFFF0001, 6, 1 << 16, 0, 0, 0]),
        ):
            with self.subTest(expected=expected):
                self.check_capture(
                    expected=expected,
                    status=1,
                    diagnostic=diagnostic,
                    completed=False,
                    capture=True,
                )


class ProgrammingTest(unittest.TestCase):
    def test_wrong_silicon_is_rejected_before_programming(self) -> None:
        load_program = MagicMock()
        debugger = MagicMock(memory=MagicMock(loadProgram=load_program))
        with patch.object(ccs_script, "read_words", side_effect=[[0], [0]]):
            with self.assertRaisesRegex(RuntimeError, "Silicon IDs"):
                ccs_script.program_image(cast(DebugSession, debugger), "suite.elf", {})
        load_program.assert_not_called()

    def test_verification_failure_propagates(self) -> None:
        load_program = MagicMock()
        verify_program = MagicMock(side_effect=RuntimeError("verify failed"))
        debugger = MagicMock(
            memory=MagicMock(loadProgram=load_program, verifyProgram=verify_program)
        )
        with patch.object(ccs_script, "read_words", side_effect=[[0x1287F000], [0x1BB7802F]]):
            with self.assertRaisesRegex(RuntimeError, "verify failed"):
                ccs_script.program_image(cast(DebugSession, debugger), "suite.elf", {})
        load_program.assert_called_once_with("suite.elf")
        verify_program.assert_called_once_with("suite.elf")


if __name__ == "__main__":
    _ = unittest.main()

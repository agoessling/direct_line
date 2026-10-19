"""Host protocol tests: a terminal state alone must never count as success."""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TypedDict, cast
from unittest.mock import patch

from python.runfiles import runfiles

from tools.debug import process
from tools.debug.elf import Elf
from tools.debug.hil import execute, probe_lock, read_report, select_cases
from tools.debug.protocol import (
    BOOT_DIAGNOSTIC_MAGIC,
    CFSR_UNDEFINSTR,
    INVALID_CASE_ID,
    NO_TOKEN,
    PROTOCOL_VERSION,
    USAGE_FAULT_EXCEPTION,
    BoardResult,
    BootDiagnostic,
    BootStage,
    Case,
    ExpectedOutcome,
    FaultDetails,
    PanicDetails,
    Result,
    RunConfig,
    RunResult,
    SelectedCase,
    Status,
    evaluate,
)


class ProtocolTest(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.case: SelectedCase = SelectedCase(
            id=7,
            token=123,
            expected=ExpectedOutcome.PASS,
            name="case",
            timeout_ms=100,
            suites=["harness"],
        )
        self.observation: dict[str, object] = dict(
            result=[PROTOCOL_VERSION, 7, 123, Status.PASS],
            diagnostic=[BOOT_DIAGNOSTIC_MAGIC, BootStage.APPLICATION, 0, 0, 0, 0, 0],
            pc=0x101,
            timed_out=False,
        )

    def test_pass(self) -> None:
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))

    def test_invalid_records_cannot_pass(self) -> None:
        for field, values in (
            ("result", [None, [], [1, 7, 123], [1, 7, 123, 99], [True, 7, 123, 2]]),
            ("diagnostic", [None, [], [0, 2, 0, 0, 0, 0, 0], [0x444C5253, 99, 0, 0, 0, 0, 0]]),
            ("timed_out", [None, 0, "false"]),
        ):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertIsNotNone(
                        evaluate(self.case, dict(self.observation, **{field: value}), 0x100)
                    )

    def test_zero_token_and_unknown_expectation_fail(self) -> None:
        self.case["expected"] = 99
        self.observation.update(result=[PROTOCOL_VERSION, 7, 123, Status.RUNNING], timed_out=True)
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))
        self.case["expected"] = ExpectedOutcome.TIMEOUT
        self.case["token"] = NO_TOKEN
        self.observation["result"] = [PROTOCOL_VERSION, 7, NO_TOKEN, Status.RUNNING]
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_integral_json_double_pc(self) -> None:
        self.observation["pc"] = 257.0
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))
        self.observation["pc"] = 257.5
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_stale_result_and_unexpected_halt(self) -> None:
        for key, value in [
            ("result", [PROTOCOL_VERSION, 7, 122, Status.PASS]),
            ("result", [PROTOCOL_VERSION, 8, 123, Status.PASS]),
            ("result", [PROTOCOL_VERSION + 1, 7, 123, Status.PASS]),
            ("pc", 0x200),
            ("timed_out", True),
            ("error", "disconnected"),
        ]:
            with self.subTest(key=key, value=value):
                self.assertIsNotNone(
                    evaluate(self.case, dict(self.observation, **{key: value}), 0x100)
                )

    def test_expected_panic_requires_fresh_running_case(self) -> None:
        self.case["expected"] = ExpectedOutcome.PANIC
        self.observation.update(
            result=[PROTOCOL_VERSION, 7, 123, Status.RUNNING],
            diagnostic=[BOOT_DIAGNOSTIC_MAGIC, BootStage.PANIC, 1, 1, 0, 0, 0],
        )
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))
        self.observation["result"] = [PROTOCOL_VERSION, 7, 123, Status.IDLE]
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_expected_udf_checks_exception_and_cause(self) -> None:
        self.case["expected"] = ExpectedOutcome.FAULT
        self.observation.update(
            result=[PROTOCOL_VERSION, 7, 123, Status.RUNNING],
            diagnostic=[
                BOOT_DIAGNOSTIC_MAGIC,
                BootStage.FAULT,
                USAGE_FAULT_EXCEPTION,
                CFSR_UNDEFINSTR,
                0,
                0,
                0,
            ],
        )
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))
        self.observation["diagnostic"] = [
            BOOT_DIAGNOSTIC_MAGIC,
            BootStage.FAULT,
            3,
            CFSR_UNDEFINSTR,
            0,
            0,
            0,
        ]
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_timeout_does_not_accept_fault_or_debugger_error(self) -> None:
        self.case["expected"] = ExpectedOutcome.TIMEOUT
        self.observation.update(result=[PROTOCOL_VERSION, 7, 123, Status.RUNNING], timed_out=True)
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))
        self.assertIsNotNone(evaluate(self.case, dict(self.observation, error="USB gone"), 0x100))
        self.observation["diagnostic"] = [
            BOOT_DIAGNOSTIC_MAGIC,
            BootStage.FAULT,
            USAGE_FAULT_EXCEPTION,
            CFSR_UNDEFINSTR,
            0,
            0,
            0,
        ]
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_probe_exclusion(self) -> None:
        with probe_lock("unit-test"):
            with self.assertRaisesRegex(RuntimeError, "in use"):
                with probe_lock("unit-test"):
                    self.fail("Second lock acquired")
        with probe_lock("unit-test"):
            pass


class RecordTest(unittest.TestCase):
    def test_result_layout_and_json_enum_encoding(self) -> None:
        # Literal wire samples independently pin the ABI's numeric encodings.
        self.assertEqual(
            Result.from_words([1, 7, 123, 2]), Result(PROTOCOL_VERSION, 7, 123, Status.PASS)
        )
        self.assertEqual(
            Result.from_words([1.0, 4294967295.0, 0.0, 0.0]),
            Result(PROTOCOL_VERSION, INVALID_CASE_ID, NO_TOKEN, Status.IDLE),
        )
        self.assertEqual(
            json.dumps([ExpectedOutcome.PANIC, Status.RUNNING, BootStage.PANIC]),
            "[1, 1, 4294901762]",
        )

    def test_fault_and_panic_payloads_have_distinct_fields(self) -> None:
        fault = BootDiagnostic.from_words([0x444C5253, 0xFFFF0001, 6, 65536, 0, 0x100, 0x200])
        self.assertEqual(
            fault,
            BootDiagnostic(
                BootStage.FAULT,
                FaultDetails(USAGE_FAULT_EXCEPTION, CFSR_UNDEFINSTR, 0, 0x100, 0x200),
            ),
        )
        panic = BootDiagnostic.from_words([0x444C5253, 0xFFFF0002, 42, 3, 0x300, 12, 0])
        self.assertEqual(panic, BootDiagnostic(BootStage.PANIC, PanicDetails(42, 3, 0x300, 12, 0)))
        self.assertEqual(
            BootDiagnostic.from_words([0x444C5253, 2, 0, 0, 0, 0, 0]),
            BootDiagnostic(BootStage.APPLICATION, None),
        )

    def test_bad_words_and_record_lengths_rejected(self) -> None:
        for value in (-1, 1 << 32, True, 1.5, float("nan"), float("inf"), "1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Result.from_words([PROTOCOL_VERSION, value, 123, Status.PASS])
        invalid_records: tuple[object, ...] = (
            None,
            {},
            [],
            [1, 7, 123],
            [1, 7, 123, 2, 0],
            [2, 7, 123, 2],
            [1, 7, 123, 99],
        )
        for value in invalid_records:
            with self.subTest(value=value), self.assertRaises(ValueError):
                Result.from_words(value)

    def test_invalid_boot_records_rejected(self) -> None:
        for value in (
            [],
            [0, 2, 0, 0, 0, 0, 0],
            [0x444C5253, 99, 0, 0, 0, 0, 0],
            [0x444C5253, 2, 6, 65536, 0, 0, 0],
            [0x444C5253, 2, 0, 0, 0, 0, 0, 0],
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                BootDiagnostic.from_words(value)


def image(records: list[tuple[int, int, int, bytes]], suites: bytes = b"harness") -> bytes:
    """Small ELF32 fixture containing the two discovery symbols."""
    payload = struct.pack("<I", len(records)) + b"".join(
        struct.pack("<III52s64s", *record, suites) for record in records
    )
    names = b"\0HIL_TEST_COUNT\0HIL_TESTS\0"
    symbols = struct.pack("<IIIBBH", 1, 0x1000, 4, 0x11, 0, 1)
    symbols += struct.pack("<IIIBBH", 16, 0x1004, len(payload) - 4, 0x11, 0, 1)
    content = payload + names + symbols
    header = struct.pack(
        "<16sHHIIIIIHHHHHH",
        b"\x7fELF\x01\x01\x01",
        2,
        40,
        1,
        0,
        0,
        52 + len(content),
        0,
        52,
        0,
        0,
        40,
        4,
        0,
    )
    sections = b"\0" * 40
    sections += struct.pack("<10I", 0, 1, 2, 0x1000, 52, len(payload), 0, 0, 4, 0)
    sections += struct.pack("<10I", 0, 3, 0, 0, 52 + len(payload), len(names), 0, 0, 1, 0)
    sections += struct.pack("<10I", 0, 2, 0, 0, 52 + len(payload) + len(names), 32, 2, 0, 4, 16)
    return header + content + sections


class DiscoveryTest(unittest.TestCase):
    def test_linked_registry(self) -> None:
        resolver = runfiles.Create()
        assert resolver is not None
        path = resolver.Rlocation(os.environ["DIRECT_LINE_TEST_ELF"])
        assert path is not None
        cases = Elf(Path(path).read_bytes()).cases()
        self.assertEqual([case["id"] for case in cases], list(range(len(cases))))
        by_name = {case["name"]: case for case in cases}
        self.assertEqual(by_name["gpio/outputs"]["suites"], ["drivers", "smoke"])
        self.assertEqual(by_name["gpio/outputs"]["expected"], 0)
        self.assertEqual(by_name["harness/panic"]["expected"], 1)
        self.assertEqual(by_name["harness/fault"]["expected"], 2)
        self.assertEqual(by_name["harness/timeout"]["expected"], 3)

    def test_names_and_deadlines_come_from_image(self) -> None:
        elf = Elf(image([(0, 500, 2, b"harness/fault")]))
        self.assertEqual(
            elf.cases(),
            [
                dict(
                    id=0,
                    timeout_ms=500,
                    expected=ExpectedOutcome.FAULT,
                    name="harness/fault",
                    suites=["harness"],
                )
            ],
        )
        self.assertEqual(elf.address("HIL_TEST_COUNT", 4), 0x1000)

    def test_duplicate_ids_and_names_rejected(self) -> None:
        for second in [(7, 100, 0, b"other"), (8, 100, 0, b"first")]:
            with self.subTest(second=second):
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    Elf(image([(7, 100, 0, b"first"), second])).cases()

    def test_invalid_metadata_rejected(self) -> None:
        for record in [
            (0, 0, 0, b"case"),
            (0, 60001, 0, b"case"),
            (0, 100, 4, b"case"),
            (0, 100, 0, b""),
        ]:
            with self.subTest(record=record):
                with self.assertRaisesRegex(ValueError, "metadata"):
                    Elf(image([record])).cases()

    def test_truncated_image_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Elf(image([(0, 100, 0, b"case")])[:-1])

    def test_nonpositional_identifier_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "indices"):
            Elf(image([(7, 100, 0, b"case")])).cases()

    def test_invalid_suites_rejected(self) -> None:
        for suites in (b"", b"smoke smoke", b"smoke,bad", b"1bad"):
            with self.subTest(suites=suites), self.assertRaisesRegex(ValueError, "suite metadata"):
                Elf(image([(0, 100, 0, b"case")], suites)).cases()


class SelectionTest(unittest.TestCase):
    cases: list[Case] = [
        Case(
            id=0,
            name="harness/pass",
            timeout_ms=1000,
            expected=ExpectedOutcome.PASS,
            suites=["harness", "smoke"],
        ),
        Case(
            id=1,
            name="gpio/outputs",
            timeout_ms=3000,
            expected=ExpectedOutcome.PASS,
            suites=["drivers", "smoke"],
        ),
        Case(
            id=2,
            name="timer/periodic",
            timeout_ms=3000,
            expected=ExpectedOutcome.PASS,
            suites=["drivers"],
        ),
    ]

    def test_default_runs_every_case(self) -> None:
        self.assertEqual(select_cases(self.cases, [], "*"), self.cases)

    def test_overlapping_suites_keep_order_and_run_each_case_once(self) -> None:
        self.assertEqual(select_cases(self.cases, ["drivers", "smoke", "smoke"], "*"), self.cases)

    def test_suite_selection_preserves_image_ids(self) -> None:
        self.assertEqual(select_cases(self.cases, ["drivers"], "*"), self.cases[1:])

    def test_filter_intersects_suites(self) -> None:
        self.assertEqual(select_cases(self.cases, ["smoke"], "gpio/*"), [self.cases[1]])
        self.assertEqual(select_cases(self.cases, [], "timer/*"), [self.cases[2]])

    def test_unknown_suite_and_empty_selection_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown suites: typo"):
            select_cases(self.cases, ["smoke", "typo"], "*")
        with self.assertRaisesRegex(ValueError, "matched no cases"):
            select_cases(self.cases, ["smoke"], "timer/*")


class DebuggerRequest(TypedDict):
    cases: list[SelectedCase]
    report: str


class ReportTest(unittest.TestCase):
    def test_board_success_requires_a_successful_run_without_board_errors(self) -> None:
        result = BoardResult(probe="probe", elf_sha256="hash", tools={})
        self.assertFalse(result.passed)
        result.run = RunResult(
            duration_s=1.0,
            identity={},
            cases=[],
            process_exit_code=0,
            debugger_error=None,
            passed=True,
        )
        self.assertTrue(result.passed)
        result.error = "cleanup failed"
        self.assertFalse(result.passed)
        result.error = None
        result.run.passed = False
        self.assertFalse(result.passed)

    def test_unavailable_identity_preserves_worker_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            path.write_text(
                json.dumps(
                    {
                        "cases": [],
                        "identity": None,
                        "error": "connection failed",
                        "cleanup_error": None,
                        "stop_error": None,
                    }
                )
            )
            self.assertEqual(read_report(path), ([], "connection failed", {}))

    def test_malformed_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            for identity in (False, list[int](), "", {"user_id": 123}):
                with self.subTest(identity=identity):
                    path.write_text(json.dumps({"cases": [], "identity": identity}))
                    with self.assertRaisesRegex(ValueError, "identity"):
                        read_report(path)

    def test_process_timeout_preserves_completed_cases(self) -> None:
        def timed_out(
            _args: RunConfig, request_path: Path, _directory: Path, _timeout: float
        ) -> None:
            request = cast(DebuggerRequest, json.loads(request_path.read_text()))
            first = request["cases"][0]
            observation = dict(
                result=[PROTOCOL_VERSION, first["id"], first["token"], Status.PASS],
                diagnostic=[BOOT_DIAGNOSTIC_MAGIC, BootStage.APPLICATION, 0, 0, 0, 0, 0],
                pc=0x100,
                timed_out=False,
            )
            Path(request["report"]).write_text(json.dumps(dict(cases=[observation])))
            raise RuntimeError("Debugger process deadline exceeded")

        cases: list[Case] = [
            Case(
                id=index,
                name=str(index),
                expected=ExpectedOutcome.PASS,
                timeout_ms=100,
                suites=["harness"],
            )
            for index in range(2)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            args = RunConfig("probe", directory / "suite.elf", Path("dslite"), Path("ccs_script"))
            elf = Elf(image([(0, 100, 0, b"case")]))
            with (
                patch("tools.debug.hil.config_for_probe"),
                patch("tools.debug.hil.run_debugger", side_effect=timed_out),
                patch.object(elf, "address", return_value=0x100),
            ):
                report = execute(args, elf, cases, directory)
        self.assertFalse(report.passed)
        self.assertTrue(report.cases[0].passed)
        self.assertFalse(report.cases[1].passed)
        assert report.debugger_error is not None
        self.assertIn("deadline", report.debugger_error)


class ProcessTest(unittest.TestCase):
    def test_detached_helpers_are_reaped_after_exit_and_timeout(self) -> None:
        script = """
import subprocess
import sys
import time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
Path(sys.argv[1]).write_text(str(child.pid))
if sys.argv[2] == "timeout":
    time.sleep(60)
"""
        for mode in ("exit", "timeout"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                pid_file = directory / "pid"
                command = [sys.executable, "-c", script, str(pid_file), mode]
                if mode == "timeout":
                    with self.assertRaises(subprocess.TimeoutExpired):
                        process.run(command, directory / "log", 1)
                else:
                    self.assertEqual(process.run(command, directory / "log", 5), 0)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), 0)


if __name__ == "__main__":
    unittest.main()

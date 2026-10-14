"""Host protocol tests: a terminal state alone must never count as success."""

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TypedDict, cast
from unittest.mock import patch

from tools.debug import process
from tools.debug.elf import Elf
from tools.debug.hil import execute, junit, probe_lock
from tools.debug.protocol import BoardResult, Case, CaseResult, RunConfig, SelectedCase, evaluate


class ProtocolTest(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.case: SelectedCase = SelectedCase(
            id=7, token=123, expected=0, name="case", timeout_ms=100
        )
        self.observation: dict[str, object] = dict(
            result=[1, 7, 123, 2],
            diagnostic=[0x444C5253, 2, 0, 0, 0, 0, 0],
            pc=0x101,
            timed_out=False,
        )

    def test_pass(self) -> None:
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))

    def test_integral_json_double_pc(self) -> None:
        self.observation["pc"] = 257.0
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))
        self.observation["pc"] = 257.5
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_stale_result_and_unexpected_halt(self) -> None:
        for key, value in [
            ("result", [1, 7, 122, 2]),
            ("result", [1, 8, 123, 2]),
            ("result", [2, 7, 123, 2]),
            ("pc", 0x200),
            ("timed_out", True),
            ("error", "disconnected"),
        ]:
            with self.subTest(key=key, value=value):
                self.assertIsNotNone(
                    evaluate(self.case, dict(self.observation, **{key: value}), 0x100)
                )

    def test_expected_panic_requires_fresh_running_case(self) -> None:
        self.case["expected"] = 1
        self.observation.update(
            result=[1, 7, 123, 1], diagnostic=[0x444C5253, 0xFFFF0002, 1, 1, 0, 0, 0]
        )
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))
        self.observation["result"] = [1, 7, 123, 0]
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_expected_udf_checks_exception_and_cause(self) -> None:
        self.case["expected"] = 2
        self.observation.update(
            result=[1, 7, 123, 1], diagnostic=[0x444C5253, 0xFFFF0001, 6, 1 << 16, 0, 0, 0]
        )
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))
        self.observation["diagnostic"] = [0x444C5253, 0xFFFF0001, 3, 1 << 16, 0, 0, 0]
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_timeout_does_not_accept_fault_or_debugger_error(self) -> None:
        self.case["expected"] = 3
        self.observation.update(result=[1, 7, 123, 1], timed_out=True)
        self.assertIsNone(evaluate(self.case, self.observation, 0x100))
        self.assertIsNotNone(evaluate(self.case, dict(self.observation, error="USB gone"), 0x100))
        self.observation["diagnostic"] = [0x444C5253, 0xFFFF0001, 6, 1 << 16, 0, 0, 0]
        self.assertIsNotNone(evaluate(self.case, self.observation, 0x100))

    def test_probe_exclusion(self) -> None:
        with probe_lock("unit-test"):
            with self.assertRaisesRegex(RuntimeError, "in use"):
                with probe_lock("unit-test"):
                    self.fail("Second lock acquired")
        with probe_lock("unit-test"):
            pass


def image(records: list[tuple[int, int, int, bytes]]) -> bytes:
    """Small ELF32 fixture containing the two discovery symbols."""
    payload = struct.pack("<I", len(records)) + b"".join(
        struct.pack("<III52s", *record) for record in records
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
    def test_names_and_deadlines_come_from_image(self) -> None:
        elf = Elf(image([(7, 500, 2, b"harness/fault")]))
        self.assertEqual(
            elf.cases(), [dict(id=7, timeout_ms=500, expected=2, name="harness/fault")]
        )
        self.assertEqual(elf.address("HIL_TEST_COUNT", 4), 0x1000)

    def test_duplicate_ids_and_names_rejected(self) -> None:
        for second in [(7, 100, 0, b"other"), (8, 100, 0, b"first")]:
            with self.subTest(second=second):
                with self.assertRaisesRegex(ValueError, "Duplicate"):
                    _ = Elf(image([(7, 100, 0, b"first"), second])).cases()

    def test_invalid_metadata_rejected(self) -> None:
        for record in [
            (0, 0, 0, b"case"),
            (0, 60001, 0, b"case"),
            (0, 100, 4, b"case"),
            (0, 100, 0, b""),
        ]:
            with self.subTest(record=record):
                with self.assertRaisesRegex(ValueError, "metadata"):
                    _ = Elf(image([record])).cases()

    def test_truncated_image_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _ = Elf(image([(0, 100, 0, b"case")])[:-1])


class DebuggerRequest(TypedDict):
    cases: list[SelectedCase]
    report: str


class ReportTest(unittest.TestCase):
    def test_process_timeout_preserves_completed_cases(self) -> None:
        def timed_out(
            _args: RunConfig, request_path: Path, _directory: Path, _timeout: float
        ) -> None:
            request = cast(DebuggerRequest, json.loads(request_path.read_text()))
            first = request["cases"][0]
            observation = dict(
                result=[1, first["id"], first["token"], 2],
                diagnostic=[0x444C5253, 2, 0, 0, 0, 0, 0],
                pc=0x100,
                timed_out=False,
            )
            _ = Path(request["report"]).write_text(json.dumps(dict(cases=[observation])))
            raise RuntimeError("Debugger process deadline exceeded")

        cases: list[Case] = [
            Case(id=index, name=str(index), expected=0, timeout_ms=100) for index in range(2)
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
        self.assertFalse(report["passed"])
        self.assertTrue(report["cases"][0]["passed"])
        self.assertFalse(report["cases"][1]["passed"])
        assert report["debugger_error"] is not None
        self.assertIn("deadline", report["debugger_error"])

    def test_process_failure_after_passing_cases_is_visible_in_junit(self) -> None:
        case: CaseResult = CaseResult(
            id=0,
            token=1,
            name="case",
            timeout_ms=100,
            expected=0,
            passed=True,
            error=None,
            observation={},
        )
        report: BoardResult = BoardResult(
            probe="probe",
            elf_sha256="",
            tools={},
            passed=False,
            debugger_error="disconnect failed",
            cases=[case],
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "junit.xml"
            junit([report], destination)
            root = ET.parse(destination).getroot()
        self.assertEqual(root.get("tests"), "2")
        self.assertEqual(root.get("errors"), "1")
        node = root.find("testcase/error")
        assert node is not None
        self.assertEqual(node.get("message"), "disconnect failed")


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
                        _ = process.run(command, directory / "log", 1)
                else:
                    self.assertEqual(process.run(command, directory / "log", 5), 0)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid_file.read_text()), 0)


if __name__ == "__main__":
    _ = unittest.main()

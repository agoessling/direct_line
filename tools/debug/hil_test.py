"""Check explicit probe selection, exclusive access, and trustworthy result reporting."""

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from tools.debug.hil import Arguments, Report, SuiteResult, command_line, execute, suite_result
from tools.debug.probe_lock import probe_lock


def summary(passed: int, failed: int = 0, ignored: int = 0) -> str:
    return "\n".join(
        json.dumps(event)
        for event in (
            {"type": "suite", "event": "started", "test_count": passed + failed + ignored},
            {
                "type": "suite",
                "event": "failed" if failed else "ok",
                "passed": passed,
                "failed": failed,
                "ignored": ignored,
            },
        )
    )


class RunnerTest(unittest.TestCase):
    def test_filters_cannot_override_probe(self) -> None:
        args = Arguments(probe="LS4500Q0", filter=["--probe"], list=True)
        command = command_line("probe-rs", "firmware.elf", "cc1354p10.yaml", args)
        options, positional = command[: command.index("--")], command[command.index("--") + 1 :]
        self.assertEqual(options[options.index("--probe") + 1], "0451:bef3-5:LS4500Q0")
        self.assertEqual(options[options.index("--chip-description-path") + 1], "cc1354p10.yaml")
        self.assertIn("--verify", options)
        self.assertIn("--preverify", options)
        self.assertIn("--list", options)
        self.assertEqual(positional, ["firmware.elf", "--probe"])

    def test_force_flash_retains_post_program_verification(self) -> None:
        command = command_line(
            "probe-rs", "firmware.elf", "cc1354p10.yaml", Arguments(force_flash=True)
        )
        self.assertNotIn("--preverify", command)
        self.assertIn("--verify", command)

    def test_multiple_filters_rejected(self) -> None:
        with self.assertRaises(ValueError):
            command_line(
                "probe-rs", "firmware.elf", "cc1354p10.yaml", Arguments(filter=["clock", "uart"])
            )

    def test_suite_summary_ignores_diagnostics(self) -> None:
        self.assertEqual(
            suite_result("attached\n" + summary(14, ignored=4) + "\ndisconnected\n"),
            SuiteResult(14, 0, 4),
        )

    def test_empty_suite_is_distinguished_from_missing_summary(self) -> None:
        self.assertEqual(suite_result(summary(0)), SuiteResult(0, 0, 0))
        self.assertIsNone(suite_result('{"type":"suite","event":"started","test_count":14}'))

    def test_malformed_or_inconsistent_summary_rejected(self) -> None:
        for field, value in (
            ("passed", True),
            ("passed", -1),
            ("passed", "14"),
            ("passed", 13),
            ("event", "failed"),
        ):
            with self.subTest(field=field, value=value):
                transcript = summary(14).replace(
                    f'"{field}": {json.dumps(14 if field == "passed" else "ok")}',
                    f'"{field}": {json.dumps(value)}',
                )
                self.assertIsNone(suite_result(transcript))

    def test_incomplete_later_suite_cannot_reuse_success(self) -> None:
        transcript = summary(14) + '\n{"type":"suite","event":"started","test_count":14}'
        self.assertIsNone(suite_result(transcript))
        self.assertIsNone(suite_result(summary(14).splitlines()[-1]))

    def run_transcript(self, text: str, *, list_only: bool = False) -> Report:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            transcript = directory / "console.txt"
            transcript.write_text(summary(14))
            command = [sys.executable, "-c", f"print({text!r})"]
            return execute(command, transcript, "LS4500Q0", image, list_only=list_only)

    def test_completed_suite_succeeds(self) -> None:
        report = self.run_transcript(summary(14, ignored=4))
        self.assertIsNone(report.error)
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.suite, SuiteResult(14, 0, 4))
        self.assertEqual(len(report.image_sha256), 64)
        json.dumps(asdict(report))

    def test_bad_suite_is_failure_even_with_successful_process(self) -> None:
        for text in ("", summary(0), summary(0, ignored=4), summary(1, failed=1)):
            with self.subTest(transcript=text):
                report = self.run_transcript(text)
                self.assertEqual(report.exit_code, 0)
                self.assertIsNotNone(report.error)

    def test_list_mode_does_not_require_execution_summary(self) -> None:
        report = self.run_transcript("driver_gpio: test", list_only=True)
        self.assertIsNone(report.error)
        self.assertIsNone(report.suite)

    def test_failed_command_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            with patch("subprocess.run", return_value=subprocess.CompletedProcess(["probe"], 7)):
                report = execute(["probe"], directory / "console.txt", "LS4500Q0", image)
            self.assertEqual(report.exit_code, 7)
            self.assertFalse(report.timed_out)
            self.assertIsNotNone(report.error)

    def test_timeout_preserves_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["probe"], 180)):
                report = execute(["probe"], directory / "console.txt", "LS4500Q0", image)
            self.assertIsNone(report.exit_code)
            self.assertTrue(report.timed_out)
            self.assertIsNotNone(report.error)

    def test_launch_failure_preserves_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            with patch("subprocess.run", side_effect=OSError("executable unavailable")):
                report = execute(["probe"], directory / "console.txt", "LS4500Q0", image)
            self.assertIsNone(report.exit_code)
            self.assertFalse(report.timed_out)
            self.assertEqual(report.error, "executable unavailable")

    def test_probe_lock_excludes_only_the_selected_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch("tempfile.gettempdir", return_value=temporary):
                with probe_lock("first"):
                    with self.assertRaises(BlockingIOError):
                        with probe_lock("first"):
                            self.fail("Concurrent access to the same probe was allowed")
                    with probe_lock("second"):
                        pass
                # Cleanup also releases the lock after a failed nested acquisition.
                with probe_lock("first"):
                    pass


if __name__ == "__main__":
    unittest.main()

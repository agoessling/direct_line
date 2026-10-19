"""Check probe selection and reporting on unsuccessful experiment runs."""

import json
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from tools.debug.experiments.run_tests import (
    Arguments,
    SuiteResult,
    command_line,
    execute,
    suite_result,
)


class RunnerTest(unittest.TestCase):
    def test_filters_cannot_override_probe(self) -> None:
        args = Arguments(probe="LS4500Q0", filter=["--probe"], list=True)
        command = command_line("probe-rs", "firmware.elf", args)
        options, positional = command[: command.index("--")], command[command.index("--") + 1 :]
        self.assertEqual(options[options.index("--probe") + 1], "0451:bef3-5:LS4500Q0")
        self.assertIn("--verify", options)
        self.assertIn("--preverify", options)
        self.assertIn("--list", options)
        self.assertEqual(positional, ["firmware.elf", "--probe"])

    def test_force_flash_retains_post_program_verification(self) -> None:
        command = command_line("probe-rs", "firmware.elf", Arguments(force_flash=True))
        self.assertNotIn("--preverify", command)
        self.assertIn("--verify", command)

    def test_multiple_filters_rejected(self) -> None:
        with self.assertRaises(ValueError):
            command_line("probe-rs", "firmware.elf", Arguments(filter=["clock", "uart"]))

    def test_suite_summary_ignores_diagnostics(self) -> None:
        summary = '{"type":"suite","event":"ok","passed":14,"failed":0,"ignored":4}'
        self.assertEqual(
            suite_result("attached\n" + summary + "\ndisconnected\n"), SuiteResult(14, 0, 4)
        )

    def test_empty_suite_is_distinguished_from_missing_summary(self) -> None:
        summary = '{"type":"suite","event":"ok","passed":0,"failed":0,"ignored":0}'
        self.assertEqual(suite_result(summary), SuiteResult(0, 0, 0))
        self.assertIsNone(suite_result('{"type":"suite","event":"started","test_count":14}'))

    def test_malformed_counts_rejected(self) -> None:
        self.assertIsNone(
            suite_result('{"type":"suite","event":"ok","passed":true,"failed":0,"ignored":0}')
        )

    def test_failed_command_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            with patch("subprocess.run", return_value=subprocess.CompletedProcess(["probe"], 7)):
                report = execute(["probe"], directory / "console.txt", "LS4500Q0", image)
            self.assertEqual(report.exit_code, 7)
            self.assertFalse(report.timed_out)
            self.assertEqual(len(report.image_sha256), 64)
            json.dumps(asdict(report))

    def test_timeout_preserves_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["probe"], 180)):
                report = execute(["probe"], directory / "console.txt", "LS4500Q0", image)
            self.assertIsNone(report.exit_code)
            self.assertTrue(report.timed_out)


if __name__ == "__main__":
    unittest.main()

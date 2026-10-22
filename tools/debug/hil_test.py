"""Check explicit probe selection, exclusive access, and trustworthy result reporting."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from tools.debug.hil import Arguments, Report, SuiteResult, command_line, execute, suite_result
from tools.debug.output import stream_process
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
        command = command_line(
            "probe-rs", "firmware.elf", "cc1354p10.yaml", args, Path("target.txt")
        )
        options, positional = command[: command.index("--")], command[command.index("--") + 1 :]
        self.assertEqual(options[options.index("--probe") + 1], "0451:bef3-5:LS4500Q0")
        self.assertEqual(options[options.index("--chip-description-path") + 1], "cc1354p10.yaml")
        self.assertIn("--verify", options)
        self.assertIn("--preverify", options)
        self.assertIn("--list", options)
        self.assertEqual(positional, ["firmware.elf", "--probe"])

    def test_force_flash_retains_post_program_verification(self) -> None:
        command = command_line(
            "probe-rs",
            "firmware.elf",
            "cc1354p10.yaml",
            Arguments(force_flash=True),
            Path("target.txt"),
        )
        self.assertNotIn("--preverify", command)
        self.assertIn("--verify", command)

    def test_multiple_filters_rejected(self) -> None:
        with self.assertRaises(ValueError):
            command_line(
                "probe-rs",
                "firmware.elf",
                "cc1354p10.yaml",
                Arguments(filter=["clock", "uart"]),
                Path("target.txt"),
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
                with self.assertRaises(ValueError):
                    suite_result(transcript)

    def test_incomplete_later_suite_cannot_reuse_success(self) -> None:
        transcript = summary(14) + '\n{"type":"suite","event":"started","test_count":14}'
        with self.assertRaises(ValueError):
            suite_result(transcript)
        with self.assertRaises(ValueError):
            suite_result(summary(14).splitlines()[-1])

    def run_transcript(self, text: str, *, list_only: bool = False) -> Report:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            transcript = directory / "console.txt"
            transcript.write_text(summary(14))
            command = [sys.executable, "-c", f"print({text!r})"]
            with redirect_stdout(io.StringIO()):
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
            report = execute(
                [sys.executable, "-c", "raise SystemExit(7)"],
                directory / "stdout.txt",
                "LS4500Q0",
                image,
            )
            self.assertEqual(report.exit_code, 7)
            self.assertFalse(report.timed_out)
            self.assertIsNotNone(report.error)

    def test_failed_suite_is_distinct_from_runner_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            for status in (1, 7):
                with self.subTest(status=status), redirect_stdout(io.StringIO()):
                    command = [
                        sys.executable,
                        "-c",
                        f"print({summary(0, failed=1)!r}); raise SystemExit({status})",
                    ]
                    report = execute(command, directory / "stdout.txt", "LS4500Q0", image)
                    self.assertEqual(report.exit_code, status)
                    self.assertEqual(report.suite, SuiteResult(0, 1, 0))
                    self.assertEqual(report.error is None, status == 1)

    def test_timeout_preserves_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            with patch(
                "tools.debug.hil.stream_process",
                side_effect=subprocess.TimeoutExpired(["probe"], 180),
            ):
                report = execute(["probe"], directory / "console.txt", "LS4500Q0", image)
            self.assertIsNone(report.exit_code)
            self.assertTrue(report.timed_out)
            self.assertIsNotNone(report.error)

    def test_launch_failure_preserves_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            image = directory / "firmware.elf"
            image.write_bytes(b"firmware")
            with patch(
                "tools.debug.hil.stream_process", side_effect=OSError("executable unavailable")
            ):
                report = execute(["probe"], directory / "console.txt", "LS4500Q0", image)
            self.assertIsNone(report.exit_code)
            self.assertFalse(report.timed_out)
            self.assertEqual(report.error, "executable unavailable")

    def test_terminal_progress_and_target_log_routing(self) -> None:
        for progress in (False, True):
            command = command_line(
                "probe-rs", "image", "target", Arguments(), Path("target.txt"), progress=progress
            )
            self.assertEqual("--disable-progressbars" in command, not progress)
            self.assertEqual(command[command.index("--target-output-file") + 1], "target.txt")

    def test_malformed_events_are_not_ignored_after_success(self) -> None:
        for bad in (
            '{"type": "suite",',
            '{"type": "test", "event": "ok"}',
            '{"type": "test", "event": "surprise", "name": "test"}',
            "[]",
        ):
            with self.subTest(event=bad):
                with self.assertRaises(ValueError):
                    suite_result(summary(1) + "\n" + bad)
                report = self.run_transcript(summary(1) + "\n" + bad)
                self.assertIsNotNone(report.error)
                self.assertIsNone(report.suite)

    def test_realistic_event_stream_with_stack_trace(self) -> None:
        events = summary(0, failed=1).splitlines()
        events[1:1] = [
            '{"type":"test","event":"started","name":"fault"}',
            "Core 0",
            "    Frame 0: capture_fault",
            '{"type":"test","event":"failed","name":"fault","stdout":"timeout"}',
        ]
        self.assertEqual(suite_result("\n".join(events)), SuiteResult(0, 1, 0))

    def test_streaming_separates_channels_and_displays_before_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for progress in (False, True):
                with self.subTest(progress=progress):
                    marker = directory / f"seen-{progress}"
                    # The child cannot complete until its stdout has been displayed.
                    script = (
                        "import os,sys,time\n"
                        "from pathlib import Path\n"
                        "sys.stderr.write('diagnostic\\n' * 10000)\n"
                        "sys.stderr.flush()\n"
                        "print('ready', flush=True)\n"
                        "print(f'tty={os.isatty(2)}', file=sys.stderr, flush=True)\n"
                        f"while not Path({str(marker)!r}).exists(): time.sleep(0.01)\n"
                    )
                    lines: list[str] = []

                    def on_line(
                        line: str, *, collected: list[str] = lines, seen: Path = marker
                    ) -> None:
                        collected.append(line)
                        seen.touch()

                    with redirect_stderr(io.StringIO()):
                        status = stream_process(
                            [sys.executable, "-c", script],
                            directory / "stdout.txt",
                            directory / "stderr.txt",
                            on_line,
                            progress=progress,
                            timeout=5,
                        )
                    self.assertEqual(status, 0)
                    self.assertEqual(lines, ["ready"])
                    self.assertEqual((directory / "stdout.txt").read_text(), "ready\n")
                    self.assertIn(f"tty={progress}", (directory / "stderr.txt").read_text())

    def test_stream_timeout_reaps_child_and_preserves_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            pids: list[int] = []
            script = "import os,time; print(os.getpid(), flush=True); time.sleep(60)"
            with self.assertRaises(subprocess.TimeoutExpired):
                stream_process(
                    [sys.executable, "-c", script],
                    directory / "stdout.txt",
                    directory / "stderr.txt",
                    lambda line: pids.append(int(line)),
                    timeout=0.5,
                )
            self.assertEqual(len(pids), 1)
            self.assertIn(str(pids[0]), (directory / "stdout.txt").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pids[0], 0)

    def test_stream_interruption_reaps_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            pids: list[int] = []

            def interrupt(line: str) -> None:
                pids.append(int(line))
                raise KeyboardInterrupt

            with self.assertRaises(KeyboardInterrupt):
                stream_process(
                    [
                        sys.executable,
                        "-c",
                        "import os,time; print(os.getpid(), flush=True); time.sleep(60)",
                    ],
                    directory / "stdout.txt",
                    directory / "stderr.txt",
                    interrupt,
                    timeout=5,
                )
            self.assertEqual(len(pids), 1)
            with self.assertRaises(ProcessLookupError):
                os.kill(pids[0], 0)

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

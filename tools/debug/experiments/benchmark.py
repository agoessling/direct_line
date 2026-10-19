"""Compare persistent-session reset costs using the pinned probe-rs CLI."""

import argparse
import errno
import fcntl
import json
import os
import pty
import select
import signal
import statistics
import struct
import tempfile
import termios
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from python.runfiles import runfiles


@dataclass
class Arguments(argparse.Namespace):
    serial: str = ""
    output_dir: str = ""


@dataclass(frozen=True)
class Measurement:
    resets: int
    duration_s: float
    exit_code: int
    transcript: str


@contextmanager
def probe_lock(serial: str) -> Generator[None]:
    directory = Path(tempfile.gettempdir()) / f"direct-line-probes-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / serial).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def measure(command: list[str], resets: int, transcript: Path) -> Measurement:
    # The debug CLI requires a controlling terminal, even for command-only runs.
    start = time.monotonic()
    pid, terminal = pty.fork()
    if pid == 0:
        fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 120, 0, 0))
        os.execve(command[0], command, {**os.environ, "TERM": "xterm", "NO_COLOR": "1"})
    status: int | None = None
    terminal_open = True
    try:
        with transcript.open("wb") as output:
            while status is None or terminal_open:
                if time.monotonic() - start > 90:
                    raise TimeoutError("probe-rs did not finish within 90 seconds")
                if terminal_open and select.select([terminal], [], [], 0.05)[0]:
                    try:
                        chunk = os.read(terminal, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b""
                    if chunk:
                        output.write(chunk)
                    else:
                        terminal_open = False
                if status is None:
                    child, child_status = os.waitpid(pid, os.WNOHANG)
                    if child:
                        status = child_status
                if not terminal_open and status is None:
                    time.sleep(0.01)
        assert status is not None
        return Measurement(
            resets, time.monotonic() - start, os.waitstatus_to_exitcode(status), str(transcript)
        )
    finally:
        os.close(terminal)
        if status is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(namespace=Arguments())
    if not args.serial.isalnum():
        raise ValueError("Expected an alphanumeric probe serial")
    runtime = runfiles.Create()
    if runtime is None:
        raise RuntimeError("Bazel runfiles are unavailable")
    executable = runtime.Rlocation(os.environ["PROBE_RS"])
    if executable is None:
        raise RuntimeError("Pinned probe-rs executable is unavailable")
    workspace = Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])
    directory = (workspace / args.output_dir).resolve()
    if not directory.is_relative_to(workspace / ".results"):
        raise ValueError("Write benchmark output beneath the checkout's ignored .results directory")
    directory.mkdir(parents=True, exist_ok=False)
    base = [
        executable,
        "debug",
        "--probe",
        f"0451:bef3-5:{args.serial}",
        "--chip",
        "CC1354P10",
        "--protocol",
        "jtag",
        "--speed",
        "1000",
        "--no-rtt",
        "-c",
        "break",
    ]
    measurements: list[Measurement] = []
    with probe_lock(args.serial):
        for pair in range(3):
            for resets in (0, 10):
                command = base + [item for _ in range(resets) for item in ("-c", "reset")]
                # FCFG1.ICEPICK_DEVICE_ID checks memory access after the reset commands.
                command.extend(["-c", "x /1wx 0x50000b18", "-c", "quit"])
                result = measure(command, resets, directory / f"pair-{pair}-resets-{resets}.txt")
                measurements.append(result)
                print(json.dumps(asdict(result)), flush=True)
                if result.exit_code:
                    raise RuntimeError(f"probe-rs failed; see {result.transcript}")
    estimates = [
        (measurements[index + 1].duration_s - measurements[index].duration_s) / 10
        for index in range(0, len(measurements), 2)
    ]
    report = {
        "probe": args.serial,
        "description": (
            "Paired CLI wall-time difference per reset; includes frontend overhead, "
            "not reset-to-ready or MCU latency."
        ),
        "measurements": [asdict(result) for result in measurements],
        "incremental_reset_s": estimates,
        "median_incremental_reset_s": statistics.median(estimates),
    }
    (directory / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

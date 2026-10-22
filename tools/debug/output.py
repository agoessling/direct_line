"""Stream probe-rs output while retaining separate stdout and diagnostic transcripts."""

import codecs
import errno
import os
import pty
import selectors
import shutil
import subprocess
import sys
import termios
import time
import tty
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path


def stream_process(
    command: list[str],
    stdout_path: Path,
    stderr_path: Path,
    on_line: Callable[[str], None],
    *,
    progress: bool = False,
    timeout: float = 180,
) -> int:
    """Drain both streams concurrently; kill and reap the process on timeout or interruption."""
    with ExitStack() as stack:
        output = stack.enter_context(stdout_path.open("wb"))
        diagnostics = stack.enter_context(stderr_path.open("wb"))
        # Only stderr gets a terminal, so native flash bars cannot contaminate JSON events.
        read_fd, write_fd = pty.openpty() if progress else os.pipe()
        stack.enter_context(os.fdopen(read_fd, "rb", buffering=0))
        writer = stack.enter_context(os.fdopen(write_fd, "wb", buffering=0))
        if progress:
            tty.setraw(write_fd)  # Relay bytes unchanged; the user's terminal handles line endings.
            columns, rows = shutil.get_terminal_size()
            termios.tcsetwinsize(write_fd, (rows, columns))
        selector = stack.enter_context(selectors.DefaultSelector())
        started = time.monotonic()
        environment = os.environ.copy()
        if not progress or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
            environment["PROBE_RS_COLOR"] = "false"
        with subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=writer, env=environment
        ) as process:
            try:
                writer.close()  # EOF must depend only on the child's copy.
                assert process.stdout is not None
                stdout_fd = process.stdout.fileno()
                selector.register(stdout_fd, selectors.EVENT_READ)
                selector.register(read_fd, selectors.EVENT_READ)
                pending = b""
                decoder = codecs.getincrementaldecoder("utf-8")("replace")
                while selector.get_map():
                    remaining = timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, timeout)
                    for key, _ in selector.select(remaining):
                        try:
                            chunk = os.read(key.fd, 65536)
                        except OSError as error:
                            # Linux PTYs signal their final slave close with EIO instead of EOF.
                            if not (progress and key.fd == read_fd and error.errno == errno.EIO):
                                raise
                            chunk = b""
                        if not chunk:
                            selector.unregister(key.fd)
                            continue
                        if key.fd == stdout_fd:
                            output.write(chunk)
                            output.flush()
                            pending += chunk
                            while b"\n" in pending:
                                line, pending = pending.split(b"\n", 1)
                                on_line(line.decode("utf-8", errors="replace"))
                        else:
                            diagnostics.write(chunk)
                            diagnostics.flush()
                            sys.stderr.write(decoder.decode(chunk))
                            sys.stderr.flush()
                if pending:
                    on_line(pending.decode("utf-8", errors="replace"))
                sys.stderr.write(decoder.decode(b"", final=True))
                sys.stderr.flush()
                return process.wait(timeout=max(0, timeout - (time.monotonic() - started)))
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

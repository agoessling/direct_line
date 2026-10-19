"""Bound a Linux debugger process, including TI helpers that create their own sessions."""

import ctypes
import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast


def run(command: list[str], log: Path, timeout: float) -> int:
    """Run one process tree; the calling process must have no other live children."""
    # A subreaper adopts orphaned descendants even when they used setsid().
    PR_SET_CHILD_SUBREAPER = 36
    PR_GET_CHILD_SUBREAPER = 37
    # Load libc's prctl and preserve errno for failures reported through ctypes.
    prctl = cast(
        Callable[[int, object, int, int, int], int], ctypes.CDLL(None, use_errno=True).prctl
    )
    previous = ctypes.c_int()
    if prctl(PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) or prctl(
        PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0
    ):
        raise OSError(ctypes.get_errno(), "Cannot supervise debugger descendants")
    try:
        with log.open("wb") as output:
            # Isolate the worker from terminal signals; this supervisor owns its cleanup.
            child = subprocess.Popen(
                command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
            )
            try:
                return child.wait(timeout=timeout)
            finally:
                # Killing the worker reparents detached CloudAgent/DSLite helpers to us.
                if child.poll() is None:
                    child.kill()
                child.wait()
                reap_children()
    finally:
        # Subreaper status belongs to this process, so restore it after each run.
        if prctl(PR_SET_CHILD_SUBREAPER, previous.value, 0, 0, 0):
            raise OSError(ctypes.get_errno(), "Cannot restore child supervision")


def reap_children() -> None:
    # Linux lists direct children here, including helpers adopted after their parent exits.
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    deadline = time.monotonic() + 5
    while True:
        # Killing an adopted parent can expose another generation of descendants.
        pids = [int(value) for value in children.read_text().split()]
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                # The helper may have exited between enumeration and the signal.
                pass
            # Collect exited children without blocking on helpers still shutting down.
            os.waitpid(pid, os.WNOHANG)
        if time.monotonic() >= deadline:
            raise RuntimeError("Debugger descendants did not exit after SIGKILL")
        time.sleep(0.01)

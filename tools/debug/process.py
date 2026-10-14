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
            child = subprocess.Popen(
                command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
            )
            try:
                return child.wait(timeout=timeout)
            finally:
                # Killing the worker reparents detached CloudAgent/DSLite helpers to us.
                if child.poll() is None:
                    child.kill()
                _ = child.wait()
                reap_children()
    finally:
        if prctl(PR_SET_CHILD_SUBREAPER, previous.value, 0, 0, 0):
            raise OSError(ctypes.get_errno(), "Cannot restore child supervision")


def reap_children() -> None:
    children = Path(f"/proc/self/task/{os.getpid()}/children")
    deadline = time.monotonic() + 5
    while True:
        pids = [int(value) for value in children.read_text().split()]
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _ = os.waitpid(pid, os.WNOHANG)
        if time.monotonic() >= deadline:
            raise RuntimeError("Debugger descendants did not exit after SIGKILL")
        time.sleep(0.01)

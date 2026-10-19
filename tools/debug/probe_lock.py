"""Serialize access to each explicitly selected hardware probe."""

import fcntl
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def probe_lock(serial: str) -> Generator[None]:
    directory = Path(tempfile.gettempdir()) / f"direct-line-probes-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    with (directory / serial).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield

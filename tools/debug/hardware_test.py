#!/usr/bin/env python3
"""Verify, flash, and capture the hardware_test firmware on one CC1354P10 board.

Build first: bazel build --config=m33 //src:hardware_test
Run separately for each probe; requires Linux serial-port and XDS110 access.
"""

import argparse
import errno
import glob
import os
from pathlib import Path
import re
import select
import signal
import struct
import subprocess
import tempfile
import termios
import threading
import time
import tty
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
BANNER = b"DIRECT_LINE_HW_TEST v1"
PASS = b"RESULT PASS 30000 ordered/checksummed records"


def config_for_probe(serial, destination):
    tree = ET.parse(ROOT / "tools/debug/xds110_cc1354p10.ccxml")
    connection = tree.find(".//connection")
    platform = connection.find("platform")
    selection = ET.Element(
        "property", {"Type": "choicelist", "Value": "1", "id": "Debug Probe Selection"}
    )
    choice = ET.SubElement(
        selection, "choice", {"Name": "Select by serial number", "value": "0"}
    )
    ET.SubElement(
        choice,
        "property",
        {"Type": "stringfield", "Value": serial, "id": "-- Enter the serial number"},
    )
    connection.insert(list(connection).index(platform), selection)
    tree.write(destination, encoding="UTF-8", xml_declaration=True)


def run_dslite(executable, arguments, log, exit_compat_library=None):
    environment = os.environ.copy()
    if exit_compat_library:
        existing = environment.get("LD_PRELOAD", "")
        environment["LD_PRELOAD"] = str(exit_compat_library) + (":" + existing if existing else "")
    with log.open("wb") as output:
        process = subprocess.Popen(
            [str(executable), *arguments], stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True, env=environment,
        )
        try:
            result = process.wait(timeout=60)
        except subprocess.TimeoutExpired as error:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise RuntimeError(f"DSLite timed out; see {log}") from error
    if result != 0:
        raise RuntimeError(f"DSLite exited {result}; see {log}")


def read_id(executable, config, directory, name, address, exit_compat_library=None):
    binary = directory / f"{name}.bin"
    binary.unlink(missing_ok=True)
    run_dslite(executable, [
        "memory", f"--config={config}", f"--range={address},1",
        f"--output={binary}", "--timeout=20",
    ], directory / f"{name}.log", exit_compat_library)
    data = binary.read_bytes()
    if len(data) != 4:
        raise RuntimeError(f"Expected four bytes for {name}, got {len(data)}")
    return struct.unpack("<I", data)[0]


def reset_probe(args, directory, action):
    log = directory / f"reset_{action}.log"
    with log.open("wb") as output:
        try:
            subprocess.run(
                [str(args.reset_tool), "-s", args.probe, "-a", action],
                stdout=output, stderr=subprocess.STDOUT, timeout=5, check=True,
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as error:
            raise RuntimeError(f"Probe reset {action} failed; see {log}") from error


class Capture:
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.data = bytearray()
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.read, daemon=True)

    def read(self):
        try:
            while not self.stop.is_set():
                if select.select([self.descriptor], [], [], 0.1)[0]:
                    chunk = os.read(self.descriptor, 4096)
                    if not chunk:
                        raise RuntimeError("UART disconnected")
                    with self.lock:
                        self.data.extend(chunk)
        except (OSError, RuntimeError) as error:
            self.error = error

    def snapshot(self):
        with self.lock:
            return bytes(self.data)


def open_uart(port):
    deadline = time.monotonic() + 15
    reported = False
    while True:
        try:
            return os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except PermissionError as error:
            raise RuntimeError(f"Cannot open UART {port}: grant this user serial-port "
                               "read/write permission and retry") from error
        except OSError as error:
            if error.errno != errno.EBUSY or time.monotonic() >= deadline:
                raise
            if not reported:
                print("UART busy; waiting up to 15s for probe discovery to finish", flush=True)
                reported = True
            time.sleep(0.25)


def execute(args, directory):
    config = directory / "probe.ccxml"
    config_for_probe(args.probe, config)
    ports = glob.glob(f"/dev/serial/by-id/*{args.probe}*-if00")
    if len(ports) != 1:
        raise RuntimeError(f"Expected one application UART for {args.probe}; found {ports}")
    print(f"Probe {args.probe}; UART {ports[0]}; logs {directory}", flush=True)
    descriptor = open_uart(ports[0])
    capture = Capture(descriptor)
    original = None
    try:
        original = termios.tcgetattr(descriptor)
        tty.setraw(descriptor)
        attributes = termios.tcgetattr(descriptor)
        attributes[4] = attributes[5] = termios.B115200
        attributes[2] |= termios.CLOCAL | termios.CREAD
        attributes[2] &= ~termios.CRTSCTS
        termios.tcsetattr(descriptor, termios.TCSANOW, attributes)
        termios.tcflush(descriptor, termios.TCIFLUSH)
        user = read_id(args.dslite, config, directory, "user_id", "0x50000A94", args.exit_compat_library)
        icepick = read_id(args.dslite, config, directory, "icepick_id", "0x50000B18", args.exit_compat_library)
        print(f"USER_ID=0x{user:08x} ICEPICK_ID=0x{icepick:08x}", flush=True)
        if ((icepick >> 12) & 0xFFFF != 0xBB78 or (user >> 12) & 0xF != 0xF
                or not user & (1 << 23) or not user & (1 << 25)):
            raise RuntimeError("Silicon IDs do not match the expected CC1354P10 target")
        run_dslite(args.dslite, [
            "flash", f"--config={config}", "-f", "-v", "--timeout=30", str(args.elf),
        ], directory / "flash.log", args.exit_compat_library)
        # Only capture a fresh boot of the verified image. Old firmware may have emitted
        # its own PASS before the flash operation halted it.
        try:
            reset_probe(args, directory, "assert")
            termios.tcflush(descriptor, termios.TCIFLUSH)
            time.sleep(0.1)  # Let pending USB/UART bytes arrive while the MCU is held in reset.
            termios.tcflush(descriptor, termios.TCIFLUSH)
            capture.thread.start()
        finally:
            # Also release reset if assertion partially succeeded or capture setup failed.
            reset_probe(args, directory, "deassert")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if capture.error:
                raise RuntimeError(f"UART capture failed: {capture.error}")
            data = capture.snapshot()
            if b"FAIL" in data:
                raise RuntimeError("Firmware reported FAIL; see uart.log")
            lines = [line.rstrip(b"\r") for line in data.split(b"\n")[:-1]]
            if BANNER in lines and PASS in lines and lines.index(BANNER) < lines.index(PASS):
                print(data.decode("utf-8", errors="replace"), end="", flush=True)
                return
            time.sleep(0.05)
        raise RuntimeError("No complete hardware-test PASS within 25s after reset; see uart.log")
    finally:
        capture.stop.set()
        if capture.thread.ident is not None:
            capture.thread.join(timeout=1)
        (directory / "uart.log").write_bytes(capture.snapshot())
        try:
            if original is not None:
                try:
                    termios.tcsetattr(descriptor, termios.TCSANOW, original)
                except termios.error:
                    # A probe firmware update or unplug can remove the UART.
                    # Preserve the original failure rather than hiding it in cleanup.
                    pass
        finally:
            os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", required=True, help="XDS110 serial number")
    parser.add_argument("--dslite", required=True, type=Path, help="Path to the DSLite executable")
    parser.add_argument("--elf", type=Path, default=ROOT / "bazel-bin/src/hardware_test")
    parser.add_argument("--output-dir", type=Path, help="Directory for probe config and logs")
    parser.add_argument("--exit-compat-library", type=Path, help="Optional DSLite shutdown workaround .so")
    parser.add_argument("--reset-tool", type=Path, help="Path to xds110reset (inferred from DSLite by default)")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.probe):
        parser.error("--probe must be an XDS110 serial number")
    args.dslite = args.dslite.resolve()
    args.elf = args.elf.resolve()
    if not args.dslite.is_file() or not args.elf.is_file():
        parser.error("--dslite and --elf must point to existing files")
    args.reset_tool = (args.reset_tool or args.dslite.parents[2] / "common/uscif/xds110/xds110reset").resolve()
    if not args.reset_tool.is_file():
        parser.error("Cannot find xds110reset; provide --reset-tool")
    if args.exit_compat_library:
        args.exit_compat_library = args.exit_compat_library.resolve()
        if not args.exit_compat_library.is_file():
            parser.error("--exit-compat-library must point to an existing shared library")
    directory = (args.output_dir or Path(tempfile.mkdtemp(prefix="direct-line-hardware-"))).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        execute(args, directory)
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {error}; logs: {directory}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

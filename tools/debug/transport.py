"""Pinned TI probe configuration, verified programming, and bounded processes."""

import os
import signal
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def config_for_probe(serial: str, destination: Path) -> None:
    tree = ET.parse(ROOT / "tools/debug/xds110_cc1354p10.ccxml")
    connection = tree.find(".//connection")
    if connection is None:
        raise ValueError("Probe template lacks a connection")
    platform = connection.find("platform")
    if platform is None:
        raise ValueError("Probe template lacks a platform")
    selection = ET.Element(
        "property", {"Type": "choicelist", "Value": "1", "id": "Debug Probe Selection"}
    )
    choice = ET.SubElement(selection, "choice", {"Name": "Select by serial number", "value": "0"})
    _ = ET.SubElement(
        choice,
        "property",
        {"Type": "stringfield", "Value": serial, "id": "-- Enter the serial number"},
    )
    connection.insert(list(connection).index(platform), selection)
    tree.write(destination, encoding="UTF-8", xml_declaration=True)


def run_dslite(executable: Path, arguments: list[str], log: Path) -> None:
    environment = os.environ.copy()
    with log.open("wb") as output:
        process = subprocess.Popen(
            [str(executable), *arguments],
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=environment,
        )
        try:
            result = process.wait(timeout=60)
        except subprocess.TimeoutExpired as error:
            os.killpg(process.pid, signal.SIGKILL)
            _ = process.wait()
            raise RuntimeError(f"DSLite timed out; see {log}") from error
    if result != 0:
        raise RuntimeError(f"DSLite exited {result}; see {log}")


def read_id(executable: Path, config: Path, directory: Path, name: str, address: str) -> int:
    binary = directory / f"{name}.bin"
    binary.unlink(missing_ok=True)
    run_dslite(
        executable,
        [
            "memory",
            f"--config={config}",
            f"--range={address},1",
            f"--output={binary}",
            "--timeout=20",
        ],
        directory / f"{name}.log",
    )
    data = binary.read_bytes()
    if len(data) != 4:
        raise RuntimeError(f"Expected four bytes for {name}, got {len(data)}")
    return int.from_bytes(data, "little")


def program_image(dslite: Path, elf: Path, config: Path, directory: Path) -> dict[str, str]:
    """Check silicon identity and require successful programming with verification."""
    user = read_id(dslite, config, directory, "user_id", "0x50000A94")
    icepick = read_id(dslite, config, directory, "icepick_id", "0x50000B18")
    print(f"USER_ID=0x{user:08x} ICEPICK_ID=0x{icepick:08x}", flush=True)
    if (
        (icepick >> 12) & 0xFFFF != 0xBB78
        or (user >> 12) & 0xF != 0xF
        or not user & (1 << 23)
        or not user & (1 << 25)
    ):
        raise RuntimeError("Silicon IDs do not match the expected CC1354P10 target")
    run_dslite(
        dslite,
        [
            "flash",
            f"--config={config}",
            "-f",
            "-v",
            "--timeout=30",
            str(elf),
        ],
        directory / "flash.log",
    )
    return {"user_id": f"0x{user:08x}", "icepick_id": f"0x{icepick:08x}"}

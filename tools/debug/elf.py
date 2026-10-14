"""Read the small HIL ABI from an ARM ELF32 image without debugger access."""

import struct
from io import BytesIO
from typing import cast

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

from tools.debug.hil_types import Case

type TestRecord = tuple[int, int, int, bytes]


class Elf:
    def __init__(self, data: bytes) -> None:
        self.data: bytes = data
        self.symbols: dict[str, tuple[int, int, int]] = {}
        try:
            self.image: ELFFile = ELFFile(BytesIO(data))
            if (
                self.image.elfclass != 32
                or not self.image.little_endian
                or self.image["e_type"] != "ET_EXEC"
                or self.image["e_machine"] != "EM_ARM"
            ):
                raise ValueError("Expected a little-endian ARM ELF32 executable")
            for section in self.image.iter_sections():
                if not isinstance(section, SymbolTableSection):
                    continue
                for symbol in section.iter_symbols():
                    index = cast(int | str, symbol["st_shndx"])
                    if not isinstance(index, int) or not 0 < index < self.image.num_sections():
                        continue
                    self.symbols[symbol.name] = (
                        cast(int, symbol["st_value"]),
                        cast(int, symbol["st_size"]),
                        index,
                    )
        except ELFError as error:
            raise ValueError(f"Invalid ELF image: {error}") from error

    def address(self, name: str, size: int | None = None) -> int:
        address, actual_size, _ = self.symbols[name]
        if size is not None and size != actual_size:
            raise ValueError(f"Unexpected {name} size: {actual_size}, expected {size}")
        return address

    def contents(self, name: str) -> bytes:
        address, size, index = self.symbols[name]
        section = self.image.get_section(index)
        if section["sh_type"] == "SHT_NOBITS" or not section["sh_flags"] & 2:
            raise ValueError(f"{name} is not allocated file-backed data")
        start = address - section["sh_addr"]
        length = section["sh_size"]
        offset = section["sh_offset"]
        if start < 0 or start + size > length:
            raise ValueError(f"{name} exceeds its ELF section")
        if offset + length > len(self.data):
            raise ValueError("ELF section extends beyond file")
        return section.data()[start : start + size]

    def cases(self) -> list[Case]:
        (count,) = cast(tuple[int], struct.unpack("<I", self.contents("HIL_TEST_COUNT")))
        data = self.contents("HIL_TESTS")
        if not 0 < count <= 256 or len(data) != count * 64:
            raise ValueError("Invalid HIL test table")
        result: list[Case] = []
        for offset in range(0, len(data), 64):
            identifier, timeout, expected, raw_name = cast(
                TestRecord, struct.unpack_from("<III52s", data, offset)
            )
            name = raw_name.split(b"\0", 1)[0].decode("ascii")
            if not name or not 1 <= timeout <= 60000 or expected not in range(4):
                raise ValueError("Invalid HIL test metadata")
            result.append(Case(id=identifier, name=name, timeout_ms=timeout, expected=expected))
        if (
            len({case["id"] for case in result}) != count
            or len({case["name"] for case in result}) != count
        ):
            raise ValueError("Duplicate test identifiers or names")
        return result

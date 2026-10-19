"""Read the small HIL ABI from an ARM ELF32 image without debugger access."""

import re
import struct
from dataclasses import dataclass
from io import BytesIO
from typing import Self, cast

from elftools.common.exceptions import ELFError
from elftools.elf.constants import SH_FLAGS
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

from tools.debug.protocol import Case, ExpectedOutcome

# Rust TestDescription: three little-endian u32s and two zero-padded ASCII fields.
TEST_RECORD = struct.Struct("<III52s64s")


@dataclass(frozen=True)
class Symbol:
    address: int
    size: int
    section_index: int


@dataclass(frozen=True)
class TestRecord:
    id: int
    timeout_ms: int
    expected: int
    name: bytes
    suites: bytes

    @classmethod
    def unpack_from(cls, data: bytes, offset: int) -> Self:
        # struct's untyped tuple follows the fixed field order above.
        return cls(*cast(tuple[int, int, int, bytes, bytes], TEST_RECORD.unpack_from(data, offset)))


class Elf:
    def __init__(self, data: bytes) -> None:
        self.data: bytes = data
        self.symbols: dict[str, Symbol] = {}
        try:
            self.image: ELFFile = ELFFile(BytesIO(data))
            # The debugger ABI assumes a linked little-endian ARM32 image.
            if (
                self.image["e_ident"]["EI_CLASS"] != "ELFCLASS32"
                or not self.image.little_endian
                or self.image["e_type"] != "ET_EXEC"
                or self.image["e_machine"] != "EM_ARM"
            ):
                raise ValueError("Expected a little-endian ARM ELF32 executable")
            # Index symbols by name so callers need no ELF traversal logic.
            for section in self.image.iter_sections():
                if not isinstance(section, SymbolTableSection):
                    continue
                for symbol in section.iter_symbols():
                    index = cast(int | str, symbol["st_shndx"])
                    # Undefined, absolute, and common symbols have no containing section.
                    if not isinstance(index, int) or not 0 < index < self.image.num_sections():
                        continue
                    self.symbols[symbol.name] = Symbol(
                        address=cast(int, symbol["st_value"]),
                        size=cast(int, symbol["st_size"]),
                        section_index=index,
                    )
        except ELFError as error:
            raise ValueError(f"Invalid ELF image: {error}") from error

    def address(self, name: str, size: int | None = None) -> int:
        """Return a target address, optionally checking the debugger's expected record size."""
        symbol = self.symbols[name]
        if size is not None and size != symbol.size:
            raise ValueError(f"Unexpected {name} size: {symbol.size}, expected {size}")
        return symbol.address

    def contents(self, name: str) -> bytes:
        """Read a symbol's initial bytes from the ELF, without accessing the board."""
        symbol = self.symbols[name]
        section = self.image.get_section(symbol.section_index)
        # Require target memory backed by file bytes; .bss has no stored contents.
        if section["sh_type"] == "SHT_NOBITS" or not section["sh_flags"] & SH_FLAGS.SHF_ALLOC:
            raise ValueError(f"{name} is not allocated file-backed data")
        # Convert the runtime address to an offset within the containing section.
        start = symbol.address - section["sh_addr"]
        length = section["sh_size"]
        offset = section["sh_offset"]
        # Check both symbol and file bounds before slicing; Python slices silently truncate.
        if start < 0 or start + symbol.size > length:
            raise ValueError(f"{name} exceeds its ELF section")
        if offset + length > len(self.data):
            raise ValueError("ELF section extends beyond file")
        return section.data()[start : start + symbol.size]

    def cases(self) -> list[Case]:
        """Decode the firmware registry into the runner's JSON-compatible case records."""
        (count,) = cast(tuple[int], struct.unpack("<I", self.contents("HIL_TEST_COUNT")))
        data = self.contents("HIL_TESTS")
        # Match the registry's case limit and reject incompatible record layouts.
        if not 0 < count <= 256 or len(data) != count * TEST_RECORD.size:
            raise ValueError("Invalid HIL test table")
        result: list[Case] = []
        for offset in range(0, len(data), TEST_RECORD.size):
            record = TestRecord.unpack_from(data, offset)
            # Strip fixed-width padding; suite names are separated by spaces.
            name = record.name.split(b"\0", 1)[0].decode("ascii")
            suites = record.suites.split(b"\0", 1)[0].decode("ascii").split()
            if not name or not 1 <= record.timeout_ms <= 60000:
                raise ValueError("Invalid HIL test metadata")
            if (
                not suites
                or len(set(suites)) != len(suites)
                or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", suite) for suite in suites)
            ):
                raise ValueError("Invalid HIL suite metadata")
            try:
                outcome = ExpectedOutcome(record.expected)
            except ValueError as error:
                raise ValueError("Invalid HIL expected-outcome metadata") from error
            result.append(
                Case(
                    id=record.id,
                    name=name,
                    timeout_ms=record.timeout_ms,
                    expected=outcome,
                    suites=suites,
                )
            )
        # Names identify cases in reports; IDs index the firmware's function table.
        if (
            len({case["id"] for case in result}) != count
            or len({case["name"] for case in result}) != count
        ):
            raise ValueError("Duplicate test identifiers or names")
        if any(case["id"] != index for index, case in enumerate(result)):
            raise ValueError("HIL identifiers must match table indices")
        return result

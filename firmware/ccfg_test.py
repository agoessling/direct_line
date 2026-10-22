"""Check CCFG placement and loadability; SysConfig owns the configuration values."""

import sys
from io import BytesIO
from pathlib import Path
from typing import cast

from elftools.elf.elffile import ELFFile


def main() -> None:
    image = Path(sys.argv[1]).read_bytes()
    elf = ELFFile(BytesIO(image))
    assert elf.elfclass == 32 and elf.little_endian, "expected ELF32 little-endian"
    ccfg = elf.get_section_by_name(".ccfg")
    assert ccfg is not None, "missing .ccfg"
    assert ccfg["sh_type"] == "SHT_PROGBITS" and ccfg["sh_flags"] & 2, (
        "CCFG must be allocated PROGBITS"
    )
    address = ccfg["sh_addr"]
    offset = ccfg["sh_offset"]
    length = ccfg["sh_size"]
    assert address == 0x50000000, "CCFG must be at the boot ROM's fixed address"
    assert length == 124, "CC1354P10 CCFG must occupy 124 bytes"
    assert offset + length <= len(image), "truncated CCFG contents"

    # Require file-backed PT_LOAD coverage at the boot ROM's physical address.
    for segment in elf.iter_segments("PT_LOAD"):
        start = segment["p_offset"]
        file_size = segment["p_filesz"]
        delta = offset - start
        if (
            0 <= delta
            and delta + length <= file_size <= segment["p_memsz"]
            and start + file_size <= len(image)
            and segment["p_vaddr"] + delta == address
            and cast(int, segment["p_paddr"]) + delta == address
        ):
            return
    raise AssertionError("CCFG contents must be loadable at 0x50000000")


if __name__ == "__main__":
    main()

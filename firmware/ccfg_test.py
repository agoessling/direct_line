"""Check CCFG placement and loadability; SysConfig owns the configuration values."""

import struct
import sys
from pathlib import Path


def section(image, wanted):
    assert image[:7] == b"\x7fELF\x01\x01\x01", "expected ELF32 little-endian"
    table = struct.unpack_from("<I", image, 32)[0]
    size, count, names_index = struct.unpack_from("<HHH", image, 46)
    headers = [struct.unpack_from("<10I", image, table + i * size) for i in range(count)]
    names_header = headers[names_index]
    names = image[names_header[4] : names_header[4] + names_header[5]]
    for header in headers:
        name = names[header[0] :].split(b"\0", 1)[0].decode()
        if name == wanted:
            return header
    raise AssertionError(f"missing {wanted}")


def main():
    image = Path(sys.argv[1]).read_bytes()
    _, kind, flags, address, offset, length, *_ = section(image, ".ccfg")
    assert kind == 1 and flags & 2, "CCFG must be allocated PROGBITS"
    assert address == 0x50000000, "CCFG must be at the boot ROM's fixed address"
    assert length == 124, "CC1354P10 CCFG must occupy 124 bytes"
    assert offset + length <= len(image), "truncated CCFG contents"

    # Section headers alone do not ensure a programmer will load these bytes.
    # Require file-backed PT_LOAD coverage at the correct physical address.
    table = struct.unpack_from("<I", image, 28)[0]
    size, count = struct.unpack_from("<HH", image, 42)
    for index in range(count):
        kind, start, virtual, physical, file_size, memory_size, _, _ = struct.unpack_from(
            "<8I", image, table + index * size
        )
        delta = offset - start
        if (
            kind == 1  # PT_LOAD.
            and 0 <= delta
            and delta + length <= file_size <= memory_size
            and start + file_size <= len(image)
            and virtual + delta == address
            and physical + delta == address
        ):
            return
    raise AssertionError("CCFG contents must be loadable at 0x50000000")


if __name__ == "__main__":
    main()

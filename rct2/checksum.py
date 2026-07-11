"""RCT2 file checksum computation.

The checksum is a 32-bit value appended to RLE-compressed data. It uses a
rolling sum with bit rotation, then applies a format-specific magic number.

TD6 magic: -120001
"""


def compute(data: bytes) -> int:
    """Compute the RCT2 checksum for raw (compressed) file data."""
    summation = 0
    for byte in data:
        # Add byte to lower 8 bits without carry-over
        temp = summation + byte
        summation = (summation & 0xFFFFFF00) | (temp & 0xFF)
        # Rotate left by 3 bits (32-bit word)
        summation = ((summation << 3) | (summation >> 29)) & 0xFFFFFFFF
    # Apply TD6 magic number
    return (summation - 120001) & 0xFFFFFFFF


def verify(data: bytes, expected: int) -> bool:
    """Check if data matches its expected checksum."""
    return compute(data) == expected


def append(data: bytes) -> bytes:
    """Return data with its checksum appended (4 bytes, little-endian)."""
    checksum = compute(data)
    return data + checksum.to_bytes(4, "little")


def strip(data: bytes) -> tuple[bytes, int]:
    """Split file data into (content, checksum). Does not verify."""
    return data[:-4], int.from_bytes(data[-4:], "little")

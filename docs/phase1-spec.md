# Phase 1 Spec: TD6 File Format Round-Trip

## Goal

Read a real `.td6` file from OpenRCT2, decode it into Python data structures,
re-encode it back to bytes, and assert the output matches the input.

No generation. No geometry. Just prove we can read and write the format correctly.

---

## What is a TD6 file?

A `.td6` file is how RCT2 and OpenRCT2 save and share individual ride designs.
You can find them in your OpenRCT2 folder under `Documents/OpenRCT2/tracks/`.

The file has two layers:

1. **RLE compression** — the whole file is compressed using a simple run-length
   encoding scheme. We decompress first, then parse.
2. **Raw binary data** — after decompression, it's a flat array of bytes at
   specific offsets describing the ride.

The last 4 bytes of the compressed file are a checksum. We skip validating
and regenerating this in Phase 1 — just strip it off on read, ignore it on write.

---

## RLE compression

RCT2 uses a simple custom RLE scheme:

- Read a control byte `c`
- If `c >= 128`: the next byte is repeated `257 - c` times
- If `c < 128`: the next `c + 1` bytes are literal (copy as-is)
- Repeat until end of input

We need both a decompressor (for reading) and a compressor (for writing).

Reference implementation to port: `rle/lib.go` in kevinburke/rct.

### Why the same data has more than one valid encoding

RLE compression is not one-to-one. A given stretch of bytes can be encoded
correctly in multiple ways, and they all decompress to the identical result.

Example — the four bytes `AA AA AA AA` can be encoded as:
- one **run**: "repeat `AA` four times" (2 bytes), or
- one **literal**: "the next 4 bytes are `AA AA AA AA`" (5 bytes).

Both are valid. Both decompress to `AA AA AA AA`.

This matters for testing. The original RCT2 encoder that produced our fixture made
its own choices about where to draw run/literal boundaries; our `compress()` makes
its own. So re-compressing a file will **not** necessarily produce byte-identical
output to the original — even when our code is perfectly correct.

Therefore the round-trip test compares **decompressed** bytes, not the raw
compressed bytes:

```python
assert decompress(reencoded) == decompress(compressed)   # ✅ compares real data
# assert reencoded == compressed                         # ❌ can fail for a non-real reason
```

Comparing decompressed bytes proves our *data* is faithful. It does **not** prove
our compressor reproduces the exact file RCT2 would. That stronger property only
matters if something downstream needs a byte-identical file — most likely the
checksum (deferred to Phase 3). For Phase 1, decompressed comparison is correct.

---

## Decompressed file layout

All offsets below refer to the decompressed byte array.

### Header fields we care about

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| 0x00 | 1 | `ride_type` | e.g. 0x11 = Mine Train |
| 0x06 | 1 | `operating_mode` | 0 = normal, 1 = continuous circuit |
| 0x07 | 1 | `color_scheme` | bits 0-1 = scheme, bit 3 = always 1 for RCT2 |
| 0x4b | 1 | `control_flags` | see control flags section below |
| 0x4c | 1 | `num_trains` | |
| 0x4d | 1 | `cars_per_train` | |
| 0x4e | 1 | `min_wait_time` | |
| 0x4f | 1 | `max_wait_time` | |
| 0x51 | 1 | `max_speed` | |
| 0x52 | 1 | `average_speed` | |
| 0x5b | 1 | `excitement` | |
| 0x5c | 1 | `intensity` | |
| 0x5d | 1 | `nausea` | |
| 0x70 | 16 | `dat_data` | raw bytes, includes vehicle type string at 0x74 |
| 0x80 | 1 | `x_space_required` | |
| 0x81 | 1 | `y_space_required` | |
| 0xa2 | 1 | `circuits_and_lift_speed` | top 3 bits = circuits, bottom 5 = lift speed |

### Track data (starts at 0xa3)

Each track element is **2 bytes**:
- Byte 0: segment type (e.g. 0x00 = flat, 0x04 = 25 deg up)
- Byte 1: flags
  - Bit 7: has chain lift
  - Bit 6: is inverted
  - Bits 2-1: colour scheme
  - Bit 0: has cable lift

The track element list is **terminated by a 0xFF byte**.

Everything after track data (entrance/exit data, scenery) we store as raw bytes
and write back verbatim in Phase 1. We don't parse it yet.

### Control flags (0x4b)

Packed into a single byte:
- Bit 7: use maximum time
- Bit 6: use minimum time
- Bit 5: sync with adjacent station
- Bit 4: leave if another train arrives
- Bit 3: wait for load
- Bits 0-2: load type (0=quarter, 1=half, 2=three-quarter, 3=full, 4=any)

---

## Python data structures

```python
@dataclass
class TrackElement:
    segment_type: int   # 0x00–0xFF
    chain_lift: bool
    inverted: bool
    colour_scheme: int  # 0–3
    cable_lift: bool

@dataclass
class Ride:
    ride_type: int
    operating_mode: int
    color_scheme: int
    control_flags: int      # store as raw byte for now
    num_trains: int
    cars_per_train: int
    min_wait_time: int
    max_wait_time: int
    max_speed: int
    average_speed: int
    excitement: int
    intensity: int
    nausea: int
    dat_data: bytes         # 16 bytes, 0x70–0x7f
    x_space_required: int
    y_space_required: int
    circuits_and_lift_speed: int
    header: bytes           # raw bytes 0x00–0xa2 (the full header block)
    elements: list[TrackElement]
    remainder: bytes        # everything after track data, written back verbatim
```

### Why `Ride` keeps a raw `header` blob

The header runs from 0x00 to 0xa2 (163 bytes), but we only name ~20 of those
bytes as fields. The unnamed bytes between them (cost at 0x02, the 0x08–0x4a
range, G-force fields, etc.) still need to survive a round-trip. So `Ride` keeps
the entire raw header block, and:

- `decode()` parses the named fields *out of* `header` for convenient inspection.
- `encode()` starts from a copy of `header`, overwrites the named-field offsets
  with the current field values, then appends elements + terminator + remainder.

Named fields are the source of truth for *their own* offsets; `header` is the
source of truth for every byte we haven't parsed yet. This is the same
"store opaque, write back verbatim" approach used for `remainder`, applied to the
gaps within the header. As later phases parse more fields, those bytes migrate
from "covered by header" to "covered by a named field" — behavior is identical
either way.

---

## Files to create

### `rct2/rle.py`
- `decompress(data: bytes) -> bytes`
- `compress(data: bytes) -> bytes`

### `rct2/td6.py`
- `decode(data: bytes) -> Ride` — takes raw compressed bytes, returns a Ride
- `encode(ride: Ride) -> bytes` — takes a Ride, returns raw compressed bytes

### `tests/test_rle.py`
- Test that compressing then decompressing returns the original bytes
- Test a known RLE sequence by hand

### `tests/test_td6.py`
- Load a real `.td6` file from `data/sample_rides/`
- Decode it
- Re-encode it
- Assert the decompressed bytes match (we skip the 4-byte checksum at the end)

---

## What "done" looks like

This test passes:

```python
def test_round_trip():
    with open("data/sample_rides/manic_miner_test.td6", "rb") as f:
        original = f.read()

    # strip 4-byte checksum
    compressed = original[:-4]

    ride = td6.decode(compressed)
    reencoded = td6.encode(ride)

    # Compare decompressed bytes, not raw compressed bytes: RLE has multiple
    # valid encodings of the same data, so our compressor may produce different
    # (still-correct) bytes than RCT2's. See "Why the same data has more than
    # one valid encoding" above.
    assert decompress(reencoded) == decompress(compressed)
```

---

## Out of scope for Phase 1

- Egress/entrance data parsing (stored as `remainder`, written back verbatim)
- Scenery data
- Feature flags (banking, loops, steep slope)
- G-force fields
- Generating any track — just reading and writing existing files

---

## Getting a sample .td6 file

OpenRCT2 ships with built-in track designs. On macOS they're typically at:

```
/Users/<you>/Library/Application Support/OpenRCT2/track/
```

Or inside the OpenRCT2 app bundle itself. Copy any `.td6` file into
`data/sample_rides/` to use as a test fixture. A mine train track is ideal
since that's the ride type we're targeting.

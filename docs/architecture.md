# Architecture

The [README](../README.md) covers what generide is and why. This doc covers how the code is structured for anyone who wants to read or modify it.

## The layered model

generide is built bottom-up as a stack of independent layers. Each layer takes the output of the layer below and turns it into something more structured. Each is independently testable: RLE has no idea what a ride is, TD6 has no idea what RLE is doing underneath it, the `Ride` object has no idea what bit offsets it came from.

```
┌──────────────────────────────────────┐
│  Generator (Phase 4)                 │  GA evolves Ride objects
├──────────────────────────────────────┤
│  Geometry (Phase 2)                  │  Validates a Ride is physically sound
├──────────────────────────────────────┤
│  Segment definitions                 │  Per-piece deltas (forward, sideways,
│  (rct2/segments.py)                  │  elevation, direction)
├──────────────────────────────────────┤
│  Ride / TrackElement dataclasses     │  Pythonic representation
│  (rct2/td6.py)                       │
├──────────────────────────────────────┤
│  TD6 byte layout (rct2/td6.py)       │  Fields at known offsets
├──────────────────────────────────────┤
│  RLE compression (rct2/rle.py)       │  Bytes ↔ bytes
├──────────────────────────────────────┤
│  Raw .td6 file                       │  ~3 KB binary blob
└──────────────────────────────────────┘
```

## Module reference

### `rct2/rle.py`

RCT2's custom run-length encoding. Two functions, no state:

- `decompress(data: bytes) -> bytes`
- `compress(data: bytes) -> bytes`

The encoding: each chunk starts with a control byte. If `c < 128`, the next `c + 1` bytes are literal data. If `c >= 128`, the next byte is repeated `257 - c` times. That's the whole format. Round-trip-tested against a real `.td6` fixture.

### `rct2/td6.py` (in progress)

Translates decompressed bytes into a `Ride` dataclass and back. Field offsets are documented in the [Phase 1 spec](phase1-spec.md). Two main functions:

- `decode(compressed_data: bytes) -> Ride` — handles RLE internally, returns a fully parsed `Ride`
- `encode(ride: Ride) -> bytes` — produces compressed bytes ready to write to disk

Anything after the track-element terminator (entrance/exit positions, scenery) is kept as opaque `remainder` bytes and written back verbatim. This is a deliberate Phase 1 shortcut — see Design decisions below.

### `rct2/segments.py` (planned for Phase 2)

Per-piece geometry deltas: when you place a "25° up" piece pointing east, how does the next piece's position and direction differ from the current one? Ported from kevinburke/rct, with corrections. The data tables in that codebase are correct; the math functions that operate on them are not. Use the tables, re-derive the math.

### `rct2/geometry.py` (planned for Phase 2)

Walks a sequence of track elements and computes per-piece positions. Validates that the track forms a closed circuit, doesn't collide with itself, and stays within map bounds.

## Data flow

A complete read-then-write cycle:

```
.td6 bytes
    │
    │  td6.decode()
    │    ├─ rle.decompress()
    │    ├─ parse header fields at fixed offsets
    │    ├─ parse track elements until 0xFF terminator
    │    └─ stash remainder bytes opaque
    ▼
Ride object  ──── (Phase 2) ────►  validated by geometry.py
    │
    │  td6.encode()
    │    ├─ serialize header fields back to offsets
    │    ├─ serialize track elements + 0xFF terminator
    │    ├─ append remainder bytes verbatim
    │    └─ rle.compress()
    ▼
.td6 bytes  (round-trip target: decompresses to the same bytes as the input)
```

## Design decisions and rationale

**Python over Go.** The reference implementation (kevinburke/rct) is Go. Python wins for this project because the iteration loop on binary format work is faster — interactive REPL exploration of byte patterns beats compile-test cycles. The performance penalty is irrelevant at this scale: a coaster has a few hundred segments, not a few million.

**TD6, not TD4.** TD4 is the RCT1 format. TD6 is the RCT2 / OpenRCT2 format. OpenRCT2 is the target, so TD6.

**Opaque `remainder` bytes.** The Phase 1 round-trip test only requires faithful read/write of the format, not full understanding of every byte. Everything after the track-element terminator gets stored as raw bytes and written back unchanged. This works for round-tripping but is a known limitation for Phase 3: a generated coaster needs real entrance/exit data, which means either parsing this section properly or splicing generated track into a template ride's remainder.

**Mine Train as the starting ride type.** Same choice kevinburke/rct made, so more reference data exists for cross-checking. Once Phase 1 is solid, supporting other ride types is mostly a matter of which track segments are allowed.

**Round-trip first, generation later.** Building bottom-up means each phase has a hard pass/fail criterion before the next one starts. Phase 1: bytes match. Phase 2: computed positions match a known-good ride. Phase 3: the game loads it. Phase 4: the GA produces a coaster a human would actually ride.

## Gotchas

**Renaming the project breaks the venv.** The venv records the absolute path to its Python interpreter. If you `mv` the project directory, the interpreter symlink breaks silently — commands fail with `bad interpreter: ... no such file or directory`. Fix: `rm -rf .venv && python3 -m venv .venv && pip install -r requirements.txt`.

**The last 4 bytes of every `.td6` are a checksum.** Phase 1 ignores it — we strip it on read and don't regenerate it on write. OpenRCT2 will reject files with bad checksums, so Phase 3 needs to compute checksums the game will accept.

**Bit-packed fields hide multiple values in one byte.** Examples: `control_flags` at offset 0x4b packs load type into bits 0-2 plus several boolean flags above; `circuits_and_lift_speed` at 0xa2 packs circuit count into the top 3 bits and lift speed into the bottom 5. Always read these as raw bytes first and unpack into structured fields second.

**kevinburke/rct is a reference, not a transplant donor.** Its TD6 read/write structure is sound. Its geometry math has real bugs: `Advance()` panics on valid input, `cosdeg()` uses `math.Sin` instead of `math.Cos`, collision detection uses bounding boxes instead of per-tile occupancy, `Mutate()` is empty. Read it for structure. Re-derive the math.

## Adding a new phase

Each phase gets its own spec doc in `docs/phaseN-spec.md`. The pattern:

1. Write the spec first. Field tables, byte layouts, function signatures, success criterion.
2. Write the tests against the spec.
3. Write the implementation.
4. Pass.

The spec is the contract. If you find yourself wanting to write code before the spec, the spec isn't clear enough yet.

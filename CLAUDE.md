# generide

## What this project is
A Python tool for generating roller coaster track files for OpenRCT2. Produces `.td6`
files that can be loaded directly into the game. Long-term goal is a genetic algorithm
that evolves interesting coasters; near-term goal is just getting a hand-authored coaster
to load in-game.

## Target game
OpenRCT2 (open source RCT2 reimplementation). Not vanilla RCT2.

## Reference material
- TD6 file format spec: https://github.com/UnknownShadow200/RCTTechDepot-Archive/blob/master/td4.html
- Track segment data (ForwardDelta, SidewaysDelta, ElevationDelta, DirectionDelta):
  ported from https://github.com/kevinburke/rct — see rct2/segments.py
- kevinburke/rct analysis: the TD6 read/write structure is sound but the geometry math
  is broken (Advance() panics, cosdeg() uses math.Sin instead of math.Cos, collision
  detection uses bounding boxes instead of per-tile occupancy, Mutate() is empty)

## Project structure
```
rct2/
  __init__.py
  td6.py        ← TD6 file format read/write (Phase 1)
  geometry.py   ← Track position math, circuit validation (Phase 2)
  segments.py   ← Track piece definitions ported from kevinburke/rct
tests/
  test_td6.py
  test_geometry.py
data/
  sample_rides/ ← Real .td6 files from OpenRCT2 for round-trip testing
```

## Phases
- **Phase 1 (current)** — TD6 round-trip: read a real .td6 file, decode it, re-encode
  it, confirm the bytes match. No generation yet.
- **Phase 2** — Geometry: implement advance_position() correctly with tests.
- **Phase 3** — Hand-author a coaster as a Python list of segments, encode to TD6,
  load in OpenRCT2.
- **Phase 4** — Genetic algorithm.

## Key decisions made
- Python (not Go) for faster iteration on geometry and binary format work
- pytest for testing
- Start with Mine Train ride type (RIDE_MINE_TRAIN = 0x11) — same as kevinburke/rct
- TD6 format not TD4 — targeting RCT2/OpenRCT2, not RCT1

## What "done" looks like for Phase 1
Read a .td6 file from data/sample_rides/, decode it into a Python dataclass,
re-encode it, and assert the output bytes match the input bytes (minus the checksum).

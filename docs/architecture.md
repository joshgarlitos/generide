# Architecture

This document describes how generide moves between raw TD6 files, Python ride objects, validated geometry, and evolved tracks. The [README](../README.md) covers setup and everyday usage.

## Layered model

```text
Evolution                    rct2/evolution.py
  tournament selection, elitism, generations
        ↕
Genome operations + fitness rct2/mutations.py, rct2/fitness.py
  segment-list mutation, crossover, repair, proxy scoring
        ↕
Ride generation             rct2/generate.py
  segment lists become Ride objects with stations and entrances
        ↕
Geometry                    rct2/segments.py, rct2/geometry.py
  movement, occupancy, bounds, closure, validation
Construction rules          rct2/construction.py
  slope, bank, lift, energy, and export validity
        ↕
TD6 model and serialization rct2/td6.py
  headers, elements, entrances, scenery
        ↕
Compression and integrity   rct2/rle.py, rct2/checksum.py
        ↕
Checksummed .td6 file
```

Each layer can be tested independently. A geometry failure does not require debugging compression, and a mutation failure does not require loading OpenRCT2.

## Core data flow

### Reading an existing ride

```text
.td6 bytes
  → split and verify 4-byte checksum
  → RLE-decompress payload
  → parse fixed header fields
  → parse 2-byte track elements until 0xFF
  → parse 6-byte entrance and exit records until 0xFF
  → preserve remaining scenery bytes
  → Ride
```

Use `td6.load(path)` for this complete operation. Lower-level `td6.decode()` accepts compressed content without the trailing checksum.

### Writing a generated ride

```text
list[int] segment genome
  → geometry validation
  → TrackElement objects
  → template-backed Ride header and vehicle data
  → calculated footprint and station entrances
  → TD6 serialization
  → RLE compression
  → checksum append
  → .td6 file
```

Use `generate.generate_ride()` to construct the `Ride` and `td6.save()` to write it.

### Evolving a ride

`evolution.evolve()` starts from a seed segment list, creates a population, scores each individual, selects parents by tournament, applies crossover and mutation, attempts circuit repair, and preserves the best individuals through elitism. The exported genome remains a plain list of TD6 segment IDs.

## Module reference

### `rct2/rle.py`

Implements RCT2's custom run-length compression. RLE has multiple valid encodings for the same decompressed data, so format round-trip tests compare decompressed bytes.

### `rct2/checksum.py`

Computes the 32-bit TD6 checksum over compressed file content using the RCT2 rolling sum, bit rotation, and TD6 magic value. `append()` and `strip()` operate on complete file bytes.

### `rct2/td6.py`

Defines `Ride`, `TrackElement`, and `Entrance`. It parses named header fields while retaining the raw header so unparsed bytes survive round trips. Scenery remains opaque. The primary file APIs are:

- `load(path) -> Ride`
- `save(ride, path) -> None`
- `decode(compressed) -> Ride`
- `encode(ride) -> bytes`

### `rct2/segments.py`

Stores immutable geometry for the Mine Train segment types currently supported. Each definition includes endpoint movement, elevation, heading change, and occupied tile footprint. Unknown IDs fail explicitly.

### `rct2/geometry.py`

Provides position advancement, complete-track tracing, occupancy, bounds, collision reporting, and `validate_track()`. Validation returns structured issue codes rather than a bare boolean.

### `rct2/generate.py`

Builds generated rides using a real Mine Train file as a template for vehicle and unparsed header data. It replaces the track, calculates dimensions, adds entrance and exit records, and leaves scenery empty.

### `rct2/construction.py`

Combines geometry with slope, bank, chain-lift, and estimated-energy rules. Generation, evolution, fitness, and CLI export use its structured result as the shared definition of a construction-valid ride.

### `rct2/mutations.py`

Implements insert, delete, replace, swap, mutation, crossover, random-track creation, and circuit repair. Slope and banked pieces are inserted as compatible sequences to avoid combinations OpenRCT2 rejects.

### `rct2/fitness.py`

Contains reusable checks for slope state, bank state, turns, elevation, and estimated energy, plus `ProxyFitness` and `WeightedProxyFitness`. The proxy rewards geometric qualities and penalizes invalid or impractical tracks. It does not reproduce OpenRCT2 ride ratings.

### `rct2/evolution.py`

Owns `Individual`, `Population`, evolution statistics, population initialization, tournament selection, elitism, and the main evolution loops.

## Design decisions

**Python over Go.** Iteration speed matters more than raw throughput for a few hundred segments per ride.

**TD6 over TD4.** OpenRCT2 and RCT2 are the targets. TD4 is the RCT1 format.

**Template-backed generation.** Generated rides reuse a known-good Mine Train header and vehicle data. This narrows current generation to one ride type while avoiding guesses about unrelated TD6 fields.

**Opaque data by default.** Unparsed header bytes and scenery survive round trips. Fields become structured only when generation needs to control them.

**Segment lists as genomes.** A list of integer IDs maps directly to TD6 track elements, stays easy to inspect, and works with straightforward mutation and crossover operators.

**Proxy fitness before game ratings.** Geometry-based scoring made it possible to prove the GA and export pipeline without automating the game. It is an intermediate signal, not the final definition of ride quality.

## Known limitations

- Only the initial Mine Train segment set has complete geometry support.
- Generated rides depend on a template TD6 for header and vehicle data.
- Scenery is not generated.
- Collision checks operate on exact occupied cells rather than full clearance volumes.
- Energy is estimated rather than simulated with OpenRCT2 physics.
- Fitness does not yet use the game's excitement, intensity, and nausea ratings.
- Mutations keep their own copies of the construction rules and insert slopes and banked turns only from fixed pre-built sequences; steep slope pieces (0x05, 0x07, 0x08) are defined but unreachable by any mutation.
- Evolution uses the global `random` module with no seed, so runs are not reproducible.

## Testing

The test suite covers binary round trips, checksum reproduction, real-fixture geometry and construction validation, generation, mutation, fitness behavior, population management, and evolution. Run it with:

```bash
pytest
```

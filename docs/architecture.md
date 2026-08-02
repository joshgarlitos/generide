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

Defines `Ride`, `TrackElement`, and `Entrance`. It parses named header fields while retaining the raw header so unparsed bytes survive round trips. Scenery remains opaque.

Named fields include the ride stats the game measured on its own test lap: speeds, ride length, vertical and lateral g, inversions, drops, highest drop height, and total air time, alongside the three ratings. Properties convert the stored bytes into displayed units. Offsets and scale factors are taken from OpenRCT2's `TD6Track` struct and T6 exporter rather than inferred from sample files; the evidence for each is recorded in [phase1-spec.md](phase1-spec.md). Those stats are what make calibration possible without running the game, since any real exported design carries the ratings the game assigned it.

The primary file APIs are:

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

Combines geometry with slope, bank, chain-lift, and estimated-energy rules. Generation, evolution, fitness, and CLI export use its structured result as the shared definition of a construction-valid ride. It also exposes `energy_stall_index`, a completability screen that sits deliberately outside that result — see "Buildable is not runnable" below.

### `rct2/mutations.py`

Implements insert, delete, replace, swap, mutation, crossover, random-track creation, and circuit repair. At each insertion or replacement point it asks `construction.py` which segments are legal given the current slope and bank state, then picks from what comes back, so offspring stay buildable without the mutation code holding its own copy of the rules. Every defined piece is reachable this way, including the steep slopes.

### `rct2/fitness.py`

Contains reusable checks for slope state, bank state, turns, elevation, and estimated energy, plus the proxy and physics fitness classes. `WeightedProxyFitness` holds the entire proxy scoring implementation with every reward and penalty exposed as a constructor weight, and `ProxyFitness` is that class with the tuned defaults, so there is only one copy of the scoring rules to keep correct. The proxy rewards geometric qualities and penalizes tracks that are invalid, impractical, or would stall. It does not reproduce OpenRCT2 ride ratings; `PhysicsFitness` scores approximate ones from `physics.py`, but those weights are uncalibrated.

### `rct2/physics.py`

Walks the track with an energy-method velocity model in meters and seconds, collecting maximum speed, drops, g-forces, airtime, and whether the train completes the circuit. `rate()` maps those stats to approximate excitement, intensity, and nausea through a weights table shaped like OpenRCT2's per-ride-type contributions. It imports `construction.py` and never the reverse, and it is the authority on completability.

### `rct2/evolution.py`

Owns `Individual`, `Population`, evolution statistics, population initialization, tournament selection, elitism, and the main evolution loops.

## Design decisions

**Python over Go.** Iteration speed matters more than raw throughput for a few hundred segments per ride.

**TD6 over TD4.** OpenRCT2 and RCT2 are the targets. TD4 is the RCT1 format.

**Template-backed generation.** Generated rides reuse a known-good Mine Train header and vehicle data. This narrows current generation to one ride type while avoiding guesses about unrelated TD6 fields.

**Opaque data by default.** Unparsed header bytes and scenery survive round trips. Fields become structured only when generation needs to control them.

**Segment lists as genomes.** A list of integer IDs maps directly to TD6 track elements, stays easy to inspect, and works with straightforward mutation and crossover operators.

**Proxy fitness before game ratings.** Geometry-based scoring made it possible to prove the GA and export pipeline without automating the game. It is an intermediate signal, not the final definition of ride quality.

**Buildable is not runnable.** `validate_construction` answers whether OpenRCT2 would reject a track, and nothing more. Whether a train actually gets around it is a separate question, because the two genuinely come apart: `create_simple_circuit()`, the seed every evolution run starts from, is a flat liftless loop the game builds without complaint and no train can complete. Making a stall a construction issue would mark that seed illegal and start the GA from an invalid individual.

So completability lives outside `.valid`. `rct2/physics.py` is the authority — it walks real arc lengths per segment. `construction.energy_stall_index` is a cheap conservative screen carrying the same energy accounting in RCT2 height units, for callers like `ProxyFitness` that must stay physics-free. The screen exists to be pessimistic in the safe direction: over a corpus of evolved, random, and fixture tracks it never passed a track the simulation stalls, at the cost of rejecting a few the simulation completes.

The two models cannot import each other (`physics` depends on `construction`), so a test pins the shared constants across the boundary rather than letting them drift.

## Known limitations

- Only the initial Mine Train segment set has complete geometry support.
- Generated rides depend on a template TD6 for header and vehicle data.
- Scenery is not generated.
- Collision checks operate on exact occupied cells rather than full clearance volumes.
- Energy is estimated rather than simulated with OpenRCT2 physics.
- `construction.energy_stall_index` charges a flat friction cost per segment while `physics.simulate` charges per meter of arc length, so the screen overcharges straights and undercharges wide turns. The real Mine Train fixture clears it by only ~0.6 segments of coasting; a legitimate ride with a longer run-in to its lift hill could be flagged as stalling when it would not. Sharing one arc-length model between the two would remove the discrepancy.
- Fitness does not use the game's excitement, intensity, and nausea ratings. `PhysicsFitness` produces approximate ones, but the weights behind them are placeholders that have never been checked against OpenRCT2.
- `missing_lift_penalty` in proxy scoring can never fire, because the lift set it checks against is derived from the first hill it is checking. See issue #17.

## Testing

The test suite covers binary round trips, checksum reproduction, real-fixture geometry and construction validation, generation, mutation, fitness behavior, population management, and evolution. Run it with:

```bash
pytest
```

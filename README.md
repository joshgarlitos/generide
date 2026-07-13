# generide

**Procedurally generating roller coasters that actually run in OpenRCT2.**

generide is a Python tool for reading, validating, generating, and evolving RollerCoaster Tycoon 2 (RCT2) track designs. It works directly with the game's `.td6` format and produces checksummed files that can be loaded into [OpenRCT2](https://openrct2.io).

I started this project as a way to explore how I could generate new rides for RCT2 and get them running in the game. That turned into a much more interesting problem involving binary file formats, three-dimensional track geometry, construction rules, approximate physics, and a genetic algorithm that has to produce something the game will accept.

Today, generide can evolve a Mine Train layout, export it, and run it in OpenRCT2. The next step is teaching it to optimize for the game's actual excitement, intensity, and nausea ratings instead of geometric stand-ins.

## Why this is an interesting problem

A coaster is not just a random list of track pieces. It has to form a closed circuit, avoid colliding with itself, stay inside its footprint, transition cleanly between slopes and banks, put a chain lift where the train needs one, and preserve enough energy to finish the course.

There is also a 1999-era binary format between the Python code and the game. TD6 files are compressed, densely packed, and protected by a custom checksum. Some fields are understood, while others still need to survive a round trip byte for byte even if generide does not interpret them yet.

That gives the project a useful stack of problems to solve:

```text
genetic algorithm
       ↓
segment genome and construction rules
       ↓
3D geometry, occupancy, and validation
       ↓
TD6 serialization, compression, and checksum
       ↓
OpenRCT2
```

The result has to make sense at every layer. A high fitness score is not useful if the circuit does not close, and a valid Python object is not useful if the game rejects the file.

## What works now

- Reads and writes real TD6 track-design files.
- Preserves unknown header data during round trips instead of discarding bytes it does not understand.
- Implements RCT2's run-length compression and TD6 checksum.
- Reconstructs tracks in three dimensions, including per-tile occupancy.
- Checks closure, collisions, bounds, slope and bank transitions, chain lift placement, and estimated energy.
- Builds new Mine Train rides with stations, entrances, exits, and valid checksums.
- Evolves tracks using mutation, crossover, tournament selection, and elitism.
- Supports seeded runs so an interesting result or failure can be reproduced.
- Has 119 passing tests, including regression tests against real OpenRCT2 exports.

Generated and evolved tracks have been placed and run in OpenRCT2. Fitness still uses geometric proxies such as length, elevation changes, turn balance, and segment variety. It does not yet reproduce the game's ride-rating calculations.

## Try it

The project currently targets Python 3 and uses `pytest` as its only dependency.

```bash
git clone https://github.com/joshgarlitos/generide.git
cd generide

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Generate the hand-authored test circuit:

```bash
python generate_coaster.py simple_coaster.td6
```

Run the genetic algorithm and export its best valid track:

```bash
python evolve_coaster.py \
  --generations 100 \
  --population 50 \
  --rng-seed 123 \
  --verbose \
  --output evolved.td6
```

Both commands use `data/sample_rides/manic_miner_test.td6` as a template for the Mine Train vehicle and header data. To use the result, copy the generated file to `~/Documents/OpenRCT2/track/`, open a Mine Train ride in OpenRCT2, and select the design from the Track Designs menu.

## How evolution works

Each coaster is represented as a list of TD6 segment IDs. That list is both a compact genetic representation and a direct description of the track written to the final file.

The evolutionary loop creates a population, scores each candidate, selects parents through tournament selection, applies crossover and mutation, and carries the strongest candidates into the next generation. Mutations can insert, delete, replace, swap, and recombine pieces. Slope and bank transitions are currently inserted as complete legal sequences because OpenRCT2 treats them as stateful construction operations.

The proxy fitness function rewards coaster-like qualities while applying strong penalties to designs that cannot be built or completed. Construction validation is shared across generation, scoring, and export so those parts of the program use the same definition of a valid ride.

The current mutation system is intentionally conservative. It can build working tracks, but it cannot yet reach every supported piece, including steep drops. The next mutation design will ask the validator which pieces are legal at a specific point instead of choosing from a small collection of pre-built sequences.

## Development approach

I use AI coding tools throughout the project for research, implementation, debugging, and review. The useful part is not how much code they can produce. It is building a workflow where their output can be checked.

For generide, that means testing assumptions against real exported rides, separating binary parsing from geometry and evolution, keeping runs reproducible, and writing regression tests for failures found in the game. One early example was a reference implementation whose file structure was useful but whose geometry contained a sine/cosine bug. Treating the reference as evidence rather than authority kept that bug out of this implementation.

The [devlog](docs/devlog.md) records those decisions and dead ends in more detail, including why round-trip tests compare decompressed data, how the construction rules emerged from failed in-game tests, and what changed to make evolutionary runs reproducible.

## Project structure

```text
rct2/
  checksum.py       TD6 checksum computation
  rle.py            RCT2 run-length compression
  td6.py            TD6 parsing, serialization, loading, and saving
  segments.py       Track-piece geometry and occupancy definitions
  geometry.py       Position tracing, bounds, collision, and validation
  construction.py   Shared slope, bank, lift, energy, and geometry rules
  generate.py       Ride construction from Python segment lists
  mutations.py      Mutation, crossover, random tracks, and repair
  fitness.py        Proxy fitness and track-rule checks
  evolution.py      Population management and evolution loops
tests/               Unit and fixture-based regression tests
data/sample_rides/   Real OpenRCT2 exports used as fixtures and templates
```

For a deeper look, see the [architecture guide](docs/architecture.md), [roadmap](docs/roadmap.md), and [development log](docs/devlog.md).

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| 1 | Read and write real TD6 files faithfully | Complete |
| 2 | Reconstruct and validate track geometry | Complete |
| 3 | Author a coaster in Python and run it in OpenRCT2 | Complete |
| 4 | Evolve constrained coasters with a genetic algorithm | In progress |

The immediate priorities are to benchmark evolution against random search, expand mutation beyond fixed slope and bank sequences, and connect candidate evaluation to real OpenRCT2 ride ratings. The longer-term goal is to accept constraints such as footprint, cost, excitement, intensity, and nausea, then generate a working ride that fits them.

## References

- [OpenRCT2](https://openrct2.io)
- [TD6 format notes](https://github.com/UnknownShadow200/RCTTechDepot-Archive/blob/master/td4.html)
- [kevinburke/rct](https://github.com/kevinburke/rct)

## License

generide is licensed under the [GNU General Public License v3.0](LICENSE).

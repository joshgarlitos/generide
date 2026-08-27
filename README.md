# generide

**Evolving playable roller coasters for RollerCoaster Tycoon 2.**

generide is a Python tool for reading, validating, generating, and evolving RollerCoaster Tycoon 2 (RCT2) track designs. It works directly with the game's `.td6` format and produces checksummed files that can be loaded into [OpenRCT2](https://openrct2.io).

I started this project as a way to explore how I could generate new rides for RCT2 and get them running in the game. That turned into a much more interesting problem involving binary file formats, three-dimensional track geometry, construction rules, approximate physics, and a genetic algorithm that has to produce something the game will accept.

Today, generide can evolve a Mine Train layout, export it, and run it in OpenRCT2. It scores candidates with OpenRCT2's own excitement, intensity, and nausea calculation, transcribed into Python, and it can hand a finished track to a real headless copy of the game to hear what the game itself says about it.

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
- Asks the validator which pieces are legal at each point during mutation, so the full piece vocabulary is reachable, including steep drops.
- Simulates the ride with an energy-method velocity model to get speed, drops, g-forces, and airtime, and reports whether a train can finish the circuit.
- Scores rides with OpenRCT2's real rating calculation, transcribed from the game's source with its integer arithmetic intact, including the requirement thresholds that halve every rating when a ride is too slow or its drops too small.
- Evolves a part-based genome as well as a flat one, so crossover cannot cut a lift hill in half, and carries the hill as a mandatory part rather than something the search has to stumble on.
- Compares search methods through a benchmark harness at equal evaluation budgets, with a hard buildable-and-completed gate and reliability and diversity tracked alongside quality.
- Builds a track piece by piece in a real headless OpenRCT2 and reads the game's own ratings back, so a benchmark run can be judged by the game rather than by our model of it.
- Renders a track as a top-down SVG plan shaded by height, and an evolution run as a fitness curve, so a result can be looked at without loading the game.
- Supports seeded runs so an interesting result or failure can be reproduced.
- Has 369 passing tests, including regression tests against real OpenRCT2 exports.

Generated and evolved tracks have been placed and run in OpenRCT2. The default fitness still scores geometric proxies such as length, elevation changes, turn balance, and segment variety. The physics fitness turns simulated ride stats into excitement, intensity, and nausea, and it can use either the old fitted weights or the transcribed calculation from OpenRCT2's source.

The headless oracle is built and the benchmark harness can call it, though the gap between what it reports and what the game stored for a known design is not yet explained. See the [research plan](docs/research-plan.md) for where that stands.

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

Evolve a coaster and export the best track found:

```bash
python evolve_coaster.py \
  --fitness physics \
  --generations 150 \
  --population 50 \
  --rng-seed 123 \
  --output evolved.td6
```

`--fitness physics` scores candidates on simulated ride stats (speed, drops, g-forces) rather than track geometry alone, and is the setting that produces rides with actual drops instead of flat loops. Expect this to take one to two minutes; shorter runs (fewer generations, smaller population) finish faster but tend to settle on shorter, tamer tracks. Reruns with the same `--rng-seed` reproduce the same track exactly, so a seed worth keeping is worth writing down.

A few flags worth knowing:

- `--rng-seed N` — reproduce a specific run. Omit it for a random seed, which the CLI prints so you can rerun it later.
- `--station-length N` — platform length in tiles (default 6, minimum 2). Only applies to the generated seed circuit, not a `--seed <path>` track.
- `--target-excitement MIN:MAX`, `--target-intensity MIN:MAX`, `--target-nausea MIN:MAX` — with `--fitness physics`, aim for a specific rating range instead of maximizing excitement, e.g. `--target-intensity 4:7`. Our rating model is not yet calibrated against the game's real ratings (see the roadmap), so treat these as rough knobs rather than exact targets for now.
- `--verbose` — print progress each generation.
- `--render` — also write an SVG plan of the best track and a fitness curve for the run, next to the `.td6`.

To compare search methods rather than produce one ride, use the benchmark harness:

```bash
python run_benchmark.py --methods random ga ga_parts --seeds 25 --evaluations 2000
```

Every method gets the same number of track evaluations, and results save with full segment lists so a run can be re-judged later without re-running the search. On a machine with OpenRCT2 installed, `--oracle` judges the winning tracks in the real game and `--rescore <results.json>` does the same to a saved run.

Run `python evolve_coaster.py --help` for the full list.

Both commands use `data/sample_rides/manic_miner_test.td6` as a template for the Mine Train vehicle and header data. To use the result, copy the generated file into OpenRCT2's `track` folder, restart the game if it is already open, then start a Mine Train ride and pick the design from the Track Designs menu. The designs are saved against that ride type, so they will not show up under any other coaster.

The `track` folder lives inside OpenRCT2's user directory, which differs by platform:

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/OpenRCT2/track/` |
| Windows | `%USERPROFILE%\Documents\OpenRCT2\track\` |
| Linux | `~/.config/OpenRCT2/track/` |

## How evolution works

Each coaster is represented as a list of TD6 segment IDs. That list is both a compact genetic representation and a direct description of the track written to the final file.

The evolutionary loop creates a population, scores each candidate, selects parents through tournament selection, applies crossover and mutation, and carries the strongest candidates into the next generation. Mutations can insert, delete, replace, swap, and recombine pieces.

Slope and banking are stateful in RCT2. A piece that exits a climb is only legal if the track is already climbing, so a mutation that drops one in at random usually produces something the game refuses to build. Mutations handle that by asking the validator which pieces are legal at the chosen point and picking from what it returns, which keeps offspring buildable while leaving the whole piece vocabulary reachable, steep drops included. An earlier version inserted slopes and banked turns only as complete pre-built sequences, which was safe but meant some pieces could never appear at all.

The proxy fitness function rewards coaster-like qualities while applying strong penalties to designs that cannot be built or completed. Construction validation is shared across generation, scoring, and export so those parts of the program use the same definition of a valid ride.

Buildable and runnable are tracked separately, because they genuinely come apart. A flat loop with no chain lift is something OpenRCT2 will let you build and no train can get around. Construction validation answers only the first question, and a cheap energy screen alongside it catches trains that would run out of speed, so evolution stops rewarding tracks that stall.

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
  physics.py        Ride simulation and stats
  ratings.py        OpenRCT2's rating calculation, transcribed
  fitness.py        Proxy fitness, physics fitness, and track-rule checks
  evolution.py      Population management and evolution loops
  benchmark.py      Method comparison at equal evaluation budgets
  oracle.py         Headless OpenRCT2 driver for the game's own ratings
  render.py         SVG plan views and fitness curves
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

Evolution has been benchmarked against random search and wins clearly, and mutation now reaches the full piece vocabulary. Rating candidates is no longer a matter of fitted guesses, because the game's own calculation is transcribed in `rct2/ratings.py`.

The immediate priority is closing the gap between the oracle's ratings and the ones the game recorded for a design it shipped. Until that is understood, every method comparison is scored by the same model the methods are searching against, which measures the model as much as the method. The longer-term goal is to accept constraints such as footprint, cost, excitement, intensity, and nausea, then generate a working ride that fits them.

## References

- [OpenRCT2](https://openrct2.io)
- [TD6 format notes](https://github.com/UnknownShadow200/RCTTechDepot-Archive/blob/master/td4.html)
- [kevinburke/rct](https://github.com/kevinburke/rct)

## License

generide is licensed under the [GNU General Public License v3.0](LICENSE).

`rct2/ratings.py` contains the ride rating calculation transcribed from [OpenRCT2](https://github.com/OpenRCT2/OpenRCT2), Copyright (c) 2014-2026 OpenRCT2 developers, which is also GPL-3.0. That module carries its own attribution notice naming the specific source files. Elsewhere the project reads OpenRCT2's source as documentation for the game's behaviour, for example the drop-counting rule in `rct2/physics.py`, without copying its code.

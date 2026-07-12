# generide

**Procedurally generating roller coasters for OpenRCT2.**

generide is a Python tool that reads, validates, generates, and evolves RollerCoaster Tycoon 2 track designs. It produces checksummed `.td6` files that OpenRCT2 can load directly.

The project started as a binary-format exercise: decode a real ride, encode it again, and prove the bytes survive. It now has an end-to-end generation pipeline and a working genetic algorithm. Evolved Mine Train coasters can be exported, placed, and run in OpenRCT2.

## Current status

- TD6 read/write, RLE compression, and checksum generation are complete.
- Track geometry closes a real 89-piece Mine Train exactly and validates occupancy and bounds.
- Python-authored tracks export with stations, entrances, exits, and valid checksums.
- The genetic algorithm evolves closed tracks with slope, banking, lift-hill, collision, energy, and footprint constraints.
- Fitness currently uses geometric proxies. It does not yet optimize OpenRCT2's actual excitement, intensity, and nausea ratings.
- The test suite contains 118 passing tests.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Generate the hand-authored test circuit:

```bash
python generate_coaster.py simple_coaster.td6
```

Run a short evolution and export its best track:

```bash
python evolve_coaster.py \
  --generations 100 \
  --population 50 \
  --verbose \
  --output evolved.td6
```

Both commands use `data/sample_rides/manic_miner_test.td6` as the default Mine Train template. Generated `.td6` files can be placed in the OpenRCT2 track-design directory and selected in game.

## How it fits together

```text
.td6 file
   ↕ checksum.py + rle.py
compressed TD6 data
   ↕ td6.py
Ride and TrackElement objects
   ↕ segments.py + geometry.py
validated track geometry
   ↕ generate.py
loadable generated ride
   ↕ mutations.py + fitness.py + evolution.py
evolved coaster
```

The genome is a list of TD6 segment IDs. Mutation operators insert, delete, replace, and recombine track pieces while preserving the station and treating slope and bank transitions as valid sequences. A proxy fitness function rewards length, elevation changes, turn balance, and segment variety while heavily penalizing invalid geometry and physics.

## Project layout

```text
rct2/
  checksum.py    TD6 checksum computation
  rle.py         RCT2 run-length compression
  td6.py         TD6 parsing, serialization, load, and save
  segments.py    Track-piece geometry and occupancy definitions
  geometry.py    Position tracing, bounds, collision, and validation
  construction.py Shared slope, bank, lift, energy, and geometry validation
  generate.py    Ride construction from Python segment lists
  mutations.py   Mutation, crossover, random tracks, and repair
  fitness.py     Proxy fitness and track-rule checks
  evolution.py   Population management and evolution loops
tests/            Unit and fixture-based regression tests
data/sample_rides/ Real OpenRCT2 exports used as fixtures and templates
```

See [docs/architecture.md](docs/architecture.md) for the module contracts and data flow, [docs/roadmap.md](docs/roadmap.md) for current priorities, and [docs/devlog.md](docs/devlog.md) for the development record.

## Roadmap

| Phase | Goal | Status |
|---|---|---|
| 1 | Read and write real TD6 files faithfully | Complete |
| 2 | Reconstruct and validate track geometry | Complete |
| 3 | Author a coaster in Python and run it in OpenRCT2 | Complete |
| 4 | Evolve constrained coasters with a genetic algorithm | In progress |

Phase 4's engine works, but the original success criterion is broader: optimize toward requested OpenRCT2 ride-rating ranges, reliably satisfy user-supplied bounds, and demonstrate improvement over a random baseline.

## References

- [TD6 format notes](https://github.com/UnknownShadow200/RCTTechDepot-Archive/blob/master/td4.html)
- [kevinburke/rct](https://github.com/kevinburke/rct)
- [OpenRCT2](https://openrct2.io)

## License

Copyright (C) 2026 Josh Garlitos

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

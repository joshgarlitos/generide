# rct2-coaster-gen

A Python tool for generating and authoring roller coaster track files for OpenRCT2.

Produces `.td6` files that can be loaded directly into OpenRCT2.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running tests

```bash
pytest
```

## Project phases

- **Phase 1** — TD6 file format: read and write `.td6` files correctly
- **Phase 2** — Geometry: track segment position math, circuit validation
- **Phase 3** — Manual authoring: write a coaster in Python, load it in-game
- **Phase 4** — Generation: genetic algorithm to evolve coasters

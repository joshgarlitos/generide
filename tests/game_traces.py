"""Recorded traces of the real game running a track, for checking physics.py.

Each file in tests/data/game_traces/ is one `oracle.score_track(...,
trace_every_ticks=5)` call against OpenRCT2 v0.5.3: the track, which pieces
carried the chain lift, and the lead car's reading every 5 ticks. They are
recorded rather than re-run because the test suite never launches the game.
Re-record with the snippet in docs/headless-oracle-spike.md.
"""

import json
from pathlib import Path

TRACE_DIR = Path(__file__).parent / "data" / "game_traces"

# The game's velocity unit: the simulator's metre per second is 65536 of them.
VELOCITY_UNITS_PER_MS = 65536


def load(name: str) -> dict:
    return json.loads((TRACE_DIR / f"{name}.json").read_text())

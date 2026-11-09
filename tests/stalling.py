"""Tracks that stall, for tests of how a stall is reported.

The flat starter loop (`create_simple_circuit()`) used to be the stalling
example. It is not any more: the game completes it (recorded in
tests/data/game_traces/simple_circuit.json, speed falling from 2.05 to 1.72
m/s over a lap), and the simulator now agrees. A flat train only stalls once
it has coasted far enough for drag to take its last 1.2 m/s, about 35 pieces.
"""

from rct2.generate import create_simple_circuit

# A station and 60 flat pieces: stalls on piece 35, with nothing to close the
# circuit. For views and warnings that only need "the train stops here".
STALLING_STRIP = [0x02, 0x01] + [0x00] * 60

# A closed, construction-valid flat loop long enough to stall (on piece 60 with
# the exported two-car train). Needs a 31-tile-wide site.
STALLING_LOOP_STATION = 30


def stalling_loop() -> list[int]:
    return create_simple_circuit(station_length=STALLING_LOOP_STATION)

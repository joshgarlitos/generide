"""Coasting: how a train's speed changes along unpowered track.

The one walk both `physics.py` (the ride simulation) and
`construction.energy_stall_index` (the cheap screen `ProxyFitness` uses) take
over a track, so the screen cannot drift from the simulation. It imports
neither of them: construction.py cannot import physics.py, and this module is
the part they share. Nothing here knows about ratings, g-forces or fitness.

Unit conventions: distances in metres, heights in RCT2 height units converted
once at the boundary by HEIGHT_UNIT_M, speed in m/s, time in seconds.
"""

import math
from dataclasses import dataclass
from typing import Optional

from rct2.segments import Segment


# Horizontal scale, calibrated against the ride length OpenRCT2 reports
# (issue #60). It was 3.0, which read about 30% short on every track tried.
# The per-piece geometry was never the problem: the shortfall stayed within
# one percent of a fixed multiplier across a 0.22 and a 0.57 fraction of turn
# length, which a wrong turn model could not do and a wrong scale does.
#
# Solving TILE_M so the simulated length equals the game's, per track:
#   manic_miner_test.td6 (header, 691 m)             -> 4.379
#   create_hill_circuit() seed (live oracle, 183 m)  -> 4.342
# 4.36 is the midpoint: -0.4% and +0.4% on those two. Two paired
# measurements is thin. Re-run the fit with more `oracle.score_track()`
# readings before trusting the last decimal.
#
# This is a calibration, not a survey: the "meters" here were never real
# meters. The vertical scale (HEIGHT_UNIT_M) is independent and unchanged:
# drop count and highest drop match the game exactly on the fixture.
TILE_M = 4.36
HEIGHT_UNIT_M = 0.75
GRAVITY = 9.81
LIFT_SPEED_MS = 2.2  # Mine Train chain lift, roughly 5 mph
MIN_SPEED_MS = 1.0  # below this off-lift, the train stalls
# Drag, taken from the game rather than fitted (OpenRCT2 v0.5.3,
# src/openrct2/ride/Vehicle.TrackMotion.cpp UpdateTrackMotion, and
# Vehicle.cpp GetAccelerationDecrease2). On every tick the game takes this off
# the train's velocity, in its own integer units:
#
#   velocity / 4096                              (a term in the speed)
#   ((velocity >> 8) ** 2 >> 4) / total_mass     (a term in the speed squared)
#
# The simulator's metre per second is 65536 of those units and a tick is
# 1/40 s, so the same two terms in m/s^2 are
#
#   LINEAR_DRAG * v + QUADRATIC_DRAG * v^2 / total_mass
#
# Read straight off the game's own log: on flat track at 783k units the seed
# circuit lost 357 units a tick, and the formula with 7 cars (mass 3500) gives
# 191 + 166 = 357 (tests/test_game_traces.py pins this). The constant friction
# this replaces charged 0.07 m/s^2 at every speed: about right at 4 m/s, six
# times too small at 18 m/s, which let evolved rides coast for a hundred pieces
# and then stall in the player's park.
GAME_TICKS_PER_S = 40
GAME_VELOCITY_UNITS_PER_MS = 65536
LINEAR_DRAG = GAME_TICKS_PER_S / 4096
QUADRATIC_DRAG = GAME_TICKS_PER_S * GAME_VELOCITY_UNITS_PER_MS / (256**2 * 16)
# The game weighs each car 500 (read off car.mass on the Mine Train), with no
# riders aboard. A train of two cars is what evolve_coaster.py exports (1 train,
# 2 cars per train in the .td6 header), so it is what the player's ride runs.
# The headless oracle cannot set the car count (ridesetvehicle rejects every
# argument tried) and runs the game's default of 7, which weighs 3.5 times as
# much and so loses far less speed to the squared drag. A ride the oracle
# passes can still stall in the player's park for that reason.
CAR_MASS = 500
DEFAULT_TRAIN_CARS = 2
# The distance a piece costs in drag is not the piece's length in TILE_M. TILE_M
# is calibrated to the ride length the game reports (a statistic), but the game
# moves a train along a flat tile in about 8 ticks, which at 11.5 m/s is 2.4 m,
# not 4.36. Fitted to the two recorded traces by minimising the speed error
# along the ride: 0.65 is best for the seed circuit (0.5% mean error), 0.5 for
# the 80-piece ride (6% mean error), 0.6 sits between and keeps both near 5%.
# Gravity needs no such scale because it works on height, not distance. Why the
# game covers more track per tick than its source formula gives is not
# explained here; this is a measured scale, not a derived one.
DRAG_LENGTH_SCALE = 0.6
# Sub-steps used to integrate drag across one piece, since a piece spans a wide
# range of speeds on a drop.
DRAG_SUBSTEPS = 8


@dataclass(frozen=True)
class SegmentGeometry:
    length_m: float
    radius_m: Optional[float]  # None for straight pieces


def segment_length(segment: Segment) -> SegmentGeometry:
    """Approximate arc length and turn radius for a segment.

    Radii come from the footprint size of the known turn shapes; unknown
    shapes fall back to a straight piece so the GA never crashes here.
    """
    rise_m = abs(segment.elevation_delta) * HEIGHT_UNIT_M
    if segment.direction_delta == 0:
        run_m = max(1, abs(segment.forward_delta)) * TILE_M
        return SegmentGeometry(length_m=math.hypot(run_m, rise_m), radius_m=None)

    # Turn radius by displacement shape: 5-tile quarter turns (forward=2,
    # right=3) curve at ~2.5 tiles, 3-tile turns (forward=1, right=2) at ~1.5.
    # These set the arc length. They no longer feed lateral g, which comes
    # from the game's per-piece table (LATERAL_FACTOR). An earlier fit tried to
    # recover the radius from lateral g readings, and found implied radii of
    # 0.83-2.0 tiles with no single value fitting; that spread was the
    # quantization in the readings, not the radius (issue #41).
    shape = (abs(segment.forward_delta), abs(segment.right_delta))
    radius_tiles = {(2, 3): 2.5, (1, 2): 1.5}.get(shape)
    if radius_tiles is None:
        # Helices and anything unrecognized: estimate from sideways reach.
        radius_tiles = max(1.0, abs(segment.right_delta) / 2)
    radius_m = radius_tiles * TILE_M
    arc_m = abs(segment.direction_delta) * (math.pi / 2) * radius_m
    return SegmentGeometry(length_m=math.hypot(arc_m, rise_m), radius_m=radius_m)


def drag_deceleration(speed_ms: float, train_mass: float) -> float:
    """What the game takes off a train's speed each second, in m/s^2."""
    deceleration = LINEAR_DRAG * speed_ms
    if train_mass:
        deceleration += QUADRATIC_DRAG * speed_ms**2 / train_mass
    return deceleration


def coast(speed: float, dz_m: float, length_m: float, train_mass: float) -> float:
    """Speed after an unpowered piece: gravity over the whole piece, drag in steps."""
    v_sq = speed**2 - 2 * GRAVITY * dz_m
    drag_m = length_m * DRAG_LENGTH_SCALE
    # Drag works on speed, which changes along the piece, so spend it in
    # equal slices of the length using the speed the train has by then.
    for _ in range(DRAG_SUBSTEPS):
        v_now = math.sqrt(max(0.0, v_sq))
        v_sq -= 2 * drag_deceleration(v_now, train_mass) * drag_m / DRAG_SUBSTEPS
    return math.sqrt(max(0.0, v_sq))

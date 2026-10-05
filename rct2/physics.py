"""Approximate physics simulation for coaster tracks.

Walks a segment list with an energy-method velocity model and derives ride
statistics (speed, drops, g-forces, airtime) plus approximate RCT2-style
excitement/intensity/nausea ratings.

Unit conventions:
- Segment data uses RCT2 integer units: distances in tiles, heights in RCT2
  height units (a 25-degree slope climbs 2 units per tile, 60-degree climbs 8).
- The simulation converts once at the boundary and runs in meters/seconds:
  TILE_M meters per tile, HEIGHT_UNIT_M meters per height unit. Neither is a
  surveyed real-world size. HEIGHT_UNIT_M is confirmed by the game's drop
  height and drop count; TILE_M is calibrated so `ride_length` matches the
  length OpenRCT2 itself reports (see TILE_M), because that is the unit the
  rating thresholds are written in.
- TILE_M is coupled to FRICTION_COEFF and GFORCE_VERTICAL_COEFF: each
  consumes a horizontal length, so they are expressed through TILE_SCALE and
  move with it. Change the scale in one place and they follow. Lateral g does
  not depend on TILE_M: it is the game's own per-piece table (LATERAL_FACTOR).
- Rating multipliers in RATING_WEIGHTS are fitted against real designs; see
  the constant's own docstring for the fit and its limits.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, NamedTuple, Optional, Set

from rct2 import construction
from rct2.segments import SEGMENTS, Segment

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
# The scale at which FRICTION_COEFF and GFORCE_VERTICAL_COEFF were fitted. Do
# not change this when recalibrating TILE_M; it records where those two numbers
# came from.
_FIT_TILE_M = 3.0
TILE_SCALE = TILE_M / _FIT_TILE_M
HEIGHT_UNIT_M = 0.75
GRAVITY = 9.81
# Rolling friction deceleration per meter, as fraction of g. Scale-coupled to
# TILE_M: energy lost is 2 * FRICTION_COEFF * GRAVITY * length_m, so when the
# same piece got longer this had to shrink by the same factor to keep the
# energy lost per piece (0.01 at the original 3.0 m per tile).
FRICTION_COEFF = 0.01 / TILE_SCALE
MPH_PER_MS = 2.23694
LIFT_SPEED_MS = 2.2  # Mine Train chain lift, roughly 5 mph
MIN_SPEED_MS = 1.0  # below this off-lift, the train stalls

# G-force is linear in speed, not speed-squared over a geometric radius.
#
# OpenRCT2's real Vehicle::GetGForces() (src/openrct2/ride/Vehicle.cpp) computes:
#
#   gForceVert += abs(velocity) * 98 / vertFactor
#   gForceLateral += abs(velocity) * 98 / lateralFactor
#
# where vertFactor/lateralFactor come from a per-track-piece, per-progress
# lookup table baked into the game's original 1999 data -- not derived from
# geometry. We don't have those tables, so this keeps our own geometric shape
# factor (angle change over arc length, in place of vertFactor's role) but
# fixes the functional form to match: velocity to the first power, and a
# fitted constant standing in for "98 / vertFactor".
#
# The earlier v^2/(radius*g) form was real centripetal physics, which is not
# what RCT2 calculates. It overestimated positive vertical g by 2-4x, non-
# uniformly (1.04x on gentle rides, 3x+ on steep ones), which is why a scale
# factor could not have fixed it — the error scaled with the very term whose
# exponent was wrong.
#
# Fitted by least squares against the 6 of 7 real designs simulatable end to
# end (our segment table doesn't yet cover every piece type real designs use;
# see issue #25) with every segment type known. A 7th, Doubledrop, was
# excluded: its real export carries zero chain-lift indices, our simulation
# nearly stalls it on the opening climb as a result, and the corrupted speed
# profile from that stall would have biased the fit for an unrelated reason.
#
# Residual error against the 6-design fit set, and independently against
# data/sample_rides/manic_miner_test.td6 (not part of the fit):
#   positive vertical g: within ~0.2g          (was 2-4x high)
#   lateral g:           within ~0.5g           (was 3-4x high)
#   negative vertical g: systematically ~0.3-0.4g too shallow (was 2-6x deep)
# Negative g (airtime/crests) is the visible remaining gap. It was not chased
# further here because the fit set is already small (6 designs); narrowing it
# needs more real designs, which needs #25 first.
#
# GFORCE_VERTICAL_COEFF is scale-coupled to TILE_M (issue #60). The vertical
# term divides by an arc length, which grew with TILE_M, so the coefficient
# grows by TILE_SCALE to leave the g-force a piece produces exactly where the
# fit above put it. The number written here is the value as fitted at 3.0 m
# per tile.
#
# The "within ~0.5g" lateral residual above and the negative-g gap share a
# cause that was found later (issue #41, below): the real values these were
# fitted against are quantized. The vertical coefficient has the same
# problem and has not been refit.
GFORCE_VERTICAL_COEFF = 0.56393 * TILE_SCALE

# Lateral g is the game's own formula, not a fit (issue #41).
#
# Vehicle::GetGForces() in OpenRCT2 computes, on every physics tick:
#
#   lateral_g_x100 = (|velocity| * 98 / lateralFactor) * 10 >> 16
#
# where lateralFactor is one constant per track piece, stored on the piece's
# TrackElementDescriptor (src/openrct2/ride/ted/TED.*.h, `.lateralFactor`).
# The sign only says left or right. The game keeps the largest value seen on
# the test lap. LATERAL_FACTOR is that table for the pieces we model. A piece
# with no entry has no lateral g in the game either.
#
# Why the earlier fit under-read. It modelled lateral g as a fitted
# coefficient times speed over turn radius, less a flat credit on banked
# turns, and fitted it to the g-force bytes in 6 real designs' headers. The
# game writes those bytes as the runtime value divided by 32 with integer
# division (src/openrct2/rct2/T6Exporter.cpp), so every g-force read from a
# TD6 header, and every max_*_g in data/calibration.csv, is a multiple of
# 0.32g rounded down. The true value lies in [stored, stored + 0.32). The fit
# absorbed that bias: its implied factors (about 164 for the 5-tile turn and
# 99 for the 3-tile turn) are about 1.7x the game's 98 and 59, and the
# turn-type ratio was right, which is why it looked plausible. The ride that
# started #41 was read from the game's own display, not a header, so it was
# the one reading without the bias: 1.37g measured against 0.76g predicted.
#
# Checks against the data we have, keeping the quantization in mind:
#   manic_miner_test.td6 header reads 1.28g, so the real value is in
#     [1.28, 1.60). This gives 1.64g at simulated speeds. Our simulated max
#     speed is about 5% above the game's, so a little high is expected.
#   the #41 ride, 1.37g real: its tightest turn is an unbanked 3-tile turn
#     (factor 59) at 7.67 m/s in the simulation, which is 1.27g by this
#     formula (worked by hand; that ride's segments are not in the repo).
#
# Speed is the larger of the piece's entry and exit speeds, because the game
# records the maximum over the ticks on the piece, not the mean. The game also
# averages each tick's value with the previous tick's; that smooths a piece's
# first few ticks and does not change a steady turn, so it is not modelled.
#
# Not ported: banked turns and helices also carry a verticalFactor, which adds
# to vertical g in the game. The vertical model above does not include it.
LATERAL_FACTOR = {
    0x10: 98, 0x11: 98,  # quarter turn, 5 tiles
    0x22: 98, 0x23: 98, 0x24: 98, 0x25: 98,  # the same turn on a 25 degree slope
    0x2A: 59, 0x2B: 59,  # quarter turn, 3 tiles
    0x16: 160, 0x17: 160,  # banked quarter turn, 5 tiles
    0x2C: 100, 0x2D: 100,  # banked quarter turn, 3 tiles
    0x5A: 100,  # half helix down, small
    0x5E: 160,  # half helix down, large
}
# The game shows mph as velocity * 9 >> 18, so one mph is this many raw units.
_VELOCITY_UNITS_PER_MPH = 262144 / 9

# Slope state names from construction.slope_state_at mapped to track angle.
_SLOPE_ANGLE_RAD = {
    "flat": 0.0,
    "up": math.radians(25),
    "steep_up": math.radians(60),
    "down": math.radians(-25),
    "steep_down": math.radians(-60),
}

# Station pieces drive the train at lift speed, like a chain lift. Shared with
# construction.energy_stall_index so both energy models agree on what is powered.
_STATION_SEGMENTS = construction.STATION_SEGMENTS


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


@dataclass(frozen=True)
class RideStats:
    max_speed: float  # m/s
    avg_speed: float  # m/s
    ride_length: float  # m
    ride_time: float  # s
    drop_count: int
    total_drop_height: float  # height units
    highest_drop: float  # height units
    max_positive_g: float
    max_negative_g: float  # most negative vertical g reached
    max_lateral_g: float
    airtime: float  # seconds with vertical g below zero
    completed: bool
    stall_index: Optional[int]


def _lateral_g(seg_id: int, speed_ms: float) -> Optional[float]:
    """Lateral g on one piece at a given speed, by the game's own formula.

    None for a piece with no lateral factor. See LATERAL_FACTOR for the
    formula, its source, and how it was checked.
    """
    factor = LATERAL_FACTOR.get(seg_id)
    if factor is None:
        return None
    velocity = speed_ms * MPH_PER_MS * _VELOCITY_UNITS_PER_MPH
    return velocity * 98 / factor * 10 / 65536 / 100


def _vertical_g(
    prev_angle: float,
    angle: float,
    speed_ms: float,
    length_m: float,
) -> float:
    """Vertical g felt through a slope transition.

    A valley (angle increasing) adds to the base gravity term, a crest
    subtracts. Linear in speed rather than speed-squared over a geometric
    radius -- see GFORCE_VERTICAL_COEFF's docstring for why, and for the
    fit this constant comes from.
    """
    base = math.cos(angle)
    dtheta = angle - prev_angle
    if dtheta == 0 or length_m <= 0:
        return base
    shape = abs(dtheta) / length_m
    dynamic = GFORCE_VERTICAL_COEFF * speed_ms * shape
    return base + math.copysign(dynamic, dtheta)


class TracePoint(NamedTuple):
    """One piece of the ride as the energy walk saw it.

    Distances are meters along the track, heights are RCT2 height units
    relative to the station, speeds are m/s. `drop` numbers the counted drop
    this piece belongs to (1 for the first), or None when the piece is not
    part of one. On the piece where the train stalls, `stalled` is set, the
    exit speed is 0, and no distance or time is added.

    A NamedTuple rather than a frozen dataclass because `simulate()` runs on
    every fitness evaluation and builds one of these per piece; a frozen
    dataclass made that walk twice as slow.
    """

    index: int
    segment: int
    distance_start_m: float
    distance_m: float
    height_in: int
    height_out: int
    speed_in: float
    speed_out: float
    mean_speed: float
    time_s: float
    g_vertical: float
    g_lateral: Optional[float]  # None on straight pieces
    on_lift: bool  # chain lift or station, both drive the train
    is_station: bool
    drop: Optional[int]
    stalled: bool


@dataclass(frozen=True)
class RideTrace:
    points: List[TracePoint]
    completed: bool
    stall_index: Optional[int]


def trace(
    segments: list[int],
    lift_indices: Optional[Set[int]] = None,
) -> RideTrace:
    """Walk a track piece by piece with the energy method.

    This is the one walk the project has: `simulate()` aggregates its ride
    stats from these points, so a side profile drawn from the trace and the
    numbers shown next to it can never disagree.
    """
    if lift_indices is None:
        lift_indices = construction.default_lift_indices(segments)

    points: List[TracePoint] = []
    speed = LIFT_SPEED_MS
    distance = 0.0
    elevation = 0
    slope_state = "flat"
    prev_angle = 0.0
    drop_count = 0
    in_drop = False

    for index, seg_id in enumerate(segments):
        segment = SEGMENTS.get(seg_id, SEGMENTS[0x00])
        geometry = segment_length(segment)
        dz_m = segment.elevation_delta * HEIGHT_UNIT_M
        is_station = seg_id in _STATION_SEGMENTS

        on_lift = index in lift_indices or is_station
        if on_lift:
            exit_speed = max(speed, LIFT_SPEED_MS)
        else:
            v_sq = speed**2 - 2 * GRAVITY * dz_m
            v_sq -= 2 * FRICTION_COEFF * GRAVITY * geometry.length_m
            exit_speed = math.sqrt(max(0.0, v_sq))
            if exit_speed < MIN_SPEED_MS:
                points.append(TracePoint(
                    index=index, segment=seg_id,
                    distance_start_m=distance, distance_m=distance,
                    height_in=elevation, height_out=elevation,
                    speed_in=speed, speed_out=0.0, mean_speed=0.0, time_s=0.0,
                    g_vertical=math.cos(prev_angle), g_lateral=None,
                    on_lift=False, is_station=is_station, drop=None, stalled=True,
                ))
                return RideTrace(points=points, completed=False, stall_index=index)

        mean_speed = max(MIN_SPEED_MS, (speed + exit_speed) / 2)
        segment_time = geometry.length_m / mean_speed
        distance_start = distance
        distance += geometry.length_m

        slope_state, _ = construction._step_slope(slope_state, seg_id)
        angle = _SLOPE_ANGLE_RAD[slope_state]
        g_vert = _vertical_g(prev_angle, angle, mean_speed, geometry.length_m)
        prev_angle = angle

        lateral_g = _lateral_g(seg_id, max(speed, exit_speed))

        # Drop tracking: OpenRCT2 counts a drop the moment the train enters a
        # run of downward-sloped elements (Vehicle.cpp's testing-flags walk),
        # with no minimum height -- there is no threshold to clear. The run
        # ends as soon as a non-downward element interrupts it, so a flat
        # plateau partway down a hill splits one geometric descent into two
        # counted drops (see issue #33: a 2-unit descent, a flat stretch, then
        # an 8-unit descent reads as 2 drops in the game, not 1).
        if segment.elevation_delta < 0:
            if not in_drop:
                drop_count += 1
                in_drop = True
            drop: Optional[int] = drop_count
        else:
            in_drop = False
            drop = None

        points.append(TracePoint(
            index=index, segment=seg_id,
            distance_start_m=distance_start, distance_m=distance,
            height_in=elevation, height_out=elevation + segment.elevation_delta,
            speed_in=speed, speed_out=exit_speed, mean_speed=mean_speed,
            time_s=segment_time, g_vertical=g_vert, g_lateral=lateral_g,
            on_lift=on_lift, is_station=is_station, drop=drop, stalled=False,
        ))
        elevation += segment.elevation_delta
        speed = exit_speed

    return RideTrace(points=points, completed=True, stall_index=None)


def simulate(
    segments: list[int],
    lift_indices: Optional[Set[int]] = None,
) -> RideStats:
    """Run the energy-method walk over a track and collect ride stats."""
    ride = trace(segments, lift_indices)

    max_speed = LIFT_SPEED_MS
    ride_length = 0.0
    ride_time = 0.0
    airtime = 0.0
    max_positive_g = 1.0
    max_negative_g = 1.0
    max_lateral_g = 0.0
    drop_heights: Dict[int, float] = {}

    for point in ride.points:
        if point.stalled:
            break
        ride_length += point.distance_m - point.distance_start_m
        ride_time += point.time_s
        max_positive_g = max(max_positive_g, point.g_vertical)
        max_negative_g = min(max_negative_g, point.g_vertical)
        if point.g_vertical < 0:
            airtime += point.time_s
        if point.g_lateral is not None:
            max_lateral_g = max(max_lateral_g, point.g_lateral)
        if point.drop is not None:
            drop_heights[point.drop] = (
                drop_heights.get(point.drop, 0) + point.height_in - point.height_out
            )
        max_speed = max(max_speed, point.speed_out)

    total_drop_height = 0.0
    highest_drop = 0.0
    for height in drop_heights.values():
        total_drop_height += height
        highest_drop = max(highest_drop, height)

    avg_speed = ride_length / ride_time if ride_time > 0 else 0.0
    return RideStats(
        max_speed=max_speed,
        avg_speed=avg_speed,
        ride_length=ride_length,
        ride_time=ride_time,
        drop_count=len(drop_heights),
        total_drop_height=total_drop_height,
        highest_drop=highest_drop,
        max_positive_g=max_positive_g,
        max_negative_g=max_negative_g,
        max_lateral_g=max_lateral_g,
        airtime=airtime,
        completed=ride.completed,
        stall_index=ride.stall_index,
    )


@dataclass(frozen=True)
class RideRatings:
    excitement: float
    intensity: float
    nausea: float


# Rating weights fitted by least squares against `data/calibration.csv`: 204
# real track designs shipped with the game, each carrying the ratings the game
# itself assigned and the stats the game itself measured. See
# docs/devlog.md (2026-08-02) for the fit and its limits.
#
# Units are the game's own, not ours: miles per hour and meters, matching the
# calibration data. `rate()` converts from RideStats at the boundary. Fitting
# in the source units keeps each coefficient interpretable as "rating points
# per mph" rather than a compound of two conversions.
#
# What this fit is good at, and what it is not:
#
#   Ranking, which is what evolution actually consumes. Spearman correlation
#   against the real ratings across all 204 designs is 0.87 for excitement,
#   0.84 intensity, 0.58 nausea — against 0.45 / 0.74 / 0.49 for the
#   placeholder weights this replaces.
#
#   Absolute values *inside the range the designs cover* (excitement 0.3-8.8,
#   median 6.3): r2 0.73 / 0.85 / 0.61, mean absolute error 0.57 / 0.78 / 0.94.
#
#   Absolute values *below* that range: unreliable, and this is the honest
#   limitation. Every ride generide has produced so far scores below 200 of
#   the 204 shipped designs, so the fit is extrapolating there and reads
#   roughly 2-4 points high. Four of our own in-game measurements were tested
#   as training anchors and did not fix it — 4 rows against 204 barely move
#   the fit.
#
#   The mechanism behind that gap is now known, and refitting cannot close it.
#   The game applies threshold checks that *divide* all three ratings (the
#   Mine Train halves them for each of drop height under 8 height units, fewer
#   than 2 drops, and three others; see RideRatings.cpp's Requirement
#   functions). Nearly every shipped design clears those thresholds and nearly
#   every track we generate fails at least one, so the fit never saw the cliff
#   and no linear model can express it. Porting the real calculation, whose
#   constants are public in OpenRCT2's source, is the actual fix; see
#   docs/devlog.md (2026-08-08).
#
# Airtime is deliberately absent. The calibration data stores it in an
# unconverted unit (see docs/phase1-spec.md) and our simulated airtime is
# separately known to be several times too high, so including it would add
# two compounding errors for one weak predictor.
RATING_WEIGHTS = {
    "excitement_base": 2.5290,
    "excitement_max_speed_mph": 0.013030,
    "excitement_average_speed_mph": 0.032069,
    "excitement_ride_length_m": 0.001522,
    "excitement_max_positive_vertical_g": 0.212852,
    "excitement_max_negative_vertical_g": -0.008452,
    "excitement_max_lateral_g": 0.410545,
    "excitement_drop_count": 0.070207,
    "excitement_highest_drop_height_m": -0.006029,
    "excitement_inversion_count": -0.073437,
    "intensity_base": 0.3928,
    "intensity_max_speed_mph": 0.104738,
    "intensity_average_speed_mph": 0.015165,
    "intensity_ride_length_m": -0.001869,
    "intensity_max_positive_vertical_g": 0.212605,
    "intensity_max_negative_vertical_g": -0.624363,
    "intensity_max_lateral_g": 0.546125,
    "intensity_drop_count": 0.217989,
    "intensity_highest_drop_height_m": -0.064294,
    "intensity_inversion_count": 0.142704,
    "nausea_base": 0.6078,
    "nausea_max_speed_mph": 0.071178,
    "nausea_average_speed_mph": 0.025821,
    "nausea_ride_length_m": -0.001699,
    "nausea_max_positive_vertical_g": 0.024989,
    "nausea_max_negative_vertical_g": -0.576455,
    "nausea_max_lateral_g": 0.780585,
    "nausea_drop_count": 0.058551,
    "nausea_highest_drop_height_m": -0.054940,
    "nausea_inversion_count": 0.027337,
}

_RATING_FEATURES = (
    "max_speed_mph",
    "average_speed_mph",
    "ride_length_m",
    "max_positive_vertical_g",
    "max_negative_vertical_g",
    "max_lateral_g",
    "drop_count",
    "highest_drop_height_m",
    "inversion_count",
)


def rating_features(stats: RideStats) -> dict:
    """Convert RideStats into the game's own units, as the fit expects them.

    `max_negative_vertical_g` is signed, negative when the train goes light
    over a crest. RideStats stores that as an unsigned magnitude, so it is
    negated here — the calibration data is signed (152 of 204 designs are
    negative) and the fitted coefficient is large, so getting this backwards
    silently inverts a real term rather than merely scaling it.
    """
    return {
        "max_speed_mph": stats.max_speed * MPH_PER_MS,
        "average_speed_mph": stats.avg_speed * MPH_PER_MS,
        "ride_length_m": stats.ride_length,
        "max_positive_vertical_g": stats.max_positive_g,
        "max_negative_vertical_g": -abs(stats.max_negative_g),
        "max_lateral_g": stats.max_lateral_g,
        "drop_count": stats.drop_count,
        "highest_drop_height_m": stats.highest_drop * HEIGHT_UNIT_M,
        # generide never builds inversions; kept so the fitted coefficients,
        # which were estimated with this column present, stay unbiased.
        "inversion_count": 0,
    }


def rate(stats: RideStats) -> RideRatings:
    """Predict the excitement/intensity/nausea the game would assign.

    This is a prediction, not a preference. The three ratings are computed
    independently, the way the game computes them — there is deliberately no
    "excitement collapses when intensity is high" term here. That behaviour is
    a statement about which rides we *want*, not about what the game would say,
    and it belongs in the fitness function. Folding it in here previously meant
    a slightly-too-high intensity estimate silently destroyed a track's
    excitement, which is what taught evolution to avoid speed and drops.

    Accuracy is documented on RATING_WEIGHTS. In short: ranking is good, and
    absolute values below roughly 3 read high because no shipped design lives
    down there to calibrate against.
    """
    w = RATING_WEIGHTS
    features = rating_features(stats)
    ratings = {}
    for target in ("excitement", "intensity", "nausea"):
        value = w[f"{target}_base"]
        for feature in _RATING_FEATURES:
            value += w[f"{target}_{feature}"] * features[feature]
        ratings[target] = max(0.0, value)

    return RideRatings(**ratings)

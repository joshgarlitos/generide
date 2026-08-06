"""Approximate physics simulation for coaster tracks.

Walks a segment list with an energy-method velocity model and derives ride
statistics (speed, drops, g-forces, airtime) plus approximate RCT2-style
excitement/intensity/nausea ratings.

Unit conventions:
- Segment data uses RCT2 integer units: distances in tiles, heights in RCT2
  height units (a 25-degree slope climbs 2 units per tile, 60-degree climbs 8).
- The simulation converts once at the boundary and runs in meters/seconds:
  TILE_M meters per tile, HEIGHT_UNIT_M meters per height unit.
- Rating multipliers in RATING_WEIGHTS are fitted against real designs; see
  the constant's own docstring for the fit and its limits.
"""

import math
from dataclasses import dataclass
from typing import Optional, Set

from rct2 import construction
from rct2.segments import SEGMENTS, Segment

TILE_M = 3.0
HEIGHT_UNIT_M = 0.75
GRAVITY = 9.81
FRICTION_COEFF = 0.01  # rolling friction deceleration per meter, as fraction of g
LIFT_SPEED_MS = 2.2  # Mine Train chain lift, roughly 5 mph
MIN_SPEED_MS = 1.0  # below this off-lift, the train stalls
DROP_THRESHOLD_UNITS = 3  # minimum descent (height units) to count as a drop
BANK_LATERAL_CREDIT = 0.67  # lateral g absorbed by a banked turn

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
GFORCE_VERTICAL_COEFF = 0.56393
GFORCE_LATERAL_COEFF = 0.44517

# Slope state names from construction.slope_state_at mapped to track angle.
_SLOPE_ANGLE_RAD = {
    "flat": 0.0,
    "up": math.radians(25),
    "steep_up": math.radians(60),
    "down": math.radians(-25),
    "steep_down": math.radians(-60),
}

# Turn pieces that are banked (felt lateral g is reduced on these).
_BANKED_TURNS = {0x16, 0x17, 0x2C, 0x2D, 0x5A, 0x5E}

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


def simulate(
    segments: list[int],
    lift_indices: Optional[Set[int]] = None,
) -> RideStats:
    """Run the energy-method walk over a track and collect ride stats."""
    if lift_indices is None:
        lift_indices = construction.default_lift_indices(segments)

    speed = LIFT_SPEED_MS
    max_speed = speed
    ride_length = 0.0
    ride_time = 0.0
    airtime = 0.0
    max_positive_g = 1.0
    max_negative_g = 1.0
    max_lateral_g = 0.0
    completed = True
    stall_index: Optional[int] = None

    elevation = 0
    slope_state = "flat"
    descent_run = 0
    drop_count = 0
    total_drop_height = 0.0
    highest_drop = 0.0
    prev_angle = 0.0

    for index, seg_id in enumerate(segments):
        segment = SEGMENTS.get(seg_id, SEGMENTS[0x00])
        geometry = segment_length(segment)
        dz_m = segment.elevation_delta * HEIGHT_UNIT_M

        on_lift = index in lift_indices or seg_id in _STATION_SEGMENTS
        if on_lift:
            exit_speed = max(speed, LIFT_SPEED_MS)
        else:
            v_sq = speed**2 - 2 * GRAVITY * dz_m
            v_sq -= 2 * FRICTION_COEFF * GRAVITY * geometry.length_m
            exit_speed = math.sqrt(max(0.0, v_sq))
            if exit_speed < MIN_SPEED_MS:
                completed = False
                stall_index = index
                break

        mean_speed = max(MIN_SPEED_MS, (speed + exit_speed) / 2)
        segment_time = geometry.length_m / mean_speed
        ride_length += geometry.length_m
        ride_time += segment_time

        slope_state, _ = construction._step_slope(slope_state, seg_id)
        angle = _SLOPE_ANGLE_RAD[slope_state]
        g_vert = _vertical_g(prev_angle, angle, mean_speed, geometry.length_m)
        max_positive_g = max(max_positive_g, g_vert)
        max_negative_g = min(max_negative_g, g_vert)
        if g_vert < 0:
            airtime += segment_time
        prev_angle = angle

        if geometry.radius_m is not None:
            # Linear in speed, same reasoning as the vertical term above.
            lateral_g = GFORCE_LATERAL_COEFF * mean_speed / geometry.radius_m
            if seg_id in _BANKED_TURNS:
                lateral_g = max(0.0, lateral_g - BANK_LATERAL_CREDIT)
            max_lateral_g = max(max_lateral_g, lateral_g)

        # Drop tracking: accumulate contiguous descent in height units.
        if segment.elevation_delta < 0:
            descent_run += -segment.elevation_delta
        else:
            if descent_run >= DROP_THRESHOLD_UNITS:
                drop_count += 1
                total_drop_height += descent_run
                highest_drop = max(highest_drop, descent_run)
            descent_run = 0
        elevation += segment.elevation_delta

        speed = exit_speed
        max_speed = max(max_speed, speed)

    if descent_run >= DROP_THRESHOLD_UNITS:
        drop_count += 1
        total_drop_height += descent_run
        highest_drop = max(highest_drop, descent_run)

    avg_speed = ride_length / ride_time if ride_time > 0 else 0.0
    return RideStats(
        max_speed=max_speed,
        avg_speed=avg_speed,
        ride_length=ride_length,
        ride_time=ride_time,
        drop_count=drop_count,
        total_drop_height=total_drop_height,
        highest_drop=highest_drop,
        max_positive_g=max_positive_g,
        max_negative_g=max_negative_g,
        max_lateral_g=max_lateral_g,
        airtime=airtime,
        completed=completed,
        stall_index=stall_index,
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
#   the fit. Closing that gap needs more of our own rides measured in-game,
#   which is the only source of data in that region.
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

MPH_PER_MS = 2.23694
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

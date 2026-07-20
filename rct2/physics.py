"""Approximate physics simulation for coaster tracks.

Walks a segment list with an energy-method velocity model and derives ride
statistics (speed, drops, g-forces, airtime) plus approximate RCT2-style
excitement/intensity/nausea ratings.

Unit conventions:
- Segment data uses RCT2 integer units: distances in tiles, heights in RCT2
  height units (a 25-degree slope climbs 2 units per tile, 60-degree climbs 8).
- The simulation converts once at the boundary and runs in meters/seconds:
  TILE_M meters per tile, HEIGHT_UNIT_M meters per height unit.
- Rating multipliers in RATING_WEIGHTS are placeholders to be calibrated
  against headless OpenRCT2 runs in a later phase.
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

# Station pieces drive the train at lift speed, like a chain lift.
_STATION_SEGMENTS = {0x01, 0x02, 0x03}


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

    Approximates the transition as an arc spanning this segment's length:
    a valley (angle increasing) adds centripetal g, a crest subtracts it.
    This is the crudest part of the model and the first calibration target.
    """
    base = math.cos(angle)
    dtheta = angle - prev_angle
    if dtheta == 0 or length_m <= 0:
        return base
    radius = length_m / abs(dtheta)
    centripetal = speed_ms**2 / (radius * GRAVITY)
    return base + math.copysign(centripetal, dtheta)


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
            lateral_g = mean_speed**2 / (geometry.radius_m * GRAVITY)
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


# Placeholder Mine Train multipliers, shaped like OpenRCT2's RideRatings
# contributions. Calibrate against headless OpenRCT2 in a later phase.
RATING_WEIGHTS = {
    "excitement_base": 2.9,
    "excitement_max_speed": 0.12,  # per m/s
    "excitement_avg_speed": 0.10,
    "excitement_drops": 0.25,  # per drop
    "excitement_drop_height": 0.02,  # per height unit dropped
    "excitement_airtime": 0.5,  # per second
    "excitement_length": 0.002,  # per meter
    "intensity_base": 2.0,
    "intensity_max_speed": 0.15,
    "intensity_positive_g": 1.2,  # per g above 1
    "intensity_negative_g": 1.5,  # per g below 0
    "intensity_lateral_g": 1.5,
    "intensity_drop_height": 0.03,
    "nausea_base": 1.0,
    "nausea_lateral_g": 1.8,
    "nausea_negative_g": 1.0,
    "nausea_intensity": 0.25,  # coupling from intensity
    "intensity_cap": 10.0,  # excitement collapses beyond this
    "lateral_g_cap": 2.8,
    "excess_penalty": 0.75,  # excitement lost per unit past a cap
}


def rate(stats: RideStats) -> RideRatings:
    """Map ride stats to approximate excitement/intensity/nausea ratings."""
    w = RATING_WEIGHTS

    intensity = (
        w["intensity_base"]
        + w["intensity_max_speed"] * stats.max_speed
        + w["intensity_positive_g"] * max(0.0, stats.max_positive_g - 1.0)
        + w["intensity_negative_g"] * max(0.0, -stats.max_negative_g)
        + w["intensity_lateral_g"] * stats.max_lateral_g
        + w["intensity_drop_height"] * stats.total_drop_height
    )

    nausea = (
        w["nausea_base"]
        + w["nausea_lateral_g"] * stats.max_lateral_g
        + w["nausea_negative_g"] * max(0.0, -stats.max_negative_g)
        + w["nausea_intensity"] * intensity
    )

    excitement = (
        w["excitement_base"]
        + w["excitement_max_speed"] * stats.max_speed
        + w["excitement_avg_speed"] * stats.avg_speed
        + w["excitement_drops"] * stats.drop_count
        + w["excitement_drop_height"] * stats.total_drop_height
        + w["excitement_airtime"] * stats.airtime
        + w["excitement_length"] * stats.ride_length
    )
    if intensity > w["intensity_cap"]:
        excitement -= (intensity - w["intensity_cap"]) * w["excess_penalty"]
    if stats.max_lateral_g > w["lateral_g_cap"]:
        excitement -= (stats.max_lateral_g - w["lateral_g_cap"]) * w["excess_penalty"]

    return RideRatings(
        excitement=max(0.0, excitement),
        intensity=max(0.0, intensity),
        nausea=max(0.0, nausea),
    )

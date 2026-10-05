"""Centerlines for a track, one per piece, in world tile coordinates.

The isometric picture draws its rails along these lines and the train rides
them, so the train always runs on the track it is drawn on. Pieces are cut
into short runs of samples because a long piece drawn as one stroke could not
be sorted back to front against a piece that only partly overlaps it.

Coordinates are tiles for x and y and RCT2 height units for z, so a height
unit is a quarter tile when the picture is drawn. A piece starts at the
midpoint of its entry edge and ends at the midpoint of the next piece's entry
edge. The tile centre is the integer position `geometry` reports, so a
straight piece runs half a tile either side of that centre.
"""

import math
from typing import List, NamedTuple, Optional, Sequence, Tuple

from rct2.construction import SLOPE_TRANSITIONS
from rct2.geometry import _AXES, Position, advance_position
from rct2.segments import get_segment

Point = Tuple[float, float, float]

# Samples per piece. Straight pieces are short and nearly line segments, but a
# slope transition curves, so they get a few. Arcs get enough that a quarter
# turn reads as round at the picture's sizes.
STRAIGHT_STEPS = 4
ARC_STEPS_PER_QUARTER = 8

# Height units a piece climbs per tile of track at each slope the construction
# rules know about. Flat pieces are 0, the 25 degree pieces rise 2 per tile,
# the 60 degree pieces 8.
_GRADIENT = {"flat": 0, "up": 2, "steep_up": 8, "down": -2, "steep_down": -8}


class PiecePath(NamedTuple):
    """One piece's centerline."""

    index: int
    segment: int
    points: Tuple[Point, ...]


def _gradient_at_ends(segment_id: int) -> Tuple[int, int]:
    required, resulting = SLOPE_TRANSITIONS.get(segment_id, ("flat", "flat"))
    return _GRADIENT[required], _GRADIENT[resulting]


def _height_fraction(t: float, segment_id: int, rise: int) -> float:
    """How far up its rise a straight piece is at fraction `t` along it.

    A piece that joins two slopes bends: it starts at the gradient of the
    slope before it and ends at the gradient of the slope after it, and
    covers the rise the piece definition gives. That gradient is constant
    across a full slope piece, so those stay straight lines.
    """
    start, end = _gradient_at_ends(segment_id)
    total = start + end
    if rise == 0 or total == 0 or start == end:
        return t
    # Gradient changes linearly from `start` to `end` along the piece, and
    # the area under it is scaled to the piece's own rise.
    return (start * t + (end - start) * t * t / 2) / (total / 2)


def _piece_points(position: Position, index: int, segment_id: int) -> PiecePath:
    segment = get_segment(segment_id)
    forward_x, forward_y, right_x, right_y = _AXES[position.heading]
    end = advance_position(position, segment)
    end_forward_x, end_forward_y, _, _ = _AXES[end.heading]

    start_xy = (position.x - 0.5 * forward_x, position.y - 0.5 * forward_y)
    end_xy = (end.x - 0.5 * end_forward_x, end.y - 0.5 * end_forward_y)
    rise = segment.elevation_delta
    turn = segment.direction_delta

    points: List[Point] = []
    if turn == 0:
        for step in range(STRAIGHT_STEPS + 1):
            t = step / STRAIGHT_STEPS
            z = position.z + rise * _height_fraction(t, segment_id, rise)
            points.append((
                start_xy[0] + (end_xy[0] - start_xy[0]) * t,
                start_xy[1] + (end_xy[1] - start_xy[1]) * t,
                z,
            ))
    else:
        # A quarter turn's radius reaches from the entry edge to the next
        # piece's tile centre, half a tile more than the forward step. A half
        # turn's is half the sideways step. These are the radii physics uses
        # for arc length.
        if abs(turn) == 1:
            radius = abs(segment.forward_delta) + 0.5
        else:
            radius = abs(segment.right_delta) / 2
        side = 1 if turn > 0 else -1
        centre = (
            start_xy[0] + side * radius * right_x,
            start_xy[1] + side * radius * right_y,
        )
        steps = ARC_STEPS_PER_QUARTER * abs(turn)
        for step in range(steps + 1):
            t = step / steps
            angle = t * abs(turn) * math.pi / 2
            # From the centre, the entry point sits behind the ride; sweeping
            # the angle turns that spoke through the turn.
            back = radius * math.cos(angle)
            across = radius * math.sin(angle)
            points.append((
                centre[0] - side * back * right_x + across * forward_x,
                centre[1] - side * back * right_y + across * forward_y,
                position.z + rise * t,
            ))
    return PiecePath(index, segment_id, tuple(points))


def track_path(segments: Sequence[int], start: Optional[Position] = None) -> List[PiecePath]:
    """The centerline of every piece, in track order."""
    position = start if start is not None else Position()
    paths = []
    for index, segment_id in enumerate(segments):
        paths.append(_piece_points(position, index, segment_id))
        position = advance_position(position, segment_id)
    return paths

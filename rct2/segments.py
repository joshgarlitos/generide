"""Geometry definitions for TD6 track segment types.

Movement deltas use a local frame: forward follows the incoming heading and
right is perpendicular to it. Elevation uses RCT2 height units.
"""

from dataclasses import dataclass


Footprint = tuple[tuple[int, int, int], ...]

_LEFT_TURN_5: Footprint = (
    (0, 0, 0), (0, -1, 0), (1, 0, 0), (1, -1, 0),
    (1, -2, 0), (2, -1, 0), (2, -2, 0),
)
_RIGHT_TURN_5: Footprint = tuple((forward, -right, z) for forward, right, z in _LEFT_TURN_5)
_LEFT_TURN_3: Footprint = ((0, 0, 0), (0, -1, 0), (1, 0, 0), (1, -1, 0))
_RIGHT_TURN_3: Footprint = tuple((forward, -right, z) for forward, right, z in _LEFT_TURN_3)


def _with_heights(footprint: Footprint, heights: tuple[int, ...]) -> Footprint:
    return tuple(
        (forward, right, height)
        for (forward, right, _), height in zip(footprint, heights)
    )


class UnknownSegmentError(ValueError):
    """Raised when geometry has not been defined for a TD6 segment type."""


@dataclass(frozen=True)
class Segment:
    type_id: int
    name: str
    forward_delta: int = 1
    right_delta: int = 0
    elevation_delta: int = 0
    direction_delta: int = 0
    footprint: Footprint = ((0, 0, 0),)


def _segment(
    type_id: int,
    name: str,
    *,
    forward: int = 1,
    right: int = 0,
    elevation: int = 0,
    turn: int = 0,
    footprint: Footprint = ((0, 0, 0),),
) -> Segment:
    return Segment(type_id, name, forward, right, elevation, turn, footprint)


_SEGMENTS = [
    _segment(0x00, "flat"),
    _segment(0x01, "end_station"),
    _segment(0x02, "begin_station"),
    _segment(0x03, "middle_station"),
    _segment(0x04, "25_deg_up", elevation=2),
    _segment(0x05, "60_deg_up", elevation=8),
    _segment(0x06, "flat_to_25_deg_up", elevation=1),
    _segment(0x07, "25_deg_up_to_60_deg_up", elevation=4),
    _segment(0x08, "60_deg_up_to_25_deg_up", elevation=4),
    _segment(0x09, "25_deg_up_to_flat", elevation=1),
    _segment(0x0A, "25_deg_down", elevation=-2),
    _segment(0x0B, "60_deg_down", elevation=-8),
    _segment(0x0C, "flat_to_25_deg_down", elevation=-1),
    _segment(0x0D, "25_deg_down_to_60_deg_down", elevation=-4),
    _segment(0x0E, "60_deg_down_to_25_deg_down", elevation=-4),
    _segment(0x0F, "25_deg_down_to_flat", elevation=-1),
    _segment(0x10, "left_quarter_turn_5_tiles", forward=2, right=-3, turn=-1, footprint=_LEFT_TURN_5),
    _segment(0x11, "right_quarter_turn_5_tiles", forward=2, right=3, turn=1, footprint=_RIGHT_TURN_5),
    _segment(0x12, "flat_to_left_bank"),
    _segment(0x13, "flat_to_right_bank"),
    _segment(0x14, "left_bank_to_flat"),
    _segment(0x15, "right_bank_to_flat"),
    _segment(0x16, "banked_left_quarter_turn_5_tiles", forward=2, right=-3, turn=-1, footprint=_LEFT_TURN_5),
    _segment(0x17, "banked_right_quarter_turn_5_tiles", forward=2, right=3, turn=1, footprint=_RIGHT_TURN_5),
    _segment(0x18, "left_bank_to_25_deg_up", elevation=1),
    _segment(0x19, "right_bank_to_25_deg_up", elevation=1),
    _segment(0x1A, "25_deg_up_to_left_bank", elevation=1),
    _segment(0x1B, "25_deg_up_to_right_bank", elevation=1),
    _segment(0x1C, "left_bank_to_25_deg_down", elevation=-1),
    _segment(0x1D, "right_bank_to_25_deg_down", elevation=-1),
    _segment(0x1E, "25_deg_down_to_left_bank", elevation=-1),
    _segment(0x1F, "25_deg_down_to_right_bank", elevation=-1),
    _segment(0x20, "left_bank"),
    _segment(0x21, "right_bank"),
    _segment(0x22, "left_quarter_turn_5_tiles_25_deg_up", forward=2, right=-3, elevation=8, turn=-1, footprint=_with_heights(_LEFT_TURN_5, (0, 2, 2, 3, 6, 4, 6))),
    _segment(0x23, "right_quarter_turn_5_tiles_25_deg_up", forward=2, right=3, elevation=8, turn=1, footprint=_with_heights(_RIGHT_TURN_5, (0, 2, 2, 3, 6, 4, 6))),
    _segment(0x24, "left_quarter_turn_5_tiles_25_deg_down", forward=2, right=-3, elevation=-8, turn=-1, footprint=_with_heights(_LEFT_TURN_5, (-2, -2, -4, -5, -6, -6, -8))),
    _segment(0x25, "right_quarter_turn_5_tiles_25_deg_down", forward=2, right=3, elevation=-8, turn=1, footprint=_with_heights(_RIGHT_TURN_5, (-2, -2, -4, -5, -6, -6, -8))),
    _segment(0x2A, "left_quarter_turn_3_tiles", right=-2, turn=-1, footprint=_LEFT_TURN_3),
    _segment(0x2B, "right_quarter_turn_3_tiles", right=2, turn=1, footprint=_RIGHT_TURN_3),
    _segment(0x2C, "banked_left_quarter_turn_3_tiles", right=-2, turn=-1, footprint=_LEFT_TURN_3),
    _segment(0x2D, "banked_right_quarter_turn_3_tiles", right=2, turn=1, footprint=_RIGHT_TURN_3),
    _segment(0x5A, "right_half_banked_helix_down_small", forward=-1, right=3, elevation=-2, turn=2, footprint=((0, 0, -1), (0, 1, -1), (1, 0, -1), (1, 1, -1), (1, 2, -2), (0, 2, -2), (1, 3, -2), (0, 3, -2))),
    _segment(0x5E, "right_half_banked_helix_down_large", forward=-1, right=5, elevation=-2, turn=2, footprint=((0, 0, -1), (0, 1, -1), (1, 0, -1), (1, 1, -1), (1, 2, -1), (1, 3, -1), (2, 2, -1), (2, 3, -2), (1, 3, -2), (2, 4, -2), (1, 4, -2), (0, 4, -2), (1, 5, -2), (0, 5, -2))),
    _segment(0x63, "brakes"),
    _segment(0xD8, "block_brakes"),
]

SEGMENTS = {segment.type_id: segment for segment in _SEGMENTS}


def get_segment(type_id: int) -> Segment:
    """Return geometry for a TD6 segment type."""
    try:
        return SEGMENTS[type_id]
    except KeyError as exc:
        raise UnknownSegmentError(
            f"no geometry defined for TD6 segment type 0x{type_id:02X}"
        ) from exc

"""Track position math and circuit traversal."""

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable, Optional, Union

from rct2.segments import Segment, UnknownSegmentError, get_segment


class Heading(IntEnum):
    NORTH = 0
    EAST = 1
    SOUTH = 2
    WEST = 3


@dataclass(frozen=True)
class Position:
    x: int = 0
    y: int = 0
    z: int = 0
    heading: Heading = Heading.NORTH


@dataclass(frozen=True)
class OccupiedTile:
    x: int
    y: int
    z: int
    segment_index: int


@dataclass(frozen=True)
class Bounds:
    min_x: int
    max_x: int
    min_y: int
    max_y: int
    min_z: int
    max_z: int

    @property
    def width(self) -> int:
        return self.max_x - self.min_x + 1

    @property
    def depth(self) -> int:
        return self.max_y - self.min_y + 1

    @property
    def height(self) -> int:
        return self.max_z - self.min_z


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...]
    bounds: Optional[Bounds]
    end_position: Optional[Position]

    @property
    def valid(self) -> bool:
        return not self.issues


SegmentLike = Union[int, Segment]

# (forward x, forward y, right x, right y)
_AXES = {
    Heading.NORTH: (0, 1, 1, 0),
    Heading.EAST: (1, 0, 0, -1),
    Heading.SOUTH: (0, -1, -1, 0),
    Heading.WEST: (-1, 0, 0, 1),
}


def _resolve_segment(segment: SegmentLike) -> Segment:
    return get_segment(segment) if isinstance(segment, int) else segment


def advance_position(position: Position, segment: SegmentLike) -> Position:
    """Return the end position after placing one segment."""
    definition = _resolve_segment(segment)
    forward_x, forward_y, right_x, right_y = _AXES[position.heading]

    return Position(
        x=position.x
        + forward_x * definition.forward_delta
        + right_x * definition.right_delta,
        y=position.y
        + forward_y * definition.forward_delta
        + right_y * definition.right_delta,
        z=position.z + definition.elevation_delta,
        heading=Heading((position.heading + definition.direction_delta) % 4),
    )


def trace_track(start: Position, segments: Iterable[SegmentLike]) -> list[Position]:
    """Return the start and each successive segment endpoint."""
    positions = [start]
    current = start
    for segment in segments:
        current = advance_position(current, segment)
        positions.append(current)
    return positions


def occupied_tiles(start: Position, segments: Iterable[SegmentLike]) -> list[OccupiedTile]:
    """Return every segment footprint tile rotated into world coordinates."""
    tiles = []
    current = start
    for index, segment in enumerate(segments):
        definition = _resolve_segment(segment)
        forward_x, forward_y, right_x, right_y = _AXES[current.heading]
        for forward, right, elevation in definition.footprint:
            tiles.append(OccupiedTile(
                x=current.x + forward_x * forward + right_x * right,
                y=current.y + forward_y * forward + right_y * right,
                z=current.z + elevation,
                segment_index=index,
            ))
        current = advance_position(current, definition)
    return tiles


def track_bounds(start: Position, segments: Iterable[SegmentLike]) -> Bounds:
    """Return inclusive horizontal bounds and endpoint-aware vertical bounds."""
    segment_list = list(segments)
    tiles = occupied_tiles(start, segment_list)
    positions = trace_track(start, segment_list)
    xs = [tile.x for tile in tiles] or [position.x for position in positions]
    ys = [tile.y for tile in tiles] or [position.y for position in positions]
    zs = [tile.z for tile in tiles] + [position.z for position in positions]
    return Bounds(min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def overlapping_tiles(tiles: Iterable[OccupiedTile]) -> dict[tuple[int, int, int], list[int]]:
    """Return exact occupied cells used by more than one segment."""
    occupants = {}
    for tile in tiles:
        occupants.setdefault((tile.x, tile.y, tile.z), []).append(tile.segment_index)
    return {cell: indices for cell, indices in occupants.items() if len(indices) > 1}


def validate_track(
    start: Position,
    segments: Iterable[SegmentLike],
    *,
    max_width: Optional[int] = None,
    max_depth: Optional[int] = None,
    max_height: Optional[int] = None,
    min_elevation: int = 0,
    allow_footprint_rotation: bool = True,
) -> ValidationResult:
    """Validate circuit closure, occupancy, and optional bounding constraints."""
    segment_list = list(segments)
    issues = []

    try:
        definitions = [_resolve_segment(segment) for segment in segment_list]
    except UnknownSegmentError as exc:
        return ValidationResult(
            issues=(ValidationIssue("unknown_segment", str(exc)),),
            bounds=None,
            end_position=None,
        )

    positions = trace_track(start, definitions)
    end = positions[-1]
    if end != start:
        issues.append(ValidationIssue(
            "open_circuit",
            "circuit does not return to its starting position and heading: "
            f"start={start}, end={end}",
        ))

    tiles = occupied_tiles(start, definitions)
    overlaps = overlapping_tiles(tiles)
    for cell, indices in sorted(overlaps.items()):
        issues.append(ValidationIssue(
            "collision",
            f"segments {indices} occupy the same cell {cell}",
        ))

    bounds = track_bounds(start, definitions)
    width_fits = max_width is None or bounds.width <= max_width
    depth_fits = max_depth is None or bounds.depth <= max_depth
    if max_width is not None and max_depth is not None and allow_footprint_rotation:
        rotated_fits = bounds.width <= max_depth and bounds.depth <= max_width
        footprint_fits = (width_fits and depth_fits) or rotated_fits
    else:
        footprint_fits = width_fits and depth_fits

    if not footprint_fits:
        issues.append(ValidationIssue(
            "footprint_exceeded",
            f"track footprint {bounds.width}x{bounds.depth} exceeds allowed "
            f"{max_width or 'unlimited'}x{max_depth or 'unlimited'}",
        ))
    if max_height is not None and bounds.height > max_height:
        issues.append(ValidationIssue(
            "height_exceeded",
            f"track height {bounds.height} exceeds allowed {max_height}",
        ))
    if bounds.min_z < min_elevation:
        issues.append(ValidationIssue(
            "below_minimum_elevation",
            f"track reaches elevation {bounds.min_z}, below allowed {min_elevation}",
        ))

    return ValidationResult(tuple(issues), bounds, end)


def is_closed_circuit(start: Position, segments: Iterable[SegmentLike]) -> bool:
    """Return whether a track ends at its exact starting pose."""
    return trace_track(start, segments)[-1] == start

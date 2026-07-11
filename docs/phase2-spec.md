# Phase 2 Spec: Track Geometry

## Goal

Given a track position and a TD6 segment type, compute the position and heading
at the end of that segment. Repeating that operation over a ride produces a path
that can be checked for closure.

## Coordinate system

- `x` increases east.
- `y` increases north.
- `z` is expressed in RCT2 height units.
- Headings are the four orthogonal directions: north, east, south, and west.
- Segment movement is stored in local coordinates as a forward delta and a
  rightward delta. Geometry rotates those deltas into world coordinates using
  the position's incoming heading.

For example, a flat segment has local movement `(forward=1, right=0)`. It moves
one tile north when entered facing north and one tile east when entered facing
east.

## Data model

`rct2/segments.py` owns immutable per-segment geometry:

```python
Segment(type_id, name, forward_delta, right_delta, elevation_delta,
        direction_delta)
```

`direction_delta` is measured in quarter turns. Positive values turn right and
negative values turn left.

`rct2/geometry.py` owns positions and traversal:

```python
advance_position(position, segment_or_type) -> Position
trace_track(start, segments_or_types) -> list[Position]
is_closed_circuit(start, segments_or_types) -> bool
occupied_tiles(start, segments_or_types) -> list[OccupiedTile]
track_bounds(start, segments_or_types) -> Bounds
overlapping_tiles(tiles) -> dict[cell, segment_indices]
validate_track(start, segments_or_types, constraints...) -> ValidationResult
```

The traced path includes the starting position followed by one ending position
per segment.

## Scope of the first slice

The initial catalog covers every segment used by the Mine Train fixture:
stations, flat track, 25 and 60 degree slopes and their transitions, banking
transitions, common 3-tile and 5-tile quarter turns, two half-helix pieces,
brakes, and block brakes. Unknown TD6 segment types raise
`UnknownSegmentError`; they are not silently treated as straight track.

Footprints use OpenRCT2's per-sequence tile offsets. Exact occupied-cell repeats
are reported with their segment owners; classifying those repeats as legal
connections, overpasses, or collisions is a separate validation step.

`validate_track()` combines closure, known-segment, exact-cell collision,
footprint, height, and minimum-elevation checks. Horizontal bounds may be
rotated by 90 degrees by default because OpenRCT2 track designs can be rotated
when placed. Each failure has a stable code and a human-readable message.

## Done criteria

- Straight pieces move correctly in all four headings.
- Slopes update elevation without changing heading.
- Left and right turns update both position and heading.
- A sequence can be traced from an arbitrary starting position.
- A path is closed only when its final position and heading equal its start.
- Unsupported segment types fail with a useful error.
- The exported 89-piece Mine Train fixture traces back to its exact starting
  position, elevation, and heading.
- Its 224 occupied tile cells contain no exact 3D repeats, and their rotated
  `15 x 18` footprint matches the TD6 header's `18 x 15` dimensions.

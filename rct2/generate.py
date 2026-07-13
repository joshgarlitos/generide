"""Generate TD6 track files from Python.

Provides functions to create minimal coaster circuits and generate
valid .td6 files that OpenRCT2 can load.
"""

from pathlib import Path
from typing import Union

from rct2 import td6
from rct2.construction import default_lift_indices, validate_construction
from rct2.geometry import (
    Heading,
    Position,
    track_bounds,
)
from rct2.td6 import Entrance, Ride, TrackElement


# Segment type constants for readability
BEGIN_STATION = 0x02
END_STATION = 0x01
FLAT = 0x00
RIGHT_QUARTER_TURN_3 = 0x2B


def create_simple_circuit() -> list[int]:
    """Return a minimal closed circuit with station.

    Layout: station + 4 right turns with 2 flats.
    Forms an 8-segment closed loop that fits in roughly 4x6 tiles.
    """
    return [
        BEGIN_STATION,      # Start station
        END_STATION,        # End station
        RIGHT_QUARTER_TURN_3,  # Turn 1 (heading NORTH -> EAST)
        RIGHT_QUARTER_TURN_3,  # Turn 2 (EAST -> SOUTH)
        FLAT,               # Straight south
        FLAT,               # Straight south
        RIGHT_QUARTER_TURN_3,  # Turn 3 (SOUTH -> WEST)
        RIGHT_QUARTER_TURN_3,  # Turn 4 (WEST -> NORTH, returns to start)
    ]


def calculate_entrance_positions(segments: list[int]) -> tuple[Entrance, Entrance]:
    """Calculate entrance and exit positions adjacent to the station.

    The station consists of BEGIN_STATION at position 0 and END_STATION at
    position 1. Places entrance beside the first station piece and exit
    beside the second.

    Args:
        segments: List of segment type IDs (must start with station segments)

    Returns:
        Tuple of (entrance, exit) Entrance objects

    Raises:
        ValueError: If segments don't start with proper station pieces
    """
    if len(segments) < 2:
        raise ValueError("Track must have at least 2 segments for a station")
    if segments[0] != BEGIN_STATION or segments[1] != END_STATION:
        raise ValueError("Track must start with BEGIN_STATION and END_STATION")

    # Station occupies tiles (0, 0) and (0, 1) when starting at origin facing NORTH.
    # Place entrance at tile (1, 0) facing WEST (direction 3) toward the station.
    # Place exit at tile (1, 1) facing WEST toward the station.
    # Coordinates are in sub-tile units (32 per tile).
    entrance = Entrance(
        x=32,         # 1 tile east of station
        y=0,          # Aligned with begin_station
        z=0,          # Ground level
        direction=3,  # Facing WEST (toward station)
        is_exit=False,
    )
    exit_ = Entrance(
        x=32,         # 1 tile east of station
        y=32,         # Aligned with end_station
        z=0,          # Ground level
        direction=3,  # Facing WEST (toward station)
        is_exit=True,
    )
    return entrance, exit_


def calculate_space_required(segments: list[int]) -> tuple[int, int]:
    """Calculate the x and y space required for the track.

    Returns dimensions suitable for the TD6 header fields.

    Args:
        segments: List of segment type IDs

    Returns:
        Tuple of (x_space, y_space) in tiles
    """
    bounds = track_bounds(Position(), segments)
    return bounds.width, bounds.depth


def generate_ride(
    segments: list[int],
    template_path: Union[str, Path],
) -> Ride:
    """Generate a Ride structure using a template for header data.

    Uses the template file's header (ride type, vehicle data, colors, etc.)
    but replaces the track elements with the provided segments.

    Args:
        segments: List of segment type IDs (must form a closed circuit)
        template_path: Path to a .td6 file to use as a template

    Returns:
        A Ride object ready to be saved

    Raises:
        ValueError: If segments don't form a closed circuit
    """
    result = validate_construction(segments)
    if not result.valid:
        issues = ", ".join(f"{i.code}: {i.message}" for i in result.issues)
        raise ValueError(f"Invalid track: {issues}")

    # Load template
    template = td6.load(template_path)

    # Create track elements from segment IDs
    lift_indices = default_lift_indices(segments)
    elements = [
        TrackElement(
            segment_type=seg,
            chain_lift=(seg == BEGIN_STATION or index in lift_indices),
            inverted=False,
            colour_scheme=0,
            cable_lift=False,
        )
        for index, seg in enumerate(segments)
    ]

    # Calculate entrance/exit positions
    entrance, exit_ = calculate_entrance_positions(segments)

    # Calculate space requirements
    x_space, y_space = calculate_space_required(segments)

    # Build the new ride using template header
    return Ride(
        ride_type=template.ride_type,
        operating_mode=template.operating_mode,
        color_scheme=template.color_scheme,
        control_flags=template.control_flags,
        num_trains=1,           # Keep it simple: 1 train
        cars_per_train=2,       # 2 cars per train
        min_wait_time=template.min_wait_time,
        max_wait_time=template.max_wait_time,
        max_speed=template.max_speed,
        average_speed=template.average_speed,
        excitement=0,           # Will be calculated by game
        intensity=0,
        nausea=0,
        dat_data=template.dat_data,
        x_space_required=x_space,
        y_space_required=y_space,
        circuits_and_lift_speed=template.circuits_and_lift_speed,
        header=template.header,  # Preserve unparsed header bytes
        elements=elements,
        entrances=[entrance, exit_],
        scenery=b"\xff",        # Empty scenery (terminator only)
    )


def generate_simple_coaster(
    output_path: Union[str, Path],
    template_path: Union[str, Path, None] = None,
) -> None:
    """Generate a simple coaster TD6 file.

    Creates a minimal closed circuit Mine Train coaster and saves it.

    Args:
        output_path: Path to save the generated .td6 file
        template_path: Path to template .td6 file (defaults to manic_miner_test.td6)
    """
    if template_path is None:
        template_path = (
            Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"
        )

    segments = create_simple_circuit()
    ride = generate_ride(segments, template_path)
    td6.save(ride, output_path)

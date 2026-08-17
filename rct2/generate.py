"""Generate TD6 track files from Python.

Provides functions to create minimal coaster circuits and generate
valid .td6 files that OpenRCT2 can load.
"""

from collections import deque
from pathlib import Path
from typing import Union

from rct2 import td6
from rct2.construction import (
    BEGIN_STATION,
    DEFAULT_STATION_LENGTH,
    END_STATION,
    MIDDLE_STATION,
    MIN_HILL_HEIGHT,
    MIN_STATION_LENGTH,
    build_hill,
    build_station,
    default_lift_indices,
    station_length,
    validate_construction,
)
from rct2.geometry import (
    Heading,
    Position,
    occupied_tiles,
    track_bounds,
)
from rct2.td6 import Entrance, Ride, TrackElement


# Segment type constants for readability. Station structure lives in
# construction.py, since what makes a valid platform is a construction rule.
FLAT = 0x00
RIGHT_QUARTER_TURN_3 = 0x2B


def create_simple_circuit(
    station_length: int = DEFAULT_STATION_LENGTH,
) -> list[int]:
    """Return a minimal closed circuit with a station.

    Layout: station, two right turns, a straight run back, two more right turns.
    The straight run has to match the station's length for the loop to close,
    since the station pieces are themselves straight and form one side of it.

    Args:
        station_length: Number of station tiles (default DEFAULT_STATION_LENGTH).

    Returns:
        A closed circuit of `2 * station_length + 4` segments.
    """
    return (
        build_station(station_length)
        + [RIGHT_QUARTER_TURN_3, RIGHT_QUARTER_TURN_3]  # 180 degrees around
        + [FLAT] * station_length                       # back down the far side
        + [RIGHT_QUARTER_TURN_3, RIGHT_QUARTER_TURN_3]  # 180 degrees home
    )


def create_hill_circuit(
    hill_height: int = MIN_HILL_HEIGHT,
    station_length: int = DEFAULT_STATION_LENGTH,
) -> list[int]:
    """Return `create_simple_circuit`'s shape with a lift hill after the station.

    The same stadium loop, with the hill sharing the station's straight and the
    far side lengthened to match. Unlike `create_simple_circuit`, which is flat
    and liftless and which no train can actually complete, this closes *and*
    runs: the hill powers the train and gives back a drop over the game's
    rating threshold.

    That is what makes it the right seed for the part-based genetic algorithm.
    A hill is a straight run of 8 or more tiles, so inserting one into an
    already-closed flat loop displaces the end by more than `repair_circuit`'s
    budget can walk back, and every descendant of that seed starts open. Seeding
    from a loop that already contains the hill avoids the problem rather than
    asking repair to solve it.

    Args:
        hill_height: Height units the lift hill climbs and then drops.
        station_length: Number of station tiles.

    Returns:
        A closed, construction-valid, completable circuit.
    """
    straight = build_station(station_length) + build_hill(hill_height)
    return (
        straight
        + [RIGHT_QUARTER_TURN_3, RIGHT_QUARTER_TURN_3]  # 180 degrees around
        + [FLAT] * len(straight)                        # back down the far side
        + [RIGHT_QUARTER_TURN_3, RIGHT_QUARTER_TURN_3]  # 180 degrees home
    )


def calculate_entrance_positions(segments: list[int]) -> tuple[Entrance, Entrance]:
    """Calculate entrance and exit positions adjacent to the station.

    The station is the leading run of BEGIN, middles, END. Starting at the
    origin facing NORTH it occupies tiles (0, 0) through (0, n-1), so the
    entrance goes beside the first station tile and the exit beside the last.

    Which side they go on depends on the track. Pinning them east regardless
    of where the loop runs means that whenever the track happens to curve east
    it encloses them, and guests cannot path to an entrance the coaster has
    built a wall around. So try each side and take one where both structures
    sit on free ground that connects to open space outside the ride.

    Args:
        segments: List of segment type IDs (must start with station segments)

    Returns:
        Tuple of (entrance, exit) Entrance objects

    Raises:
        ValueError: If segments don't start with a well-formed station
    """
    length = station_length(segments)
    if length == 0:
        raise ValueError(
            "Track must start with a station: BEGIN_STATION, "
            "optional MIDDLE_STATION pieces, then END_STATION"
        )

    occupied = {(tile.x, tile.y) for tile in occupied_tiles(Position(), segments)}

    # East of the platform faces WEST back at it, and vice versa.
    sides = ((1, Heading.WEST), (-1, Heading.EAST))
    chosen_offset, chosen_facing = sides[0]
    for offset, facing in sides:
        tiles = [(offset, 0), (offset, length - 1)]
        if all(
            tile not in occupied and _reaches_open_ground(tile, occupied)
            for tile in tiles
        ):
            chosen_offset, chosen_facing = offset, facing
            break

    # Coordinates are in sub-tile units (32 per tile).
    entrance = Entrance(
        x=chosen_offset * 32,
        y=0,                          # Aligned with the first station piece
        z=0,                          # Ground level
        direction=int(chosen_facing),
        is_exit=False,
    )
    exit_ = Entrance(
        x=chosen_offset * 32,
        y=(length - 1) * 32,          # Aligned with the last station piece
        z=0,                          # Ground level
        direction=int(chosen_facing),
        is_exit=True,
    )
    return entrance, exit_


def _reaches_open_ground(
    tile: tuple[int, int],
    occupied: set[tuple[int, int]],
) -> bool:
    """Whether a guest could walk from `tile` to outside the ride's footprint.

    Flood fill across free tiles. Escaping the track's bounding box means the
    tile connects to the rest of the park; failing to means the coaster has
    enclosed it and no queue can reach it.
    """
    if not occupied:
        return True
    xs = [x for x, _ in occupied]
    ys = [y for _, y in occupied]
    min_x, max_x = min(xs) - 2, max(xs) + 2
    min_y, max_y = min(ys) - 2, max(ys) + 2

    seen = {tile}
    queue = deque([tile])
    while queue:
        x, y = queue.popleft()
        if x <= min_x or x >= max_x or y <= min_y or y >= max_y:
            return True
        for neighbour in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if neighbour not in seen and neighbour not in occupied:
                seen.add(neighbour)
                queue.append(neighbour)
    return False


def calculate_space_required(segments: list[int]) -> tuple[int, int]:
    """Calculate the x and y space required for the ride.

    Covers the entrance and exit as well as the track. They sit one tile off
    the platform, outside the track's own bounds, and the game still has to
    reserve room for them, so a width taken from `track_bounds` alone
    under-reports what the ride actually needs.

    Args:
        segments: List of segment type IDs

    Returns:
        Tuple of (x_space, y_space) in tiles
    """
    bounds = track_bounds(Position(), segments)
    width, depth = bounds.width, bounds.depth
    if station_length(segments):
        entrance, exit_ = calculate_entrance_positions(segments)
        for structure in (entrance, exit_):
            tile_x, tile_y = structure.x // 32, structure.y // 32
            width = max(width, tile_x - bounds.min_x + 1)
            depth = max(depth, tile_y - bounds.min_y + 1)
    return width, depth


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

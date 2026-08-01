"""Tests for coaster generation."""

import tempfile
from pathlib import Path

import pytest

from rct2 import td6
from rct2.construction import validate_construction
from rct2.generate import (
    BEGIN_STATION,
    DEFAULT_STATION_LENGTH,
    END_STATION,
    FLAT,
    MIDDLE_STATION,
    RIGHT_QUARTER_TURN_3,
    calculate_entrance_positions,
    calculate_space_required,
    create_simple_circuit,
    generate_ride,
    generate_simple_coaster,
    station_length,
)
from rct2.geometry import (
    Position,
    is_closed_circuit,
    occupied_tiles,
    track_bounds,
    validate_track,
)


TEMPLATE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def test_simple_circuit_is_closed():
    """The simple circuit returns to its starting position and heading."""
    segments = create_simple_circuit()
    assert is_closed_circuit(Position(), segments)


def test_simple_circuit_passes_validation():
    """The simple circuit has no validation issues."""
    segments = create_simple_circuit()
    result = validate_track(Position(), segments)
    assert result.valid, f"Validation failed: {result.issues}"


def test_simple_circuit_has_station():
    """The simple circuit starts with a full station platform."""
    segments = create_simple_circuit()
    length = station_length(segments)

    assert length == DEFAULT_STATION_LENGTH
    assert segments[0] == BEGIN_STATION
    assert segments[length - 1] == END_STATION
    assert all(seg == MIDDLE_STATION for seg in segments[1:length - 1])


def test_simple_circuit_closes_at_any_station_length():
    """The straight run has to track the station length for the loop to close."""
    for length in (2, 3, 4, 6, 9):
        segments = create_simple_circuit(station_length=length)
        assert station_length(segments) == length
        assert is_closed_circuit(Position(), segments)
        assert validate_construction(segments).valid


def test_entrance_positions_sit_at_each_end_of_the_platform():
    """Entrance beside the first station tile, exit beside the last."""
    segments = create_simple_circuit(station_length=6)
    entrance, exit_ = calculate_entrance_positions(segments)

    # One tile east of the platform, both facing WEST back toward it.
    assert entrance.x == 32
    assert entrance.y == 0        # beside the BEGIN piece
    assert entrance.is_exit is False
    assert entrance.direction == 3

    assert exit_.x == 32
    assert exit_.y == 5 * 32      # beside the END piece, 6 tiles along
    assert exit_.is_exit is True
    assert exit_.direction == 3


def test_entrance_positions_track_a_shorter_platform():
    _, exit_ = calculate_entrance_positions(create_simple_circuit(station_length=2))
    assert exit_.y == 32


def test_entrance_and_exit_tiles_stay_clear_of_track():
    """The structures must not land on a tile the track already occupies."""
    segments = create_simple_circuit(station_length=6)
    entrance, exit_ = calculate_entrance_positions(segments)
    occupied = {(t.x, t.y) for t in occupied_tiles(Position(), segments)}

    for structure in (entrance, exit_):
        assert (structure.x // 32, structure.y // 32) not in occupied


def test_entrance_positions_reject_invalid_segments():
    """calculate_entrance_positions raises on tracks without a proper station."""
    with pytest.raises(ValueError, match="must start with a station"):
        calculate_entrance_positions([BEGIN_STATION])

    with pytest.raises(ValueError, match="must start with a station"):
        calculate_entrance_positions([FLAT, FLAT])

    # A platform that never closes with an END piece is not a station.
    with pytest.raises(ValueError, match="must start with a station"):
        calculate_entrance_positions([BEGIN_STATION, MIDDLE_STATION, FLAT])


def test_space_required_covers_entrance_and_exit():
    """The declared footprint must cover the structures beside the platform.

    They can fall outside the track's own bounds, so a size taken from
    track_bounds alone under-reports what the ride needs and the game reserves
    less space than the design occupies.
    """
    segments = create_simple_circuit(station_length=6)
    bounds = track_bounds(Position(), segments)
    entrance, exit_ = calculate_entrance_positions(segments)
    x_space, y_space = calculate_space_required(segments)

    for structure in (entrance, exit_):
        tile_x, tile_y = structure.x // 32, structure.y // 32
        assert x_space >= tile_x - bounds.min_x + 1
        assert y_space >= tile_y - bounds.min_y + 1

    assert x_space >= bounds.width
    assert y_space >= bounds.depth


def test_space_required_grows_when_a_structure_falls_outside_the_track():
    """A track looping away from the structures leaves them outside its bounds."""
    # Mirror of the seed circuit: turning left sends the loop away from the
    # entrance column, which is where the evolved tracks end up.
    left_turn_circuit = (
        create_simple_circuit(station_length=6)[:6]
        + [0x2A, 0x2A] + [FLAT] * 6 + [0x2A, 0x2A]
    )
    bounds = track_bounds(Position(), left_turn_circuit)
    x_space, _ = calculate_space_required(left_turn_circuit)

    assert bounds.max_x == 0                 # track never goes east of the platform
    assert x_space == bounds.width + 1       # but the structures do


def test_space_required_matches_bounds():
    """calculate_space_required returns correct dimensions."""
    segments = create_simple_circuit()
    x_space, y_space = calculate_space_required(segments)

    # The circuit spans roughly 4x6 tiles based on the trace
    assert x_space > 0
    assert y_space > 0


def test_generate_ride_produces_valid_structure():
    """generate_ride creates a Ride with correct properties."""
    segments = create_simple_circuit()
    ride = generate_ride(segments, TEMPLATE)

    # Check basic structure
    assert ride.ride_type == 0x11  # Mine Train (from template)
    assert len(ride.elements) == len(segments)
    assert ride.num_trains == 1
    assert ride.cars_per_train == 2

    # Check entrances
    assert len(ride.entrances) == 2
    assert any(not e.is_exit for e in ride.entrances)  # Has entrance
    assert any(e.is_exit for e in ride.entrances)       # Has exit

    # Check space requirements are positive
    assert ride.x_space_required > 0
    assert ride.y_space_required > 0


def test_generate_ride_preserves_template_data():
    """generate_ride uses vehicle data from template."""
    segments = create_simple_circuit()
    ride = generate_ride(segments, TEMPLATE)
    template = td6.load(TEMPLATE)

    assert ride.dat_data == template.dat_data
    assert ride.ride_type == template.ride_type
    assert ride.operating_mode == template.operating_mode


def test_generate_ride_rejects_open_circuit():
    """generate_ride raises ValueError for tracks that don't close."""
    open_track = [BEGIN_STATION, END_STATION, FLAT]  # Doesn't return to start
    with pytest.raises(ValueError, match="closed circuit|open_circuit"):
        generate_ride(open_track, TEMPLATE)


def test_generate_ride_rejects_invalid_track():
    """generate_ride raises ValueError for tracks with validation issues."""
    # A single flat segment doesn't form a closed circuit
    with pytest.raises(ValueError, match="Invalid track|open_circuit"):
        generate_ride([FLAT], TEMPLATE)


def test_generate_ride_rejects_closed_track_with_invalid_banking():
    segments = create_simple_circuit()
    segments[2] = 0x2D
    with pytest.raises(ValueError, match="bank_transition"):
        generate_ride(segments, TEMPLATE)


def test_generated_ride_saves_and_loads():
    """A generated ride can be saved and loaded back."""
    segments = create_simple_circuit()
    ride = generate_ride(segments, TEMPLATE)

    with tempfile.NamedTemporaryFile(suffix=".td6", delete=False) as f:
        temp_path = Path(f.name)
    try:
        td6.save(ride, temp_path)

        # Load it back
        loaded = td6.load(temp_path)

        assert loaded.ride_type == ride.ride_type
        assert len(loaded.elements) == len(ride.elements)
        assert len(loaded.entrances) == len(ride.entrances)
        assert loaded.x_space_required == ride.x_space_required
        assert loaded.y_space_required == ride.y_space_required
    finally:
        temp_path.unlink()


def test_generate_simple_coaster_creates_file():
    """generate_simple_coaster creates a valid TD6 file."""
    with tempfile.NamedTemporaryFile(suffix=".td6", delete=False) as f:
        temp_path = Path(f.name)
    try:
        generate_simple_coaster(temp_path)

        # Verify the file exists and can be loaded
        assert temp_path.exists()
        ride = td6.load(temp_path)
        assert ride.ride_type == 0x11  # Mine Train
        assert len(ride.elements) == len(create_simple_circuit())
        assert station_length([e.segment_type for e in ride.elements]) == (
            DEFAULT_STATION_LENGTH
        )
    finally:
        temp_path.unlink()


def test_generated_ride_elements_have_chain_lift_on_station():
    """Station segments should have chain lift enabled."""
    segments = create_simple_circuit()
    ride = generate_ride(segments, TEMPLATE)

    # First element (BEGIN_STATION) should have chain lift
    assert ride.elements[0].chain_lift is True
    assert ride.elements[0].segment_type == BEGIN_STATION

    # Non-station elements should not have chain lift
    for element in ride.elements[2:]:
        assert element.chain_lift is False

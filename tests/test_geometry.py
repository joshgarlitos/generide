from pathlib import Path

import pytest

from rct2 import td6
from rct2.geometry import (
    Heading,
    Bounds,
    Position,
    advance_position,
    is_closed_circuit,
    occupied_tiles,
    overlapping_tiles,
    track_bounds,
    trace_track,
    validate_track,
)
from rct2.segments import Segment, UnknownSegmentError


FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        (Heading.NORTH, Position(10, 21, 3, Heading.NORTH)),
        (Heading.EAST, Position(11, 20, 3, Heading.EAST)),
        (Heading.SOUTH, Position(10, 19, 3, Heading.SOUTH)),
        (Heading.WEST, Position(9, 20, 3, Heading.WEST)),
    ],
)
def test_flat_moves_forward_in_each_heading(heading, expected):
    assert advance_position(Position(10, 20, 3, heading), 0x00) == expected


def test_slope_changes_elevation_without_changing_heading():
    assert advance_position(Position(2, 4, 10, Heading.EAST), 0x04) == Position(
        3, 4, 12, Heading.EAST
    )


def test_right_turn_rotates_local_movement_and_heading():
    assert advance_position(Position(0, 0, 0, Heading.NORTH), 0x2B) == Position(
        2, 1, 0, Heading.EAST
    )


def test_left_turn_rotates_local_movement_and_heading():
    assert advance_position(Position(10, 10, 0, Heading.EAST), 0x2A) == Position(
        11, 12, 0, Heading.NORTH
    )


def test_trace_track_includes_start_and_each_endpoint():
    assert trace_track(Position(), [0x00, 0x2B, 0x00]) == [
        Position(0, 0, 0, Heading.NORTH),
        Position(0, 1, 0, Heading.NORTH),
        Position(2, 2, 0, Heading.EAST),
        Position(3, 2, 0, Heading.EAST),
    ]


def test_four_right_turns_form_a_closed_circuit():
    assert is_closed_circuit(Position(), [0x2B] * 4)


def test_empty_track_is_closed_at_its_start():
    assert is_closed_circuit(Position(), [])


def test_track_ending_elsewhere_is_not_closed():
    assert not is_closed_circuit(Position(), [0x00])


def test_same_coordinates_with_wrong_heading_are_not_closed():
    turn_in_place = Segment(0xFE, "turn_in_place", forward_delta=0, direction_delta=1)
    assert not is_closed_circuit(Position(), [turn_in_place])


def test_unknown_segment_fails_clearly():
    with pytest.raises(UnknownSegmentError, match="0xFE"):
        advance_position(Position(), 0xFE)


def test_exported_mine_train_closes_its_circuit():
    ride = td6.decode(FIXTURE.read_bytes()[:-4])
    segment_types = [element.segment_type for element in ride.elements]

    assert len(segment_types) == 89
    assert is_closed_circuit(Position(), segment_types)


def test_turn_footprint_rotates_with_heading():
    tiles = occupied_tiles(Position(10, 10, 4, Heading.EAST), [0x2B])
    assert {(tile.x, tile.y, tile.z) for tile in tiles} == {
        (10, 10, 4), (10, 9, 4), (11, 10, 4), (11, 9, 4)
    }


def test_track_bounds_include_footprints_and_elevation():
    assert track_bounds(Position(), [0x2B, 0x04]) == Bounds(0, 2, 0, 1, 0, 2)


def test_overlapping_tiles_report_segment_owners():
    tiles = occupied_tiles(Position(), [0x00, 0x00])
    duplicated = tiles + [tiles[0].__class__(0, 0, 0, 2)]
    assert overlapping_tiles(duplicated) == {(0, 0, 0): [0, 2]}


def test_exported_mine_train_occupancy_matches_header_dimensions():
    ride = td6.decode(FIXTURE.read_bytes()[:-4])
    segment_types = [element.segment_type for element in ride.elements]
    tiles = occupied_tiles(Position(), segment_types)
    bounds = track_bounds(Position(), segment_types)

    assert len(tiles) == 224
    assert sorted((bounds.width, bounds.depth)) == sorted(
        (ride.x_space_required, ride.y_space_required)
    )
    assert overlapping_tiles(tiles) == {}


def test_exported_mine_train_passes_unified_validation():
    ride = td6.decode(FIXTURE.read_bytes()[:-4])
    result = validate_track(
        Position(),
        [element.segment_type for element in ride.elements],
        max_width=ride.x_space_required,
        max_depth=ride.y_space_required,
        max_height=22,
    )

    assert result.valid
    assert result.issues == ()
    assert result.end_position == Position()
    assert result.bounds == Bounds(-9, 5, -10, 7, 0, 22)


def test_validation_explains_open_circuit_and_bounds_failures():
    result = validate_track(
        Position(), [0x04], max_width=1, max_depth=1, max_height=1
    )

    assert not result.valid
    assert {issue.code for issue in result.issues} == {
        "open_circuit", "height_exceeded"
    }


def test_validation_reports_unknown_segment_without_crashing():
    result = validate_track(Position(), [0xFE])
    assert [issue.code for issue in result.issues] == ["unknown_segment"]
    assert "0xFE" in result.issues[0].message


def test_validation_detects_exact_cell_collision():
    stay_put = Segment(0xFE, "stay_put", forward_delta=0)
    turn_around = Segment(
        0xFD, "turn_around", forward_delta=0, direction_delta=2
    )
    result = validate_track(Position(), [stay_put, turn_around])

    assert any(issue.code == "collision" for issue in result.issues)


def test_validation_rejects_track_below_minimum_elevation():
    result = validate_track(Position(), [0x0A], min_elevation=0)
    assert any(issue.code == "below_minimum_elevation" for issue in result.issues)

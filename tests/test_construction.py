from pathlib import Path

from rct2 import td6
from rct2.construction import (
    bank_closing_path,
    bank_state_at,
    default_lift_indices,
    legal_bank_segments,
    legal_slope_segments,
    slope_closing_path,
    slope_state_at,
    validate_construction,
)
from rct2.evolution import Individual
from rct2.generate import create_simple_circuit


FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def test_simple_circuit_is_construction_valid():
    assert validate_construction(create_simple_circuit()).valid


def test_real_mine_train_is_construction_valid_with_exported_lifts():
    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {index for index, element in enumerate(ride.elements) if element.chain_lift}

    result = validate_construction(segments, lift_indices=lifts)

    assert result.valid, result.issues


def test_invalid_slope_transition_reports_segment_index():
    result = validate_construction([0x02, 0x01, 0x09])

    issue = next(issue for issue in result.issues if issue.code == "slope_transition")
    assert "segment 2" in issue.message


def test_closed_track_with_invalid_banking_is_not_valid():
    segments = create_simple_circuit()
    segments[2] = 0x2D

    result = validate_construction(segments)

    assert any(issue.code == "bank_transition" for issue in result.issues)
    assert not Individual(segments).is_valid()


def test_missing_first_hill_lift_is_reported():
    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]

    result = validate_construction(segments, lift_indices=set())

    assert any(issue.code == "missing_chain_lift" for issue in result.issues)


def test_default_lifts_cover_first_uphill_sequence():
    segments = [0x02, 0x01, 0x06, 0x04, 0x09, 0x00]
    assert default_lift_indices(segments) == {2, 3, 4}


def test_legal_slope_segments_from_flat_matches_entry_pieces():
    assert legal_slope_segments("flat") == {
        0x06: "up", 0x0C: "down", 0x18: "up", 0x19: "up", 0x1C: "down", 0x1D: "down",
    }


def test_legal_slope_segments_from_up_includes_steep_climb():
    assert legal_slope_segments("up") == {
        0x04: "up", 0x07: "steep_up", 0x09: "flat", 0x1A: "flat", 0x1B: "flat",
        0x22: "up", 0x23: "up",
    }


def test_legal_slope_segments_from_steep_up_stays_or_descends():
    assert legal_slope_segments("steep_up") == {0x05: "steep_up", 0x08: "up"}


def test_legal_bank_segments_from_flat_matches_entry_pieces():
    assert legal_bank_segments("flat") == {
        0x12: "left", 0x13: "right", 0x1A: "left", 0x1B: "right", 0x1E: "left", 0x1F: "right",
    }


def test_slope_closing_path_returns_shortest_non_combo_route_to_flat():
    assert slope_closing_path("flat") == []
    assert slope_closing_path("up") == [0x09]
    assert slope_closing_path("steep_up") == [0x08, 0x09]
    assert slope_closing_path("down") == [0x0F]
    assert slope_closing_path("steep_down") == [0x0E, 0x0F]


def test_bank_closing_path_returns_shortest_non_combo_route_to_flat():
    assert bank_closing_path("flat") == []
    assert bank_closing_path("left") == [0x14]
    assert bank_closing_path("right") == [0x15]


def test_slope_state_at_replays_prefix():
    segments = [0x02, 0x01, 0x06, 0x04, 0x09, 0x00]
    assert slope_state_at(segments, 2) == "flat"
    assert slope_state_at(segments, 3) == "up"
    assert slope_state_at(segments, 4) == "up"
    assert slope_state_at(segments, 5) == "flat"
    assert slope_state_at(segments) == "flat"


def test_bank_state_at_replays_prefix():
    segments = [0x02, 0x01, 0x12, 0x16, 0x14, 0x00]
    assert bank_state_at(segments, 2) == "flat"
    assert bank_state_at(segments, 3) == "left"
    assert bank_state_at(segments, 4) == "left"
    assert bank_state_at(segments, 5) == "flat"
    assert bank_state_at(segments) == "flat"

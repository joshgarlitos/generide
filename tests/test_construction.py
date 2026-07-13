from pathlib import Path

from rct2 import td6
from rct2.construction import default_lift_indices, validate_construction
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

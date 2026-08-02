"""Tests for the ratings-calibration dataset extractor."""

import tempfile
from pathlib import Path

from rct2 import td6
from rct2.calibration import CalibrationRow, extract_directory, extract_row, read_csv, write_csv
from rct2.generate import create_simple_circuit

FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def _rated_ride():
    ride = td6.load(FIXTURE)
    assert ride.excitement != 0  # fixture must actually carry ratings, or this test proves nothing
    return ride


def _unrated_ride():
    """A generide-authored ride: valid, but with no test-lap stats, like our own exports."""
    ride = td6.load(FIXTURE)
    ride.excitement = 0
    ride.intensity = 0
    ride.nausea = 0
    return ride


def test_extract_row_reads_stats_and_ratings_from_a_rated_design():
    row = extract_row(FIXTURE)

    assert row is not None
    assert row.name == FIXTURE.stem
    assert row.ride_type == 0x11
    assert row.excitement == 6.2
    assert row.intensity == 6.5
    assert row.nausea == 4.2
    assert row.drop_count == 6
    assert row.max_speed_mph == 36.0


def test_extract_row_skips_unrated_designs():
    """A design with no ratings (excitement 0) is not measured, not measured-as-zero."""
    with tempfile.NamedTemporaryFile(suffix=".td6", delete=False) as f:
        temp_path = Path(f.name)
    try:
        td6.save(_unrated_ride(), temp_path)
        assert extract_row(temp_path) is None
    finally:
        temp_path.unlink()


def test_extract_directory_walks_recursively_and_skips_unrated():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "nested").mkdir()
        td6.save(_rated_ride(), root / "rated.td6")
        td6.save(_unrated_ride(), root / "nested" / "unrated.td6")
        (root / "not_a_track.txt").write_text("ignore me")

        rows, failures = extract_directory(root)

        assert len(rows) == 1
        assert rows[0].name == "rated"
        assert failures == []


def test_extract_directory_reports_failures_without_stopping():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        td6.save(_rated_ride(), root / "good.td6")
        (root / "corrupt.td6").write_bytes(b"not a valid td6 file at all")

        rows, failures = extract_directory(root)

        assert len(rows) == 1
        assert len(failures) == 1
        assert failures[0][0].name == "corrupt.td6"


def test_csv_round_trip_preserves_values():
    row = extract_row(FIXTURE)
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        csv_path = Path(f.name)
    try:
        write_csv([row], csv_path)
        reloaded = list(read_csv(csv_path))
        assert len(reloaded) == 1
        assert reloaded[0] == row
    finally:
        csv_path.unlink()


def test_csv_round_trip_preserves_types_not_just_values():
    """A regression guard: reading the CSV back must not silently turn ints into
    strings or floats, which would break any downstream fitting code that
    does arithmetic on these columns."""
    row = extract_row(FIXTURE)
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        csv_path = Path(f.name)
    try:
        write_csv([row], csv_path)
        reloaded = next(iter(read_csv(csv_path)))
        assert isinstance(reloaded.ride_type, int)
        assert isinstance(reloaded.drop_count, int)
        assert isinstance(reloaded.excitement, float)
        assert isinstance(reloaded.max_speed_mph, float)
    finally:
        csv_path.unlink()


def test_generated_tracks_are_never_included():
    """generide's own output has never had a test lap run on it, so it must
    never appear in a calibration dataset alongside real designs."""
    from rct2.generate import generate_ride

    ride = generate_ride(create_simple_circuit(), FIXTURE)
    with tempfile.NamedTemporaryFile(suffix=".td6", delete=False) as f:
        temp_path = Path(f.name)
    try:
        td6.save(ride, temp_path)
        assert extract_row(temp_path) is None
    finally:
        temp_path.unlink()

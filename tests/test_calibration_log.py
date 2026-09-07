"""Tests for the oracle-calibration JSON-lines log."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from rct2.calibration_log import CalibrationRecord, append_record, read_records
from rct2.oracle import OracleResult, RideMeasurements


def test_rated_result_writes_one_line_with_rating_fields(tmp_path: Path):
    log_path = tmp_path / "calibration.jsonl"
    result = OracleResult(
        excitement=5.21,
        intensity=6.97,
        nausea=4.31,
        status="rated",
        measurements=RideMeasurements(highest_drop_height=16, max_speed=42.0),
    )
    record = CalibrationRecord.from_oracle_result(
        role="best", generation=10, rng_seed=123, segments=[1, 2, 3], result=result,
    )
    append_record(log_path, record)

    [written] = read_records(log_path)
    assert written.status == "rated"
    assert written.excitement == 5.21
    assert written.intensity == 6.97
    assert written.nausea == 4.31
    assert written.measurements == {
        "highest_drop_height": 16,
        "num_drops": None,
        "num_lift_hills": None,
        "max_speed": 42.0,
        "average_speed": None,
        "ride_length": None,
        "ride_time": None,
        "total_air_time": None,
        "max_positive_vertical_gs": None,
        "max_negative_vertical_gs": None,
        "max_lateral_gs": None,
    }


def test_duck_typed_measurements_does_not_raise_or_become_oracle_error(tmp_path: Path):
    log_path = tmp_path / "calibration.jsonl"
    # A stand-in for OracleResult, as an injected test `oracle_scorer` might
    # return -- measurements is a SimpleNamespace, not a real dataclass, and
    # only sets some of RideMeasurements' fields.
    result = SimpleNamespace(
        excitement=5.0,
        intensity=6.0,
        nausea=3.0,
        status="rated",
        detail="",
        stalled_at_index=None,
        stalled_at_type=None,
        measurements=SimpleNamespace(highest_drop_height=5, max_speed=10.0),
    )
    record = CalibrationRecord.from_oracle_result(
        role="best", generation=1, rng_seed=1, segments=[1, 2], result=result,
    )
    append_record(log_path, record)

    [written] = read_records(log_path)
    assert written.status == "rated"
    assert written.measurements == {
        "highest_drop_height": 5,
        "num_drops": None,
        "num_lift_hills": None,
        "max_speed": 10.0,
        "average_speed": None,
        "ride_length": None,
        "ride_time": None,
        "total_air_time": None,
        "max_positive_vertical_gs": None,
        "max_negative_vertical_gs": None,
        "max_lateral_gs": None,
    }


def test_stalled_result_writes_one_line_with_no_rating_fields(tmp_path: Path):
    log_path = tmp_path / "calibration.jsonl"
    result = OracleResult(
        excitement=None, intensity=None, nausea=None,
        status="stalled", stalled_at_index=42, stalled_at_type=0x06,
    )
    record = CalibrationRecord.from_oracle_result(
        role="worst", generation=20, rng_seed=7, segments=[4, 5], result=result,
    )
    append_record(log_path, record)

    [written] = read_records(log_path)
    assert written.status == "stalled"
    assert written.excitement is None
    assert written.intensity is None
    assert written.nausea is None
    assert written.stalled_at_index == 42
    assert written.stalled_at_type == 0x06


def test_placement_failed_result_is_distinguishable_by_status_alone(tmp_path: Path):
    log_path = tmp_path / "calibration.jsonl"
    result = OracleResult(
        excitement=None, intensity=None, nausea=None,
        status="placement_failed", detail="Mine Train Coaster 1 in the way",
    )
    record = CalibrationRecord.from_oracle_result(
        role="best", generation=0, rng_seed=1, segments=[9], result=result,
    )
    append_record(log_path, record)

    [written] = read_records(log_path)
    assert written.status == "placement_failed"
    assert written.detail == "Mine Train Coaster 1 in the way"


def test_oracle_error_record_writes_one_line_with_no_rating_fields(tmp_path: Path):
    log_path = tmp_path / "calibration.jsonl"
    record = CalibrationRecord.oracle_error(
        role="best", generation=5, rng_seed=99, segments=[1],
        error=FileNotFoundError("OpenRCT2 binary not found"),
    )
    append_record(log_path, record)

    [written] = read_records(log_path)
    assert written.status == "oracle_error"
    assert written.excitement is None
    assert written.intensity is None
    assert written.nausea is None
    assert "OpenRCT2 binary not found" in written.error


def test_two_calls_append_two_lines_in_order(tmp_path: Path):
    log_path = tmp_path / "calibration.jsonl"
    first = CalibrationRecord.oracle_error(
        role="best", generation=0, rng_seed=1, segments=[1], error=RuntimeError("first"),
    )
    second = CalibrationRecord.oracle_error(
        role="worst", generation=10, rng_seed=1, segments=[2], error=RuntimeError("second"),
    )
    append_record(log_path, first)
    append_record(log_path, second)

    written = read_records(log_path)
    assert len(written) == 2
    assert written[0].error == "first"
    assert written[1].error == "second"
    assert log_path.read_text().count("\n") == 2


def test_each_line_round_trips(tmp_path: Path):
    log_path = tmp_path / "calibration.jsonl"
    result = OracleResult(excitement=1.0, intensity=2.0, nausea=3.0, status="rated")
    record = CalibrationRecord.from_oracle_result(
        role="best", generation=3, rng_seed=42, segments=[1, 2, 3], result=result,
    )
    append_record(log_path, record)

    [written] = read_records(log_path)
    assert written == record


def test_append_record_creates_parent_directories(tmp_path: Path):
    log_path = tmp_path / "nested" / "calibration.jsonl"
    record = CalibrationRecord.oracle_error(
        role="best", generation=0, rng_seed=1, segments=[], error=RuntimeError("x"),
    )
    append_record(log_path, record)

    assert log_path.exists()


@pytest.mark.parametrize("segments", [[], [1, 2, 3, 4, 5]])
def test_segments_list_is_preserved(tmp_path: Path, segments):
    log_path = tmp_path / "calibration.jsonl"
    record = CalibrationRecord.oracle_error(
        role="best", generation=0, rng_seed=1, segments=segments, error=RuntimeError("x"),
    )
    append_record(log_path, record)

    [written] = read_records(log_path)
    assert written.segments == segments

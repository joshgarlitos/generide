"""Tests for the headless oracle's non-game-dependent parts."""

from rct2 import oracle, td6
from rct2.oracle import (
    TICKS_PER_SECOND,
    _build_plugin_source,
    _default_timeout_ticks,
    _assign_piece_indices,
    _parse_result,
    _parse_trace,
    _parse_trains,
)


def test_parses_a_rated_result():
    result = _parse_result("'GENERIDE_RESULT|status=rated|E=652|I=498|N=310'")
    assert result.status == "rated"
    assert result.excitement == 6.52
    assert result.intensity == 4.98
    assert result.nausea == 3.10


def test_parses_a_failure_with_no_ratings():
    result = _parse_result("'GENERIDE_RESULT|status=timeout'")
    assert result.status == "timeout"
    assert result.excitement is None
    assert result.intensity is None
    assert result.nausea is None


def test_parses_a_failure_with_a_detail():
    # Real OpenRCT2 output wraps each line in quotes and an ANSI reset code,
    # e.g. "'GENERIDE_RESULT|status=placement_failed:piece_20_type_12'\x1b[0m".
    result = _parse_result(
        "'GENERIDE_RESULT|status=placement_failed:piece_20_type_12'\x1b[0m"
    )
    assert result.status == "placement_failed"
    assert result.detail == "piece_20_type_12"


def test_ignores_lines_without_a_result():
    assert _parse_result("'GENERIDE_PLACE|i=0|type=1|error=0|msg='") is None
    assert _parse_result("just some other output") is None


def test_plugin_source_embeds_the_segment_list_and_build_site():
    source = _build_plugin_source([0, 4, 4, 9], base_x_tile=100, base_y_tile=100,
                                   timeout_ticks=2000, level_radius=20)
    assert "[0, 4, 4, 9]" in source
    assert "BASE_X_TILE = 100" in source
    assert "BASE_Y_TILE = 100" in source
    assert "registerPlugin" in source


def test_the_timeout_budget_covers_a_real_ride():
    # The old flat 2000-tick default was 50s of game time against Manic
    # Miner's real 83s, so a ride that ran perfectly came back as a timeout.
    ride = td6.load("data/sample_rides/manic_miner_test.td6")
    segments = [e.segment_type for e in ride.elements]

    budget_seconds = _default_timeout_ticks(segments) / TICKS_PER_SECOND

    assert budget_seconds > 83


def test_the_timeout_budget_has_a_floor_for_short_tracks():
    # A stub too short to simulate must still get a usable budget rather than
    # a couple of seconds scaled off a near-zero ride time.
    assert _default_timeout_ticks([0x02, 0x01, 0x00]) >= 4000


def test_reads_back_the_train_configuration_the_game_actually_used():
    # ridesetvehicle rejects our arguments, so the game runs its own defaults.
    # Reporting what we asked for would corrupt any calibration built on it.
    assert _parse_trains("'GENERIDE_TRAINS|numTrains=3|carsPerTrain=4'") == (3, 4)


def test_an_unreadable_train_configuration_is_not_a_number():
    assert _parse_trains("'GENERIDE_TRAINS|numTrains=-1|carsPerTrain=2'") is None
    assert _parse_trains("'GENERIDE_PLACE|i=0|type=1|error=0'") is None


# ---------------------------------------------------------------------------
# Which game binary score_track launches, and cleanup when it cannot.
# ---------------------------------------------------------------------------

import subprocess

import pytest


class _Launched(Exception):
    pass


def _capture_launch(monkeypatch):
    launched = []

    def fake_popen(argv, **kwargs):
        launched.append(argv)
        raise _Launched

    monkeypatch.setattr(oracle.subprocess, "Popen", fake_popen)
    return launched


def test_score_track_launches_the_overridden_binary(monkeypatch, tmp_path):
    monkeypatch.setenv("GENERIDE_OPENRCT2_BINARY", "/opt/games/OpenRCT2")
    launched = _capture_launch(monkeypatch)
    with pytest.raises(_Launched):
        oracle.score_track([0x02, 0x01])
    assert launched[0][0] == "/opt/games/OpenRCT2"


def test_score_track_defaults_to_the_mac_app_binary(monkeypatch):
    monkeypatch.delenv("GENERIDE_OPENRCT2_BINARY")
    launched = _capture_launch(monkeypatch)
    with pytest.raises(_Launched):
        oracle.score_track([0x02, 0x01])
    assert launched[0][0] == oracle.OPENRCT2_BINARY


def test_an_explicit_binary_argument_wins(monkeypatch):
    launched = _capture_launch(monkeypatch)
    with pytest.raises(_Launched):
        oracle.score_track([0x02, 0x01], binary="/elsewhere/OpenRCT2")
    assert launched[0][0] == "/elsewhere/OpenRCT2"


def test_a_failed_launch_removes_the_plugin_it_wrote(monkeypatch):
    # The conftest points the binary at a path that does not exist, so the
    # real Popen raises; the plugin written just before must not be left in
    # the game's plugin folder.
    with pytest.raises(FileNotFoundError):
        oracle.score_track([0x02, 0x01])
    assert oracle.PLUGIN_DIR.is_dir()
    assert list(oracle.PLUGIN_DIR.iterdir()) == []


# The game's per-tick car trace (U1 of the train-drag plan). The trace is how
# the simulator's speed model gets checked against the game's own, so the
# parser has to be exact about units: velocity and acceleration stay in the
# game's integer units and are converted only where they are compared.

def test_parses_a_trace_sample_keeping_the_games_units():
    sample = _parse_trace(
        "'GENERIDE_TRACE|t=655|v=777626|a=-353|mass=500|tt=0|prog=2"
        "|tx=3040|ty=3200|tz=148|z=148'\x1b[0m"
    )
    assert sample.tick == 655
    assert sample.velocity == 777626
    assert sample.acceleration == -353
    assert sample.mass == 500
    assert sample.track_type == 0
    assert (sample.track_x, sample.track_y, sample.track_z) == (3040, 3200, 148)


def test_a_trace_line_with_a_missing_field_is_skipped_not_a_crash():
    assert _parse_trace("'GENERIDE_TRACE|t=5|v=0'") is None
    assert _parse_trace("'GENERIDE_TRACE|t=5|v=undefined|a=0|mass=500|tt=1|prog=1|tx=1|ty=1|tz=1|z=1'") is None
    assert _parse_trace("'GENERIDE_STATS|maxSpeed=26'") is None


def test_the_plugin_only_logs_a_trace_when_asked():
    plain = _build_plugin_source([0, 4, 4, 9], 100, 100, 2000, 20)
    traced = _build_plugin_source([0, 4, 4, 9], 100, 100, 2000, 20, trace_every_ticks=5)
    assert "GENERIDE_TRACE" not in plain
    assert "GENERIDE_TRACE" in traced


def test_samples_are_matched_to_the_piece_the_car_is_on():
    placements = {0: (3200, 3200, 144, 2), 1: (3168, 3200, 144, 3), 2: (3136, 3200, 144, 3)}
    samples = [
        _parse_trace("'GENERIDE_TRACE|t=1|v=1|a=0|mass=500|tt=3|prog=1|tx=3136|ty=3200|tz=144|z=144'"),
        _parse_trace("'GENERIDE_TRACE|t=2|v=1|a=0|mass=500|tt=2|prog=1|tx=3200|ty=3200|tz=144|z=144'"),
    ]
    indexed = _assign_piece_indices(samples, placements)
    assert [s.piece_index for s in indexed] == [2, 0]


def test_a_sample_on_no_placed_piece_has_no_index():
    samples = [_parse_trace("'GENERIDE_TRACE|t=1|v=1|a=0|mass=500|tt=3|prog=1|tx=1|ty=1|tz=1|z=1'")]
    assert _assign_piece_indices(samples, {0: (3200, 3200, 144, 2)})[0].piece_index is None


def test_cars_per_train_is_read_from_the_cars_the_game_built():
    # The plugin echoes the cars it asked for, which the game ignores. The
    # count that matters is how many car entities exist per train, and train
    # mass (and so the speed-squared drag) depends on it.
    line = "'GENERIDE_TRAINS|numTrains=1|carsPerTrain=2|totalCars=7'"

    assert _parse_trains(line) == (1, 7)


def test_cars_per_train_divides_the_cars_across_the_trains():
    line = "'GENERIDE_TRAINS|numTrains=3|carsPerTrain=2|totalCars=12'"

    assert _parse_trains(line) == (3, 4)


def test_a_car_count_that_does_not_split_evenly_is_not_trusted():
    line = "'GENERIDE_TRAINS|numTrains=3|carsPerTrain=2|totalCars=10'"

    assert _parse_trains(line) == (3, 2)

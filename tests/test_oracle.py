"""Tests for the headless oracle's non-game-dependent parts."""

from rct2 import oracle, td6
from rct2.oracle import (
    TICKS_PER_SECOND,
    _build_plugin_source,
    _default_timeout_ticks,
    _parse_result,
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

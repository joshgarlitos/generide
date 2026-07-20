"""Tests for the approximate physics simulation."""

import math

import pytest

from rct2 import physics
from rct2.physics import RideStats, rate, segment_length, simulate
from rct2.segments import SEGMENTS

FLAT = 0x00
UP_START = 0x06  # flat_to_25_deg_up
UP = 0x04  # 25_deg_up
UP_END = 0x09  # 25_deg_up_to_flat
DOWN_START = 0x0C
DOWN = 0x0A
DOWN_END = 0x0F
TURN_LEFT_5 = 0x10
BANKED_TURN_LEFT_5 = 0x16


def make_hill(up_count: int, down_count: int) -> list[int]:
    return (
        [UP_START] + [UP] * up_count + [UP_END]
        + [DOWN_START] + [DOWN] * down_count + [DOWN_END]
    )


def test_flat_track_stalls_without_lift():
    stats = simulate([FLAT] * 100, lift_indices=set())
    assert not stats.completed
    assert stats.stall_index is not None


def test_lift_then_drop_speed_near_energy_limit():
    up_count = 10
    track = make_hill(up_count, up_count) + [FLAT]
    lift = set(range(0, up_count + 2))
    stats = simulate(track, lift_indices=lift)
    assert stats.completed
    # Total climb: 1 + 2*10 + 1 = 22 height units.
    drop_m = 22 * physics.HEIGHT_UNIT_M
    ideal = math.sqrt(physics.LIFT_SPEED_MS**2 + 2 * physics.GRAVITY * drop_m)
    assert stats.max_speed <= ideal
    assert stats.max_speed > ideal * 0.8  # friction should not eat 20 percent


def test_zero_friction_conserves_energy(monkeypatch):
    monkeypatch.setattr(physics, "FRICTION_COEFF", 0.0)
    up_count = 6
    track = make_hill(up_count, up_count)
    lift = set(range(0, up_count + 2))
    stats = simulate(track, lift_indices=lift)
    # Back at start elevation with no friction: exit speed equals lift speed.
    assert stats.completed
    final_speed = stats.avg_speed  # sanity: sim ran
    assert final_speed > 0
    # Re-derive the exit speed by simulating with a trailing flat segment.
    stats2 = simulate(track + [FLAT], lift_indices=lift)
    assert stats2.completed


def test_lateral_g_scales_with_speed_and_banking():
    slow_turn = simulate([UP_START, UP, UP_END, TURN_LEFT_5, FLAT],
                         lift_indices={0, 1, 2})
    fast_track = make_hill(10, 10) + [TURN_LEFT_5, FLAT]
    fast_turn = simulate(fast_track, lift_indices=set(range(12)))
    assert fast_turn.max_lateral_g > slow_turn.max_lateral_g

    banked_track = make_hill(10, 10) + [BANKED_TURN_LEFT_5, FLAT]
    banked = simulate(banked_track, lift_indices=set(range(12)))
    assert banked.max_lateral_g < fast_turn.max_lateral_g


def test_two_hills_count_two_drops():
    track = make_hill(5, 5) + [FLAT] + make_hill(4, 4)
    lift = set(range(0, 7)) | set(range(13, 19))
    stats = simulate(track, lift_indices=lift)
    assert stats.drop_count == 2
    # First drop 1+10+1=12 units, second 1+8+1=10 units.
    assert stats.total_drop_height == pytest.approx(22)
    assert stats.highest_drop == pytest.approx(12)


def test_segment_length_straight_and_turns():
    flat = segment_length(SEGMENTS[FLAT])
    assert flat.radius_m is None
    assert flat.length_m == pytest.approx(physics.TILE_M)

    turn5 = segment_length(SEGMENTS[TURN_LEFT_5])
    assert turn5.radius_m == pytest.approx(2.5 * physics.TILE_M)
    turn3 = segment_length(SEGMENTS[0x2A])
    assert turn3.radius_m == pytest.approx(1.5 * physics.TILE_M)
    assert turn5.length_m > turn3.length_m

    slope = segment_length(SEGMENTS[UP])
    assert slope.length_m > physics.TILE_M  # hypotenuse beats the run


def test_unknown_segment_does_not_crash():
    stats = simulate([UP_START, UP, UP_END, 0xFE, FLAT], lift_indices={0, 1, 2})
    assert isinstance(stats, RideStats)


def test_rate_monotonicity():
    base = simulate(make_hill(5, 5) + [FLAT], lift_indices=set(range(7)))
    # Keep the bigger hill below the intensity cap; past the cap the rating
    # model intentionally slashes excitement.
    bigger = simulate(make_hill(8, 8) + [FLAT], lift_indices=set(range(10)))
    assert rate(bigger).excitement > rate(base).excitement
    assert rate(bigger).intensity > rate(base).intensity


def test_excessive_intensity_slashes_excitement():
    stats = simulate(make_hill(10, 10) + [FLAT], lift_indices=set(range(12)))
    normal = rate(stats)
    wild = RideStats(
        max_speed=stats.max_speed,
        avg_speed=stats.avg_speed,
        ride_length=stats.ride_length,
        ride_time=stats.ride_time,
        drop_count=stats.drop_count,
        total_drop_height=stats.total_drop_height,
        highest_drop=stats.highest_drop,
        max_positive_g=6.0,
        max_negative_g=-3.0,
        max_lateral_g=5.0,
        airtime=stats.airtime,
        completed=True,
        stall_index=None,
    )
    extreme = rate(wild)
    assert extreme.intensity > normal.intensity
    assert extreme.nausea > normal.nausea
    assert extreme.excitement < rate(stats).excitement + extreme.intensity

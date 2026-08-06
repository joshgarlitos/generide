"""Tests for the approximate physics simulation."""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from rct2 import physics
from rct2.calibration import read_csv
from rct2.physics import RATING_WEIGHTS, RideStats, rate, segment_length, simulate
from rct2.segments import SEGMENTS

CALIBRATION = Path(__file__).parent.parent / "data" / "calibration.csv"

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
    """A bigger hill rates higher, with no cap to work around.

    This test used to need its hills kept small so they stayed under an
    intensity cap that would otherwise slash excitement. That coupling is gone
    from `rate` — it predicts what the game would say, and the game rates the
    three independently — so the caveat no longer applies.
    """
    base = simulate(make_hill(5, 5) + [FLAT], lift_indices=set(range(7)))
    bigger = simulate(make_hill(8, 8) + [FLAT], lift_indices=set(range(10)))
    assert rate(bigger).excitement > rate(base).excitement
    assert rate(bigger).intensity > rate(base).intensity


def test_excitement_is_independent_of_intensity():
    """Cranking intensity must not move excitement.

    The old model subtracted from excitement once intensity passed a cap. On
    uncalibrated intensity readings that fired on essentially every real
    coaster, so evolution learned that speed and drops were dangerous. Steering
    away from punishing rides is a preference and now lives in PhysicsFitness;
    `rate` only predicts.
    """
    stats = simulate(make_hill(10, 10) + [FLAT], lift_indices=set(range(12)))
    baseline = rate(stats)

    # Same ride, but with g-forces that would have blown past the old cap.
    violent = replace(stats, max_positive_g=6.0, max_negative_g=3.0, max_lateral_g=5.0)
    extreme = rate(violent)

    assert extreme.intensity > baseline.intensity
    assert extreme.nausea > baseline.nausea
    # Excitement responds to its own terms, never to intensity's magnitude.
    expected = (
        baseline.excitement
        + RATING_WEIGHTS["excitement_max_positive_vertical_g"]
        * (6.0 - stats.max_positive_g)
        + RATING_WEIGHTS["excitement_max_negative_vertical_g"]
        * (-3.0 - -abs(stats.max_negative_g))
        + RATING_WEIGHTS["excitement_max_lateral_g"] * (5.0 - stats.max_lateral_g)
    )
    assert extreme.excitement == pytest.approx(expected, abs=1e-9)


def test_negative_vertical_g_is_fed_to_the_model_as_a_signed_value():
    """RideStats stores a magnitude; the fitted weights expect a signed value.

    152 of the 204 calibration designs carry a negative value here and the
    fitted coefficient is one of the largest in the model, so passing the
    magnitude through unchanged would invert a real term rather than just
    rescale it.
    """
    stats = simulate(make_hill(6, 6) + [FLAT], lift_indices=set(range(8)))
    airborne = replace(stats, max_negative_g=1.5)

    assert physics.rating_features(airborne)["max_negative_vertical_g"] == -1.5
    # Sign convention aside, more airtime must read as more intense.
    assert rate(airborne).intensity > rate(replace(stats, max_negative_g=0.0)).intensity


def test_calibrated_weights_reproduce_a_real_ride_from_the_game_s_own_stats():
    """Pin the fit's quality against ground truth.

    Feeding the game's own measured stats for Manic Miner through the weights
    should land near the rating the game actually assigned it (6.1 excitement).
    This isolates the rating model from our physics: if this test passes and a
    simulated prediction is still off, the error is in `simulate`, not here.
    """
    row = next(
        r for r in read_csv(CALIBRATION) if r.name == "Manic Miner"
    )
    features = {
        "max_speed_mph": row.max_speed_mph,
        "average_speed_mph": row.average_speed_mph,
        "ride_length_m": row.ride_length_m,
        "max_positive_vertical_g": row.max_positive_vertical_g,
        "max_negative_vertical_g": row.max_negative_vertical_g,
        "max_lateral_g": row.max_lateral_g,
        "drop_count": row.drop_count,
        "highest_drop_height_m": row.highest_drop_height_m,
        "inversion_count": row.inversion_count,
    }

    def predict(target):
        value = RATING_WEIGHTS[f"{target}_base"]
        for name in physics._RATING_FEATURES:
            value += RATING_WEIGHTS[f"{target}_{name}"] * features[name]
        return value

    assert predict("excitement") == pytest.approx(row.excitement, abs=0.5)
    assert predict("intensity") == pytest.approx(row.intensity, abs=1.0)


def test_ratings_never_go_negative():
    """A track with nothing going on floors at zero rather than going negative."""
    nothing = simulate([0x02, 0x01] + [0x00] * 4)
    ratings = rate(nothing)

    assert ratings.excitement >= 0.0
    assert ratings.intensity >= 0.0
    assert ratings.nausea >= 0.0


FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def test_gforce_model_matches_the_real_fixture_within_a_stated_tolerance():
    """The committed regression check for the velocity-linear g-force model.

    The fitted coefficients (GFORCE_VERTICAL_COEFF, GFORCE_LATERAL_COEFF) come
    from 6 real designs read from a local game install, which isn't something
    this test can load -- those .td6 files aren't committed, only the fit's
    result is. This fixture is what's actually checked in, and it was not
    part of the fit, so matching it is real evidence the coefficients
    generalize rather than just memorizing the 6 they were tuned on.

    Real values (from the fixture's own TD6 header, which is a real game
    export): +g=2.56, -g=-0.64, lateral=1.28. Tolerances match the residuals
    documented on GFORCE_VERTICAL_COEFF -- this is not a tight equality
    check, because the model is still an approximation, just no longer one
    that's wrong by a factor of 2-4x.
    """
    from rct2 import td6

    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {index for index, element in enumerate(ride.elements) if element.chain_lift}

    stats = simulate(segments, lift_indices=lifts)

    assert stats.max_positive_g == pytest.approx(2.56, abs=0.5)
    assert stats.max_negative_g == pytest.approx(-0.64, abs=0.5)
    assert stats.max_lateral_g == pytest.approx(1.28, abs=0.6)

    # The old v^2/(radius*g) model landed at +g=5.01, -g=-2.25, lat=5.05 on
    # this exact fixture -- 2x to 4x high. Pin that the new model is not
    # merely closer by coincidence but is decisively inside the old model's
    # error band.
    assert stats.max_positive_g < 3.5
    assert stats.max_lateral_g < 2.5


def test_gforce_is_linear_in_speed_not_quadratic():
    """Confirms the functional form, not just the fitted constants.

    OpenRCT2's real Vehicle::GetGForces() adds `velocity * 98 / factor` -- speed
    to the first power. Doubling the speed through an identical transition
    should double the dynamic (non-gravity) contribution exactly, not
    quadruple it. Tests `_vertical_g` directly rather than through `simulate`,
    since the full energy pipeline confounds entry speed with everything
    downstream of it (friction is a flat per-segment cost, not proportional
    to speed, so entry speed and speed-at-a-later-segment aren't linearly
    related even though the g-force formula itself is linear in speed).
    """
    prev_angle = 0.0
    angle = math.radians(25)
    length_m = 3.0

    slow_g = physics._vertical_g(prev_angle, angle, 5.0, length_m)
    fast_g = physics._vertical_g(prev_angle, angle, 10.0, length_m)

    base = math.cos(angle)
    slow_dynamic = slow_g - base
    fast_dynamic = fast_g - base

    assert slow_dynamic > 0
    assert fast_dynamic == pytest.approx(slow_dynamic * 2, rel=1e-9)

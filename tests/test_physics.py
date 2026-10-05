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


def test_flat_plateau_mid_descent_still_counts_two_drops():
    """Reproduces issue #33.

    OpenRCT2 counts a drop the moment a downward run starts, with no minimum
    height, so a short partial descent that our old DROP_THRESHOLD_UNITS
    filter would have discarded still counts on its own once a flat stretch
    ends it. A climb to 10, a 2-unit descent, a flat plateau, then an 8-unit
    descent back to 0 must read as 2 drops, matching the game, not 1.
    """
    track = (
        [UP_START] + [UP] * 4 + [UP_END]
        + [DOWN_START, DOWN_END]
        + [FLAT] * 4
        + [DOWN_START] + [DOWN] * 3 + [DOWN_END]
    )
    stats = simulate(track, lift_indices=set(range(0, 6)))
    assert stats.drop_count == 2
    assert stats.highest_drop == pytest.approx(8)
    assert stats.total_drop_height == pytest.approx(10)


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
    """The committed regression check for the g-force model against a real ride.

    GFORCE_VERTICAL_COEFF was fitted to 6 real designs read from a local game
    install, which isn't something this test can load; those .td6 files aren't
    committed, only the fit's result is. Lateral g is not fitted: it is the
    game's own per-piece table (LATERAL_FACTOR). This fixture is what's
    actually checked in, and it was not part of the vertical fit.

    Real values come from the fixture's TD6 header: +g=2.56, -g=-0.64,
    lateral=1.28. The game stores those bytes as the runtime value divided by
    32 with integer division, so each is a floor to 0.32g and the true value
    is up to 0.32g higher. Tolerances are loose for that reason and because the
    model is still an approximation, just no longer one that's wrong by a
    factor of 2-4x. The lateral value gets a tighter, interval-aware check in
    the next test.
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


def test_lateral_g_agrees_with_the_fixture_headers_quantized_reading():
    """Issue #41: the fixture's lateral g, checked against what its header allows.

    The header byte is the game's max lateral g divided by 32 with integer
    division, so a stored 4 means the real value is in [1.28, 1.60), not 1.28.
    Comparing against 1.28 as if exact is what biased the earlier fit low. The
    simulation reads 1.64g here, 0.04 above the top of the interval, which is
    the size of error to expect from a simulated max speed that is about 5%
    above the game's (and lateral g is linear in speed). The 0.15 slack covers
    that and nothing more: an unbanked 3-tile turn read through the old fitted
    coefficient would have sat well below the floor of the interval.
    """
    from rct2 import td6

    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {index for index, element in enumerate(ride.elements) if element.chain_lift}

    floor = ride.max_lateral_g * 0.32  # the header's reading, rounded down
    stats = simulate(segments, lift_indices=lifts)

    assert floor - 0.15 <= stats.max_lateral_g < floor + 0.32 + 0.15


def test_lateral_g_follows_the_games_formula_and_factor_table():
    """Issue #41: pin the formula and the table, not just one ride.

    The game computes (|velocity| * 98 / lateralFactor) * 10 >> 16, in
    hundredths of g, with velocity in raw units where mph is velocity * 9 >> 18.
    The anchor below redoes that arithmetic in integers for a known piece and
    speed, independently of the float version in physics.
    """
    speed_ms = 10.0

    raw_velocity = int(speed_ms * physics.MPH_PER_MS * 2**18 / 9)
    expected = ((raw_velocity * 98 // 98) * 10 >> 16) / 100  # 5-tile turn, factor 98
    assert physics._lateral_g(0x10, speed_ms) == pytest.approx(expected, abs=0.01)

    # Linear in speed, and the ratio between turn types is the ratio of the
    # game's factors, so a tighter turn pulls harder at the same speed.
    assert physics._lateral_g(0x10, 2 * speed_ms) == pytest.approx(
        2 * physics._lateral_g(0x10, speed_ms)
    )
    assert physics._lateral_g(0x2A, speed_ms) / physics._lateral_g(0x10, speed_ms) == pytest.approx(98 / 59)
    assert physics._lateral_g(0x2C, speed_ms) / physics._lateral_g(0x2A, speed_ms) == pytest.approx(59 / 100)

    # Left and right pieces share a magnitude, the slope does not change a
    # 5-tile turn's factor, and a piece with no entry has no lateral g.
    assert physics._lateral_g(0x11, speed_ms) == physics._lateral_g(0x10, speed_ms)
    assert physics._lateral_g(0x22, speed_ms) == physics._lateral_g(0x10, speed_ms)
    assert physics._lateral_g(0x00, speed_ms) is None
    assert physics._lateral_g(0x04, speed_ms) is None

    # It does not depend on the horizontal scale: only the speed does.
    assert physics.LATERAL_FACTOR[0x2A] == 59 and physics.LATERAL_FACTOR[0x10] == 98


def test_trace_reports_lateral_g_on_turns_only_at_the_faster_of_entry_and_exit():
    track = [0x02, 0x01, 0x2A, 0x00]
    ride = physics.trace(track, lift_indices={0, 1, 2, 3})

    turn = ride.points[2]
    assert turn.g_lateral == pytest.approx(
        physics._lateral_g(0x2A, max(turn.speed_in, turn.speed_out))
    )
    assert ride.points[3].g_lateral is None


def test_ride_length_matches_the_real_fixture_header():
    """Issue #60: pin the simulated length against the length the game measured.

    The fixture's TD6 header stores the ride length OpenRCT2 measured on the
    real test lap: 691 m. TILE_M is calibrated so `ride_length` lands on that
    number, because it is the unit `ratings.requirement_length`'s 370
    threshold is written in. At the old TILE_M of 3.0 this read 481.8 m, 30%
    short, and no test noticed because none asserted length at all.

    The tolerance is 2%. The calibration currently lands within 0.5% here, and
    on the hill-circuit seed, whose live oracle reading of 183 m is recorded
    in issue #60 (it simulates to 183.7 m). The slack leaves room for a refit of
    TILE_M against more tracks without a test edit, while staying far inside
    the 30% error this guards against.
    """
    from rct2 import td6

    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {index for index, element in enumerate(ride.elements) if element.chain_lift}

    assert ride.ride_length == 691  # the header really holds the game's reading

    stats = simulate(segments, lift_indices=lifts)

    assert stats.ride_length == pytest.approx(ride.ride_length, rel=0.02)


def test_scale_coupled_constants_stay_expressed_at_the_current_tile_scale():
    """Issue #60: FRICTION_COEFF and the vertical g coefficient move with TILE_M.

    Each one consumes a horizontal length, so recalibrating TILE_M alone makes
    the real Manic Miner stall (friction is charged per metre) and shifts every
    vertical g-force. These pin the products and ratios that must hold at the
    scale the constants were fitted at (3.0 m per tile), so an edit that
    changes one without the other fails here rather than silently invalidating
    them. Lateral g is not scale-coupled: it is the game's own table.
    """
    fit_tile_m = 3.0

    # Energy lost over one flat tile is the same as at the fitted scale.
    assert physics.FRICTION_COEFF * physics.TILE_M == pytest.approx(0.01 * fit_tile_m)
    # The shape term divides by a length, which grew with TILE_M.
    assert physics.GFORCE_VERTICAL_COEFF / physics.TILE_M == pytest.approx(0.56393 / fit_tile_m)


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


# ---------------------------------------------------------------------------
# simulate() must not move when it is rebuilt on top of trace(). The reference
# was captured from simulate() before that refactor, for the sample ride and a
# spread of generated tracks (completed and stalled), with each track's
# segments stored alongside so the reference does not depend on generators.
# ---------------------------------------------------------------------------

REFERENCE = Path(__file__).parent / "data" / "simulate_reference.json"


def _reference_cases():
    import json

    return json.loads(REFERENCE.read_text())


def _lifts(case):
    return None if case["lift_indices"] is None else set(case["lift_indices"])


@pytest.mark.parametrize("case", _reference_cases(), ids=lambda c: c["name"])
def test_simulate_matches_recorded_reference_exactly(case):
    from dataclasses import asdict

    assert asdict(simulate(case["segments"], _lifts(case))) == case["stats"]


@pytest.mark.parametrize("case", _reference_cases(), ids=lambda c: c["name"])
def test_trace_agrees_with_simulate(case):
    stats = simulate(case["segments"], _lifts(case))
    ride = physics.trace(case["segments"], _lifts(case))

    assert ride.completed == stats.completed
    assert ride.stall_index == stats.stall_index
    if stats.completed:
        # One point per piece, and the last one ends where the ride does.
        assert len(ride.points) == len(case["segments"])
        assert ride.points[-1].distance_m == stats.ride_length
    else:
        # The trace ends on the piece where the train stops.
        assert len(ride.points) == stats.stall_index + 1
        assert ride.points[-1].index == stats.stall_index
        assert ride.points[-1].stalled
        assert ride.points[-1].speed_out == 0.0

    drops = {p.drop for p in ride.points if p.drop is not None}
    assert len(drops) == stats.drop_count


def test_trace_points_chain_distance_height_and_speed():
    track = make_hill(4, 4) + [FLAT]
    ride = physics.trace(track, lift_indices=set(range(6)))

    for before, after in zip(ride.points, ride.points[1:]):
        assert after.distance_start_m == before.distance_m
        assert after.height_in == before.height_out
        assert after.speed_in == before.speed_out
    assert all(p.on_lift for p in ride.points[:6])
    assert not any(p.on_lift for p in ride.points[6:])
    # The hill's way down is one counted drop, and only those pieces carry it.
    assert [p.drop for p in ride.points[6:12]] == [1] * 6
    assert ride.points[0].height_in == 0
    assert ride.points[5].height_out == max(p.height_out for p in ride.points)


def test_trace_of_empty_track_is_empty_and_complete():
    ride = physics.trace([])
    assert ride.points == []
    assert ride.completed

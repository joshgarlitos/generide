"""Tests for the ported OpenRCT2 rating calculation.

The point of these is to pin behaviour the old fitted model could not express,
above all the requirement checks that divide ratings. See issue #40.
"""

from pathlib import Path

import pytest

from rct2 import physics, ratings, td6
from rct2.ratings import RatingInputs, Tuple3, TurnCounts

FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def load_fixture():
    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {i for i, e in enumerate(ride.elements) if e.chain_lift}
    return ride, segments, lifts


def inputs_from_header(ride, segments) -> RatingInputs:
    """Drive the port from the game's own measured stats rather than ours.

    This is what isolates the formula from our simulation: the header of a
    real export carries the numbers the game measured on its own test lap, so
    feeding those in tests the ported arithmetic alone.
    """
    flat, banked, sloped = ratings.count_turns(segments)
    return RatingInputs(
        max_speed_units=ride.max_speed,
        average_speed_units=ride.average_speed,
        ride_length_m=ride.ride_length,
        duration_s=0,
        max_positive_g=int(ride.max_positive_vertical_g_force * 100),
        max_negative_g=int(ride.max_negative_vertical_g_force * 100),
        max_lateral_g=int(ride.max_lateral_g_force * 100),
        num_drops=ride.drop_count,
        highest_drop_height=ride.highest_drop_height,
        cars_per_train=ride.cars_per_train,
        flat_turns=flat,
        banked_turns=banked,
        sloped_turns=sloped,
    )


def test_fixture_intensity_and_nausea_land_close_to_the_game():
    """Fed the game's own stats, the port should reproduce its own ratings.

    Intensity and nausea come out within a few tenths, which is the evidence
    that the transcribed constants and fixed-point arithmetic are right.
    Excitement is checked separately below because it is knowingly incomplete.
    """
    ride, segments, _ = load_fixture()
    result = ratings.calculate(inputs_from_header(ride, segments))

    assert result.intensity / 100 == pytest.approx(ride.intensity_rating, abs=0.5)
    assert result.nausea / 100 == pytest.approx(ride.nausea_rating, abs=0.5)


def test_fixture_excitement_is_short_by_the_omitted_bonuses():
    """Documents the port's known incompleteness instead of hiding it.

    `calculate` skips bonus_sheltered, bonus_proximity and bonus_scenery
    because they read the surrounding park rather than the track. All three
    are excitement-weighted (proximity 0.33, scenery 0.26), so the residual
    should sit almost entirely on excitement, and it does: about 1.7 low on
    this fixture while intensity and nausea land within half a point.

    If someone implements proximity and this test starts failing high, that is
    the expected outcome and the bound should move, not the feature.
    """
    ride, segments, _ = load_fixture()
    result = ratings.calculate(inputs_from_header(ride, segments))
    shortfall = ride.excitement_rating - result.excitement / 100

    assert 1.0 < shortfall < 2.5, (
        f"excitement shortfall {shortfall:.2f} outside the documented band; "
        "the omitted park-dependent bonuses should account for roughly 1.7"
    )


def test_failing_a_requirement_halves_every_rating():
    """The behaviour no linear model could represent.

    The game divides all three ratings when a ride misses a threshold. Two
    otherwise identical rides either side of the drop-height requirement must
    differ by exactly a factor of two, not by a smooth increment.
    """
    base = dict(
        max_speed_units=20, average_speed_units=10, ride_length_m=500,
        duration_s=60, max_positive_g=200, max_negative_g=-50,
        max_lateral_g=100, num_drops=5,
        flat_turns=TurnCounts(), banked_turns=TurnCounts(), sloped_turns=TurnCounts(),
    )
    threshold = ratings.MINE_TRAIN["requirement_drop_height"][0]

    clears = ratings.calculate(RatingInputs(highest_drop_height=threshold, **base))
    fails = ratings.calculate(RatingInputs(highest_drop_height=threshold - 1, **base))

    # Not merely lower: halved, because the requirement is a division.
    assert fails.intensity == clears.intensity // 2
    assert fails.nausea == clears.nausea // 2


def test_requirement_length_halves_every_rating():
    """Same behaviour as the drop-height requirement, for track length.

    Confirmed in-game 2026-08-29: rebuilding the real Manic Miner with one
    station instead of two, so this requirement reads the whole circuit
    instead of half of it, took the oracle's rating from 3.12/3.48/2.55 to
    6.19/7.03/5.08. See docs/devlog.md and the comment in ratings.calculate.
    """
    base = dict(
        max_speed_units=20, average_speed_units=10, highest_drop_height=10,
        duration_s=60, max_positive_g=200, max_negative_g=-50,
        max_lateral_g=100, num_drops=5,
        flat_turns=TurnCounts(), banked_turns=TurnCounts(), sloped_turns=TurnCounts(),
    )
    threshold = ratings.MINE_TRAIN["requirement_length"][0]

    clears = ratings.calculate(RatingInputs(ride_length_m=threshold, **base))
    fails = ratings.calculate(RatingInputs(ride_length_m=threshold - 1, **base))

    assert fails.intensity == clears.intensity // 2
    assert fails.nausea == clears.nausea // 2


def test_requirements_compound():
    """Two failed requirements quarter the rating rather than halving it once.

    Each input tested by a requirement also feeds a bonus, so these stay one
    unit either side of the thresholds to keep the bonus difference negligible
    and leave the divisions as the effect being measured. That is also why the
    comparison carries a small tolerance instead of demanding exact halves.
    """
    drop_threshold = ratings.MINE_TRAIN["requirement_drop_height"][0]
    speed_threshold = ratings.MINE_TRAIN["requirement_max_speed"][0]
    base = dict(
        average_speed_units=10, ride_length_m=500, duration_s=60,
        max_positive_g=200, max_negative_g=-50, max_lateral_g=100, num_drops=5,
        flat_turns=TurnCounts(), banked_turns=TurnCounts(), sloped_turns=TurnCounts(),
    )
    both_ok = ratings.calculate(RatingInputs(
        highest_drop_height=drop_threshold, max_speed_units=speed_threshold, **base))
    one_fails = ratings.calculate(RatingInputs(
        highest_drop_height=drop_threshold - 1, max_speed_units=speed_threshold, **base))
    two_fail = ratings.calculate(RatingInputs(
        highest_drop_height=drop_threshold - 1, max_speed_units=speed_threshold - 1,
        **base))

    assert one_fails.nausea == pytest.approx(both_ok.nausea / 2, abs=2)
    assert two_fail.nausea == pytest.approx(both_ok.nausea / 4, abs=2)


def test_generated_track_scores_far_below_the_old_fitted_model():
    """The regression that motivated the port.

    A short, slow track with a shallow drop fails the drop-height and max-speed
    requirements. An in-game reading of a ride of this shape returned 0.25
    excitement while the fitted model predicted 3.91. The port has to land in
    the right neighbourhood rather than several points high.
    """
    inputs = RatingInputs(
        max_speed_units=8,          # below the requirement of 10
        average_speed_units=4,
        ride_length_m=95,
        duration_s=30,
        max_positive_g=150,
        max_negative_g=-20,
        max_lateral_g=80,
        num_drops=3,
        highest_drop_height=2,      # below the requirement of 8
        flat_turns=TurnCounts(two=2),
        banked_turns=TurnCounts(),
        sloped_turns=TurnCounts(),
    )
    result = ratings.calculate(inputs)
    assert result.excitement / 100 < 1.5


def test_intensity_penalty_compounds_across_thresholds():
    """Excitement loses a quarter at each intensity bound crossed."""
    ratings_at_9 = Tuple3(excitement=800, intensity=900)
    ratings._apply_intensity_penalty(ratings_at_9)
    assert ratings_at_9.excitement == 800  # below 10, untouched

    crossed_one = Tuple3(excitement=800, intensity=1050)
    ratings._apply_intensity_penalty(crossed_one)
    assert crossed_one.excitement == 600  # 800 - 200

    crossed_all = Tuple3(excitement=800, intensity=1500)
    ratings._apply_intensity_penalty(crossed_all)
    assert crossed_all.excitement < 300  # five successive quarter cuts


def test_add_clamps_to_int16_rather_than_wrapping():
    """The game saturates ratings; going negative or wrapping would be a bug."""
    high = Tuple3(excitement=ratings.RATING_MAX - 5)
    ratings._add(high, 100, 0, 0)
    assert high.excitement == ratings.RATING_MAX

    low = Tuple3(excitement=10)
    ratings._add(low, -100, 0, 0)
    assert low.excitement == 0


def test_turn_counting_buckets_by_run_length():
    """A run of consecutive turn pieces is one turn, bucketed by its length."""
    left3 = 0x2A   # 3-tile quarter turn left, unbanked, flat
    flat_piece = 0x00

    flat, _, _ = ratings.count_turns([left3, flat_piece, left3, left3])
    assert flat.one == 1   # the lone turn
    assert flat.two == 1   # the pair


def test_banked_classification_wins_over_sloped():
    """The game checks banked before sloped, so a banked turn counts as banked."""
    banked_left = 0x16
    _, banked, sloped = ratings.count_turns([banked_left, banked_left])
    assert banked.two == 1
    assert sloped.two == 0


def test_rate_runs_end_to_end_on_the_fixture():
    """The public entry point works from our own simulation output."""
    _, segments, lifts = load_fixture()
    stats = physics.simulate(segments, lift_indices=lifts)
    result = ratings.rate(stats, segments)

    assert result.excitement > 0
    assert result.intensity > 0
    assert result.nausea > 0

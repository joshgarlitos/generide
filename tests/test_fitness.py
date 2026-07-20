"""Tests for fitness functions, including the physics-based fitness."""

import math
from pathlib import Path

from rct2 import td6
from rct2.fitness import PhysicsFitness, RatingTargets
from rct2.generate import create_simple_circuit
from rct2.physics import rate, simulate

FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def load_fixture():
    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {index for index, element in enumerate(ride.elements) if element.chain_lift}
    return segments, lifts


def test_fixture_ride_completes_with_sane_stats():
    segments, lifts = load_fixture()
    stats = simulate(segments, lift_indices=lifts)

    assert stats.completed, f"stalled at segment {stats.stall_index}"
    assert 3.0 < stats.max_speed < 30.0
    assert stats.drop_count >= 1
    assert stats.ride_length > 0
    for value in (stats.max_speed, stats.avg_speed, stats.airtime,
                  stats.max_positive_g, stats.max_lateral_g):
        assert math.isfinite(value)

    ratings = rate(stats)
    assert math.isfinite(ratings.excitement)
    assert ratings.excitement > 0


def test_physics_fitness_returns_finite_scores():
    segments, _ = load_fixture()
    fitness = PhysicsFitness()
    assert math.isfinite(fitness.evaluate(segments))
    assert math.isfinite(fitness.evaluate(create_simple_circuit()))


def test_invalid_track_scores_below_fixture():
    segments, _ = load_fixture()
    fitness = PhysicsFitness()
    invalid = [0x02, 0x01, 0x09, 0x05, 0x00]  # broken slope transitions, open circuit
    assert fitness.evaluate(invalid) < fitness.evaluate(segments)


def test_target_window_scoring():
    segments, _ = load_fixture()
    ratings = rate(simulate(segments))

    inside = RatingTargets(excitement=(ratings.excitement - 1, ratings.excitement + 1))
    disjoint = RatingTargets(excitement=(ratings.excitement + 50, ratings.excitement + 60))

    in_score = PhysicsFitness(targets=inside).evaluate(segments)
    out_score = PhysicsFitness(targets=disjoint).evaluate(segments)
    assert in_score > out_score

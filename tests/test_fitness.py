"""Tests for fitness functions, including the physics-based fitness."""

import math
import random
from pathlib import Path

import pytest

from rct2 import construction, td6
from rct2.fitness import (
    PhysicsFitness,
    ProxyFitness,
    RatingTargets,
    WeightedProxyFitness,
    estimate_energy_violations,
)
from rct2.generate import create_simple_circuit
from rct2.mutations import generate_random_track
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


# Hand-built tracks, each chosen to trip one penalty. Random generation goes
# through the validator now, so it produces legal tracks and never exercises
# the slope/bank/energy branches on its own.
BREAKS_SLOPE = [0x02, 0x01, 0x00, 0x09, 0x00]  # exits a climb never entered
BREAKS_BANK = [0x02, 0x01, 0x00, 0x17, 0x00]  # banked turn off a flat straight
CLIMBS_TOO_HIGH = [0x02, 0x01, 0x06, 0x09, 0x00, 0x06, 0x04, 0x04, 0x04, 0x09]
DIVES_UNDERGROUND = [0x02, 0x01, 0x0C, 0x0A, 0x0A, 0x0F, 0x00, 0x00, 0x00]
OVERLAPS_ITSELF = [0x02, 0x01] + [0x10] * 8


def _mixed_corpus(count: int = 40) -> list[list[int]]:
    """Valid and invalid tracks, so scoring differences actually surface."""
    rng = random.Random(4242)
    corpus = [
        create_simple_circuit(),
        [0x00] * 3,                    # below min_length
        [0x02, 0x01] + [0x00] * 70,    # past ideal_length
        BREAKS_SLOPE,
        BREAKS_BANK,
        CLIMBS_TOO_HIGH,
        DIVES_UNDERGROUND,
        OVERLAPS_ITSELF,
    ]
    for _ in range(count):
        low = rng.randint(4, 45)
        corpus.append(generate_random_track(rng, low, low + 25))
    return corpus


def test_weighted_defaults_match_proxy_exactly():
    """The anti-drift test.

    ProxyFitness is WeightedProxyFitness with default weights, so the two must
    agree on every track. WeightedProxyFitness previously scored geometry only
    and silently skipped every construction penalty, which made weights tuned
    on it useless for the fitness the GA actually runs. If someone adds a term
    to one class and not the other, this fails.
    """
    proxy = ProxyFitness()
    weighted = WeightedProxyFitness()
    for segments in _mixed_corpus():
        assert weighted.evaluate(segments) == proxy.evaluate(segments)


def test_weighted_fitness_penalizes_construction_invalidity():
    """The specific bug: the old class scored geometry and skipped this."""
    assert not construction.validate_construction(BREAKS_SLOPE).valid

    lenient = WeightedProxyFitness(invalid_construction_penalty=0.0)
    strict = WeightedProxyFitness(invalid_construction_penalty=10000.0)

    assert strict.evaluate(BREAKS_SLOPE) == pytest.approx(
        lenient.evaluate(BREAKS_SLOPE) - 10000.0
    )


def test_every_penalty_weight_reaches_the_score():
    """Each validity weight must be wired in, not merely stored on the instance.

    A weight that __init__ accepts and evaluate() then ignores is the failure
    this class already had once, so check them one at a time against a corpus
    holding a track each penalty actually fires on.
    """
    corpus = _mixed_corpus()
    weights = [
        "invalid_construction_penalty",
        "open_circuit_penalty",
        "collision_penalty_per_tile",
        "underground_penalty_per_unit",
        "slope_violation_penalty",
        "bank_violation_penalty",
        "energy_violation_penalty",
        "stall_penalty",
    ]
    baseline = WeightedProxyFitness()
    for name in weights:
        harsh = WeightedProxyFitness(**{name: 50000.0})
        assert any(
            harsh.evaluate(segments) < baseline.evaluate(segments)
            for segments in corpus
        ), f"{name} never changed a score, so it is not wired into evaluate()"


def test_missing_lift_penalty_cannot_fire_on_the_default_path():
    """Documents a dead branch rather than pretending it is covered.

    `missing_lift_penalty` is excluded from the reachability test above because
    it can never fire. Scoring calls `estimate_energy_violations(segments)`
    with no lift set, so the check falls back to `default_lift_indices`, which
    returns exactly the first hill's own indices. `check_first_hill_has_lift`
    then asks whether any of those indices is in that same set, which is true
    for any non-empty hill. The penalty only becomes reachable if scoring
    starts accepting real per-segment lift flags, at which point delete this.
    """
    corpus = _mixed_corpus()
    assert all(estimate_energy_violations(segments)[1] for segments in corpus)


def test_reward_weights_reach_the_score():
    corpus = _mixed_corpus()
    baseline = WeightedProxyFitness()
    for name in ("length_weight", "elevation_weight",
                 "turn_balance_weight", "variety_weight"):
        generous = WeightedProxyFitness(**{name: 100.0})
        assert any(
            generous.evaluate(segments) > baseline.evaluate(segments)
            for segments in corpus
        ), f"{name} never changed a score, so it is not wired into evaluate()"

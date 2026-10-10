"""Tests for fitness functions, including the physics-based fitness."""

import math
import random
from pathlib import Path

import pytest

from rct2 import construction, td6
from rct2.evolution import evolve
from rct2.fitness import (
    CoasterRequest,
    PhysicsFitness,
    ProxyFitness,
    RatingTargets,
    WeightedProxyFitness,
    estimate_energy_violations,
)
from rct2.generate import create_simple_circuit
from rct2.geometry import Position, track_bounds
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


def test_ported_ratings_flag_changes_which_model_scores_the_track():
    """Both rating models stay reachable, and they disagree as expected.

    On a small track that misses the game's requirement thresholds, the ported
    calculation halves the ratings where the fitted weights cannot, so the same
    track has to score lower through the ported model. If this ever stops being
    true the flag has silently stopped being wired in.
    """
    from rct2 import physics as physics_module
    from rct2 import ratings as ratings_module

    small = create_simple_circuit() + [0x06, 0x04, 0x09, 0x0C, 0x0A, 0x0F]
    stats = simulate(small)

    fitted = physics_module.rate(stats)
    ported = ratings_module.rate(stats, small)
    assert ported.excitement < fitted.excitement

    open_ended_fitted = PhysicsFitness(ported_ratings=False).evaluate(small)
    open_ended_ported = PhysicsFitness(ported_ratings=True).evaluate(small)
    assert open_ended_ported < open_ended_fitted


def test_coaster_request_defaults_to_unconstrained_ratings():
    """No rating windows set means rating_targets() is None, not an empty RatingTargets.

    PhysicsFitness treats `targets=None` as open-ended scoring and a
    RatingTargets with every field None as a (pointless) zero-width-nowhere
    match against nothing, so the distinction matters.
    """
    request = CoasterRequest()
    assert request.rating_targets() is None
    assert request.max_width == 30
    assert request.max_depth == 30


def test_coaster_request_rating_targets_carries_set_windows():
    request = CoasterRequest(excitement=(5.0, 7.0), nausea=(0.0, 4.0))
    targets = request.rating_targets()
    assert targets.excitement == (5.0, 7.0)
    assert targets.intensity is None
    assert targets.nausea == (0.0, 4.0)


def test_physics_fitness_from_request_matches_manual_construction():
    segments, _ = load_fixture()
    request = CoasterRequest(max_width=15, max_depth=20, excitement=(4.0, 8.0))

    from_request = PhysicsFitness.from_request(request)
    manual = PhysicsFitness(
        targets=request.rating_targets(), max_width=15, max_depth=20,
    )

    assert from_request.evaluate(segments) == manual.evaluate(segments)


def test_footprint_constrained_evolution_fits_the_request():
    """Acceptance criterion for #5: a tight footprint actually shapes what
    evolution produces, not just something validated after the fact.
    """
    request = CoasterRequest(max_width=12, max_depth=12)
    fitness_fn = ProxyFitness(max_width=request.max_width, max_depth=request.max_depth)

    rng = random.Random(7)
    stats = evolve(
        create_simple_circuit(),
        rng,
        fitness_fn=fitness_fn,
        generations=25,
        population_size=25,
        elitism=4,
    )

    bounds = track_bounds(Position(), stats.best_individual.segments)
    assert bounds.width <= request.max_width
    assert bounds.depth <= request.max_depth


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
        [0x02, 0x01] + [0x00] * 120,   # past ideal_length (100, since 2026-09-13)
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


def test_ideal_length_default_matches_mine_train_calibration():
    """Pins the calibrated default so a future edit can't silently drift it.

    100 is chosen from the four real Mine Train designs in
    data/calibration.csv (82, 89, 104, 142) -- see rct2/fitness.py's
    WeightedProxyFitness docstring for the full rationale.
    """
    assert WeightedProxyFitness().ideal_length == 100
    assert ProxyFitness().ideal_length == 100


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


def test_padding_past_ideal_length_earns_no_elevation_turn_or_variety_reward():
    """Repair-added segments past ideal_length must not keep earning reward.

    Without this, a track's elevation/turn/variety reward kept growing with
    every segment regardless of ideal_length, so it easily outweighed
    over_length_penalty (0.5/segment by default) and let genome length
    ratchet upward with nothing to stop it -- exactly what repair_circuit's
    append-only repair does under a tight footprint, where more corrective
    segments are needed to close the loop.
    """
    fitness_fn = WeightedProxyFitness(
        ideal_length=5,
        invalid_construction_penalty=0.0,
        open_circuit_penalty=0.0,
        bounds_penalty_per_tile=0.0,
        collision_penalty_per_tile=0.0,
        underground_penalty_per_unit=0.0,
        slope_violation_penalty=0.0,
        bank_violation_penalty=0.0,
        energy_violation_penalty=0.0,
        missing_lift_penalty=0.0,
        stall_penalty=0.0,
        short_penalty_per_segment=0.0,
    )
    prefix = [0x00] * 5
    flat_padding = [0x00] * 5
    hilly_padding = [0x06, 0x09, 0x10, 0x11, 0x06]  # elevation changes + turns

    assert fitness_fn.evaluate(prefix + flat_padding) == fitness_fn.evaluate(
        prefix + hilly_padding
    )


class TestNoSiteIsUnchanged:
    """Covers AE3: with no site, scoring and a seeded run match the code before sites existed.

    The expected values were recorded from the commit before the site work,
    not computed from the code under test.
    """

    def test_default_proxy_and_physics_scores_on_the_fixture(self):
        segments, _ = load_fixture()

        assert ProxyFitness().evaluate(segments) == 521.0
        assert ProxyFitness(max_width=10, max_depth=10).evaluate(segments) == -9609.0
        assert PhysicsFitness().evaluate(segments) == pytest.approx(61.55684431164997)
        assert PhysicsFitness(max_width=12, max_depth=12).evaluate(segments) == pytest.approx(
            11.556844311649968
        )

    @pytest.mark.parametrize(
        "make_fitness, best_fitness, length",
        [
            (ProxyFitness, 235.0, 58),
            (PhysicsFitness, 50.853068924145916, 54),
        ],
    )
    def test_a_seeded_run_finds_the_same_best_ride(self, make_fitness, best_fitness, length):
        from rct2.evolution import evolve_parts
        from rct2.generate import create_hill_circuit

        stats = evolve_parts(
            create_hill_circuit(),
            random.Random(3),
            fitness_fn=make_fitness(),
            generations=6,
            population_size=12,
        )

        assert stats.best_fitness == pytest.approx(best_fitness)
        assert len(stats.best_individual.segments) == length


def _site_for(segments, margin=2, blocked=(), heading=None):
    """An open site that holds `segments` with room to spare, with the given world tiles blocked."""
    from rct2.geometry import Heading, occupied_tiles
    from rct2.site import Site, site_coords

    heading = Heading.NORTH if heading is None else heading
    tiles = [(t.x, t.y) for t in occupied_tiles(Position(), segments)]
    tiles += [(-1, 0), (1, 0)]
    # Pick the anchor so that every tile lands at a non-negative site position.
    probe = [site_coords((0, 0), heading, x, y) for x, y in tiles]
    anchor = (margin - min(x for x, _ in probe), margin - min(y for _, y in probe))
    placed = [site_coords(anchor, heading, x, y) for x, y in tiles]
    width = max(x for x, _ in placed) + margin + 1
    depth = max(y for _, y in placed) + margin + 1
    rows = [["."] * width for _ in range(depth)]
    for x, y in blocked:
        rows[y][x] = "#"
    return Site.from_rows(["".join(r) for r in rows], anchor=anchor), anchor


def _ride_world_tiles(segments, anchor, heading=None):
    from rct2.geometry import Heading, occupied_tiles
    from rct2.site import site_coords

    heading = Heading.NORTH if heading is None else heading
    return sorted({site_coords(anchor, heading, t.x, t.y) for t in occupied_tiles(Position(), segments)})


class TestSiteFitness:
    def test_a_ride_that_spills_past_the_old_rectangle_but_fits_the_site_is_not_invalid(self):
        # The fixture is wider than 10 tiles, so the old rectangle rejects it outright.
        segments, _ = load_fixture()
        site, _ = _site_for(segments)

        assert ProxyFitness(max_width=10, max_depth=10).evaluate(segments) == -9609.0
        assert ProxyFitness(max_width=10, max_depth=10, site=site).evaluate(segments) == 521.0
        assert PhysicsFitness(max_width=12, max_depth=12, site=site).evaluate(
            segments
        ) == pytest.approx(61.55684431164997)

    @pytest.mark.parametrize("make", [ProxyFitness, PhysicsFitness])
    def test_a_ride_with_more_blocked_tiles_scores_lower(self, make):
        segments, _ = load_fixture()
        open_site, anchor = _site_for(segments)
        tiles = _ride_world_tiles(segments, anchor)
        few, _ = _site_for(segments, blocked=tiles[:2])
        many, _ = _site_for(segments, blocked=tiles[:12])

        assert (
            make(site=open_site).evaluate(segments)
            > make(site=few).evaluate(segments)
            > make(site=many).evaluate(segments)
        )

    @pytest.mark.parametrize("make", [ProxyFitness, PhysicsFitness])
    def test_penalties_stop_growing_past_the_cap(self, make):
        segments, _ = load_fixture()
        open_site, anchor = _site_for(segments)
        tiles = _ride_world_tiles(segments, anchor)
        enough, _ = _site_for(segments, blocked=tiles[:120])
        everything, _ = _site_for(segments, blocked=tiles)
        assert len(tiles) > 120

        assert make(site=everything).evaluate(segments) == pytest.approx(
            make(site=enough).evaluate(segments)
        )

    def test_a_fitting_ride_beats_a_longer_better_ride_that_heavily_violates_the_site(self):
        from rct2.generate import create_hill_circuit

        long_ride, _ = load_fixture()
        short_ride = create_hill_circuit()
        _, anchor = _site_for(long_ride)
        blocked_site, _ = _site_for(long_ride, blocked=_ride_world_tiles(long_ride, anchor))
        fitting_site, _ = _site_for(short_ride)
        fitness_blocked = ProxyFitness(site=blocked_site)
        fitness_fitting = ProxyFitness(site=fitting_site)

        assert fitness_fitting.evaluate(short_ride) > fitness_blocked.evaluate(long_ride)

    def test_a_ride_that_fits_only_when_turned_east_takes_no_site_penalty(self):
        from rct2.geometry import Heading

        segments, _ = load_fixture()
        open_site, _ = _site_for(segments)
        east_site, east_anchor = _site_for(segments, heading=Heading.EAST)
        # Shrink the east site to exactly what the ride needs when it faces east.
        needed = set(_ride_world_tiles(segments, east_anchor, Heading.EAST))
        needed |= {(east_anchor[0], east_anchor[1] + 1), (east_anchor[0], east_anchor[1] - 1)}
        rows = [
            "".join(
                "." if (x, y) in needed else "#" for x in range(east_site.width)
            )
            for y in range(east_site.depth)
        ]
        from rct2.site import Site, best_fit

        tight = Site.from_rows(rows, anchor=east_anchor)

        assert best_fit(tight, segments).heading == Heading.EAST
        assert ProxyFitness(site=tight).evaluate(segments) == ProxyFitness(
            site=open_site
        ).evaluate(segments)

    @pytest.mark.parametrize("make", [ProxyFitness, PhysicsFitness])
    def test_covers_ae2_a_short_run_loops_around_a_blocked_block(self, make):
        from rct2.evolution import evolve_parts
        from rct2.generate import create_hill_circuit
        from rct2.site import Site, best_fit

        seed = create_hill_circuit()
        base, anchor = _site_for(seed, margin=8)
        rows = [list(r) for r in base.rows]
        # A 2 by 2 block the seed ride would cross: two tiles along from the station, one over.
        ax, ay = anchor
        for dx in (2, 3):
            for dy in (4, 5):
                rows[ay + dy][ax + dx] = "#"
        site = Site.from_rows(["".join(r) for r in rows], anchor=anchor)
        assert best_fit(site, seed).blocked > 0

        stats = evolve_parts(
            seed,
            random.Random(3),
            fitness_fn=make(site=site),
            generations=25,
            population_size=20,
        )

        assert best_fit(site, stats.best_individual.segments).blocked == 0

    def test_a_small_site_does_not_make_genomes_grow(self):
        from rct2.evolution import evolve_parts
        from rct2.generate import create_hill_circuit

        seed = create_hill_circuit()
        site, _ = _site_for(seed, margin=1)
        fitness = ProxyFitness(site=site)

        stats = evolve_parts(
            seed, random.Random(5), fitness_fn=fitness, generations=15, population_size=20
        )

        assert len(stats.best_individual.segments) <= fitness.ideal_length + 20

    def test_the_site_penalty_cap_is_above_the_largest_reward(self):
        fitness = ProxyFitness()
        largest_reward = fitness.ideal_length * (
            fitness.length_weight
            + fitness.elevation_weight
            + fitness.variety_weight
            + fitness.turn_balance_weight / 2
        )

        assert fitness.site_penalty_cap_per_kind > largest_reward

"""Tests for the method-comparison benchmark harness.

The harness exists because the 2026-08-09 experiments weren't trustworthy:
too few seeds, changes confounded together, and tracks scored by the same
model being optimized. These tests check the specific things that made that
happen can't happen here -- the hard gate, honest reliability/diversity, and
that saved results round-trip so a comparison never needs re-running.
"""

import random
from pathlib import Path

import pytest

from rct2.benchmark import (
    METHODS,
    RunResult,
    diversity,
    evaluate_result,
    judge_results,
    load_results,
    method_ga,
    method_ga_parts,
    method_random,
    reliability,
    rescore,
    run_benchmark,
    save_results,
    summarize,
)
from rct2.generate import create_simple_circuit


# A short open stub: station drives it the whole way, so `completed` is True,
# but it never closes the loop, so `valid` is False. Exactly the shape of
# track that must not receive a score.
OPEN_STUB = [0x02, 0x01, 0x00, 0x00, 0x00]

# The real fixture, known construction-valid and completing.
FIXTURE_SEGMENTS = None  # populated by fixture below


@pytest.fixture
def real_segments():
    from rct2 import td6
    ride = td6.load(Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6")
    return [e.segment_type for e in ride.elements]


class TestHardGate:
    """A track that isn't buildable and complete must get no score, ever."""

    def test_invalid_track_gets_no_ported_score(self):
        result = evaluate_result("test", seed=1, segments=OPEN_STUB, evaluations_used=1)
        assert not result.valid
        assert result.ported_excitement is None
        assert result.ported_intensity is None
        assert result.ported_nausea is None

    def test_valid_completing_track_gets_a_score(self, real_segments):
        result = evaluate_result("test", seed=1, segments=real_segments, evaluations_used=1)
        assert result.valid
        assert result.completed
        assert result.ported_excitement is not None
        assert result.ported_excitement > 0

    def test_gate_requires_both_valid_and_completed(self):
        """Physical stats are still recorded on a gated-out track -- only
        the ported ratings are withheld. Otherwise a failed run tells you
        nothing about *how* it failed.
        """
        result = evaluate_result("test", seed=1, segments=OPEN_STUB, evaluations_used=1)
        assert result.ported_excitement is None
        # highest_drop, drop_count etc. come from simulate() regardless of
        # validity, so they should still be present (possibly zero).
        assert result.drop_count is not None


class TestReliabilityAndDiversity:
    def test_reliability_is_fraction_valid_and_completed(self, real_segments):
        good = evaluate_result("m", 1, real_segments, 1)
        bad = evaluate_result("m", 2, OPEN_STUB, 1)

        assert reliability([]) == 0.0
        assert reliability([bad, bad]) == 0.0
        assert reliability([good, good]) == 1.0
        assert reliability([good, bad]) == 0.5

    def test_flat_liftless_loop_is_valid_but_does_not_complete(self):
        """create_simple_circuit is construction-valid (the game builds it)
        but no train can finish it -- the seed every evolution run starts
        from (see docs/architecture.md, "Buildable is not runnable"). It's
        the concrete case that makes `valid and completed` the right gate
        rather than `valid` alone.
        """
        result = evaluate_result("m", 1, create_simple_circuit(), 1)
        assert result.valid
        assert not result.completed
        assert result.ported_excitement is None

    def test_diversity_is_zero_with_no_valid_results(self):
        bad = evaluate_result("m", 1, OPEN_STUB, 1)
        assert diversity([bad]) == 0.0

    def test_diversity_is_one_when_every_result_is_a_different_shape(self, real_segments):
        from dataclasses import replace

        base = evaluate_result("m", 1, real_segments, 1)
        variants = [
            replace(base, seed=i, drop_count=base.drop_count + i)
            for i in range(4)
        ]
        assert diversity(variants) == 1.0

    def test_diversity_is_low_when_every_result_is_the_same_shape(self, real_segments):
        base = evaluate_result("m", 1, real_segments, 1)
        identical = [base for _ in range(5)]
        assert diversity(identical) == pytest.approx(1 / 5)


class TestMethodsRegistered:
    """Smoke tests: each registered method returns a real segment list under
    a tiny budget. Not a quality claim, just that nothing crashes and the
    budget is respected in spirit.
    """

    @pytest.mark.parametrize("name", list(METHODS))
    def test_method_returns_segments(self, name):
        rng = random.Random(1)
        segments = METHODS[name](rng, max_evaluations=15)
        assert isinstance(segments, list)
        assert len(segments) > 0
        assert all(isinstance(s, int) for s in segments)

    def test_ga_and_random_are_reproducible_given_the_same_seed(self):
        segs1 = method_random(random.Random(7), max_evaluations=10)
        segs2 = method_random(random.Random(7), max_evaluations=10)
        assert segs1 == segs2

        segs1 = method_ga(random.Random(7), max_evaluations=60, population_size=20)
        segs2 = method_ga(random.Random(7), max_evaluations=60, population_size=20)
        assert segs1 == segs2

    def test_ga_parts_is_reproducible_given_the_same_seed(self):
        segs1 = method_ga_parts(random.Random(7), max_evaluations=60, population_size=20)
        segs2 = method_ga_parts(random.Random(7), max_evaluations=60, population_size=20)
        assert segs1 == segs2


class TestRunBenchmark:
    def test_produces_one_result_per_method_per_seed(self):
        results = run_benchmark(
            {"random": method_random}, seeds=[1, 2, 3], max_evaluations=10,
        )
        assert len(results) == 3
        assert {r.seed for r in results} == {1, 2, 3}
        assert all(r.method == "random" for r in results)

    def test_every_method_scored_under_the_same_budget(self):
        results = run_benchmark(
            {"random": method_random, "ga": method_ga}, seeds=[1], max_evaluations=40,
        )
        assert {r.evaluations_used for r in results} == {40}


class TestPersistence:
    def test_results_round_trip_through_a_file(self, tmp_path, real_segments):
        original = [evaluate_result("m", 1, real_segments, 100)]
        path = tmp_path / "results.json"

        save_results(original, path)
        loaded = load_results(path)

        assert loaded == original

    def test_save_creates_parent_directories(self, tmp_path, real_segments):
        path = tmp_path / "nested" / "dir" / "results.json"
        save_results([evaluate_result("m", 1, real_segments, 1)], path)
        assert path.exists()


class TestSummarize:
    def test_summarize_groups_by_method(self, real_segments):
        results = [
            evaluate_result("a", 1, real_segments, 100),
            evaluate_result("b", 1, real_segments, 100),
        ]
        summary = {row.method: row for row in summarize(results)}
        assert set(summary) == {"a", "b"}
        assert summary["a"].runs == 1

    def test_median_excitement_ignores_gated_out_runs(self):
        results = [
            evaluate_result("m", 1, OPEN_STUB, 1),
            evaluate_result("m", 2, OPEN_STUB, 1),
        ]
        summary = summarize(results)[0]
        assert summary.median_excitement is None
        assert summary.reliability == 0.0


class _FakeJudged:
    """Stands in for an OracleResult without needing a game installed."""

    def __init__(self, excitement=None, status="rated"):
        self.status = status
        self.excitement = excitement
        self.intensity = (excitement or 0) + 1
        self.nausea = (excitement or 0) - 1


def _run(method="ga", seed=1, valid=True, completed=True, ported=1.0, segments=None):
    return RunResult(
        method=method, seed=seed, evaluations_used=100,
        segments=segments if segments is not None else [seed],
        valid=valid, completed=completed,
        highest_drop=8.0, drop_count=3, max_speed_mph=30.0, ride_length_m=200.0,
        ported_excitement=ported if (valid and completed) else None,
        ported_intensity=ported if (valid and completed) else None,
        ported_nausea=ported if (valid and completed) else None,
    )


def test_judging_only_sends_tracks_that_passed_the_gate():
    # The hard gate stays the gate: a track the game would refuse to build
    # is not worth four seconds of the game's time.
    results = [_run(seed=1), _run(seed=2, valid=False, completed=False), _run(seed=3)]
    sent = []

    def scorer(tracks):
        sent.extend(tracks)
        return [_FakeJudged(6.2) for _ in tracks]

    judge_results(results, scorer=scorer)

    assert sent == [[1], [3]]
    assert results[0].real_excitement == 6.2
    assert results[1].real_excitement is None
    assert results[2].real_excitement == 6.2


def test_judging_top_n_takes_the_best_per_method():
    results = [
        _run(method="ga", seed=1, ported=1.0),
        _run(method="ga", seed=2, ported=5.0),
        _run(method="ga_parts", seed=3, ported=2.0),
        _run(method="ga_parts", seed=4, ported=4.0),
    ]

    judge_results(results, scorer=lambda tracks: [_FakeJudged(6.0) for _ in tracks], top_n=1)

    judged = {r.seed for r in results if r.real_excitement is not None}
    assert judged == {2, 4}


def test_an_unrated_track_leaves_the_real_columns_empty():
    # "The game never gave this a rating" and "the game rated it badly" have
    # to stay distinguishable, or a stalled ride reads as a 0.0 ride.
    results = [_run(seed=1)]

    judge_results(results, scorer=lambda tracks: [_FakeJudged(status="stalled")])

    assert results[0].real_excitement is None


def test_summary_reports_the_game_alongside_the_ported_model():
    results = [_run(seed=1, ported=1.0), _run(seed=2, ported=3.0)]
    judge_results(results, scorer=lambda tracks: [_FakeJudged(2.0), _FakeJudged(4.0)])

    row = summarize(results)[0]

    assert row.median_excitement == 2.0
    assert row.judged == 2
    assert row.median_real_excitement == 3.0
    assert row.best_real_excitement == 4.0


def test_summary_says_nothing_about_the_game_before_anything_is_judged():
    row = summarize([_run(seed=1)])[0]
    assert row.judged == 0
    assert row.median_real_excitement is None


def test_rescoring_a_saved_file_needs_no_search_rerun(tmp_path):
    path = tmp_path / "results.json"
    save_results([_run(seed=1, ported=2.0)], path)

    rescore(path, scorer=lambda tracks: [_FakeJudged(6.2) for _ in tracks])

    reloaded = load_results(path)
    assert reloaded[0].real_excitement == 6.2
    assert reloaded[0].real_intensity == 7.2
    # The ported score is kept, not overwritten: the gap between the two is
    # the finding.
    assert reloaded[0].ported_excitement == 2.0


def test_a_scorer_that_drops_a_track_is_an_error_not_a_silent_shift():
    results = [_run(seed=1), _run(seed=2)]

    with pytest.raises(ValueError, match="1 judgements for 2 tracks"):
        judge_results(results, scorer=lambda tracks: [_FakeJudged(6.0)])

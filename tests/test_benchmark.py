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


class TestSiteBenchmark:
    """Fit rate on canned sites, so ways of supplying or searching a site compare on one number."""

    def test_there_are_three_canned_sites_that_hold_the_default_hill_circuit(self):
        from rct2.benchmark import canned_sites
        from rct2.generate import create_hill_circuit
        from rct2.site import best_fit

        sites = canned_sites()

        assert set(sites) == {"l-shape", "blocked-centre", "downhill"}
        # The hill circuit seed is what the parts search starts from; the
        # blocked centre is deliberately in its way, the others are not.
        assert best_fit(sites["l-shape"], create_hill_circuit()).fits
        assert best_fit(sites["downhill"], create_hill_circuit()).fits
        assert not best_fit(sites["blocked-centre"], create_hill_circuit()).fits

    def test_a_site_run_records_the_site_and_whether_the_ride_fits(self, real_segments):
        from rct2.site import Site

        open_site = Site.from_rows(["." * 40] * 40, anchor=(10, 10))
        shut_site = Site.from_rows(["#" * 40] * 40, anchor=(10, 10))

        fits = evaluate_result("m", 1, real_segments, 10, site=open_site, site_name="open")
        shut = evaluate_result("m", 1, real_segments, 10, site=shut_site, site_name="shut")
        plain = evaluate_result("m", 1, real_segments, 10)

        assert (fits.site, fits.fits_site, fits.site_violations) == ("open", True, 0)
        assert shut.fits_site is False and shut.site_violations > 0
        assert (plain.site, plain.fits_site, plain.site_violations) == (None, None, None)

    def test_a_ride_bigger_than_the_old_rectangle_is_valid_against_a_site(self, real_segments):
        from rct2.site import Site

        site = Site.from_rows(["." * 40] * 40, anchor=(10, 10))

        result = evaluate_result("m", 1, real_segments, 10, max_width=2, max_depth=2, site=site)

        assert result.valid is True

    def test_the_site_reaches_the_search_fitness(self, monkeypatch):
        import rct2.benchmark as benchmark
        from rct2.site import Site

        seen = []
        real = benchmark._search_fitness
        monkeypatch.setattr(
            benchmark, "_search_fitness", lambda site=None: seen.append(site) or real(site)
        )
        site = Site.from_rows(["." * 30] * 30, anchor=(8, 8))

        benchmark.run_site_benchmark({"random": method_random}, {"s": site}, [1], 3)

        assert seen == [site]

    def test_a_site_row_differs_from_the_same_seeds_without_the_site(self):
        from rct2.site import Site

        shut = Site.from_rows(["#" * 30] * 30, anchor=(8, 8))

        with_site = run_benchmark({"random": method_random}, [1, 2], 5)
        on_site = benchmark_run({"random": method_random}, {"shut": shut}, [1, 2], 5)

        assert all(r.fits_site is None for r in with_site)
        assert all(r.fits_site is False and r.site == "shut" for r in on_site)

    def test_a_site_nothing_fits_reports_a_fit_rate_of_zero(self):
        from rct2.benchmark import summarize_sites
        from rct2.site import Site

        shut = Site.from_rows(["#" * 30] * 30, anchor=(8, 8))

        rows = summarize_sites(benchmark_run({"random": method_random}, {"shut": shut}, [1, 2, 3], 4))

        assert [(r.site, r.method, r.runs, r.fit_rate, r.usable_fit_rate) for r in rows] == [
            ("shut", "random", 3, 0.0, 0.0)
        ]

    def test_one_row_per_canned_site_and_method(self):
        from rct2.benchmark import canned_sites, summarize_sites

        rows = summarize_sites(benchmark_run({"random": method_random}, canned_sites(), [1], 3))

        assert sorted(r.site for r in rows) == ["blocked-centre", "downhill", "l-shape"]

    def test_the_same_seeds_give_the_same_fit_rate_twice(self):
        from rct2.benchmark import canned_sites, summarize_sites

        def rates():
            rows = summarize_sites(
                benchmark_run({"random": method_random}, canned_sites(), [1, 2], 4)
            )
            return [(r.site, r.fit_rate, r.usable_fit_rate) for r in rows]

        assert rates() == rates()

    def test_site_runs_do_not_leak_into_the_open_field_summary(self, real_segments):
        from rct2.site import Site

        site = Site.from_rows(["." * 40] * 40, anchor=(10, 10))
        open_run = evaluate_result("m", 1, real_segments, 10)
        site_run = evaluate_result("m", 1, real_segments, 10, site=site, site_name="open")

        (row,) = summarize([open_run, site_run])

        assert row.runs == 1

    def test_site_fields_survive_a_save_and_load(self, tmp_path, real_segments):
        from rct2.site import Site

        site = Site.from_rows(["." * 40] * 40, anchor=(10, 10))
        result = evaluate_result("m", 1, real_segments, 10, site=site, site_name="open")

        save_results([result], tmp_path / "r.json")

        assert load_results(tmp_path / "r.json") == [result]


class TestExtraSiteFiles:
    """`--site-file` adds a saved site to the benchmark, named by its file."""

    REPO = Path(__file__).parent.parent
    FIXTURE = Path(__file__).parent / "data" / "site-14x14.json"

    def _run_cli(self, tmp_path, *extra):
        import subprocess
        import sys

        return subprocess.run(
            [sys.executable, str(self.REPO / "run_benchmark.py"), "--methods", "random",
             "--seeds", "1", "--evaluations", "3", "--output", str(tmp_path / "out.json"),
             *extra],
            capture_output=True, text=True, cwd=self.REPO,
        )

    def test_the_14_by_14_fixture_is_an_open_flat_square(self):
        from rct2.site import Site

        site = Site.load(self.FIXTURE)

        assert (site.width, site.depth) == (14, 14)
        assert all(ch == "." for row in site.rows for ch in row)
        assert {h for row in site.heights for h in row} == {0}

    def test_a_site_file_appears_next_to_the_canned_sites_under_its_file_name(self):
        from rct2.benchmark import benchmark_sites

        sites = benchmark_sites(True, [self.FIXTURE])

        assert list(sites) == ["l-shape", "blocked-centre", "downhill", "site-14x14"]

    def test_a_site_file_alone_runs_without_the_canned_sites(self):
        from rct2.benchmark import benchmark_sites

        assert list(benchmark_sites(False, [self.FIXTURE])) == ["site-14x14"]

    def test_the_canned_sites_do_not_change(self):
        from rct2.benchmark import canned_sites

        assert list(canned_sites()) == ["l-shape", "blocked-centre", "downhill"]

    def test_a_missing_file_a_bad_file_and_a_clashing_name_are_each_refused(self, tmp_path):
        from rct2.benchmark import benchmark_sites
        from rct2.site import SiteError

        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        clash = tmp_path / "l-shape.json"
        clash.write_text(self.FIXTURE.read_text())

        with pytest.raises(SiteError, match="could not be read"):
            benchmark_sites(False, [tmp_path / "nope.json"])
        with pytest.raises(SiteError, match="not valid JSON"):
            benchmark_sites(False, [bad])
        with pytest.raises(SiteError, match="both be called 'l-shape'"):
            benchmark_sites(True, [clash])

    def test_the_command_refuses_a_bad_site_before_any_run_starts(self, tmp_path):
        done = self._run_cli(tmp_path, "--site-file", str(tmp_path / "nope.json"))

        assert done.returncode == 2
        assert "could not be read" in done.stderr
        assert not (tmp_path / "out.json").exists()
        assert "Methods:" not in done.stdout

    def test_the_command_reports_the_file_next_to_the_canned_sites(self, tmp_path):
        done = self._run_cli(tmp_path, "--sites", "--site-file", str(self.FIXTURE))

        assert done.returncode == 0, done.stderr
        for name in ("l-shape", "blocked-centre", "downhill", "site-14x14"):
            assert name in done.stdout


def benchmark_run(methods, sites, seeds, evaluations):
    from rct2.benchmark import run_site_benchmark

    return run_site_benchmark(methods, sites, seeds, evaluations)


class TestBenchmarkMovesTheHillOnlyWithASite:
    def _kwargs(self, monkeypatch, site):
        import rct2.evolution as evolution
        from rct2.benchmark import method_ga_parts

        seen = {}
        real = evolution.evolve_parts

        def spy(*args, **kwargs):
            seen.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr(evolution, "evolve_parts", spy)
        method_ga_parts(random.Random(1), 8, population_size=4, site=site)
        return seen

    def test_a_site_run_moves_the_hill(self, monkeypatch):
        from rct2.site import Site

        site = Site.from_rows(["." * 30] * 30, anchor=(10, 10))

        assert self._kwargs(monkeypatch, site)["relocate_hill"] is True

    def test_a_run_without_a_site_does_not(self, monkeypatch):
        assert self._kwargs(monkeypatch, None)["relocate_hill"] is False

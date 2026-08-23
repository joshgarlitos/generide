"""Benchmark harness for comparing coaster-generation methods.

Built in response to a specific failure: the four experiments in
docs/devlog.md (2026-08-09) used three seeds, inconsistent generation
budgets, changes confounded with each other, and scored tracks with the same
model being optimized. None of those numbers were trustworthy. This module
is the fix -- see docs/research-plan.md for the design this implements.

A method is any callable of the shape `(rng, max_evaluations) -> segments`.
It decides internally how to spend its budget; the harness does not care
whether that means generations of a population or iterations of something
else, so new methods (piece-by-piece search, RL) register the same way GA
and random search do here.

Every result goes through the same gate before it gets a score: a track
that is not construction-valid and does not complete its circuit gets no
ported rating at all, regardless of what its raw stats look like. Reporting
a rating on an unbuildable track is the specific mistake that produced a
5.03 excitement score on tracks the game would refuse to build (2026-08-09).
"""

import json
import random
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

from rct2 import construction, physics, ratings
from rct2.geometry import Position, track_bounds


@dataclass
class RunResult:
    """One method's output from one seed.

    Stores the full segment list, not just derived stats, so a saved result
    file can be re-scored later (a new rating model, the headless oracle)
    without re-running the search that produced it.
    """

    method: str
    seed: int
    evaluations_used: int
    segments: list[int]
    valid: bool
    completed: bool
    highest_drop: float
    drop_count: int
    max_speed_mph: float
    ride_length_m: float
    # None whenever `valid and completed` is False -- the hard gate.
    ported_excitement: Optional[float] = None
    ported_intensity: Optional[float] = None
    ported_nausea: Optional[float] = None
    # Filled in later by the headless oracle (issue #42); absent until then.
    real_excitement: Optional[float] = None
    real_intensity: Optional[float] = None
    real_nausea: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunResult":
        return cls(**d)


MethodFn = Callable[[random.Random, int], list[int]]


def _search_fitness():
    """The in-loop scorer every method searches against.

    Ported ratings, per docs/devlog.md (2026-08-08): scoring evolution with
    the fitted model let it climb toward numbers the game does not agree
    with. Using the same scorer for every method also keeps the comparison
    fair -- a method that wins because it optimizes a friendlier objective
    is not a method that produces better rides.
    """
    from rct2.fitness import PhysicsFitness
    return PhysicsFitness(ported_ratings=True)


def method_random(rng: random.Random, max_evaluations: int) -> list[int]:
    """Rung 0: random legal tracks, keep the best. The baseline every other
    method has to clear -- if a method can't beat this, that's the finding.
    """
    from rct2.mutations import generate_random_track

    fitness_fn = _search_fitness()
    best_segments = generate_random_track(rng)
    best_score = fitness_fn.evaluate(best_segments)
    for _ in range(max_evaluations - 1):
        candidate = generate_random_track(rng)
        score = fitness_fn.evaluate(candidate)
        if score > best_score:
            best_score = score
            best_segments = candidate
    return best_segments


def method_ga(
    rng: random.Random, max_evaluations: int, population_size: int = 40,
) -> list[int]:
    """Rung 1: the current genetic algorithm. The baseline to beat."""
    from rct2.evolution import evolve
    from rct2.generate import create_simple_circuit

    generations = max(1, (max_evaluations - population_size) // population_size)
    stats = evolve(
        create_simple_circuit(), rng, fitness_fn=_search_fitness(),
        population_size=population_size, generations=generations,
    )
    return stats.best_individual.segments


def method_ga_parts(
    rng: random.Random, max_evaluations: int, population_size: int = 40,
) -> list[int]:
    """Rung 2: the genetic algorithm with a part-based genome, so crossover
    can never slice a slope run or banked turn in half (see
    docs/research-plan.md and rct2/mutations.py's crossover_parts). Compared
    against "ga" through this same harness, unmodified, so the comparison is
    a real one rather than a hopeful rewrite.
    """
    from rct2.evolution import evolve_parts
    from rct2.generate import create_hill_circuit

    generations = max(1, (max_evaluations - population_size) // population_size)
    stats = evolve_parts(
        create_hill_circuit(), rng, fitness_fn=_search_fitness(),
        population_size=population_size, generations=generations,
    )
    return stats.best_individual.segments


METHODS: dict[str, MethodFn] = {
    "random": method_random,
    "ga": method_ga,
    "ga_parts": method_ga_parts,
}


def evaluate_result(
    method: str, seed: int, segments: list[int], evaluations_used: int,
    max_width: int = 30, max_depth: int = 30,
) -> RunResult:
    """Score a finished track the same way regardless of which method produced it.

    This is the hard gate: `ported_excitement`/`intensity`/`nausea` stay
    None unless the track is both construction-valid and completes its
    circuit. Physical stats (drop count, speed, length) are recorded either
    way, since they're useful for diagnosing *why* a method failed.
    """
    check = construction.validate_construction(
        segments, max_width=max_width, max_depth=max_depth,
    )
    stats = physics.simulate(segments)
    bounds = track_bounds(Position(), segments)

    valid = check.valid
    completed = stats.completed
    excitement = intensity = nausea = None
    if valid and completed:
        rating = ratings.rate(stats, segments)
        excitement, intensity, nausea = rating.excitement, rating.intensity, rating.nausea

    return RunResult(
        method=method,
        seed=seed,
        evaluations_used=evaluations_used,
        segments=segments,
        valid=valid,
        completed=completed,
        highest_drop=stats.highest_drop,
        drop_count=stats.drop_count,
        max_speed_mph=stats.max_speed * 2.23694,
        ride_length_m=stats.ride_length,
        ported_excitement=excitement,
        ported_intensity=intensity,
        ported_nausea=nausea,
    )


def run_benchmark(
    methods: dict[str, MethodFn],
    seeds: list[int],
    max_evaluations: int,
    max_width: int = 30,
    max_depth: int = 30,
) -> list[RunResult]:
    """Run every method against every seed at the same evaluation budget.

    Budget is counted in track evaluations, not generations, because
    "generations" isn't a concept every method shares -- random search and a
    future piece-by-piece builder don't have them. Evaluations are the one
    unit every method can be charged in.
    """
    results = []
    for name, method_fn in methods.items():
        for seed in seeds:
            rng = random.Random(seed)
            segments = method_fn(rng, max_evaluations)
            results.append(
                evaluate_result(name, seed, segments, max_evaluations, max_width, max_depth)
            )
    return results


def save_results(results: list[RunResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.to_dict() for r in results], indent=2))


def load_results(path: Path) -> list[RunResult]:
    return [RunResult.from_dict(d) for d in json.loads(path.read_text())]


def reliability(results: list[RunResult]) -> float:
    """Fraction of runs that produced a buildable, completable track."""
    if not results:
        return 0.0
    return sum(1 for r in results if r.valid and r.completed) / len(results)


def diversity(results: list[RunResult]) -> float:
    """Fraction of distinct rides among the valid, completed results.

    1.0 means every seed produced a meaningfully different ride. Close to
    0 means the method collapses to nearly the same ride regardless of
    seed. Distinctness is judged on the physical shape -- drop count,
    highest drop, length, and speed, each rounded -- rather than exact
    segment lists, since two tracks that are the same ride with one flat
    piece moved shouldn't count as different rides.

    Recorded from the start rather than added later: the goal is eventually
    generating many different kinds of rides, and that's much easier to
    have tracked from every run than to reconstruct after the fact.
    """
    ok = [r for r in results if r.valid and r.completed]
    if not ok:
        return 0.0
    signatures = {
        (r.drop_count, round(r.highest_drop), round(r.ride_length_m, -1), round(r.max_speed_mph))
        for r in ok
    }
    return len(signatures) / len(ok)


@dataclass
class MethodSummary:
    method: str
    runs: int
    reliability: float
    diversity: float
    median_excitement: Optional[float]
    best_excitement: Optional[float]
    # The game's own verdict on the runs that were judged by the oracle.
    # None until judge_results has run; `judged` says how many runs the
    # medians rest on, since a median over 2 of 25 runs is not a median.
    judged: int = 0
    median_real_excitement: Optional[float] = None
    best_real_excitement: Optional[float] = None


def summarize(results: list[RunResult]) -> list[MethodSummary]:
    """One row per method: reliability, diversity, and score distribution.

    Median rather than best-of-run is the headline quality number. Best-of-
    run is what made the 2026-08-09 repair-budget results look meaningful
    when the underlying runs were mostly noise.
    """
    by_method: dict[str, list[RunResult]] = {}
    for r in results:
        by_method.setdefault(r.method, []).append(r)

    summaries = []
    for method, rs in by_method.items():
        scores = sorted(r.ported_excitement for r in rs if r.ported_excitement is not None)
        real = sorted(r.real_excitement for r in rs if r.real_excitement is not None)
        summaries.append(MethodSummary(
            method=method,
            runs=len(rs),
            reliability=reliability(rs),
            diversity=diversity(rs),
            median_excitement=statistics.median(scores) if scores else None,
            best_excitement=max(scores) if scores else None,
            judged=len(real),
            median_real_excitement=statistics.median(real) if real else None,
            best_real_excitement=max(real) if real else None,
        ))
    return summaries


def _oracle_scorer(tracks: list[list[int]]) -> list:
    """Score each track in a real headless OpenRCT2, one at a time.

    Kept as a plain loop over `oracle.score_track` so this module stays
    independent of how the oracle drives the game. Each call costs a game
    launch on top of the test lap, so a faster batched path belongs in
    `rct2/oracle.py` behind the same interface rather than here.
    """
    from rct2.oracle import score_track

    return [score_track(segments) for segments in tracks]


def judge_results(
    results: list[RunResult],
    scorer: Optional[Callable[[list[list[int]]], list]] = None,
    top_n: Optional[int] = None,
) -> list[RunResult]:
    """Fill in `real_*` by asking the game, and hand back the same results.

    This is what breaks the circularity the research plan names: every
    method searches against the ported rating model, so reporting that same
    model's opinion of the winner measures the model as much as the method.
    The game is the only judge that isn't also the objective.

    Only results that already passed the buildable-and-completed gate are
    sent -- the gate stays the gate, and a track the game would refuse to
    build isn't worth four seconds of its time. `top_n` judges only the best
    N per method by ported excitement, for when the oracle's per-track cost
    matters more than judging every seed; the default judges all of them.

    `scorer` takes a list of segment lists and returns one result per track,
    each with `.status`, `.excitement`, `.intensity`, and `.nausea`. It
    defaults to the real oracle; tests pass a stand-in. Anything the oracle
    did not rate (a stalled train, a track the game refused to build) leaves
    the real columns empty rather than writing a low score, because "we never
    found out" and "the game hated it" are different answers.
    """
    if scorer is None:
        scorer = _oracle_scorer

    eligible = [r for r in results if r.valid and r.completed]
    if top_n is not None:
        by_method: dict[str, list[RunResult]] = {}
        for r in eligible:
            by_method.setdefault(r.method, []).append(r)
        eligible = [
            r
            for rs in by_method.values()
            for r in sorted(rs, key=lambda r: r.ported_excitement or 0.0, reverse=True)[:top_n]
        ]
    if not eligible:
        return results

    judgements = scorer([r.segments for r in eligible])
    if len(judgements) != len(eligible):
        # zip would silently truncate here, and a scorer that drops a track
        # would shift every later judgement onto the wrong run.
        raise ValueError(
            f"scorer returned {len(judgements)} judgements for {len(eligible)} tracks"
        )

    for result, judged in zip(eligible, judgements):
        if judged.status != "rated":
            continue
        result.real_excitement = judged.excitement
        result.real_intensity = judged.intensity
        result.real_nausea = judged.nausea
    return results


def rescore(path: Path, scorer=None, top_n: Optional[int] = None) -> list[RunResult]:
    """Re-judge a saved results file in place, without re-running any search.

    The point of storing full segment lists rather than derived stats: a run
    that cost an hour of search can be re-judged by a new rating model, or
    by the game, for the cost of the judging alone.
    """
    results = judge_results(load_results(path), scorer=scorer, top_n=top_n)
    save_results(results, path)
    return results

#!/usr/bin/env python3
"""Compare what ProxyFitness and PhysicsFitness actually evolve.

The two fitness functions score on incompatible scales, so their raw numbers
cannot be compared. Instead this runs seeded trials with each, then measures
the winning tracks with neutral metrics and cross-scores each winner under
both fitness functions.

The cross-scoring matrix is the point. If physics-evolved tracks already score
near the top under the proxy (and vice versa), the two are searching for the
same thing and the physics model is not changing the outcome. If they diverge,
each is finding tracks the other would not.
"""

import argparse
import random
import statistics
from dataclasses import dataclass

from rct2 import physics
from rct2.construction import validate_construction
from rct2.evolution import evolve
from rct2.fitness import (
    PhysicsFitness,
    ProxyFitness,
    count_elevation_changes,
    count_segment_variety,
    count_turns,
)
from rct2.generate import create_simple_circuit


@dataclass
class TrackMeasurement:
    """Neutral measurements of a single evolved track."""

    approach: str
    seed: int
    segments: int
    valid: bool
    # Physics stats
    completed: bool
    max_speed: float
    drop_count: int
    total_drop_height: float
    airtime: float
    max_lateral_g: float
    excitement: float
    intensity: float
    nausea: float
    # Geometric stats
    elevation_changes: int
    turn_balance: int
    variety: int
    # Cross-scores
    proxy_score: float
    physics_score: float


def measure(approach: str, seed: int, segments: list[int]) -> TrackMeasurement:
    """Measure an evolved track under both fitness functions and neutral stats."""
    result = validate_construction(segments)
    stats = physics.simulate(segments, lift_indices=set(result.lift_indices))
    ratings = physics.rate(stats)

    return TrackMeasurement(
        approach=approach,
        seed=seed,
        segments=len(segments),
        valid=result.valid,
        completed=stats.completed,
        max_speed=stats.max_speed,
        drop_count=stats.drop_count,
        total_drop_height=stats.total_drop_height,
        airtime=stats.airtime,
        max_lateral_g=stats.max_lateral_g,
        excitement=ratings.excitement,
        intensity=ratings.intensity,
        nausea=ratings.nausea,
        elevation_changes=count_elevation_changes(segments),
        turn_balance=min(count_turns(segments, "left"), count_turns(segments, "right")),
        variety=count_segment_variety(segments),
        proxy_score=ProxyFitness().evaluate(segments),
        physics_score=PhysicsFitness().evaluate(segments),
    )


def run_trial(
    approach: str,
    seed: int,
    generations: int,
    population_size: int,
) -> TrackMeasurement:
    """Evolve one track with the named fitness function and measure it."""
    fitness_fn = ProxyFitness() if approach == "proxy" else PhysicsFitness()
    stats = evolve(
        seed=create_simple_circuit(),
        rng=random.Random(seed),
        fitness_fn=fitness_fn,
        population_size=population_size,
        generations=generations,
        mutation_rate=0.1,
    )
    return measure(approach, seed, stats.best_individual.segments)


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def print_report(proxy: list[TrackMeasurement], phys: list[TrackMeasurement]) -> None:
    """Print the neutral-metric comparison and the cross-scoring matrix."""
    print()
    print("=" * 68)
    print("FITNESS COMPARISON")
    print("=" * 68)
    print(f"Trials per approach: {len(proxy)}")
    print()

    rows = [
        ("Segments", "segments", "{:.1f}"),
        ("Valid tracks", "valid", "{:.0%}"),
        ("Completes circuit", "completed", "{:.0%}"),
        ("Max speed (m/s)", "max_speed", "{:.1f}"),
        ("Drops", "drop_count", "{:.1f}"),
        ("Total drop height", "total_drop_height", "{:.1f}"),
        ("Airtime (s)", "airtime", "{:.2f}"),
        ("Max lateral g", "max_lateral_g", "{:.2f}"),
        ("Excitement", "excitement", "{:.2f}"),
        ("Intensity", "intensity", "{:.2f}"),
        ("Nausea", "nausea", "{:.2f}"),
        ("Elevation changes", "elevation_changes", "{:.1f}"),
        ("Turn balance", "turn_balance", "{:.1f}"),
        ("Segment variety", "variety", "{:.1f}"),
    ]

    print("MEAN TRACK PROPERTIES (evolved by each fitness function):")
    print("-" * 68)
    print(f"{'Metric':<24}{'Proxy':>14}{'Physics':>14}{'Difference':>14}")
    print("-" * 68)
    for label, field, fmt in rows:
        p = _mean([float(getattr(m, field)) for m in proxy])
        f = _mean([float(getattr(m, field)) for m in phys])
        diff = f - p
        diff_str = ("{:+.0%}" if fmt == "{:.0%}" else "{:+.2f}").format(diff)
        print(f"{label:<24}{fmt.format(p):>14}{fmt.format(f):>14}{diff_str:>14}")

    print()
    print("CROSS-SCORING MATRIX (mean score of each winner under each fitness):")
    print("-" * 68)
    print(f"{'Track evolved by':<24}{'Proxy score':>18}{'Physics score':>18}")
    print("-" * 68)
    print(
        f"{'Proxy':<24}"
        f"{_mean([m.proxy_score for m in proxy]):>18.1f}"
        f"{_mean([m.physics_score for m in proxy]):>18.1f}"
    )
    print(
        f"{'Physics':<24}"
        f"{_mean([m.proxy_score for m in phys]):>18.1f}"
        f"{_mean([m.physics_score for m in phys]):>18.1f}"
    )
    print()

    proxy_own = _mean([m.proxy_score for m in proxy])
    proxy_under_phys = _mean([m.physics_score for m in proxy])
    phys_own = _mean([m.physics_score for m in phys])
    phys_under_proxy = _mean([m.proxy_score for m in phys])

    print("READING:")
    print("-" * 68)
    if phys_own > proxy_under_phys:
        print(
            f"Physics-evolved tracks beat proxy-evolved tracks on physics score "
            f"({phys_own:.1f} vs {proxy_under_phys:.1f}), so optimizing physics "
            f"finds tracks the proxy does not."
        )
    else:
        print(
            f"Proxy-evolved tracks already score {proxy_under_phys:.1f} on physics "
            f"versus {phys_own:.1f} for physics-evolved ones. The physics fitness "
            f"is not finding better rides than the proxy already did."
        )
    if proxy_own > phys_under_proxy:
        print(
            f"Proxy-evolved tracks beat physics-evolved tracks on proxy score "
            f"({proxy_own:.1f} vs {phys_under_proxy:.1f}), so the two objectives "
            f"genuinely disagree."
        )
    else:
        print(
            f"Physics-evolved tracks also win on proxy score "
            f"({phys_under_proxy:.1f} vs {proxy_own:.1f}); the objectives agree."
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare tracks evolved by ProxyFitness and PhysicsFitness"
    )
    parser.add_argument("--trials", "-n", type=int, default=10,
                        help="Trials per fitness function (default: 10)")
    parser.add_argument("--generations", "-g", type=int, default=50,
                        help="Generations per trial (default: 50)")
    parser.add_argument("--population", "-p", type=int, default=30,
                        help="Population size (default: 30)")
    parser.add_argument("--seed", "-s", type=int, default=42,
                        help="Base random seed (default: 42)")
    args = parser.parse_args()

    print(f"Trials: {args.trials}, generations: {args.generations}, "
          f"population: {args.population}, base seed: {args.seed}")
    print()

    proxy_results = []
    physics_results = []
    for trial in range(args.trials):
        seed = args.seed + trial
        print(f"Trial {trial + 1}/{args.trials} (seed {seed})...")
        # Both approaches get the same seed, so they start from the same
        # random sequence and differ only in what they optimize for.
        proxy_results.append(
            run_trial("proxy", seed, args.generations, args.population)
        )
        physics_results.append(
            run_trial("physics", seed, args.generations, args.population)
        )

    print_report(proxy_results, physics_results)


if __name__ == "__main__":
    main()

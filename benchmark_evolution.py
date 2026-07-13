#!/usr/bin/env python3
"""Benchmark genetic algorithm against random search.

Compares evolution to pure random generation using equal evaluation budgets.
Runs multiple seeded trials and reports statistics.
"""

import argparse
import random
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from rct2.evolution import evolve
from rct2.fitness import ProxyFitness
from rct2.generate import create_simple_circuit
from rct2.mutations import generate_random_track


@dataclass
class TrialResult:
    """Results from a single benchmark trial."""
    approach: str
    seed: int
    best_fitness: float
    evaluations: int
    best_valid: bool


def run_evolution_trial(
    seed: int,
    evaluation_budget: int,
    population_size: int,
) -> TrialResult:
    """Run one evolution trial with the given budget."""
    rng = random.Random(seed)
    fitness_fn = ProxyFitness()

    # Calculate generations from budget
    # Budget = population_size (initial) + (population_size * generations)
    generations = (evaluation_budget - population_size) // population_size

    stats = evolve(
        seed=create_simple_circuit(),
        rng=rng,
        fitness_fn=fitness_fn,
        population_size=population_size,
        generations=generations,
        mutation_rate=0.1,
    )

    actual_evals = population_size + (population_size * generations)

    return TrialResult(
        approach="evolution",
        seed=seed,
        best_fitness=stats.best_fitness,
        evaluations=actual_evals,
        best_valid=stats.best_individual.is_valid(),
    )


def run_random_trial(
    seed: int,
    evaluation_budget: int,
) -> TrialResult:
    """Run one random search trial with the given budget."""
    rng = random.Random(seed)
    fitness_fn = ProxyFitness()

    best_fitness = float('-inf')
    best_valid = False

    for _ in range(evaluation_budget):
        track = generate_random_track(rng)
        fitness = fitness_fn.evaluate(track)

        if fitness > best_fitness:
            best_fitness = fitness
            # Quick validity check (closed circuit)
            from rct2.geometry import Position, is_closed_circuit
            best_valid = is_closed_circuit(Position(), track)

    return TrialResult(
        approach="random",
        seed=seed,
        best_fitness=best_fitness,
        evaluations=evaluation_budget,
        best_valid=best_valid,
    )


def run_benchmark(
    num_trials: int,
    evaluation_budget: int,
    population_size: int,
    base_seed: int,
) -> tuple[list[TrialResult], list[TrialResult]]:
    """Run benchmark trials for both approaches."""

    evolution_results = []
    random_results = []

    for trial in range(num_trials):
        seed = base_seed + trial

        print(f"Running trial {trial + 1}/{num_trials} (seed {seed})...")

        # Evolution trial
        evo_result = run_evolution_trial(seed, evaluation_budget, population_size)
        evolution_results.append(evo_result)
        print(f"  Evolution: fitness={evo_result.best_fitness:.1f}, valid={evo_result.best_valid}")

        # Random trial
        rand_result = run_random_trial(seed, evaluation_budget)
        random_results.append(rand_result)
        print(f"  Random:    fitness={rand_result.best_fitness:.1f}, valid={rand_result.best_valid}")

    return evolution_results, random_results


def print_statistics(evolution_results: list[TrialResult], random_results: list[TrialResult]):
    """Print comparison statistics."""

    evo_fitness = [r.best_fitness for r in evolution_results]
    rand_fitness = [r.best_fitness for r in random_results]

    evo_valid_count = sum(1 for r in evolution_results if r.best_valid)
    rand_valid_count = sum(1 for r in random_results if r.best_valid)

    print("\n" + "="*60)
    print("BENCHMARK RESULTS")
    print("="*60)
    print()
    print(f"Trials per approach: {len(evolution_results)}")
    print(f"Evaluation budget: {evolution_results[0].evaluations}")
    print()

    print("FITNESS STATISTICS:")
    print("-" * 60)
    print(f"{'Metric':<20} {'Evolution':>15} {'Random':>15} {'Difference':>10}")
    print("-" * 60)

    evo_mean = statistics.mean(evo_fitness)
    rand_mean = statistics.mean(rand_fitness)
    print(f"{'Mean':<20} {evo_mean:>15.1f} {rand_mean:>15.1f} {evo_mean - rand_mean:>+10.1f}")

    evo_median = statistics.median(evo_fitness)
    rand_median = statistics.median(rand_fitness)
    print(f"{'Median':<20} {evo_median:>15.1f} {rand_median:>15.1f} {evo_median - rand_median:>+10.1f}")

    evo_min = min(evo_fitness)
    rand_min = min(rand_fitness)
    print(f"{'Min':<20} {evo_min:>15.1f} {rand_min:>15.1f} {evo_min - rand_min:>+10.1f}")

    evo_max = max(evo_fitness)
    rand_max = max(rand_fitness)
    print(f"{'Max':<20} {evo_max:>15.1f} {rand_max:>15.1f} {evo_max - rand_max:>+10.1f}")

    if len(evo_fitness) > 1:
        evo_stdev = statistics.stdev(evo_fitness)
        rand_stdev = statistics.stdev(rand_fitness)
        print(f"{'Std Dev':<20} {evo_stdev:>15.1f} {rand_stdev:>15.1f}")

    print()
    print("VALIDITY:")
    print("-" * 60)
    print(f"Evolution valid: {evo_valid_count}/{len(evolution_results)} ({100*evo_valid_count/len(evolution_results):.0f}%)")
    print(f"Random valid:    {rand_valid_count}/{len(random_results)} ({100*rand_valid_count/len(random_results):.0f}%)")
    print()

    # Simple conclusion
    improvement = evo_mean - rand_mean
    improvement_pct = 100 * improvement / abs(rand_mean) if rand_mean != 0 else 0

    print("CONCLUSION:")
    print("-" * 60)
    if improvement > 0:
        print(f"Evolution outperforms random search by {improvement:.1f} fitness points ({improvement_pct:+.1f}%).")
    elif improvement < 0:
        print(f"Random search outperforms evolution by {-improvement:.1f} fitness points ({-improvement_pct:+.1f}%).")
    else:
        print("Evolution and random search perform equally.")

    if evo_valid_count > rand_valid_count:
        print(f"Evolution also produces {evo_valid_count - rand_valid_count} more valid tracks.")
    elif evo_valid_count < rand_valid_count:
        print(f"Random search produces {rand_valid_count - evo_valid_count} more valid tracks.")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark genetic algorithm against random search"
    )
    parser.add_argument(
        "--trials", "-n",
        type=int,
        default=20,
        help="Number of trials per approach (default: 20)",
    )
    parser.add_argument(
        "--budget", "-b",
        type=int,
        default=1000,
        help="Evaluation budget per trial (default: 1000)",
    )
    parser.add_argument(
        "--population", "-p",
        type=int,
        default=50,
        help="Population size for evolution (default: 50)",
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=42,
        help="Base random seed (default: 42)",
    )

    args = parser.parse_args()

    print("BENCHMARK CONFIGURATION")
    print("="*60)
    print(f"Trials per approach: {args.trials}")
    print(f"Evaluation budget: {args.budget}")
    print(f"Evolution population: {args.population}")
    print(f"Base seed: {args.seed}")
    print("="*60)
    print()

    evolution_results, random_results = run_benchmark(
        num_trials=args.trials,
        evaluation_budget=args.budget,
        population_size=args.population,
        base_seed=args.seed,
    )

    print_statistics(evolution_results, random_results)


if __name__ == "__main__":
    main()

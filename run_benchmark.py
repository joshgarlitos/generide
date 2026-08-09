#!/usr/bin/env python3
"""CLI for the method-comparison benchmark harness.

Usage:
    python run_benchmark.py
    python run_benchmark.py --methods random ga --seeds 25 --evaluations 2000
    python run_benchmark.py --output benchmark_results/2026-08-10.json

See docs/research-plan.md for why this exists and rct2/benchmark.py for the
comparison design: equal evaluation budgets, a hard buildable-and-completed
gate before any score counts, and reliability/diversity tracked alongside
quality rather than reporting best-of-run alone.
"""

import argparse
from pathlib import Path

from rct2.benchmark import METHODS, run_benchmark, save_results, summarize


def main():
    parser = argparse.ArgumentParser(
        description="Compare coaster-generation methods under equal evaluation budgets"
    )
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=list(METHODS),
        default=list(METHODS),
        help="Which methods to run (default: all registered)",
    )
    parser.add_argument(
        "--seeds", "-n",
        type=int,
        default=25,
        help="Number of seeds per method (default: 25 -- see docs/research-plan.md "
             "for why 3 wasn't enough)",
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=1,
        help="First seed; seeds run consecutively from here (default: 1)",
    )
    parser.add_argument(
        "--evaluations", "-e",
        type=int,
        default=2000,
        help="Track evaluations per run, same for every method (default: 2000)",
    )
    parser.add_argument(
        "--max-width",
        type=int,
        default=30,
        help="Maximum track footprint width in tiles (default: 30)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=30,
        help="Maximum track footprint depth in tiles (default: 30)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Where to save full results as JSON (default: "
             "benchmark_results/<timestamp>.json)",
    )

    args = parser.parse_args()

    if args.output is None:
        from datetime import datetime
        args.output = Path(f"benchmark_results/{datetime.now():%Y%m%d-%H%M%S}.json")

    seeds = list(range(args.base_seed, args.base_seed + args.seeds))
    methods = {name: METHODS[name] for name in args.methods}

    print(f"Methods: {', '.join(methods)}")
    print(f"Seeds: {len(seeds)} (from {seeds[0]} to {seeds[-1]})")
    print(f"Evaluation budget: {args.evaluations} per run")
    print()

    results = run_benchmark(
        methods, seeds, args.evaluations,
        max_width=args.max_width, max_depth=args.max_depth,
    )
    save_results(results, args.output)
    print(f"Saved {len(results)} results to {args.output}")
    print()

    print(f"{'method':<10} {'runs':>5} {'reliability':>12} {'diversity':>10} "
          f"{'median E':>9} {'best E':>8}")
    for row in summarize(results):
        median = f"{row.median_excitement:.2f}" if row.median_excitement is not None else "n/a"
        best = f"{row.best_excitement:.2f}" if row.best_excitement is not None else "n/a"
        print(f"{row.method:<10} {row.runs:>5} {row.reliability:>11.0%} "
              f"{row.diversity:>10.0%} {median:>9} {best:>8}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""How often the page's default run meets the ride bar (R16), by run size.

Ride quality does not depend on where the engine runs: a Pyodide run and a
CPython run with the same seed and settings produce the same .td6 (checked
by measure.mjs), so this measures quality in fast native Python across many
seeds, and measure.mjs measures time in Pyodide on a few.

Usage (from the repo root):
    python demo/tools/ride_bar.py --sizes 20x20 30x30 --seeds 1-10
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rct2 import demo  # noqa: E402


def one(job):
    generations, population, seed, values = job
    result = demo.run(dict(values, seed=seed), lambda kind, payload: None,
                      generations=generations, population=population)
    summary = result["summary"]
    return {
        "generations": generations,
        "population": population,
        "seed": seed,
        "meets_bar": demo.meets_ride_bar(summary),
        "valid": summary["valid"],
        "completed": summary["completed"],
        "drops": summary["stats"]["drop_count"],
        "excitement": round(summary["estimated"]["excitement"], 2),
    }


def parse_seeds(text):
    low, _, high = text.partition("-")
    return list(range(int(low), int(high or low) + 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", nargs="+", default=["30x30"], help="GENERATIONSxPOPULATION")
    parser.add_argument("--seeds", default="1-10", help="a range such as 1-10")
    parser.add_argument("--values", default="{}", help="JSON of page settings, default the page defaults")
    args = parser.parse_args()

    values = json.loads(args.values)
    jobs = []
    for size in args.sizes:
        generations, population = (int(n) for n in size.split("x"))
        jobs += [(generations, population, seed, values) for seed in parse_seeds(args.seeds)]
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(one, jobs))
    for size in args.sizes:
        generations, population = (int(n) for n in size.split("x"))
        mine = [r for r in rows if (r["generations"], r["population"]) == (generations, population)]
        passed = [r["seed"] for r in mine if r["meets_bar"]]
        failed = [r["seed"] for r in mine if not r["meets_bar"]]
        print(f"{size}: {len(passed)}/{len(mine)} meet the bar; failing seeds {failed}")
    print(json.dumps(rows))


if __name__ == "__main__":
    main()

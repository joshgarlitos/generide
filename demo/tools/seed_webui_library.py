#!/usr/bin/env python3
"""Fill a throwaway run library with finished runs for the browser tests.

demo/playwright.config.mjs runs this before it starts the local web UI, so
demo/tests/webui.spec.mjs has finished runs to open and compare without
running an evolution. Each run holds the Manic Miner fixture as its best
ride, built the way tests/test_webui.py's saved_run builds one. The oldest run
(seed 4) was given a narrow site and also carries a second ride, the best one
that fits it, which a train would stall on.

Usage: GENERIDE_HOME=<throwaway folder> python demo/tools/seed_webui_library.py
The folder named by GENERIDE_HOME is cleared first, so never point it at a
real library. The script refuses to run without GENERIDE_HOME set. It prints
the run ids, one per line.
"""

import os
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from rct2 import runrecord, settings, td6  # noqa: E402

MANIC_MINER = REPO / "data" / "sample_rides" / "manic_miner_test.td6"
# A process id that is not running, so the run reads as finished and not as
# still going.
DEAD_PID = 999999


def seed_run(seed):
    segments = [e.segment_type for e in td6.load(MANIC_MINER).elements]
    values = settings.validate({"seed": seed}).values
    run_id = runrecord.create_run(
        seed=seed, request=values, settings=settings.cli_args(values),
        generations=values["generations"], pid=DEAD_PID,
    )
    now = time.time()
    for gen in range(4):
        runrecord.append_progress(run_id, {"generation": gen, "time": now + gen,
                                           "best_fitness": float(gen)})
    runrecord.append_improvement(run_id, {"generation": 3, "time": now, "fitness": 3.0,
                                          "segments": segments})
    summary = runrecord.ride_summary(segments, values["max_width"], values["max_depth"])
    summary.update(fitness=3.0, stopped_early=False, exported=True)
    (runrecord.run_dir(run_id) / "best.td6").write_bytes(MANIC_MINER.read_bytes())
    runrecord.finish_run(run_id, "completed", generations_run=4, result=summary)
    return run_id


def seed_two_ride_run(seed):
    from rct2.generate import create_simple_circuit
    from rct2.site import Site

    segments = [e.segment_type for e in td6.load(MANIC_MINER).elements]
    oval = create_simple_circuit()
    site = Site.from_rows(["." * 8] * 14, anchor=(4, 7))
    home = runrecord.generide_home()
    given = home / "narrow-site.json"
    site.save(given)
    values = settings.validate({"seed": seed, "site": str(given)}).values
    run_id = runrecord.create_run(
        seed=seed, request=values, settings=settings.cli_args(values),
        generations=values["generations"], pid=DEAD_PID,
    )
    runrecord.save_site(run_id, site)
    now = time.time()
    for gen in range(4):
        runrecord.append_progress(run_id, {"generation": gen, "time": now + gen,
                                           "best_fitness": float(gen)})
    runrecord.append_improvement(run_id, {"generation": 3, "time": now, "fitness": 3.0,
                                          "segments": segments})
    summary = runrecord.ride_summary(
        segments, values["max_width"], values["max_depth"], site=site,
    )
    summary.update(fitness=3.0, stopped_early=False, exported=True)
    summary["fitting_ride"] = dict(
        runrecord.ride_summary(oval, values["max_width"], values["max_depth"], site=site),
        track=oval, playable=False, fitness=1.0, file=runrecord.FITS_TD6,
    )
    (runrecord.run_dir(run_id) / "best.td6").write_bytes(MANIC_MINER.read_bytes())
    (runrecord.run_dir(run_id) / runrecord.FITS_TD6).write_bytes(MANIC_MINER.read_bytes())
    runrecord.finish_run(run_id, "completed", generations_run=4, result=summary)
    return run_id


def main():
    home = os.environ.get("GENERIDE_HOME")
    if not home:
        sys.exit("Set GENERIDE_HOME to a throwaway folder; this script clears it.")
    shutil.rmtree(home, ignore_errors=True)
    Path(home).mkdir(parents=True)
    # Oldest first, so the library lists the plain runs (seeds 6 and 5) ahead of it.
    print(seed_two_ride_run(4))
    for seed in (5, 6):
        print(seed_run(seed))


if __name__ == "__main__":
    main()

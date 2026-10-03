"""One run for the in-browser page, built the way the CLI builds it.

The page (demo/) runs this module inside Pyodide, in a Web Worker, so a
visitor can evolve a Mine Train without installing anything. It shows a
short list of the settings the local web UI has, fixes the rest, and keeps
every run small enough to finish quickly in a browser.

`run()` builds the seed track, the fitness function, and the `evolve_parts`
call exactly as `evolve_coaster.py` does for `--genome parts --fitness
physics`, so the `cli_args` it returns reproduce the same ride in the CLI,
byte for byte (pinned by tests/test_demo.py). It reports through one
`emit(kind, payload)` callback:

- "progress", once per generation: the generation and the score curve so far
- "best", every time the best ride improves: a complete result for that ride
  (pictures, summary, and the .td6 bytes), so stopping a run at any point
  still has a whole ride to show
- the final result is the return value

Everything here is plain data (str, int, float, bool, list, dict, bytes) so
it crosses from Python to JavaScript without special handling.
"""

import random
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from rct2 import checksum, render, runrecord, settings, td6, webui
from rct2.evolution import evolve_parts
from rct2.fitness import CoasterRequest, PhysicsFitness
from rct2.generate import create_hill_circuit

TEMPLATE = Path(__file__).resolve().parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"

# The settings a visitor sees, in the order the page shows them.
VISIBLE = (
    "seed",
    "station_length",
    "max_width",
    "max_depth",
    "target_excitement",
    "target_intensity",
    "target_nausea",
)

# Fixed for every page run. Physics scoring is what rating windows need and
# what produces real drops; parts is the CLI's default genome.
FIXED = {"fitness": "physics", "genome": "parts", "mutation_rate": 0.1}

# Run size and the starting seed, from measurements (docs/devlog.md,
# 2026-10-03). 25 generations of 25 is the largest size whose slowest
# allowed settings still finish in about 27 seconds in Pyodide; at that size
# every one of 20 measured seeds meets the ride bar (R16), and seed 2 gave
# the most exciting default ride.
GENERATIONS = 25
POPULATION = 25
DEFAULT_SEED = 2

# Tighter than the local web UI's ranges, so the slowest allowed settings
# still finish quickly. Measured alongside the run size.
MAXIMUMS = {"station_length": 12, "max_width": 60, "max_depth": 60}

Emit = Callable[[str, Dict[str, Any]], None]


def settings_view() -> Dict[str, Any]:
    """The form the page shows: curated rows from the shared settings table."""
    rows = []
    for row in settings.table():
        if row["key"] not in VISIBLE:
            continue
        if row["key"] in MAXIMUMS:
            row["maximum"] = MAXIMUMS[row["key"]]
        if row["key"] == "seed":
            row["default"] = DEFAULT_SEED
        rows.append(row)
    rows.sort(key=lambda row: VISIBLE.index(row["key"]))
    return {
        "settings": rows,
        "generations": GENERATIONS,
        "population": POPULATION,
        "estimate_note": settings.ESTIMATE_NOTE,
    }


def validate(raw_values: Dict[str, Any]) -> Dict[str, Any]:
    """Check page values with the shared validator, then the page's own limits.

    A blank field takes the local web UI's default, except a blank seed,
    which stays blank so `run()` picks one and reports it.
    """
    errors: Dict[str, str] = {}
    for key in raw_values:
        if key not in VISIBLE:
            errors[key] = f"{key} is not a setting this page offers."
    check = settings.validate({k: v for k, v in raw_values.items() if k in VISIBLE})
    errors.update(check.errors)
    values = dict(check.values)
    values.update(FIXED)
    for key, maximum in MAXIMUMS.items():
        s = settings.BY_KEY[key]
        unit = f" {s.unit}" if s.unit else ""
        page_range = f"{s.label} must be from {s.minimum:g} to {maximum}{unit} on this page."
        out_of_range = values.get(key) is not None and values[key] > maximum
        # The shared validator names the local web UI's wider range; on this
        # page the form shows the narrower one, so say that instead.
        shared_range = errors.get(key, "").startswith(f"{s.label} must be from ")
        if out_of_range or shared_range:
            errors[key] = page_range
    return {"values": values, "errors": errors}


def _window(value: Optional[List[float]]):
    return None if value is None else (float(value[0]), float(value[1]))


def ride_result(segments: List[int], max_width: Optional[int], max_depth: Optional[int]) -> Dict[str, Any]:
    """Pictures, summary, and .td6 bytes for one ride.

    A ride that fails construction checks gets no .td6, as in the CLI, which
    never exports one.
    """
    summary = runrecord.ride_summary(segments, max_width, max_depth)
    data = None
    if summary["valid"]:
        from evolve_coaster import create_ride_from_segments

        ride = create_ride_from_segments(list(segments), TEMPLATE)
        data = checksum.append(td6.encode(ride))
    return {
        "summary": summary,
        # The local web UI's own wording for the numbers and the flags.
        "stats_view": webui._stats_view(summary, {}),
        "warnings": webui._warnings(summary, {}),
        "plan_svg": render.render_track(segments, title="Top-down plan"),
        "profile_svg": render.render_profile(
            segments, lift_indices=set(summary["lift_indices"]), title="Side profile",
        ),
        "td6": data,
    }


def meets_ride_bar(summary: Dict[str, Any]) -> bool:
    """R16: the ride builds, its train finishes the circuit, and it has a drop."""
    return bool(summary["valid"] and summary["completed"] and summary["stats"]["drop_count"] >= 1)


def run(
    raw_values: Dict[str, Any],
    emit: Emit,
    generations: Optional[int] = None,
    population: Optional[int] = None,
) -> Dict[str, Any]:
    """Run one request. Returns the final result, or {"errors": ...} with no run."""
    check = validate(raw_values)
    if check["errors"]:
        return {"errors": check["errors"]}
    values = check["values"]
    generations = GENERATIONS if generations is None else generations
    population = POPULATION if population is None else population

    # Recorded in the values so cli_args() names the size this run used.
    values["generations"] = generations
    values["population"] = population

    seed = values["seed"]
    if seed is None:
        seed = random.randint(0, settings.SEED_MAX)
        values["seed"] = seed
    rng = random.Random(seed)

    request = CoasterRequest(
        max_width=values["max_width"],
        max_depth=values["max_depth"],
        excitement=_window(values["target_excitement"]),
        intensity=_window(values["target_intensity"]),
        nausea=_window(values["target_nausea"]),
    )
    fitness_fn = PhysicsFitness.from_request(request)
    start = create_hill_circuit(station_length=values["station_length"])

    history: List[float] = []
    valid_history: List[float] = []
    best_sent: List[float] = []

    def send_best(generation: int, individual) -> None:
        best_sent[:] = [individual.fitness]
        payload = ride_result(individual.segments, values["max_width"], values["max_depth"])
        payload.update(generation=generation, fitness=individual.fitness)
        emit("best", payload)

    def progress(generation: int, population_now) -> None:
        best = population_now.best()
        history.append(best.fitness if best else 0.0)
        valid_history.append(
            population_now.valid_count() / len(population_now.individuals)
            if population_now.individuals else 0.0
        )
        emit("progress", {
            "seed": seed,
            "generation": generation,
            "generations": generations,
            "best_fitness": best.fitness if best else None,
            "avg_fitness": population_now.average_fitness(),
            "fitness_svg": render.render_fitness_history(
                history, valid_history, title="Best score by generation",
            ),
        })
        if best is not None and (not best_sent or best.fitness > best_sent[0]):
            send_best(generation, best)

    stats = evolve_parts(
        seed=start,
        rng=rng,
        fitness_fn=fitness_fn,
        population_size=population,
        generations=generations,
        mutation_rate=values["mutation_rate"],
        progress_callback=progress,
    )

    best = stats.best_individual
    result = ride_result(best.segments, values["max_width"], values["max_depth"])
    if not best_sent or best.fitness > best_sent[0]:
        # A best bred in the last generation only shows up here, as in the CLI.
        emit("best", dict(result, generation=stats.generations, fitness=best.fitness))
    result.update(
        seed=seed,
        values=values,
        fitness=best.fitness,
        generations_run=stats.generations,
        stopped_early=False,
        meets_ride_bar=meets_ride_bar(result["summary"]),
        cli_args=settings.cli_args(values),
    )
    return result

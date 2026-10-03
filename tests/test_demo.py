"""Tests for rct2/demo.py, the run module behind the in-browser page.

The page runs this module inside Pyodide. Here it runs under CPython, which
is enough to pin what matters: the module builds a run exactly the way
`evolve_coaster.py` does, so a seed from the page reproduces in the CLI, and
it reports progress, every improvement, and the final ride as plain data the
page can show without asking the engine anything else.
"""

import subprocess
import sys
from pathlib import Path

from rct2 import demo
from rct2.generate import create_hill_circuit, create_simple_circuit

REPO = Path(__file__).resolve().parent.parent

# Small enough to keep the suite fast, big enough to breed a few generations.
SMALL = dict(generations=4, population=8)


def _collect(values, **size):
    events = []
    final = demo.run(values, lambda kind, payload: events.append((kind, payload)), **size)
    return final, events


def test_run_matches_the_cli_byte_for_byte(tmp_path):
    values = {"seed": 123, "station_length": 6}
    final, _ = _collect(values, **SMALL)
    assert final["td6"] is not None

    out = tmp_path / "cli.td6"
    # The page's own command, unchanged apart from where to write the file.
    args = final["cli_args"] + ["--no-record", "--output", str(out)]
    subprocess.run(
        [sys.executable, str(REPO / "evolve_coaster.py"), *args],
        cwd=REPO, check=True, capture_output=True,
    )
    assert out.read_bytes() == final["td6"]


def test_cli_args_carry_the_hidden_fixed_settings():
    final, _ = _collect({"seed": 7}, **SMALL)
    args = final["cli_args"]
    assert args[args.index("--fitness") + 1] == "physics"
    assert args[args.index("--genome") + 1] == "parts"
    assert args[args.index("--rng-seed") + 1] == "7"
    assert args.count("--generations") == 1
    assert args[args.index("--generations") + 1] == str(SMALL["generations"])
    assert args[args.index("--population") + 1] == str(SMALL["population"])


def test_progress_comes_once_per_generation_and_improvements_carry_a_ride():
    final, events = _collect({"seed": 123}, **SMALL)
    progress = [p for kind, p in events if kind == "progress"]
    best = [p for kind, p in events if kind == "best"]

    assert [p["generation"] for p in progress] == list(range(SMALL["generations"]))
    assert progress[-1]["fitness_svg"].startswith("<svg")
    assert best, "the first generation always sets a best ride"
    first = best[0]
    assert first["plan_svg"].startswith("<svg")
    assert first["profile_svg"].startswith("<svg")
    assert first["summary"]["segments"] > 0
    assert final["generations_run"] == SMALL["generations"]
    assert final["stopped_early"] is False


def test_blank_seed_picks_one_and_reports_it_so_it_can_be_rerun():
    final, _ = _collect({"seed": ""}, **SMALL)
    seed = final["seed"]
    assert isinstance(seed, int)

    again, _ = _collect({"seed": seed}, **SMALL)
    assert again["td6"] == final["td6"]


def test_invalid_input_is_reported_and_no_run_starts():
    events = []
    result = demo.run({"station_length": 1}, lambda kind, payload: events.append(kind), **SMALL)
    maximum = demo.MAXIMUMS["station_length"]
    assert result["errors"]["station_length"] == f"Station length must be from 2 to {maximum} tiles on this page."
    assert events == []


def test_values_above_the_demo_maximums_are_rejected():
    for key, setting in demo.MAXIMUMS.items():
        check = demo.validate({key: setting + 1})
        assert key in check["errors"]
        assert str(setting) in check["errors"][key]


def test_unknown_settings_are_refused():
    check = demo.validate({"oracle_calibrate": True})
    assert "oracle_calibrate" in check["errors"]


def test_settings_view_shows_only_the_curated_settings_with_the_default_seed():
    view = demo.settings_view()
    keys = [row["key"] for row in view["settings"]]
    assert keys == list(demo.VISIBLE)
    seed = next(row for row in view["settings"] if row["key"] == "seed")
    assert seed["default"] == demo.DEFAULT_SEED
    for row in view["settings"]:
        if row["key"] in demo.MAXIMUMS:
            assert row["maximum"] == demo.MAXIMUMS[row["key"]]


def test_a_construction_invalid_ride_has_no_download():
    # Covers AE3: the page, like the CLI, never exports a track that fails
    # construction checks.
    broken = create_simple_circuit(station_length=6)[:-3]
    result = demo.ride_result(broken, max_width=30, max_depth=30)
    assert result["summary"]["valid"] is False
    assert result["td6"] is None


def test_a_buildable_ride_whose_train_stalls_is_still_offered():
    # The flat starter loop builds but has no lift, so the train stops.
    flat = create_simple_circuit(station_length=6)
    result = demo.ride_result(flat, max_width=30, max_depth=30)
    assert result["summary"]["valid"] is True
    assert result["summary"]["completed"] is False
    assert result["td6"] is not None


def test_ride_bar_matches_r16():
    assert demo.meets_ride_bar(demo.ride_result(create_hill_circuit(station_length=6), 30, 30)["summary"])
    flat = demo.ride_result(create_simple_circuit(station_length=6), 30, 30)
    assert not demo.meets_ride_bar(flat["summary"])


def test_results_carry_the_web_uis_stats_table_and_warnings():
    flat = demo.ride_result(create_simple_circuit(station_length=6), 30, 30)
    labels = [row["label"] for row in flat["stats_view"]["simulated"]]
    assert "Top speed" in labels and "Completes the circuit" in labels
    assert any("does not complete the circuit" in w for w in flat["warnings"])

    broken = demo.ride_result(create_simple_circuit(station_length=6)[:-3], 30, 30)
    assert any("fails construction checks" in w for w in broken["warnings"])

    hill = demo.ride_result(create_hill_circuit(station_length=6), 30, 30)
    assert hill["warnings"] == []


def test_out_of_range_messages_name_the_pages_range_not_the_local_one():
    # 99 is past both the local web UI's limit and this page's; the message
    # should name the range the page's form shows.
    check = demo.validate({"station_length": 99})
    maximum = demo.MAXIMUMS["station_length"]
    assert check["errors"]["station_length"] == f"Station length must be from 2 to {maximum} tiles on this page."

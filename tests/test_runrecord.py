"""Tests for the run record and library."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from rct2 import runrecord
from rct2.runrecord import (
    InvalidRunId,
    RunIsActive,
    UnsupportedSchema,
    append_improvement,
    append_progress,
    create_run,
    delete_run,
    display_name,
    finish_run,
    library_root,
    list_runs,
    load_run,
    new_run_id,
    record_check,
    record_install,
    stagnation,
    time_remaining,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOCK = datetime(2026, 9, 27, 9, 36, 12, tzinfo=timezone.utc)


def _dead_pid():
    """A pid that is guaranteed not to be running: a child we already reaped."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def _make(seed=7, **kw):
    kw.setdefault("request", {"generations": 60, "seed": seed})
    kw.setdefault("settings", ["--generations", "60", "--rng-seed", str(seed)])
    kw.setdefault("generations", 60)
    kw.setdefault("pid", os.getpid())
    return create_run(seed=seed, **kw)


class TestLibraryLocation:
    def test_root_follows_generide_home(self, isolated_generide_home):
        assert library_root() == isolated_generide_home / "runs"

    def test_default_root_is_under_the_home_folder(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GENERIDE_HOME")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert library_root() == tmp_path / ".generide" / "runs"


class TestRoundTrip:
    def test_create_append_finish_round_trips_every_field(self):
        run_id = _make(seed=42, parent="20260926T100000Z-s1", now=CLOCK)
        append_progress(run_id, {"generation": 0, "time": 1.0, "best_fitness": 3.0})
        append_progress(run_id, {"generation": 1, "time": 2.0, "best_fitness": 4.5})
        append_improvement(run_id, {"generation": 1, "fitness": 4.5, "segments": [1, 2, 3]})
        finish_run(run_id, "completed", generations_run=60,
                   result={"valid": True, "stats": {"max_speed": 12.5}})
        record_check(run_id, {"status": "rated", "excitement": 5.1})
        record_install(run_id, {"name": "Canyon", "file": "Canyon.td6"})

        run = load_run(run_id)
        rec = run.record
        assert rec["schema_version"] == runrecord.SCHEMA_VERSION
        assert rec["id"] == run_id == "20260927T093612Z-s42"
        assert rec["seed"] == 42
        assert rec["request"] == {"generations": 60, "seed": 42}
        assert rec["settings"] == ["--generations", "60", "--rng-seed", "42"]
        assert rec["parent"] == "20260926T100000Z-s1"
        assert rec["status"] == "completed"
        assert rec["generations_planned"] == 60
        assert rec["generations_run"] == 60
        assert rec["finished"] is not None
        assert rec["result"] == {"valid": True, "stats": {"max_speed": 12.5}}
        assert rec["checks"][0]["status"] == "rated"
        assert rec["check_status"] is None
        assert rec["installs"][0]["name"] == "Canyon"
        assert [p["generation"] for p in run.progress] == [0, 1]
        assert run.improvements == [{"generation": 1, "fitness": 4.5, "segments": [1, 2, 3]}]

    def test_explicit_id_is_used_and_cannot_be_reused(self):
        run_id = _make(run_id="20260927T093612Z-s5")
        assert run_id == "20260927T093612Z-s5"
        with pytest.raises(FileExistsError):
            _make(run_id="20260927T093612Z-s5")

    def test_explicit_id_may_use_a_directory_made_ahead_of_time(self):
        directory = library_root() / "20260927T093612Z-s6"
        directory.mkdir(parents=True)
        (directory / "console.log").write_text("starting\n")
        assert list_runs() == []  # nothing to show until the run file exists
        assert _make(run_id="20260927T093612Z-s6") == "20260927T093612Z-s6"
        assert (directory / "console.log").exists()

    def test_same_second_and_seed_gets_a_numeric_suffix(self):
        first = _make(seed=3, now=CLOCK)
        second = _make(seed=3, now=CLOCK)
        assert first == "20260927T093612Z-s3"
        assert second == "20260927T093612Z-s3-2"

    def test_truncated_last_log_line_drops_only_that_line(self):
        run_id = _make()
        append_progress(run_id, {"generation": 0, "time": 1.0, "best_fitness": 1.0})
        append_progress(run_id, {"generation": 1, "time": 2.0, "best_fitness": 2.0})
        with (library_root() / run_id / "progress.jsonl").open("a") as f:
            f.write('{"generation": 2, "ti')
        assert [p["generation"] for p in load_run(run_id).progress] == [0, 1]

    def test_unknown_future_schema_fails_clearly(self):
        run_id = _make()
        path = library_root() / run_id / "run.json"
        data = json.loads(path.read_text())
        data["schema_version"] = runrecord.SCHEMA_VERSION + 1
        path.write_text(json.dumps(data))
        with pytest.raises(UnsupportedSchema, match="newer version"):
            load_run(run_id)


class TestListing:
    def test_newest_first_including_separately_created_runs(self):
        older = _make(seed=1, now=datetime(2026, 9, 1, tzinfo=timezone.utc))
        newer = _make(seed=2, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
        # A terminal run creates its directory on its own; listing just finds it.
        subprocess.run(
            [sys.executable, "-c",
             "from rct2.runrecord import create_run; "
             "create_run(seed=9, request={}, settings=[], generations=5)"],
            check=True, env=os.environ.copy(), cwd=REPO,
        )
        ids = [r["id"] for r in list_runs()]
        assert len(ids) == 3
        assert ids[1:] == [newer, older]

    def test_empty_library_lists_nothing(self):
        assert list_runs() == []

    def test_unreadable_run_is_listed_as_unreadable_not_raised(self):
        run_id = _make()
        (library_root() / run_id / "run.json").write_text("{not json")
        (entry,) = list_runs()
        assert entry["id"] == run_id
        assert entry["status"] == "unreadable"


class TestStatusRepair:
    def test_running_run_with_dead_pid_is_interrupted_and_saved(self):
        run_id = _make(pid=_dead_pid())
        assert load_run(run_id).record["status"] == "interrupted"
        saved = json.loads((library_root() / run_id / "run.json").read_text())
        assert saved["status"] == "interrupted"
        assert list_runs()[0]["status"] == "interrupted"

    def test_running_run_with_live_pid_stays_running(self):
        run_id = _make(pid=os.getpid())
        assert load_run(run_id).record["status"] == "running"

    def test_finished_run_is_never_repaired(self):
        run_id = _make(pid=_dead_pid())
        finish_run(run_id, "completed", generations_run=60)
        assert load_run(run_id).record["status"] == "completed"


class TestDelete:
    def test_delete_removes_the_run_and_nothing_in_the_track_folder(self, tmp_path):
        track_dir = tmp_path / "tracks"
        track_dir.mkdir()
        installed = track_dir / "Canyon.td6"
        installed.write_bytes(b"design")
        run_id = _make(pid=_dead_pid())
        finish_run(run_id, "completed", generations_run=60)
        record_install(run_id, {"name": "Canyon", "file": str(installed)})

        delete_run(run_id)

        assert not (library_root() / run_id).exists()
        assert list_runs() == []
        assert installed.read_bytes() == b"design"

    def test_deleting_a_running_run_is_refused(self):
        run_id = _make(pid=os.getpid())
        with pytest.raises(RunIsActive):
            delete_run(run_id)
        assert (library_root() / run_id).exists()

    def test_deleting_an_interrupted_run_is_allowed(self):
        run_id = _make(pid=_dead_pid())
        delete_run(run_id)
        assert not (library_root() / run_id).exists()


class TestRunIds:
    @pytest.mark.parametrize("bad", [
        "..", "../x", "a/b", "20260927T093612Z-s1/../..", "", "run.json",
        "20260927T093612Z-s1\n", "20260927T093612Z-s1 ", "/etc/passwd",
    ])
    def test_bad_ids_are_rejected_before_touching_files(self, bad, monkeypatch):
        touched = []
        monkeypatch.setattr(runrecord, "library_root", lambda: touched.append(1))
        for fn in (load_run, delete_run):
            with pytest.raises(InvalidRunId):
                fn(bad)
        assert touched == []

    def test_generated_ids_pass_validation(self):
        runrecord.validate_run_id(new_run_id(123, CLOCK))
        runrecord.validate_run_id(new_run_id(-5, CLOCK))
        runrecord.validate_run_id("20260927T093612Z-s3-2")


class TestDisplayName:
    def test_latest_install_name_wins(self):
        rec = {"seed": 4, "created": CLOCK.isoformat(),
               "installs": [{"name": "First"}, {"name": "Second"}]}
        assert display_name(rec) == "Second"

    def test_never_installed_uses_date_and_seed(self):
        rec = {"seed": 4, "created": CLOCK.isoformat(), "installs": []}
        assert display_name(rec) == "2026-09-27 09:36, seed 4"


def _progress(durations, best=None):
    t = 0.0
    out = [{"generation": 0, "time": t, "best_fitness": (best or [0.0])[0]}]
    for i, d in enumerate(durations, start=1):
        t += d
        fitness = best[i] if best else float(i)
        out.append({"generation": i, "time": t, "best_fitness": fitness})
    return out


class TestTimeRemaining:
    def test_estimating_before_three_generations(self):
        assert time_remaining(_progress([]), 100) is None
        assert time_remaining(_progress([1.0, 1.0]), 100) is None
        assert time_remaining(_progress([1.0, 1.0, 1.0]), 100) == pytest.approx(97.0)

    def test_uses_only_the_last_ten_durations(self):
        durations = [0.1] * 20 + [2.0] * 10
        remaining = time_remaining(_progress(durations), 100)
        # 30 generations bred, 70 left, each now taking 2 seconds.
        assert remaining == pytest.approx(140.0)

    def test_zero_when_nothing_is_left(self):
        assert time_remaining(_progress([1.0] * 5), 5) == 0.0


class TestStagnation:
    def _flat_after(self, improving, flat):
        best = [float(i) for i in range(improving)] + [float(improving - 1)] * flat
        return _progress([1.0] * (len(best) - 1), best)

    def test_fires_after_twenty_flat_generations_in_a_sixty_generation_run(self):
        assert stagnation(self._flat_after(10, 19), 60) is None
        assert stagnation(self._flat_after(10, 20), 60) == 20

    def test_quarter_rule_holds_it_back_in_a_long_run(self):
        assert stagnation(self._flat_after(10, 20), 200) is None
        assert stagnation(self._flat_after(10, 50), 200) == 50

    def test_never_fires_while_the_best_keeps_improving(self):
        best = [float(i) for i in range(80)]
        assert stagnation(_progress([1.0] * 79, best), 60) is None

    def test_empty_progress_is_not_stagnant(self):
        assert stagnation([], 60) is None

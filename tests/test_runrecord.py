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


class TestPidReuseDetection:
    """A pid alone can't tell generide's own run apart from an unrelated
    process that later reused the same number, especially right after a
    reboot when low pids are handed out again quickly. A start-time
    fingerprint, captured when the run is created, closes that gap."""

    def test_fingerprint_is_stable_for_a_live_process(self):
        first = runrecord._pid_fingerprint(os.getpid())
        second = runrecord._pid_fingerprint(os.getpid())
        assert first
        assert first == second

    def test_fingerprint_is_none_for_a_dead_or_bad_pid(self):
        assert runrecord._pid_fingerprint(_dead_pid()) is None
        assert runrecord._pid_fingerprint(0) is None
        assert runrecord._pid_fingerprint(-1) is None
        assert runrecord._pid_fingerprint("not a pid") is None

    def test_create_run_records_the_pid_fingerprint(self):
        run_id = _make()
        assert load_run(run_id).record["pid_started"]

    def test_a_reused_pid_is_detected_and_repaired_to_interrupted(self, monkeypatch):
        # Simulates a reboot: the process this run recorded has exited and
        # an unrelated one, still alive, was handed the same pid.
        run_id = _make()
        monkeypatch.setattr(runrecord, "_pid_fingerprint", lambda pid: "a-different-process")
        assert load_run(run_id).record["status"] == "interrupted"
        saved = json.loads((library_root() / run_id / "run.json").read_text())
        assert saved["status"] == "interrupted"

    def test_an_unverifiable_alive_pid_still_reads_as_running(self, monkeypatch):
        # No fingerprint captured, or `ps` unavailable now: falls back to
        # the plain liveness check, exactly as before fingerprinting existed.
        run_id = _make()
        monkeypatch.setattr(runrecord, "_pid_fingerprint", lambda pid: None)
        assert load_run(run_id).record["status"] == "running"

    def test_can_signal_requires_a_verified_match(self, monkeypatch):
        run_id = _make()
        assert runrecord.can_signal(load_run(run_id).record)

        run_id2 = _make()
        monkeypatch.setattr(runrecord, "_pid_fingerprint", lambda pid: None)
        assert not runrecord.can_signal(load_run(run_id2).record)

    def test_can_signal_is_false_for_a_finished_run(self):
        run_id = _make()
        finish_run(run_id, "completed", generations_run=1)
        assert not runrecord.can_signal(load_run(run_id).record)

    def test_signal_stop_sends_sigterm_to_a_verified_pid(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            run_id = _make(pid=child.pid)
            runrecord.signal_stop(run_id)
            assert child.wait(timeout=5) != 0
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

    def test_signal_stop_refuses_an_unverifiable_pid(self, monkeypatch):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            run_id = _make(pid=child.pid)
            monkeypatch.setattr(runrecord, "_pid_fingerprint", lambda pid: None)
            with pytest.raises(runrecord.CannotVerifyProcess):
                runrecord.signal_stop(run_id)
            assert child.poll() is None  # left alone, not signaled
        finally:
            child.kill()
            child.wait()

    def test_signal_stop_refuses_a_run_that_is_not_running(self):
        run_id = _make()
        finish_run(run_id, "completed", generations_run=1)
        with pytest.raises(runrecord.RunNotRunning):
            runrecord.signal_stop(run_id)

    def test_a_record_from_before_fingerprinting_still_repairs_by_liveness_alone(self):
        # A run.json saved by generide before this existed has no
        # "pid_started" key at all, not just an empty one.
        run_id = _make(pid=os.getpid())
        path = library_root() / run_id / "run.json"
        record = json.loads(path.read_text())
        del record["pid_started"]
        path.write_text(json.dumps(record))

        assert load_run(run_id).record["status"] == "running"
        assert not runrecord.can_signal(load_run(run_id).record)

        dead_run = _make(pid=_dead_pid())
        path = library_root() / dead_run / "run.json"
        record = json.loads(path.read_text())
        del record["pid_started"]
        path.write_text(json.dumps(record))
        assert load_run(dead_run).record["status"] == "interrupted"


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


class TestRunNames:
    def _at(self, minute, seed):
        return _make(seed=seed, pid=_dead_pid(), now=CLOCK.replace(minute=minute))

    def test_unnamed_runs_are_numbered_oldest_first(self):
        newest = self._at(30, 2)
        oldest = self._at(10, 1)
        names = runrecord.name_unnamed_runs()
        assert names[oldest] == "Mine Train 1"
        assert names[newest] == "Mine Train 2"

    def test_a_new_run_takes_the_lowest_free_number_and_names_stay_put(self):
        # The game does the same: delete Mine Train 1 and the next new ride
        # is Mine Train 1 again, while Mine Train 2 keeps its name.
        first, second = self._at(10, 1), self._at(20, 2)
        runrecord.name_unnamed_runs()
        delete_run(first)
        third = self._at(30, 3)
        names = runrecord.name_unnamed_runs()
        assert names[second] == "Mine Train 2"
        assert names[third] == "Mine Train 1"

    def test_a_run_installed_before_names_existed_keeps_its_install_name(self):
        run_id = self._at(10, 1)
        record_install(run_id, {"name": "Gold  Rush", "path": "/x.td6"})
        assert runrecord.name_unnamed_runs()[run_id] == "Gold Rush"

    def test_renaming_is_saved_beside_the_record_not_in_it(self):
        run_id = self._at(10, 1)
        load_run(run_id)  # marks the dead run interrupted, a write of its own
        before = (runrecord.run_dir(run_id) / runrecord.RUN_FILE).read_text()
        assert runrecord.set_run_name(run_id, "  Big   Thunder ") == "Big Thunder"
        assert runrecord.run_name(load_run(run_id).record) == "Big Thunder"
        assert (runrecord.run_dir(run_id) / runrecord.RUN_FILE).read_text() == before

    @pytest.mark.parametrize("bad", ["", "   ", None, 5, "x" * 61, "bell\x07"])
    def test_bad_names_are_refused(self, bad):
        run_id = self._at(10, 1)
        with pytest.raises(runrecord.InvalidRunName):
            runrecord.set_run_name(run_id, bad)

    def test_an_unnamed_run_falls_back_to_its_date_and_seed(self):
        run_id = self._at(10, 4)
        assert runrecord.run_name(load_run(run_id).record) == "2026-09-27 09:10, seed 4"


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


class TestSiteInTheSummary:
    """The result view says whether a ride fits its site, and where to put it."""

    def _ride(self):
        from rct2.generate import create_simple_circuit

        return create_simple_circuit()

    def _site(self, rows=None, anchor=(3, 4)):
        from rct2.site import Site

        return Site.from_rows(rows or ["." * 10] * 14, anchor=anchor)

    def test_a_ride_that_fits_says_so_and_where_to_place_it(self):
        summary = runrecord.ride_summary(self._ride(), site=self._site())

        site = summary["site"]
        assert site["fits"] is True
        assert (site["outside"], site["blocked"], site["below_ground"]) == (0, 0, 0)
        assert site["place_at"]["tile"] == [3, 4]
        assert site["place_at"]["heading"] == "north"
        assert "facing north" in site["place_at"]["text"]

    def test_the_verdict_names_what_it_did_not_check(self):
        site = runrecord.ride_summary(self._ride(), site=self._site())["site"]

        assert "station flatness" in site["not_checked"]
        assert "path connection" in site["not_checked"]
        assert "clearance above ground" in site["not_checked"]

    def test_a_ride_that_does_not_fit_has_counts_and_no_place_at(self):
        # Covers AE4: every tile blocked.
        site = runrecord.ride_summary(self._ride(), site=self._site(["#" * 10] * 14))["site"]

        assert site["fits"] is False
        assert site["blocked"] > 0
        assert site["place_at"] is None

    def test_the_heading_that_fits_is_reported(self):
        from rct2.geometry import Heading
        from rct2.site import site_coords

        ride = self._ride()
        needed = {site_coords((2, 6), Heading.EAST, x, y) for x in range(-1, 4) for y in range(-2, 8)}
        width = max(x for x, _ in needed) + 2
        depth = max(y for _, y in needed) + 2
        rows = ["".join("." if (x, y) in needed else "#" for x in range(width)) for y in range(depth)]

        site = runrecord.ride_summary(ride, site=self._site(rows, anchor=(2, 6)))["site"]

        assert site["fits"] is True
        assert site["place_at"]["heading"] == "east"

    def test_a_ride_bigger_than_the_old_rectangle_is_valid_when_it_fits_the_site(self):
        summary = runrecord.ride_summary(
            self._ride(), max_width=2, max_depth=2, site=self._site()
        )

        assert summary["valid"] is True

    def test_without_a_site_the_summary_has_no_site_entry(self):
        assert "site" not in runrecord.ride_summary(self._ride())


class TestStoringASite:
    def test_the_site_is_copied_into_the_run_and_the_request_points_at_the_copy(self, tmp_path):
        from rct2.site import Site

        site = Site.from_rows(["..", ".."], anchor=(0, 0))
        original = tmp_path / "mine.json"
        site.save(original)
        run_id = create_run(
            seed=1, request={"site": str(original)}, settings=[], generations=1, now=CLOCK
        )

        runrecord.save_site(run_id, site)

        record = load_run(run_id).record
        stored = runrecord.run_dir(run_id) / "site.json"
        assert record["request"]["site"] == str(stored)
        original.unlink()  # the copy survives the original going away
        assert runrecord.site_from_path(record["request"]["site"]) == site

    def test_a_missing_or_unreadable_site_is_none_not_an_error(self, tmp_path):
        assert runrecord.site_from_path(None) is None
        assert runrecord.site_from_path("") is None
        assert runrecord.site_from_path(str(tmp_path / "gone.json")) is None

"""Tests for OpenRCT2 locations, the headless check, and install."""

import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from rct2 import openrct2_paths, runrecord, td6
from rct2.openrct2_paths import (
    InstallConflict,
    InvalidName,
    apply_template,
    availability,
    check_message,
    install,
    load_ui_settings,
    run_check,
    sanitize_name,
    save_ui_settings,
)

CLOCK = datetime(2026, 9, 27, 14, 5, tzinfo=timezone.utc)
MANIC_MINER = "data/sample_rides/manic_miner_test.td6"


@pytest.fixture
def game(tmp_path, monkeypatch):
    """A fake OpenRCT2: a binary that exists and an empty track folder."""
    binary = tmp_path / "game" / "OpenRCT2"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n")
    tracks = tmp_path / "game" / "track"
    tracks.mkdir()
    monkeypatch.setenv("GENERIDE_OPENRCT2_BINARY", str(binary))
    monkeypatch.setenv("GENERIDE_TRACK_DIR", str(tracks))
    return SimpleNamespace(binary=binary, tracks=tracks)


@pytest.fixture
def finished_run():
    run_id = runrecord.create_run(seed=5, request={}, settings=[], generations=3)
    directory = runrecord.run_dir(run_id)
    (directory / runrecord.BEST_TD6).write_bytes(open(MANIC_MINER, "rb").read())
    runrecord.finish_run(run_id, "completed", generations_run=3)
    return run_id


class TestAvailability:
    def test_missing_game_makes_check_and_install_unavailable(self):
        """Covers AE1: the conftest points both paths at nothing."""
        state = availability()
        assert not state.check and not state.install
        assert "OpenRCT2" in state.check_reason
        assert "GENERIDE_OPENRCT2_BINARY" in state.check_reason
        assert "track folder" in state.install_reason

    def test_present_game_makes_both_available(self, game):
        state = availability()
        assert state.check and state.install
        assert state.check_reason == state.install_reason == ""
        assert state.track_dir == str(game.tracks)

    def test_default_track_folder_is_the_mac_one(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GENERIDE_TRACK_DIR")
        monkeypatch.setenv("HOME", str(tmp_path))
        assert openrct2_paths.track_dir() == (
            tmp_path / "Library" / "Application Support" / "OpenRCT2" / "track"
        )


class TestNames:
    def test_template_with_name_and_date(self):
        assert apply_template("{name} {date}", name="Canyon", seed=4, now=CLOCK) \
            == "Canyon 2026-09-27"

    def test_template_with_every_field(self):
        assert apply_template("{name} {date} {time} s{seed}", name="Canyon", seed=4,
                              now=CLOCK) == "Canyon 2026-09-27 14-05 s4"

    def test_unknown_template_field_is_refused(self):
        with pytest.raises(InvalidName, match="colour"):
            apply_template("{name} {colour}", name="x", seed=1, now=CLOCK)

    @pytest.mark.parametrize("raw", [
        "a/b", "../../etc/passwd", "line\nbreak", "tab\there", "back\\slash",
        "x" * 200, "  spaced  ", ".hidden", "colon:name",
    ])
    def test_names_come_out_filesystem_safe(self, raw):
        name = sanitize_name(raw)
        assert name
        assert len(name) <= 60
        assert not any(c in name for c in "/\\\n\t\r:")
        assert name == name.strip()
        assert not name.startswith(".")

    @pytest.mark.parametrize("raw", ["", "   ", "///", "..", "\n\n"])
    def test_names_with_nothing_left_are_refused(self, raw):
        with pytest.raises(InvalidName):
            sanitize_name(raw)


class TestInstall:
    def test_install_copies_the_exact_bytes_and_records_it(self, game, finished_run):
        entry = install(finished_run, "Canyon Run")
        dest = game.tracks / "Canyon Run.td6"
        assert dest.read_bytes() == (runrecord.run_dir(finished_run) / "best.td6").read_bytes()
        assert entry["name"] == "Canyon Run"
        assert entry["file"] == str(dest)
        installs = runrecord.load_run(finished_run).record["installs"]
        assert [i["name"] for i in installs] == ["Canyon Run"]

    def test_existing_name_is_a_conflict_unless_replacing(self, game, finished_run):
        """Covers AE5."""
        existing = game.tracks / "Canyon.td6"
        existing.write_bytes(b"someone else's ride")
        with pytest.raises(InstallConflict) as exc:
            install(finished_run, "Canyon")
        assert exc.value.name == "Canyon"
        assert existing.read_bytes() == b"someone else's ride"
        assert runrecord.load_run(finished_run).record["installs"] == []

        entry = install(finished_run, "Canyon", replace=True)
        assert existing.read_bytes() != b"someone else's ride"
        assert entry["replaced"] is True

    def test_install_is_refused_when_the_game_is_missing(self, finished_run):
        with pytest.raises(openrct2_paths.GameUnavailable):
            install(finished_run, "Canyon")

    def test_install_needs_an_exported_ride(self, game):
        run_id = runrecord.create_run(seed=1, request={}, settings=[], generations=1)
        runrecord.finish_run(run_id, "failed", generations_run=1)
        with pytest.raises(FileNotFoundError):
            install(run_id, "Nothing")


def _fake_scorer(result, calls=None, delay=0.0):
    def scorer(segments, **kwargs):
        if calls is not None:
            calls.append(("start", time.monotonic()))
        time.sleep(delay)
        if calls is not None:
            calls.append(("end", time.monotonic()))
        return result
    return scorer


def _oracle_result(**kw):
    base = dict(excitement=None, intensity=None, nausea=None, status="rated", detail="",
                stalled_at_index=None, stalled_at_type=None, measurements=None)
    base.update(kw)
    return SimpleNamespace(**base)


class TestCheck:
    def test_a_stall_is_recorded_and_named_in_plain_language(self, game, finished_run):
        result = _oracle_result(status="stalled", stalled_at_index=42, stalled_at_type=12)
        check = run_check(finished_run, scorer=_fake_scorer(result))

        assert check["status"] == "stalled"
        assert check["stalled_at_index"] == 42
        assert "piece 43" in check["message"]
        rec = runrecord.load_run(finished_run).record
        assert rec["checks"][-1]["status"] == "stalled"
        assert rec["check_status"] is None

    def test_a_rated_check_records_the_game_ratings(self, game, finished_run):
        result = _oracle_result(status="rated", excitement=5.21, intensity=6.97, nausea=4.31)
        check = run_check(finished_run, scorer=_fake_scorer(result))
        assert (check["excitement"], check["intensity"], check["nausea"]) == (5.21, 6.97, 4.31)
        assert "game" in check["message"].lower()

    def test_the_check_builds_the_exported_ride_with_its_lift(self, game, finished_run):
        seen = {}

        def scorer(segments, **kwargs):
            seen["segments"] = segments
            seen["lift_indices"] = kwargs.get("lift_indices")
            return _oracle_result()

        run_check(finished_run, scorer=scorer)
        ride = td6.load(MANIC_MINER)
        assert seen["segments"] == [e.segment_type for e in ride.elements]
        assert seen["lift_indices"] == {i for i, e in enumerate(ride.elements) if e.chain_lift}

    def test_a_scorer_that_raises_becomes_a_recorded_failure(self, game, finished_run):
        def scorer(segments, **kwargs):
            raise OSError("game crashed")

        check = run_check(finished_run, scorer=scorer)
        assert check["status"] == "oracle_error"
        assert "game crashed" in check["detail"]
        assert runrecord.load_run(finished_run).record["check_status"] is None

    def test_two_checks_never_overlap(self, game, finished_run):
        calls = []
        scorer = _fake_scorer(_oracle_result(), calls=calls, delay=0.05)
        threads = [threading.Thread(target=run_check, args=(finished_run,),
                                    kwargs={"scorer": scorer}) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert [kind for kind, _ in calls] == ["start", "end", "start", "end"]
        assert calls[2][1] >= calls[1][1]
        assert len(runrecord.load_run(finished_run).record["checks"]) == 2

    @pytest.mark.parametrize("status,words", [
        ("timeout", "time"),
        ("placement_failed", "build"),
        ("oracle_error", "could not"),
    ])
    def test_every_failure_has_a_plain_message(self, status, words):
        message = check_message({"status": status, "detail": "piece_20_type_12"})
        assert words in message.lower()


class TestUiSettings:
    def test_defaults_when_nothing_is_saved(self):
        data = load_ui_settings()
        assert data["name_templates"]
        assert all("{name}" in t for t in data["name_templates"])

    def test_saved_templates_live_under_generide_home(self, isolated_generide_home):
        save_ui_settings({"name_templates": ["{name} {date}", "{name} seed {seed}"]})
        assert (isolated_generide_home / "settings.json").exists()
        assert load_ui_settings()["name_templates"] == ["{name} {date}", "{name} seed {seed}"]

    def test_a_bad_template_is_not_saved(self):
        with pytest.raises(InvalidName):
            save_ui_settings({"name_templates": ["{name} {oops}"]})

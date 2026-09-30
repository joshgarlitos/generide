"""Tests for the web UI's server and JSON API."""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from rct2 import runrecord, settings, td6
from rct2.webui import App, Request, make_server

REPO = Path(__file__).resolve().parent.parent
MANIC_MINER = REPO / "data" / "sample_rides" / "manic_miner_test.td6"
PORT = 8765
# The station powers the first pieces; on 30 flat pieces after it the train
# runs out of speed and stops.
STALLS = [0x02, 0x01] + [0x00] * 30
HOST = f"127.0.0.1:{PORT}"

# Stands in for evolve_coaster.py: writes a run record under the id it is
# given, logs a generation every 20ms, and on SIGTERM finishes as stopped,
# the way the real CLI does.
FAKE_CHILD = r"""
import argparse, signal, sys, time
from rct2 import runrecord
p = argparse.ArgumentParser()
p.add_argument("--run-id"); p.add_argument("--rng-seed", type=int)
p.add_argument("--parent-run"); p.add_argument("--generations", type=int, default=100)
p.add_argument("--oracle-calibrate", action="store_true")
a, _ = p.parse_known_args()
stop = []
signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
runrecord.create_run(run_id=a.run_id, seed=a.rng_seed, settings=sys.argv[1:],
                     request={"seed": a.rng_seed, "oracle_calibrate": a.oracle_calibrate},
                     generations=a.generations, parent=a.parent_run)
gen = 0
while not stop and gen < 5000:
    runrecord.append_progress(a.run_id, {"generation": gen, "time": time.time(),
                                         "best_fitness": 1.0})
    gen += 1
    time.sleep(0.02)
runrecord.finish_run(a.run_id, "stopped", generations_run=gen)
"""
FAKE_COMMAND = (sys.executable, "-c", FAKE_CHILD)


@pytest.fixture(autouse=True)
def importable_children(monkeypatch):
    # Children run with the run directory as their working directory, so the
    # fake one needs the repo on its path to import rct2.
    monkeypatch.setenv("PYTHONPATH", str(REPO))


@pytest.fixture
def app():
    made = App(port=PORT, command=FAKE_COMMAND)
    yield made
    for child in list(made.supervisor._children.values()):
        if child.poll() is None:
            child.kill()
            child.wait()


def call(app, method, path, body=None, headers=None):
    hdrs = {"Host": HOST}
    if method in ("POST", "DELETE"):
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    raw = b"" if body is None else json.dumps(body).encode()
    return app.dispatch(Request(method=method, path=path, headers=hdrs, body=raw))


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def _dead_pid():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def saved_run(seed=5, segments=None, status="completed", with_ride=True, **request):
    """A finished run in the library, as the CLI would leave it."""
    ride = td6.load(MANIC_MINER)
    segments = segments or [e.segment_type for e in ride.elements]
    values = settings.validate(dict({"seed": seed}, **request)).values
    run_id = runrecord.create_run(
        seed=seed, request=values, settings=settings.cli_args(values),
        generations=values["generations"], pid=_dead_pid(),
    )
    t = time.time()
    for gen in range(4):
        runrecord.append_progress(run_id, {"generation": gen, "time": t + gen,
                                           "best_fitness": float(gen)})
    runrecord.append_improvement(run_id, {"generation": 3, "time": t, "fitness": 3.0,
                                          "segments": segments})
    summary = runrecord.ride_summary(segments, values["max_width"], values["max_depth"])
    summary.update(fitness=3.0, stopped_early=False, exported=with_ride)
    if with_ride:
        (runrecord.run_dir(run_id) / "best.td6").write_bytes(MANIC_MINER.read_bytes())
    runrecord.finish_run(run_id, status, generations_run=4, result=summary)
    return run_id


@pytest.fixture
def game(tmp_path, monkeypatch):
    binary = tmp_path / "game" / "OpenRCT2"
    binary.parent.mkdir()
    binary.write_text("")
    tracks = tmp_path / "game" / "track"
    tracks.mkdir()
    monkeypatch.setenv("GENERIDE_OPENRCT2_BINARY", str(binary))
    monkeypatch.setenv("GENERIDE_TRACK_DIR", str(tracks))
    return SimpleNamespace(binary=binary, tracks=tracks)


class TestStartAndStop:
    def test_start_then_a_second_start_is_refused_naming_the_active_run(self, app):
        """Covers AE2."""
        first = call(app, "POST", "/api/runs", {"values": {"seed": 3}})
        assert first.status == 201
        run_id = first.json()["id"]

        active = call(app, "GET", "/api/active").json()["active"]
        assert active["id"] == run_id
        assert active["status"] == "running"
        assert active["stoppable"] is True

        second = call(app, "POST", "/api/runs", {"values": {"seed": 4}})
        assert second.status == 409
        assert second.json()["active"] == run_id
        assert len(runrecord.list_runs()) == 1

    def test_stop_ends_the_run_as_stopped(self, app):
        run_id = call(app, "POST", "/api/runs", {"values": {"seed": 3}}).json()["id"]
        wait_for(lambda: runrecord.load_run(run_id).progress)
        assert call(app, "POST", f"/api/runs/{run_id}/stop").status == 202
        wait_for(lambda: runrecord.load_record(run_id)["status"] == "stopped")
        assert call(app, "GET", "/api/active").json()["active"] is None

    def test_the_child_runs_in_its_own_session(self, monkeypatch):
        seen = {}

        def popen(*args, **kwargs):
            seen.update(kwargs)
            child = subprocess.Popen(*args, **kwargs)
            seen["child"] = child
            return child

        made = App(port=PORT, command=FAKE_COMMAND, popen=popen)
        try:
            call(made, "POST", "/api/runs", {"values": {"seed": 3}})
            assert seen["start_new_session"] is True
            assert os.getsid(seen["child"].pid) != os.getsid(0)
        finally:
            seen["child"].kill()
            seen["child"].wait()

    def test_the_run_is_started_with_the_validated_settings_and_ids(self, app):
        parent = saved_run(seed=9)
        run_id = call(app, "POST", "/api/runs", {
            "values": {"seed": 9, "generations": 12, "target_intensity": {"min": 2, "max": 5}},
            "parent": parent,
        }).json()["id"]
        rec = runrecord.load_record(run_id)
        args = rec["settings"]
        assert args[args.index("--run-id") + 1] == run_id
        assert args[args.index("--parent-run") + 1] == parent
        assert args[args.index("--generations") + 1] == "12"
        assert args[args.index("--target-intensity") + 1] == "2:5"
        assert args[args.index("--fitness") + 1] == "physics"
        output = Path(args[args.index("--output") + 1])
        assert output.parent == runrecord.run_dir(run_id)
        assert rec["parent"] == parent

    def test_a_blank_seed_is_picked_before_starting(self, app):
        run_id = call(app, "POST", "/api/runs", {"values": {}}).json()["id"]
        rec = runrecord.load_record(run_id)
        assert isinstance(rec["seed"], int)
        assert run_id.endswith(f"-s{rec['seed']}")

    def test_invalid_values_start_nothing(self, monkeypatch):
        launched = []
        made = App(port=PORT, popen=lambda *a, **k: launched.append(a))
        response = call(made, "POST", "/api/runs", {
            "values": {"target_excitement": {"min": 7, "max": 5}, "generations": 0},
        })
        assert response.status == 400
        assert set(response.json()["errors"]) == {"target_excitement", "generations"}
        assert launched == []
        assert runrecord.list_runs() == []

    def test_a_child_that_dies_before_writing_its_record_is_reported(self):
        made = App(port=PORT, command=(sys.executable, "-c",
                                       "import sys; print('boom'); sys.exit(2)"))
        response = call(made, "POST", "/api/runs", {"values": {"seed": 1}})
        assert response.status == 500
        assert "boom" in response.json()["console"]
        assert not any(runrecord.library_root().iterdir())

    def test_a_run_started_elsewhere_cannot_be_stopped_from_the_page(self, app):
        run_id = runrecord.create_run(seed=1, request={}, settings=[], generations=5)
        response = call(app, "POST", f"/api/runs/{run_id}/stop")
        assert response.status == 409
        assert "terminal" in response.json()["error"]


class TestStatus:
    def test_active_run_reports_generation_remaining_and_stagnation(self, app):
        run_id = runrecord.create_run(seed=1, request={}, settings=[], generations=60)
        t = 1000.0
        for gen in range(31):
            best = float(min(gen, 10))  # stops improving at generation 10
            runrecord.append_progress(run_id, {"generation": gen, "time": t + gen * 2.0,
                                               "best_fitness": best})
        live = call(app, "GET", "/api/active").json()["active"]["live"]
        assert live["generation"] == 30
        assert live["generations_planned"] == 60
        assert live["remaining"] == pytest.approx(60.0)  # 30 left at 2s each
        assert live["stagnant_for"] == 20
        assert live["estimating"] is False

    def test_a_new_run_is_estimating(self, app):
        runrecord.create_run(seed=1, request={}, settings=[], generations=60)
        live = call(app, "GET", "/api/active").json()["active"]["live"]
        assert live["remaining"] is None and live["estimating"] is True

    def test_run_detail_labels_estimates_and_flags_problems(self, app):
        run_id = saved_run(seed=2, segments=STALLS, status="failed", with_ride=False)
        run = call(app, "GET", f"/api/runs/{run_id}").json()["run"]
        assert set(run["best"]["estimated"]) == {"excitement", "intensity", "nausea"}
        assert "excitement" in run["headline"] and "game_excitement" in run["headline"]
        assert run["headline"]["game_excitement"] is None
        assert run["warnings"]
        assert run["has_ride"] is False

    def test_library_lists_runs_newest_first_with_headlines(self, app):
        older = saved_run(seed=1)
        newer = saved_run(seed=2)
        runs = call(app, "GET", "/api/runs").json()["runs"]
        assert [r["id"] for r in runs] == [newer, older]
        assert runs[0]["headline"]["excitement"] is not None
        assert runs[0]["inputs"]["fitness"] == "physics"
        assert runs[0]["installed"] == []

    def test_rerun_values_carry_every_input_and_the_seed(self, app):
        """Covers AE6."""
        source = saved_run(seed=77, target_intensity={"min": 3, "max": 6}, generations=40)
        rerun = call(app, "GET", f"/api/runs/{source}/rerun").json()
        assert rerun["parent"] == source
        assert rerun["values"]["seed"] == 77
        assert rerun["values"]["generations"] == 40
        assert rerun["values"]["target_intensity"] == {"min": 3.0, "max": 6.0}


class TestCompare:
    def test_only_the_changed_inputs_are_marked(self, app):
        a = saved_run(seed=5, target_intensity={"min": 3, "max": 6})
        b = saved_run(seed=6, target_intensity={"min": 4, "max": 7})
        data = call(app, "GET", f"/api/compare?ids={a},{b}").json()
        changed = {row["key"] for row in data["inputs"] if row["changed"]}
        assert changed == {"target_intensity", "seed"}
        excitement = next(r for r in data["stats"] if r["key"] == "excitement")
        assert excitement["deltas"][0] == 0
        assert excitement["deltas"][1] == pytest.approx(0.0)  # same ride saved for both
        assert [r["id"] for r in data["runs"]] == [a, b]

    @pytest.mark.parametrize("count", [1, 4])
    def test_one_or_four_runs_are_refused(self, app, count):
        ids = ",".join(saved_run(seed=i) for i in range(count))
        assert call(app, "GET", f"/api/compare?ids={ids}").status == 400


class TestIds:
    @pytest.mark.parametrize("path", [
        "/api/runs/..", "/api/runs/..%2F..%2Fetc", "/api/runs/abc",
        "/api/runs/20260927T093612Z-s1%2F..", "/api/runs/20260927T093612Z-s1.json",
    ])
    def test_malformed_ids_are_not_found_without_touching_files(self, app, path, monkeypatch):
        touched = []
        monkeypatch.setattr(runrecord, "library_root", lambda: touched.append(1))
        response = call(app, "GET", path)
        assert response.status == 404
        assert touched == []

    def test_an_unknown_but_well_formed_id_is_not_found(self, app):
        assert call(app, "GET", "/api/runs/20260101T000000Z-s1").status == 404
        assert call(app, "DELETE", "/api/runs/20260101T000000Z-s1").status == 404


class TestRequestGuards:
    @pytest.mark.parametrize("host", ["evil.example:8765", "127.0.0.1:9999", "", "0.0.0.0:8765"])
    def test_a_foreign_host_is_refused(self, app, host):
        response = call(app, "GET", "/api/runs", headers={"Host": host})
        assert response.status == 403

    def test_localhost_is_accepted(self, app):
        assert call(app, "GET", "/api/runs", headers={"Host": f"localhost:{PORT}"}).status == 200

    @pytest.mark.parametrize("headers", [
        {"Origin": "https://evil.example"},
        {"Origin": "http://127.0.0.1:9999"},
        {"Content-Type": "text/plain"},
        {"Content-Type": "application/x-www-form-urlencoded"},
    ])
    def test_foreign_origin_or_non_json_changes_nothing(self, app, game, headers):
        running = runrecord.create_run(seed=1, request={}, settings=[], generations=5)
        done = saved_run(seed=2)
        attempts = [
            ("POST", "/api/runs", {"values": {"seed": 3}}),
            ("POST", f"/api/runs/{running}/stop", {}),
            ("POST", f"/api/runs/{done}/install", {"name": "Evil"}),
            ("POST", f"/api/runs/{done}/check", {}),
            ("DELETE", f"/api/runs/{done}", {}),
            ("POST", "/api/ui-settings", {"name_templates": ["{name}"]}),
        ]
        for method, path, body in attempts:
            assert call(app, method, path, body, headers=headers).status == 403, path
        assert {r["id"] for r in runrecord.list_runs()} == {running, done}
        assert runrecord.load_record(done)["installs"] == []
        assert runrecord.load_record(done)["check_status"] is None
        assert list(game.tracks.iterdir()) == []
        assert app.supervisor._children == {}

    def test_responses_carry_security_headers(self, app):
        response = call(app, "GET", "/")
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "script-src 'self'" in response.headers["Content-Security-Policy"]

    def test_serves_every_file_the_page_links(self, app):
        # The page links tokens.css (the design system) and then style.css.
        # A file the server doesn't serve fails silently in the browser and
        # leaves the page unstyled, so check each link resolves.
        page = call(app, "GET", "/").body.decode()
        linked = re.findall(r'(?:href|src)="(/[^"#]+\.(?:css|js))"', page)
        assert "/tokens.css" in linked and "/style.css" in linked
        for path in linked:
            response = call(app, "GET", path)
            assert response.status == 200, path
            assert response.body, path


class TestPicturesAndDownload:
    @pytest.mark.parametrize("kind", ["plan", "profile", "fitness"])
    def test_svg_endpoints_return_svg(self, app, kind):
        run_id = saved_run()
        response = call(app, "GET", f"/api/runs/{run_id}/{kind}.svg")
        assert response.status == 200
        assert response.content_type.startswith("image/svg+xml")
        assert response.body.startswith(b"<svg")

    def test_download_returns_the_td6_bytes(self, app):
        run_id = saved_run()
        response = call(app, "GET", f"/api/runs/{run_id}/download")
        assert response.status == 200
        assert response.body == MANIC_MINER.read_bytes()
        assert response.headers["Content-Disposition"].startswith("attachment;")
        assert response.headers["Content-Disposition"].endswith('.td6"')

    def test_download_of_a_run_without_a_ride_is_not_found(self, app):
        run_id = saved_run(with_ride=False, status="failed")
        assert call(app, "GET", f"/api/runs/{run_id}/download").status == 404


class TestCheck:
    def test_unavailable_game_refuses_the_check_with_the_reason(self, app):
        """Covers AE1: download still works while check and install do not."""
        run_id = saved_run()
        response = call(app, "POST", f"/api/runs/{run_id}/check", {})
        assert response.status == 409
        assert "OpenRCT2" in response.json()["error"]
        availability = call(app, "GET", f"/api/runs/{run_id}").json()["run"]["availability"]
        assert availability["check"] is False and availability["install"] is False
        assert call(app, "GET", f"/api/runs/{run_id}/download").status == 200

    def test_while_a_check_runs_it_reads_checking_and_a_second_is_refused(self, game):
        release = threading.Event()

        def scorer(segments, **kwargs):
            release.wait(5)
            return SimpleNamespace(status="rated", excitement=5.0, intensity=4.0, nausea=3.0,
                                   detail="", stalled_at_index=None, stalled_at_type=None,
                                   measurements=None)

        made = App(port=PORT, command=FAKE_COMMAND, check_scorer=scorer)
        run_id = saved_run()
        assert call(made, "POST", f"/api/runs/{run_id}/check", {}).status == 202
        assert call(made, "GET", f"/api/runs/{run_id}").json()["run"]["checking"] is True
        assert call(made, "POST", f"/api/runs/{run_id}/check", {}).status == 409

        release.set()
        wait_for(lambda: runrecord.load_record(run_id)["checks"])
        run = call(made, "GET", f"/api/runs/{run_id}").json()["run"]
        assert run["checking"] is False
        assert run["headline"]["game_excitement"] == 5.0
        assert run["checks"][-1]["message"]

    def test_check_is_refused_while_a_calibrating_run_is_going(self, app, game):
        done = saved_run()
        runrecord.create_run(seed=1, request={"oracle_calibrate": True}, settings=[],
                             generations=5)
        response = call(app, "POST", f"/api/runs/{done}/check", {})
        assert response.status == 409
        assert "calibrat" in response.json()["error"]
        assert runrecord.load_record(done)["check_status"] is None

    def test_a_check_left_over_from_a_previous_server_is_cleared(self):
        run_id = saved_run()
        runrecord.set_check_status(run_id, "checking")
        App(port=PORT)
        assert runrecord.load_record(run_id)["check_status"] is None


class TestInstall:
    def test_install_with_a_template(self, app, game):
        run_id = saved_run(seed=31)
        response = call(app, "POST", f"/api/runs/{run_id}/install",
                        {"name": "Canyon", "template": "{name} seed {seed}"})
        assert response.status == 200
        assert (game.tracks / "Canyon seed 31.td6").read_bytes() == MANIC_MINER.read_bytes()
        assert "restart" in response.json()["restart_note"]
        listed = call(app, "GET", "/api/runs").json()["runs"][0]
        assert listed["installed"] == ["Canyon seed 31"]
        assert listed["name"] == "Canyon seed 31"

    def test_existing_name_asks_before_replacing(self, app, game):
        """Covers AE5."""
        (game.tracks / "Canyon.td6").write_bytes(b"theirs")
        run_id = saved_run()
        preview = call(app, "GET", f"/api/runs/{run_id}/name?name=Canyon").json()
        assert preview == {"name": "Canyon", "exists": True}
        response = call(app, "POST", f"/api/runs/{run_id}/install", {"name": "Canyon"})
        assert response.status == 409
        assert response.json()["conflict"] is True
        assert (game.tracks / "Canyon.td6").read_bytes() == b"theirs"
        response = call(app, "POST", f"/api/runs/{run_id}/install",
                        {"name": "Canyon", "replace": True})
        assert response.status == 200
        assert (game.tracks / "Canyon.td6").read_bytes() == MANIC_MINER.read_bytes()

    def test_a_ride_that_does_not_complete_needs_confirmation(self, app, game):
        """Covers AE7."""
        run_id = saved_run(segments=STALLS)
        response = call(app, "POST", f"/api/runs/{run_id}/install", {"name": "Stub"})
        assert response.status == 409
        body = response.json()
        assert body["needs_confirmation"] is True
        assert any("does not complete the circuit" in w for w in body["warnings"])
        assert list(game.tracks.iterdir()) == []
        response = call(app, "POST", f"/api/runs/{run_id}/install",
                        {"name": "Stub", "confirm": True})
        assert response.status == 200

    def test_bad_name_is_a_field_error(self, app, game):
        run_id = saved_run()
        response = call(app, "POST", f"/api/runs/{run_id}/install", {"name": "///"})
        assert response.status == 400
        assert response.json()["field"] == "name"

    def test_install_without_the_game_says_why(self, app):
        run_id = saved_run()
        response = call(app, "POST", f"/api/runs/{run_id}/install", {"name": "Canyon"})
        assert response.status == 409
        assert "track folder" in response.json()["error"]

    def test_templates_are_saved(self, app):
        response = call(app, "POST", "/api/ui-settings", {"name_templates": ["{name} {date}"]})
        assert response.status == 200
        ui = call(app, "GET", "/api/settings").json()["ui"]
        assert ui["name_templates"] == ["{name} {date}"]
        assert call(app, "POST", "/api/ui-settings",
                    {"name_templates": ["{nope}"]}).status == 400


class TestDelete:
    def test_delete_removes_the_run_but_not_the_installed_design(self, app, game):
        """Covers AE9."""
        run_id = saved_run()
        call(app, "POST", f"/api/runs/{run_id}/install", {"name": "Keeper"})
        assert call(app, "DELETE", f"/api/runs/{run_id}", {}).status == 200
        assert call(app, "GET", "/api/runs").json()["runs"] == []
        assert (game.tracks / "Keeper.td6").exists()

    def test_an_active_run_cannot_be_deleted(self, app):
        run_id = runrecord.create_run(seed=1, request={}, settings=[], generations=5)
        assert call(app, "DELETE", f"/api/runs/{run_id}", {}).status == 409
        assert runrecord.run_dir(run_id).exists()


class TestSettingsEndpoint:
    def test_settings_come_with_availability_and_the_estimate_note(self, app):
        data = call(app, "GET", "/api/settings").json()
        assert {s["key"] for s in data["settings"]} == {s.key for s in settings.SETTINGS}
        assert "estimate" in data["estimate_note"]
        assert data["availability"]["check"] is False

    def test_validate_reports_field_errors(self, app):
        data = call(app, "POST", "/api/validate",
                    {"values": {"target_excitement": {"min": 7, "max": 5}}}).json()
        assert data["ok"] is False and "target_excitement" in data["errors"]


class TestRealServer:
    def test_serves_the_page_and_settings_over_http(self):
        server, app = make_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{app.port}"
            with urllib.request.urlopen(base + "/") as page:
                assert page.status == 200
                assert b"<!doctype html>" in page.read().lower()
            with urllib.request.urlopen(base + "/api/settings") as resp:
                assert json.loads(resp.read())["settings"]
            post = urllib.request.Request(base + "/api/validate", data=b"{}", method="POST",
                                          headers={"Content-Type": "text/plain"})
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(post)
            assert exc.value.code == 403
        finally:
            server.shutdown()
            server.server_close()

    def test_a_real_short_cli_run_completes_and_writes_only_to_the_library(
        self, tmp_path, monkeypatch, isolated_generide_home,
    ):
        """Covers AE8 end to end, through the API and the real CLI."""
        cwd = tmp_path / "server-cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        made = App(port=PORT)
        response = call(made, "POST", "/api/runs", {"values": {
            "seed": 21, "generations": 4, "population": 8,
        }})
        assert response.status == 201, response.json()
        run_id = response.json()["id"]
        wait_for(lambda: runrecord.load_record(run_id)["status"] != "running", timeout=60)

        record = runrecord.load_record(run_id)
        assert record["status"] == "completed", (
            runrecord.run_dir(run_id) / "console.log").read_text()
        assert [r["id"] for r in call(made, "GET", "/api/runs").json()["runs"]] == [run_id]
        assert list(cwd.iterdir()) == []
        outside = [p for p in tmp_path.iterdir()
                   if p.name not in ("server-cwd", isolated_generide_home.name, "no-openrct2")]
        assert outside == []
        assert (runrecord.run_dir(run_id) / "best.td6").exists()


class TestDisplay:
    def test_result_numbers_keep_estimates_and_game_apart(self, app, game):
        def scorer(segments, **kwargs):
            return SimpleNamespace(status="rated", excitement=4.5, intensity=6.0, nausea=3.25,
                                   detail="", stalled_at_index=None, stalled_at_type=None,
                                   measurements=None)

        made = App(port=PORT, command=FAKE_COMMAND, check_scorer=scorer)
        run_id = saved_run()
        view = call(made, "GET", f"/api/runs/{run_id}").json()["run"]["stats_view"]
        assert [r["game"] for r in view["ratings"]] == [None, None, None]
        assert all(r["estimate"] for r in view["ratings"])
        labels = [r["label"] for r in view["simulated"]]
        assert "Top speed" in labels and "Completes the circuit" in labels
        assert next(r for r in view["simulated"] if r["label"] == "Top speed")["value"].endswith("mph")

        call(made, "POST", f"/api/runs/{run_id}/check", {})
        wait_for(lambda: runrecord.load_record(run_id)["checks"])
        view = call(made, "GET", f"/api/runs/{run_id}").json()["run"]["stats_view"]
        assert [r["game"] for r in view["ratings"]] == ["4.50", "6.00", "3.25"]

    def test_a_stalling_ride_says_where(self, app):
        run_id = saved_run(segments=STALLS)
        view = call(app, "GET", f"/api/runs/{run_id}").json()["run"]["stats_view"]
        circuit = next(r for r in view["simulated"] if r["label"] == "Completes the circuit")
        assert circuit["value"].startswith("No, it stalls on piece")

    def test_compare_formats_values_and_signed_deltas(self, app):
        a = saved_run(seed=5, target_intensity={"min": 3, "max": 6})
        b = saved_run(seed=6, target_intensity={"min": 4, "max": 7},
                      segments=STALLS)
        data = call(app, "GET", f"/api/compare?ids={a},{b}").json()
        window = next(r for r in data["inputs"] if r["key"] == "target_intensity")
        assert window["display"] == ["3 to 6", "4 to 7"]
        pieces = next(r for r in data["stats"] if r["key"] == "segments")
        assert pieces["delta_display"][0] == ""
        assert pieces["delta_display"][1].startswith("-")
        assert pieces["changed"] is True


class TestRobustness:
    def test_check_and_install_wait_until_the_run_finishes(self, app, game):
        run_id = runrecord.create_run(seed=1, request={}, settings=[], generations=5)
        (runrecord.run_dir(run_id) / "best.td6").write_bytes(MANIC_MINER.read_bytes())
        for action, body in (("check", {}), ("install", {"name": "Early"})):
            response = call(app, "POST", f"/api/runs/{run_id}/{action}", body)
            assert response.status == 409, action
            assert "still going" in response.json()["error"]
        assert list(game.tracks.iterdir()) == []
        assert runrecord.load_record(run_id)["check_status"] is None

    def test_an_unexpected_error_is_a_json_500(self, app, monkeypatch):
        def boom():
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(app, "list_runs", boom)
        response = call(app, "GET", "/api/runs")
        assert response.status == 500
        assert "disk on fire" in response.json()["error"]

    @pytest.mark.parametrize("length", ["-5", "lots"])
    def test_a_malformed_content_length_is_a_400(self, length):
        import http.client

        server, made = make_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", made.port, timeout=5)
            conn.putrequest("POST", "/api/validate", skip_accept_encoding=True)
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", length)
            conn.endheaders()
            assert conn.getresponse().status == 400
        finally:
            server.shutdown()
            server.server_close()

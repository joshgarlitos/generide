"""Tests for the evolve_coaster.py CLI's oracle-calibration flags.

These tests never run real evolution or the real oracle: `main()`'s
`evolve`/`evolve_parts` call is monkeypatched to a fake that captures the
kwargs it was given and returns a stand-in EvolutionStats, so the tests
exercise only the CLI's own argument parsing, validation, and wiring,
not the GA loop or the oracle itself (already covered in test_evolution.py).
"""

import sys

import pytest

import evolve_coaster
from rct2.calibration_log import CalibrationRecord
from rct2.evolution import EvolutionStats, Individual
from rct2.generate import create_hill_circuit


def _fake_run(captured: dict):
    """Return a fake evolve_parts()/evolve() that records its kwargs."""

    def run(**kwargs):
        captured.update(kwargs)
        return EvolutionStats(
            generations=kwargs.get("generations", 1),
            best_fitness=1.0,
            best_individual=Individual(segments=create_hill_circuit(), fitness=1.0),
            fitness_history=[1.0],
            valid_ratio_history=[1.0],
        )

    return run


def _run_cli(monkeypatch, tmp_path, extra_args, patch_evolve_parts=True, patch_evolve=True):
    captured = {}
    if patch_evolve_parts:
        monkeypatch.setattr(evolve_coaster, "evolve_parts", _fake_run(captured))
    if patch_evolve:
        monkeypatch.setattr(evolve_coaster, "evolve", _fake_run(captured))

    output_path = tmp_path / "out.td6"
    argv = [
        "evolve_coaster.py",
        "--output", str(output_path),
        "--generations", "3",
        "--population", "5",
        *extra_args,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    evolve_coaster.main()
    return captured, output_path


class TestOracleCalibrateFlag:
    def test_disabled_by_default_does_not_touch_oracle_kwargs(self, monkeypatch, tmp_path, capsys):
        captured, output_path = _run_cli(monkeypatch, tmp_path, ["--genome", "parts"])

        assert "oracle_interval" not in captured
        assert "oracle_log_writer" not in captured
        assert output_path.exists()
        assert "Oracle calibration enabled" not in capsys.readouterr().out

    def test_enabling_calibration_threads_flags_through_to_evolve_parts(
        self, monkeypatch, tmp_path,
    ):
        captured, _ = _run_cli(
            monkeypatch, tmp_path,
            ["--genome", "parts", "--oracle-calibrate",
             "--oracle-interval", "2", "--oracle-max-calls", "5"],
        )

        assert captured["oracle_interval"] == 2
        assert captured["oracle_max_calls"] == 5
        assert callable(captured["oracle_log_writer"])

    def test_genome_pieces_with_oracle_calibrate_is_a_hard_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", [
            "evolve_coaster.py",
            "--output", str(tmp_path / "out.td6"),
            "--genome", "pieces",
            "--oracle-calibrate",
        ])
        with pytest.raises(SystemExit):
            evolve_coaster.main()

    def test_oracle_interval_below_one_is_a_hard_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", [
            "evolve_coaster.py",
            "--output", str(tmp_path / "out.td6"),
            "--genome", "parts",
            "--oracle-calibrate",
            "--oracle-interval", "0",
        ])
        with pytest.raises(SystemExit):
            evolve_coaster.main()

    def test_oracle_max_calls_below_one_is_a_hard_error(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "argv", [
            "evolve_coaster.py",
            "--output", str(tmp_path / "out.td6"),
            "--genome", "parts",
            "--oracle-calibrate",
            "--oracle-max-calls", "0",
        ])
        with pytest.raises(SystemExit):
            evolve_coaster.main()

    def test_oracle_log_defaults_off_output_path(self, monkeypatch, tmp_path):
        output_path = tmp_path / "out.td6"
        captured, _ = _run_cli(
            monkeypatch, tmp_path, ["--genome", "parts", "--oracle-calibrate"],
        )

        expected_log_path = output_path.with_suffix(".oracle-log.jsonl")
        # The default is computed from args.output inside main(); confirm the
        # log_writer closure actually points at it by writing through it.
        record = CalibrationRecord.oracle_error(
            role="best", generation=0, rng_seed=1, segments=[], error=RuntimeError("x"),
        )
        captured["oracle_log_writer"](record)
        assert expected_log_path.exists()

    def test_upfront_estimate_line_prints_when_calibration_enabled(
        self, monkeypatch, tmp_path, capsys,
    ):
        _run_cli(
            monkeypatch, tmp_path,
            ["--genome", "parts", "--oracle-calibrate", "--oracle-max-calls", "10"],
        )

        out = capsys.readouterr().out
        assert "Oracle calibration enabled: up to 10 calls" in out
        assert "900s" in out


# ---------------------------------------------------------------------------
# Run records (U4). These run the real evolution, kept tiny, because what is
# under test is what the CLI writes from a real run.
# ---------------------------------------------------------------------------

import hashlib
import os
import signal

from rct2 import runrecord, td6


def _real_cli(monkeypatch, tmp_path, *extra):
    output_path = tmp_path / "out.td6"
    monkeypatch.setattr(sys, "argv", [
        "evolve_coaster.py", "--output", str(output_path), *extra,
    ])
    evolve_coaster.main()
    return output_path


def _only_run():
    (record,) = runrecord.list_runs()
    return runrecord.load_run(record["id"])


class TestRunRecord:
    def test_a_cli_run_writes_a_complete_record(self, monkeypatch, tmp_path, capsys):
        """Covers AE8: a terminal run lands in the library like any other."""
        _real_cli(monkeypatch, tmp_path, "-g", "6", "-p", "8", "--rng-seed", "3",
                  "--fitness", "physics", "--target-intensity", "2:6")

        run = _only_run()
        rec = run.record
        assert rec["status"] == "completed"
        assert rec["seed"] == 3
        assert rec["generations_planned"] == 6
        assert rec["generations_run"] == 6
        assert rec["pid"] == os.getpid()
        assert rec["request"]["fitness"] == "physics"
        assert rec["request"]["target_intensity"] == [2.0, 6.0]
        assert rec["request"]["seed"] == 3
        assert "--target-intensity" in rec["settings"]
        assert [p["generation"] for p in run.progress] == list(range(6))
        assert {"time", "best_fitness", "avg_fitness", "population"} <= set(run.progress[0])
        assert run.improvements
        assert (run.directory / "best.td6").exists()
        result = rec["result"]
        assert result["valid"] is True
        assert set(result["estimated"]) == {"excitement", "intensity", "nausea"}
        assert result["footprint"]["max_width"] == 30
        assert result["stats"]["ride_length"] > 0
        assert str(run.directory) in capsys.readouterr().out

    def test_a_blank_seed_is_recorded_as_the_one_used(self, monkeypatch, tmp_path, capsys):
        _real_cli(monkeypatch, tmp_path, "-g", "2", "-p", "4")
        out = capsys.readouterr().out
        rec = _only_run().record
        assert f"RNG seed: {rec['seed']}" in out
        assert rec["request"]["seed"] == rec["seed"]

    @pytest.mark.parametrize("args,digest", [
        (["-g", "10", "-p", "12", "--rng-seed", "21", "--fitness", "physics"],
         "dcca17515b2780c02f22006b08ef6c37a731dcc7c7a843918486f0a9a43fb986"),
        (["-g", "10", "-p", "12", "--rng-seed", "8", "--fitness", "proxy"],
         "d48f9f35d8f5e58c1d124687610266ae30016a3ce8af84dd6a5983458788c978"),
    ])
    def test_output_bytes_are_unchanged_for_a_fixed_seed(self, monkeypatch, tmp_path, args, digest):
        """Digests recorded from the CLI before run records existed."""
        output = _real_cli(monkeypatch, tmp_path, *args)
        assert hashlib.sha256(output.read_bytes()).hexdigest() == digest
        run = _only_run()
        assert (run.directory / "best.td6").read_bytes() == output.read_bytes()

    def test_no_record_writes_nothing_under_generide_home(
        self, monkeypatch, tmp_path, isolated_generide_home, capsys,
    ):
        output = _real_cli(monkeypatch, tmp_path, "-g", "2", "-p", "4", "--no-record")
        assert output.exists()
        assert not isolated_generide_home.exists()
        assert "Run record" not in capsys.readouterr().out

    def test_last_improvement_is_the_exported_track(self, monkeypatch, tmp_path):
        output = _real_cli(monkeypatch, tmp_path, "-g", "8", "-p", "10", "--rng-seed", "21",
                           "--fitness", "physics")
        run = _only_run()
        exported = [e.segment_type for e in td6.load(output).elements]
        assert run.improvements[-1]["segments"] == exported
        fitnesses = [i["fitness"] for i in run.improvements]
        assert fitnesses == sorted(fitnesses)
        assert run.improvements[-1]["fitness"] == pytest.approx(run.record["result"]["fitness"])

    def test_final_generation_best_is_logged_even_though_no_callback_saw_it(
        self, monkeypatch, tmp_path,
    ):
        """The progress callback runs before each generation breeds, so a new
        best from the last generation's offspring only exists in the result."""
        better = create_hill_circuit()

        def run(**kwargs):
            population = type("P", (), {})()
            seed_ind = Individual(segments=create_hill_circuit(), fitness=1.0)
            population.individuals = [seed_ind]
            population.best = lambda: seed_ind
            population.average_fitness = lambda: 1.0
            population.valid_count = lambda: 1
            kwargs["progress_callback"](0, population)
            return EvolutionStats(
                generations=1, best_fitness=5.0,
                best_individual=Individual(segments=better, fitness=5.0),
                fitness_history=[1.0], valid_ratio_history=[1.0],
            )

        monkeypatch.setattr(evolve_coaster, "evolve_parts", run)
        _real_cli(monkeypatch, tmp_path, "-g", "1", "-p", "4")
        improvements = _only_run().improvements
        assert [i["fitness"] for i in improvements] == [1.0, 5.0]
        assert improvements[-1]["segments"] == better

    def test_parent_run_is_stored(self, monkeypatch, tmp_path):
        _real_cli(monkeypatch, tmp_path, "-g", "2", "-p", "4",
                  "--parent-run", "20260926T100000Z-s1")
        assert _only_run().record["parent"] == "20260926T100000Z-s1"

    def test_run_id_from_the_caller_is_used(self, monkeypatch, tmp_path):
        _real_cli(monkeypatch, tmp_path, "-g", "2", "-p", "4",
                  "--run-id", "20260927T120000Z-s77")
        assert _only_run().record["id"] == "20260927T120000Z-s77"

    @pytest.mark.parametrize("flag", ["--run-id", "--parent-run"])
    def test_malformed_ids_are_refused(self, monkeypatch, tmp_path, flag):
        monkeypatch.setattr(sys, "argv", [
            "evolve_coaster.py", "--output", str(tmp_path / "o.td6"), flag, "../escape",
        ])
        with pytest.raises(SystemExit):
            evolve_coaster.main()
        assert runrecord.list_runs() == []

    def test_a_stop_mid_run_finishes_as_stopped(self, monkeypatch, tmp_path):
        """Covers AE3: SIGTERM (what the page's Stop sends) ends the run at
        the next generation with its best ride exported and recorded."""
        real_evolve_parts = evolve_coaster.evolve_parts

        def run(**kwargs):
            callback = kwargs["progress_callback"]

            def stop_at_three(gen, population):
                callback(gen, population)
                if gen == 3:
                    os.kill(os.getpid(), signal.SIGTERM)

            kwargs["progress_callback"] = stop_at_three
            return real_evolve_parts(**kwargs)

        monkeypatch.setattr(evolve_coaster, "evolve_parts", run)
        output = _real_cli(monkeypatch, tmp_path, "-g", "40", "-p", "8", "--rng-seed", "21",
                           "--fitness", "physics")
        run_ = _only_run()
        assert run_.record["status"] == "stopped"
        assert run_.record["generations_run"] == 3
        assert run_.record["generations_planned"] == 40
        assert output.exists()
        assert (run_.directory / "best.td6").exists()
        # The handler is removed again once the run is over.
        assert signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None)

    def test_no_valid_ride_finishes_as_failed_and_exits_1(self, monkeypatch, tmp_path):
        broken = [0x00, 0x00, 0x00]

        def run(**kwargs):
            population = type("P", (), {})()
            ind = Individual(segments=broken, fitness=-100.0)
            population.individuals = [ind]
            population.best = lambda: ind
            population.average_fitness = lambda: -100.0
            population.valid_count = lambda: 0
            kwargs["progress_callback"](0, population)
            return EvolutionStats(
                generations=1, best_fitness=-100.0, best_individual=ind,
                fitness_history=[-100.0], valid_ratio_history=[0.0],
            )

        monkeypatch.setattr(evolve_coaster, "evolve_parts", run)
        with pytest.raises(SystemExit) as exc:
            _real_cli(monkeypatch, tmp_path, "-g", "1", "-p", "4")
        assert exc.value.code == 1
        run_ = _only_run()
        assert run_.record["status"] == "failed"
        assert run_.record["result"]["valid"] is False
        assert run_.improvements
        assert not (run_.directory / "best.td6").exists()
        assert not (tmp_path / "out.td6").exists()


class TestSiteFlag:
    """A site given on the command line reaches whichever fitness class --fitness selects."""

    def _write_site(self, tmp_path):
        from rct2.site import Site

        site = Site.from_rows(["." * 12] * 20, anchor=(4, 4))
        path = tmp_path / "site.json"
        site.save(path)
        return site, path

    @pytest.mark.parametrize("fitness_args", [[], ["--fitness", "physics"]])
    def test_the_site_reaches_the_fitness_function(self, monkeypatch, tmp_path, fitness_args):
        site, path = self._write_site(tmp_path)

        captured, _ = _run_cli(
            monkeypatch, tmp_path, ["--genome", "parts", "--site", str(path), *fitness_args]
        )

        assert captured["fitness_fn"].site == site

    def test_without_the_flag_no_site_is_applied(self, monkeypatch, tmp_path):
        captured, _ = _run_cli(monkeypatch, tmp_path, ["--genome", "parts"])

        assert captured["fitness_fn"].site is None

    def test_a_ride_bigger_than_the_old_rectangle_is_still_exported_when_it_fits_the_site(
        self, monkeypatch, tmp_path
    ):
        # The default rectangle is 30 by 30; the hill circuit is far smaller, so shrink it.
        site, path = self._write_site(tmp_path)

        captured, output_path = _run_cli(
            monkeypatch,
            tmp_path,
            ["--genome", "parts", "--site", str(path), "--max-width", "2", "--max-depth", "2"],
        )

        assert output_path.exists()

    def test_a_missing_site_file_stops_before_evolving(self, monkeypatch, tmp_path, capsys):
        with pytest.raises(SystemExit) as exit_info:
            _run_cli(monkeypatch, tmp_path, ["--site", str(tmp_path / "nope.json")])

        assert exit_info.value.code == 1
        assert "site file could not be read" in capsys.readouterr().err

    def test_a_malformed_site_file_is_named_before_a_run_starts(self, monkeypatch, tmp_path, capsys):
        path = tmp_path / "bad.json"
        path.write_text('{"version": 1, "rows": [".."], "anchor": [9, 9]}')
        captured = {}

        with pytest.raises(SystemExit):
            _run_cli(monkeypatch, tmp_path, ["--site", str(path)])

        assert "anchor" in capsys.readouterr().err

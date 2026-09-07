"""Tests for the evolve_coaster.py CLI's oracle-calibration flags.

These tests never run real evolution or the real oracle: `main()`'s
`evolve`/`evolve_parts` call is monkeypatched to a fake that captures the
kwargs it was given and returns a stand-in EvolutionStats, so the tests
exercise only the CLI's own argument parsing, validation, and wiring (U3),
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

"""Tests for the page's settings table and validation."""

import pytest

import evolve_coaster
from rct2 import settings
from rct2.settings import SETTINGS, cli_args, form_values, request_from_args, validate


def _parser():
    return evolve_coaster.build_parser()


def _action(flag):
    for action in _parser()._actions:
        if flag in action.option_strings:
            return action
    return None


def _valid(**overrides):
    values = {"seed": 11}
    values.update(overrides)
    result = validate(values)
    assert result.errors == {}, result.errors
    return result.values


class TestTableMatchesTheCli:
    @pytest.mark.parametrize("setting", SETTINGS, ids=lambda s: s.key)
    def test_every_flag_exists_with_the_same_default(self, setting):
        action = _action(setting.flag)
        assert action is not None, f"{setting.flag} is not an evolve_coaster.py flag"
        assert setting.cli_default == action.default
        if setting.key == "fitness":
            # The one documented difference (KTD8): the page starts from
            # physics scoring, the CLI keeps its proxy default.
            assert setting.default == "physics" and action.default == "proxy"
        elif setting.kind == "window":
            assert setting.default is None and action.default is None
        else:
            assert setting.default == action.default
        if setting.choices:
            assert tuple(setting.choices) == tuple(action.choices)

    def test_groups_are_the_up_front_and_advanced_sets(self):
        up_front = {s.key for s in SETTINGS if s.group == "basic"}
        assert up_front == {
            "max_width", "max_depth", "target_excitement", "target_intensity",
            "target_nausea", "station_length", "generations", "population", "seed",
        }
        advanced = {s.key for s in SETTINGS if s.group == "advanced"}
        assert {"fitness", "genome", "mutation_rate", "seed_track",
                "oracle_calibrate"} <= advanced

    @pytest.mark.parametrize("setting", SETTINGS, ids=lambda s: s.key)
    def test_help_reads_as_plain_sentences(self, setting):
        assert setting.label and setting.help
        assert setting.help[0].isupper() and setting.help.endswith(".")
        assert "--" not in setting.help  # no CLI jargon on the page

    def test_rating_windows_say_they_aim_at_estimates(self):
        for key in ("target_excitement", "target_intensity", "target_nausea"):
            (setting,) = [s for s in SETTINGS if s.key == key]
            assert "estimate" in setting.note.lower()

    def test_table_is_json_ready(self):
        import json

        json.dumps(settings.table())


class TestValidArguments:
    def test_defaults_parse_in_the_cli(self):
        args = cli_args(_valid())
        parsed = _parser().parse_args(args)
        assert parsed.fitness == "physics"
        assert parsed.rng_seed == 11
        assert parsed.generations == 100

    def test_every_setting_filled_in_parses_in_the_cli(self, tmp_path):
        seed_track = tmp_path / "seed.td6"
        seed_track.write_bytes(b"x")
        values = _valid(
            max_width=20, max_depth="18", target_excitement={"min": 5, "max": 7},
            target_intensity={"min": "4", "max": "6.5"}, target_nausea=None,
            station_length=4, generations=30, population=20, fitness="physics",
            genome="parts", mutation_rate=0.2, seed_track=str(seed_track),
            oracle_calibrate=True, oracle_interval=5, oracle_max_calls=3,
        )
        parsed = _parser().parse_args(cli_args(values))
        assert (parsed.max_width, parsed.max_depth) == (20, 18)
        assert parsed.target_excitement == "5:7"
        assert parsed.target_intensity == "4:6.5"
        assert parsed.target_nausea is None
        assert parsed.seed == str(seed_track)
        assert parsed.oracle_calibrate is True
        assert (parsed.oracle_interval, parsed.oracle_max_calls) == (5, 3)

    def test_a_blank_seed_is_left_for_the_caller_to_pick(self):
        values = validate({}).values
        assert values["seed"] is None
        assert "--rng-seed" not in cli_args(values)


class TestErrors:
    def test_excitement_window_the_wrong_way_round(self):
        errors = validate({"target_excitement": {"min": 7, "max": 5}}).errors
        assert set(errors) == {"target_excitement"}
        assert "7" in errors["target_excitement"] and "5" in errors["target_excitement"]
        assert "above" in errors["target_excitement"]

    def test_window_with_one_end_missing(self):
        errors = validate({"target_nausea": {"min": 2, "max": ""}}).errors
        assert "both" in errors["target_nausea"]

    def test_intensity_window_with_proxy_scoring(self):
        errors = validate({"fitness": "proxy",
                           "target_intensity": {"min": 3, "max": 5}}).errors
        assert set(errors) == {"target_intensity"}
        assert "physics" in errors["target_intensity"]

    @pytest.mark.parametrize("key,value", [
        ("generations", 0), ("station_length", 1), ("population", 1),
        ("mutation_rate", 1.5), ("max_width", -3),
    ])
    def test_range_errors_name_the_allowed_range(self, key, value):
        errors = validate({key: value}).errors
        assert set(errors) == {key}
        (setting,) = [s for s in SETTINGS if s.key == key]
        assert f"from {setting.minimum:g} to {setting.maximum:g}" in errors[key]

    def test_not_a_number(self):
        errors = validate({"generations": "lots", "mutation_rate": "abc"}).errors
        assert "whole number" in errors["generations"]
        assert "number" in errors["mutation_rate"]

    def test_fractional_generations_are_rejected(self):
        assert "whole number" in validate({"generations": 2.5}).errors["generations"]

    def test_oracle_calibration_with_pieces_genome(self):
        errors = validate({"genome": "pieces", "oracle_calibrate": True}).errors
        assert "oracle_calibrate" in errors

    @pytest.mark.parametrize("path", ["nope.td6", "notes.txt"])
    def test_seed_track_must_be_an_existing_td6(self, path, tmp_path):
        if path.endswith(".txt"):
            (tmp_path / path).write_text("x")
        errors = validate({"seed_track": str(tmp_path / path)}).errors
        assert "seed_track" in errors

    def test_unknown_choice_and_unknown_field(self):
        errors = validate({"genome": "tentacles", "colour": "red"}).errors
        assert "genome" in errors and "colour" in errors


class TestRerun:
    def test_stored_request_round_trips_to_the_same_cli_arguments(self):
        """Covers AE6: every input, the seed included, carries into the rerun form."""
        original = _valid(
            max_width=22, target_intensity={"min": 3, "max": 5.5},
            generations=40, population=24, seed=987654,
        )
        args = cli_args(original)
        # The CLI stores its request from the parsed arguments (U4).
        stored = request_from_args(_parser().parse_args(args))

        values = form_values(stored)
        assert values["seed"] == 987654
        assert cli_args(validate(values).values) == args

    def test_form_values_fill_gaps_with_page_defaults(self):
        values = form_values({"generations": 12, "seed": 3})
        assert values["generations"] == 12
        assert values["fitness"] == "physics"
        assert values["max_width"] == 30

    def test_the_cli_simple_seed_means_no_seed_track(self):
        stored = request_from_args(_parser().parse_args(["--seed", "simple"]))
        assert stored["seed_track"] is None
        assert validate(form_values(stored)).ok


class TestSeedTrackPaths:
    def test_a_relative_seed_track_is_stored_absolute(self, tmp_path, monkeypatch):
        """Runs started from the page execute in their own run folder, so a
        relative path would point somewhere else there."""
        (tmp_path / "seed.td6").write_bytes(b"x")
        monkeypatch.chdir(tmp_path)
        values = validate({"seed_track": "seed.td6"}).values
        assert values["seed_track"] == str(tmp_path / "seed.td6")
        stored = request_from_args(_parser().parse_args(["--seed", "seed.td6"]))
        assert stored["seed_track"] == str(tmp_path / "seed.td6")

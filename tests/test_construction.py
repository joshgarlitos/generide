from pathlib import Path

import pytest

from rct2 import construction, physics, td6
from rct2.construction import (
    DROP_HEIGHT_THRESHOLD,
    LIFT_CAPABLE_SEGMENTS,
    MAX_HILL_HEIGHT,
    MIN_HILL_HEIGHT,
    bank_closing_path,
    bank_state_at,
    build_hill,
    build_station,
    default_lift_indices,
    energy_stall_index,
    legal_bank_segments,
    legal_slope_segments,
    slope_closing_path,
    hill_height,
    slope_state_at,
    validate_construction,
)
from rct2.segments import SEGMENTS
from rct2.evolution import Individual
from rct2.generate import create_simple_circuit
from rct2.physics import simulate


FIXTURE = Path(__file__).parent.parent / "data" / "sample_rides" / "manic_miner_test.td6"


def test_simple_circuit_is_construction_valid():
    assert validate_construction(create_simple_circuit()).valid


def test_real_mine_train_is_construction_valid_with_exported_lifts():
    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {index for index, element in enumerate(ride.elements) if element.chain_lift}

    result = validate_construction(segments, lift_indices=lifts)

    assert result.valid, result.issues


def test_invalid_slope_transition_reports_segment_index():
    result = validate_construction([0x02, 0x01, 0x09])

    issue = next(issue for issue in result.issues if issue.code == "slope_transition")
    assert "segment 2" in issue.message


def test_closed_track_with_invalid_banking_is_not_valid():
    segments = create_simple_circuit()
    segments[2] = 0x2D

    result = validate_construction(segments)

    assert any(issue.code == "bank_transition" for issue in result.issues)
    assert not Individual(segments).is_valid()


def test_missing_first_hill_lift_is_reported():
    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]

    result = validate_construction(segments, lift_indices=set())

    assert any(issue.code == "missing_chain_lift" for issue in result.issues)


def test_default_lifts_cover_first_uphill_sequence():
    segments = [0x02, 0x01, 0x06, 0x04, 0x09, 0x00]
    assert default_lift_indices(segments) == {2, 3, 4}


def test_legal_slope_segments_from_flat_matches_entry_pieces():
    assert legal_slope_segments("flat") == {
        0x06: "up", 0x0C: "down", 0x18: "up", 0x19: "up", 0x1C: "down", 0x1D: "down",
    }


def test_legal_slope_segments_from_up_includes_steep_climb():
    assert legal_slope_segments("up") == {
        0x04: "up", 0x07: "steep_up", 0x09: "flat", 0x1A: "flat", 0x1B: "flat",
        0x22: "up", 0x23: "up",
    }


def test_legal_slope_segments_from_steep_up_stays_or_descends():
    assert legal_slope_segments("steep_up") == {0x05: "steep_up", 0x08: "up"}


def test_legal_bank_segments_from_flat_matches_entry_pieces():
    assert legal_bank_segments("flat") == {
        0x12: "left", 0x13: "right", 0x1A: "left", 0x1B: "right", 0x1E: "left", 0x1F: "right",
    }


def test_slope_closing_path_returns_shortest_non_combo_route_to_flat():
    assert slope_closing_path("flat") == []
    assert slope_closing_path("up") == [0x09]
    assert slope_closing_path("steep_up") == [0x08, 0x09]
    assert slope_closing_path("down") == [0x0F]
    assert slope_closing_path("steep_down") == [0x0E, 0x0F]


def test_bank_closing_path_returns_shortest_non_combo_route_to_flat():
    assert bank_closing_path("flat") == []
    assert bank_closing_path("left") == [0x14]
    assert bank_closing_path("right") == [0x15]


def test_slope_state_at_replays_prefix():
    segments = [0x02, 0x01, 0x06, 0x04, 0x09, 0x00]
    assert slope_state_at(segments, 2) == "flat"
    assert slope_state_at(segments, 3) == "up"
    assert slope_state_at(segments, 4) == "up"
    assert slope_state_at(segments, 5) == "flat"
    assert slope_state_at(segments) == "flat"


def test_bank_state_at_replays_prefix():
    segments = [0x02, 0x01, 0x12, 0x16, 0x14, 0x00]
    assert bank_state_at(segments, 2) == "flat"
    assert bank_state_at(segments, 3) == "left"
    assert bank_state_at(segments, 4) == "left"
    assert bank_state_at(segments, 5) == "flat"
    assert bank_state_at(segments) == "flat"


def test_climb_beyond_lift_height_is_an_energy_shortfall():
    # Station, one short powered hill, then keep climbing under momentum alone.
    # The lift set is explicit: default_lift_indices would power the whole
    # contiguous climb and there would be nothing to run out of.
    segments = [0x02, 0x01, 0x06, 0x09] + [0x06, 0x04, 0x04, 0x04, 0x09] * 3

    result = validate_construction(segments, lift_indices={2, 3})

    assert result.count("energy_shortfall") > 0


def test_flat_liftless_circuit_is_buildable_but_not_completable():
    """The seed track is the case that keeps the two checks separate.

    OpenRCT2 builds this fine, so it stays construction-valid. No train can
    run it, so the stall screen and physics both reject it.
    """
    segments = create_simple_circuit()

    assert validate_construction(segments).valid
    assert energy_stall_index(segments) is not None
    assert not simulate(segments).completed


def test_stall_screen_catches_friction_death_on_flat_ground():
    # Long flat run with no lift: nothing ever climbs, so _energy_issues stays
    # silent while the train coasts to a stop.
    segments = [0x02, 0x01] + [0x00] * 40

    assert not validate_construction(segments).count("energy_shortfall")
    assert energy_stall_index(segments) is not None


def test_lift_restores_head_so_a_powered_track_keeps_running():
    segments = [0x02, 0x01] + [0x00] * 6

    # Identical geometry: marking the flat run as lift-driven is what keeps
    # the train alive, so the lift set has to actually feed the budget.
    assert energy_stall_index(segments, lift_indices=set()) is not None
    assert energy_stall_index(segments, lift_indices=set(range(2, 8))) is None


def test_real_mine_train_completes_under_the_stall_screen():
    """The screen must not reject a real, working, game-authored ride."""
    ride = td6.load(FIXTURE)
    segments = [element.segment_type for element in ride.elements]
    lifts = {index for index, element in enumerate(ride.elements) if element.chain_lift}

    assert energy_stall_index(segments, lift_indices=lifts) is None
    assert simulate(segments, lift_indices=lifts).completed


def test_stall_screen_constants_match_the_physics_model():
    """Pin the head constants so the two energy models cannot drift.

    construction.py cannot import physics.py (physics depends on construction),
    so the head constants are written out as numbers there. This recomputes
    them from the physics source values and fails if either side moves.
    """
    def head_units(speed_ms: float) -> float:
        return speed_ms**2 / (2 * physics.GRAVITY) / physics.HEIGHT_UNIT_M

    assert construction.LIFT_HEAD == pytest.approx(
        head_units(physics.LIFT_SPEED_MS), abs=1e-3
    )
    assert construction.STALL_HEAD == pytest.approx(
        head_units(physics.MIN_SPEED_MS), abs=1e-3
    )


class TestBuildHill:
    """The lift hill part: one atomic climb-then-drop over the game's
    drop-height threshold. See docs/research-plan.md."""

    HEIGHTS = list(range(MIN_HILL_HEIGHT, MAX_HILL_HEIGHT + 1, 2))

    @pytest.mark.parametrize("height", HEIGHTS)
    def test_climb_and_drop_cancel_out(self, height):
        """A hill returns the track to the elevation it started at, so it can
        be dropped in anywhere without shifting everything after it."""
        deltas = [SEGMENTS[seg].elevation_delta for seg in build_hill(height)]
        assert sum(deltas) == 0
        assert sum(d for d in deltas if d > 0) == height

    @pytest.mark.parametrize("height", HEIGHTS)
    def test_physics_measures_it_as_one_drop_of_that_height(self, height):
        """The descent must be uninterrupted. physics.simulate resets its
        run at the first non-descending piece, so a hill whose drop is broken
        up would measure short and miss the threshold it exists to clear."""
        stats = simulate(build_station() + build_hill(height) + [0x00] * 3)
        assert stats.highest_drop == height
        assert stats.drop_count == 1

    @pytest.mark.parametrize("height", HEIGHTS)
    def test_every_hill_clears_the_games_drop_threshold(self, height):
        assert height >= DROP_HEIGHT_THRESHOLD

    @pytest.mark.parametrize("height", HEIGHTS)
    def test_the_climb_takes_the_chain_lift(self, height):
        """find_first_hill assigns the lift to the first run of climb pieces,
        so a hill placed directly after the station must be that run --
        otherwise the train has no power to reach the top."""
        segments = build_station() + build_hill(height) + [0x00] * 3
        lift = default_lift_indices(segments)
        assert lift
        assert construction.check_first_hill_has_lift(segments, lift)

    @pytest.mark.parametrize("height", HEIGHTS)
    def test_hill_height_round_trips(self, height):
        assert hill_height(build_hill(height)) == height

    def test_hill_height_rejects_anything_that_is_not_a_hill(self):
        assert hill_height([]) == 0
        assert hill_height([0x00] * 8) == 0
        assert hill_height(build_station()) == 0
        assert hill_height(build_hill(MIN_HILL_HEIGHT)[:-1]) == 0

    def test_rejects_odd_and_out_of_range_heights(self):
        with pytest.raises(ValueError):
            build_hill(MIN_HILL_HEIGHT + 1)
        with pytest.raises(ValueError):
            build_hill(MIN_HILL_HEIGHT - 2)
        with pytest.raises(ValueError):
            build_hill(MAX_HILL_HEIGHT + 2)


class TestLiftSteepness:
    """The Mine Train's chain lift tops out at 25 degrees.

    A generated ride passed every check here and then would not build in the
    game: "Too steep for lift hill". The headless oracle missed it too, since
    it places track without ever setting the chain lift flag. See
    docs/devlog.md (2026-08-16).
    """

    def test_a_steep_lift_is_a_construction_error(self):
        segments = (
            build_station()
            + [0x06, 0x07, 0x05, 0x08, 0x09, 0x0C, 0x0D, 0x0E, 0x0F]
            + [0x00] * 3
        )
        codes = [i.code for i in validate_construction(segments).issues]
        assert "lift_too_steep" in codes

    def test_the_error_names_every_offending_piece(self):
        segments = build_station() + [0x06, 0x07, 0x05, 0x08, 0x09] + [0x00] * 3
        issues = [
            i for i in validate_construction(segments).issues
            if i.code == "lift_too_steep"
        ]
        # 0x07, 0x05 and 0x08 are the 60-degree climb and its transitions.
        assert len(issues) == 3

    @pytest.mark.parametrize(
        "height", list(range(MIN_HILL_HEIGHT, MAX_HILL_HEIGHT + 1, 2))
    )
    def test_build_hill_never_produces_one(self, height):
        segments = build_station() + build_hill(height) + [0x00] * 3
        codes = [i.code for i in validate_construction(segments).issues]
        assert "lift_too_steep" not in codes

    @pytest.mark.parametrize(
        "height", list(range(MIN_HILL_HEIGHT, MAX_HILL_HEIGHT + 1, 2))
    )
    def test_every_climb_piece_can_carry_a_lift(self, height):
        """The climb is what the lift sits on, so every rising piece in a hill
        has to be one the lift is allowed to occupy."""
        climbing = [
            seg for seg in build_hill(height)
            if SEGMENTS[seg].elevation_delta > 0
        ]
        assert climbing
        assert all(seg in LIFT_CAPABLE_SEGMENTS for seg in climbing)

    def test_the_drop_is_still_allowed_to_be_steep(self):
        """Only the lift is limited. A 60-degree drop is legal, and it is
        where the speed and the excitement come from."""
        dropping = [
            seg for seg in build_hill(MIN_HILL_HEIGHT)
            if SEGMENTS[seg].elevation_delta < 0
        ]
        assert any(seg in {0x0B, 0x0D, 0x0E} for seg in dropping)

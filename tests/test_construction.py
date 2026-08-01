from pathlib import Path

import pytest

from rct2 import construction, physics, td6
from rct2.construction import (
    bank_closing_path,
    bank_state_at,
    default_lift_indices,
    energy_stall_index,
    legal_bank_segments,
    legal_slope_segments,
    slope_closing_path,
    slope_state_at,
    validate_construction,
)
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

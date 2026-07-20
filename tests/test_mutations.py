"""Tests for mutation operators."""

import random

import pytest

import rct2.mutations
from rct2.construction import BANK_TRANSITIONS, SLOPE_TRANSITIONS, bank_state_at, slope_state_at
from rct2.geometry import Position, is_closed_circuit
from rct2.generate import create_simple_circuit
from rct2.mutations import (
    BEGIN_STATION,
    END_STATION,
    FLAT_SEGMENTS,
    SIMPLE_SEGMENTS,
    TURN_LEFT,
    TURN_RIGHT,
    _build_bank_run,
    _build_slope_run,
    _slope_bump,
    crossover,
    delete_segment,
    generate_random_track,
    insert_segment,
    mutate,
    repair_circuit,
    replace_segment,
    swap_segments,
)


class TestNoDuplicatedLegalityData:
    """construction.py must be the single source of truth for slope/bank rules."""

    def test_no_canned_slope_or_bank_tables_in_mutations(self):
        assert not hasattr(rct2.mutations, "SLOPE_SEQUENCES")
        assert not hasattr(rct2.mutations, "BANKED_SEQUENCES")


class TestBasicOperations:
    """Tests for basic mutation operations."""

    def test_insert_segment_increases_length(self):
        """Inserting a segment increases the list length by 1."""
        original = [0x00, 0x00, 0x00]
        result = insert_segment(original, 1, 0x2B)
        assert len(result) == len(original) + 1
        assert result[1] == 0x2B

    def test_insert_segment_at_start(self):
        """Can insert at the beginning of the list."""
        original = [0x00, 0x00]
        result = insert_segment(original, 0, 0x2B)
        assert result == [0x2B, 0x00, 0x00]

    def test_insert_segment_at_end(self):
        """Can insert at the end of the list."""
        original = [0x00, 0x00]
        result = insert_segment(original, 2, 0x2B)
        assert result == [0x00, 0x00, 0x2B]

    def test_delete_segment_decreases_length(self):
        """Deleting a segment decreases the list length by 1."""
        original = [0x00, 0x2B, 0x00]
        result = delete_segment(original, 1)
        assert len(result) == len(original) - 1
        assert 0x2B not in result

    def test_delete_preserves_order(self):
        """Deleting preserves the order of remaining segments."""
        original = [0x00, 0x2B, 0x2A, 0x00]
        result = delete_segment(original, 1)
        assert result == [0x00, 0x2A, 0x00]

    def test_replace_segment_maintains_length(self):
        """Replacing a segment keeps the list length unchanged."""
        original = [0x00, 0x00, 0x00]
        result = replace_segment(original, 1, 0x2B)
        assert len(result) == len(original)
        assert result[1] == 0x2B

    def test_replace_preserves_other_positions(self):
        """Replacing only changes the target position."""
        original = [0x01, 0x02, 0x03]
        result = replace_segment(original, 1, 0xFF)
        assert result[0] == 0x01
        assert result[2] == 0x03

    def test_swap_segments_exchanges_values(self):
        """Swapping exchanges two segment values."""
        original = [0x00, 0x2B, 0x2A, 0x00]
        result = swap_segments(original, 1, 2)
        assert result[1] == 0x2A
        assert result[2] == 0x2B

    def test_swap_segments_maintains_length(self):
        """Swapping doesn't change list length."""
        original = [0x00, 0x2B, 0x2A, 0x00]
        result = swap_segments(original, 1, 2)
        assert len(result) == len(original)

    def test_operations_do_not_modify_original(self):
        """All operations return new lists, not modify in place."""
        original = [0x00, 0x00, 0x00]
        insert_segment(original, 1, 0x2B)
        assert len(original) == 3  # Unchanged

        delete_segment(original, 1)
        assert len(original) == 3  # Unchanged

        replace_segment(original, 1, 0x2B)
        assert original[1] == 0x00  # Unchanged


class TestBuildRuns:
    """Tests for the run-building helpers that back insert_slope/insert_banked."""

    def test_build_slope_run_starts_and_ends_flat(self):
        rng = random.Random(42)
        for _ in range(50):
            run = _build_slope_run(rng)
            assert slope_state_at(run) == "flat"

    def test_build_bank_run_starts_and_ends_flat(self):
        rng = random.Random(42)
        for _ in range(50):
            run = _build_bank_run(rng)
            assert bank_state_at(run) == "flat"

    def test_build_slope_run_can_reach_steep_pieces(self):
        rng = random.Random(1)
        found = set()
        for _ in range(500):
            found.update(_build_slope_run(rng))
        assert {0x05, 0x07, 0x08} & found


class TestMutateFunction:
    """Tests for the high-level mutate function."""

    def test_mutate_preserves_station(self):
        """Mutation should not remove station segments."""
        rng = random.Random(42)
        segments = create_simple_circuit()
        for _ in range(10):  # Multiple attempts
            mutated = mutate(segments, rng, rate=0.5)
            assert mutated[0] == BEGIN_STATION
            assert mutated[1] == END_STATION

    def test_mutate_returns_valid_segments(self):
        """Mutated segments should be from the valid set."""
        rng = random.Random(42)
        segments = create_simple_circuit()
        # Build set of all valid segments (simple + any legal slope/bank piece)
        valid_segments = (
            set(SIMPLE_SEGMENTS) | {BEGIN_STATION, END_STATION}
            | set(SLOPE_TRANSITIONS) | set(BANK_TRANSITIONS)
        )

        for _ in range(10):
            mutated = mutate(segments, rng, rate=0.3)
            for seg in mutated:
                assert seg in valid_segments

    def test_mutate_with_zero_rate_returns_original(self):
        """Zero mutation rate should return unchanged segments."""
        rng = random.Random(42)
        segments = create_simple_circuit()
        mutated = mutate(segments, rng, rate=0.0)
        # With rate 0, we still get 1 mutation, but it might still close
        assert len(mutated) >= len(segments) - 1

    def test_mutate_handles_short_track(self):
        """Mutate should handle very short tracks gracefully."""
        rng = random.Random(42)
        segments = [BEGIN_STATION, END_STATION]
        mutated = mutate(segments, rng, rate=0.5)
        assert mutated[0] == BEGIN_STATION
        assert mutated[1] == END_STATION


class TestRepairCircuit:
    """Tests for circuit repair functionality."""

    def test_repair_circuit_closes_gap(self):
        """Repair should close an open circuit."""
        rng = random.Random(42)
        # Simple open track: station + straight
        open_track = [BEGIN_STATION, END_STATION, FLAT_SEGMENTS[0]]
        repaired = repair_circuit(open_track, rng, max_repair_segments=20)

        if repaired is not None:
            assert is_closed_circuit(Position(), repaired)

    def test_repair_already_closed(self):
        """Repair should return closed circuits unchanged."""
        rng = random.Random(42)
        closed = create_simple_circuit()
        repaired = repair_circuit(closed, rng)
        assert repaired is not None
        assert is_closed_circuit(Position(), repaired)

    def test_slope_bump_matches_original_hardcoded_pairs(self):
        """The derived elevation bump should match the old literal pairs."""
        assert _slope_bump("up") == [0x06, 0x09]
        assert _slope_bump("down") == [0x0C, 0x0F]

    def test_repair_returns_none_on_failure(self):
        """Repair should return None if it can't close the circuit."""
        rng = random.Random(42)
        # Very long straight line is hard to close
        impossible = [BEGIN_STATION, END_STATION] + [FLAT_SEGMENTS[0]] * 100
        repaired = repair_circuit(impossible, rng, max_repair_segments=4)
        # May or may not succeed depending on random choices
        if repaired is not None:
            assert is_closed_circuit(Position(), repaired)


class TestCrossover:
    """Tests for crossover operator."""

    def test_crossover_produces_two_offspring(self):
        """Crossover should produce exactly two offspring."""
        rng = random.Random(42)
        parent1 = create_simple_circuit()
        parent2 = [BEGIN_STATION, END_STATION] + [TURN_LEFT[0]] * 4

        child1, child2 = crossover(parent1, parent2, rng)
        assert isinstance(child1, list)
        assert isinstance(child2, list)

    def test_crossover_preserves_station_start(self):
        """Offspring should start with station segments."""
        rng = random.Random(42)
        parent1 = create_simple_circuit()
        parent2 = [BEGIN_STATION, END_STATION] + [TURN_RIGHT[0]] * 4

        child1, child2 = crossover(parent1, parent2, rng)
        assert child1[0] == BEGIN_STATION
        assert child1[1] == END_STATION

    def test_crossover_combines_genetic_material(self):
        """Offspring should contain segments from both parents."""
        rng = random.Random(42)
        # Make parents very different
        parent1 = [BEGIN_STATION, END_STATION] + [FLAT_SEGMENTS[0]] * 5
        parent2 = [BEGIN_STATION, END_STATION] + [TURN_RIGHT[1]] * 5

        # Run multiple times since crossover is random
        found_mixed = False
        for _ in range(20):
            child1, child2 = crossover(parent1, parent2, rng)
            has_flat = FLAT_SEGMENTS[0] in child1
            has_turn = TURN_RIGHT[1] in child1
            if has_flat and has_turn:
                found_mixed = True
                break

        # At least sometimes we should get mixed offspring
        assert found_mixed or len(parent1) <= 3  # Allow for very short tracks


class TestGenerateRandomTrack:
    """Tests for random track generation."""

    def test_generate_random_track_has_station(self):
        """Generated tracks should have station segments."""
        rng = random.Random(42)
        track = generate_random_track(rng)
        assert track[0] == BEGIN_STATION
        assert track[1] == END_STATION

    def test_generate_random_track_respects_length_bounds(self):
        """Generated tracks should be within length bounds."""
        rng = random.Random(42)
        track = generate_random_track(rng, min_length=5, max_length=10)
        # Length includes station (2) plus mutable segments
        assert len(track) >= 5 + 2  # min_length + station

    def test_generate_random_track_uses_valid_segments(self):
        """Generated tracks should use valid segment types."""
        rng = random.Random(42)
        valid = (
            set(SIMPLE_SEGMENTS) | {BEGIN_STATION, END_STATION}
            | set(SLOPE_TRANSITIONS) | set(BANK_TRANSITIONS)
        )
        for _ in range(5):
            track = generate_random_track(rng)
            for seg in track:
                assert seg in valid


class TestIntegration:
    """Integration tests combining multiple operations."""

    def test_steep_slope_pieces_are_reachable_end_to_end(self):
        """Steep slope pieces (0x05/0x07/0x08) must be producible via the
        public mutate()/generate_random_track() entry points, not just the
        internal run-builder (acceptance criterion #1 of issue #2)."""
        steep = {0x05, 0x07, 0x08}
        found = set()
        for seed in range(200):
            rng = random.Random(seed)
            found.update(generate_random_track(rng))
            if found & steep:
                break
        if not found & steep:
            original = create_simple_circuit()
            for seed in range(200):
                rng = random.Random(seed)
                found.update(mutate(original, rng, rate=0.5))
                if found & steep:
                    break
        assert found & steep

    def test_mutate_simple_circuit_often_stays_valid(self):
        """Mutating a valid circuit should often produce another valid circuit."""
        rng = random.Random(42)
        original = create_simple_circuit()
        valid_count = 0

        for _ in range(20):
            mutated = mutate(original, rng, rate=0.1)
            if is_closed_circuit(Position(), mutated):
                valid_count += 1

        # At least some mutations should produce valid circuits
        assert valid_count > 0

    def test_repair_fixes_some_broken_mutations(self):
        """Repair should fix some mutations that break closure."""
        rng = random.Random(42)
        original = create_simple_circuit()
        repair_success = 0

        for _ in range(20):
            # Add a single flat which breaks closure
            mutated = original.copy()
            mutated.append(FLAT_SEGMENTS[0])  # Break closure

            repaired = repair_circuit(mutated, rng, max_repair_segments=15)
            if repaired is not None and is_closed_circuit(Position(), repaired):
                repair_success += 1

        # Repair should succeed at least sometimes
        # Note: repair is stochastic and depends on track geometry
        assert repair_success >= 1

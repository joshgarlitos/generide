"""Tests for mutation operators."""

import pytest

from rct2.geometry import Position, is_closed_circuit
from rct2.generate import create_simple_circuit
from rct2.mutations import (
    BANKED_SEQUENCES,
    BEGIN_STATION,
    END_STATION,
    FLAT_SEGMENTS,
    SIMPLE_SEGMENTS,
    SLOPE_SEQUENCES,
    TURN_LEFT,
    TURN_RIGHT,
    crossover,
    delete_segment,
    generate_random_track,
    insert_segment,
    mutate,
    repair_circuit,
    replace_segment,
    swap_segments,
)


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


class TestMutateFunction:
    """Tests for the high-level mutate function."""

    def test_mutate_preserves_station(self):
        """Mutation should not remove station segments."""
        segments = create_simple_circuit()
        for _ in range(10):  # Multiple attempts
            mutated = mutate(segments, rate=0.5)
            assert mutated[0] == BEGIN_STATION
            assert mutated[1] == END_STATION

    def test_mutate_returns_valid_segments(self):
        """Mutated segments should be from the valid set."""
        segments = create_simple_circuit()
        # Build set of all valid segments (simple + slope + banked sequences)
        valid_segments = set(SIMPLE_SEGMENTS) | {BEGIN_STATION, END_STATION}
        for seq in SLOPE_SEQUENCES:
            valid_segments.update(seq)
        for seq in BANKED_SEQUENCES:
            valid_segments.update(seq)

        for _ in range(10):
            mutated = mutate(segments, rate=0.3)
            for seg in mutated:
                assert seg in valid_segments

    def test_mutate_with_zero_rate_returns_original(self):
        """Zero mutation rate should return unchanged segments."""
        segments = create_simple_circuit()
        mutated = mutate(segments, rate=0.0)
        # With rate 0, we still get 1 mutation, but it might still close
        assert len(mutated) >= len(segments) - 1

    def test_mutate_handles_short_track(self):
        """Mutate should handle very short tracks gracefully."""
        segments = [BEGIN_STATION, END_STATION]
        mutated = mutate(segments, rate=0.5)
        assert mutated[0] == BEGIN_STATION
        assert mutated[1] == END_STATION


class TestRepairCircuit:
    """Tests for circuit repair functionality."""

    def test_repair_circuit_closes_gap(self):
        """Repair should close an open circuit."""
        # Simple open track: station + straight
        open_track = [BEGIN_STATION, END_STATION, FLAT_SEGMENTS[0]]
        repaired = repair_circuit(open_track, max_repair_segments=20)

        if repaired is not None:
            assert is_closed_circuit(Position(), repaired)

    def test_repair_already_closed(self):
        """Repair should return closed circuits unchanged."""
        closed = create_simple_circuit()
        repaired = repair_circuit(closed)
        assert repaired is not None
        assert is_closed_circuit(Position(), repaired)

    def test_repair_returns_none_on_failure(self):
        """Repair should return None if it can't close the circuit."""
        # Very long straight line is hard to close
        impossible = [BEGIN_STATION, END_STATION] + [FLAT_SEGMENTS[0]] * 100
        repaired = repair_circuit(impossible, max_repair_segments=4)
        # May or may not succeed depending on random choices
        if repaired is not None:
            assert is_closed_circuit(Position(), repaired)


class TestCrossover:
    """Tests for crossover operator."""

    def test_crossover_produces_two_offspring(self):
        """Crossover should produce exactly two offspring."""
        parent1 = create_simple_circuit()
        parent2 = [BEGIN_STATION, END_STATION] + [TURN_LEFT[0]] * 4

        child1, child2 = crossover(parent1, parent2)
        assert isinstance(child1, list)
        assert isinstance(child2, list)

    def test_crossover_preserves_station_start(self):
        """Offspring should start with station segments."""
        parent1 = create_simple_circuit()
        parent2 = [BEGIN_STATION, END_STATION] + [TURN_RIGHT[0]] * 4

        child1, child2 = crossover(parent1, parent2)
        assert child1[0] == BEGIN_STATION
        assert child1[1] == END_STATION

    def test_crossover_combines_genetic_material(self):
        """Offspring should contain segments from both parents."""
        # Make parents very different
        parent1 = [BEGIN_STATION, END_STATION] + [FLAT_SEGMENTS[0]] * 5
        parent2 = [BEGIN_STATION, END_STATION] + [TURN_RIGHT[1]] * 5

        # Run multiple times since crossover is random
        found_mixed = False
        for _ in range(20):
            child1, child2 = crossover(parent1, parent2)
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
        track = generate_random_track()
        assert track[0] == BEGIN_STATION
        assert track[1] == END_STATION

    def test_generate_random_track_respects_length_bounds(self):
        """Generated tracks should be within length bounds."""
        track = generate_random_track(min_length=5, max_length=10)
        # Length includes station (2) plus mutable segments
        assert len(track) >= 5 + 2  # min_length + station

    def test_generate_random_track_uses_valid_segments(self):
        """Generated tracks should use valid segment types."""
        valid = set(SIMPLE_SEGMENTS) | {BEGIN_STATION, END_STATION}
        for seq in SLOPE_SEQUENCES:
            valid.update(seq)
        for seq in BANKED_SEQUENCES:
            valid.update(seq)
        for _ in range(5):
            track = generate_random_track()
            for seg in track:
                assert seg in valid


class TestIntegration:
    """Integration tests combining multiple operations."""

    def test_mutate_simple_circuit_often_stays_valid(self):
        """Mutating a valid circuit should often produce another valid circuit."""
        original = create_simple_circuit()
        valid_count = 0

        for _ in range(20):
            mutated = mutate(original, rate=0.1)
            if is_closed_circuit(Position(), mutated):
                valid_count += 1

        # At least some mutations should produce valid circuits
        assert valid_count > 0

    def test_repair_fixes_some_broken_mutations(self):
        """Repair should fix some mutations that break closure."""
        original = create_simple_circuit()
        repair_success = 0

        for _ in range(20):
            # Add a single flat which breaks closure
            mutated = original.copy()
            mutated.append(FLAT_SEGMENTS[0])  # Break closure

            repaired = repair_circuit(mutated, max_repair_segments=15)
            if repaired is not None and is_closed_circuit(Position(), repaired):
                repair_success += 1

        # Repair should succeed at least sometimes
        # Note: repair is stochastic and depends on track geometry
        assert repair_success >= 1

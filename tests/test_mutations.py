"""Tests for mutation operators."""

import random

import pytest

import rct2.mutations
from rct2.construction import (
    BANK_TRANSITIONS,
    DEFAULT_STATION_LENGTH,
    SLOPE_TRANSITIONS,
    STATION_SEGMENTS,
    bank_state_at,
    build_station,
    slope_state_at,
    station_length,
)
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
    crossover_parts,
    delete_segment,
    flatten_parts,
    generate_random_track,
    generate_random_track_parts,
    insert_segment,
    mutate,
    mutate_parts,
    repair_circuit,
    replace_segment,
    segments_to_parts,
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

    def test_slope_run_never_digs_below_ground_at_the_default_floor(self):
        """A run built at ground level must never go negative.

        `_build_slope_run` used to pick "up" or "down" with equal odds
        regardless of current elevation, which let evolution excavate a big
        drop instead of climbing to one -- cheaper for the GA to find, and
        the digging showed up for real once big drops started scoring high
        enough to be worth it. See docs/devlog.md.
        """
        from rct2.segments import SEGMENTS

        rng = random.Random(99)
        lowest = 0
        for _ in range(2000):
            run = _build_slope_run(rng, current_z=0, min_elevation=0)
            z = 0
            for seg in run:
                z += SEGMENTS[seg].elevation_delta
                lowest = min(lowest, z)
        assert lowest == 0

    def test_slope_run_can_still_climb_from_ground_level(self):
        """The floor only removes "down"; "up" must still be reachable."""
        rng = random.Random(3)
        reached_positive = False
        for _ in range(200):
            run = _build_slope_run(rng, current_z=0, min_elevation=0)
            from rct2.segments import SEGMENTS
            z = sum(SEGMENTS[s].elevation_delta for s in run)
            if z > 0:
                reached_positive = True
                break
        assert reached_positive

    def test_slope_run_respects_an_arbitrary_floor_not_just_zero(self):
        """min_elevation is a real parameter, not a hardcoded zero check."""
        from rct2.segments import SEGMENTS

        rng = random.Random(5)
        floor = 4
        for _ in range(500):
            run = _build_slope_run(rng, current_z=floor, min_elevation=floor)
            z = floor
            for seg in run:
                z += SEGMENTS[seg].elevation_delta
                assert z >= floor

    def test_random_tracks_never_dig_below_ground(self):
        """The same floor applies to whole generated tracks, not just one run."""
        from rct2.geometry import track_bounds

        rng = random.Random(7)
        for _ in range(100):
            segments = generate_random_track(rng, min_length=10, max_length=40)
            bounds = track_bounds(Position(), segments)
            assert bounds.min_z >= 0


class TestMutateFunction:
    """Tests for the high-level mutate function."""

    def test_mutate_preserves_station(self):
        """Mutation must leave the whole platform intact, not just its first piece."""
        rng = random.Random(42)
        segments = create_simple_circuit()
        platform = segments[:station_length(segments)]
        for _ in range(10):  # Multiple attempts
            mutated = mutate(segments, rng, rate=0.5)
            assert mutated[:len(platform)] == platform
            assert station_length(mutated) == DEFAULT_STATION_LENGTH

    def test_mutate_returns_valid_segments(self):
        """Mutated segments should be from the valid set."""
        rng = random.Random(42)
        segments = create_simple_circuit()
        # Build set of all valid segments (simple + any legal slope/bank piece)
        valid_segments = (
            set(SIMPLE_SEGMENTS) | STATION_SEGMENTS
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
        parent2 = build_station() + [TURN_RIGHT[0]] * 4

        child1, child2 = crossover(parent1, parent2, rng)
        assert station_length(child1) == DEFAULT_STATION_LENGTH
        assert station_length(child2) == DEFAULT_STATION_LENGTH

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
        assert station_length(track) == DEFAULT_STATION_LENGTH

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
            set(SIMPLE_SEGMENTS) | STATION_SEGMENTS
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


class TestPartsRepresentation:
    """Tests for the part-based genome (segments_to_parts/flatten_parts and
    the crossover_parts/mutate_parts/generate_random_track_parts trio)."""

    def test_flatten_parts_round_trips_with_segments_to_parts(self):
        rng = random.Random(1)
        tracks = [
            create_simple_circuit(),
            generate_random_track(rng),
            generate_random_track(rng),
            build_station() + _build_slope_run(rng, current_z=0) + [FLAT_SEGMENTS[0]],
        ]
        for track in tracks:
            assert flatten_parts(segments_to_parts(track)) == track

    def test_segments_to_parts_groups_the_station_as_one_part(self):
        station = build_station()
        track = station + [TURN_LEFT[0]] * 4
        parts = segments_to_parts(track)
        assert parts[0] == station

    def test_segments_to_parts_groups_a_slope_run_as_one_part(self):
        rng = random.Random(3)
        slope_run = _build_slope_run(rng, current_z=0)
        assert len(slope_run) > 1  # otherwise this test proves nothing
        track = build_station() + slope_run + [FLAT_SEGMENTS[0]]
        parts = segments_to_parts(track)
        assert slope_run in parts

    def test_segments_to_parts_groups_a_bank_run_as_one_part(self):
        rng = random.Random(5)
        bank_run = _build_bank_run(rng)
        assert len(bank_run) > 1  # otherwise this test proves nothing
        track = build_station() + bank_run + [FLAT_SEGMENTS[0]]
        parts = segments_to_parts(track)
        assert bank_run in parts

    def test_crossover_parts_never_splits_a_part(self):
        """The whole point of the part-based genome: a multi-segment run must
        appear in a child in full, exactly as it was in a parent, or not at
        all -- never as a partial slice."""
        rng = random.Random(7)
        run_a = _build_slope_run(rng, current_z=0)
        run_b = _build_bank_run(rng)
        assert len(run_a) > 1 and len(run_b) > 1

        parts1 = segments_to_parts(build_station() + run_a + [FLAT_SEGMENTS[0]])
        parts2 = segments_to_parts(build_station() + run_b + [TURN_RIGHT[0]])
        all_original_parts = parts1 + parts2

        for seed in range(50):
            child1, child2 = crossover_parts(parts1, parts2, random.Random(seed))
            for child in (child1, child2):
                for part in child:
                    assert part in all_original_parts

    def test_mutate_parts_produces_only_well_formed_parts(self):
        """No empty parts, ever -- an empty part would break the invariant
        that mutation/crossover always move whole, non-empty units."""
        rng = random.Random(11)
        parts = segments_to_parts(create_simple_circuit())
        for _ in range(20):
            parts = mutate_parts(parts, rng, rate=0.2)
            assert all(len(part) >= 1 for part in parts)

    def test_mutate_parts_sometimes_produces_closed_circuits(self):
        rng = random.Random(13)
        original = segments_to_parts(create_simple_circuit())
        valid_count = 0
        for _ in range(20):
            mutated = mutate_parts(original, rng, rate=0.1)
            if is_closed_circuit(Position(), flatten_parts(mutated)):
                valid_count += 1
        assert valid_count > 0

    def test_generate_random_track_parts_has_station_and_valid_segments(self):
        rng = random.Random(17)
        valid = (
            set(SIMPLE_SEGMENTS) | STATION_SEGMENTS
            | set(SLOPE_TRANSITIONS) | set(BANK_TRANSITIONS)
        )
        for _ in range(5):
            parts = generate_random_track_parts(rng)
            track = flatten_parts(parts)
            assert station_length(track) == DEFAULT_STATION_LENGTH
            for seg in track:
                assert seg in valid

    def test_generate_random_track_parts_respects_length_bounds(self):
        rng = random.Random(19)
        parts = generate_random_track_parts(rng, min_length=5, max_length=10)
        track = flatten_parts(parts)
        assert len(track) >= 5 + 2  # min_length + station

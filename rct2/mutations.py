"""Mutation operators for genetic algorithm track evolution.

Provides mutation operations that modify track segment sequences while
attempting to maintain valid closed circuits.
"""

import random
from typing import Optional

from rct2.construction import (
    BANK_TRANSITIONS,
    SLOPE_TRANSITIONS,
    bank_closing_path,
    bank_state_at,
    legal_bank_segments,
    legal_slope_segments,
    slope_closing_path,
    slope_state_at,
)
from rct2.geometry import (
    Heading,
    Position,
    advance_position,
    is_closed_circuit,
    trace_track,
)
from rct2.segments import SEGMENTS


# Segment categories for smart mutations
FLAT_SEGMENTS = [0x00]
TURN_LEFT_FLAT = [0x10, 0x2A]   # unbanked quarter turns left (5-tile, 3-tile)
TURN_RIGHT_FLAT = [0x11, 0x2B]  # unbanked quarter turns right
BRAKES = [0x63, 0xD8]  # brakes, block brakes

# Simple segments that can be inserted individually (all work on flat track, no banking)
SIMPLE_SEGMENTS = FLAT_SEGMENTS + TURN_LEFT_FLAT + TURN_RIGHT_FLAT + BRAKES

# For backwards compatibility
TURN_LEFT = TURN_LEFT_FLAT
TURN_RIGHT = TURN_RIGHT_FLAT

# Station segments that should not be mutated
BEGIN_STATION = 0x02
END_STATION = 0x01


def insert_segment(segments: list[int], position: int, segment: int) -> list[int]:
    """Insert a segment at the given position.

    Args:
        segments: Current segment list
        position: Index to insert at
        segment: Segment type ID to insert

    Returns:
        New segment list with insertion
    """
    result = segments.copy()
    result.insert(position, segment)
    return result


def delete_segment(segments: list[int], position: int) -> list[int]:
    """Delete the segment at the given position.

    Args:
        segments: Current segment list
        position: Index to delete

    Returns:
        New segment list with deletion
    """
    result = segments.copy()
    del result[position]
    return result


def replace_segment(segments: list[int], position: int, segment: int) -> list[int]:
    """Replace the segment at the given position.

    Args:
        segments: Current segment list
        position: Index to replace
        segment: New segment type ID

    Returns:
        New segment list with replacement
    """
    result = segments.copy()
    result[position] = segment
    return result


def swap_segments(segments: list[int], pos1: int, pos2: int) -> list[int]:
    """Swap two segments in the list.

    Args:
        segments: Current segment list
        pos1: First position
        pos2: Second position

    Returns:
        New segment list with swap
    """
    result = segments.copy()
    result[pos1], result[pos2] = result[pos2], result[pos1]
    return result


def _find_mutable_range(segments: list[int]) -> tuple[int, int]:
    """Find the range of indices that can be mutated (excluding station).

    Returns:
        Tuple of (start_index, end_index) for mutable region
    """
    # Skip BEGIN_STATION and END_STATION at the start
    start = 0
    if len(segments) > 0 and segments[0] == BEGIN_STATION:
        start = 1
    if len(segments) > 1 and segments[1] == END_STATION:
        start = 2
    return start, len(segments)


def _insert_sequence(segments: list[int], position: int, sequence: list[int]) -> list[int]:
    """Insert a sequence of segments at the given position."""
    result = segments.copy()
    for i, seg in enumerate(sequence):
        result.insert(position + i, seg)
    return result


def _build_run(rng: random.Random, legal_fn, closing_fn, excluded: set) -> list[int]:
    """Randomly walk a legality-query state machine from flat back to flat.

    Used to build self-contained slope or bank runs from scratch. Combined
    bank+slope segments (0x18-0x1F) are excluded so slope runs and bank runs
    stay independent; mutating combined bank-slope track is out of scope here.
    """
    state = "flat"
    run: list[int] = []
    for _ in range(rng.randint(1, 4)):
        options = {seg: nxt for seg, nxt in legal_fn(state).items() if seg not in excluded}
        if not options:
            break
        segment = rng.choice(list(options))
        run.append(segment)
        state = options[segment]
        if state == "flat":
            break
    run.extend(closing_fn(state))
    return run


def _build_slope_run(rng: random.Random) -> list[int]:
    """Build a self-contained slope run (starts and ends flat)."""
    return _build_run(rng, legal_slope_segments, slope_closing_path, BANK_TRANSITIONS)


def _build_bank_run(rng: random.Random) -> list[int]:
    """Build a self-contained banked-turn run (starts and ends flat)."""
    return _build_run(rng, legal_bank_segments, bank_closing_path, SLOPE_TRANSITIONS)


def _slope_bump(direction: str) -> list[int]:
    """Smallest legal non-combo bump from flat to `direction` ("up"/"down") and back."""
    entries = {
        seg: nxt for seg, nxt in legal_slope_segments("flat").items()
        if seg not in BANK_TRANSITIONS and nxt == direction
    }
    entry = min(entries)
    return [entry] + slope_closing_path(entries[entry])


def _insert_legal_run_or_continuation(
    segments: list[int],
    position: int,
    rng: random.Random,
    state_fn,
    legal_fn,
    excluded: set,
    build_fn,
) -> list[int]:
    """Insert at `position`, respecting whatever slope/bank state is already there.

    On flat ground, builds a whole new self-contained run. Mid-run, inserts a
    single segment that legally continues from the current state, leaving the
    existing downstream segments to close it as before.
    """
    state = state_fn(segments, position)
    if state == "flat":
        run = build_fn(rng)
        return _insert_sequence(segments, position, run) if run else segments
    options = {seg: nxt for seg, nxt in legal_fn(state).items() if seg not in excluded}
    if not options:
        return segments
    return insert_segment(segments, position, rng.choice(list(options)))


def _is_special_segment(seg_id: int) -> bool:
    """Check if a segment is part of a slope or bank (not safe to delete individually)."""
    return seg_id in SLOPE_TRANSITIONS or seg_id in BANK_TRANSITIONS


def mutate(
    segments: list[int],
    rng: random.Random,
    rate: float = 0.1,
    max_attempts: int = 10,
) -> list[int]:
    """Apply random mutations to a segment list.

    Attempts mutations and returns the result only if it maintains a
    closed circuit. Falls back to the original if all attempts fail.

    Mutations:
    - insert_simple: Add a simple flat segment
    - insert_slope: Add a complete slope sequence
    - insert_banked: Add a complete banked turn sequence
    - delete: Remove a segment (avoids breaking special sequences)
    - replace: Swap one simple segment for another
    - swap: Exchange two simple segments

    Args:
        segments: Current segment list
        rate: Probability of mutation per segment
        max_attempts: Maximum mutation attempts before giving up

    Returns:
        Mutated segment list (or original if mutation fails)
    """
    if len(segments) < 3:
        return segments

    start, end = _find_mutable_range(segments)
    if start >= end:
        return segments

    for _ in range(max_attempts):
        result = segments.copy()

        # Determine number of mutations based on rate
        num_mutations = max(1, int(len(segments) * rate))

        for _ in range(num_mutations):
            mutation_type = rng.choice([
                "insert_simple", "insert_slope", "insert_banked",
                "delete", "replace", "swap"
            ])
            mutable_indices = list(range(start, len(result)))

            if not mutable_indices:
                continue

            if mutation_type == "insert_simple":
                # Insert a single flat-compatible segment
                pos = rng.randint(start, len(result))
                new_seg = rng.choice(SIMPLE_SEGMENTS)
                result = insert_segment(result, pos, new_seg)

            elif mutation_type == "insert_slope":
                # Insert a new hill, or continue one already at this position
                pos = rng.randint(start, len(result))
                result = _insert_legal_run_or_continuation(
                    result, pos, rng,
                    slope_state_at, legal_slope_segments, BANK_TRANSITIONS, _build_slope_run,
                )

            elif mutation_type == "insert_banked":
                # Insert a new banked turn, or continue one already at this position
                pos = rng.randint(start, len(result))
                result = _insert_legal_run_or_continuation(
                    result, pos, rng,
                    bank_state_at, legal_bank_segments, SLOPE_TRANSITIONS, _build_bank_run,
                )

            elif mutation_type == "delete":
                if len(result) > start + 1:  # Keep at least one mutable segment
                    # Find segments safe to delete (not special segments)
                    safe_indices = [i for i in mutable_indices
                                    if not _is_special_segment(result[i])]
                    if safe_indices:
                        pos = rng.choice(safe_indices)
                        result = delete_segment(result, pos)

            elif mutation_type == "replace":
                # Only replace non-special segments with other simple segments
                safe_indices = [i for i in mutable_indices
                                if not _is_special_segment(result[i])]
                if safe_indices:
                    pos = rng.choice(safe_indices)
                    new_seg = rng.choice(SIMPLE_SEGMENTS)
                    result = replace_segment(result, pos, new_seg)

            elif mutation_type == "swap":
                # Only swap non-special segments
                safe_indices = [i for i in mutable_indices
                                if not _is_special_segment(result[i])]
                if len(safe_indices) >= 2:
                    pos1, pos2 = rng.sample(safe_indices, 2)
                    result = swap_segments(result, pos1, pos2)

        # Try to repair if not closed
        repaired = repair_circuit(result, rng)
        if repaired is not None and is_closed_circuit(Position(), repaired):
            return repaired

    return segments  # Return original if all mutations fail


def _calculate_gap(segments: list[int]) -> tuple[int, int, int, int]:
    """Calculate the position/heading gap between track end and start.

    Returns:
        Tuple of (x_gap, y_gap, z_gap, heading_gap)
    """
    positions = trace_track(Position(), segments)
    end = positions[-1]
    start = Position()

    heading_gap = (start.heading - end.heading) % 4
    return end.x - start.x, end.y - start.y, end.z - start.z, heading_gap


def _get_required_heading_to_start(end_pos: Position, start: Position) -> int:
    """Calculate which heading would point from end toward start.

    Returns heading (0=NORTH, 1=EAST, 2=SOUTH, 3=WEST) that points toward start.
    """
    dx = start.x - end_pos.x
    dy = start.y - end_pos.y

    # Determine primary direction needed
    if abs(dy) >= abs(dx):
        # More north/south travel needed
        if dy > 0:
            return 0  # NORTH
        elif dy < 0:
            return 2  # SOUTH
    if dx > 0:
        return 1  # EAST
    elif dx < 0:
        return 3  # WEST
    return end_pos.heading  # Already at target position


def repair_circuit(
    segments: list[int],
    rng: random.Random,
    max_repair_segments: int = 8,
) -> Optional[list[int]]:
    """Attempt to repair an open circuit by inserting corrective segments.

    Strategy:
    1. Calculate position/heading gap between end and start
    2. Turn to face toward start position
    3. Add flats/slopes to close the distance
    4. Fix final heading to match start heading

    Args:
        segments: Track segments to repair
        max_repair_segments: Maximum segments to add for repair

    Returns:
        Repaired segment list, or None if repair fails
    """
    if is_closed_circuit(Position(), segments):
        return segments

    result = segments.copy()
    start = Position()
    segments_added = 0

    for _ in range(max_repair_segments * 2):  # More iterations for complex repairs
        if is_closed_circuit(Position(), result):
            return result

        if segments_added >= max_repair_segments:
            break

        positions = trace_track(Position(), result)
        end = positions[-1]

        # Calculate gaps
        x_gap = end.x - start.x
        y_gap = end.y - start.y
        z_gap = end.z - start.z
        heading_gap = (start.heading - end.heading) % 4

        # If we're at the right position, just fix heading
        if x_gap == 0 and y_gap == 0 and z_gap == 0:
            if heading_gap == 0:
                return result  # Done!
            elif heading_gap == 1 or heading_gap == -3:  # Need right turn
                result.append(rng.choice(TURN_RIGHT))
            elif heading_gap == 3 or heading_gap == -1:  # Need left turn
                result.append(rng.choice(TURN_LEFT))
            else:  # heading_gap == 2
                result.append(rng.choice(TURN_RIGHT))
            segments_added += 1
            continue

        # Fix elevation first if needed - use the smallest legal slope bump
        if z_gap < 0:  # End is below start, need to go up
            bump = _slope_bump("up")
            result.extend(bump)
            segments_added += len(bump)
            continue
        elif z_gap > 0:  # End is above start, need to go down
            bump = _slope_bump("down")
            result.extend(bump)
            segments_added += len(bump)
            continue

        # Determine which direction we should be heading to get to start
        target_heading = _get_required_heading_to_start(end, start)
        turn_needed = (target_heading - end.heading) % 4

        if turn_needed != 0:
            # Need to turn toward start
            if turn_needed == 1:  # Need right turn
                result.append(rng.choice(TURN_RIGHT))
            elif turn_needed == 3:  # Need left turn
                result.append(rng.choice(TURN_LEFT))
            elif turn_needed == 2:  # Need 180
                result.append(rng.choice(TURN_RIGHT))
            segments_added += 1
            continue

        # We're heading toward start, add a flat to get closer
        result.append(FLAT_SEGMENTS[0])
        segments_added += 1

    if is_closed_circuit(Position(), result):
        return result
    return None


def crossover(
    parent1: list[int],
    parent2: list[int],
    rng: random.Random,
) -> tuple[list[int], list[int]]:
    """Single-point crossover between two parent tracks.

    Note: Crossover often breaks circuit closure, so offspring will need
    repair or validation.

    Args:
        parent1: First parent segment list
        parent2: Second parent segment list

    Returns:
        Tuple of two offspring segment lists
    """
    start1, end1 = _find_mutable_range(parent1)
    start2, end2 = _find_mutable_range(parent2)

    if end1 <= start1 or end2 <= start2:
        return parent1.copy(), parent2.copy()

    # Choose crossover points in mutable regions
    point1 = rng.randint(start1, end1 - 1) if end1 > start1 else start1
    point2 = rng.randint(start2, end2 - 1) if end2 > start2 else start2

    # Create offspring
    child1 = parent1[:point1] + parent2[point2:]
    child2 = parent2[:point2] + parent1[point1:]

    return child1, child2


def generate_random_track(
    rng: random.Random,
    min_length: int = 8,
    max_length: int = 30,
) -> list[int]:
    """Generate a random track with station and attempt to close it.

    Uses valid slope and banked sequences to ensure proper transitions.

    Args:
        min_length: Minimum number of segments (excluding station)
        max_length: Maximum number of segments (excluding station)

    Returns:
        Random track segment list (may not be closed)
    """
    target_length = rng.randint(min_length, max_length)

    # Start with station
    segments = [BEGIN_STATION, END_STATION]

    # Add random segments, slope runs, and banked runs
    while len(segments) - 2 < target_length:
        choice = rng.random()
        if choice < 0.25:  # 25% chance for a slope run
            segments.extend(_build_slope_run(rng))
        elif choice < 0.40:  # 15% chance for a banked run
            segments.extend(_build_bank_run(rng))
        else:  # 60% chance for simple segment
            segments.append(rng.choice(SIMPLE_SEGMENTS))

    # Try to repair
    repaired = repair_circuit(segments, rng)
    return repaired if repaired is not None else segments

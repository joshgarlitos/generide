"""Mutation operators for genetic algorithm track evolution.

Provides mutation operations that modify track segment sequences while
attempting to maintain valid closed circuits.
"""

import random
from typing import Optional

from rct2.construction import (
    BANK_TRANSITIONS,
    BEGIN_STATION,
    DEFAULT_STATION_LENGTH,
    END_STATION,
    SLOPE_TRANSITIONS,
    bank_closing_path,
    bank_state_at,
    build_station,
    elevation_at,
    legal_bank_segments,
    legal_slope_segments,
    slope_closing_path,
    slope_state_at,
    station_length,
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

    The whole leading station run is off limits, not just its first two pieces.
    A platform is BEGIN, then middles, then END, and mutating a middle out of
    the middle of it would leave the ride with a shorter platform than asked
    for, or a malformed one.

    Returns:
        Tuple of (start_index, end_index) for mutable region
    """
    start = station_length(segments)
    if start == 0:
        # No well-formed station; fall back to protecting a leading BEGIN piece
        # so a partially built track still keeps its first element.
        start = 1 if segments and segments[0] == BEGIN_STATION else 0
    return start, len(segments)


def _insert_sequence(segments: list[int], position: int, sequence: list[int]) -> list[int]:
    """Insert a sequence of segments at the given position."""
    result = segments.copy()
    for i, seg in enumerate(sequence):
        result.insert(position + i, seg)
    return result


def _build_run(
    rng: random.Random, legal_fn, closing_fn, excluded: set,
    current_z: int = 0, min_elevation: Optional[int] = None,
) -> list[int]:
    """Randomly walk a legality-query state machine from flat back to flat.

    Used to build self-contained slope or bank runs from scratch. Combined
    bank+slope segments (0x18-0x1F) are excluded so slope runs and bank runs
    stay independent; mutating combined bank-slope track is out of scope here.

    `min_elevation` (only meaningful for slope runs; bank runs pass None
    because excluding combined pieces keeps them flat) filters out any option
    that would carry the run below the floor at any step, including the
    closing path. Without this, a "down" pick at ground level is exactly as
    legal as "up", so nothing stops a mutation from excavating a big drop
    instead of climbing to one -- which is cheaper for the GA to discover and
    is what it did once a big drop got scored highly enough to be worth
    pursuing. See docs/devlog.md for the run where that showed up.
    """
    state = "flat"
    run: list[int] = []
    z = current_z
    for _ in range(rng.randint(1, 4)):
        options = {seg: nxt for seg, nxt in legal_fn(state).items() if seg not in excluded}
        if min_elevation is not None:
            options = {
                seg: nxt for seg, nxt in options.items()
                if z + SEGMENTS[seg].elevation_delta >= min_elevation
            }
        if not options:
            break
        segment = rng.choice(list(options))
        run.append(segment)
        z += SEGMENTS[segment].elevation_delta
        state = options[segment]
        if state == "flat":
            break

    closing = closing_fn(state)
    if min_elevation is not None:
        closing_z = z
        for segment in closing:
            closing_z += SEGMENTS[segment].elevation_delta
            if closing_z < min_elevation:
                # The per-step filter above only covers the loop's own
                # committed steps. If the loop ran out of random steps (or
                # picked "flat" state) before the run actually leveled out,
                # the remaining closing segments still have to finish the
                # descent -- and those were never checked. Discard the whole
                # run rather than land it below the floor; the caller treats
                # an empty run as "nothing to insert here."
                return []
    run.extend(closing)
    return run


def _build_slope_run(
    rng: random.Random, current_z: int = 0, min_elevation: Optional[int] = 0,
) -> list[int]:
    """Build a self-contained slope run (starts and ends flat).

    `min_elevation` defaults to ground level, matching `validate_construction`'s
    own default floor, so a run built with the default arguments can never
    dig below where the game would reject the track anyway.
    """
    return _build_run(
        rng, legal_slope_segments, slope_closing_path, BANK_TRANSITIONS,
        current_z=current_z, min_elevation=min_elevation,
    )


def _build_bank_run(
    rng: random.Random, current_z: int = 0, min_elevation: Optional[int] = None,
) -> list[int]:
    """Build a self-contained banked-turn run (starts and ends flat).

    Accepts and ignores `current_z`/`min_elevation` so callers can pass the
    same arguments to either build function without special-casing which one
    they have -- a banked run never changes elevation, since combined
    bank+slope pieces are excluded from it.
    """
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
        run = build_fn(rng, current_z=elevation_at(segments, position), min_elevation=0)
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
    station_tiles: int = DEFAULT_STATION_LENGTH,
) -> list[int]:
    """Generate a random track with station and attempt to close it.

    Uses valid slope and banked sequences to ensure proper transitions.

    Args:
        min_length: Minimum number of segments (excluding station)
        max_length: Maximum number of segments (excluding station)
        station_tiles: Length of the station platform in tiles

    Returns:
        Random track segment list (may not be closed)
    """
    target_length = rng.randint(min_length, max_length)

    # Start with a full station platform
    segments = build_station(station_tiles)

    # Add random segments, slope runs, and banked runs
    while len(segments) - station_tiles < target_length:
        choice = rng.random()
        if choice < 0.25:  # 25% chance for a slope run
            segments.extend(_build_slope_run(rng, current_z=elevation_at(segments)))
        elif choice < 0.40:  # 15% chance for a banked run
            segments.extend(_build_bank_run(rng))
        else:  # 60% chance for simple segment
            segments.append(rng.choice(SIMPLE_SEGMENTS))

    # Try to repair
    repaired = repair_circuit(segments, rng)
    return repaired if repaired is not None else segments


# ---------------------------------------------------------------------------
# Part-based representation.
#
# Crossover above cuts at an arbitrary segment index, which can (and does)
# slice a slope run or banked turn in half. A "part" is either one simple
# piece or one whole pre-built run (station, slope run, bank run); the
# functions below operate on lists of parts instead of individual segments,
# so a run can never be split apart by crossover or picked at piece by piece
# by mutation. They sit alongside the flat-list functions above rather than
# replacing them, so the existing GA stays available as an unmodified
# baseline -- see docs/research-plan.md and rct2/benchmark.py's "ga_parts".
# ---------------------------------------------------------------------------


def _group_runs(segments: list[int]) -> list[list[int]]:
    """Group a flat (post-station) list into parts.

    A maximal run of consecutive segments in SLOPE_TRANSITIONS or
    BANK_TRANSITIONS becomes one part (this can fuse an adjacent bank run and
    slope run into a single part if nothing simple separates them -- still
    safe for crossover, since the fused blob is still never split, but it
    means a multi-segment part can't always be labeled "slope" or "bank").
    Everything else is its own single-segment part.
    """
    parts: list[list[int]] = []
    run: list[int] = []
    for seg in segments:
        if _is_special_segment(seg):
            run.append(seg)
            continue
        if run:
            parts.append(run)
            run = []
        parts.append([seg])
    if run:
        parts.append(run)
    return parts


def segments_to_parts(segments: list[int]) -> list[list[int]]:
    """Group a flat segment list into parts, with the station as part 0.

    Mirrors `_find_mutable_range`'s station detection exactly, including its
    fallback for a track that opens with BEGIN_STATION but has no
    well-formed platform.
    """
    station_len = station_length(segments)
    if station_len == 0 and segments and segments[0] == BEGIN_STATION:
        station_len = 1
    if station_len == 0:
        return _group_runs(segments)
    return [segments[:station_len]] + _group_runs(segments[station_len:])


def flatten_parts(parts: list[list[int]]) -> list[int]:
    """Flatten a parts list back into the plain segment list every other
    function in the project (fitness, construction, td6 export) expects."""
    return [seg for part in parts for seg in part]


def generate_random_track_parts(
    rng: random.Random,
    min_length: int = 8,
    max_length: int = 30,
    station_tiles: int = DEFAULT_STATION_LENGTH,
) -> list[list[int]]:
    """Part-based counterpart to `generate_random_track`.

    Builds the same mix of station, slope runs, bank runs, and single simple
    segments with the same probabilities, but keeps each one as its own part
    instead of flattening into one list.
    """
    target_length = rng.randint(min_length, max_length)
    parts: list[list[int]] = [build_station(station_tiles)]
    length = 0

    while length < target_length:
        choice = rng.random()
        if choice < 0.25:  # 25% chance for a slope run
            run = _build_slope_run(rng, current_z=elevation_at(flatten_parts(parts)))
            if not run:
                continue
            parts.append(run)
            length += len(run)
        elif choice < 0.40:  # 15% chance for a banked run
            run = _build_bank_run(rng)
            if not run:
                continue
            parts.append(run)
            length += len(run)
        else:  # 60% chance for simple segment
            parts.append([rng.choice(SIMPLE_SEGMENTS)])
            length += 1

    # repair_circuit only ever appends, never touches the existing prefix, so
    # regrouping just the new tail (rather than the whole flattened result)
    # keeps every part boundary already established above untouched and
    # correctly keeps a repair-added slope bump atomic instead of scattering
    # it into single-segment parts.
    flat_before = flatten_parts(parts)
    repaired = repair_circuit(flat_before, rng)
    if repaired is None:
        return parts
    tail = repaired[len(flat_before):]
    return parts + _group_runs(tail) if tail else parts


def mutate_parts(
    parts: list[list[int]],
    rng: random.Random,
    rate: float = 0.1,
    max_attempts: int = 10,
) -> list[list[int]]:
    """Part-based counterpart to `mutate`.

    The same six mutation types, but operating on whole parts: a slope run
    or banked turn is inserted, deleted, replaced, or swapped as one unit,
    never picked apart segment by segment. Assumes part 0 is the station
    (callers should run the seed through `segments_to_parts` after
    `_ensure_station`, never the other way around).
    """
    if not parts:
        return parts

    for _ in range(max_attempts):
        result = [part.copy() for part in parts]
        num_mutations = max(1, int(len(parts) * rate))

        for _ in range(num_mutations):
            mutation_type = rng.choice([
                "insert_simple", "insert_slope", "insert_banked",
                "delete", "replace", "swap",
            ])
            mutable_indices = list(range(1, len(result)))

            if mutation_type == "insert_simple":
                pos = rng.randint(1, len(result))
                result.insert(pos, [rng.choice(SIMPLE_SEGMENTS)])

            elif mutation_type == "insert_slope":
                pos = rng.randint(1, len(result))
                run = _build_slope_run(rng, current_z=elevation_at(flatten_parts(result[:pos])))
                if run:
                    result.insert(pos, run)

            elif mutation_type == "insert_banked":
                pos = rng.randint(1, len(result))
                run = _build_bank_run(rng)
                if run:
                    result.insert(pos, run)

            elif mutation_type == "delete":
                if mutable_indices:
                    del result[rng.choice(mutable_indices)]

            elif mutation_type == "replace":
                if mutable_indices:
                    pos = rng.choice(mutable_indices)
                    if len(result[pos]) == 1:
                        result[pos] = [rng.choice(SIMPLE_SEGMENTS)]
                    else:
                        # A multi-segment part might be a slope run, a bank
                        # run, or (see _group_runs) both fused together, so
                        # there's no single "kind" to preserve -- pick fresh,
                        # same as insert_slope/insert_banked do.
                        current_z = elevation_at(flatten_parts(result[:pos]))
                        builder = rng.choice([_build_slope_run, _build_bank_run])
                        new_run = builder(rng, current_z=current_z)
                        if new_run:
                            result[pos] = new_run

            elif mutation_type == "swap":
                if len(mutable_indices) >= 2:
                    pos1, pos2 = rng.sample(mutable_indices, 2)
                    result[pos1], result[pos2] = result[pos2], result[pos1]

        flat_before = flatten_parts(result)
        repaired = repair_circuit(flat_before, rng)
        if repaired is not None and is_closed_circuit(Position(), repaired):
            tail = repaired[len(flat_before):]
            return result + _group_runs(tail) if tail else result

    return parts  # Return original if all mutations fail


def crossover_parts(
    parts1: list[list[int]],
    parts2: list[list[int]],
    rng: random.Random,
) -> tuple[list[list[int]], list[list[int]]]:
    """Part-based counterpart to `crossover`.

    Cuts only ever land on a part boundary, so a slope run or banked turn
    can never be split between the two children -- the flat version's bug.
    Part 0 (the station) is always protected since the cut point is chosen
    from index 1 onward.
    """
    point1 = rng.randint(1, len(parts1))
    point2 = rng.randint(1, len(parts2))
    child1 = parts1[:point1] + parts2[point2:]
    child2 = parts2[:point2] + parts1[point1:]
    return child1, child2

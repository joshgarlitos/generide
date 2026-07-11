"""Fitness functions for evaluating coaster tracks.

Provides pluggable fitness evaluation for the genetic algorithm.
ProxyFitness scores tracks based on geometric properties without
running the game.
"""

from typing import Optional, Protocol, Set, Tuple

from rct2.geometry import Position, is_closed_circuit, occupied_tiles, overlapping_tiles, track_bounds
from rct2.segments import SEGMENTS


# Slope state tracking for transition validation
SLOPE_TRANSITIONS = {
    # segment_id: (required_slope_state, resulting_slope_state)
    # slope_state: 'flat', 'up', 'down'
    0x04: ('up', 'up'),           # 25_deg_up - must be on upslope, stays up
    0x05: ('steep_up', 'steep_up'),  # 60_deg_up
    0x06: ('flat', 'up'),         # flat_to_25_deg_up - starts upslope
    0x07: ('up', 'steep_up'),     # 25_deg_up_to_60_deg_up
    0x08: ('steep_up', 'up'),     # 60_deg_up_to_25_deg_up
    0x09: ('up', 'flat'),         # 25_deg_up_to_flat - ends upslope
    0x0A: ('down', 'down'),       # 25_deg_down
    0x0B: ('steep_down', 'steep_down'),  # 60_deg_down
    0x0C: ('flat', 'down'),       # flat_to_25_deg_down
    0x0D: ('down', 'steep_down'), # 25_deg_down_to_60_deg_down
    0x0E: ('steep_down', 'down'), # 60_deg_down_to_25_deg_down
    0x0F: ('down', 'flat'),       # 25_deg_down_to_flat
}

# Segments that require flat slope state
FLAT_ONLY_SEGMENTS = {
    0x00,  # flat
    0x10, 0x11,  # quarter turns 5
    0x2A, 0x2B,  # quarter turns 3
    0x16, 0x17,  # banked quarter turns 5
    0x2C, 0x2D,  # banked quarter turns 3
    0x12, 0x13, 0x14, 0x15,  # bank transitions
    0x20, 0x21,  # banked
    0x63, 0xD8,  # brakes
    0x01, 0x02, 0x03,  # stations
}

# Bank state tracking for transition validation
# segment_id: (required_bank_state, resulting_bank_state)
# bank_state: 'flat', 'left', 'right'
BANK_TRANSITIONS = {
    0x12: ('flat', 'left'),      # flat_to_left_bank
    0x13: ('flat', 'right'),     # flat_to_right_bank
    0x14: ('left', 'flat'),      # left_bank_to_flat
    0x15: ('right', 'flat'),     # right_bank_to_flat
    0x20: ('left', 'left'),      # left_bank (maintains)
    0x21: ('right', 'right'),    # right_bank (maintains)
    0x16: ('left', 'left'),      # banked_left_quarter_turn_5_tiles
    0x17: ('right', 'right'),    # banked_right_quarter_turn_5_tiles
    0x2C: ('left', 'left'),      # banked_left_quarter_turn_3_tiles
    0x2D: ('right', 'right'),    # banked_right_quarter_turn_3_tiles
    # Bank-to-slope transitions
    0x18: ('left', 'flat'),      # left_bank_to_25_deg_up (ends bank, starts slope)
    0x19: ('right', 'flat'),     # right_bank_to_25_deg_up
    0x1A: ('flat', 'left'),      # 25_deg_up_to_left_bank (ends slope, starts bank)
    0x1B: ('flat', 'right'),     # 25_deg_up_to_right_bank
    0x1C: ('left', 'flat'),      # left_bank_to_25_deg_down
    0x1D: ('right', 'flat'),     # right_bank_to_25_deg_down
    0x1E: ('flat', 'left'),      # 25_deg_down_to_left_bank
    0x1F: ('flat', 'right'),     # 25_deg_down_to_right_bank
}

# Segments that require flat bank state (no banking)
FLAT_BANK_SEGMENTS = {
    0x00,  # flat
    0x10, 0x11,  # quarter turns 5 (unbanked)
    0x2A, 0x2B,  # quarter turns 3 (unbanked)
    0x04, 0x05, 0x06, 0x07, 0x08, 0x09,  # up slopes
    0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,  # down slopes
    0x63, 0xD8,  # brakes
    0x01, 0x02, 0x03,  # stations
}


def count_slope_violations(segments: list[int]) -> int:
    """Count invalid slope transitions in a segment sequence."""
    violations = 0
    slope_state = 'flat'

    for seg_id in segments:
        if seg_id in SLOPE_TRANSITIONS:
            required, resulting = SLOPE_TRANSITIONS[seg_id]
            if slope_state != required:
                violations += 1
            slope_state = resulting
        elif seg_id in FLAT_ONLY_SEGMENTS:
            if slope_state != 'flat':
                violations += 1
            slope_state = 'flat'
        # Unknown segments - assume they work in any state

    return violations


def count_bank_violations(segments: list[int]) -> int:
    """Count invalid bank transitions in a segment sequence.

    Tracks banking state (flat, left, right) and penalizes:
    - Banked segments when track is not banked
    - Flat segments when track is banked (without transition)
    - Left bank segments when track is right-banked (and vice versa)
    """
    violations = 0
    bank_state = 'flat'

    for seg_id in segments:
        if seg_id in BANK_TRANSITIONS:
            required, resulting = BANK_TRANSITIONS[seg_id]
            if bank_state != required:
                violations += 1
            bank_state = resulting
        elif seg_id in FLAT_BANK_SEGMENTS:
            if bank_state != 'flat':
                violations += 1
            bank_state = 'flat'
        # Unknown segments - assume they work in any bank state

    return violations


# Segments that can have chain lift (upward slopes)
CHAIN_LIFT_SEGMENTS = {
    0x04,  # 25_deg_up
    0x05,  # 60_deg_up
    0x06,  # flat_to_25_deg_up
    0x07,  # 25_deg_up_to_60_deg_up
    0x08,  # 60_deg_up_to_25_deg_up
    0x09,  # 25_deg_up_to_flat
}

# Friction loss per segment (in elevation units) - rough estimate
FRICTION_PER_SEGMENT = 0.1


def find_first_hill(segments: list[int]) -> Optional[Tuple[int, int]]:
    """Find the start and end indices of the first uphill sequence.

    Returns:
        Tuple of (start_index, end_index) or None if no hill found.
    """
    start = None
    for i, seg_id in enumerate(segments):
        if seg_id in CHAIN_LIFT_SEGMENTS:
            if start is None:
                start = i
        elif start is not None:
            # End of first hill
            return (start, i)

    if start is not None:
        return (start, len(segments))
    return None


def check_first_hill_has_lift(segments: list[int], lift_indices: set[int]) -> bool:
    """Check if the first hill has chain lift enabled."""
    first_hill = find_first_hill(segments)
    if first_hill is None:
        return True  # No hill, no problem

    start, end = first_hill
    # At least one segment in the first hill should have lift
    for i in range(start, end):
        if i in lift_indices:
            return True
    return False


def estimate_energy_violations(
    segments: list[int],
    lift_indices: Optional[Set[int]] = None,
) -> Tuple[int, bool]:
    """Estimate energy-related track violations.

    Tracks elevation through the circuit and checks if the train would
    have enough energy to complete each section.

    Args:
        segments: List of segment type IDs
        lift_indices: Set of segment indices that have chain lift.
                     If None, assumes first hill has lift.

    Returns:
        Tuple of (violation_count, first_hill_has_lift)
    """
    if lift_indices is None:
        # Default: assume first hill has chain lift
        first_hill = find_first_hill(segments)
        if first_hill:
            lift_indices = set(range(first_hill[0], first_hill[1]))
        else:
            lift_indices = set()

    violations = 0
    current_elevation = 0
    max_elevation_with_lift = 0  # Highest point reached with chain assist
    segments_since_lift = 0

    for i, seg_id in enumerate(segments):
        # Get elevation change for this segment
        if seg_id in SEGMENTS:
            elevation_delta = SEGMENTS[seg_id].elevation_delta
        else:
            elevation_delta = 0

        current_elevation += elevation_delta

        if i in lift_indices:
            # Chain lift - we can reach this height "for free"
            max_elevation_with_lift = max(max_elevation_with_lift, current_elevation)
            segments_since_lift = 0
        else:
            segments_since_lift += 1

            # Calculate available energy (max height minus friction losses)
            friction_loss = segments_since_lift * FRICTION_PER_SEGMENT
            available_height = max_elevation_with_lift - friction_loss

            # If current elevation exceeds available energy, we'd valley
            if current_elevation > available_height + 0.5:  # Small buffer
                violations += 1

    first_hill_ok = check_first_hill_has_lift(segments, lift_indices)

    return violations, first_hill_ok


class FitnessFunction(Protocol):
    """Protocol for fitness evaluation functions."""

    def evaluate(self, segments: list[int]) -> float:
        """Evaluate fitness of a track segment sequence.

        Args:
            segments: List of segment type IDs (excluding station)

        Returns:
            Fitness score (higher is better)
        """
        ...


# Segment categories for fitness analysis
FLAT_SEGMENTS = {0x00}
TURN_LEFT = {0x10, 0x2A, 0x16, 0x2C}  # quarter turns left
TURN_RIGHT = {0x11, 0x2B, 0x17, 0x2D}  # quarter turns right
SLOPE_UP = {0x06, 0x04, 0x09, 0x07, 0x08}  # flat→up, up, up→flat, transitions
SLOPE_DOWN = {0x0C, 0x0A, 0x0F, 0x0D, 0x0E}  # flat→down, down, down→flat
BRAKES = {0x63, 0xD8}  # brakes, block brakes
BANKED = {0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x20, 0x21, 0x2C, 0x2D}


def count_elevation_changes(segments: list[int]) -> int:
    """Count number of segments that change elevation."""
    count = 0
    for seg_id in segments:
        if seg_id in SEGMENTS:
            segment = SEGMENTS[seg_id]
            if segment.elevation_delta != 0:
                count += 1
    return count


def count_turns(segments: list[int], direction: str = "left") -> int:
    """Count number of turns in a given direction."""
    turn_set = TURN_LEFT if direction == "left" else TURN_RIGHT
    return sum(1 for seg_id in segments if seg_id in turn_set)


def count_segment_variety(segments: list[int]) -> int:
    """Count unique segment types used."""
    return len(set(segments))


class ProxyFitness:
    """Scores tracks based on geometric properties without running the game.

    Rewards:
    - Track length (up to a point)
    - Elevation changes (hills make coasters exciting)
    - Balanced turns (left and right)
    - Segment variety (using different piece types)

    Penalties:
    - Open circuits (track must close)
    - Excessive footprint (track too large)
    - Too short (boring rides)
    """

    def __init__(
        self,
        max_width: int = 30,
        max_depth: int = 30,
        ideal_length: int = 50,
    ) -> None:
        self.max_width = max_width
        self.max_depth = max_depth
        self.ideal_length = ideal_length

    def evaluate(self, segments: list[int]) -> float:
        """Evaluate fitness of a track segment sequence.

        Args:
            segments: List of segment type IDs

        Returns:
            Fitness score (higher is better)
        """
        score = 0.0

        # Length: reward longer tracks up to ideal, slight penalty beyond
        length = len(segments)
        if length <= self.ideal_length:
            score += length * 2
        else:
            score += self.ideal_length * 2
            score -= (length - self.ideal_length) * 0.5

        # Elevation changes: reward hills
        elevation_changes = count_elevation_changes(segments)
        score += elevation_changes * 5

        # Turns: reward balanced turns (both directions)
        left_turns = count_turns(segments, direction="left")
        right_turns = count_turns(segments, direction="right")
        score += min(left_turns, right_turns) * 3

        # Variety: unique segment types used
        unique_segments = count_segment_variety(segments)
        score += unique_segments * 2

        # Penalties
        if not is_closed_circuit(Position(), segments):
            score -= 10000  # Heavy penalty for open circuits

        bounds = track_bounds(Position(), segments)
        if bounds.width > self.max_width or bounds.depth > self.max_depth:
            excess_width = max(0, bounds.width - self.max_width)
            excess_depth = max(0, bounds.depth - self.max_depth)
            score -= (excess_width + excess_depth) * 10

        # Penalty for collisions (self-intersection)
        tiles = occupied_tiles(Position(), segments)
        overlaps = overlapping_tiles(tiles)
        score -= len(overlaps) * 50  # Heavy penalty per collision

        # Penalty for going below ground
        if bounds.min_z < 0:
            score -= abs(bounds.min_z) * 20

        # Penalty for invalid slope transitions
        slope_violations = count_slope_violations(segments)
        score -= slope_violations * 100  # Heavy penalty - these cause build errors

        # Penalty for invalid bank transitions
        bank_violations = count_bank_violations(segments)
        score -= bank_violations * 100  # Heavy penalty - these cause build errors

        # Penalty for energy/physics violations
        energy_violations, first_hill_ok = estimate_energy_violations(segments)
        score -= energy_violations * 50  # Penalty for potential valleys
        if not first_hill_ok:
            score -= 200  # First hill must have chain lift

        # Penalty for too short
        if length < 8:
            score -= (8 - length) * 20

        return score


class WeightedProxyFitness:
    """Proxy fitness with configurable weights for experimentation."""

    def __init__(
        self,
        length_weight: float = 2.0,
        elevation_weight: float = 5.0,
        turn_balance_weight: float = 3.0,
        variety_weight: float = 2.0,
        open_circuit_penalty: float = 10000.0,
        bounds_penalty_per_tile: float = 10.0,
        short_penalty_per_segment: float = 20.0,
        max_width: int = 30,
        max_depth: int = 30,
        ideal_length: int = 50,
        min_length: int = 8,
    ) -> None:
        self.length_weight = length_weight
        self.elevation_weight = elevation_weight
        self.turn_balance_weight = turn_balance_weight
        self.variety_weight = variety_weight
        self.open_circuit_penalty = open_circuit_penalty
        self.bounds_penalty_per_tile = bounds_penalty_per_tile
        self.short_penalty_per_segment = short_penalty_per_segment
        self.max_width = max_width
        self.max_depth = max_depth
        self.ideal_length = ideal_length
        self.min_length = min_length

    def evaluate(self, segments: list[int]) -> float:
        """Evaluate fitness with configurable weights."""
        score = 0.0
        length = len(segments)

        # Length score
        if length <= self.ideal_length:
            score += length * self.length_weight
        else:
            score += self.ideal_length * self.length_weight
            score -= (length - self.ideal_length) * (self.length_weight / 4)

        # Elevation changes
        score += count_elevation_changes(segments) * self.elevation_weight

        # Turn balance
        left_turns = count_turns(segments, direction="left")
        right_turns = count_turns(segments, direction="right")
        score += min(left_turns, right_turns) * self.turn_balance_weight

        # Variety
        score += count_segment_variety(segments) * self.variety_weight

        # Penalties
        if not is_closed_circuit(Position(), segments):
            score -= self.open_circuit_penalty

        bounds = track_bounds(Position(), segments)
        if bounds.width > self.max_width or bounds.depth > self.max_depth:
            excess = max(0, bounds.width - self.max_width)
            excess += max(0, bounds.depth - self.max_depth)
            score -= excess * self.bounds_penalty_per_tile

        if length < self.min_length:
            score -= (self.min_length - length) * self.short_penalty_per_segment

        return score

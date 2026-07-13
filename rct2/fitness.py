"""Fitness functions for evaluating coaster tracks.

Provides pluggable fitness evaluation for the genetic algorithm.
ProxyFitness scores tracks based on geometric properties without
running the game.
"""

from typing import Optional, Protocol, Set, Tuple

from rct2 import construction
from rct2.geometry import Position, is_closed_circuit, occupied_tiles, overlapping_tiles, track_bounds
from rct2.segments import SEGMENTS


def count_slope_violations(segments: list[int]) -> int:
    """Count invalid slope transitions in a segment sequence."""
    return construction.count_slope_violations(segments)


def count_bank_violations(segments: list[int]) -> int:
    """Count invalid bank transitions in a segment sequence.

    Tracks banking state (flat, left, right) and penalizes:
    - Banked segments when track is not banked
    - Flat segments when track is banked (without transition)
    - Left bank segments when track is right-banked (and vice versa)
    """
    return construction.count_bank_violations(segments)


def find_first_hill(segments: list[int]) -> Optional[Tuple[int, int]]:
    """Find the start and end indices of the first uphill sequence.

    Returns:
        Tuple of (start_index, end_index) or None if no hill found.
    """
    return construction.find_first_hill(segments)


def check_first_hill_has_lift(segments: list[int], lift_indices: set[int]) -> bool:
    """Check if the first hill has chain lift enabled."""
    return construction.check_first_hill_has_lift(segments, lift_indices)


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
    return construction.estimate_energy_violations(segments, lift_indices)


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
        construction_result = construction.validate_construction(
            segments,
            max_width=self.max_width,
            max_depth=self.max_depth,
        )
        if not construction_result.valid:
            score -= 10000

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

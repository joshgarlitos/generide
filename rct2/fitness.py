"""Fitness functions for evaluating coaster tracks.

Provides pluggable fitness evaluation for the genetic algorithm.
ProxyFitness scores tracks based on geometric properties without
running the game.
"""

from dataclasses import dataclass
from typing import Optional, Protocol, Set, Tuple

from rct2 import construction, physics
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


class WeightedProxyFitness:
    """Proxy fitness with every reward and penalty exposed as a weight.

    This is the whole proxy scoring implementation. `ProxyFitness` is this
    class with the tuned default weights, so anything measured here transfers
    directly to the default the CLI and the GA use. There is deliberately no
    second copy of the scoring rules: an earlier version of this class scored
    geometry only and silently skipped every construction-validity penalty,
    which meant weights tuned here produced tracks the game would reject.

    Rewards track length (up to `ideal_length`), elevation changes, balanced
    left/right turns, and segment variety. Penalizes construction invalidity,
    open circuits, excessive footprint, collisions, going below ground, illegal
    slope and bank transitions, energy shortfalls, a first hill with no chain
    lift, stalling before the circuit closes, and being too short.

    Scoring stays physics-free: the stall penalty comes from
    `construction.energy_stall_index`, a cheap screen, not from
    `rct2.physics.simulate`. That keeps this a genuine proxy and keeps it
    comparable against PhysicsFitness.
    """

    def __init__(
        self,
        # Footprint and length configuration
        max_width: int = 30,
        max_depth: int = 30,
        ideal_length: int = 50,
        min_length: int = 8,
        # Rewards
        length_weight: float = 2.0,
        over_length_penalty: float = 0.5,
        elevation_weight: float = 5.0,
        turn_balance_weight: float = 3.0,
        variety_weight: float = 2.0,
        # Penalties
        invalid_construction_penalty: float = 10000.0,
        open_circuit_penalty: float = 10000.0,
        bounds_penalty_per_tile: float = 10.0,
        collision_penalty_per_tile: float = 50.0,
        underground_penalty_per_unit: float = 20.0,
        slope_violation_penalty: float = 100.0,
        bank_violation_penalty: float = 100.0,
        energy_violation_penalty: float = 50.0,
        missing_lift_penalty: float = 200.0,
        stall_penalty: float = 500.0,
        short_penalty_per_segment: float = 20.0,
    ) -> None:
        self.max_width = max_width
        self.max_depth = max_depth
        self.ideal_length = ideal_length
        self.min_length = min_length
        self.length_weight = length_weight
        self.over_length_penalty = over_length_penalty
        self.elevation_weight = elevation_weight
        self.turn_balance_weight = turn_balance_weight
        self.variety_weight = variety_weight
        self.invalid_construction_penalty = invalid_construction_penalty
        self.open_circuit_penalty = open_circuit_penalty
        self.bounds_penalty_per_tile = bounds_penalty_per_tile
        self.collision_penalty_per_tile = collision_penalty_per_tile
        self.underground_penalty_per_unit = underground_penalty_per_unit
        self.slope_violation_penalty = slope_violation_penalty
        self.bank_violation_penalty = bank_violation_penalty
        self.energy_violation_penalty = energy_violation_penalty
        self.missing_lift_penalty = missing_lift_penalty
        self.stall_penalty = stall_penalty
        self.short_penalty_per_segment = short_penalty_per_segment

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
            score -= self.invalid_construction_penalty

        # Length: reward longer tracks up to ideal, slight penalty beyond
        length = len(segments)
        if length <= self.ideal_length:
            score += length * self.length_weight
        else:
            score += self.ideal_length * self.length_weight
            score -= (length - self.ideal_length) * self.over_length_penalty

        # Elevation changes: reward hills
        elevation_changes = count_elevation_changes(segments)
        score += elevation_changes * self.elevation_weight

        # Turns: reward balanced turns (both directions)
        left_turns = count_turns(segments, direction="left")
        right_turns = count_turns(segments, direction="right")
        score += min(left_turns, right_turns) * self.turn_balance_weight

        # Variety: unique segment types used
        unique_segments = count_segment_variety(segments)
        score += unique_segments * self.variety_weight

        # Penalties
        if not is_closed_circuit(Position(), segments):
            score -= self.open_circuit_penalty  # Heavy penalty for open circuits

        bounds = track_bounds(Position(), segments)
        if bounds.width > self.max_width or bounds.depth > self.max_depth:
            excess_width = max(0, bounds.width - self.max_width)
            excess_depth = max(0, bounds.depth - self.max_depth)
            score -= (excess_width + excess_depth) * self.bounds_penalty_per_tile

        # Penalty for collisions (self-intersection)
        tiles = occupied_tiles(Position(), segments)
        overlaps = overlapping_tiles(tiles)
        score -= len(overlaps) * self.collision_penalty_per_tile

        # Penalty for going below ground
        if bounds.min_z < 0:
            score -= abs(bounds.min_z) * self.underground_penalty_per_unit

        # Penalty for invalid slope transitions
        slope_violations = count_slope_violations(segments)
        score -= slope_violations * self.slope_violation_penalty

        # Penalty for invalid bank transitions
        bank_violations = count_bank_violations(segments)
        score -= bank_violations * self.bank_violation_penalty

        # Penalty for energy/physics violations
        energy_violations, first_hill_ok = estimate_energy_violations(segments)
        score -= energy_violations * self.energy_violation_penalty
        if not first_hill_ok:
            score -= self.missing_lift_penalty  # First hill must have chain lift

        # Penalty for stalling. Graded by how far the train got, so evolution
        # has a gradient toward completing the circuit instead of a cliff --
        # the same shape PhysicsFitness uses for its stall penalty.
        # Reuse the lift set validate_construction already resolved rather than
        # walking for the first hill again; this runs on every individual.
        stall_index = construction.energy_stall_index(
            segments, construction_result.lift_indices
        )
        if stall_index is not None:
            progress = stall_index / max(1, len(segments))
            score -= self.stall_penalty * (1.0 - progress)

        # Penalty for too short
        if length < self.min_length:
            score -= (self.min_length - length) * self.short_penalty_per_segment

        return score


class ProxyFitness(WeightedProxyFitness):
    """Scores tracks based on geometric properties without running the game.

    The default proxy fitness, used by the CLI and by `evolve()` when no
    fitness function is given. This is `WeightedProxyFitness` with its tuned
    default weights and nothing else; see that class for what is scored and
    for the knobs to turn when experimenting.
    """

    def __init__(
        self,
        max_width: int = 30,
        max_depth: int = 30,
        ideal_length: int = 50,
        stall_penalty: float = 500.0,
    ) -> None:
        super().__init__(
            max_width=max_width,
            max_depth=max_depth,
            ideal_length=ideal_length,
            stall_penalty=stall_penalty,
        )


@dataclass
class RatingTargets:
    """Optional (min, max) windows for each ride rating.

    A None window means that rating is unconstrained.
    """

    excitement: Optional[Tuple[float, float]] = None
    intensity: Optional[Tuple[float, float]] = None
    nausea: Optional[Tuple[float, float]] = None


def _window_distance(value: float, window: Optional[Tuple[float, float]]) -> float:
    """Linear distance outside a (min, max) window; 0 when inside or unset."""
    if window is None:
        return 0.0
    low, high = window
    if value < low:
        return low - value
    if value > high:
        return value - high
    return 0.0


class PhysicsFitness:
    """Scores tracks by simulated ride physics and approximate ratings.

    Runs the physics walk from rct2.physics over each candidate, rates the
    resulting stats, and scores either open-ended excitement (default) or
    distance from requested rating windows. Construction violations and
    stalls are penalized with a gradient so evolution can climb out of them.
    """

    def __init__(
        self,
        targets: Optional[RatingTargets] = None,
        validity_weight: float = 50.0,
        target_weight: float = 20.0,
        open_circuit_penalty: float = 10000.0,
        intensity_ceiling: float = 9.0,
        nausea_ceiling: float = 7.0,
        max_width: int = 30,
        max_depth: int = 30,
    ) -> None:
        self.targets = targets
        self.validity_weight = validity_weight
        self.target_weight = target_weight
        self.open_circuit_penalty = open_circuit_penalty
        self.intensity_ceiling = intensity_ceiling
        self.nausea_ceiling = nausea_ceiling
        self.max_width = max_width
        self.max_depth = max_depth

    def evaluate(self, segments: list[int]) -> float:
        score = 0.0

        result = construction.validate_construction(
            segments,
            max_width=self.max_width,
            max_depth=self.max_depth,
        )
        score -= self.validity_weight * len(result.issues)

        # An open circuit is categorically different from the other issues, so
        # it does not ride on validity_weight with everything else. The train
        # would run off the end of the track; there is no ride to rate.
        #
        # It needs its own heavy penalty because the stall check below cannot
        # catch it. `simulate` walks the segment list once and reports
        # `completed` when the train reaches the end without stalling, and a
        # short open stub does exactly that — the station drives it the whole
        # way. So a station plus four flats scores better than a real closed
        # circuit, which pays for real hills and real g-forces. Weighting this
        # like a routine issue let the GA converge on stubs, and the longer the
        # station the worse it got, since more of the track was powered.
        if not is_closed_circuit(Position(), segments):
            score -= self.open_circuit_penalty

        stats = physics.simulate(segments, lift_indices=set(result.lift_indices))
        if not stats.completed:
            # Graded stall penalty: stalling later is better than stalling
            # early, so the GA has a gradient toward completing the circuit.
            progress = (stats.stall_index or 0) / max(1, len(segments))
            score -= self.validity_weight * 4 * (1.0 - progress)

        ratings = physics.rate(stats)
        if self.targets is None:
            score += ratings.excitement * 10
            # Steer away from rides too punishing to be worth riding. This is a
            # preference, so it lives here rather than inside `physics.rate`,
            # which predicts what the game would say and nothing more. The
            # thresholds are on the calibrated rating scale, where a real
            # Mine Train sits near 6.5 intensity and the worst shipped designs
            # reach the low 9s, so these only bite on genuinely extreme tracks
            # rather than firing constantly the way the old uncalibrated
            # intensity did.
            score -= max(0.0, ratings.intensity - self.intensity_ceiling) * 5
            score -= max(0.0, ratings.nausea - self.nausea_ceiling) * 5
        else:
            score += ratings.excitement  # mild tiebreaker inside windows
            score -= self.target_weight * _window_distance(
                ratings.excitement, self.targets.excitement
            )
            score -= self.target_weight * _window_distance(
                ratings.intensity, self.targets.intensity
            )
            score -= self.target_weight * _window_distance(
                ratings.nausea, self.targets.nausea
            )

        return score

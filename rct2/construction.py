"""Construction rules shared by generation, fitness, and evolution.

Buildability versus completability
----------------------------------
`validate_construction` answers "would the game reject this track?" It does not
answer "would a train get around it?" Those are different questions, and this
module deliberately only owns the first.

`create_simple_circuit()` is the proof: a flat, liftless 8-segment loop that
OpenRCT2 will happily let you build, and that no train can run. It is valid
here, and `rct2.physics.simulate` reports it stalling at segment 5. Both are
right. Folding a stall check into `.valid` would make the project's own seed
track invalid and start every evolution run from an illegal individual.

So completability lives in `energy_stall_index` below, outside `.valid`, for
callers that must stay physics-free. `rct2.physics.simulate` remains the
authority; `energy_stall_index` is a cheap conservative screen that agrees with
it on where a train dies. `physics` imports this module, so the dependency
cannot run the other way — `tests/test_construction.py` pins the shared
constants against `physics` instead, so the two models cannot drift apart
silently.
"""

from dataclasses import dataclass
from typing import Optional, Set, Tuple

from rct2.geometry import Position, ValidationIssue, ValidationResult, validate_track
from rct2.segments import SEGMENTS


SLOPE_TRANSITIONS = {
    0x04: ("up", "up"), 0x05: ("steep_up", "steep_up"),
    0x06: ("flat", "up"), 0x07: ("up", "steep_up"),
    0x08: ("steep_up", "up"), 0x09: ("up", "flat"),
    0x0A: ("down", "down"), 0x0B: ("steep_down", "steep_down"),
    0x0C: ("flat", "down"), 0x0D: ("down", "steep_down"),
    0x0E: ("steep_down", "down"), 0x0F: ("down", "flat"),
    0x18: ("flat", "up"), 0x19: ("flat", "up"),
    0x1A: ("up", "flat"), 0x1B: ("up", "flat"),
    0x1C: ("flat", "down"), 0x1D: ("flat", "down"),
    0x1E: ("down", "flat"), 0x1F: ("down", "flat"),
    0x22: ("up", "up"), 0x23: ("up", "up"),
    0x24: ("down", "down"), 0x25: ("down", "down"),
}

FLAT_ONLY_SEGMENTS = {
    0x00, 0x10, 0x11, 0x2A, 0x2B, 0x16, 0x17, 0x2C, 0x2D,
    0x12, 0x13, 0x14, 0x15, 0x20, 0x21, 0x63, 0xD8,
    0x5A, 0x5E, 0x01, 0x02, 0x03,
}

BANK_TRANSITIONS = {
    0x12: ("flat", "left"), 0x13: ("flat", "right"),
    0x14: ("left", "flat"), 0x15: ("right", "flat"),
    0x20: ("left", "left"), 0x21: ("right", "right"),
    0x16: ("left", "left"), 0x17: ("right", "right"),
    0x2C: ("left", "left"), 0x2D: ("right", "right"),
    0x18: ("left", "flat"), 0x19: ("right", "flat"),
    0x1A: ("flat", "left"), 0x1B: ("flat", "right"),
    0x1C: ("left", "flat"), 0x1D: ("right", "flat"),
    0x1E: ("flat", "left"), 0x1F: ("flat", "right"),
}

FLAT_BANK_SEGMENTS = {
    0x00, 0x10, 0x11, 0x2A, 0x2B,
    0x04, 0x05, 0x06, 0x07, 0x08, 0x09,
    0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
    0x63, 0xD8, 0x01, 0x02, 0x03,
}

CHAIN_LIFT_SEGMENTS = {0x04, 0x05, 0x06, 0x07, 0x08, 0x09}
FRICTION_PER_SEGMENT = 0.1

# Station pieces drive the train, exactly as a chain lift does.
STATION_SEGMENTS = {0x01, 0x02, 0x03}

# Kinetic energy expressed as head (height the train could still climb), in
# RCT2 height units. Derived from physics.py: v^2 / 2g, converted out of meters
# by HEIGHT_UNIT_M. A train leaves the station or the lift at LIFT_SPEED_MS and
# is considered stalled below MIN_SPEED_MS.
LIFT_HEAD = 0.329  # physics.LIFT_SPEED_MS -> head
STALL_HEAD = 0.068  # physics.MIN_SPEED_MS -> head


@dataclass(frozen=True)
class ConstructionResult:
    issues: tuple[ValidationIssue, ...]
    geometry: ValidationResult
    lift_indices: frozenset[int]

    @property
    def valid(self) -> bool:
        return not self.issues

    def count(self, code: str) -> int:
        return sum(issue.code == code for issue in self.issues)


def _step_slope(state: str, segment: int) -> Tuple[str, Optional[str]]:
    """Advance slope state by one segment.

    Returns (resulting_state, required_state) where required_state is None
    when the segment is unconstrained by slope (state passes through unchanged).
    """
    if segment in SLOPE_TRANSITIONS:
        required, resulting = SLOPE_TRANSITIONS[segment]
        return resulting, required
    if segment in FLAT_ONLY_SEGMENTS:
        return "flat", "flat"
    return state, None


def _step_bank(state: str, segment: int) -> Tuple[str, Optional[str]]:
    """Advance bank state by one segment.

    Returns (resulting_state, required_state) where required_state is None
    when the segment is unconstrained by banking (state passes through unchanged).
    """
    if segment in BANK_TRANSITIONS:
        required, resulting = BANK_TRANSITIONS[segment]
        return resulting, required
    if segment in FLAT_BANK_SEGMENTS:
        return "flat", "flat"
    return state, None


def slope_state_at(segments: list[int], position: Optional[int] = None) -> str:
    """Slope state after replaying segments[:position] (or the full list)."""
    state = "flat"
    for segment in segments[:position]:
        state, _ = _step_slope(state, segment)
    return state


def bank_state_at(segments: list[int], position: Optional[int] = None) -> str:
    """Bank state after replaying segments[:position] (or the full list)."""
    state = "flat"
    for segment in segments[:position]:
        state, _ = _step_bank(state, segment)
    return state


def legal_slope_segments(state: str) -> dict[int, str]:
    """Segments that can legally follow the given slope state, mapped to the
    resulting state each would produce."""
    return {
        segment: resulting
        for segment, (required, resulting) in SLOPE_TRANSITIONS.items()
        if required == state
    }


def legal_bank_segments(state: str) -> dict[int, str]:
    """Segments that can legally follow the given bank state, mapped to the
    resulting state each would produce."""
    return {
        segment: resulting
        for segment, (required, resulting) in BANK_TRANSITIONS.items()
        if required == state
    }


def _closing_path(state: str, legal_fn, excluded: Set[int]) -> list[int]:
    """Shortest sequence of non-excluded segments back to 'flat', via BFS."""
    if state == "flat":
        return []
    frontier = [(state, [])]
    visited = {state}
    while frontier:
        current_state, path = frontier.pop(0)
        for segment, resulting in legal_fn(current_state).items():
            if segment in excluded:
                continue
            next_path = path + [segment]
            if resulting == "flat":
                return next_path
            if resulting not in visited:
                visited.add(resulting)
                frontier.append((resulting, next_path))
    return []


def slope_closing_path(state: str) -> list[int]:
    """Shortest sequence of non-combo slope segments back to flat."""
    return _closing_path(state, legal_slope_segments, set(BANK_TRANSITIONS))


def bank_closing_path(state: str) -> list[int]:
    """Shortest sequence of non-combo bank segments back to flat."""
    return _closing_path(state, legal_bank_segments, set(SLOPE_TRANSITIONS))


def _slope_issues(segments: list[int]) -> list[ValidationIssue]:
    issues = []
    state = "flat"
    for index, segment in enumerate(segments):
        resulting, required = _step_slope(state, segment)
        if required is not None and state != required:
            reason = "flat track" if required == "flat" else f"slope {required}"
            issues.append(ValidationIssue(
                "slope_transition",
                f"segment {index} (0x{segment:02X}) requires {reason}, found {state}",
            ))
        state = resulting
    if state != "flat":
        issues.append(ValidationIssue(
            "slope_transition",
            f"track reconnects to the station with slope state {state}",
        ))
    return issues


def _bank_issues(segments: list[int]) -> list[ValidationIssue]:
    issues = []
    state = "flat"
    for index, segment in enumerate(segments):
        resulting, required = _step_bank(state, segment)
        if required is not None and state != required:
            reason = "unbanked track" if required == "flat" else f"bank {required}"
            issues.append(ValidationIssue(
                "bank_transition",
                f"segment {index} (0x{segment:02X}) requires {reason}, found {state}",
            ))
        state = resulting
    if state != "flat":
        issues.append(ValidationIssue(
            "bank_transition",
            f"track reconnects to the station with bank state {state}",
        ))
    return issues


def find_first_hill(segments: list[int]) -> Optional[Tuple[int, int]]:
    start = None
    for index, segment in enumerate(segments):
        if segment in CHAIN_LIFT_SEGMENTS:
            if start is None:
                start = index
        elif start is not None:
            return start, index
    return (start, len(segments)) if start is not None else None


def default_lift_indices(segments: list[int]) -> set[int]:
    first_hill = find_first_hill(segments)
    if first_hill is None:
        return set()
    return set(range(first_hill[0], first_hill[1]))


def check_first_hill_has_lift(segments: list[int], lift_indices: set[int]) -> bool:
    first_hill = find_first_hill(segments)
    if first_hill is None:
        return True
    start, end = first_hill
    return any(index in lift_indices for index in range(start, end))


def _energy_issues(segments: list[int], lift_indices: set[int]) -> list[ValidationIssue]:
    """Segments that climb higher than the lift could ever carry the train.

    This is the reachable-height check only. `available` floors at zero on
    purpose: that floor is what keeps this scoped to climbs, so a track sitting
    at or below the datum is never flagged here no matter how much friction has
    accumulated. Running out of speed on the flat is a different failure, and
    `energy_stall_index` owns it — see the module docstring.
    """
    issues = []
    elevation = 0
    powered_height = 0
    segments_since_lift = 0
    for index, segment in enumerate(segments):
        elevation += SEGMENTS.get(segment, SEGMENTS[0x00]).elevation_delta
        if index in lift_indices:
            powered_height = max(powered_height, elevation)
            segments_since_lift = 0
            continue
        segments_since_lift += 1
        available = max(0.0, powered_height - segments_since_lift * FRICTION_PER_SEGMENT)
        if elevation > available + 0.5:
            issues.append(ValidationIssue(
                "energy_shortfall",
                f"segment {index} reaches elevation {elevation:.1f} with only "
                f"{available:.1f} estimated energy available",
            ))
    return issues


def energy_stall_index(
    segments: list[int],
    lift_indices: Optional[Set[int]] = None,
) -> Optional[int]:
    """Index of the first segment where the train would run out of speed.

    Tracks the train's kinetic energy as head — the height it could still climb
    — in RCT2 height units. Climbing spends head, descending returns it, and
    every unpowered segment pays FRICTION_PER_SEGMENT. Chain lift and station
    pieces drive the train, so they restore head instead of spending it. The
    train stalls once head falls below STALL_HEAD.

    Unlike `_energy_issues`, nothing floors the budget at zero, so this catches
    a train dying on flat ground from accumulated friction as well as one that
    fails to crest a hill.

    This is a screen, not an adjudicator, and it is deliberately not part of
    `validate_construction` — a stalling track is still buildable. Callers that
    can afford the real simulation should use `rct2.physics.simulate`, whose
    per-segment arc lengths make it strictly more accurate than the flat
    per-segment friction charged here.

    Returns:
        The index of the first stalling segment, or None if the train gets
        all the way around.
    """
    resolved = default_lift_indices(segments) if lift_indices is None else set(lift_indices)
    head = LIFT_HEAD
    for index, segment in enumerate(segments):
        if index in resolved or segment in STATION_SEGMENTS:
            head = max(head, LIFT_HEAD)
            continue
        head -= SEGMENTS.get(segment, SEGMENTS[0x00]).elevation_delta
        head -= FRICTION_PER_SEGMENT
        if head < STALL_HEAD:
            return index
    return None


def count_slope_violations(segments: list[int]) -> int:
    return len(_slope_issues(segments))


def count_bank_violations(segments: list[int]) -> int:
    return len(_bank_issues(segments))


def estimate_energy_violations(
    segments: list[int],
    lift_indices: Optional[Set[int]] = None,
) -> Tuple[int, bool]:
    resolved = default_lift_indices(segments) if lift_indices is None else set(lift_indices)
    return len(_energy_issues(segments, resolved)), check_first_hill_has_lift(segments, resolved)


def validate_construction(
    segments: list[int],
    *,
    lift_indices: Optional[Set[int]] = None,
    max_width: Optional[int] = None,
    max_depth: Optional[int] = None,
    max_height: Optional[int] = None,
    min_elevation: int = 0,
) -> ConstructionResult:
    geometry = validate_track(
        Position(), segments,
        max_width=max_width,
        max_depth=max_depth,
        max_height=max_height,
        min_elevation=min_elevation,
    )
    resolved = default_lift_indices(segments) if lift_indices is None else set(lift_indices)
    issues = list(geometry.issues)
    issues.extend(_slope_issues(segments))
    issues.extend(_bank_issues(segments))
    if not check_first_hill_has_lift(segments, resolved):
        issues.append(ValidationIssue("missing_chain_lift", "the first uphill section has no chain lift"))
    issues.extend(_energy_issues(segments, resolved))
    return ConstructionResult(tuple(issues), geometry, frozenset(resolved))

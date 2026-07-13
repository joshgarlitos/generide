"""Construction rules shared by generation, fitness, and evolution."""

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


def _slope_issues(segments: list[int]) -> list[ValidationIssue]:
    issues = []
    state = "flat"
    for index, segment in enumerate(segments):
        if segment in SLOPE_TRANSITIONS:
            required, resulting = SLOPE_TRANSITIONS[segment]
            if state != required:
                issues.append(ValidationIssue(
                    "slope_transition",
                    f"segment {index} (0x{segment:02X}) requires slope {required}, found {state}",
                ))
            state = resulting
        elif segment in FLAT_ONLY_SEGMENTS:
            if state != "flat":
                issues.append(ValidationIssue(
                    "slope_transition",
                    f"segment {index} (0x{segment:02X}) requires flat track, found {state}",
                ))
            state = "flat"
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
        if segment in BANK_TRANSITIONS:
            required, resulting = BANK_TRANSITIONS[segment]
            if state != required:
                issues.append(ValidationIssue(
                    "bank_transition",
                    f"segment {index} (0x{segment:02X}) requires bank {required}, found {state}",
                ))
            state = resulting
        elif segment in FLAT_BANK_SEGMENTS:
            if state != "flat":
                issues.append(ValidationIssue(
                    "bank_transition",
                    f"segment {index} (0x{segment:02X}) requires unbanked track, found {state}",
                ))
            state = "flat"
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

"""A site: the space in a park a ride has to fit, and the check that it does.

A site says which tiles are usable and which are blocked, how high the ground
is on each, and where the ride's first station piece goes (the anchor). The
generator evolves a ride relative to its own start, so the check maps the
ride's tiles onto the site through the anchor and one of four headings, and
`best_fit` tries all four and reports the best.

Coordinates: `x` is the column and `y` the row of the site, so `rows[y][x]` is
a tile. Heights are absolute and in the same units as track height, and the
ride's start sits at the anchor tile's ground height, so a track tile is below
ground when the anchor's height plus the track's own height is under the
ground at that tile.

This is the one answer to "does it fit", the way `construction` is the one
answer to "can it be built". It checks tiles only. Station flatness, the path
to the entrance and clearance above ground are not checked.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from rct2 import construction
from rct2.generate import calculate_entrance_positions
from rct2.geometry import _AXES, Heading, Position, occupied_tiles

SITE_VERSION = 1
MAX_SITE_SIDE = 200
USABLE = "."
BLOCKED = "#"

# Compass order, which is also how a tie between headings is broken.
HEADINGS: Tuple[Heading, ...] = (Heading.NORTH, Heading.EAST, Heading.SOUTH, Heading.WEST)


class SiteError(ValueError):
    """A site file or description that cannot be used."""


def _is_whole(value: Any) -> bool:
    """A whole number as JSON writes it: an int, but not a bool, a float or text."""
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class Site:
    rows: Tuple[str, ...]
    anchor: Tuple[int, int]
    heights: Tuple[Tuple[int, ...], ...]

    @property
    def width(self) -> int:
        return len(self.rows[0])

    @property
    def depth(self) -> int:
        return len(self.rows)

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[str],
        anchor: Tuple[int, int],
        heights: Optional[Sequence[Sequence[int]]] = None,
    ) -> "Site":
        rows = tuple(rows)
        if not rows:
            raise SiteError("A site needs at least one row.")
        width = len(rows[0])
        if width == 0 or any(len(row) != width for row in rows):
            raise SiteError("Every row of a site must be the same length, and not empty.")
        if width > MAX_SITE_SIDE or len(rows) > MAX_SITE_SIDE:
            raise SiteError(f"A site can be at most {MAX_SITE_SIDE} tiles on a side.")
        for row in rows:
            if any(ch not in (USABLE, BLOCKED) for ch in row):
                raise SiteError(f"Site rows may only contain '{USABLE}' or '{BLOCKED}'.")

        if heights is None:
            grid = tuple(tuple(0 for _ in range(width)) for _ in rows)
        else:
            if len(heights) != len(rows) or any(len(r) != width for r in heights):
                raise SiteError("The heights must be a grid the same size as the rows.")
            if not all(_is_whole(h) for r in heights for h in r):
                raise SiteError("The heights must be whole numbers.")
            grid = tuple(tuple(r) for r in heights)

        if not (isinstance(anchor, (list, tuple)) and len(anchor) == 2
                and all(_is_whole(v) for v in anchor)):
            raise SiteError("The anchor must be two whole numbers, x then y.")
        ax, ay = anchor
        if not (0 <= ax < width and 0 <= ay < len(rows)):
            raise SiteError("The anchor must be a tile inside the site.")
        return cls(rows=rows, anchor=(ax, ay), heights=grid)

    @classmethod
    def from_dict(cls, data: Any) -> "Site":
        if not isinstance(data, dict):
            raise SiteError("A site file must hold one JSON object.")
        if data.get("version", SITE_VERSION) != SITE_VERSION:
            raise SiteError(f"Unsupported site version {data.get('version')!r}.")
        if "anchor" not in data:
            raise SiteError("A site needs an anchor tile.")
        rows = data.get("rows")
        if not isinstance(rows, list) or not all(isinstance(r, str) for r in rows):
            raise SiteError("A site needs a list of text rows.")
        return cls.from_rows(rows, anchor=data["anchor"], heights=data.get("heights"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": SITE_VERSION,
            "anchor": list(self.anchor),
            "rows": list(self.rows),
            "heights": [list(r) for r in self.heights],
        }

    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Site":
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise SiteError(f"The site file could not be read: {exc.strerror or exc}.") from None
        try:
            data = json.loads(text)
        except ValueError:
            raise SiteError("The site file is not valid JSON.") from None
        return cls.from_dict(data)

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.depth

    def blocked(self, x: int, y: int) -> bool:
        return self.rows[y][x] == BLOCKED

    def ground(self, x: int, y: int) -> int:
        return self.heights[y][x]


@dataclass(frozen=True)
class SiteFit:
    """How a ride sits on a site at one heading."""

    heading: Heading
    outside: int
    blocked: int
    below_ground: int

    @property
    def total(self) -> int:
        return self.outside + self.blocked + self.below_ground

    @property
    def fits(self) -> bool:
        return self.total == 0


def site_coords(anchor: Tuple[int, int], heading: Heading, x: int, y: int) -> Tuple[int, int]:
    """Where a ride tile `(x, y)` lands on the site: `x` is to the right of the ride, `y` ahead."""
    forward_x, forward_y, right_x, right_y = _AXES[heading]
    return (
        anchor[0] + x * right_x + y * forward_x,
        anchor[1] + x * right_y + y * forward_y,
    )


def _entrance_side(segments: List[int]) -> Optional[int]:
    """Which side of the station the exported ride puts its entrance and exit on.

    +1 is to the right of the ride, -1 to the left. The export picks the side
    from track geometry alone (`generate.calculate_entrance_positions`), so the
    check scores that side, not the better of the two: a ride must not be
    reported as fitting while its entrance lands on a blocked tile.
    """
    if not construction.station_length(segments):
        return None
    entrance, _ = calculate_entrance_positions(segments)
    return entrance.x // 32


def _entrance_violations(
    site: Site, heading: Heading, side: int, length: int
) -> Tuple[int, int]:
    """Outside and blocked counts for the entrance and exit tiles on one side of the station."""
    outside = blocked = 0
    for y in (0, length - 1):
        wx, wy = site_coords(site.anchor, heading, side, y)
        if not site.inside(wx, wy):
            outside += 1
        elif site.blocked(wx, wy):
            blocked += 1
    return outside, blocked


def _footprint(segments: List[int]) -> List[Tuple[int, int, int]]:
    """The ride's tiles as (x, y, z), built once however many headings are tried."""
    return [(t.x, t.y, t.z) for t in occupied_tiles(Position(), segments)]


def _fit_tiles(
    site: Site,
    tiles: Sequence[Tuple[int, int, int]],
    station: int,
    side: Optional[int],
    heading: Heading,
) -> SiteFit:
    """Count where a ride's tiles break the site when it faces `heading`.

    The inline mapping below is `site_coords` unrolled for speed; a test pins
    the two together.
    """
    forward_x, forward_y, right_x, right_y = _AXES[heading]
    anchor_x, anchor_y = site.anchor
    width, depth = site.width, site.depth
    anchor_ground = site.heights[anchor_y][anchor_x]

    outside_tiles = set()
    blocked_tiles = set()
    below_ground = 0
    for x, y, z in tiles:
        wx = anchor_x + x * right_x + y * forward_x
        wy = anchor_y + x * right_y + y * forward_y
        if not (0 <= wx < width and 0 <= wy < depth):
            outside_tiles.add((wx, wy))
        elif site.rows[wy][wx] == BLOCKED:
            blocked_tiles.add((wx, wy))
        elif anchor_ground + z < site.heights[wy][wx]:
            below_ground += 1

    outside, blocked = len(outside_tiles), len(blocked_tiles)
    if side is not None:
        entrance_outside, entrance_blocked = _entrance_violations(site, heading, side, station)
        outside += entrance_outside
        blocked += entrance_blocked

    return SiteFit(heading=heading, outside=outside, blocked=blocked, below_ground=below_ground)


def fit_at(site: Site, segments: Iterable[int], heading: Heading) -> SiteFit:
    """Count where a ride's tiles break the site when it faces `heading`."""
    segments = list(segments)
    return _fit_tiles(
        site, _footprint(segments), construction.station_length(segments),
        _entrance_side(segments), heading,
    )


def best_fit(site: Site, segments: Iterable[int]) -> SiteFit:
    """The fit at whichever of the four headings breaks the site least.

    A tie goes to the first of north, east, south, west, so once a heading
    fits exactly, the rest cannot beat it and are skipped. This runs on every
    individual in a search, so the ride's tiles and entrance side are found once.
    """
    segments = list(segments)
    tiles = _footprint(segments)
    station = construction.station_length(segments)
    side = _entrance_side(segments)
    best = None
    for heading in HEADINGS:
        fit = _fit_tiles(site, tiles, station, side, heading)
        if best is None or fit.total < best.total:
            best = fit
        if best.total == 0:
            break
    return best


def site_penalty(fit: SiteFit, per_tile: float, cap_per_kind: float) -> float:
    """A graded penalty for a fit, each kind of violation capped separately.

    Graded so evolution has something to climb on a tight site, and capped so a
    hard site cannot keep rewarding ever-longer rides that try to dodge it.
    """
    return sum(
        min(count * per_tile, cap_per_kind)
        for count in (fit.outside, fit.blocked, fit.below_ground)
    )

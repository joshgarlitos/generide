"""SVG renderers for tracks and evolution runs.

The only way to see a generated track used to be loading it in OpenRCT2,
which is a slow loop for a question as simple as "did the hill survive?".
These produce a plan view and a fitness curve from data we already have, so
a run can be looked at without the game.

SVG rather than a raster format because it stays sharp in the devlog and the
web UI at any size. Every picture paints its own dark background, like the
ride graphs in RollerCoaster Tycoon 2, so it reads the same on a light page,
a dark page, and GitHub, and needs no stylesheet to follow a theme. The
colours are the chart colours in `docs/design/README.md`.
"""

import math
from dataclasses import dataclass
from typing import AbstractSet, Iterable, List, NamedTuple, Optional, Sequence, Tuple

from rct2.construction import STATION_SEGMENTS
from rct2.geometry import OccupiedTile, Position, occupied_tiles, track_bounds
from rct2.physics import HEIGHT_UNIT_M, MPH_PER_MS, trace
from rct2.trackpath import PiecePath, Point, track_path

# The chart colours from docs/design/README.md, as the game's palette values
# that rct2/webui_static/tokens.css names. Written straight onto each element
# as presentation attributes, because GitHub strips <style> out of SVGs.
# Kept as one block so a change to the design system is one edit rather than
# a hunt through string literals.
GRAPH = {
    "bg": "#233333",        # --graph-bg (grey step 1)
    "text": "#eff3f3",      # grey step 11
    "text_sec": "#b7c3c3",  # --graph-axis (grey step 9)
    "border": "#3f5353",    # --graph-grid (grey step 3)
    "score": "#8bdf73",     # --trace-score (green step 9)
    "speed": "#ffe72f",     # --trace-speed (yellow step 8)
    "height": "#afdbc3",    # --trace-height (dark green step 10)
    "lift": "#77bbef",      # --trace-lift (light blue step 8)
    "stall": "#eb9f9f",     # --trace-stall (bordeaux step 10)
    "start": "#ffe72f",     # the station marker on the plan
}
# The brown ramp, steps 4 to 11: low ground is dark, high ground is light.
ELEVATION = ["#6b5333", "#7b674b", "#8f7f6b", "#a3937f",
             "#bbab93", "#cfc3ab", "#e7dbc3", "#fff3df"]
FONT = "Verdana,Tahoma,'DejaVu Sans','Segoe UI',sans-serif"

ELEVATION_BANDS = len(ELEVATION)


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _elevation_band(z: int, min_z: int, max_z: int) -> int:
    """Which of the eight colour bands an elevation falls in.

    Banded rather than a continuous gradient because the colours come from
    the game's palette, which has fixed steps. Eight bands is enough to read
    a hill's shape and few enough that each stays distinguishable from its
    neighbours.
    """
    if max_z <= min_z:
        return ELEVATION_BANDS - 1
    span = max_z - min_z
    band = ((z - min_z) * (ELEVATION_BANDS - 1)) // span
    return max(0, min(ELEVATION_BANDS - 1, band))


@dataclass(frozen=True)
class TrackPlan:
    """What the plan view draws, separated from how it is drawn.

    Keeping this apart from the SVG string makes the layout testable
    without parsing markup, and leaves room for another output format
    later without touching the geometry.
    """

    tiles: list[OccupiedTile]
    min_x: int
    max_x: int
    min_y: int
    max_y: int
    min_z: int
    max_z: int

    @property
    def width_tiles(self) -> int:
        return self.max_x - self.min_x + 1

    @property
    def depth_tiles(self) -> int:
        return self.max_y - self.min_y + 1


def plan_track(segments: Sequence[int], start: Optional[Position] = None) -> TrackPlan:
    """Collect the tiles a track occupies, with the extent needed to lay them out.

    Where a track crosses over itself the same tile appears more than once at
    different heights. The highest wins when drawing, so a crossing reads as
    the bridge it is rather than the tunnel underneath.
    """
    start = start if start is not None else Position()
    tiles = list(occupied_tiles(start, segments))
    if not tiles:
        return TrackPlan(tiles=[], min_x=0, max_x=0, min_y=0, max_y=0, min_z=0, max_z=0)

    bounds = track_bounds(start, segments)
    return TrackPlan(
        tiles=tiles,
        min_x=bounds.min_x, max_x=bounds.max_x,
        min_y=bounds.min_y, max_y=bounds.max_y,
        min_z=bounds.min_z, max_z=bounds.max_z,
    )


def render_track(
    segments: Sequence[int],
    start: Optional[Position] = None,
    title: str = "Track plan",
    tile_px: int = 12,
) -> str:
    """Top-down plan of a track, each tile shaded by its height.

    Reads like a blueprint: lighter tiles are higher ground. The first tile
    carries a marker, because a plan view with no orientation is a shape
    rather than a ride, and knowing where the station is makes the rest
    legible.
    """
    plan = plan_track(segments, start)
    if not plan.tiles:
        return _empty_svg(title, "no tiles: the track is empty")

    pad = 24
    label_h = 46
    grid_w = plan.width_tiles * tile_px
    h = plan.depth_tiles * tile_px + pad * 2 + label_h

    # Highest tile wins per (x, y), so a crossing draws as the bridge.
    top: dict[tuple[int, int], OccupiedTile] = {}
    for tile in plan.tiles:
        key = (tile.x, tile.y)
        if key not in top or tile.z > top[key].z:
            top[key] = tile

    def screen(tx: int, ty: int) -> tuple[int, int]:
        # SVG y grows downward and our tracer's y grows north, so the row is
        # flipped to keep north at the top of the page.
        sx = pad + (tx - plan.min_x) * tile_px
        sy = pad + label_h + (plan.max_y - ty) * tile_px
        return sx, sy

    rects = []
    for (tx, ty), tile in sorted(top.items()):
        sx, sy = screen(tx, ty)
        band = _elevation_band(tile.z, plan.min_z, plan.max_z)
        rects.append(
            f'<rect class="e{band} gap" x="{sx}" y="{sy}" '
            f'width="{tile_px}" height="{tile_px}" '
            f'fill="{ELEVATION[band]}" stroke="{GRAPH["bg"]}" stroke-width="0.5"/>'
        )

    first = plan.tiles[0]
    fx, fy = screen(first.x, first.y)
    marker = (
        f'<rect class="ac" x="{fx}" y="{fy}" width="{tile_px}" height="{tile_px}" '
        f'fill="none" stroke="{GRAPH["start"]}" stroke-width="2"/>'
    )

    footprint = f"{plan.width_tiles} x {plan.depth_tiles} tiles"
    relief = f"{plan.max_z - plan.min_z} height units"
    subtitle = f"{len(segments)} segments, {footprint}, {relief} of relief"

    # A narrow track would otherwise crop its own heading, since the width
    # came only from the tile grid. Roughly 6.2px per character at 11px.
    text_w = int(max(len(title) * 8.4, len(subtitle) * 6.2))
    w = max(grid_w, text_w) + pad * 2

    return f"""<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" \
style="width:100%;font-family:{FONT};background:{GRAPH["bg"]};">
  <title>{_escape(title)}</title>
  <desc>Top-down plan of a roller coaster track. Each square is one occupied \
tile, shaded from dark brown (lowest) to pale sand (highest). {_escape(subtitle)}</desc>
  <rect class="bg" x="0" y="0" width="{w}" height="{h}" fill="{GRAPH["bg"]}"/>
  <text class="tx" x="{pad}" y="26" font-size="14" font-weight="600" \
fill="{GRAPH["text"]}">{_escape(title)}</text>
  <text class="ts" x="{pad}" y="44" font-size="11" fill="{GRAPH["text_sec"]}">\
{_escape(subtitle)}</text>
{chr(10).join("  " + r for r in rects)}
  {marker}
</svg>
"""


def render_fitness_history(
    fitness_history: Sequence[float],
    valid_ratio_history: Optional[Sequence[float]] = None,
    title: str = "Fitness by generation",
) -> str:
    """The best fitness per generation, with the share of valid tracks behind it.

    Fitness alone hides the failure worth catching. A run whose fitness sits
    flat while its valid share collapses is not converging, it is running out
    of buildable candidates, and the two lines together say which happened.
    """
    if not fitness_history:
        return _empty_svg(title, "no generations recorded")

    w, h = 640, 300
    left, right, top_pad, bottom = 56, 52, 52, 44
    plot_w = w - left - right
    plot_h = h - top_pad - bottom

    lo, hi = min(fitness_history), max(fitness_history)
    span = hi - lo
    if span <= 0:
        # A run that never improved is a flat line, not a divide by zero.
        lo, hi, span = lo - 1.0, hi + 1.0, 2.0

    def point(i: int, value: float, series_lo: float, series_span: float) -> tuple[float, float]:
        x = left + (plot_w * i / max(1, len(fitness_history) - 1))
        y = top_pad + plot_h - (plot_h * (value - series_lo) / series_span)
        return round(x, 1), round(y, 1)

    fitness_path = " ".join(
        f"{'M' if i == 0 else 'L'}{x},{y}"
        for i, (x, y) in enumerate(
            point(i, v, lo, span) for i, v in enumerate(fitness_history)
        )
    )

    valid_layer = ""
    if valid_ratio_history:
        valid_path = " ".join(
            f"{'M' if i == 0 else 'L'}{x},{y}"
            for i, (x, y) in enumerate(
                point(i, v, 0.0, 1.0) for i, v in enumerate(valid_ratio_history)
            )
        )
        valid_layer = (
            f'<path class="acs" d="{valid_path}" fill="none" stroke="{GRAPH["text_sec"]}" '
            f'stroke-width="1" stroke-dasharray="3 3"/>\n  '
            f'<text class="ts" x="{w - right + 6}" y="{top_pad + 4}" font-size="10" '
            f'fill="{GRAPH["text_sec"]}">100%</text>\n  '
            f'<text class="ts" x="{w - right + 6}" y="{top_pad + plot_h}" font-size="10" '
            f'fill="{GRAPH["text_sec"]}">0%</text>\n  '
            f'<text class="ts" x="{w - right + 6}" y="{top_pad + plot_h + 18}" font-size="10" '
            f'fill="{GRAPH["text_sec"]}">valid</text>'
        )

    generations = len(fitness_history)
    subtitle = f"{generations} generations, best {hi:.2f}"

    return f"""<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" \
style="width:100%;font-family:{FONT};background:{GRAPH["bg"]};">
  <title>{_escape(title)}</title>
  <desc>Line chart of best fitness per generation over {generations} generations, \
peaking at {hi:.2f}. A dashed line shows the share of the population that was \
buildable.</desc>
  <rect class="bg" x="0" y="0" width="{w}" height="{h}" fill="{GRAPH["bg"]}"/>
  <text class="tx" x="{left}" y="26" font-size="14" font-weight="600" fill="{GRAPH["text"]}">\
{_escape(title)}</text>
  <text class="ts" x="{left}" y="44" font-size="11" fill="{GRAPH["text_sec"]}">{_escape(subtitle)}</text>
  <line class="ax" x1="{left}" y1="{top_pad}" x2="{left}" y2="{top_pad + plot_h}" \
stroke="{GRAPH["border"]}" stroke-width="1"/>
  <line class="ax" x1="{left}" y1="{top_pad + plot_h}" x2="{left + plot_w}" y2="{top_pad + plot_h}" \
stroke="{GRAPH["border"]}" stroke-width="1"/>
  <text class="ts" x="{left - 8}" y="{top_pad + 4}" text-anchor="end" font-size="10" \
fill="{GRAPH["text_sec"]}">{hi:.2f}</text>
  <text class="ts" x="{left - 8}" y="{top_pad + plot_h}" text-anchor="end" font-size="10" \
fill="{GRAPH["text_sec"]}">{lo:.2f}</text>
  <text class="ts" x="{left}" y="{h - 16}" font-size="10" fill="{GRAPH["text_sec"]}">0</text>
  <text class="ts" x="{left + plot_w}" y="{h - 16}" text-anchor="end" font-size="10" \
fill="{GRAPH["text_sec"]}">{generations - 1}</text>
  <text class="ts" x="{left + plot_w / 2}" y="{h - 16}" text-anchor="middle" font-size="10" \
fill="{GRAPH["text_sec"]}">generation</text>
  <path class="ac" d="{fitness_path}" fill="none" stroke="{GRAPH["score"]}" stroke-width="2"/>
  {valid_layer}
</svg>
"""


def render_profile(
    segments: Sequence[int],
    lift_indices: Optional[AbstractSet[int]] = None,
    title: str = "Side profile",
) -> str:
    """The ride unrolled into a side view: height along the track, with speed.

    The plan view shows where a ride goes but not what it does, and what it
    does is the part that makes it worth building: how high the lift climbs,
    where the drops fall, how fast the train is going when it gets there.
    Drawn from `physics.trace`, the same walk the ride stats come from, so
    the picture and the numbers next to it cannot disagree.

    Height is the solid line, with the lift hill drawn over it in a heavier
    stroke. Speed is the dashed line on its own right-hand scale. Each
    counted drop is numbered where it starts, and a train that stalls gets a
    cross where it stops.
    """
    ride = trace(list(segments), set(lift_indices) if lift_indices is not None else None)
    if not ride.points:
        return _empty_svg(title, "no pieces: the track is empty")

    w, h = 640, 300
    left, right, top_pad, bottom = 56, 60, 52, 44
    plot_w = w - left - right
    plot_h = h - top_pad - bottom

    length = max(ride.points[-1].distance_m, 1.0)
    heights = [0] + [p.height_out for p in ride.points]
    lo_z, hi_z = min(heights), max(heights)
    climb_m = (hi_z - lo_z) * HEIGHT_UNIT_M
    if hi_z <= lo_z:
        lo_z, hi_z = lo_z - 1, hi_z + 1
    top_speed = max([p.speed_in for p in ride.points] + [p.speed_out for p in ride.points])
    top_speed = max(top_speed, 1.0)

    def x_at(distance: float) -> float:
        return round(left + plot_w * distance / length, 1)

    # Room above the highest point for the drop label that usually sits there.
    head = 16

    def y_height(z: float) -> float:
        return round(top_pad + plot_h - (plot_h - head) * (z - lo_z) / (hi_z - lo_z), 1)

    def y_speed(v: float) -> float:
        return round(top_pad + plot_h - plot_h * v / top_speed, 1)

    def path(pairs: Sequence[tuple]) -> str:
        return " ".join(f"{'M' if i == 0 else 'L'}{x},{y}" for i, (x, y) in enumerate(pairs))

    height_pts = [(x_at(0.0), y_height(ride.points[0].height_in))]
    speed_pts = [(x_at(0.0), y_speed(ride.points[0].speed_in))]
    for p in ride.points:
        height_pts.append((x_at(p.distance_m), y_height(p.height_out)))
        speed_pts.append((x_at(p.distance_m), y_speed(p.speed_out)))

    # Contiguous runs of chain-lift pieces (not the station, which also
    # drives the train but is not what anyone means by "the lift").
    lift_paths = []
    run: list = []
    for p in ride.points:
        if p.on_lift and not p.is_station and not p.stalled:
            if not run:
                run.append((x_at(p.distance_start_m), y_height(p.height_in)))
            run.append((x_at(p.distance_m), y_height(p.height_out)))
        elif run:
            lift_paths.append(run)
            run = []
    if run:
        lift_paths.append(run)

    layers = []
    for pairs in lift_paths:
        layers.append(
            f'<path class="ac" data-series="lift" d="{path(pairs)}" fill="none" '
            f'stroke="{GRAPH["lift"]}" stroke-width="6" stroke-opacity="0.55" '
            f'stroke-linecap="round"/>'
        )
    layers.append(
        f'<path class="acs" data-series="speed" d="{path(speed_pts)}" fill="none" '
        f'stroke="{GRAPH["speed"]}" stroke-width="1.5" stroke-dasharray="4 3"/>'
    )
    layers.append(
        f'<path class="ac" data-series="height" d="{path(height_pts)}" fill="none" '
        f'stroke="{GRAPH["height"]}" stroke-width="2"/>'
    )

    seen_drops = set()
    for p in ride.points:
        if p.drop is None or p.drop in seen_drops:
            continue
        seen_drops.add(p.drop)
        x, y = x_at(p.distance_start_m), y_height(p.height_in)
        layers.append(
            f'<text class="tx" data-drop="{p.drop}" x="{x}" y="{round(y - 7, 1)}" '
            f'text-anchor="middle" font-size="10" font-weight="600" '
            f'fill="{GRAPH["text"]}">D{p.drop}</text>'
        )

    notes = []
    if not ride.completed:
        stop = ride.points[-1]
        x, y = x_at(stop.distance_m), y_height(stop.height_in)
        layers.append(
            f'<path class="tx" data-series="stall" d="M{x - 5},{y - 5} L{x + 5},{y + 5} '
            f'M{x - 5},{y + 5} L{x + 5},{y - 5}" stroke="{GRAPH["stall"]}" '
            f'stroke-width="2" fill="none"/>'
        )
        layers.append(
            f'<text class="tx" x="{x}" y="{round(y + 18, 1)}" text-anchor="middle" '
            f'font-size="10" fill="{GRAPH["stall"]}">stalls here</text>'
        )
        notes.append(f"the train stalls on piece {stop.index + 1}")

    top_mph = top_speed * MPH_PER_MS
    drops = len(seen_drops)
    subtitle = (
        f"{round(ride.points[-1].distance_m)} m long, {climb_m:.1f} m of height, "
        f"top speed {top_mph:.0f} mph, {drops} drop{'s' if drops != 1 else ''}"
    )
    if notes:
        subtitle += ", " + ", ".join(notes)

    return f"""<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" \
style="width:100%;font-family:{FONT};background:{GRAPH["bg"]};">
  <title>{_escape(title)}</title>
  <desc>Side profile of a roller coaster: height along the ride as a solid line, \
with the lift hill drawn heavier, and speed as a dashed line on the right-hand \
scale. Drops are numbered where they start. {_escape(subtitle)}.</desc>
  <rect class="bg" x="0" y="0" width="{w}" height="{h}" fill="{GRAPH["bg"]}"/>
  <text class="tx" x="{left}" y="26" font-size="14" font-weight="600" fill="{GRAPH["text"]}">\
{_escape(title)}</text>
  <text class="ts" x="{left}" y="44" font-size="11" fill="{GRAPH["text_sec"]}">{_escape(subtitle)}</text>
  <line class="ax" x1="{left}" y1="{top_pad}" x2="{left}" y2="{top_pad + plot_h}" \
stroke="{GRAPH["border"]}" stroke-width="1"/>
  <line class="ax" x1="{left}" y1="{top_pad + plot_h}" x2="{left + plot_w}" y2="{top_pad + plot_h}" \
stroke="{GRAPH["border"]}" stroke-width="1"/>
  <text class="ts" x="{left - 8}" y="{top_pad + head + 4}" text-anchor="end" font-size="10" \
fill="{GRAPH["text_sec"]}">{hi_z * HEIGHT_UNIT_M:.0f} m</text>
  <text class="ts" x="{left - 8}" y="{top_pad + plot_h}" text-anchor="end" font-size="10" \
fill="{GRAPH["text_sec"]}">{lo_z * HEIGHT_UNIT_M:.0f} m</text>
  <text class="ts" x="{left + plot_w + 6}" y="{top_pad + 4}" font-size="10" \
fill="{GRAPH["text_sec"]}">{top_mph:.0f} mph</text>
  <text class="ts" x="{left + plot_w + 6}" y="{top_pad + plot_h}" font-size="10" \
fill="{GRAPH["text_sec"]}">0 mph</text>
  <text class="ts" x="{left + plot_w + 6}" y="{top_pad + plot_h + 18}" font-size="10" \
fill="{GRAPH["text_sec"]}">speed</text>
  <text class="ts" x="{left}" y="{h - 16}" font-size="10" fill="{GRAPH["text_sec"]}">station</text>
  <text class="ts" x="{left + plot_w}" y="{h - 16}" text-anchor="end" font-size="10" \
fill="{GRAPH["text_sec"]}">{round(ride.points[-1].distance_m)} m</text>
  <text class="ts" x="{left + plot_w / 2}" y="{h - 16}" text-anchor="middle" font-size="10" \
fill="{GRAPH["text_sec"]}">distance along the ride</text>
{chr(10).join("  " + layer for layer in layers)}
</svg>
"""


# ---------------------------------------------------------------------------
# Isometric view

# A 2:1 isometric projection like the game's own. A tile is a diamond
# `tile_px` wide and half that tall. A height unit is a quarter tile, and in
# this projection a tile's height is about 1.22 half-widths on screen, so one
# height unit is a quarter of that.
ISO_Z_PER_HALF_TILE = 0.306
# The rails sit this far apart, in tiles.
ISO_GAUGE = 0.36
# Pieces at the viewer's side of the ride are painted last. The picture turns
# in quarter turns, so there are four of them.
ISO_ANGLES = 4


class IsoChunk(NamedTuple):
    """A short run of track and what is painted with it, in paint order."""

    piece: int
    a: Point
    b: Point
    tile: Tuple[int, int]  # the tile the chunk sits in, in the turned view
    z: float
    support: bool  # a support column stands under this chunk's start
    station: bool  # the chunk belongs to a station piece


def _rotate(x: float, y: float, angle: int, cx: float, cy: float) -> Tuple[float, float]:
    """World coordinates turned `angle` quarter turns about the ride's centre."""
    u, v = x - cx, y - cy
    for _ in range(angle % ISO_ANGLES):
        u, v = v, -u
    return u, v


def iso_paint_order(
    paths: Sequence[PiecePath], angle: int = 0, centre: Tuple[float, float] = (0.0, 0.0),
) -> List[IsoChunk]:
    """Every chunk of track, sorted back to front for one view.

    Sorted by the tile a chunk sits in, far tiles first, and within a tile
    low before high, so where a track passes over itself the upper piece
    paints last. Sorting whole pieces would draw a long piece wholly in front
    of or behind a piece it only partly overlaps.
    """
    cx, cy = centre
    chunks: List[IsoChunk] = []
    for path in paths:
        points = path.points
        middle = len(points) // 2
        for i in range(len(points) - 1):
            a, b = points[i], points[i + 1]
            mid_x, mid_y = _rotate((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, angle, cx, cy)
            # Tile indices are taken from the turned coordinates, so the tile a
            # chunk counts as in follows the view.
            tile_u, tile_v = math.floor(mid_x + 0.5), math.floor(mid_y + 0.5)
            z = (a[2] + b[2]) / 2
            chunks.append(IsoChunk(
                piece=path.index, a=a, b=b,
                tile=(tile_u, tile_v), z=z,
                support=i == 0 or i == middle,
                station=path.segment in STATION_SEGMENTS,
            ))
    # Larger u + v is farther from the viewer, so it paints first.
    chunks.sort(key=lambda c: (-(c.tile[0] + c.tile[1]), c.z))
    return chunks


def render_isometric(
    segments: Sequence[int],
    angle: int = 0,
    start: Optional[Position] = None,
    title: str = "Ride view",
    tile_px: int = 28,
) -> str:
    """An isometric picture of a track: rails, ties, and support columns.

    Drawn back to front, like the game's own view, from one of four angles
    (`angle` quarter turns). It shows generide's model of the ride, so a
    piece's slope follows its definition, not the game's exact geometry.
    """
    angle %= ISO_ANGLES
    paths = track_path(segments, start)
    if not paths:
        return _empty_svg(title, "no tiles: the track is empty")

    bounds = track_bounds(start if start is not None else Position(), segments)
    cx = (bounds.min_x + bounds.max_x) // 2
    cy = (bounds.min_y + bounds.max_y) // 2
    half = tile_px / 2
    z_px = ISO_Z_PER_HALF_TILE * half
    ground_z = min(bounds.min_z, 0)

    def project(x: float, y: float, z: float) -> Tuple[float, float]:
        u, v = _rotate(x, y, angle, cx, cy)
        return (u - v) * half, -(u + v) * half / 2 - z * z_px

    def fmt(point: Tuple[float, float]) -> str:
        return f"{point[0]:.1f},{point[1]:.1f}"

    # Every drawn point, to size the picture before laying anything out.
    xs: List[float] = []
    ys: List[float] = []

    def seen(point: Tuple[float, float]) -> Tuple[float, float]:
        xs.append(point[0])
        ys.append(point[1])
        return point

    layers: List[str] = []

    # Ground grid: tile edges at the lowest level the ride reaches.
    left, right = bounds.min_x - 0.5, bounds.max_x + 0.5
    near, far = bounds.min_y - 0.5, bounds.max_y + 0.5
    grid = []
    for gx in range(bounds.min_x, bounds.max_x + 2):
        a = seen(project(gx - 0.5, near, ground_z))
        b = seen(project(gx - 0.5, far, ground_z))
        grid.append(f"M{fmt(a)}L{fmt(b)}")
    for gy in range(bounds.min_y, bounds.max_y + 2):
        a = seen(project(left, gy - 0.5, ground_z))
        b = seen(project(right, gy - 0.5, ground_z))
        grid.append(f"M{fmt(a)}L{fmt(b)}")
    layers.append(
        f'<path class="ax" d="{"".join(grid)}" fill="none" stroke="{GRAPH["border"]}" stroke-width="0.6"/>'
    )

    # Station marker: every station piece's tile is outlined on the ground. A
    # track with no station piece marks its first tile instead, so the picture
    # still says where the ride starts.
    marked = [path for path in paths if path.segment in STATION_SEGMENTS] or [paths[0]]
    is_station = marked[0].segment in STATION_SEGMENTS
    for path in marked:
        mid = path.points[len(path.points) // 2]
        sx, sy = round(mid[0]), round(mid[1])
        corners = [
            seen(project(sx + dx, sy + dy, ground_z))
            for dx, dy in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5))
        ]
        tag = ' data-station="tile"' if is_station else ""
        layers.append(
            f'<path class="ac"{tag} d="M{"L".join(fmt(c) for c in corners)}Z" fill="none" '
            f'stroke="{GRAPH["start"]}" stroke-width="2"/>'
        )

    for chunk in iso_paint_order(paths, angle, (cx, cy)):
        a, b = chunk.a, chunk.b
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        # Rails sit either side of the centreline, level with each other.
        ox, oy = -dy / length * ISO_GAUGE / 2, dx / length * ISO_GAUGE / 2
        if chunk.support and a[2] - ground_z > 0.5:
            top = seen(project(a[0], a[1], a[2]))
            bottom = seen(project(a[0], a[1], ground_z))
            layers.append(
                f'<path class="ts" d="M{fmt(top)}L{fmt(bottom)}" fill="none" '
                f'stroke="{GRAPH["text_sec"]}" stroke-opacity="0.45" stroke-width="1.5"/>'
            )
        tie_a = seen(project(a[0] + ox, a[1] + oy, a[2]))
        tie_b = seen(project(a[0] - ox, a[1] - oy, a[2]))
        layers.append(
            f'<path class="ts" d="M{fmt(tie_a)}L{fmt(tie_b)}" fill="none" '
            f'stroke="{GRAPH["text_sec"]}" stroke-width="1.2"/>'
        )
        rails = []
        for side in (1, -1):
            p = seen(project(a[0] + side * ox, a[1] + side * oy, a[2]))
            q = seen(project(b[0] + side * ox, b[1] + side * oy, b[2]))
            rails.append(f"M{fmt(p)}L{fmt(q)}")
        rail_colour = GRAPH["start"] if chunk.station else GRAPH["height"]
        tag = ' data-station="rail"' if chunk.station else ""
        layers.append(
            f'<path class="ac"{tag} d="{"".join(rails)}" fill="none" stroke="{rail_colour}" '
            f'stroke-width="1.6" stroke-linecap="round"/>'
        )

    pad, label_h = 24, 46
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    footprint = f"{bounds.width} x {bounds.depth} tiles"
    subtitle = f"{len(segments)} pieces, {footprint}, {bounds.height} height units of relief"
    text_w = int(max(len(title) * 8.4, len(subtitle) * 6.2))
    w = max(max_x - min_x, text_w) + pad * 2
    h = (max_y - min_y) + pad * 2 + label_h
    # The shift puts the picture's top-left corner at (pad, pad + label_h),
    # centred when the heading is the wider of the two.
    shift_x = pad + (w - pad * 2 - (max_x - min_x)) / 2 - min_x
    shift_y = pad + label_h - min_y

    return f"""<svg viewBox="0 0 {w:.0f} {h:.0f}" xmlns="http://www.w3.org/2000/svg" role="img" \
style="width:100%;font-family:{FONT};background:{GRAPH["bg"]};">
  <title>{_escape(title)}</title>
  <desc>Isometric view of a roller coaster track, View {angle + 1} of {ISO_ANGLES}. \
Two rails with ties and support columns, drawn from the back to the front. \
{_escape(subtitle)}</desc>
  <rect class="bg" x="0" y="0" width="{w:.0f}" height="{h:.0f}" fill="{GRAPH["bg"]}"/>
  <text class="tx" x="{pad}" y="26" font-size="14" font-weight="600" \
fill="{GRAPH["text"]}">{_escape(title)}</text>
  <text class="ts" x="{pad}" y="44" font-size="11" fill="{GRAPH["text_sec"]}">\
{_escape(subtitle)}</text>
  <g transform="translate({shift_x:.1f} {shift_y:.1f})">
{chr(10).join("    " + layer for layer in layers)}
  </g>
</svg>
"""


def _empty_svg(title: str, reason: str) -> str:
    """Something renderable for a track or run with nothing in it.

    Returning a picture that says "empty" beats raising, because these are
    called from a CLI at the end of a long run and a crash there would throw
    away the result the user was waiting for.
    """
    return f"""<svg viewBox="0 0 320 80" xmlns="http://www.w3.org/2000/svg" role="img" \
style="width:100%;font-family:{FONT};background:{GRAPH["bg"]};">
  <title>{_escape(title)}</title>
  <desc>{_escape(reason)}</desc>
  <rect class="bg" x="0" y="0" width="320" height="80" fill="{GRAPH["bg"]}"/>
  <text class="tx" x="16" y="32" font-size="14" font-weight="600" fill="{GRAPH["text"]}">\
{_escape(title)}</text>
  <text class="ts" x="16" y="52" font-size="11" fill="{GRAPH["text_sec"]}">{_escape(reason)}</text>
</svg>
"""

"""SVG renderers for tracks and evolution runs.

The only way to see a generated track used to be loading it in OpenRCT2,
which is a slow loop for a question as simple as "did the hill survive?".
These produce a plan view and a fitness curve from data we already have, so
a run can be looked at without the game.

SVG rather than a raster format for two reasons: it stays sharp in the
devlog at any size, and it carries its own stylesheet, so a diagram inlined
into a page follows that page's light or dark theme. The palette and the
theme mechanism match `docs/assets/rle-diagram.svg` so the two sit together
without looking like they came from different projects.
"""

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from rct2.geometry import OccupiedTile, Position, occupied_tiles, track_bounds

# Matches docs/assets/rle-diagram.svg. Kept as one block so a change to the
# design system is one edit rather than a hunt through string literals.
# Light values are written straight onto each element as presentation
# attributes so the file renders correctly anywhere, including GitHub, which
# strips <style> out of SVGs altogether. The stylesheet below only has to
# carry the dark overrides, and CSS beats a presentation attribute wherever
# the stylesheet does survive. Palette matches docs/assets/rle-diagram.svg.
LIGHT = {
    "bg": "#fcfcfa", "text": "#1a1a1a", "text_sec": "#6a6a64",
    "accent": "#59670f", "border": "#e5e3d8",
}
DARK = {
    "bg": "#1a1a17", "text": "#f0efe8", "text_sec": "#9a9a90",
    "accent": "#a0b030", "border": "#3a3a33",
}
ELEVATION_LIGHT = ["#e8e6d8", "#d8d9c0", "#c6cba4", "#b2bd87",
                   "#9cae6a", "#849d4e", "#6b8b33", "#59670f"]
ELEVATION_DARK = ["#2f2f27", "#3a3d2c", "#474d31", "#555e36",
                  "#64703b", "#748340", "#8a9a3a", "#a0b030"]

_DARK_RULES = "\n".join(
    [f"      .e{i} {{ fill: {c}; }}" for i, c in enumerate(ELEVATION_DARK)]
    + [f"      .bg {{ fill: {DARK['bg']}; }}",
       f"      .tx {{ fill: {DARK['text']}; }}",
       f"      .ts {{ fill: {DARK['text_sec']}; }}",
       f"      .ax {{ stroke: {DARK['border']}; }}",
       f"      .ac {{ stroke: {DARK['accent']}; }}",
       f"      .acs {{ stroke: {DARK['text_sec']}; }}",
       f"      .gap {{ stroke: {DARK['bg']}; }}"]
)

_THEME = f"""
    @media (prefers-color-scheme: dark) {{
{_DARK_RULES}
    }}
"""

ELEVATION_BANDS = len(ELEVATION_LIGHT)


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _elevation_band(z: int, min_z: int, max_z: int) -> int:
    """Which of the eight colour bands an elevation falls in.

    Banded rather than a continuous gradient because the colours are CSS
    variables, which cannot be interpolated. Eight bands is enough to read
    a hill's shape and few enough that each stays distinguishable from its
    neighbours in both themes.
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

    Reads like a blueprint: darker olive is higher ground. The first tile
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
            f'fill="{ELEVATION_LIGHT[band]}" stroke="{LIGHT["bg"]}" stroke-width="0.5"/>'
        )

    first = plan.tiles[0]
    fx, fy = screen(first.x, first.y)
    marker = (
        f'<rect class="ac" x="{fx}" y="{fy}" width="{tile_px}" height="{tile_px}" '
        f'fill="none" stroke="{LIGHT["accent"]}" stroke-width="2"/>'
    )

    footprint = f"{plan.width_tiles} x {plan.depth_tiles} tiles"
    relief = f"{plan.max_z - plan.min_z} height units"
    subtitle = f"{len(segments)} segments, {footprint}, {relief} of relief"

    # A narrow track would otherwise crop its own heading, since the width
    # came only from the tile grid. Roughly 6.2px per character at 11px.
    text_w = int(max(len(title) * 8.4, len(subtitle) * 6.2))
    w = max(grid_w, text_w) + pad * 2

    return f"""<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" \
style="width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,\
'Helvetica Neue',Arial,sans-serif;background:{LIGHT["bg"]};">
  <title>{_escape(title)}</title>
  <desc>Top-down plan of a roller coaster track. Each square is one occupied \
tile, shaded from light (lowest) to deep olive (highest). {_escape(subtitle)}</desc>
  <style>{_THEME}</style>
  <rect class="bg" x="0" y="0" width="{w}" height="{h}" fill="{LIGHT["bg"]}"/>
  <text class="tx" x="{pad}" y="26" font-size="14" font-weight="600" \
fill="{LIGHT["text"]}">{_escape(title)}</text>
  <text class="ts" x="{pad}" y="44" font-size="11" fill="{LIGHT["text_sec"]}">\
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
            f'<path class="acs" d="{valid_path}" fill="none" stroke="{LIGHT["text_sec"]}" '
            f'stroke-width="1" stroke-dasharray="3 3"/>\n  '
            f'<text class="ts" x="{w - right + 6}" y="{top_pad + 4}" font-size="10" '
            f'fill="{LIGHT["text_sec"]}">100%</text>\n  '
            f'<text class="ts" x="{w - right + 6}" y="{top_pad + plot_h}" font-size="10" '
            f'fill="{LIGHT["text_sec"]}">0%</text>\n  '
            f'<text class="ts" x="{w - right + 6}" y="{top_pad + plot_h + 18}" font-size="10" '
            f'fill="{LIGHT["text_sec"]}">valid</text>'
        )

    generations = len(fitness_history)
    subtitle = f"{generations} generations, best {hi:.2f}"

    return f"""<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" \
style="width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,\
'Helvetica Neue',Arial,sans-serif;background:{LIGHT["bg"]};">
  <title>{_escape(title)}</title>
  <desc>Line chart of best fitness per generation over {generations} generations, \
peaking at {hi:.2f}. A dashed line shows the share of the population that was \
buildable.</desc>
  <style>{_THEME}</style>
  <text class="tx" x="{left}" y="26" font-size="14" font-weight="600" fill="{LIGHT["text"]}">\
{_escape(title)}</text>
  <text class="ts" x="{left}" y="44" font-size="11" fill="{LIGHT["text_sec"]}">{_escape(subtitle)}</text>
  <line class="ax" x1="{left}" y1="{top_pad}" x2="{left}" y2="{top_pad + plot_h}" \
stroke="{LIGHT["border"]}" stroke-width="1"/>
  <line class="ax" x1="{left}" y1="{top_pad + plot_h}" x2="{left + plot_w}" y2="{top_pad + plot_h}" \
stroke="{LIGHT["border"]}" stroke-width="1"/>
  <text class="ts" x="{left - 8}" y="{top_pad + 4}" text-anchor="end" font-size="10" \
fill="{LIGHT["text_sec"]}">{hi:.2f}</text>
  <text class="ts" x="{left - 8}" y="{top_pad + plot_h}" text-anchor="end" font-size="10" \
fill="{LIGHT["text_sec"]}">{lo:.2f}</text>
  <text class="ts" x="{left}" y="{h - 16}" font-size="10" fill="{LIGHT["text_sec"]}">0</text>
  <text class="ts" x="{left + plot_w}" y="{h - 16}" text-anchor="end" font-size="10" \
fill="{LIGHT["text_sec"]}">{generations - 1}</text>
  <text class="ts" x="{left + plot_w / 2}" y="{h - 16}" text-anchor="middle" font-size="10" \
fill="{LIGHT["text_sec"]}">generation</text>
  <path class="ac" d="{fitness_path}" fill="none" stroke="{LIGHT["accent"]}" stroke-width="2"/>
  {valid_layer}
</svg>
"""


def _empty_svg(title: str, reason: str) -> str:
    """Something renderable for a track or run with nothing in it.

    Returning a picture that says "empty" beats raising, because these are
    called from a CLI at the end of a long run and a crash there would throw
    away the result the user was waiting for.
    """
    return f"""<svg viewBox="0 0 320 80" xmlns="http://www.w3.org/2000/svg" role="img" \
style="width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,\
'Helvetica Neue',Arial,sans-serif;background:{LIGHT["bg"]};">
  <title>{_escape(title)}</title>
  <desc>{_escape(reason)}</desc>
  <style>{_THEME}</style>
  <text class="tx" x="16" y="32" font-size="14" font-weight="600" fill="{LIGHT["text"]}">\
{_escape(title)}</text>
  <text class="ts" x="16" y="52" font-size="11" fill="{LIGHT["text_sec"]}">{_escape(reason)}</text>
</svg>
"""

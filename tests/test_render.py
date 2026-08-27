"""Tests for the SVG renderers.

These check the things that would silently produce a wrong or unreadable
picture, since a diagram that renders without error but shows the wrong
shape is worse than one that crashes.
"""

import xml.etree.ElementTree as ET

import pytest

from rct2 import td6
from rct2.geometry import Position, track_bounds
from rct2.render import (
    ELEVATION_BANDS,
    _elevation_band,
    plan_track,
    render_fitness_history,
    render_track,
)

FLAT_OVAL = [0x02, 0x01, 0x00, 0x00, 0x00]


def manic_miner_segments():
    ride = td6.load("data/sample_rides/manic_miner_test.td6")
    return [e.segment_type for e in ride.elements]


def test_a_real_design_renders_to_parseable_svg():
    svg = render_track(manic_miner_segments(), title="Manic Miner")
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


def test_the_plan_matches_the_geometry_it_came_from():
    # The header states a footprint; it has to be the footprint the tracer
    # reports, or the picture is telling a different story from the code.
    segments = manic_miner_segments()
    plan = plan_track(segments)
    bounds = track_bounds(Position(), segments)

    assert plan.width_tiles == bounds.width
    assert plan.depth_tiles == bounds.depth
    assert f"{bounds.width} x {bounds.depth} tiles" in render_track(segments)


def test_fills_are_literal_colours_rather_than_css_variables():
    # GitHub strips <style> out of SVGs, and a fill of var(--e3) with no
    # stylesheet renders black. Every tile came out black the first time
    # this was built.
    svg = render_track(manic_miner_segments())

    assert "var(--" not in svg
    assert 'fill="#' in svg


def test_dark_overrides_ride_along_for_where_css_survives():
    svg = render_track(manic_miner_segments())
    assert "prefers-color-scheme: dark" in svg


def test_a_crossing_draws_the_bridge_not_the_tunnel():
    # Where a track passes over itself the same tile appears twice. The
    # higher one has to win, or a crossing reads as the wrong elevation.
    segments = manic_miner_segments()
    plan = plan_track(segments)

    repeated = {}
    for tile in plan.tiles:
        repeated.setdefault((tile.x, tile.y), []).append(tile.z)
    crossings = {k: v for k, v in repeated.items() if len(set(v)) > 1}
    assert crossings, "fixture is expected to cross over itself"

    svg = render_track(segments, tile_px=10)
    for (tx, ty), heights in crossings.items():
        band = _elevation_band(max(heights), plan.min_z, plan.max_z)
        sx = 24 + (tx - plan.min_x) * 10
        sy = 24 + 46 + (plan.max_y - ty) * 10
        assert f'class="e{band} gap" x="{sx}" y="{sy}"' in svg


def test_elevation_bands_span_the_range_and_stay_in_bounds():
    assert _elevation_band(0, 0, 10) == 0
    assert _elevation_band(10, 0, 10) == ELEVATION_BANDS - 1
    assert 0 < _elevation_band(5, 0, 10) < ELEVATION_BANDS - 1
    # A flat track has no range to divide by.
    assert _elevation_band(3, 3, 3) == ELEVATION_BANDS - 1


def test_a_narrow_track_does_not_crop_its_own_heading():
    # Width came only from the tile grid at first, so a short track cut its
    # subtitle off mid-word.
    svg = render_track(FLAT_OVAL, title="A rather long title for a tiny track")
    width = float(ET.fromstring(svg).get("viewBox").split()[2])

    assert width > len("A rather long title for a tiny track") * 8


def test_an_empty_track_renders_a_card_rather_than_raising():
    # Called at the end of a long run, after the .td6 is already written.
    # Raising here would end the run on a traceback.
    root = ET.fromstring(render_track([]))
    assert "empty" in "".join(root.itertext()).lower()


def test_a_fitness_curve_plots_every_generation():
    svg = render_fitness_history([1.0, 2.0, 3.0, 4.0], title="Run")
    path = [e for e in ET.fromstring(svg).iter() if e.tag.endswith("path")][0]
    assert path.get("d").count("L") == 3


def test_a_run_that_never_improved_is_a_flat_line_not_a_crash():
    # Identical values give a zero range, which divided the plot by zero.
    root = ET.fromstring(render_fitness_history([3.0, 3.0, 3.0]))
    assert root.tag.endswith("svg")


def test_the_valid_share_is_optional_and_drawn_behind_when_given():
    without = render_fitness_history([1.0, 2.0])
    with_valid = render_fitness_history([1.0, 2.0], [0.5, 0.9])

    assert "valid" not in without
    assert "valid" in with_valid
    assert "stroke-dasharray" in with_valid


def test_an_empty_history_renders_a_card():
    root = ET.fromstring(render_fitness_history([]))
    assert "no generations" in "".join(root.itertext())

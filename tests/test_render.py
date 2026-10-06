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
    GRAPH,
    _elevation_band,
    iso_paint_order,
    plan_track,
    render_fitness_history,
    render_isometric,
    render_profile,
    render_track,
)
from rct2.construction import STATION_SEGMENTS
from rct2.physics import trace
from rct2.trackpath import STRAIGHT_STEPS, PiecePath, track_path

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


@pytest.mark.parametrize("render", [
    lambda: render_track(manic_miner_segments()),
    lambda: render_profile(manic_miner_segments(), _manic_miner_lifts()),
    lambda: render_fitness_history([1.0, 2.0, 2.5], [0.5, 0.7, 0.9]),
    lambda: render_isometric(manic_miner_segments()),
], ids=["plan", "profile", "fitness", "isometric"])
def test_pictures_look_the_same_in_any_theme(render):
    # Charts sit on their own dark background, like the game's ride graphs
    # (docs/design/README.md), so nothing may depend on a stylesheet that
    # GitHub strips or on the viewer's colour scheme.
    svg = render()
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    assert root.find(ns + "style") is None
    assert "prefers-color-scheme" not in svg
    assert root.find(f"{ns}rect[@class='bg']").get("fill") == GRAPH["bg"]


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


def _manic_miner_lifts():
    ride = td6.load("data/sample_rides/manic_miner_test.td6")
    return {i for i, e in enumerate(ride.elements) if e.chain_lift}


def test_profile_of_a_real_design_is_parseable_and_marks_the_lift():
    svg = render_profile(manic_miner_segments(), _manic_miner_lifts(), title="Manic Miner")
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    assert root.tag == ns + "svg"
    assert root.find(ns + "title").text == "Manic Miner"
    assert root.findall(f".//{ns}path[@data-series='lift']")
    assert root.findall(f".//{ns}path[@data-series='height']")
    assert root.findall(f".//{ns}path[@data-series='speed']")


def test_profile_marks_each_counted_drop():
    from rct2.physics import simulate

    segments, lifts = manic_miner_segments(), _manic_miner_lifts()
    root = ET.fromstring(render_profile(segments, lifts))
    markers = root.findall(".//{http://www.w3.org/2000/svg}*[@data-drop]")
    assert len(markers) == simulate(segments, lifts).drop_count


def test_profile_marks_the_stall_point():
    root = ET.fromstring(render_profile([0x00] * 30, lift_indices=set()))
    stall = root.findall(".//{http://www.w3.org/2000/svg}*[@data-series='stall']")
    assert stall
    assert "stalls" in ET.tostring(root, encoding="unicode")


def test_profile_of_empty_track_uses_empty_state():
    svg = render_profile([], title="Nothing")
    root = ET.fromstring(svg)
    assert "no pieces" in root.find("{http://www.w3.org/2000/svg}desc").text


@pytest.mark.parametrize("svg", [
    render_track(FLAT_OVAL),
    render_profile(FLAT_OVAL),
    render_fitness_history([1.0, 2.0, 2.5]),
    render_track([]),
    render_isometric(FLAT_OVAL),
    render_isometric([]),
], ids=["plan", "profile", "fitness", "empty", "isometric", "isometric-empty"])
def test_every_picture_paints_its_own_background(svg):
    # The light text is only readable on the dark background the picture
    # paints for itself; without it, a light page shows through.
    root = ET.fromstring(svg)
    backgrounds = root.findall("{http://www.w3.org/2000/svg}rect[@class='bg']")
    assert backgrounds


# ---------------------------------------------------------------------------
# Isometric view


def _bridge_over_road():
    # A road along x at height 0 and a bridge along y at height 8, crossing in
    # tile (0, 0). Built by hand so the crossing is exact.
    road = PiecePath(0, 0x00, tuple((x / 4, 0.0, 0.0) for x in range(-2, 3)))
    bridge = PiecePath(1, 0x00, tuple((0.0, y / 4, 8.0) for y in range(-2, 3)))
    return [road, bridge]


@pytest.mark.parametrize("angle", [0, 1, 2, 3])
def test_a_bridge_is_painted_after_the_road_it_crosses_from_every_angle(angle):
    # Covers AE2. Pieces nearer the viewer paint later, and where two pieces
    # share a tile the higher one paints later, so the bridge ends up on top.
    order = iso_paint_order(_bridge_over_road(), angle)

    last_road = max(i for i, chunk in enumerate(order) if chunk.piece == 0)
    first_bridge = min(i for i, chunk in enumerate(order) if chunk.piece == 1)
    assert first_bridge > last_road


@pytest.mark.parametrize("angle", [0, 1, 2, 3])
def test_a_real_crossing_paints_the_upper_track_last(angle):
    paths = track_path(manic_miner_segments())
    order = iso_paint_order(paths, angle)

    by_tile = {}
    for position, chunk in enumerate(order):
        by_tile.setdefault(chunk.tile, []).append((position, chunk.z))
    crossings = {t: v for t, v in by_tile.items() if len({round(z) for _, z in v}) > 1}
    assert crossings, "fixture is expected to cross over itself"
    for entries in crossings.values():
        heights_in_paint_order = [z for _, z in sorted(entries)]
        assert heights_in_paint_order == sorted(heights_in_paint_order)


def test_the_isometric_picture_parses_and_uses_literal_colours():
    svg = render_isometric(manic_miner_segments(), title="Manic Miner")

    assert ET.fromstring(svg).tag.endswith("svg")
    assert "var(--" not in svg


def test_the_isometric_footprint_matches_the_geometry():
    segments = manic_miner_segments()
    bounds = track_bounds(Position(), segments)

    assert f"{bounds.width} x {bounds.depth} tiles" in render_isometric(segments)


def test_each_quarter_turn_gives_a_different_picture_and_four_turns_come_back():
    segments = manic_miner_segments()
    pictures = [render_isometric(segments, angle) for angle in range(4)]

    assert len(set(pictures)) == 4
    assert render_isometric(segments, 4) == pictures[0]
    assert render_isometric(segments, -1) == pictures[3]


def test_the_description_names_the_view():
    root = ET.fromstring(render_isometric(manic_miner_segments(), 2))
    desc = root.find("{http://www.w3.org/2000/svg}desc").text

    assert "View 3 of 4" in desc


def test_the_isometric_picture_stays_small_enough_to_send_four_at_a_time():
    # The browser demo carries all four angles in each update.
    assert len(render_isometric(manic_miner_segments()).encode("utf-8")) < 150_000


def test_an_empty_track_renders_the_empty_card_in_isometric():
    svg = render_isometric([])

    assert "the track is empty" in svg


def test_every_station_piece_is_marked_not_only_the_first():
    segments = manic_miner_segments()
    stations = sum(1 for s in segments if s in STATION_SEGMENTS)
    assert stations > 1, "fixture is expected to have a multi-piece station"

    svg = render_isometric(segments)

    # Each station piece is cut into the same number of chunks, and the rails
    # of every one of them carry the station colour.
    marked_rails = svg.count('data-station="rail"')
    assert marked_rails == stations * STRAIGHT_STEPS
    assert svg.count('data-station="tile"') == stations
    assert f'data-station="rail" d=' in svg
    assert GRAPH["start"] in svg


def test_a_track_with_no_station_piece_has_no_station_marks():
    svg = render_isometric([0x00, 0x00, 0x2B, 0x00])

    assert "data-station" not in svg


def test_each_piece_has_at_most_one_support_column():
    segments = manic_miner_segments()
    svg = render_isometric(segments)

    columns = svg.count('data-support="1"')
    assert 0 < columns <= len(segments)


# ---------------------------------------------------------------------------
# The train


def _motion(svg):
    root = ET.fromstring(svg)
    node = root.find(".//{http://www.w3.org/2000/svg}animateMotion")
    assert node is not None, "the picture has no train animation"
    return node


def _floats(text):
    return [float(v) for v in text.split(";")]


def test_the_train_runs_at_the_simulations_speeds_over_twenty_seconds():
    # Covers AE6. The share of the lap spent on lift and station pieces is the
    # simulation's own, about 39 percent for Manic Miner, whatever the lap's
    # length in seconds.
    segments = manic_miner_segments()
    ride = trace(segments)
    motion = _motion(render_isometric(segments))

    assert motion.get("dur") == "20s"
    assert motion.get("repeatCount") == "indefinite"
    times = _floats(motion.get("keyTimes"))
    share = sum(
        times[p.index + 1] - times[p.index] for p in ride.points if p.on_lift or p.is_station
    )
    assert share == pytest.approx(0.388, abs=0.01)


def test_the_train_uses_linear_timing_or_the_speeds_are_ignored():
    # The default `paced` mode throws keyTimes and keyPoints away and runs the
    # train at one speed.
    motion = _motion(render_isometric(manic_miner_segments()))

    assert motion.get("calcMode") == "linear"
    assert motion.get("rotate") == "auto"


def test_key_times_and_key_points_cover_every_piece_and_never_run_backward():
    segments = manic_miner_segments()
    motion = _motion(render_isometric(segments))
    times = _floats(motion.get("keyTimes"))
    points = _floats(motion.get("keyPoints"))

    assert len(times) == len(points) == len(segments) + 1
    for series in (times, points):
        assert series[0] == 0 and series[-1] == 1
        assert series == sorted(series)


def test_turning_the_view_changes_where_the_train_is_not_when():
    segments = manic_miner_segments()
    first, second = _motion(render_isometric(segments, 0)), _motion(render_isometric(segments, 1))

    assert first.get("keyTimes") == second.get("keyTimes")
    assert first.get("dur") == second.get("dur")
    assert first.get("keyPoints") != second.get("keyPoints")


STALLING = [0x02, 0x01] + [0x00] * 30


def test_a_train_that_stalls_stops_where_the_simulation_says_with_a_marker():
    # Covers AE4.
    ride = trace(STALLING)
    assert not ride.completed
    svg = render_isometric(STALLING)
    motion = _motion(svg)

    assert motion.get("repeatCount") == "1"
    assert motion.get("fill") == "freeze"
    # Only the pieces before the stalled one are driven.
    assert len(_floats(motion.get("keyTimes"))) == ride.stall_index + 1
    assert 'data-stall="1"' in svg
    assert "stalls here" in svg


def test_a_ride_that_completes_has_no_stall_marker():
    svg = render_isometric(manic_miner_segments())

    assert "data-stall" not in svg

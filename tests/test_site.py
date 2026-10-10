"""Tests for the site description and the fit check.

The ride used throughout is `create_simple_circuit()`: a six-tile station
heading north from the origin, with a loop whose tiles span x 0..3 and
y -2..7. Its entrance and exit sit on the west side, at x -1.
"""

import json

import pytest

from rct2.generate import create_simple_circuit
from rct2.geometry import Heading, Position, occupied_tiles
from rct2.site import Site, SiteError, SiteFit, best_fit, fit_at, site_coords, site_penalty

RIDE = create_simple_circuit()
RIDE_TILES = {(t.x, t.y) for t in occupied_tiles(Position(), RIDE)}
# Entrance and exit tiles, west of the first and last station tile.
ENTRANCE_TILES = {(-1, 0), (-1, 5)}
ANCHOR = (3, 4)


def site_around_ride(extra_blocked=(), heights=None, anchor=ANCHOR, width=10, depth=14):
    """An open field big enough for the ride when it faces north from `anchor`."""
    rows = [["."] * width for _ in range(depth)]
    for x, y in extra_blocked:
        rows[y][x] = "#"
    return Site.from_rows(["".join(r) for r in rows], anchor=anchor, heights=heights)


def world(tile, anchor=ANCHOR):
    return (anchor[0] + tile[0], anchor[1] + tile[1])


def test_a_ride_inside_the_site_reports_no_violations():
    # Covers AE1.
    fit = fit_at(site_around_ride(), RIDE, Heading.NORTH)

    assert (fit.outside, fit.blocked, fit.below_ground) == (0, 0, 0)
    assert fit.fits


def test_an_l_shaped_site_holds_a_ride_that_stays_inside_the_l():
    # Covers AE1. Everything the ride needs is usable; the rest of the field is blocked.
    needed = {world(t) for t in RIDE_TILES | ENTRANCE_TILES}
    rows = [
        "".join("." if (x, y) in needed else "#" for x in range(10)) for y in range(14)
    ]

    fit = fit_at(Site.from_rows(rows, anchor=ANCHOR), RIDE, Heading.NORTH)

    assert fit.total == 0


def test_a_tile_one_step_outside_the_site_counts_as_outside():
    site = site_around_ride(width=ANCHOR[0] + 3)  # ride reaches x = anchor + 3, one column short

    fit = fit_at(site, RIDE, Heading.NORTH)

    assert fit.outside > 0
    assert fit.blocked == 0


def test_a_tile_on_a_blocked_cell_counts_once():
    target = world((0, 3))
    site = site_around_ride(extra_blocked=[target])
    assert target in {world(t) for t in RIDE_TILES}

    fit = fit_at(site, RIDE, Heading.NORTH)

    assert fit.blocked == 1


def test_track_under_the_local_ground_counts_as_below_ground():
    flat = site_around_ride()
    rows = ["".join(r) for r in (["." * 10] * 14)]
    high = [[0] * 10 for _ in range(14)]
    high[5][3] = 4  # the station tile after the anchor sits on ground 4 high, anchor ground is 0
    sloped = Site.from_rows(rows, anchor=ANCHOR, heights=high)

    assert fit_at(flat, RIDE, Heading.NORTH).below_ground == 0
    assert fit_at(sloped, RIDE, Heading.NORTH).below_ground >= 1


def test_the_ride_starts_at_the_anchor_tiles_ground_height():
    # Anchor ground is 6, the rest of the field is 6 or lower: a ride at relative
    # height 0 is level with its anchor, so nothing is below ground.
    heights = [[6] * 10 for _ in range(14)]
    heights[0][0] = 3
    rows = ["." * 10] * 14
    site = Site.from_rows(rows, anchor=ANCHOR, heights=heights)

    assert fit_at(site, RIDE, Heading.NORTH).below_ground == 0

    heights[ANCHOR[1] + 1][ANCHOR[0]] = 9  # one ride tile now sits under higher ground
    taller = Site.from_rows(rows, anchor=ANCHOR, heights=heights)
    assert fit_at(taller, RIDE, Heading.NORTH).below_ground >= 1


def test_a_blocked_tile_on_the_side_the_export_uses_is_a_violation():
    # The export puts this ride's entrance and exit on the west side (x -1), so
    # a blocked west tile counts even though the east side is free.
    blocked_west = [world(t) for t in ENTRANCE_TILES]
    site = site_around_ride(extra_blocked=blocked_west)

    assert fit_at(site, RIDE, Heading.NORTH).blocked == 2


def test_a_blocked_tile_on_the_side_the_export_does_not_use_is_fine():
    # East of the first and last station tile is free of track; the export does not use it.
    unused_side = [world((1, 0)), world((1, 5))]
    site = site_around_ride(extra_blocked=unused_side)

    assert fit_at(site, RIDE, Heading.NORTH).total == 0


def test_the_entrance_and_exit_the_export_writes_sit_on_tiles_the_check_approved():
    from rct2.generate import calculate_entrance_positions

    entrance, exit_ = calculate_entrance_positions(RIDE)
    site = site_around_ride()
    fit = best_fit(site, RIDE)

    assert fit.fits
    for structure in (entrance, exit_):
        tile = (structure.x // 32, structure.y // 32)
        wx, wy = site_coords(site.anchor, fit.heading, *tile)
        assert site.inside(wx, wy) and not site.blocked(wx, wy)


@pytest.mark.parametrize("heading", list(Heading))
def test_the_inline_tile_mapping_agrees_with_site_coords(heading):
    # _fit_tiles unrolls site_coords for speed; count the same ride the slow way.
    site = site_around_ride(extra_blocked=[world((0, 3)), world((0, 1))], width=6, depth=8)
    expected_outside = set()
    expected_blocked = set()
    for tile in occupied_tiles(Position(), RIDE):
        wx, wy = site_coords(site.anchor, heading, tile.x, tile.y)
        if not site.inside(wx, wy):
            expected_outside.add((wx, wy))
        elif site.blocked(wx, wy):
            expected_blocked.add((wx, wy))

    fit = fit_at(site, RIDE, heading)

    # Entrance and exit tiles add to these counts, never subtract.
    assert fit.outside >= len(expected_outside)
    assert fit.blocked >= len(expected_blocked)


def test_site_coords_rotate_with_the_heading():
    # Facing east, a tile three along the ride is three columns to the east.
    assert site_coords((5, 5), Heading.EAST, 0, 3) == (8, 5)
    assert site_coords((5, 5), Heading.NORTH, 0, 3) == (5, 8)
    assert site_coords((5, 5), Heading.SOUTH, 0, 3) == (5, 2)
    assert site_coords((5, 5), Heading.WEST, 0, 3) == (2, 5)
    # A tile one to the right of a north-facing ride is one to the east; facing east it is one south.
    assert site_coords((5, 5), Heading.NORTH, 1, 0) == (6, 5)
    assert site_coords((5, 5), Heading.EAST, 1, 0) == (5, 4)


def test_a_ride_that_fits_only_when_turned_east_reports_east():
    needed = {site_coords((2, 6), Heading.EAST, *t) for t in RIDE_TILES | ENTRANCE_TILES}
    needed |= {site_coords((2, 6), Heading.EAST, 1, 0), site_coords((2, 6), Heading.EAST, 1, 5)}
    width = max(x for x, _ in needed) + 2
    depth = max(y for _, y in needed) + 2
    rows = [
        "".join("." if (x, y) in needed else "#" for x in range(width)) for y in range(depth)
    ]
    site = Site.from_rows(rows, anchor=(2, 6))

    fit = best_fit(site, RIDE)

    assert fit.heading == Heading.EAST
    assert fit.total == 0
    assert fit_at(site, RIDE, Heading.NORTH).total > 0


def test_a_ride_that_fits_no_heading_reports_the_heading_with_the_fewest_violations():
    site = Site.from_rows(["." * 3] * 3, anchor=(1, 1))

    fit = best_fit(site, RIDE)
    totals = {h: fit_at(site, RIDE, h).total for h in Heading}

    assert fit.total == min(totals.values())
    assert not fit.fits


def test_a_tie_takes_the_first_heading_in_compass_order():
    site = site_around_ride(width=40, depth=40, anchor=(20, 20))

    assert best_fit(site, RIDE).heading == Heading.NORTH


def test_a_saved_site_round_trips(tmp_path):
    site = Site.from_rows(
        ["..#.", "....", "#..."], anchor=(1, 1), heights=[[0, 1, 2, 3], [0, 0, 0, 0], [4, 4, 4, 4]]
    )
    path = tmp_path / "site.json"

    site.save(path)

    assert Site.load(path) == site
    assert json.loads(path.read_text())["version"] == 1


@pytest.mark.parametrize(
    "data, message",
    [
        ({"version": 1, "rows": [], "anchor": [0, 0]}, "at least one row"),
        ({"version": 1, "rows": ["..", "."], "anchor": [0, 0]}, "same length"),
        ({"version": 1, "rows": ["a."], "anchor": [0, 0]}, "'.' or '#'"),
        ({"version": 1, "rows": [".."], "anchor": [5, 0]}, "anchor"),
        ({"version": 1, "rows": [".."], "anchor": [0, 0], "heights": [[0]]}, "heights"),
        ({"version": 2, "rows": [".."], "anchor": [0, 0]}, "version"),
        ({"rows": [".."]}, "anchor"),
        ({"version": 1, "rows": [".."], "anchor": ["1", "0"]}, "anchor"),
        ({"version": 1, "rows": [".."], "anchor": "10"}, "anchor"),
        ({"version": 1, "rows": [".."], "anchor": [True, 0]}, "anchor"),
        ({"version": 1, "rows": [".."], "anchor": [0, 0], "heights": [[1.9, 0]]}, "heights"),
        ({"version": 1, "rows": [".."], "anchor": [0, 0], "heights": [["1", 0]]}, "heights"),
    ],
)
def test_a_malformed_site_is_rejected_with_a_message(data, message):
    with pytest.raises(SiteError, match=message):
        Site.from_dict(data)


def test_a_site_file_that_is_not_json_is_rejected(tmp_path):
    path = tmp_path / "site.json"
    path.write_text("not json")

    with pytest.raises(SiteError, match="not valid JSON"):
        Site.load(path)


def test_site_penalty_adds_each_kind_and_caps_each_kind_separately():
    fit = SiteFit(heading=Heading.NORTH, outside=2, blocked=3, below_ground=4)

    # 2 * 10 = 20 (under the cap), 3 * 10 = 30 -> 25, 4 * 10 = 40 -> 25
    assert site_penalty(fit, per_tile=10, cap_per_kind=25) == 70
    assert site_penalty(SiteFit(Heading.NORTH, 0, 0, 0), per_tile=10, cap_per_kind=25) == 0

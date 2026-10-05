"""Tests for the track centerline module.

The isometric picture and the train both ride on these lines, so a gap
between two pieces, an arc that ends off its tile, or a slope that rises by
the wrong amount would show up as a visibly broken ride.
"""

import math

import pytest

from rct2 import td6
from rct2.geometry import Position, advance_position
from rct2.trackpath import track_path

FLAT = 0x00
UP_25 = 0x04
UP_60 = 0x05
LEFT_TURN_3 = 0x2A
RIGHT_TURN_3 = 0x2B
LEFT_TURN_5 = 0x10
HELIX_SMALL = 0x5A
HELIX_LARGE = 0x5E
EPS = 1e-9


def manic_miner_segments():
    ride = td6.load("data/sample_rides/manic_miner_test.td6")
    return [e.segment_type for e in ride.elements]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def test_a_gentle_and_a_steep_slope_rise_four_to_one():
    # Covers AE1. One tile each: the piece definitions say 2 and 8 height units.
    gentle = track_path([UP_25])[0]
    steep = track_path([UP_60])[0]

    assert gentle.points[-1][2] - gentle.points[0][2] == pytest.approx(2)
    assert steep.points[-1][2] - steep.points[0][2] == pytest.approx(8)


def test_each_piece_starts_where_the_last_one_ended():
    path = track_path(manic_miner_segments())

    assert len(path) == 89
    for before, after in zip(path, path[1:]):
        for got, want in zip(after.points[0], before.points[-1]):
            assert got == pytest.approx(want, abs=EPS)


def test_a_closed_circuit_ends_where_it_started():
    path = track_path(manic_miner_segments())

    for got, want in zip(path[-1].points[-1], path[0].points[0]):
        assert got == pytest.approx(want, abs=EPS)


@pytest.mark.parametrize("segment, radius", [(LEFT_TURN_3, 1.5), (RIGHT_TURN_3, 1.5), (LEFT_TURN_5, 2.5)])
def test_a_quarter_turn_is_a_circular_arc(segment, radius):
    # Radii are the ones physics.segment_length uses for arc length.
    points = track_path([segment])[0].points
    turn = points[0], points[-1]
    # The arc's centre is a radius to the side of the entry point, so every
    # sample is the same distance from it.
    start, end = turn
    sign = 1 if segment == RIGHT_TURN_3 else -1
    # Entry heading is north (+y); right is +x.
    centre = (start[0] + sign * radius, start[1])
    assert dist(centre, start) == pytest.approx(radius)
    for p in points:
        assert dist(centre, p) == pytest.approx(radius)
    assert dist(centre, end) == pytest.approx(radius)


def test_a_turn_leaves_on_the_heading_the_geometry_reports():
    for segment in (LEFT_TURN_3, RIGHT_TURN_3, LEFT_TURN_5):
        start = Position()
        end = advance_position(start, segment)
        points = track_path([segment], start)[0].points
        # The next piece starts half a tile before its tile centre, so the
        # arc must stop half a tile behind the end tile's centre along the
        # new heading.
        step = {0: (0, 1), 1: (1, 0), 2: (0, -1), 3: (-1, 0)}[int(end.heading)]
        want = (end.x - 0.5 * step[0], end.y - 0.5 * step[1])
        assert points[-1][0] == pytest.approx(want[0])
        assert points[-1][1] == pytest.approx(want[1])


@pytest.mark.parametrize("segment, sideways", [(HELIX_SMALL, 3), (HELIX_LARGE, 5)])
def test_a_half_turn_helix_comes_back_alongside_without_reversing(segment, sideways):
    points = track_path([segment])[0].points

    # Zero forward displacement and `sideways` tiles to the right.
    assert points[-1][0] - points[0][0] == pytest.approx(sideways)
    assert points[-1][1] - points[0][1] == pytest.approx(0, abs=EPS)
    # Moving along the arc never doubles back: the distance covered along the
    # entry heading rises to the apex and falls, and the sideways distance
    # only grows.
    xs = [p[0] for p in points]
    assert xs == sorted(xs)


def test_a_flat_piece_stays_level_and_a_transition_eases_into_the_slope():
    flat = track_path([FLAT])[0].points
    assert {p[2] for p in flat} == {0}

    # flat_to_25_deg_up rises 1 unit and meets the 25 degree slope at its
    # full gradient: it starts level and ends rising.
    ease = track_path([0x06])[0].points
    assert ease[-1][2] - ease[0][2] == pytest.approx(1)
    first_rise = ease[1][2] - ease[0][2]
    last_rise = ease[-1][2] - ease[-2][2]
    assert last_rise > 3 * first_rise


def test_an_empty_track_has_no_path():
    assert track_path([]) == []

"""The road network on the map (GPSFrame's LayoutRoads), with the real road data."""

import math

import pytest

from azerothgps.routecheck import _runtime
from test_addon_lua import multi


@pytest.fixture(scope="module")
def game():
    return _runtime()


def spread(t):
    xs = [t[i][3] for i in range(1, len(t) + 1)]
    ys = [t[i][4] for i in range(1, len(t) + 1)]
    return min(xs), max(xs), min(ys), max(ys)


def test_zoomed_out_every_side_of_the_view_keeps_its_roads(game):
    lua, ns = game
    G = ns.GPS
    # the Barrens at 2,500 yd: more than 3,000 lines' worth of road
    G.MAX_SEGMENTS = 10 ** 9
    whole = G.LayoutRoads(-450.0, -2650.0, 1, 0, 2500.0, 130.0)
    G.MAX_SEGMENTS = 1500
    segs = G.LayoutRoads(-450.0, -2650.0, 1, 0, 2500.0, 130.0)
    assert len(whole) > 3000 and len(segs) <= 1500
    assert spread(segs) == pytest.approx(spread(whole), abs=6)  # (as far out as with no cap)


def test_zoomed_out_a_drawn_road_still_shows(game):
    lua, ns = game
    G = ns.GPS
    # a road drawn at the edge of Orgrimmar's view (its streets alone: more lines than the cap)
    ns.db.tracks = lua.eval("{ { op = 'add', continent = 1, time = 1, pts = { 1150,-4050, 1100,-4100, 1050,-4150 } } }")
    ns.Router.Reset()
    half, zoom = 130.0, 1200.0
    segs = G.LayoutRoads(1600.0, -4400.0, 1, 0, zoom, half)
    n = len(segs)
    assert 0 < n <= G.MAX_SEGMENTS
    s = half / zoom
    pts = [(segs[i][1], segs[i][2]) for i in range(1, n + 1)] + [(segs[i][3], segs[i][4]) for i in range(1, n + 1)]
    for wx, wy in ((1150, -4050), (1050, -4150)):  # (the drawn road's ends are drawn)
        dx, dy = multi(lua, ns.Geo.ScreenOffset, 1600.0, -4400.0, wx, wy)
        assert min(math.hypot(px - dx * s, py - dy * s) for px, py in pts) < 3
    ns.db.tracks = None
    ns.Router.Reset()


def test_zooming_back_in_gets_the_fine_roads_back(game):
    lua, ns = game
    G = ns.GPS
    first = len(G.LayoutRoads(-9460.0, 60.0, 0, 0, 300.0, 130.0))
    z = 300.0
    for _ in range(20):
        z *= 1.06
        G.LayoutRoads(-9460.0, 60.0, 0, 0, z, 130.0)
    for _ in range(20):
        z /= 1.06
        G.LayoutRoads(-9460.0, 60.0, 0, 0, z, 130.0)
    assert len(G.LayoutRoads(-9460.0, 60.0, 0, 0, 300.0, 130.0)) == first

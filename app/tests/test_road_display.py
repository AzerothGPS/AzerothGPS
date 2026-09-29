"""The road network on the map (GPSFrame's LayoutRoads), with the real road data."""

import math

import pytest

from azerothgps.routecheck import _runtime
from test_addon_lua import ADDON, multi


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


def test_roads_stay_on_screen_while_rebuilt_after_an_edit(game):
    lua, ns = game
    G, R = ns.GPS, ns.Router
    lua.execute("GetTime = function() return os.clock() end")
    R.WARM, R.SYNC_WALKS = True, False
    try:
        before = len(G.LayoutRoads(-9460.0, 60.0, 0, 0, 600.0, 130.0))  # (built: shown)
        assert before > 0
        # a road drawn, the road network rebuilt in the background (as Record.Changed does)
        ns.db.tracks = lua.eval("{ { op = 'add', continent = 0, time = 7, pts = { -9460,60, -9400,120, -9350,200 } } }")
        R.Reset()
        during = G.LayoutRoads(-9460.0, 60.0, 0, 0, 600.0, 130.0)
        assert len(during) >= before  # (the roads as they were, and the new one as drawn)
        clock = lua.eval("function() return os.clock() * 1000 end")
        while R.HasWork():
            R.Pump(clock() + 5, clock)
        assert len(G.LayoutRoads(-9460.0, 60.0, 0, 0, 600.0, 130.0)) > 0
    finally:
        R.WARM, R.SYNC_WALKS = False, True
        ns.db.tracks = None
        R.Reset()


def test_an_erased_road_goes_at_once_while_rebuilt(game):
    lua, ns = game
    G, R = ns.GPS, ns.Router
    lua.execute("GetTime = function() return os.clock() end")
    R.WARM, R.SYNC_WALKS = True, False
    half, zoom, px, py = 130.0, 600.0, -9460.0, 60.0
    s = half / zoom
    try:
        G.LayoutRoads(px, py, 0, 0, zoom, half)  # (built)
        n = R.Nearest(0, px, py)  # a road point near Goldshire
        rx, ry = n.px, n.py
        box = [rx - 25, ry - 25, rx + 25, ry - 25, rx + 25, ry + 25, rx - 25, ry + 25, rx - 25, ry - 25]

        def inside(segs):
            out = 0
            for i in range(1, len(segs) + 1):
                for (ax, ay) in ((segs[i][1], segs[i][2]), (segs[i][3], segs[i][4])):
                    for wx, wy in ((rx, ry),):
                        dx, dy = multi(lua, ns.Geo.ScreenOffset, px, py, wx, wy)
                        if abs(ax - dx * s) < 20 * s and abs(ay - dy * s) < 20 * s:
                            out += 1
            return out
        assert inside(G.LayoutRoads(px, py, 0, 0, zoom, half)) > 0  # (the road is drawn there)
        # circled to erase it: the network rebuilt in the background, the road there gone at once
        ns.db.tracks = lua.eval("{}")
        ns.db.tracks[1] = lua.table(op="remove", area=True, continent=0, time=9, pts=lua.table(*box))
        R.Reset()
        assert inside(G.LayoutRoads(px, py, 0, 0, zoom, half)) == 0
    finally:
        R.WARM, R.SYNC_WALKS = False, True
        ns.db.tracks = None
        R.Reset()


def test_cave_entrances_sit_at_their_caves(game):
    lua, ns = game
    G, P = ns.GPS, ns.Passability
    for cont, low, high in ((0, 170, 400), (1, 170, 500)):
        caves = ns.Caves[cont]
        marks = G.CaveEntrances(cont)
        assert low <= len(marks) <= high  # (about one or two a cave: 175 caves each)
        names = {caves[i][1] for i in range(1, len(caves) + 1)}
        for i in range(1, len(marks) + 1):
            m = marks[i]
            assert m.name in names or m.name == "Cave"
            # (at its cave: within its grid's rectangle, or just outside at the mouth)
            best = min(
                math.hypot(max(b[0] - m.x, 0, m.x - b[1]), max(b[2] - m.y, 0, m.y - b[3]))
                for b in (multi(lua, P.GridBounds, caves[k][2]) for k in range(1, len(caves) + 1)))
            assert best <= 30
    names0 = {G.CaveEntrances(0)[i].name for i in range(1, len(G.CaveEntrances(0)) + 1)}
    assert {"Jasperlode Mine", "Fargodeep Mine"} <= names0


def test_with_the_road_tools_on_edits_rebuild_once_when_turned_off(game):
    lua, ns = game
    G, R = ns.GPS, ns.Router
    if not ns.Record:
        loader = lua.eval("function(src, name) return assert(load(src, '@' .. name)) end")
        loader((ADDON / "Record.lua").read_text(encoding="utf-8"), "Record.lua")("AzerothGPS", ns)
    Rec = ns.Record
    lua.execute("GetTime = function() return os.clock() end")
    R.WARM, R.SYNC_WALKS = True, False
    clock = lua.eval("function() return os.clock() * 1000 end")
    try:
        R.Reset()
        G.LayoutRoads(-9460.0, 60.0, 0, 0, 600.0, 130.0)
        while R.HasWork():
            R.Pump(clock() + 50, clock)
        G.LayoutRoads(-9460.0, 60.0, 0, 0, 600.0, 130.0)  # (its index for drawing)
        assert R.GraphReady(0)
        G.SetRoadMode(True)
        ns.db.tracks = lua.eval("{ { op = 'add', continent = 0, time = 11, pts = { -9300,300, -9250,350, -9200,420 } } }")
        Rec.Changed()  # (a road drawn with the tools on)
        assert R.GraphReady(0) and Rec.pending  # (no rebuild yet)
        segs = G.LayoutRoads(-9460.0, 60.0, 0, 0, 600.0, 130.0)
        s = 130.0 / 600.0
        dx, dy = multi(lua, ns.Geo.ScreenOffset, -9460.0, 60.0, -9200.0, 420.0)
        pts = [(segs[i][3], segs[i][4]) for i in range(1, len(segs) + 1)] + [(segs[i][1], segs[i][2]) for i in range(1, len(segs) + 1)]
        assert min(math.hypot(px - dx * s, py - dy * s) for px, py in pts) < 3  # (drawn at once)
        G.SetRoadMode(False)  # (the tools off: rebuilt now, once)
        assert not Rec.pending and not R.GraphReady(0)
    finally:
        G.SetRoadMode(False)
        R.WARM, R.SYNC_WALKS = False, True
        ns.db.tracks = None
        R.Reset()

"""Trips `agps route-check` flagged, kept as regressions (the addon's real roads and terrain).

Each checks what route-check checks: the route isn't far longer than the terrain grid's own
walk, and its off-road stretches don't cross impassable ground (away from the ends).
"""

import math

import pytest

lupa = pytest.importorskip("lupa")

from test_addon_lua import PRELUDE, load, route_pts  # noqa: E402

DETOUR = {"offroad": (1.4, 150), "road": (2.5, 300)}  # as routecheck.py
BLOCKED_RUN_YD, END_ALLOW_YD = 25, 60


@pytest.fixture(scope="module")
def world():
    lua = lupa.LuaRuntime()
    lua.execute(PRELUDE)
    ns = lua.table()
    ns.IsSecret = lua.eval("function(v) return false end")
    load(lua, ns, "Geo.lua", "Data/Roads.lua", "Data/Terrain.lua", "Passability.lua", "Router.lua")
    ns.Router.SYNC_WALKS = True
    return lua, ns


def grid_walk(ns, cont, sx, sy, tx, ty):
    P = ns.Passability
    limits = (P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS)
    P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS = 400000, 900 * 900
    try:
        ref = P.FindPath(cont, sx, sy, tx, ty)
    finally:
        P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS = limits
    return ref[0] if isinstance(ref, tuple) else ref


def blocked_run(ns, cont, pts, kinds, start, stop):
    """Longest run of impassable ground the route's off-road stretches cross."""
    worst = run = 0.0
    for i, k in enumerate(kinds):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        seg = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(seg / 3))
        for j in range(n + 1):
            x, y = x1 + (x2 - x1) * j / n, y1 + (y2 - y1) * j / n
            near_end = min(math.hypot(x - start[0], y - start[1]), math.hypot(x - stop[0], y - stop[1])) < END_ALLOW_YD
            if k == 1 and not near_end and ns.Passability.At(cont, x, y) == 2:
                run += seg / n
                worst = max(worst, run)
            else:
                run = 0.0
    return worst


def check_trip(world, cont, start, stop, mode):
    lua, ns = world
    ns.Router.Reset()
    r = ns.Router.Route(cont, *start, *stop, lua.table(offroad=(mode == "offroad")))
    pts, kinds = route_pts(r)
    walk = grid_walk(ns, cont, *start, *stop)
    assert walk is not None
    share, extra = DETOUR[mode]
    assert r.length <= max(walk * share, walk + extra), (r.length, walk)
    assert blocked_run(ns, cont, pts, kinds, start, stop) < BLOCKED_RUN_YD
    return r, walk


# Road mode walks straight there (around obstacles) when the roads go a long way round or
# are only reached across blocked ground (Router.ROAD_DIRECT_PENALTY).

def test_badlands_open_ground_between_ridges_no_loop_through_the_next_zones(world):
    # 389 yd apart in the middle of the Badlands, no road near: was a 15.8 km loop round
    # through Searing Gorge and Loch Modan, with legs over the ridges at both ends.
    r, _ = check_trip(world, 0, (-6716.9, -3378.6), (-6419.4, -3134.6), "road")
    assert r.length < 600


def test_alterac_stop_behind_a_ridge_is_walked_to_not_reached_over_it(world):
    # The last leg ran 371 yd straight over a ridge from a far-off road (1.3 km in all);
    # the walk round the ridge is 690 yd.
    r, _ = check_trip(world, 0, (106.4, -681.0), (-179.8, -190.9), "road")
    assert r.length < 900


def test_desolace_across_the_open_west_not_via_a_road_scrap_over_the_hills(world):
    check_trip(world, 1, (-2099.6, 1597.9), (-1707.0, 2864.0), "road")
    # and the ridge in the north-west: was 6.3 km round by the roads
    check_trip(world, 1, (-1177.8, 1319.5), (-1358.5, 1856.5), "road")


def test_road_mode_still_keeps_to_roads_that_are_only_somewhat_longer(world):
    # South of Razor Hill (Durotar) -> the Crossroads (Barrens): by the roads and the
    # Southfury bridge, not straight across country.
    lua, ns = world
    ns.Router.Reset()
    r = ns.Router.Route(1, -440.0, -4700.0, -450.0, -2640.0, lua.table(offroad=False))
    assert r.road > 0.8 * r.length


# A leg to or from the roads that the terrain blocks in a straight line, taken as a last
# resort (not one of the nearest few, which search the grid anyway), is walked around the
# obstacle once searched, like a gap between road pieces, instead of drawn over the ridge.

@pytest.mark.parametrize("cont, start, stop", [
    (0, (726.0, -579.9), (431.2, 207.7)),  # Alterac Mountains: over a ridge to the stop
    (0, (1039.2, -3791.9), (-73.4, -3558.4)),  # The Hinterlands: 360 yd over the hills
    (0, (-8771.7, -2812.3), (-9692.5, -3239.2)),  # Redridge Mountains: 313 yd
])
def test_blocked_legs_to_the_roads_are_walked_around(world, cont, start, stop):
    lua, ns = world
    ns.Router.ROAD_DIRECT_PENALTY = 1e9  # (the roads only: not walked straight there instead)
    try:
        ns.Router.Reset()
        r = ns.Router.Route(cont, *start, *stop, lua.table(offroad=False))
        pts, kinds = route_pts(r)
        assert r.road > 0
        assert blocked_run(ns, cont, pts, kinds, start, stop) < BLOCKED_RUN_YD
    finally:
        ns.Router.ROAD_DIRECT_PENALTY = 2


@pytest.fixture(scope="module")
def caves_world():
    # (route-check's: the caves', capitals' and buildings' grids and roads too)
    from azerothgps.routecheck import _runtime

    return _runtime()


def test_dun_algaz_goes_round_by_the_road_not_through_the_mountain(caves_world):
    # (reported, a screenshot) from the Dun Algaz road north: a 276 yd straight link through the mountain
    # from one cave mouth's road to another's (a gap link joining road pieces nothing else joined); the road
    # round, drawn in game, joins them now, and the route takes it
    lua, ns = caves_world
    ns.Router.Reset()
    r = ns.Router.Route(0, -4325.0, -2395.0, -4055.0, -2449.0, lua.table(offroad=False))
    pts, kinds = route_pts(r)
    assert r.length < 450
    assert max(math.dist(pts[i], pts[i + 1]) for i, k in enumerate(kinds) if k == 1) < 60


def test_ironforge_to_the_wetlands_by_the_roads(caves_world):
    # (reported, a screenshot: a straight line over the mountains, "Walk 2.2k yd") a road drawn by Dun
    # Algaz's cave mouths, once shipped, was a piece of its own nearer the Wetlands' roads than Dun Algaz's;
    # the gap link joining them, under BRIDGE_SHORT, was one of the nearest few per node, and the cave
    # mouth's shorter ones pushed it out: the Wetlands cut off from the south (every joining link kept now)
    lua, ns = caves_world
    for start in ((-5010.0, -800.0), (-8900.0, 600.0)):  # Ironforge's gate, Stormwind
        ns.Router.Reset()
        r = ns.Router.Route(0, *start, -3900.0, -2700.0, lua.table(offroad=False))
        assert not r.unconnected and r.road > 0.8 * r.length, start


def test_a_shipped_drawn_road_joins_the_cave_mouths_roads(caves_world):
    # (the same road: drawn in game from one cave mouth's road to another's, its ends joined them there;
    # shipped, the data's build joins drawn roads to the land's roads only) a loose end within TRACK_SNAP
    # of a cave's mouth joins it (Router.JoinDrawnEnds)
    lua, ns = caves_world
    ns.Router.Reset()
    ns.Router.Route(0, -4325.0, -2395.0, -4055.0, -2449.0, lua.table(offroad=False))
    g = ns.Router.DebugGraph(0)
    for end in ((-4097.1, -2465.9), (-4092.7, -2435.7)):
        n = min(range(1, int(g.count) + 1), key=lambda i: math.dist((g.n[2 * i - 1], g.n[2 * i]), end))
        assert math.dist((g.n[2 * n - 1], g.n[2 * n]), end) < 1 and len(g.adj[n]) >= 2, end

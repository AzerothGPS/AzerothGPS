"""Frame budget: work that runs while the game plays must pause often, never freeze a frame.

Lag spikes have come back more than once (the first road display after a /reload, road and wall
edits): each check here is one of them. Times are CPU milliseconds under lupa, a little slower
than the game's Lua; the limits leave room for that and are far below the spikes they catch.
"""

import pytest

from azerothgps.routecheck import _runtime

FRAME_MS = 40  # the longest a single slice of background work may run (the spikes were 100-300)


@pytest.fixture(scope="module")
def game():
    lua, ns = _runtime()
    lua.execute("GetTime = function() return os.clock() end")
    return lua, ns


def _drawn(lua, cont, x, y, n=8):
    """n drawn roads and a drawn wall near (x, y), as the road and wall tools save them."""
    rows = [f"{{ op = 'add', continent = {cont}, time = {i}, pts = {{ {x + i * 40},{y}, {x + i * 40 + 60},{y + 60}, "
            f"{x + i * 40 + 110},{y + 140} }} }}" for i in range(1, n + 1)]
    rows.append(f"{{ op = 'wall', continent = {cont}, time = 99, pts = {{ {x},{y - 50}, {x + 100},{y - 50} }} }}")
    return lua.eval("{ " + ", ".join(rows) + " }")


@pytest.mark.parametrize("cont, x, y", [(0, -9460.0, 60.0), (1, -450.0, -2650.0), (2991, 3000.0, 1000.0)])
def test_the_road_network_rebuilds_in_short_slices(game, cont, x, y):
    lua, ns = game
    R = ns.Router
    ns.db.tracks = _drawn(lua, cont, x, y)
    R.WARM, R.SYNC_WALKS = True, False
    try:
        ns.Passability.RefreshWalls()
        R.Reset()  # (as after a road or wall edit, or a /reload)
        R.WarmUp(cont, x, y)
        clock = lua.eval("function() return os.clock() * 1000 end")
        worst = 0.0
        while R.HasWork():
            a = clock()
            R.Pump(clock() + 1, clock)
            worst = max(worst, clock() - a)
        assert worst < FRAME_MS, f"a slice of the rebuild ran {worst:.0f} ms"
    finally:
        R.WARM, R.SYNC_WALKS = False, True
        ns.db.tracks = None
        ns.Passability.RefreshWalls()
        R.Reset()


def test_showing_the_roads_never_builds_them_in_the_frame(game):
    lua, ns = game
    G, R = ns.GPS, ns.Router
    R.WARM, R.SYNC_WALKS = True, False
    try:
        R.Reset()
        clock = lua.eval("function() return os.clock() * 1000 end")
        a = clock()
        G.LayoutRoads(-9460.0, 60.0, 0, 0, 600.0, 130.0)
        assert clock() - a < FRAME_MS
        assert not R.GraphReady(0)  # (left to the background work)
    finally:
        R.WARM, R.SYNC_WALKS = False, True
        while R.HasWork():
            R.Pump(1e18, lua.eval("function() return 0 end"))
        R.Reset()

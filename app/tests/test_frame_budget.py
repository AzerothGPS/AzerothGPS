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
    # (Undercity's level too: routes through its flight master built its roads in the frame)
    from azerothgps.routecheck import ADDON_DIR
    loader = lua.eval("function(src, name) return assert(load(src, '@' .. name)) end")
    for name in ("Data/Transports.lua", "Data/Cities.lua"):
        loader((ADDON_DIR / name).read_text(encoding="utf-8"), name)("AzerothGPS", ns)
    assert ns.Roads[10001]
    return lua, ns


def _drawn(lua, cont, x, y, n=8):
    """n drawn roads and a drawn wall near (x, y), as the road and wall tools save them."""
    rows = [f"{{ op = 'add', continent = {cont}, time = {i}, pts = {{ {x + i * 40},{y}, {x + i * 40 + 60},{y + 60}, "
            f"{x + i * 40 + 110},{y + 140} }} }}" for i in range(1, n + 1)]
    rows.append(f"{{ op = 'wall', continent = {cont}, time = 99, pts = {{ {x},{y - 50}, {x + 100},{y - 50} }} }}")
    return lua.eval("{ " + ", ".join(rows) + " }")


# (and Undercity, 10001: its roads were built in the frame on a route through its flight master)
@pytest.mark.parametrize("cont, x, y", [(0, -9460.0, 60.0), (1, -450.0, -2650.0), (2991, 3000.0, 1000.0),
                                        (10001, 1600.0, 240.0)])
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
        assert R.GraphReady(cont)  # (built: not a level with no roads here)
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


def test_merging_many_drawn_roads_stays_cheap(game):
    """Every road or wall edit merges all the drawn roads not in the data yet into the network:
    that has to stay cheap as they pile up in a session (40 took about a second before)."""
    lua, ns = game
    rows = [f"{{ op = 'add', continent = 0, time = {i}, pts = {{ {-9460 + i * 37},{60 + (i % 5) * 50}, "
            f"{-9400 + i * 37},{120 + (i % 5) * 50}, {-9350 + i * 37},{200 + (i % 5) * 50} }} }}" for i in range(1, 41)]
    tracks = lua.eval("{ " + ", ".join(rows) + " }")
    clock = lua.eval("function() return os.clock() * 1000 end")
    a = clock()
    ns.Router.WithTracks(ns.Roads[0], tracks, 0)
    assert clock() - a < 250, f"merging 40 drawn roads took {clock() - a:.0f} ms"


@pytest.mark.parametrize("cont", [0, 1])
def test_cave_entrances_are_worked_out_within_a_frame(game, cont):
    lua, ns = game
    clock = lua.eval("function() return os.clock() * 1000 end")
    a = clock()
    ns.GPS.CaveEntrances(cont)
    assert clock() - a < FRAME_MS

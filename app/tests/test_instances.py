"""Dungeons and raids as their own levels (Data/Instances.lua): routing inside, and in through
the portal from outside. The addon's Lua runs under lupa (see test_addon_lua.py)."""

import math

import pytest

from test_addon_lua import env, load, nav_env  # noqa: F401 (fixtures)

pytest.importorskip("lupa")

DM = 20036  # the Deadmines' level (instances.LEVEL_BASE + its MapID)
WC = 20043  # Wailing Caverns'
DM_INSIDE = (-14.6, -385.5)  # where the portal puts you
VANCLEEF = (-87.4, -819.9)
SENTINEL_HILL = (-10630.0, 1040.0)  # Westfall, on the continent


@pytest.fixture
def inst_env(nav_env):  # noqa: F811
    lua, ns = nav_env
    # (as the toc: the caves and capitals too; the instances after them)
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua", "Data/Caves.lua", "Data/Capitals.lua",
         "Data/Instances.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    return lua, ns


def pts_kinds(r):
    flat = [r.pts[i] for i in range(1, len(r.pts) + 1)]
    kinds = [r.kinds[i] for i in range(1, len(r.kinds) + 1)]
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)], kinds


def boss(ns, level, name):
    bs = ns.Instances[level].bosses
    return next(bs[i] for i in range(1, len(bs) + 1) if bs[i][1] == name)


def test_instances_load_as_levels(inst_env):
    lua, ns = inst_env
    lvl = ns.CityLevels[DM]
    assert lvl.base == 36 and lvl.instance and lvl.name == "Deadmines"
    assert ns.Geo.Base(DM) == 36
    assert ns.Nav.PlayerLevel(36) == DM  # (the game reports the instance's map inside it)
    assert ns.Nav.PlayerLevel(0) == 0
    inst = ns.Instances[DM]
    names = [inst.bosses[i][1] for i in range(1, len(inst.bosses) + 1)]
    assert "Edwin VanCleef" in names and "Rhahk'Zor" in names
    b = boss(ns, DM, "Edwin VanCleef")
    assert b.order and len(b.enc) >= 1
    assert ns.Passability.IsOpen(DM, *DM_INSIDE)
    assert ns.Nav.CityHeight(DM, *DM_INSIDE) == pytest.approx(62, abs=4)  # (the entering spot's height)


def test_route_to_a_boss_follows_the_instances_roads(inst_env):
    lua, ns = inst_env
    R, P = ns.Router, ns.Passability
    r = R.Route(DM, *DM_INSIDE, *VANCLEEF, lua.table(offroad=False))
    pts, kinds = pts_kinds(r)
    assert r.length > 800  # (down the mine, through the foundry, out to the cove)
    road = sum(math.dist(pts[i], pts[i + 1]) for i, k in enumerate(kinds) if k == 0)
    assert road / r.length > 0.9
    assert math.dist(pts[-1], VANCLEEF) < 1
    # the legs off the roads stay on the floors (but for a few yards where the mine's tunnel
    # comes out into the cove: the floors don't quite meet there)
    bad = 0.0
    for i, k in enumerate(kinds):
        if k == 1:
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            n = max(1, int(math.dist(pts[i], pts[i + 1])))
            bad += sum(1 for s in range(1, n) if not P.IsOpen(DM, x1 + (x2 - x1) * s / n, y1 + (y2 - y1) * s / n))
    assert bad <= 8


def test_route_from_outside_to_a_boss_takes_the_portal(inst_env):
    lua, ns = inst_env
    N = ns.Nav
    legs, secs = N.Plan(0, *SENTINEL_HILL, 7.0, lua.table(x=VANCLEEF[0], y=VANCLEEF[1], cont=DM))
    kinds = ["ride" if legs[i].ride else "walk" for i in range(1, len(legs) + 1)]
    assert kinds == ["walk", "ride", "walk"]
    ride = legs[2].ride
    assert ride[8] == "portal" and {ride[1], ride[4]} == {0, DM}
    assert legs[1].cont == 0 and legs[3].cont == DM
    # the walk to the portal ends in the mine under Moonbrook, and the one inside starts
    # where the portal puts you
    assert math.dist((legs[1].x2, legs[1].y2), (-11208.7, 1675.9)) < 10
    assert math.dist((legs[3].x1, legs[3].y1), DM_INSIDE) < 1
    # the whole route: walked on the continent, the portal, then the instance's roads
    N.SetStops(lua.table(lua.table(x=VANCLEEF[0], y=VANCLEEF[1], cont=DM, name="Edwin VanCleef")))
    r = N.Route(*SENTINEL_HILL, 0)
    assert r and r.parts
    conts = [r.parts[i].cont for i in range(1, len(r.parts) + 1)]
    assert conts[0] == 0 and conts[-1] == DM


def test_route_out_of_an_instance_takes_the_portal_back(inst_env):
    lua, ns = inst_env
    legs, _ = ns.Nav.Plan(DM, *VANCLEEF, 7.0, lua.table(x=SENTINEL_HILL[0], y=SENTINEL_HILL[1], cont=0))
    rides = [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride]
    assert len(rides) == 1 and rides[0][8] == "portal"


def test_continent_trips_take_no_portal(inst_env):
    lua, ns = inst_env
    # (Westfall to Stormwind: walked; a portal only leads into its instance)
    legs, _ = ns.Nav.Plan(0, *SENTINEL_HILL, 7.0, lua.table(x=-8900.0, y=560.0, cont=0))
    assert all(not legs[i].ride or legs[i].ride[8] != "portal" for i in range(1, len(legs) + 1))


def test_wailing_caverns_portal_is_in_its_cave(inst_env):
    lua, ns = inst_env
    rows = ns.Transports
    portal = next(rows[i] for i in range(1, len(rows) + 1) if rows[i][8] == "portal" and rows[i][4] == WC)
    assert portal[1] == 1
    # (the portal is down in the cave in front of the Wailing Caverns: over its floor)
    v = ns.Passability.OverlayRaw(1, portal[2], portal[3])
    v, grid = v if isinstance(v, tuple) else (v, None)
    assert grid is not None and grid.cave


def test_instance_map_view_helpers(inst_env):
    lua, ns = inst_env
    load(lua, ns, "GPSFrame.lua")
    G, P = ns.GPS, ns.Passability
    assert G.InstanceOf(DM) == DM and G.InstanceOf(0) is None and G.InstanceOf(10001) is None
    # the map fitted to the instance's grid: every boss and the way in are on it
    x0, x1, y0, y1 = P.GridBounds(DM)
    inst = ns.Instances[DM]
    for i in range(1, len(inst.bosses) + 1):
        b = inst.bosses[i]
        assert x0 <= b[3] <= x1 and y0 <= b[4] <= y1, b[1]
    assert x0 <= DM_INSIDE[0] <= x1 and y0 <= DM_INSIDE[1] <= y1
    # its floors filled in on the map (no art for dungeons): runs of open ground, and the outline
    for lvl in (DM, 20033):  # (Shadowfang Keep: showed nothing but thin lines over the game world)
        bx0, bx1, by0, by1 = P.GridBounds(lvl)
        G.ClearEdges()
        e = G.BlockEdges(lvl, (bx0 + bx1) / 2, (by0 + by1) / 2, max(bx1 - bx0, by1 - by0) / 2)
        assert len(e) > 400 and len(e.fill) > 300 and e.step <= 4
    # entrance icons per continent, at the continent end of the portal
    ents = G.InstanceEntrances(0)
    dm = [ents[i] for i in range(1, len(ents) + 1) if ents[i].level == DM]
    assert len(dm) == 1 and dm[0].cont == 0 and dm[0].x == pytest.approx(-11208.7, abs=0.2)
    names1 = {G.InstanceEntrances(1)[i].name for i in range(1, len(G.InstanceEntrances(1)) + 1)}
    assert "Wailing Caverns" in names1 and "Deadmines" not in names1
    # the Scarlet Monastery's wings share a spot: one icon on a continent's map
    sm = [ents[i] for i in range(1, len(ents) + 1) if "Scarlet Monastery" in ents[i].name]
    if len(sm) > 1:
        assert any(not e.shared for e in sm) and any(e.shared for e in sm)


def test_boss_kills_mark_boss_stops_done(inst_env):
    lua, ns = inst_env
    load(lua, ns, "GPSFrame.lua")
    N, G = ns.Nav, ns.GPS
    lua.execute('GetInstanceInfo = function() return "Deadmines", "party", 1, "Normal", 5, 0, false, 36 end')
    lua.execute("time = function() return 1000 end")
    assert N.CurrentInstance() == DM
    assert N.NpcOf("Creature-0-5250-36-12-639-00001A2B3C") == 639
    assert N.NpcOf("Player-5250-0ABCDEF1") is None
    # the route: the bosses in the usual order, the optional ones left out
    stops, dead = G.BossStops(DM)
    names = [stops[i].name for i in range(1, len(stops) + 1)]
    assert names[0] == "Rhahk'Zor" and names[-1] == "Edwin VanCleef" and dead == 0
    assert "Miner Johnson" not in names and "Cookie" not in names
    N.SetStops(stops, True)  # (kept in that order: a dungeon's level)
    assert N.stops[1].name == "Rhahk'Zor" and N.stops[1].boss == 644
    rz = boss(ns, DM, "Rhahk'Zor")
    # standing at the boss doesn't count: it has to die
    N.Status(rz[3], rz[4], 36)
    assert N.stops[1].name == "Rhahk'Zor"
    # its death in the combat log (by NPC entry): on to the next one
    assert N.BossKilled(DM, 644) == 1
    N.Status(rz[3], rz[4], 36)
    assert N.stops[1].name == "Sneed"
    # ENCOUNTER_END's DungeonEncounter id, from anywhere in the dungeon
    sneed = boss(ns, DM, "Sneed")
    assert N.BossKilled(DM, None, sneed.enc[1]) == 1
    N.Status(*DM_INSIDE, 36)
    assert N.stops[1].name == "Gilnid"
    # a new boss route leaves out the dead ones
    stops, dead = G.BossStops(DM)
    assert dead == 2 and stops[1].name == "Gilnid"
    # another instance, or hours later: started over
    lua.execute("time = function() return 1000 + 4 * 3600 end")
    assert not N.BossDead(lua.table(cont=DM, boss=644))
    assert N.BossKilled(WC, None, None, "no such boss") == 0
    assert not N.BossDead(lua.table(cont=DM, boss=644))


def test_instance_maps_use_the_games_minimap_art(inst_env):
    lua, ns = inst_env
    load(lua, ns, "Data/Interiors.lua", "Data/Instances.lua", "GPSFrame.lua")  # (Interiors.lua first, as the toc)
    G, P = ns.GPS, ns.Passability
    lua.execute("GetMinimapZoneText = function() return '' end IsIndoors = function() return true end")
    with_art = []
    for lvl in sorted(int(k) for k in ns.Instances.keys()):
        mid = ns.CityLevels[lvl].base
        places = ns.Interiors[mid]
        if not places:
            continue
        with_art.append(ns.Instances[lvl].name)
        # its models' art lies over its walk grid (same coordinates)
        x0, x1, y0, y1 = P.GridBounds(lvl)
        over = [places[i] for i in range(1, len(places) + 1)
                if places[i][8] >= x0 and places[i][6] <= x1 and places[i][9] >= y0 and places[i][7] <= y1]
        assert over, ns.Instances[lvl].name
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        zoom = max(x1 - x0, y1 - y0) / 2
        assert len(G.LayoutInstanceArt(cx, cy, lvl, 0, zoom, 200)) > 0, ns.Instances[lvl].name
    assert "Shadowfang Keep" in with_art and "Deadmines" in with_art and len(with_art) >= 20
    # floors: stacked ones apart (Shadowfang Keep's), a cave going down one (the Stockade's)
    SFK = 20033
    floors = G.InstanceFloors(SFK)
    assert len(floors) >= 3 and len(G.InstanceFloors(20034)) == 1
    lows = [floors[i][1] for i in range(1, len(floors) + 1)]
    assert lows == sorted(lows)
    # one floor's art is less than all of them
    x0, x1, y0, y1 = P.GridBounds(SFK)
    cx, cy, zoom = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) / 2
    every = len(G.LayoutInstanceArt(cx, cy, SFK, 0, zoom, 200))
    top = len(G.LayoutInstanceArt(cx, cy, SFK, 0, zoom, 200, floors[len(floors)]))
    assert 0 < top < every
    # the player's floor, by height: the one they stand on (counted from the top)
    ns.settings = lua.eval("{ gps = { zoom = 150 } }")
    assert G.ShownFloor(SFK, floors[1][1] + 1) == len(floors)
    assert G.ShownFloor(SFK, floors[len(floors)][1] + 1) == 1
    assert G.ShownFloor(SFK, None) == 0  # (not in it: all of them)


def test_right_click_leaves_a_dungeons_map_for_the_view_it_came_from(inst_env):
    lua, ns = inst_env
    load(lua, ns, "GPSFrame.lua")
    G = ns.GPS
    ns.settings = lua.eval("{ gps = { zoom = 500 } }")
    # from the terrain view, looking somewhere (not following)
    lua.eval("function(G) G.BrowseToTerrain() end")(G)  # (no browse: nothing happens)
    G.ShowEntrance(lua.table(0, -11208.7, 1675.9))  # the Deadmines' entrance, terrain view
    G.SetZoom(700)
    G.ShowInstance(DM)
    browse, free = G.BrowseState()
    assert free.instance == DM and free.cont == DM
    G.TerrainZoomOut()  # right-click (terrain style)
    browse, free = G.BrowseState()
    assert browse is None and free.cont == 0 and free.x == pytest.approx(-11208.7)
    assert ns.settings.gps.zoom == pytest.approx(700)  # (its zoom too)
    # from a zone's map (World Map style): back to that map
    westfall = next(k for k in ns.Maps.keys() if ns.Maps[k].name == "Westfall" and ns.Maps[k].type == 3)
    G.Browse(westfall)
    G.ShowInstance(DM)
    assert G.BrowseState()[0] is None
    G.ZoomOut()  # right-click (map style)
    assert G.BrowseState()[0] == westfall
    # following the player: back to following
    G.Follow()
    G.ShowInstance(DM)
    G.TerrainZoomOut()
    assert G.BrowseState()[1] is None


def test_mouse_wheel_steps_a_dungeons_floors(inst_env):
    lua, ns = inst_env
    load(lua, ns, "Data/Interiors.lua", "Data/Instances.lua", "GPSFrame.lua")
    G = ns.GPS
    ns.settings = lua.eval("{ gps = { zoom = 500 } }")
    lua.execute("UnitPosition = function() return nil end")
    SFK = 20033
    n = len(G.InstanceFloors(SFK))
    G.ShowInstance(SFK)
    fit = ns.settings.gps.zoom
    assert G.ShownFloor(SFK, None) == 0  # all floors
    # scrolling in: each floor down from the top, the zoom kept
    for k in range(1, n + 1):
        assert G.FloorWheel(1)
        assert G.ShownFloor(SFK, None) == k and ns.settings.gps.zoom == pytest.approx(fit)
    assert not G.FloorWheel(1)  # past the bottom floor: the usual zoom in
    G.SetZoom(fit * 0.64)
    # scrolling out: back to where the floors were stepped, then up them, then all, then zoom out
    assert G.FloorWheel(-1) and G.FloorWheel(-1)
    assert ns.settings.gps.zoom == pytest.approx(fit) and G.ShownFloor(SFK, None) == n
    for k in range(n - 1, -1, -1):
        assert G.FloorWheel(-1) and G.ShownFloor(SFK, None) == k
    assert not G.FloorWheel(-1)
    # one floor only (the Stockade): the wheel zooms
    G.ShowInstance(20034)
    assert not G.FloorWheel(1)


def test_dungeon_route_holds_off_other_routes(inst_env):
    lua, ns = inst_env
    load(lua, ns, "GPSFrame.lua")
    N, G = ns.Nav, ns.GPS
    ns.settings = lua.eval("{ gps = { zoom = 500, dungeonRoute = true } }")
    ns.Print = lua.eval("function() end")
    lua.execute('GetInstanceInfo = function() return "Deadmines", "party", 1, "Normal", 5, 0, false, 36 end')
    lua.execute("UnitPosition = function() return -14.6, -385.5, 62, 36 end")
    G.DungeonEntered()  # in: its boss route
    assert N.stops[1].name == "Rhahk'Zor" and N.DungeonLocked()
    other = lua.table(x=-100.0, y=-500.0, cont=DM, name="somewhere")
    assert not N.SetStops(lua.table(other))  # held off
    assert not N.AddStop(other)
    assert N.stops[1].name == "Rhahk'Zor"
    G.DungeonEntered()  # (a /reload in there: kept, not started over)
    assert N.stops[1].name == "Rhahk'Zor"
    G.SetDungeonRoute(False)  # off: routes are the player's
    assert len(N.stops) == 0 and not N.DungeonLocked()
    assert N.SetStops(lua.table(other))
    G.SetDungeonRoute(True)  # back on in there: the boss route again
    assert N.stops[1].name == "Rhahk'Zor"
    # out of the dungeon: its boss route ends
    lua.execute('GetInstanceInfo = function() return "Westfall", "none", 0, "", 0, 0, false, 0 end')
    G.DungeonEntered()
    assert len(N.stops) == 0 and not N.DungeonLocked()
    # the position hidden in there: not started
    lua.execute('GetInstanceInfo = function() return "Deadmines", "party", 1, "Normal", 5, 0, false, 36 end')
    lua.execute("UnitPosition = function() return nil end")
    G.DungeonEntered()
    assert len(N.stops) == 0

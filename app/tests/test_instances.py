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

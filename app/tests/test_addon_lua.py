"""Run the addon's pure Lua (layout math, generated data) under a standalone Lua."""

import math
import time
from pathlib import Path

import pytest

lupa = pytest.importorskip("lupa")

ADDON = Path(__file__).resolve().parents[2] / "addon" / "AzerothGPS"
TILE = 1600 / 3

PRELUDE = """
issecretvalue = nil
CreateFrame = function() error("no frames in tests") end
"""


def load(lua, ns, *names, data=None):
    loader = lua.eval("function(src, name) return assert(load(src, '@' .. name)) end")
    for name in names:
        src = (ADDON / name).read_text(encoding="utf-8")
        loader(src, name)("AzerothGPS", ns)
        if name == "Data/Terrain.lua":  # (the buildings and the grids by blocks with them, as the toc loads them)
            for extra in ("Data/Buildings.lua", "Data/TerrainHPA.lua"):
                loader((ADDON / extra).read_text(encoding="utf-8"), extra)("AzerothGPS", ns)


@pytest.fixture
def env():
    lua = lupa.LuaRuntime()
    lua.execute(PRELUDE)
    ns = lua.table()
    ns.IsSecret = lua.eval("function(v) return false end")
    load(lua, ns, "Geo.lua")
    # GPSFrame.lua only builds frames in G.Init(), so loading it is safe.
    load(lua, ns, "GPSFrame.lua")
    return lua, ns


def quads(lua, t):
    out = []
    for i in range(1, len(t) + 1):
        q = t[i]
        out.append([q[j] for j in range(1, 12)])
    return out


def centre_of_tile(tx, ty):
    return (32 - (ty + 0.5)) * TILE, (32 - (tx + 0.5)) * TILE  # world X, Y


def test_generated_data_loads(env):
    lua, ns = env
    load(lua, ns, "Data/Minimap.lua", "Data/Maps.lua")
    assert len(list(ns.MinimapTiles[1].keys())) > 900
    durotar = ns.Maps[1411]
    assert durotar.name == "Durotar" and durotar.artW == 1002
    assert len(durotar.overlays) > 5


def minimap_env(lua, ns):
    ns.MinimapTiles = lua.eval("{ [1] = {} }")
    for tx in range(38, 43):
        for ty in range(31, 36):
            ns.MinimapTiles[1][tx * 64 + ty] = 1000 * tx + ty


def by_fid(qs):
    return {int(q[0]): q for q in qs}


def test_north_up_tiles(env):
    lua, ns = env
    minimap_env(lua, ns)
    half, zoom = 100.0, 1000.0  # far enough out that neighbouring tiles aren't cropped
    s = half / zoom
    px, py = centre_of_tile(40, 33)
    qs = by_fid(quads(lua, ns.GPS.LayoutMinimap(px, py, 1, 0, zoom, half)))
    assert qs[40033][1:3] == pytest.approx([0, 0], abs=1e-6)
    assert qs[41033][1:3] == pytest.approx([TILE * s, 0])  # next tile east -> right
    assert qs[40034][1:3] == pytest.approx([0, -TILE * s])  # next tile south -> down
    assert qs[40033][3] == pytest.approx(TILE * s + 1)


def test_heading_up_puts_facing_direction_on_top(env):
    lua, ns = env
    minimap_env(lua, ns)
    half, zoom = 100.0, 1000.0
    s = half / zoom
    px, py = centre_of_tile(40, 33)
    facing_west = math.pi / 2  # WoW facing: counter-clockwise from north
    qs = by_fid(quads(lua, ns.GPS.LayoutMinimap(px, py, 1, -facing_west, zoom, half)))
    assert qs[39033][1:3] == pytest.approx([0, TILE * s], abs=1e-6)  # west tile now straight up
    assert qs[40032][1:3] == pytest.approx([TILE * s, 0], abs=1e-6)  # north tile now to the right
    assert qs[39033][5] == pytest.approx(-facing_west)


def test_only_nearby_tiles(env):
    lua, ns = env
    minimap_env(lua, ns)
    px, py = centre_of_tile(40, 33)
    qs = quads(lua, ns.GPS.LayoutMinimap(px, py, 1, 0, 100.0, 100.0))
    assert 1 <= len(qs) <= 9
    assert quads(lua, ns.GPS.LayoutMinimap(px, py, 0, 0, 100.0, 100.0)) == []  # no tiles for continent 0


def test_zone_art_placement(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua")
    m = ns.Maps[1411]
    minX, minY, maxX, maxY = (m.bounds[i] for i in range(1, 5))
    # Player at the world point under art pixel (128, 128): centre of the first base tile.
    px = maxX - 128 * (maxX - minX) / m.artH
    py = maxY - 128 * (maxY - minY) / m.artW
    qs = quads(lua, ns.GPS.LayoutZone(px, py, 1411, 0, 3000.0, 100.0))
    first_tile_fid = m.tiles[1][1]
    q = next(q for q in qs if q[0] == first_tile_fid and q[10] == 0)
    assert q[1:3] == pytest.approx([0, 0], abs=0.01)
    assert any(q[10] == 1 for q in qs)  # explored overlays included, drawn above


def test_generated_roads_load(env):
    lua, ns = env
    load(lua, ns, "Data/Roads.lua")
    kal = ns.Roads[1]
    assert len(kal.e) > 100
    e = kal.e[1]
    assert (len(e) - 4) % 2 == 0 and len(e) >= 8  # a, b, len, src, then x/y pairs


def test_layout_roads_in_view_only(env):
    lua, ns = env
    ns.Roads = lua.eval("""{ [1] = { n = {0,0, 0,-100, 5000,5000, 5000,5100},
        e = { {1,2,100,0, 0,0, 0,-50, 0,-100}, {3,4,100,0, 5000,5000, 5000,5100} } } }""")
    segs = quads(lua, ns.GPS.LayoutRoads(0.0, 0.0, 1, 0, 200.0, 100.0))
    assert len(segs) == 2  # only the nearby edge (two segments)
    # Road runs from the player due east (world Y decreasing): screen +x.
    s1 = segs[0]
    assert s1[0:2] == pytest.approx([0, 0]) and s1[2] == pytest.approx(25) and s1[3] == pytest.approx(0)


@pytest.mark.parametrize("name", sorted(str(p.relative_to(ADDON)) for p in ADDON.rglob("*.lua")))
def test_every_addon_file_compiles(name):
    lua = lupa.LuaRuntime()
    ok, err = lua.eval("function(src, n) local f, e = load(src, '@' .. n); return f ~= nil, e end")(
        (ADDON / name).read_text(encoding="utf-8"), name)
    assert ok, err


def test_toc_lists_every_file():
    toc = (ADDON / "AzerothGPS.toc").read_text(encoding="utf-8").splitlines()
    listed = {l.strip().replace("\\", "/") for l in toc if l.strip() and not l.startswith("#")}
    files = {str(p.relative_to(ADDON)).replace("\\", "/") for p in ADDON.rglob("*.lua")}
    assert listed == files


def test_pan_north_up(env):
    lua, ns = env
    # Drag the map 10 UI units right at 2 units/yd: the view moves 5 yd west (world Y +5).
    x, y = ns.GPS.PanCenter(100.0, 200.0, 10.0, 0.0, 0.0, 2.0)
    assert (x, y) == pytest.approx((100.0, 205.0))
    # Drag up: the view moves south (world X -5).
    x, y = ns.GPS.PanCenter(100.0, 200.0, 0.0, 10.0, 0.0, 2.0)
    assert (x, y) == pytest.approx((95.0, 200.0))


def test_pan_heading_up(env):
    lua, ns = env
    # Facing west (west is up on screen, rot = -pi/2). Dragging the map up moves the
    # view "down" on screen, which is east in the world (world Y decreases).
    x, y = ns.GPS.PanCenter(0.0, 0.0, 0.0, 10.0, -math.pi / 2, 1.0)
    assert (x, y) == pytest.approx((0.0, -10.0), abs=1e-9)


INTERIOR = """
ns.WMOs = { [42] = { groups = {
  { -50, -50, -20, 50, 50, 0, n = "Lower Hall", ["in"] = true, blocks = { {111, 0, 0, 200, 200} } },
  { 60, -10, -18, 90, 10, -2, n = "", ["in"] = true, blocks = { {444, 0, 0, 60, 40} } },
  { -50, -50, 10, 50, 50, 30, n = "Upper Hall", ["in"] = true, blocks = { {222, 0, 0, 200, 200} } },
  { -10, -10, -20, 10, 10, 0, n = "Closet", ["in"] = true, blocks = { {333, 0, 0, 40, 40} } },
} } }
ns.Interiors = { [0] = { {42, 1000, 2000, 50, math.pi, 900, 1900, 1100, 2100} } }
"""


@pytest.fixture
def interior_env(env):
    lua, ns = env
    lua.eval("function(ns, src) return assert(load(src))(nil, ns) end")
    loader = lua.eval("function(src) return assert(load('local _, ns = ...; ' .. src)) end")
    loader(INTERIOR)(None, ns)
    return lua, ns


def test_find_interior_in_a_city_by_its_floor_height(interior_env):
    # (reported) no room name, the game says outdoors: down in a city its floor height finds the room
    lua, ns = interior_env
    assert ns.GPS.FindInterior(970.0, 1970.0, 0, 0, "", False)[0] is None
    place, wmo, room = ns.GPS.FindInterior(970.0, 1970.0, 0, 0, "", False, -15, 42)
    assert room.n == "Lower Hall"
    place, wmo, room = ns.GPS.FindInterior(970.0, 1970.0, 0, 0, "", False, 19, 42)
    assert room.n == "Upper Hall"


def test_find_interior_by_zone_text(interior_env):
    lua, ns = interior_env
    place, wmo, room = ns.GPS.FindInterior(1000 - 30.0, 2000 - 30.0, 0, 0, "Upper Hall", True)
    assert room.n == "Upper Hall"
    place, wmo, room = ns.GPS.FindInterior(1000 - 30.0, 2000 - 30.0, 0, 0, "Lower Hall", True)
    assert room.n == "Lower Hall"
    # Game says outdoors (as it does all over Undercity), but the minimap names the room.
    place, wmo, room = ns.GPS.FindInterior(1000 - 30.0, 2000 - 30.0, 0, 0, "Lower Hall", False)
    assert room.n == "Lower Hall"
    # No name match but the game says indoors: smallest indoor room containing the point.
    place, wmo, room = ns.GPS.FindInterior(1000.0, 2000.0, 0, 0, "", True)
    assert room.n == "Closet"
    # Neither a name match nor indoors: not inside (e.g. walking past a building).
    assert ns.GPS.FindInterior(1000.0, 2000.0, 0, 0, "Durotar", False)[0] is None
    assert ns.GPS.FindInterior(5000.0, 5000.0, 0, 0, "", True)[0] is None


def test_find_interior_uses_height_when_known(interior_env):
    lua, ns = interior_env
    place, wmo, room = ns.GPS.FindInterior(1000 - 30.0, 2000 - 30.0, 50 + 20.0, 0, "")
    assert room.n == "Upper Hall"


def test_a_city_model_s_streets_are_outside_with_the_height_known(interior_env):
    # (reported: Stormwind's map switched between its own art and the terrain with the zoom) with the
    # player's height known, a model's outdoor pieces (a city's streets) aren't "inside": only its
    # indoor rooms, or where the game says indoors
    lua, ns = interior_env
    loader = lua.eval("function(src) return assert(load('local _, ns = ...; ' .. src)) end")
    loader("""
      ns.WMOs[43] = { groups = {
        { -100, -100, -5, 100, 100, 30, n = "", ["in"] = false, blocks = { {555, 0, 0, 400, 400} } },
        { 20, 20, -2, 40, 40, 10, n = "The Gilded Rose", ["in"] = true, blocks = { {666, 0, 0, 40, 40} } },
      } }
      table.insert(ns.Interiors[0], { 43, 3000, 3000, 0, 0, 2900, 2900, 3100, 3100 })
    """)(None, ns)
    G = ns.GPS
    assert G.FindInterior(3050.0, 3060.0, 2.0, 0, "Trade District", False)[0] is None  # a street
    place, _w, room = G.FindInterior(3030.0, 3030.0, 2.0, 0, "The Gilded Rose", True)  # in the inn
    assert place and room.n == "The Gilded Rose"
    # (the game says indoors: its indoor rooms and, as ever, whatever it's in there)
    assert G.FindInterior(3050.0, 3060.0, 2.0, 0, "", True)[0] is not None


def test_stormwind_keeps_the_terrain_map(env):
    # (reported twice: zoomed in on Stormwind's streets the map switched to the city's own art; then
    # asked: no inside map from Stormwind's model at all, it looks worse than the terrain) every piece
    # of its model has art and a district's name, so the minimap's zone text matched
    lua, ns = env
    load(lua, ns, "Data/Interiors.lua")
    G = ns.GPS
    street = (-8832.0, 625.0)  # (the Trade District)
    for z in (0, 97.0):  # (the height unknown, or known)
        for indoors in (False, True):
            place = G.FindInterior(*street, z, 0, "Trade District", indoors)[0]
            assert place is None or place[1] not in G.NO_INSIDE_MAP, (z, indoors)


def test_layout_interior_floor_and_rotation(interior_env):
    lua, ns = interior_env
    place, wmo, room = ns.GPS.FindInterior(1000 - 30.0, 2000 - 30.0, 0, 0, "Lower Hall", True)
    qs = quads(lua, ns.GPS.LayoutInterior(1000.0, 2000.0, place, wmo, room, 0, 100.0, 100.0))
    fids = sorted(int(q[0]) for q in qs)
    assert fids == [111, 333, 444]  # the lower floor (incl. its corridor), not the upper hall
    lower = next(q for q in qs if q[0] == 111)
    # Block covers local x,y in [-50, 50]: centred on the building origin.
    assert lower[1:3] == pytest.approx([0, 0], abs=1e-6)
    assert lower[3] == pytest.approx(100 + 0.5)  # 200 px at 2 px/yd = 100 yd at 1 unit/yd
    assert lower[5] == pytest.approx(math.pi + math.pi / 2)  # building turned 180 degrees


def test_undercity_rooms_match_in_game_readings(env):
    """Positions and minimap zone texts reported in game (/agps debug interior)."""
    lua, ns = env
    load(lua, ns, "Data/Interiors.lua")
    for x, y, zone in ((1527.6, 223.9, "Trade Quarter"), (1643.8, 245.7, "Ruins of Lordaeron")):
        place, wmo, room = ns.GPS.FindInterior(x, y, 0, 0, zone, False)
        assert place is not None and place[1] == 7675285
        assert room.n == zone


def test_generated_interiors_include_undercity(env):
    lua, ns = env
    load(lua, ns, "Data/Interiors.lua")
    uc = [ns.Interiors[0][i] for i in range(1, len(ns.Interiors[0]) + 1) if ns.Interiors[0][i][1] == 7675285]
    assert uc, "Forever's Undercity placement missing"
    groups = ns.WMOs[7675285].groups
    assert any(groups[i].n == "War Quarter" for i in range(1, len(groups) + 1))


def test_screen_to_world_inverts_layout(env):
    lua, ns = env
    # A point 30 yd north and 40 yd east of the centre, drawn heading-up facing west.
    rot, s = -math.pi / 2, 2.0
    dx, dy = ns.Geo.ScreenOffset(100.0, 200.0, 130.0, 160.0)  # world (130, 160): +30 X (north), -40 Y (east)
    sx, sy = ns.Geo.Rotate(dx * s, dy * s, rot)
    x, y = ns.GPS.ScreenToWorld(100.0, 200.0, sx, sy, rot, s)
    assert (x, y) == pytest.approx((130.0, 160.0))


def test_zone_at_and_fit(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua")
    durotar = ns.Maps[1411]
    b = durotar.bounds
    assert ns.GPS.ZoneAt((b[1] + b[3]) / 2, (b[2] + b[4]) / 2, 1414) == 1411
    assert ns.GPS.MapFitZoom(durotar) == pytest.approx(max(b[3] - b[1], b[4] - b[2]) / 2 * 1.02)
    assert ns.GPS.DisplayMap(1411) == 1411


# ---- Router -------------------------------------------------------------------------

L_ROADS = """
-- An L: A(0,0) -> B(0,-1000) -> C(1000,-1000) in world X/Y (B is 1000 yd east of A, C 1000 yd north of B).
ns.Roads = { [1] = { n = { 0,0, 0,-1000, 1000,-1000 },
  e = { {1,2,1000,0, 0,0, 0,-500, 0,-1000}, {2,3,1000,0, 0,-1000, 500,-1000, 1000,-1000} } } }
"""


@pytest.fixture
def router(env):
    lua, ns = env
    load(lua, ns, "Router.lua")
    lua.eval("function(src) return assert(load('local _, ns = ...; ' .. src)) end")(L_ROADS)(None, ns)
    ns.Router.Reset()
    return lua, ns


def route_pts(r):
    pts = [r.pts[i] for i in range(1, len(r.pts) + 1)]
    return list(zip(pts[0::2], pts[1::2])), [r.kinds[i] for i in range(1, len(r.kinds) + 1)]


def test_route_follows_roads(router):
    lua, ns = router
    # From 30 yd west of A to 30 yd north of C: along both legs of the L.
    r = ns.Router.Route(1, 0.0, 30.0, 1030.0, -1000.0)
    pts, kinds = route_pts(r)
    assert kinds[0] == 1 and kinds[-1] == 1  # off-road legs at both ends
    assert all(k == 0 for k in kinds[1:-1])  # road in between
    assert pts[1] == pytest.approx((0, 0), abs=1e-6)  # joins the road at the nearest point
    assert (0, -1000) in [tuple(round(v) for v in p) for p in pts]  # passes the corner B
    assert r.length == pytest.approx(30 + 1000 + 1000 + 30, abs=0.5)
    assert r.road == pytest.approx(2000, abs=0.5)


def test_route_exits_at_closest_point(router):
    lua, ns = router
    # Destination beside the middle of the second leg: leave the road there.
    r = ns.Router.Route(1, 0.0, 30.0, 500.0, -1040.0)
    pts, kinds = route_pts(r)
    assert pts[-2] == pytest.approx((500, -1000), abs=1e-6)
    assert pts[-1] == pytest.approx((500, -1040))


def test_straight_line_when_shorter(router):
    lua, ns = router
    # Both points far from any road and close together: no detour to the road.
    r = ns.Router.Route(1, 500.0, 500.0, 520.0, 480.0)
    pts, kinds = route_pts(r)
    assert kinds == [1] and len(pts) == 2


def test_same_edge(router):
    lua, ns = router
    r = ns.Router.Route(1, 10.0, -100.0, 10.0, -900.0)  # both beside the first leg
    pts, kinds = route_pts(r)
    assert kinds[0] == 1 and kinds[-1] == 1
    assert r.road == pytest.approx(800, abs=0.5)


def test_real_route_razor_hill_to_crossroads(env):
    lua, ns = env
    load(lua, ns, "Data/Roads.lua", "Router.lua")
    # South of Razor Hill (Durotar) -> the Crossroads (Barrens): north to Razor Hill,
    # west over the Southfury bridge, then the Barrens road.
    r = ns.Router.Route(1, -440.0, -4700.0, -450.0, -2640.0)
    straight = math.hypot(-440 + 450, -4700 + 2640)
    assert r.road > 0.8 * r.length  # mostly on roads
    assert straight < r.length < straight * 2.2


def test_destination_survives_reload(env):
    lua, ns = env
    lua.execute("GetTime = function() return 0 end")
    store = lua.eval("{}")
    ns.db = lua.eval("{}")
    ns.CharDB = lua.eval("function(store) return function() return store end end")(store)
    load(lua, ns, "Router.lua", "Nav.lua")
    ns.Nav.SetDestination(-600.0, -4180.0, 1, "Sen'jin Village")
    assert store.stops[1].x == -600.0 and store.stops[1].name == "Sen'jin Village"
    # Simulate /reload: fresh Nav module, same saved variables.
    load(lua, ns, "Nav.lua")
    assert ns.Nav.dest is None
    ns.Nav.Restore()
    assert ns.Nav.dest.y == -4180.0 and ns.Nav.dest.cont == 1
    ns.Nav.Clear()
    assert store.stops is None
    # a save from before multi-stop routes (single `dest`) still loads
    store.dest = lua.eval("{ x = 1, y = 2, cont = 0, name = 'old' }")
    ns.Nav.Restore()
    assert ns.Nav.dest.name == "old" and len(ns.Nav.stops) == 1


def test_unnamed_corridor_on_the_named_floor(interior_env):
    lua, ns = interior_env
    # Local (75, 0) is only inside the unnamed corridor, which is on the "Lower Hall" floor.
    # Building turned 180 degrees: world = origin - local.
    place, wmo, room = ns.GPS.FindInterior(1000 - 75.0, 2000 - 0.0, 0, 0, "Lower Hall", False)
    assert room.n == "" and room[1] == 60
    # Same spot, but the minimap names the upper floor: the corridor is not on it.
    place, wmo, room = ns.GPS.FindInterior(1000 - 75.0, 2000 - 0.0, 0, 0, "Upper Hall", False)
    assert room.n == "Upper Hall"  # nearest room on that floor


def test_no_interior_without_any_signal(interior_env):
    lua, ns = interior_env
    assert ns.GPS.FindInterior(1000 - 75.0, 2000 - 0.0, 0, 0, "Durotar", False)[0] is None


def test_locate_world(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua")
    # Durotar map coordinates of the in-game UnitPosition sample (0.46798, 0.674273).
    mid, name, mx, my = ns.GPS.LocateWorld(1, -568.5, -4436.9)
    assert name == "Durotar"
    assert (mx, my) == pytest.approx((0.46798, 0.674273), abs=1e-4)
    # Inside Orgrimmar the city map wins over Durotar (smallest containing map).
    b = ns.Maps[1454].bounds
    assert ns.GPS.LocateWorld(1, (b[1] + b[3]) / 2, (b[2] + b[4]) / 2)[1] == "Orgrimmar"


def test_layout_pois_faction_and_view(env):
    lua, ns = env
    ns.Pois = lua.eval("""{ [1] = {
      {1, 100, 0, "Horde FM", 23, "H"}, {1, 0, 100, "Alliance FM", 26, "A"}, {1, -100, 0, "Neutral FM", 80, "AH"},
      {2, 0, -100, "A cave", 3}, {3, 50, 50, "Some Farm", 14}, {1, 9000, 9000, "Far away", 99, "H"} } }""")
    show = lua.table(True, True, False)
    pois = quads(lua, ns.GPS.LayoutPois(0.0, 0.0, 1, 0, 200.0, 100.0, show, "H"))
    names = {p[3] for p in pois}
    assert names == {"Horde FM", "Neutral FM", "A cave"}  # other faction, labels off, out of view
    hfm = next(p for p in pois if p[3] == "Horde FM")
    assert hfm[1:3] == pytest.approx([0, 50])  # 100 yd north at 0.5 units/yd -> straight up
    assert hfm[4:6] == pytest.approx([100, 0])  # world position kept for routing


def test_generated_pois(env):
    lua, ns = env
    load(lua, ns, "Data/Pois.lua")
    kal = [ns.Pois[1][i] for i in range(1, len(ns.Pois[1]) + 1)]
    assert any(p[1] == 1 and p[4].startswith("Orgrimmar") and "H" in p[6] for p in kal)
    assert any(p[1] == 3 and p[4] == "Razor Hill" for p in kal)


def test_no_stray_globals(env):
    """Locals used before their declaration silently become globals in Lua."""
    lua, ns = env
    before = set(lua.globals().keys())
    ns.GPS.Follow()
    ns.GPS.CancelTour()
    ns.GPS.SetZoom = ns.GPS.SetZoom  # touch
    leaked = set(lua.globals().keys()) - before
    assert not leaked, leaked


def test_close_zoom_crops_tiles_to_the_view(env):
    lua, ns = env
    minimap_env(lua, ns)
    half, zoom = 130.0, 60.0  # closest zoom
    px, py = centre_of_tile(40, 33)
    qs = quads(lua, ns.GPS.LayoutMinimap(px, py, 1, 0, zoom, half))
    assert len(qs) == 1  # only the tile under the player
    q = qs[0]
    s = half / zoom
    R = zoom * 1.42
    assert q[3] == pytest.approx(2 * R * s + 1) and q[4] == pytest.approx(2 * R * s + 1)  # small region
    assert q[6] == pytest.approx(0.5 - R / TILE) and q[7] == pytest.approx(0.5 + R / TILE)  # centre of the texture
    assert q[1:3] == pytest.approx([0, 0], abs=1e-6)


def test_crop_edge_tile_texcoords(env):
    lua, ns = env
    minimap_env(lua, ns)
    # Player on the boundary between tile (40, 33) and the tile east of it: the east part of
    # the western tile shows on the left, the west part of the eastern tile on the right.
    cx, cy = centre_of_tile(40, 33)
    edge_y = cy - TILE / 2  # eastern boundary (Y decreases eastwards)
    qs = by_fid(quads(lua, ns.GPS.LayoutMinimap(cx, edge_y, 1, 0, 100.0, 100.0)))
    left, right = qs[40033], qs[41033]
    assert left[6] > 0.5 and left[7] == pytest.approx(1.0)  # eastern part of the west tile
    assert right[6] == pytest.approx(0.0) and right[7] < 0.5  # western part of the east tile
    assert left[1] < 0 < right[1]


# ---- Offroad ------------------------------------------------------------------------

def test_row_encoding_roundtrip(env):
    import numpy as np
    from azerothgps.roads.terrain import decode_row, encode_row

    lua, ns = env
    load(lua, ns, "Passability.lua")
    rng = np.random.default_rng(1)
    for k in range(40):
        # (the continent's rows, and a cave's: values up to 3, short runs up to 15, 2-digit long ones)
        short, long = (21, 3) if k < 20 else (15, 2)
        row = np.repeat(rng.integers(0, 5 if k < 20 else 4, 40), rng.integers(1, 100, 40)).astype(np.uint8)
        text = encode_row(row, short, long)
        assert decode_row(text, short, long) == row.tolist()
        runs = ns.Passability.DecodeRow(text, short, long)
        flat = []
        prev = 0
        for i in range(1, len(runs) + 1, 2):
            flat += [runs[i + 1]] * (runs[i] - prev)
            prev = runs[i]
        assert flat == row.tolist()


def wall_terrain_lua():
    """3x3 tiles around the origin; a cliff wall at world X 290..310 except a pass at |Y| < 60."""
    import numpy as np
    from azerothgps.roads.terrain import QUAD_YD, encode_row

    cell = QUAD_YD * 2
    tx0 = ty0 = 30
    n = int(3 * TILE / cell)
    rows = []
    for r in range(n):
        x = (32 - ty0) * TILE - (r + 0.5) * cell  # world X of the row centre
        row = np.zeros(n, np.uint8)
        if 290 <= x <= 310:
            for c in range(n):
                y = (32 - tx0) * TILE - (c + 0.5) * cell
                if abs(y) >= 60:
                    row[c] = 2
        rows.append('"' + encode_row(row) + '"')
    return (f"ns.Terrain = {{ [1] = {{ tx0 = {tx0}, ty0 = {ty0}, cell = {cell}, w = {n}, h = {n}, "
            f"rows = {{ {', '.join(rows)} }} }} }}\n"
            "ns.Roads = { [1] = { n = { 100,0, 500,0 }, e = { {1,2,400,0, 100,0, 300,0, 500,0} } } }")


@pytest.fixture
def offroad(env):
    lua, ns = env
    load(lua, ns, "Passability.lua", "Router.lua")
    lua.eval("function(src) return assert(load('local _, ns = ...; ' .. src)) end")(wall_terrain_lua())(None, ns)
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True  # terrain searches right away (the game runs them in the background)
    ns.Passability.ClearCache()
    return lua, ns


def test_passability_lookup(offroad):
    lua, ns = offroad
    P = ns.Passability
    assert P.At(1, 300.0, 400.0) == 2  # on the wall
    assert P.At(1, 300.0, 0.0) == 0  # in the pass
    assert P.At(1, 0.0, 400.0) == 0  # open ground
    assert P.SegmentCost(1, 0.0, 400.0, 600.0, 400.0) is None  # straight through the wall
    assert P.SegmentCost(1, 0.0, 400.0, 0.0, -400.0) == pytest.approx(800)


def test_offroad_straight_when_open(offroad):
    lua, ns = offroad
    r = ns.Router.Route(1, 0.0, 400.0, 0.0, -400.0, lua.table(offroad=True))
    pts, kinds = route_pts(r)
    assert kinds == [1] and len(pts) == 2


def test_offroad_uses_the_pass(offroad):
    lua, ns = offroad
    # South of the wall to north of it: straight is blocked, so cut to the road, take it
    # through the pass, then cut straight to the destination. (Walking around on foot is
    # turned off here; test_offroad_walks_around covers it.)
    ns.Router.OFFROAD_WALK_AROUND = 0
    r = ns.Router.Route(1, 0.0, 400.0, 600.0, 400.0, lua.table(offroad=True))
    pts, kinds = route_pts(r)
    assert kinds[0] == 1 and kinds[-1] == 1 and 0 in kinds
    # both ends of every road segment (the road may now be left right in the pass)
    road_pts = [pts[j] for i in range(len(kinds)) if kinds[i] == 0 for j in (i, i + 1)]
    assert any(280 <= x <= 320 and abs(y) < 60 for x, y in road_pts)  # through the pass
    for i, k in enumerate(kinds):  # every off-road leg is passable
        if k == 1:
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            assert ns.Passability.SegmentCost(1, x1, y1, x2, y2) is not None
    # A detour through the pass, not a trip along the whole road: 400 south-west leg,
    # ~200 through the pass, ~450 back north-east.
    assert r.length < 1300


def test_offroad_walks_around(offroad):
    lua, ns = offroad
    # Short trip with the wall in the way: through the pass on foot, all passable.
    r = ns.Router.Route(1, 0.0, 300.0, 600.0, 300.0, lua.table(offroad=True))
    pts, kinds = route_pts(r)
    assert any(abs(y) < 60 for x, y in pts if 250 < x < 350)
    for i in range(len(kinds)):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        assert ns.Passability.SegmentCost(1, x1, y1, x2, y2) is not None


def test_find_path_walks_through_the_pass(offroad):
    lua, ns = offroad
    P = ns.Passability
    cost, path = P.FindPath(1, 0.0, 400.0, 600.0, 400.0)
    pts = [path[i] for i in range(1, len(path) + 1)]
    pts = list(zip(pts[0::2], pts[1::2]))
    assert pts[0] == (0, 400) and pts[-1] == (600, 400)
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        assert P.SegmentCost(1, x1, y1, x2, y2) is not None
    assert any(abs(y) < 60 for x, y in pts if 250 < x < 350)  # crosses the wall at the pass
    assert cost < 1100


def test_straight_leg_along_a_road_is_drawn_as_road(router):
    lua, ns = router
    # Offroad and no terrain data: straight, and it runs 5 yd beside the first leg of the L.
    r = ns.Router.Route(1, 5.0, -50.0, 5.0, -950.0, lua.table(offroad=True))
    pts, kinds = route_pts(r)
    assert set(kinds) == {0}
    assert r.road == pytest.approx(900, abs=1)
    # Crossing a road (rather than following it) stays off-road.
    r = ns.Router.Route(1, -200.0, -500.0, 200.0, -500.0, lua.table(offroad=True))
    assert r.road == 0


def tirisfal_env(env):
    lua, ns = env
    load(lua, ns, "Data/Roads.lua", "Data/Terrain.lua", "Passability.lua", "Router.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    ns.Passability.ClearCache()
    minX, minY, maxX, maxY = 825.0, -1485.4166, 3837.4998, 3033.3333  # Tirisfal Glades
    return lua, ns, lambda mx, my: (maxX - my / 100 * (maxX - minX), maxY - mx / 100 * (maxY - minY))


def test_buildings_are_ground_routes_dont_walk_through(env):
    # (asked: "buildings as objects we can't walk through, like Goldshire") the inn's cells are
    # blocked (Data/Buildings.lua, buildings.py), a leg straight through it isn't taken, a route
    # past it goes round, and a stop inside it (the innkeeper) is still reached
    lua, ns = env
    load(lua, ns, "Data/Roads.lua", "Data/Terrain.lua", "Passability.lua", "Router.lua")
    R, P = ns.Router, ns.Passability
    R.Reset()
    R.SYNC_WALKS = True
    P.ClearCache()
    inn = (-9466.0, 16.0)  # Goldshire's Lion's Pride Inn
    assert P.At(0, *inn) == 2
    assert P.SegmentCost(0, -9466.0, -30.0, -9466.0, 70.0) is None  # straight through it
    assert P.SegmentCost(0, -9440.0, -30.0, -9440.0, 70.0) is not None  # beside it: open ground
    r = R.Route(0, -9466.0, -30.0, -9466.0, 70.0, lua.table())
    pts, kinds = route_pts(r)
    # (round it: nowhere inside the inn's walls, about X -9478..-9454, Y -8..40; its off-road legs pass
    # the router's own check)
    for i, ((x1, y1), (x2, y2)) in enumerate(zip(pts, pts[1:])):
        if kinds[i] == 1:
            assert P.SegmentCost(0, x1, y1, x2, y2) is not None
        n = max(1, int(math.hypot(x2 - x1, y2 - y1)))
        for k in range(n + 1):
            x, y = x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n
            assert not (-9475 < x < -9457 and -5 < y < 37), (x, y)
    assert sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])) > 110  # (100 yd straight)
    stop = R.Route(0, -9440.0, -40.0, inn[0], inn[1], lua.table())
    n = len(stop.pts)
    assert stop and (stop.pts[n - 1], stop.pts[n]) == pytest.approx(inn) and not stop.unconnected


def test_the_buildings_data_is_made_from_the_client_and_small(env):
    # (Data/Buildings.lua: runs of cells per continent; reading them at first use stays cheap)
    lua, ns = env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua")
    for cont in (0, 1):
        runs = ns.BuildingCells[cont]
        assert len(runs) % 3 == 0 and len(runs) > 3000
    t = time.perf_counter()
    ns.Passability.At(0, -9466.0, 16.0)
    assert (time.perf_counter() - t) * 1000 < 20  # (the set made at first read)
    text = (ADDON / "Data/Buildings.lua").read_text(encoding="utf-8")
    assert "agps buildings" in text and len(text) < 200_000
    assert "Data\\Buildings.lua" in (ADDON / "AzerothGPS.toc").read_text(encoding="utf-8")


def test_offroad_respects_tirisfal_mountains(env):
    lua, ns, at = tirisfal_env(env)
    # Shadowvale is walled in by mountains: from east of Brill it must come in by the road,
    # not straight over the ridge.
    (sx, sy), (tx, ty) = at(57.2, 55.4), at(12.6, 65.2)
    assert ns.Passability.SegmentCost(0, sx, sy, tx, ty) is None
    r = ns.Router.Route(0, sx, sy, tx, ty, lua.table(offroad=True))
    pts, kinds = route_pts(r)
    assert 0 in kinds
    for i, k in enumerate(kinds):
        if k == 1:
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            assert ns.Passability.SegmentCost(0, x1, y1, x2, y2) is not None


def test_offroad_long_route_works_out_node_links_in_the_background(env):
    lua, ns, at = tirisfal_env(env)
    R = ns.Router
    (sx, sy), (tx, ty) = at(57.2, 55.4), at(12.6, 65.2)
    want = R.Route(0, sx, sy, tx, ty, lua.table(offroad=True)).length  # all at once
    R.Reset()
    R.SYNC_WALKS, R.NODE_LINK_MS = False, 0  # (none in the route calculation itself)
    pump = lua.eval("function(R) while R.HasWork() do R.Pump(math.huge, function() return 0 end) end end")
    try:
        r = R.Route(0, sx, sy, tx, ty, lua.table(offroad=True))
        assert r.pending  # provisional: the links are worked out in the background
        for _ in range(10):
            pump(R)
            r = R.Route(0, sx, sy, tx, ty, lua.table(offroad=True))
            if not r.pending:
                break
        assert not r.pending
        assert r.length == pytest.approx(want, abs=1)  # then the same route
    finally:
        R.SYNC_WALKS, R.NODE_LINK_MS = True, 12


def test_offroad_from_undercity_skips_brill(env):
    lua, ns, at = tirisfal_env(env)
    # Out of the Ruins' gate and straight west, not north through Brill first.
    r = ns.Router.Route(0, 1600.0, 240.0, *at(12.6, 65.2), lua.table(offroad=True))
    pts, _ = route_pts(r)
    bx, by = at(60.5, 52.0)  # Brill
    assert min(math.hypot(x - bx, y - by) for x, y in pts) > 250
    assert r.length < 3200


# ---- World map, transports ----------------------------------------------------------

def test_world_map_conversion_roundtrip(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua")
    x, y = ns.Geo.ToContinent(0, 1600.0, 240.0, 1)  # Undercity into Kalimdor's coordinates
    bx, by = ns.Geo.ToContinent(1, x, y, 0)
    assert (bx, by) == pytest.approx((1600.0, 240.0), abs=0.01)
    # Undercity lies north-east of Kalimdor on the world map: beyond Kalimdor's north edge
    # (X) and east edge (Y), in Kalimdor's frame.
    kal = ns.Maps[1414].bounds
    assert x > kal[3] - 20000 and y < kal[2]


def test_zoom_out_levels(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua")
    name = lambda i: ns.Maps[i].name if i else None
    assert name(ns.GPS.UpMap(1458)) == "Tirisfal Glades"  # Undercity
    assert name(ns.GPS.UpMap(1454)) == "Durotar"  # Orgrimmar
    assert name(ns.GPS.UpMap(1420)) == "Eastern Kingdoms"
    assert name(ns.GPS.UpMap(1415)) == "Azeroth"
    assert ns.GPS.UpMap(947) is None


@pytest.fixture
def nav_env(env):
    lua, ns = env
    lua.execute("""
      GetTime = function() return 0 end
      GetUnitSpeed = function() return 0, 7, 7, 4.7 end
      IsMounted = function() return false end
    """)
    ns.db = lua.eval("{}")
    ns.CharDB = lua.eval("function(store) return function() return store end end")(lua.eval("{}"))
    load(lua, ns, "Data/Maps.lua", "Data/Roads.lua", "Data/Transports.lua", "Router.lua", "Nav.lua")
    ns.Nav.LATER_PER_CALL = 100  # the whole route in one call (see test_stretches_between_stops_fill_in)
    ns.Router.WARM = False  # no background warm-up (nothing pumps it here)
    return lua, ns


def test_plan_undercity_to_orgrimmar_takes_the_zeppelin(nav_env):
    lua, ns = nav_env
    ns.Nav.SetDestination(1600.0, -4400.0, 1, "Orgrimmar")
    legs, secs = ns.Nav.Plan(0, 1600.0, 240.0, 7.0)
    kinds = ["ride" if legs[i].ride else "walk" for i in range(1, len(legs) + 1)]
    assert kinds == ["walk", "ride", "walk"]
    ride = legs[2].ride
    assert ride[8] == "zeppelin" and {ride[1], ride[4]} == {0, 1}
    assert secs < 30 * 60


def test_plan_same_continent_walks(nav_env):
    lua, ns = nav_env
    ns.Nav.SetDestination(-600.0, -4180.0, 1, "Valley of Trials")
    legs, _ = ns.Nav.Plan(1, -450.0, -4700.0, 7.0)
    assert len(legs) == 1 and legs[1].walk


def test_cross_continent_route_has_transport_leg(nav_env):
    lua, ns = nav_env
    ns.Nav.SetDestination(-440.0, -4700.0, 1, "near Razor Hill")  # ~2k yd south of the zeppelin tower
    r = ns.Nav.Route(1600.0, 240.0, 0)
    parts = [r.parts[i] for i in range(1, len(r.parts) + 1)]
    assert [p.cont for p in parts] == [0, 0, 1]  # walk (EK), ride (drawn from EK), walk (Kalimdor)
    assert [parts[1].kinds[i] for i in range(1, len(parts[1].kinds) + 1)] == [2]
    far = parts[2]
    far_kinds = [far.kinds[i] for i in range(1, len(far.kinds) + 1)]
    assert 0 in far_kinds  # the far side is routed over Kalimdor's roads, not a straight line
    assert r.extraSeconds > 0


def test_route_seen_from_the_other_continent(nav_env):
    lua, ns = nav_env
    ns.Nav.SetDestination(1600.0, -4400.0, 1, "Orgrimmar")
    r = ns.Nav.Route(1600.0, 240.0, 0)
    segs = []
    last = ns.Nav.EachSegment(r, 1, lambda *a: segs.append(a))
    assert len(segs) > 5
    assert (last[0], last[1]) == pytest.approx((1600.0, -4400.0), abs=0.5)  # ends at the destination in Kalimdor's frame


# ---- Map layers (Layers.lua) -------------------------------------------------------------

def test_minimap_hover_offset(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    L = ns.Layers
    # North-up minimap 140 UI units showing 466.67 yd: 30 units right, 15 up of the centre.
    dx, dy = L.MinimapOffset(30.0, 15.0, 140.0, 1400 / 3, 0)
    k = (1400 / 3) / 140
    assert dx == pytest.approx(15 * k)  # up = north = +X
    assert dy == pytest.approx(-30 * k)  # right = east = -Y
    # Rotating minimap, player facing west (+Y, facing = pi/2): up on the minimap is west.
    dx, dy = L.MinimapOffset(0.0, 15.0, 140.0, 1400 / 3, math.pi / 2)
    assert dx == pytest.approx(0, abs=1e-9) and dy == pytest.approx(15 * k)


def test_nodes_merge_and_herbs_ore_layers(env):
    lua, ns = env
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = { layerHerbs = true, layerOre = true } }")
    lua.execute("""
      GetNumSkillLines = function() return 1 end
      GetSkillLineInfo = function() return "Mining", false end
      GetTime = function() return 0 end
    """)
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    L = ns.Layers
    assert L.AddNode(1, 100.0, 200.0, "Copper Vein") is True
    assert L.AddNode(1, 110.0, 205.0, "Copper Vein") is False  # same node, seen again
    assert L.AddNode(1, 100.0, 200.0, "Peacebloom") is True
    assert L.AddNode(1, 0.0, 0.0, "Some Rock") is False  # not a gathering node
    def shown():
        marks = L.Marks(1, 100.0, 200.0, 500.0, lua.table())
        return sorted(marks[i][4] for i in range(1, len(marks) + 1))
    assert shown() == ["Copper Vein", "Peacebloom"]  # both layers on
    ns.settings.gps.layerHerbs = False
    assert shown() == ["Copper Vein"]  # the Herbs layer off
    ns.settings.gps.layerHerbs, ns.settings.gps.layerOre = True, False
    assert shown() == ["Peacebloom"]


def test_quest_marks_from_the_quest_api(env):
    lua, ns = env
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = { layerQuests = true } }")
    lua.execute("""
      GetTime = function() return 0 end
      C_QuestLog = {
        GetQuestsOnMap = function() return { { questID = 7, x = 0.5, y = 0.5 } } end,
        IsComplete = function() return false end,
        GetTitleForQuestID = function() return "Sting of the Scorpid" end,
      }
    """)
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    durotar = ns.Maps[1411]
    b = durotar.bounds
    cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
    marks = ns.Layers.Marks(1, cx, cy, 10000.0, lua.table(1411))
    got = {marks[i][4]: (marks[i][1], marks[i][2]) for i in range(1, len(marks) + 1)}
    assert set(got) == {"Sting of the Scorpid"}
    assert got["Sting of the Scorpid"] == pytest.approx((cx, cy))  # map centre -> zone centre


def test_outline_of_a_square(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    inside = lua.eval("function(i, j) return i >= 2 and i <= 4 and j >= 2 and j <= 4 end")
    segs = ns.Layers.Outline(inside, 8, 8)
    pts = [segs[i] for i in range(1, len(segs) + 1)]
    n = len(pts) // 4
    assert n == 12  # 3 cells per side, 4 sides, one segment per boundary cell edge
    xs = pts[0::2]
    assert min(xs) == 1.5 and max(xs) == 4.5  # halfway between inside and outside samples


def test_quest_area_traced_from_hit_tests(env):
    lua, ns = env
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("""
      GetTime = function() return 1000 end
      C_QuestLog = {
        GetQuestsOnMap = function() return { { questID = 7, x = 0.4, y = 0.6 } } end,
        IsComplete = function() return false end,
        GetQuestObjectives = function() return { { finished = false } } end,
      }
      -- the quest's area: a circle of radius 0.1 around (0.4, 0.6) in map coordinates
      C_Minimap = { IsInsideQuestBlob = function(q, u, v)
        return q == 7 and (u - 0.4) ^ 2 + (v - 0.6) ^ 2 <= 0.01 end }
    """)
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    L = ns.Layers
    maps = lua.table(1411)
    b = ns.Maps[1411].bounds
    cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
    assert len(L.Areas(1, cx, cy, 1e6, maps)) == 0  # queued, not traced yet
    assert L.hitterName == "IsInsideQuestBlob(q, u, v)"
    L.TraceAll()
    a = L.Areas(1, cx, cy, 1e6, maps)
    pts = [a[i] for i in range(1, len(a) + 1)]
    assert len(pts) > 40
    # every outline point lies on the circle (radius 0.1 of the map), to within a fine cell
    ox, oy, _ = L.MapToWorld(1411, 0.4, 0.6)
    rx = 0.1 * (b[3] - b[1])  # yards per 0.1 of the map, north-south
    ry = 0.1 * (b[4] - b[2])
    for x, y in zip(pts[0::2], pts[1::2]):
        r = math.hypot((x - ox) / rx, (y - oy) / ry)
        assert 0.9 < r < 1.1
    # hovering: inside the circle finds the quest, outside doesn't
    assert list(L.QuestsAt(1, ox, oy).values()) == [7]
    assert len(L.QuestsAt(1, ox + 2 * rx, oy)) == 0
    lua.execute("C_QuestLog.IsComplete = function() return true end")
    assert len(L.QuestsAt(1, ox, oy)) == 0  # done: no area, no tooltip


def test_small_quest_area_found_near_the_player(env):
    # A quest area of about 30 yards, between the coarse samples, its map icon elsewhere:
    # not found while the player is far away; looked for again around them later, found.
    lua, ns = env
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("""
      AGPS_T = 1000
      GetTime = function() return AGPS_T end
      AGPS_QUESTS = { { questID = 1, x = 0.5, y = 0.5 } }
      C_QuestLog = {
        GetQuestsOnMap = function() return AGPS_QUESTS end,
        IsComplete = function() return false end,
        GetQuestObjectives = function() return { { finished = false } } end,
      }
      AGPS_U, AGPS_V = 0.1, 0.9 -- the player, far from it
      C_Map = C_Map or {}
      C_Map.GetPlayerMapPosition = function() return { x = AGPS_U, y = AGPS_V } end
      -- quest 1: a big area (picks the hit test); quest 8: radius 0.006 around (0.708, 0.292)
      C_Minimap = { IsInsideQuestBlob = function(q, u, v)
        if q == 1 then return (u - 0.5) ^ 2 + (v - 0.5) ^ 2 <= 0.01 end
        if q == 8 then return (u - 0.708) ^ 2 + (v - 0.292) ^ 2 <= 0.006 ^ 2 end
        return false end }
    """)
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    L = ns.Layers
    maps = lua.table(1411)
    L.Areas(1, 0, 0, 1e6, maps)
    L.TraceAll()
    assert L.hitterName
    ox, oy, _ = L.MapToWorld(1411, 0.708, 0.292)
    lua.execute("AGPS_T = 2000; AGPS_QUESTS = { { questID = 8, x = 0.3, y = 0.3 } }")
    L.Areas(1, 0, 0, 1e6, maps)
    L.TraceAll()
    assert list(L.QuestsAt(1, ox, oy).values()) == []  # stepped over, the player far away
    lua.execute("AGPS_T = 2100; AGPS_U, AGPS_V = 0.71, 0.29")  # later, the player near it
    L.Areas(1, 0, 0, 1e6, maps)
    L.TraceAll()
    assert list(L.QuestsAt(1, ox, oy).values()) == [8]


def test_quest_area_without_a_map_icon_is_traced(env):
    # Quest 9 is in the log but not among the map's quests (no icon here), with a small
    # area near the player: traced anyway.
    lua, ns = env
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("""
      AGPS_T = 1000
      GetTime = function() return AGPS_T end
      C_QuestLog = {
        GetQuestsOnMap = function() return { { questID = 1, x = 0.5, y = 0.5 } } end,
        GetNumQuestLogEntries = function() return 3, 2 end,
        GetInfo = function(i)
          if i == 1 then return { isHeader = true, title = "Durotar" } end
          if i == 2 then return { questID = 1 } end
          if i == 3 then return { questID = 9 } end
        end,
        IsComplete = function() return false end,
        GetQuestObjectives = function() return { { finished = false } } end,
      }
      C_Map = C_Map or {}
      C_Map.GetPlayerMapPosition = function() return { x = 0.71, y = 0.29 } end
      C_Minimap = { IsInsideQuestBlob = function(q, u, v)
        if q == 1 then return (u - 0.5) ^ 2 + (v - 0.5) ^ 2 <= 0.01 end
        if q == 9 then return (u - 0.708) ^ 2 + (v - 0.292) ^ 2 <= 0.006 ^ 2 end
        return false end }
    """)
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    L = ns.Layers
    assert list(L.LogQuests().values()) == [1, 9]
    maps = lua.table(1411)
    L.Areas(1, 0, 0, 1e6, maps)
    L.TraceAll()
    ox, oy, _ = L.MapToWorld(1411, 0.708, 0.292)
    assert list(L.QuestsAt(1, ox, oy).values()) == [9]


def test_quest_route_stops_from_the_quest_log(env):
    # Log: 1 open (pin on Durotar), 2 finished (turn-in pin), 3 open with no pin (next
    # waypoint), 4 nowhere. Stops for 1-3, named; 4 reported missing.
    lua, ns = env
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("""
      GetTime = function() return 10 end
      C_Map = C_Map or {}
      C_Map.GetBestMapForUnit = function() return 1411 end
      C_QuestLog = {
        GetNumQuestLogEntries = function() return 4, 4 end,
        GetInfo = function(i) return { questID = i } end,
        IsComplete = function(id) return id == 2 end,
        GetTitleForQuestID = function(id) return ({ "Wolves", "Letter", "Far Away", "Lost" })[id] end,
        GetQuestsOnMap = function(mapID)
          if mapID == 1411 then return { { questID = 1, x = 0.4, y = 0.5 }, { questID = 2, x = 0.6, y = 0.3 } } end
          return {}
        end,
        GetNextWaypoint = function(id) if id == 3 then return 1411, 0.2, 0.8 end end,
      }
    """)
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    stops, c = ns.Layers.QuestStops()
    names = sorted(stops[i].name for i in range(1, len(stops) + 1))
    assert names == ["Far Away", "Turn in: Letter", "Wolves"]
    assert c.todo == 2 and c.turnin == 1 and list(c.missing.values()) == ["Lost"]
    x, y, cont = ns.Layers.MapToWorld(1411, 0.4, 0.5)
    wolves = [stops[i] for i in range(1, len(stops) + 1) if stops[i].name == "Wolves"][0]
    assert (wolves.x, wolves.y, wolves.cont) == (x, y, cont)


def test_undercity_district_labels(env):
    # Inside Undercity's map: one label per district, the Trade Quarter's in its middle.
    lua, ns = env
    load(lua, ns, "Data/Interiors.lua")
    G = ns.GPS
    best = None
    for i in range(1, len(ns.Interiors[0]) + 1):
        p = ns.Interiors[0][i]
        if p[6] < 1600 < p[8] and p[7] < 240 < p[9]:
            area = (p[8] - p[6]) * (p[9] - p[7])
            if not best or area > best[0]:
                best = (area, p)
    p = best[1]
    c, s = math.cos(p[5]), math.sin(p[5])
    wx, wy = p[2] - 54.8 * c + 2.4 * s, p[3] - 54.8 * s - 2.4 * c  # the Trade Quarter's middle
    place, wmo, room = G.FindInterior(wx, wy, 0, 0, "Trade Quarter", True)
    labels = G.InteriorLabels(place, wmo, room)
    names = [labels[i][3] for i in range(1, len(labels) + 1)]
    assert len(names) == len(set(names))  # each once
    for n in ("Trade Quarter", "War Quarter", "Magic Quarter", "Rogues' Quarter", "The Apothecarium", "Royal Quarter"):
        assert n in names
    tq = [labels[i] for i in range(1, len(labels) + 1) if labels[i][3] == "Trade Quarter"][0]
    assert math.hypot(tq[1] - wx, tq[2] - wy) < 20


# ---- Multi-stop routes -----------------------------------------------------------------

def stops(lua, *pts):
    return lua.table(*[lua.table(x=x, y=y, cont=1) for x, y in pts])


def test_multi_stop_route_covers_every_stop(nav_env):
    lua, ns = nav_env
    a, b = (-600.0, -4180.0), (-440.0, -4700.0)  # Valley of Trials, south of Razor Hill
    ns.Nav.SetStops(stops(lua, a, b))
    assert [ns.Nav.stops[i].icon for i in (1, 2)] == [6, 1]  # square, then star
    r = ns.Nav.Route(-800.0, -4400.0, 1)
    last = ns.Nav.EachSegment(r, 1, lambda *x: None)
    assert (last[0], last[1]) == pytest.approx(b, abs=0.5)  # ends at the last stop
    assert r.totalYards > r.walkYards > 0  # whole trip longer than the way to stop 1
    # every segment knows which stop it leads to (for per-stop colours)
    seen = set()
    ns.Nav.EachSegment(r, 1, lambda x1, y1, x2, y2, kind, stop, *rest: seen.add(stop))
    assert seen == {1, 2}


def test_reaching_a_stop_moves_on_to_the_next(nav_env):
    lua, ns = nav_env
    ns.Nav.SetStops(stops(lua, (-600.0, -4180.0), (-440.0, -4700.0)))
    status = ns.Nav.Status(-602.0, -4181.0, 1)  # standing at stop 1
    assert len(ns.Nav.stops) == 1 and ns.Nav.dest.x == -440.0
    assert "Arrived" not in status
    assert "Arrived" in ns.Nav.Status(-440.0, -4700.0, 1)


def test_the_last_stop_goes_at_once_when_reached(nav_env):
    # (reported) arrived, still running: out of the stop's circle the route to it came back,
    # until the stop went a few seconds later. Reached: gone at once, "Arrived" shown a while.
    lua, ns = nav_env
    N = ns.Nav
    lua.execute("AGPS_T = 100 GetTime = function() return AGPS_T end")
    N.SetStops(stops(lua, (-440.0, -4700.0)))
    assert "Arrived" in N.Status(-440.0, -4700.0, 1)
    assert len(N.stops) == 0 and N.dest is None and N.route is None
    lua.execute("AGPS_T = 102")
    assert "Arrived" in N.Status(-470.0, -4700.0, 1)  # (30 yd on: still just "Arrived")
    assert N.dest is None and N.Route(-470.0, -4700.0, 1) is None
    lua.execute("AGPS_T = 106")
    N.Tick()
    assert N.Status(-500.0, -4700.0, 1) is None  # (then nothing)


def test_fastest_order(nav_env):
    lua, ns = nav_env
    lua.execute("Geo_Player = nil")
    # placed far-first; the fastest order visits the near one first
    near, far = (-500.0, -4400.0), (-500.0, -3400.0)
    ns.Nav.SetStops(stops(lua, far, near))
    ns.Nav.OrderStops(-500.0, -4600.0, 1)
    assert ns.Nav.stops[1].y == -4400.0 and ns.Nav.stops[2].y == -3400.0
    assert ns.Nav.stops[1].icon == 1  # markers stay with their stops (placed 2nd: star)


def test_fastest_order_many_stops(nav_env):
    lua, ns = nav_env
    # 8 stops on a line, shuffled: nearest-first + 2-opt must visit them in line order
    ys = [-4600.0 + 100 * k for k in (5, 2, 7, 1, 8, 3, 6, 4)]
    ns.Nav.SetStops(stops(lua, *[(-500.0, y) for y in ys]))
    ns.Nav.OrderStops(-500.0, -4600.0, 1)
    got = [ns.Nav.stops[i].y for i in range(1, 9)]
    assert got == sorted(got)


def test_steps_for_a_zeppelin_trip(nav_env):
    lua, ns = nav_env
    ns.Nav.SetDestination(-440.0, -4700.0, 1, "Razor Hill")
    ns.Nav.Route(1600.0, 240.0, 0)  # Undercity
    steps = ns.Nav.Steps()
    steps = [steps[i] for i in range(1, len(steps) + 1)]
    assert len(steps) == 3
    assert steps[0].startswith("Walk ") and "to the zeppelin (Brill, Tirisfal Glades)" in steps[0]
    assert steps[1] == "Take the zeppelin to Jaggedswine Farm, Durotar"
    assert steps[2].startswith("Walk ") and steps[2].endswith("Razor Hill")


def test_steps_text_shows_three_then_more(nav_env):
    lua, ns = nav_env
    # zeppelin trip (3 steps) then two more stops in Durotar: 5 steps
    ns.Nav.SetStops(lua.table(lua.table(x=-440.0, y=-4700.0, cont=1), lua.table(x=-600.0, y=-4180.0, cont=1),
                              lua.table(x=-800.0, y=-4400.0, cont=1)))
    ns.Nav.Route(1600.0, 240.0, 0)
    assert len(ns.Nav.Steps()) == 5
    steps = ns.Nav.Steps()
    # each step reaching a stop ends with the time from the previous stop (run speed 7 yd/s here)
    r = ns.Nav.route
    for n, stop_step in ((2, 3), (3, 4)):
        st = r.stretches[n]
        assert steps[stop_step + 1].endswith(ns.Nav.FormatTime(st.walk / 7 + st.ride) + "|r")
    first = r.stretches[1]
    assert steps[3].endswith(ns.Nav.FormatTime(first.walk / 7 + first.ride) + "|r")  # includes the zeppelin
    text = ns.Nav.StepsText(3)
    lines = text.split("\n")
    assert len(lines) == 4 and lines[0].startswith("|cffffffff1. ") and "2 more steps" in lines[3]
    # single walk: no step list
    ns.Nav.SetDestination(-600.0, -4180.0, 1)
    ns.Nav.Route(-800.0, -4400.0, 1)
    assert ns.Nav.StepsText(3) == ""


def test_no_spoiler_map_draws_only_explored_overlays(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua")
    lua.execute("""
      GetTime = function() return 0 end
      C_MapExplorationInfo = { GetExploredMapTextures = function(id)
        -- one explored area 300x200 px at (100, 50): 2x1 textures, the second 44 px wide
        return { { textureWidth = 300, textureHeight = 200, offsetX = 100, offsetY = 50,
                   isShownByMouseOver = false, fileDataIDs = { 11, 12 } },
                 { textureWidth = 64, textureHeight = 64, offsetX = 0, offsetY = 0,
                   isShownByMouseOver = true, fileDataIDs = { 13 } } } end }
    """)
    G = ns.GPS
    tiles = G.ExploredOverlays(1411)
    t = [[tiles[i][j] for j in range(1, 8)] for i in range(1, len(tiles) + 1)]
    assert t == [[11, 100, 50, 256, 200, 256, 256], [12, 356, 50, 44, 200, 64, 256]]
    d = ns.Maps[1411]
    b = d.bounds
    cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
    full = G.LayoutZone(cx, cy, 1411, 0, 3000.0, 130.0)
    nospoil = G.LayoutZone(cx, cy, 1411, 0, 3000.0, 130.0, None, True)
    fids = lambda qs: [qs[i][1] for i in range(1, len(qs) + 1)]
    n_base = len(d.tiles)
    assert len(fids(full)) > n_base + 2  # every explored overlay
    assert fids(nospoil)[n_base:] == [11, 12]  # only what this character explored
    assert G.IsMapStyle("nospoiler") and not G.IsMapStyle("minimap")


def test_terrain_walks_run_in_the_background(offroad):
    lua, ns = offroad
    R, P = ns.Router, ns.Passability
    R.SYNC_WALKS = False
    P.PATH_YIELD_EVERY = 10  # small slices, to see them
    opts = lua.table(offroad=True)
    # a short trip with the wall in the way: the walk around it isn't known yet
    before = R.Route(1, 0.0, 300.0, 600.0, 300.0, opts)
    assert R.HasWork()
    # the search runs in slices: a clock that passes the deadline after one check allows
    # exactly one slice per Pump call
    one_slice = lua.eval("function() local n = 0; return function() n = n + 1; return n == 1 and -1 or 1 end end")
    slices = 0
    while R.HasWork():
        R.Pump(0, one_slice())
        slices += 1
    assert slices > 10
    after = R.Route(1, 0.0, 300.0, 600.0, 300.0, opts)
    pts, kinds = route_pts(after)
    # (meanwhile about straight: only the wall's width is blocked; then the walk found, through the pass)
    assert before.pending and not after.pending
    assert any(abs(y) < 60 for x, y in pts if 250 < x < 350)
    for i, k in enumerate(kinds):
        if k == 1:
            (x1, y1), (x2, y2) = pts[i], pts[i + 1]
            assert P.SegmentCost(1, x1, y1, x2, y2) is not None


def test_added_stops_take_the_next_free_marker(nav_env):
    lua, ns = nav_env
    N = ns.Nav
    N.SetStops(stops(lua, (-600.0, -4180.0), (-440.0, -4700.0)))  # square, star
    pending = lua.table()
    m1 = N.NextMarker(N.stops, pending)
    assert m1 == 4  # triangle: square and star are taken
    pending[1] = lua.table(x=0.0, y=0.0, cont=1, icon=m1)
    assert N.NextMarker(N.stops, pending) == 3  # then diamond
    # reaching the first stop frees the square for the next one placed
    N.Status(-600.0, -4180.0, 1)
    assert [N.stops[i].icon for i in range(1, len(N.stops) + 1)] == [1]
    assert N.NextMarker(N.stops, lua.table()) == 6
    # confirming appends: existing stops keep their markers, new ones follow
    combined = lua.table(N.stops[1], lua.table(x=-800.0, y=-4400.0, cont=1, icon=6))
    N.SetStops(combined)
    assert [N.stops[i].icon for i in (1, 2)] == [1, 6]


def test_stretches_between_stops_fill_in(nav_env):
    # One stretch between stops per call: the route grows over the next calls (frames),
    # the player's stretch isn't recalculated for it, and after Invalidate the old
    # stretches stay drawn until each is replaced.
    lua, ns = nav_env
    N = ns.Nav
    N.LATER_PER_CALL = 1
    N.SetStops(stops(lua, (-600.0, -4180.0), (-440.0, -4700.0), (-800.0, -4400.0)))
    r = N.Route(-500.0, -4500.0, 1)
    assert r.stretches[2] and not r.stretches[3]
    first = r.firstStretch
    r = N.Route(-500.0, -4500.0, 1)
    assert r.stretches[3] and lua.eval("rawequal")(r.firstStretch, first)
    last = N.EachSegment(r, 1, lambda *a: None)
    assert (last[0], last[1]) == pytest.approx((-800.0, -4400.0), abs=0.5)
    N.Invalidate(True)
    r = N.Route(-500.0, -4500.0, 1)
    assert r.stretches[2] and r.stretches[3]


def test_road_data_warms_up_in_the_background(nav_env):
    # The first route on a continent waits for its road data to be built in small steps
    # (none of them long), then works out as usual; after WARM_WAIT it doesn't wait.
    lua, ns = nav_env
    R, N = ns.Router, ns.Nav
    R.Reset()
    R.WARM = True
    lua.execute("AGPS_T = 0; GetTime = function() return AGPS_T end")
    N.SetDestination(-910.0, -3490.0, 0, "Hammerfall")
    assert N.Route(1350.0, 150.0, 0) is None and "Working out" in N.Status(1350.0, 150.0, 0)
    clock = lua.eval("function() return os.clock() * 1000 end")
    steps, longest = 0, 0.0
    while R.HasWork() and steps < 100000:
        t0 = clock()
        R.Pump(t0 + 1, clock)
        longest = max(longest, clock() - t0)
        steps += 1
    assert steps > 5 and longest < 25  # built in slices (generous: lupa timing is coarse)
    # (then the route itself, worked out in the background too: no frame waits on it)
    assert N.Route(1350.0, 150.0, 0) is None and "Working out" in N.Status(1350.0, 150.0, 0)
    while R.HasWork():
        t0 = clock()
        R.Pump(t0 + 1, clock)
        longest = max(longest, clock() - t0)
    assert longest < 25
    r = N.Route(1350.0, 150.0, 0)
    assert r and r.totalYards > 1000
    # another continent while its warm-up can't run: after WARM_WAIT, worked out anyway
    N.SetDestination(-600.0, -4180.0, 1)
    assert N.Route(-800.0, -4400.0, 1) is None
    lua.execute("AGPS_T = 10")
    N.Route(-800.0, -4400.0, 1)
    while R.HasWork():
        R.Pump(clock() + 5, clock)
    assert N.Route(-800.0, -4400.0, 1)


def test_long_imported_list_in_fastest_order_routed_a_few_ahead(nav_env):
    # 60 stops scattered around Durotar: all ordered from the player in one go (quickly),
    # the route worked out and drawn 8 ahead, and reaching a stop brings in the next.
    import random
    import time
    lua, ns = nav_env
    N = ns.Nav
    ns.settings = lua.eval("{ gps = { stopsAhead = 8 } }")  # (the option at its most; 3 by default)
    lua.execute("AGPS_PLAYER = { -500.0, -4500.0, 1 }")
    ns.Geo.PlayerWorld = lua.eval("function() return AGPS_PLAYER[1], AGPS_PLAYER[2], AGPS_PLAYER[3] end")
    rnd = random.Random(3)
    pts = [(rnd.uniform(-1500, 900), rnd.uniform(-5200, -3800)) for _ in range(60)]
    t0 = time.perf_counter()
    N.SetStops(lua.table(*[lua.table(x=x, y=y, cont=1) for x, y in pts]), True)
    assert time.perf_counter() - t0 < 2.0
    ordered = [(N.stops[i].x, N.stops[i].y) for i in range(1, len(N.stops) + 1)]
    assert sorted(ordered) == sorted(pts)  # every stop, once

    def length(seq):
        total, (cx, cy) = 0.0, (-500.0, -4500.0)
        for x, y in seq:
            total += ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            cx, cy = x, y
        return total
    assert length(ordered) < 0.3 * length(pts)
    assert N.PlannedStops() == 8
    r = N.Route(-500.0, -4500.0, 1)
    assert len(r.stretches) == 8
    assert "Next 8 stops:" in N.Status(-500.0, -4500.0, 1)
    ninth = (N.stops[9].x, N.stops[9].y)
    N.RemoveStop(1)  # as if reached
    assert (N.stops[8].x, N.stops[8].y) == ninth and N.PlannedStops() == 8


def test_questing_stop_waits_for_the_quest_objectives(nav_env):
    # A stop inside a quest's area: getting there doesn't finish it; in the area the route
    # waits and the directions show the objectives; leaving leads back; finishing the
    # quest moves on to the next stop.
    lua, ns = nav_env
    N = ns.Nav
    lua.execute("""
      AGPS_T = 0
      GetTime = function() return AGPS_T end
      AGPS_DONE = {}
      C_QuestLog = {
        IsComplete = function(id) return AGPS_DONE[id] == true end,
        IsOnQuest = function(id) return true end,
        GetQuestObjectives = function(id)
          return { { text = "Vile Familiar slain: 3/8", finished = false }, { text = "Collect a claw: 1/1", finished = true } }
        end,
        GetTitleForQuestID = function(id) return "Vile Familiars" end,
      }
      -- quest 101's area: 150 yd around (-600, -4180) on Kalimdor
      AGPS_LAYERS = { QuestsAt = function(cont, x, y)
        if cont == 1 and (x + 600) ^ 2 + (y + 4180) ^ 2 < 150 ^ 2 and not AGPS_DONE[101] then return { 101 } end
        if cont == 1 and (x + 300) ^ 2 + (y + 4700) ^ 2 < 100 ^ 2 then return { 202 } end
        return {}
      end }
    """)
    load(lua, ns, "Layers.lua")
    ns.Layers.QuestsAt = lua.eval("AGPS_LAYERS.QuestsAt")
    ns.settings = lua.eval("{ gps = { questing = true } }")
    N.SetStops(lua.table(lua.table(x=-600.0, y=-4180.0, cont=1), lua.table(x=-800.0, y=-4400.0, cont=1)))

    def status(x, y):
        lua.execute("AGPS_T = AGPS_T + 1")
        return N.Status(x, y, 1)

    assert "In the quest area" not in status(-300.0, -4700.0) and not N.questing
    # on the way, in another quest's area (202, around -300, -4700): its objectives with
    # the directions, the times line still last
    assert list(N.areaQuests.values()) == [202] and not N.questing
    text = status(-300.0, -4700.0)
    assert "Vile Familiar slain: 3/8" in text and text.splitlines()[-1].startswith("All stops:")
    # in the area: objectives, and the arrow still leads to the stop's spot (route kept up)
    text = status(-650.0, -4150.0)
    assert "In the quest area" in text and "Vile Familiar slain: 3/8" in text and N.questing[1] == 101
    assert not N.QuestPaused() and N.route and N.StepsText(3) == ""
    # right at the spot: not reached while the quest is open; from now on the route waits
    status(-600.0, -4180.0)
    assert len(N.stops) == 2 and N.questing and N.QuestPaused()
    before = N.route
    status(-640.0, -4160.0)
    assert lua.eval("rawequal")(N.Route(-640.0, -4160.0, 1), before)
    # left the area: back to directions, the route recalculated from here
    assert "In the quest area" not in status(-300.0, -4700.0) and not N.questing
    assert N.route and len(N.stops) == 2
    # back in the area (spot already visited): waits right away
    status(-650.0, -4150.0)
    assert N.QuestPaused()
    # the quest done (from anywhere): on to the next stop
    lua.execute("AGPS_DONE[101] = true")
    status(-650.0, -4150.0)
    assert len(N.stops) == 1 and N.dest.x == -800.0 and not N.questing
    # questing off: a stop is reached by getting there, as before
    ns.settings.gps.questing = False
    N.SetStops(lua.table(lua.table(x=-600.0, y=-4180.0, cont=1), lua.table(x=-800.0, y=-4400.0, cont=1)))
    lua.execute("AGPS_DONE[101] = nil")
    status(-600.0, -4180.0)
    assert len(N.stops) == 1


def test_questing_stop_done_when_its_quest_finishes_in_the_area(nav_env):
    # A stop inside quest 404's big area: its quest finished anywhere in the area (300 yd
    # from the spot) completes the stop; finished outside the area, the stop is reached by
    # going there.
    lua, ns = nav_env
    N = ns.Nav
    lua.execute("""
      AGPS_T = 0
      GetTime = function() return AGPS_T end
      AGPS_DONE = {}
      C_QuestLog = { IsComplete = function(id) return AGPS_DONE[id] == true end, IsOnQuest = function() return true end,
        GetQuestObjectives = function() return {} end, GetTitleForQuestID = function() return "Q" end }
      local function inside(x, y) return (x + 300) ^ 2 + (y + 4700) ^ 2 < 400 ^ 2 end
      AGPS_LAYERS = {
        QuestsAt = function(cont, x, y) if cont == 1 and inside(x, y) and not AGPS_DONE[404] then return { 404 } end return {} end,
        AreaContains = function(id, cont, x, y) return id == 404 and cont == 1 and inside(x, y) end,
      }
    """)
    load(lua, ns, "Layers.lua")
    ns.Layers.QuestsAt = lua.eval("AGPS_LAYERS.QuestsAt")
    ns.Layers.AreaContains = lua.eval("AGPS_LAYERS.AreaContains")
    ns.settings = lua.eval("{ gps = { questing = true } }")

    def step(x, y):
        lua.execute("AGPS_T = AGPS_T + 1")
        N.Status(x, y, 1)

    # done 300 yd from the spot, inside the area: the stop is done
    N.SetStops(lua.table(lua.table(x=-300.0, y=-4400.0, cont=1, name="spot"), lua.table(x=-900.0, y=-4100.0, cont=1, name="next")))
    step(-300.0, -4700.0)
    assert N.questing
    lua.execute("AGPS_DONE[404] = true")
    step(-300.0, -4700.0)
    assert N.stops[1].name == "next"
    # done outside the area (the quest finished elsewhere): kept, reached by getting there
    lua.execute("AGPS_DONE[404] = nil")
    N.SetStops(lua.table(lua.table(x=-300.0, y=-4400.0, cont=1, name="spot"), lua.table(x=-900.0, y=-4100.0, cont=1, name="next")))
    step(-1500.0, -4700.0)
    lua.execute("AGPS_DONE[404] = true")
    step(-1500.0, -4700.0)
    assert N.stops[1].name == "spot" and not N.questing
    step(-300.0, -4400.0)
    assert N.stops[1].name == "next"


def test_quest_area_objectives_without_a_route(nav_env):
    # No route at all: standing in a quest's area still gives its quests (for the arrow).
    lua, ns = nav_env
    N = ns.Nav
    lua.execute("""
      GetTime = function() return 50 end
      C_QuestLog = { IsComplete = function() return false end, IsOnQuest = function() return true end,
        GetQuestObjectives = function() return { { text = "Wolves slain: 2/10", finished = false } } end,
        GetTitleForQuestID = function() return "Wolves" end }
      AGPS_LAYERS = { QuestsAt = function(cont, x, y)
        if cont == 1 and (x + 300) ^ 2 + (y + 4700) ^ 2 < 100 ^ 2 then return { 505 } end
        return {}
      end }
    """)
    load(lua, ns, "Layers.lua")
    ns.Layers.QuestsAt = lua.eval("AGPS_LAYERS.QuestsAt")
    ns.settings = lua.eval("{ gps = { questing = true } }")
    N.Clear()
    assert N.Status(-300.0, -4700.0, 1) is None
    assert list(N.areaQuests.values()) == [505]
    assert N.QuestLines(N.areaQuests)[2][1] == "Wolves slain: 2/10"


def test_later_stop_in_the_quest_area_youre_in_comes_first(nav_env):
    # Stops: A (no quest), B, C (in quest 303's area around -300, -4700). Standing in that
    # area while heading to A: C comes first (already there).
    lua, ns = nav_env
    N = ns.Nav
    lua.execute("""
      AGPS_T = 0
      GetTime = function() return AGPS_T end
      C_QuestLog = { IsComplete = function() return false end, IsOnQuest = function() return true end,
        GetQuestObjectives = function() return {} end, GetTitleForQuestID = function() return "Q" end }
      local function inside(x, y) return (x + 300) ^ 2 + (y + 4700) ^ 2 < 150 ^ 2 end
      AGPS_LAYERS = {
        QuestsAt = function(cont, x, y) if cont == 1 and inside(x, y) then return { 303 } end return {} end,
        AreaContains = function(id, cont, x, y) return id == 303 and cont == 1 and inside(x, y) end,
      }
    """)
    load(lua, ns, "Layers.lua")
    ns.Layers.QuestsAt = lua.eval("AGPS_LAYERS.QuestsAt")
    ns.Layers.AreaContains = lua.eval("AGPS_LAYERS.AreaContains")
    ns.settings = lua.eval("{ gps = { questing = true } }")
    N.SetStops(lua.table(lua.table(x=-900.0, y=-4100.0, cont=1, name="A"), lua.table(x=-700.0, y=-4300.0, cont=1, name="B"),
                         lua.table(x=-320.0, y=-4680.0, cont=1, name="C")))
    lua.execute("AGPS_T = 1")
    N.Status(-1200.0, -4000.0, 1)  # outside: order kept
    assert [N.stops[i].name for i in (1, 2, 3)] == ["A", "B", "C"]
    lua.execute("AGPS_T = 2")
    N.Status(-280.0, -4720.0, 1)  # in C's quest area
    assert [N.stops[i].name for i in (1, 2, 3)] == ["C", "A", "B"]
    assert N.questing and N.questing[1] == 303


def test_corpse_run_puts_your_body_first(nav_env):
    # Released as a ghost: the body (skull) becomes stop 1 ahead of the route, never
    # reordered; alive again, it's taken off and the route goes on. No route: just the body.
    lua, ns = nav_env
    N = ns.Nav
    lua.execute("""
      AGPS_T = 0
      GetTime = function() return AGPS_T end
      AGPS_GHOST = false
      UnitIsGhost = function() return AGPS_GHOST end
      C_DeathInfo = { GetCorpseMapPosition = function(id)
        if id == AGPS_KALIMDOR then return { x = 0.6, y = 0.5 } end
      end }
    """)
    lua.globals().AGPS_NSREF = ns
    lua.execute("""
      for id, m in pairs(AGPS_NSREF.Maps) do
        if m.type == 2 and m.continent == 1 and m.bounds then AGPS_KALIMDOR = id end
      end
    """)
    assert lua.eval("AGPS_KALIMDOR")
    ns.settings = lua.eval("{ gps = { fastestOrder = true } }")

    def step():
        lua.execute("AGPS_T = AGPS_T + 2")
        return N.Status(-500.0, -4500.0, 1)

    N.SetStops(lua.table(lua.table(x=-600.0, y=-4180.0, cont=1, name="A"), lua.table(x=-800.0, y=-4400.0, cont=1, name="B")))
    step()
    assert len(N.stops) == 2
    lua.execute("AGPS_GHOST = true")
    step()
    assert len(N.stops) == 3 and N.stops[1].corpse and N.stops[1].icon == 8 and N.stops[2].name == "A"
    assert N.OrderStops(-500.0, -4500.0, 1) is False and N.stops[1].corpse  # never moved
    assert N.route is None or N.Route(-500.0, -4500.0, 1)
    lua.execute("AGPS_GHOST = false")
    step()
    assert [N.stops[i].name for i in (1, 2)] == ["A", "B"] and len(N.stops) == 2
    # no route at all: just the body
    N.Clear()
    lua.execute("AGPS_GHOST = true")
    step()
    assert len(N.stops) == 1 and N.stops[1].corpse


def undercity_env(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua", "Data/Caves.lua",
         "Data/Capitals.lua")  # (as the toc: the caves and capitals too)
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    lua.execute("""
      AGPS_MAP = 1458
      C_Map = C_Map or {}
      C_Map.GetBestMapForUnit = function() return AGPS_MAP end
    """)
    return lua, ns, 10001


def test_undercity_is_its_own_level(nav_env):
    # Down in Undercity (the game reports its map): the player routes on the city's level,
    # and stops placed on its floors are on it; drawn in Eastern Kingdoms coordinates.
    lua, ns, UC = undercity_env(nav_env)
    N, Geo = ns.Nav, ns.Geo
    tq = (1560.0, 228.0)  # the Trade Quarter's raised ring
    assert N.PlayerLevel(0) == UC
    assert N.StopLevel(0, *tq) == UC
    assert Geo.MapCont(1458) == UC and Geo.Base(UC) == 0
    assert tuple(Geo.ToContinent(UC, 10.0, 20.0, 0)) == (10.0, 20.0)
    lua.execute("AGPS_MAP = 1420")  # up in Tirisfal
    lua.execute("GetTime = function() return 100 end")
    assert N.PlayerLevel(0) == 0


def test_a_stop_by_a_ledge_down_in_undercity_stays_down_there(nav_env):
    # (reported) down at the bottom, a stop on the First Aid trainer (at the edge of the bank's
    # level, over the drop): "board the lift to the Ruins". A spot a yard or two off the
    # trainer is a closed cell (the ledge), but it's the city's floors, not the Ruins up top.
    lua, ns, UC = undercity_env(nav_env)
    N = ns.Nav
    assert N.PlayerLevel(0) == UC
    ledge = (1522.7, 166.05)  # next to the First Aid trainer, over the drop
    assert not ns.Passability.IsOpen(UC, *ledge)
    assert N.StopLevel(0, *ledge) == UC
    N.SetDestination(ledge[0], ledge[1], N.StopLevel(0, *ledge), "First Aid")
    r = N.Route(1588.6, 174.8, 0)  # at the bottom, below the bank
    assert all(not (l.ride and l.ride[8] == "lift") for l in r.legs.values())


def test_out_of_the_ruins_through_the_north_gate(nav_env):
    # (reported) from a lift's top to anywhere outside: out the north gate onto the road, not
    # straight over the ruins' walls (the road outside the gate was dropped: its end crossed
    # the gate's steps, so the ruins' roads led nowhere and routes fell back to a straight line)
    lua, ns, UC = undercity_env(nav_env)
    R, P = ns.Router, ns.Passability
    for offroad in (False, True):
        # Brill, the Sepulcher, Tarren Mill, and the road just west of the Ruins (reported: over the west bank)
        for stop in ((2250.0, 280.0), (505.0, 1570.0), (-20.0, -900.0), (1560.0, 540.0)):
            r = R.Route(0, 1594.9, 290.8, stop[0], stop[1], lua.table(offroad=offroad))
            pts = [(r.pts[i], r.pts[i + 1]) for i in range(1, len(r.pts), 2)]
            assert len(pts) > 3, (offroad, stop)
            # out across the gate's line (x 1866), in its opening (y 208 to 268)
            gate = [a[1] + (b[1] - a[1]) * (1866 - a[0]) / (b[0] - a[0]) for a, b in zip(pts, pts[1:])
                    if (a[0] - 1866) * (b[0] - 1866) < 0]
            assert gate and 208 <= gate[0] <= 268, (offroad, stop, gate)
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                d = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                n, run = max(1, int(d / 0.5)), 0
                for k in range(1, n):
                    v = P.OverlayRaw(0, x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n, True)
                    run = run + 1 if v == 2 else 0
                    assert run < 5, (offroad, stop, x1, y1, x2, y2)  # (a corner, not through a wall)


def test_the_map_shows_undercitys_roads_on_its_map(nav_env):
    # (reported) Undercity's map (its model's inside map, or its zone map) showed no roads, and
    # zoomed out the city's roads lay over the Ruins on Tirisfal's map: the art shown decides
    lua, ns, UC = undercity_env(nav_env)
    G = ns.GPS
    wmo = ns.CityLevels[UC].wmo
    assert G.CityArtLevel(wmo) == UC and G.CityArtLevel(None, 1458) == UC
    assert G.CityArtLevel(None, 1420) is None and G.CityArtLevel(12345) is None  # Tirisfal, a building
    # the road tools draw on the level shown there: the city's over its map, over the city only
    saved = []
    ns.Print = lambda *a: None
    ns.Record = lua.table(Save=lambda t: saved.append(t) or len(saved))
    lua.execute("C_Map.GetMapInfo = function() return { name = 'Undercity' } end time = os.time")
    line = lambda x, y: lua.table(cont=0, pts=lua.table(x, y, x + 10, y, x + 20, y))
    G.shownLevel, G.shownCont = UC, 0
    G.FinishRoad(line(1560.0, 228.0))
    G.FinishRoad(line(-9000.0, 400.0))
    G.shownLevel = 0  # Tirisfal's map
    G.FinishRoad(line(1560.0, 228.0))
    assert [t.continent for t in saved] == [UC, 0, 0]


def test_undercitys_map_stays_up_anywhere_over_the_city_while_down_in_it(nav_env):
    # (reported, a recording) zooming in on the city's map moved the view off the player, and the
    # outside map (the Ruins' ground) flipped in and out: down there, the city's map anywhere over it
    lua, ns, UC = undercity_env(nav_env)
    G = ns.GPS
    lua.execute("GetTime = function() return 10 end")
    assert G.DownInCityAt(0, 1700.0, 60.0) == UC  # the Magic Quarter, the player elsewhere down there
    assert G.DownInCityAt(0, -9000.0, 400.0) is None  # Elwynn
    lua.execute("AGPS_MAP = 1420 GetTime = function() return 100 end")  # up in Tirisfal
    assert G.DownInCityAt(0, 1700.0, 60.0) is None


def test_right_click_in_a_building_goes_to_the_outside_view_first(nav_env):
    # (reported) inside a building, its inside map shown: a right-click jumped to the continent's
    # map. First the outside view there (kept while in that building), the continent's map next.
    lua, ns, UC = undercity_env(nav_env)
    G = ns.GPS
    browsed = []
    G.Browse = lambda *a: browsed.append(a)
    G.shownInside, G.outsideOf = "Inn", None
    G.TerrainZoomOut()
    assert G.outsideOf == "Inn" and G.shownInside is None and not browsed
    assert G.KeepOutside("Inn", "Inn") == "Inn"  # still in there: still outside
    assert G.KeepOutside("Inn", None) is None  # left it: its inside map again next time in
    assert G.KeepOutside("Inn", "Bank") is None
    assert G.KeepOutside(None, "Inn") is None


def test_down_in_undercity_the_route_starts_on_the_players_own_floor(nav_env):
    # (reported) under a walkway, the top floor's height at the player's spot is the walkway's:
    # the route started up there (up the stairs and back). The game's height says which floor.
    lua, ns, UC = undercity_env(nav_env)
    R, N = ns.Router, ns.Nav
    zoff = ns.CityLevels[UC].zoff
    start, stop = (1520.0, 172.0), (1677.8, 99.0)  # under the First Aid walkway; the Fishing trainer
    assert N.CityHeight(UC, *start) > -110  # (the top floor there: the walkway)
    lua.execute(f"UnitPosition = function() return {start[1]}, {start[0]}, {-124.0 + zoff}, 0 end")
    assert abs(N.PlayerCityZ(UC) + 124) < 0.1
    r = R.Route(UC, start[0], start[1], stop[0], stop[1], lua.table(offroad=False, z=-124.0 + zoff, tz=-61.9))
    near = [r.zs[i] - zoff for i in range(2, 4)]  # (the route's own heights: floors over floors)
    assert all(z < -118 for z in near)  # (on the bottom floor, not up the walkway)


def test_city_places_carry_their_npcs_height_to_the_stop(nav_env):
    # (reported) the Cooking trainer and Guild Master are on the bank's level, 12 yd under the
    # walkway the route went to: a place's height (its NPC's) tells the floor
    lua, ns, UC = undercity_env(nav_env)
    load(lua, ns, "Layers.lua", "Data/CityPlaces.lua")
    L = ns.Layers
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = { layerCity = true, style = 'minimap' } }")
    L.RevealCity()
    cook = next(p for p in L.RevealedPlaces(0).values() if p[3] == "Undercity Cooking Trainer")
    assert abs(cook.z - -55.3) < 0.5 and abs((cook.z - ns.CityLevels[UC].zoff) - N_bank(ns, UC)) < 5
    marks = L.Marks(0, cook[1], cook[2], 400.0, lua.table(), UC)
    mark = next(marks[i] for i in range(1, len(marks) + 1) if marks[i][4] == "Undercity Cooking Trainer")
    assert mark[13] == cook.z
    assert L.PlaceZ(UC, cook[1] + 3, cook[2], "Undercity Cooking Trainer") == cook.z  # (a guard's directions)
    assert L.PlaceZ(UC, cook[1] + 80, cook[2], "Undercity Cooking Trainer") is None


def N_bank(ns, UC):
    return ns.Nav.CityHeight(UC, 1598.0, 262.0)  # (the bank's floor, the model's own height)


def test_undercitys_roads_are_on_floors_over_floors(nav_env):
    # (reported) the Cooking trainer and Guild Master on the bank's level, a Warlock trainer on
    # the Magic Quarter's lower floor, First Aid on its walkway: each place's own floor, reached
    # by the roads on that floor (floors over floors), not the top floor over it
    lua, ns, UC = undercity_env(nav_env)
    R = ns.Router
    zoff = ns.CityLevels[UC].zoff
    lift = (1545.3, 239.5, -104.0 + zoff)
    # (the places: Cooking, Guild Master, a Warlock trainer, First Aid; and at most how long, from the
    # south lift: the old top-floor network's were 240, 216, 611 and 463 yd; on foot over the floors,
    # the Warlock's is 437, First Aid's 324: not the 112 of a way dropping through the floors; the
    # Guild Master's 114 went down steps of 3-4 yd off a ledge, walked it's up the Trade Quarter's steps)
    for x, y, z, most in ((1590.5, 277.0, -55.3, 160), (1591.2, 204.5, -55.3, 200), (1780.3, 44.0, -61.4, 650),
                          (1525.0, 171.4, -62.1, 460)):
        r = R.Route(UC, lift[0], lift[1], x, y, lua.table(offroad=False, z=lift[2], tz=z))
        n = len(r.pts) // 2
        last_road = next(r.zs[i] for i in range(n - 1, 0, -1) if r.zs[i])
        assert abs(last_road - z) <= 4, (x, y, z, last_road)  # (on the place's floor, not the one over it: 12 yd up)
        assert r.length < most, (x, y, r.length)


def test_undercity_legs_off_the_roads_dont_cross_gaps_or_walls(nav_env):
    # (the 600-trip sweep) a leg onto the roads went over a hole down to the floor below, and across
    # a canal's water: on the one-floor grid, a top floor well under the leg is a gap at its height
    lua, ns, UC = undercity_env(nav_env)
    R = ns.Router
    zoff = ns.CityLevels[UC].zoff
    assert R.WallYards(UC, 1594.4, 170.0, -104.0 + zoff, 1586.3, 165.8, -108.5 + zoff) > R.LAYER_VOID_YD  # (the hole)
    assert R.VoidYards(UC, 1765.0, 240.0, 1743.0, 240.0) > R.LAYER_VOID_YD  # (the canal)
    assert R.WallYards(UC, 1594.4, 170.0, -104.0 + zoff, 1602.3, 169.8, -103.5 + zoff) <= R.LAYER_VOID_YD  # (along the walkway)


def test_undercity_routes_dont_drop_through_the_floors(nav_env):
    # (reported) from the walkway by the Apothecarium to the Enchanting trainer below: 55 yd, down
    # through the floor; on foot it's round by the passage (222 yd over the floors). Floors stacked
    # a few yards apart had let a way zig-zag down through them (clear_step now).
    lua, ns, UC = undercity_env(nav_env)
    R = ns.Router
    zoff = ns.CityLevels[UC].zoff
    r = R.Route(UC, 1528.45, 268.79, 1487.48, 274.54, lua.table(offroad=False, z=-108.0 + zoff, tz=-62.1))
    assert r.length > 150
    n = len(r.pts) // 2
    for i in range(1, n):
        a, b = r.zs[i], r.zs[i + 1]
        if a and b:
            d = ((r.pts[2 * i + 1] - r.pts[2 * i - 1]) ** 2 + (r.pts[2 * i + 2] - r.pts[2 * i]) ** 2) ** 0.5
            assert abs(a - b) <= max(6, 2 * d), (i, a - zoff, b - zoff, d)


def test_no_undercity_road_climbs_steeper_than_a_stair(nav_env):
    # (a stair between floors whose cells were joined in the wrong order jumped and doubled back:
    # a road a yard long rising 13 yd. Between two nodes, no steeper than a stair.)
    lua, ns, UC = undercity_env(nav_env)
    e, g = ns.Router.Edges(UC)
    steep = []
    for i in range(1, len(e) + 1):
        a, b, length = e[i][1], e[i][2], e[i][3]
        dz = abs(g.z[a] - g.z[b])
        if dz > 1.2 * length + 3:
            steep.append((i, round(length, 1), round(dz, 1)))
    assert len(steep) <= 0.005 * len(e), steep[:10]  # (a few quirks of the floors: 80 when the stairs' cells were in the wrong order)


def test_undercity_roads_dont_climb_onto_a_canals_rim(nav_env):
    # (reported) by the Trade Quarter's edge, the Enchanting trainer 95 yd away "straight" down: the
    # road stepped up onto the canal's rim (4 yd up, one diagonal step of the floors) and across.
    # The way is round by the passages (about 200 yd and more).
    lua, ns, UC = undercity_env(nav_env)
    R = ns.Router
    zoff = ns.CityLevels[UC].zoff
    start, trainer = (1545.7, 292.8), (1487.5, 274.5)
    r = R.Route(UC, *start, *trainer, lua.table(offroad=False, z=-124.5 + zoff, tz=-62.1))
    pts, _ = route_pts(r)
    assert r.length > 150, round(r.length)
    assert min(math.hypot(x - 1536, y - 300) for x, y in pts) > 4  # (not over the rim)
    e, g = R.Edges(UC)
    rim = [i for i in range(1, len(e) + 1) if abs(g.z[e[i][1]] - g.z[e[i][2]]) > 3.2 * max(e[i][3], 1)]
    assert len(rim) <= 0.002 * len(e), rim[:10]


def test_a_route_to_another_continent_is_overviewed_on_the_world_map(nav_env):
    # (reported) routing over the sea, the overview zoomed out to the continent's map: the world
    # map shows both ends (then back to following the player, in their own view)
    lua, ns, UC = undercity_env(nav_env)
    G, N = ns.GPS, ns.Nav
    N.stops = lua.eval("{ { x = 1600, y = -4400, cont = 1 } }")  # Orgrimmar, from Eastern Kingdoms
    assert G.TourAcrossContinents(0)
    N.stops = lua.eval("{ { x = 2250, y = 280, cont = 0 } }")  # Brill: the same continent
    assert not G.TourAcrossContinents(0)
    N.stops = lua.eval("{ { x = 1590, y = 277, cont = 10001 } }")  # down in Undercity: on it too
    assert not G.TourAcrossContinents(0)
    # (reported, a recording) a stop on this continent reached through the other one (Tirisfal to
    # Riverglades by the zeppelins through Durotar): the world map too
    N.stops = lua.eval("{ { x = -12000, y = 200, cont = 0 } }")
    N.route = lua.eval("{ parts = { { cont = 0, pts = {} }, { cont = 1, pts = {} }, { cont = 0, pts = {} } } }")
    assert G.TourAcrossContinents(0)
    N.route = None


def test_undercity_lift_tops_are_up_top(nav_env):
    # The halls at the lifts' tops report Undercity's map too, but they're up at the surface:
    # a stop in the Trade Quarter right below is down a lift, not a few yards away.
    lua, ns, UC = undercity_env(nav_env)
    N = ns.Nav
    lua.execute('GetSubZoneText = function() return "Ruins of Lordaeron" end')
    assert N.PlayerLevel(0) == 0
    top = (1570.0, 240.0)  # the hall at the west lift's top
    legs, secs = N.Plan(N.PlayerLevel(0), top[0], top[1], 7.0, lua.table(x=1593.0, y=238.0, cont=UC))
    rides = [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride]
    assert len(rides) == 1 and rides[0][8] == "lift"
    lua.execute('GetSubZoneText = function() return "Trade Quarter" end GetTime = function() return 100 end')
    assert N.PlayerLevel(0) == UC


def test_undercity_walk_to_the_road_goes_round_walls(nav_env):
    # (reported) by a wall north of the Trade Quarter, heading for the bank: onto the road
    # beside the player, not through the one-cell wall to the road past it. (Floors over floors:
    # a short step onto a road on the player's own floor; the 3D walk of Undercity's routes
    # over its floors is checked offline.)
    lua, ns, UC = undercity_env(nav_env)
    R = ns.Router
    zoff = ns.CityLevels[UC].zoff
    here = ns.Nav.CityHeight(UC, 1594.4, 170.0)
    r = R.Route(UC, 1594.4, 170.0, 1595.6, 232.5, lua.table(offroad=False, z=here + zoff, tz=-52.1))
    first = ((r.pts[3] - r.pts[1]) ** 2 + (r.pts[4] - r.pts[2]) ** 2) ** 0.5
    assert first <= 8 and abs(r.zs[2] - zoff - here) <= 3


def test_a_safe_drop_depends_on_health(nav_env):
    # (a drop off a ledge: taken when the fall is safe; health decides how far. Undercity's
    # roads have none now: floors over floors, joined by their stairs and ramps)
    lua, ns, UC = undercity_env(nav_env)
    # health decides how far: full health survives more than a sliver
    lua.execute("UnitHealth = function() return AGPS_HP end UnitHealthMax = function() return 100 end")
    lua.execute("AGPS_HP = 100")
    full = ns.Nav.SafeDrop()
    lua.execute("AGPS_HP = 20")
    assert full > 40 and ns.Nav.SafeDrop() == ns.Nav.FALL_FREE


def test_any_banker_reaches_a_bank_stop(nav_env):
    # the guard marked one spot; the bank window opening near it (another banker) will do
    lua, ns, UC = undercity_env(nav_env)
    N = ns.Nav
    N.SetStops(lua.table(lua.table(x=1595.6, y=232.5, cont=UC, name="Undercity Bank"),
                         lua.table(x=1760.0, y=335.0, cont=UC, name="War Quarter")))
    assert not N.OnService("AUCTION_HOUSE_SHOW", 1590.0, 225.0, 0)  # not the bank's window
    assert not N.OnService("BANKFRAME_OPENED", 1700.0, 300.0, 0)  # a bank far away
    assert N.OnService("BANKFRAME_OPENED", 1590.0, 225.0, 0)
    N.Status(1590.0, 225.0, 0)
    assert len(N.stops) == 1 and N.dest.name == "War Quarter"


def test_undercity_says_below_or_above(nav_env):
    lua, ns, UC = undercity_env(nav_env)
    N = ns.Nav
    ring, bank_floor = (1560.0, 228.0), (1605.0, 240.0)  # the raised ring, and the bank's floor
    assert N.CityHeight(UC, *ring) > N.CityHeight(UC, *bank_floor) + 6
    N.SetStops(lua.table(lua.table(x=bank_floor[0], y=bank_floor[1], cont=UC, name="Bank")))
    way, yd = N.HeightHint(ring[0], ring[1], 0)
    assert way == "down" and yd >= 6 and "Below you" in N.HeightText(ring[0], ring[1], 0)
    # up at the lift tops: down a lift
    lua.execute('GetSubZoneText = function() return "Ruins of Lordaeron" end GetTime = function() return 50 end')
    assert N.HeightText(1586.0, 240.0, 0) == "|cff80c0ffBelow you (down a lift)|r"


def test_guard_locations_down_in_undercity_are_on_its_level(nav_env):
    # (reported) the Enchanting Trainer, marked on the continent's map: it's down in the city
    lua, ns, UC = undercity_env(nav_env)
    load(lua, ns, "Layers.lua")
    L = ns.Layers
    assert L.CityLevelAt(0, 1488.82, 278.71) == UC
    assert L.CityLevelAt(0, 2250.0, 250.0) is None  # Brill: up on the continent
    ns.db = lua.eval('{ cityPois = { [0] = { { 1488.82, 278.71, "Undercity Enchanting Trainer" }, { 2250, 250, "Brill" } } } }')
    db = L.CityDB()
    assert len(db[0]) == 1 and db[UC][1][3] == "Undercity Enchanting Trainer"


def test_undercity_lower_level_walks_stay_on_their_floor(nav_env):
    # (reported) down by the ring's foot, to the Enchanting Trainer: onto the road on the same
    # floor, not up onto the ring through its wall
    lua, ns, UC = undercity_env(nav_env)
    R, P = ns.Router, ns.Passability
    zoff = ns.CityLevels[UC].zoff
    here = ns.Nav.CityHeight(UC, 1541.9, 295.6)  # (the floor by the ring's foot)
    r = R.Route(UC, 1541.9, 295.6, 1488.82, 278.71, lua.table(offroad=False, z=here + zoff, tz=-62.1))
    assert abs(r.zs[2] - zoff - here) < 4  # (onto the road on the same floor)


def test_city_places_show_after_talking_to_a_guard(nav_env):
    lua, ns, UC = undercity_env(nav_env)
    load(lua, ns, "Layers.lua", "Data/CityPlaces.lua")
    L = ns.Layers
    ns.db = lua.eval("{}")
    assert len(L.RevealedPlaces(0)) == 0  # nothing until a guard there is talked to
    guard = lua.eval('{ { name = "The bank" }, { name = "The inn" }, { name = "A class trainer" } }')
    other = lua.eval('{ { name = "Let me browse your goods." } }')
    assert L.IsGuardMenu(guard) and not L.IsGuardMenu(other)
    L.RevealCity()  # (the player's map: Undercity)
    names = {p[3]: p.cont for p in L.RevealedPlaces(0).values()}
    assert names.get("Undercity Bank") == UC and "Undercity Enchanting Trainer" in names
    assert not any(n.startswith("Orgrimmar") for n in names)


def test_a_guard_in_any_capital_shows_all_its_places(nav_env):
    # (reported: a Stormwind guard showed only the place asked for) every capital has its places,
    # the Alliance's too: a guard there shows them all, and only that city's
    lua, ns, UC = undercity_env(nav_env)
    load(lua, ns, "Layers.lua", "Data/CityPlaces.lua")
    L = ns.Layers
    real = lua.eval("C_Map.GetBestMapForUnit")
    try:
        for ui, city, cont in ((1453, "Stormwind", 0), (1455, "Ironforge", 0), (1457, "Darnassus", 1),
                               (1454, "Orgrimmar", 1), (1456, "Thunder Bluff", 1), (1458, "Undercity", 0)):
            ns.db = lua.eval("{}")
            lua.execute(f"C_Map.GetBestMapForUnit = function() return {ui} end")
            L.RevealCity()
            names = [p[3] for p in L.RevealedPlaces(cont).values()]
            assert len(names) >= 19, (city, len(names))
            assert f"{city} Bank" in names and f"{city} Inn" in names, city
            assert all(n.startswith(city + " ") for n in names), city
    finally:
        lua.globals().C_Map.GetBestMapForUnit = real


def test_undercity_places_show_only_down_in_the_city(nav_env):
    lua, ns, UC = undercity_env(nav_env)
    load(lua, ns, "Layers.lua", "Data/CityPlaces.lua")
    L = ns.Layers
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = { layerCity = true, style = 'minimap' } }")
    L.RevealCity()
    bank = next(p for p in L.RevealedPlaces(0).values() if p[3] == "Undercity Bank")
    def names(level):
        marks = L.Marks(0, bank[1], bank[2], 400.0, lua.table(), level)
        return {marks[i][4] for i in range(1, len(marks) + 1)}
    assert "Undercity Bank" not in names(0)  # up in Tirisfal: not over the Ruins
    assert "Undercity Bank" not in names(None)  # (looking at another map)
    assert "Undercity Bank" in names(UC)  # down in the city


def test_a_city_place_s_stop_is_down_in_the_city_even_without_floor_data_under_it(nav_env):
    lua, ns, UC = undercity_env(nav_env)
    load(lua, ns, "Layers.lua", "Data/CityPlaces.lua")
    L = ns.Layers
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = { layerCity = true, style = 'minimap' } }")
    L.RevealCity()
    priest = next(p for p in L.RevealedPlaces(0).values() if p[3] == "Undercity Priest Trainer")
    marks = L.Marks(0, priest[1], priest[2], 400.0, lua.table(), UC)
    mark = next(marks[i] for i in range(1, len(marks) + 1) if marks[i][4] == "Undercity Priest Trainer")
    assert mark[12] == UC  # (a stop made from it goes down the lift, though no floor is under its booth)


def test_zone_hover_says_the_levels_colored_for_the_player(router):
    lua, ns = router
    G = ns.GPS
    assert list(G.ZoneHoverText(1, "Desolace", 35))[:2] == ["Desolace", "Level 30-40"]
    assert tuple(G.ZoneHoverText(1, "Desolace", 35))[2:] == (1, 1, 0)  # yellow: in range
    assert tuple(G.ZoneHoverText(1, "Desolace", 12))[2:] == (1, 0.1, 0.1)  # red: far below
    assert tuple(G.ZoneHoverText(1, "Desolace", 60))[2:] == (0.6, 0.6, 0.6)  # gray: far above
    assert G.ZoneHoverText(1, "Somewhere New", 10) == "Somewhere New"  # no levels known


def test_ruins_of_lordaeron_walk_follows_its_roads(nav_env):
    # (reported) from the Ruins' north gate to a lift: along the ruins' roads, round their
    # walls and slime, not straight across the courtyard
    lua, ns, UC = undercity_env(nav_env)
    R, P = ns.Router, ns.Passability
    r = R.Route(0, 1835.7, 236.2, 1545.0, 240.0, lua.table(offroad=False))
    pts, kinds = r.pts, r.kinds
    road, bad = 0.0, 0
    for i in range(1, len(pts) - 2, 2):
        x1, y1, x2, y2 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        d = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if kinds[(i + 1) // 2] == 0:
            road += d
        m = max(1, int(d))
        bad += sum(1 for k in range(1, m) if not P.IsOpen(0, x1 + (x2 - x1) * k / m, y1 + (y2 - y1) * k / m))
    assert road > 0.8 * r.length and bad <= 3


def test_undercity_trainer_from_the_walkway_beside_it(nav_env):
    # (reported) on the Apothecarium's upper walkway, the trainer just round the corner: not
    # down off the walkway and round below (its marker sits on a sliver of the lower floor)
    lua, ns, UC = undercity_env(nav_env)
    r = ns.Router.Route(UC, 1481.7, 295.6, 1488.82, 278.71, lua.table(offroad=False))
    assert r.length < 40
    assert all(r.kinds[i] != ns.Router.KIND_DROP for i in range(1, len(r.kinds) + 1))


def test_ruins_lift_hall_to_each_lift(nav_env):
    # (reported) in the hall between the guardians: straight down a corridor to a lift
    lua, ns, UC = undercity_env(nav_env)
    for lift in ((1597.0, 190.0), (1545.0, 240.0), (1595.0, 291.0)):
        r = ns.Router.Route(0, 1596.3, 241.0, lift[0], lift[1], lua.table(offroad=False))
        assert r.length < 70, (lift, r.length)


def test_undercity_route_stays_on_the_floors(nav_env):
    # Trade Quarter to the War Quarter hall: along the city's roads, and the walks to and
    # from them on its walkable floors (no straight line through a wall or off a ledge; the
    # stairs between levels are roads, through the ledges' cells).
    lua, ns, UC = undercity_env(nav_env)
    N, P = ns.Nav, ns.Passability
    N.SetStops(lua.table(lua.table(x=1760.0, y=335.0, cont=UC, name="War Quarter")))
    r = N.Route(1560.0, 228.0, 0)
    assert r and r.walkYards > 200
    pts = r.pts
    bad = 0
    for i in range(1, len(pts) - 2, 2):
        if r.kinds[(i + 1) // 2] in (0, 4):  # (a road, or a drop off a ledge)
            continue
        x1, y1, x2, y2 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
        for k in range(1, 10):
            f = k / 10
            if not P.IsOpen(UC, x1 + (x2 - x1) * f, y1 + (y2 - y1) * f):
                bad += 1
    assert bad <= 3  # (a cell or so of slack at corners)


def test_undercity_to_brill_takes_a_lift(nav_env):
    lua, ns, UC = undercity_env(nav_env)
    N = ns.Nav
    legs, secs = N.Plan(UC, 1593.0, 238.0, 7.0, lua.table(x=2250.0, y=250.0, cont=0))
    rides = [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride]
    assert len(rides) == 1 and rides[0][8] == "lift"


# ---- Caves (Data/Caves.lua) --------------------------------------------------------------

def caves_world(lua, ns, caves=True):
    load(lua, ns, "Data/Roads.lua", "Data/Terrain.lua", *(("Data/Caves.lua",) if caves else ()),
         "Passability.lua", "Router.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    ns.Router.WARM = False
    ns.Passability.ClearCache()
    return lua, ns


@pytest.fixture
def caves_env(env):
    return caves_world(*env)


def cave_cell(ns, cont, x, y):
    """A cave overlay's own value at (x, y) and its grid, or (None, None)."""
    r = ns.Passability.OverlayRaw(cont, x, y)
    return r if isinstance(r, tuple) else (r, None)


def cave_key(ns, cont, name):
    caves = ns.Caves[cont]
    return next(caves[i][2] for i in range(1, len(caves) + 1) if caves[i][1] == name)


def check_cave_route(ns, cont, name, r, mouths):
    """Along the cave's roads, in by a mouth, never through its closed cells: (share on roads,
    yards through closed cells)."""
    pts, kinds = route_pts(r)
    grid = ns.Terrain[cave_key(ns, cont, name)]
    road = closed = 0.0
    for i, k in enumerate(kinds):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        d = math.hypot(x2 - x1, y2 - y1)
        road += d if k == 0 else 0
        n = max(1, int(d))
        for s in range(n + 1):
            v, g = cave_cell(ns, cont, x1 + (x2 - x1) * s / n, y1 + (y2 - y1) * s / n)
            if v == 2 and g.tx0 == grid.tx0 and g.ty0 == grid.ty0:
                closed += d / (n + 1)
    near_mouth = min(math.hypot(x - mx, y - my) for x, y in pts for mx, my in mouths)
    assert near_mouth < 15, near_mouth  # (in by its mouth, not through the hill)
    return road / r.length, closed


def test_route_into_burning_blade_coven_follows_its_roads(caves_env):
    # From Durotar's road to the cave's far end: out along its way in (through the basin south
    # of it, not over the ridge), in at its mouth, along its tunnels.
    lua, ns = caves_env
    r = ns.Router.Route(1, -84.0, -4743.0, -62.0, -4229.0, lua.table(offroad=False))
    share, closed = check_cave_route(ns, 1, "Burning Blade Coven", r,
                                     [(-174.0, -4343.0), (-182.0, -4385.0), (-200.0, -4361.0)])
    assert share > 0.9 and closed < 15
    assert r.length < 2000


def test_route_into_fargodeep_mine_follows_its_roads(caves_env):
    # A mine under a hill (its floors under walkable ground): into its deep end by the mouth.
    lua, ns = caves_env
    r = ns.Router.Route(0, -9703.0, 299.0, -9830.0, 181.0, lua.table(offroad=False))
    share, closed = check_cave_route(ns, 0, "Fargodeep Mine", r,
                                     [(-9808.0, 211.0), (-9822.0, 211.0), (-9838.0, 171.0), (-9848.0, 219.0), (-9856.0, 175.0)])
    assert share > 0.9 and closed < 10
    assert r.length < 800


def test_up_top_over_a_mine_keeps_off_its_roads(caves_env):
    # On the hill over Fargodeep Mine: outdoors, the roads to get on at are the land's, not the
    # mine's under it; indoors (down in it), only the mine's.
    lua, ns = caves_env
    R = ns.Router
    x, y = -9790.0, 140.0
    assert cave_cell(ns, 0, x, y)[0] == 3  # (a floor under walkable ground)
    _, g = R.Edges(0)
    near = R.NearestEdges(0, x, y)
    assert not R.CaveDown(0, x, y, False) and R.CaveDown(0, x, y, True) and R.CaveDown(0, x, y)
    up = R.CaveLevel(g, 0, near, False, False)
    down = R.CaveLevel(g, 0, near, True, False)
    assert any(g.cave[near[i].edge] for i in range(1, len(near) + 1))
    assert not any(g.cave[up[i].edge] for i in range(1, len(up) + 1)) and len(up) > 0
    assert all(g.cave[down[i].edge] for i in range(1, len(down) + 1))


def test_surface_routes_away_from_caves_unchanged(env):
    # Trips nowhere near a cave route the same with the caves loaded.
    trips = [(0, (2250.0, 250.0), (1841.0, 236.0)), (1, (1300.0, -4400.0), (1050.0, -4450.0)),
             (1, (-2350.0, -350.0), (-2100.0, -500.0))]
    lua, ns = env
    with_caves = caves_world(lua, ns)
    got = [route_pts(ns.Router.Route(c, *a, *b, lua.table(offroad=o))) for c, a, b in trips for o in (False, True)]
    lua2 = lupa.LuaRuntime()
    lua2.execute(PRELUDE)
    ns2 = lua2.table()
    ns2.IsSecret = lua2.eval("function(v) return false end")
    load(lua2, ns2, "Geo.lua")
    caves_world(lua2, ns2, caves=False)
    want = [route_pts(ns2.Router.Route(c, *a, *b, lua2.table(offroad=o))) for c, a, b in trips for o in (False, True)]
    assert got == want


def test_cave_roads_join_the_land_roads_at_their_mouths(caves_env):
    # Each cave road ending on a land road (joins) is tied onto it: the network runs on.
    lua, ns = caves_env
    for cont in (0, 1):
        ov = ns.RoadOverlays[cont]
        extra = next(ov[i] for i in range(1, len(ov) + 1) if ov[i].cave)
        base = len(ns.Roads[cont].n) // 2
        _, g = ns.Router.Edges(cont)
        last = base + len(extra.n) // 2
        # (roads drawn since the caves were generated can move a road off a mouth: that one
        # falls back to a gap link, so nearly all, not all)
        tied = 0
        for k in range(1, len(extra.joins) + 1):
            j = base + extra.joins[k]
            links = g.adj[j]
            tied += any(links[i][1] <= base or links[i][1] > last for i in range(1, len(links) + 1))
        assert tied >= 0.95 * len(extra.joins), (cont, tied, len(extra.joins))


# ---- Capitals at ground level (Data/Capitals.lua) --------------------------------------------

def capitals_world(lua, ns, capitals=True):
    load(lua, ns, "Data/Maps.lua", "Data/CityPlaces.lua", "Data/Roads.lua", "Data/Terrain.lua", "Data/Caves.lua",
         *(("Data/Capitals.lua",) if capitals else ()), "Passability.lua", "Router.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    ns.Router.WARM = False
    ns.Passability.ClearCache()
    return lua, ns


@pytest.fixture
def capitals_env(env):
    return capitals_world(*env)


def test_stormwind_s_roads_are_its_streets(capitals_env):
    # (reported: Stormwind's roads jumbled everywhere and into the water) the land's roads (traced from
    # the ground's textures and NPCs' paths) don't run over a model-built capital's own cells any more
    # (roads drawn in game excepted), and the city's own roads are its streets, not every floor's middle
    lua, ns = capitals_env
    P = ns.Passability
    roads = ns.Roads[0]
    inside = 0
    for i in range(1, len(roads.e) + 1):
        e = roads.e[i]
        if e[4] == 2:  # (drawn in game)
            continue
        for k in range(5, len(e) + 1, 2):
            x, y = e[k], e[k + 1]
            # (well inside: the land's roads run on 20 yd into a capital's grid, up to its gates)
            if -9100 < x < -8300 and 350 < y < 1200 and all(
                    P.Overlay(0, x + dx, y + dy) in (0, 2) for dx, dy in
                    ((0, 0), (25, 0), (-25, 0), (0, 25), (0, -25), (18, 18), (18, -18), (-18, 18), (-18, -18))):
                inside += 1
    assert inside == 0
    ov = next(o for o in ns.RoadOverlays[0].values() if o.capital)  # (the continent's capitals' roads)
    total = 0.0
    for i in range(1, len(ov.e) + 1):
        e = ov.e[i]
        x, y = ov.n[2 * e[1] - 1], ov.n[2 * e[1]]
        if -9200 < x < -8200 and 200 < y < 1300:  # (Stormwind's)
            total += e[3]
    assert 5000 < total < 22000  # (every floor's middle: 36,000 yd)


def city_places(ns, ui_map):
    """A capital's places (Data/CityPlaces.lua, map %) in world yards: [(name, x, y)]."""
    c, b = ns.CityPlaces[ui_map], ns.Maps[ui_map].bounds
    minX, minY, maxX, maxY = (b[i] for i in range(1, 5))
    return [(c[i][3], maxX - c[i][2] / 100 * (maxX - minX), maxY - c[i][1] / 100 * (maxY - minY))
            for i in range(1, len(c) + 1)]


def check_capital_route(ns, cont, r):
    """(share of the route on roads, yards of off-road legs through the capital's closed cells,
    the last leg's yards)."""
    P = ns.Passability
    pts, kinds = route_pts(r)
    road = closed = drawn = 0.0
    for i, k in enumerate(kinds):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        d = math.hypot(x2 - x1, y2 - y1)
        drawn += d
        road += d if k in (0, 4, 5, 6) else 0  # (roads, drops off ledges, lifts)
        if k == 1:
            n = max(1, int(d))
            closed += sum(d / (n + 1) for s in range(n + 1)
                          if P.Overlay(cont, x1 + (x2 - x1) * s / n, y1 + (y2 - y1) * s / n) == 2)
    last = math.hypot(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
    return road / max(drawn, 1), closed, last  # (of the way drawn: a lift's length counts its wait too)


ORGRIMMAR_OUTSIDE = (1310.0, -4388.0)  # (on Durotar's road, outside the front gate)


def test_route_into_orgrimmar_follows_its_streets(capitals_env):
    # From Durotar's road outside the gate to the bank: in at the gate, along the city's own
    # roads (no line straight through its walls; before, it had no roads in there at all)
    lua, ns = capitals_env
    bank = next((x, y) for n, x, y in city_places(ns, 1454) if n == "Orgrimmar Bank")
    r = ns.Router.Route(1, *ORGRIMMAR_OUTSIDE, *bank, lua.table(offroad=False))
    share, closed, last = check_capital_route(ns, 1, r)
    assert share > 0.8 and closed < 5 and last < 20
    assert r.length < 2.2 * math.dist(ORGRIMMAR_OUTSIDE, bank)
    pts, _ = route_pts(r)
    assert min(math.dist(p, (1352.0, -4372.0)) for p in pts) < 25  # (through the gate)


def test_orgrimmar_places_are_reached_on_its_roads(capitals_env):
    # Every service a guard points out, from outside the gate: mostly on the city's roads,
    # the last stretch short, and never a long way through its walls
    lua, ns = capitals_env
    for name, x, y in city_places(ns, 1454):
        r = ns.Router.Route(1, *ORGRIMMAR_OUTSIDE, x, y, lua.table(offroad=False))
        share, closed, last = check_capital_route(ns, 1, r)
        assert share > 0.75 and closed < 40 and last < 45 and r.length < 2500, (name, share, closed, last, r.length)


def test_orgrimmar_flight_master_up_its_tower(capitals_env):
    # The wind rider master is up on a tower, reached by the ramp winding round it: the route
    # climbs it (it isn't a straight line up from the street at its foot)
    lua, ns = capitals_env
    fm = (1677.6, -4315.7)
    r = ns.Router.Route(1, *ORGRIMMAR_OUTSIDE, *fm, lua.table(offroad=False))
    pts, _ = route_pts(r)
    assert min(math.dist(p, (1675.0, -4336.0)) for p in pts) < 8  # (on the ramp round the tower)
    assert math.dist(pts[-2], fm) < 12


def test_orgrimmar_cleft_of_shadow_is_down_under_the_drag(capitals_env):
    # The warlock trainer is down in the Cleft of Shadow, under the Drag: a stop there is on the
    # floor under (its own roads), the player up on the Drag isn't (their height tells)
    lua, ns = capitals_env
    R = ns.Router
    wl = next((x, y) for n, x, y in city_places(ns, 1454) if n == "Orgrimmar Warlock Trainer")
    under = (1788.0, -4388.0)  # (a spot with the Cleft's floor at about -17, the Drag's at 37)
    assert R.CaveDown(1, *under) and R.CaveDown(1, *under, None, -16.0) and not R.CaveDown(1, *under, None, 37.0)
    r = R.Route(1, *ORGRIMMAR_OUTSIDE, *wl, lua.table(offroad=False))
    share, closed, last = check_capital_route(ns, 1, r)
    # (the capitals' roads are their streets now, not every floor's centerline: a last walk over the open
    # floor a few yards longer, never through closed cells)
    assert share > 0.8 and last < 15


IRONFORGE_OUTSIDE = (-5100.0, -741.0)  # (on Dun Morogh's road below the gates)


@pytest.mark.parametrize("name,spot", [("the Great Forge", (-4763.0, -1108.0)), ("the Deeprun Tram", (-4838.0, -1318.0)),
                                       ("the gryphon master", (-4821.8, -1155.4)), ("the Mystic Ward", (-4661.0, -954.0)),
                                       ("the Vault", (-4888.0, -995.0)), ("the Military Ward", (-4976.0, -1208.0))])
def test_route_into_ironforge_follows_its_halls(capitals_env, name, spot):
    # From Dun Morogh's road in at the gates and along the city's halls round the Great Forge
    lua, ns = capitals_env
    r = ns.Router.Route(0, *IRONFORGE_OUTSIDE, *spot, lua.table(offroad=False))
    share, closed, last = check_capital_route(ns, 0, r)
    assert share > 0.85 and closed < 5 and last < 60, (name, share, closed, last)  # (the streets: see above)
    assert r.length < 2.5 * math.dist(IRONFORGE_OUTSIDE, spot), (name, r.length)
    pts, _ = route_pts(r)
    assert min(math.dist(p, (-5030.0, -835.0)) for p in pts) < 20  # (in by the gates)


STORMWIND_OUTSIDE = (-9120.0, 397.0)  # (on Elwynn's road before the bridge to the gate)


@pytest.mark.parametrize("name,spot", [("the Trade District", (-8832.0, 625.0)), ("Cathedral Square", (-8618.0, 776.0)),
                                       ("the gryphon master", (-8832.8, 478.6)), ("the Dwarven District", (-8407.0, 573.0)),
                                       ("Stormwind Keep", (-8438.0, 399.0)), ("the Mage Quarter", (-8947.0, 858.0))])
def test_route_into_stormwind_follows_its_streets(capitals_env, name, spot):
    # In at the gate past the Valley of Heroes, along the city's streets and over its canals'
    # bridges (not straight through its walls and houses)
    lua, ns = capitals_env
    r = ns.Router.Route(0, *STORMWIND_OUTSIDE, *spot, lua.table(offroad=False))
    share, closed, last = check_capital_route(ns, 0, r)
    # (the road drawn in game onto the gate's bridge starts 15 yd past the land's road: their join
    # crosses the bridge's edge cells, 8 yd)
    assert share > 0.78 and closed < 10 and last < 25, (name, share, closed, last)
    assert r.length < 2.5 * math.dist(STORMWIND_OUTSIDE, spot), (name, r.length)
    pts, _ = route_pts(r)
    near = min(_seg_dist(p, q, (-9016.0, 474.0)) for p, q in zip(pts, pts[1:]))
    assert near < 30  # (through the Valley of Heroes: a drawn road runs straight through it)


def _seg_dist(a, b, p):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L2 = vx * vx + vy * vy
    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2)) if L2 > 0 else 0.0
    return math.hypot(a[0] + vx * t - p[0], a[1] + vy * t - p[1])


THUNDER_BLUFF_BELOW = (-1334.0, 176.0)  # (on Mulgore's road at the foot of the west lifts)


def test_route_up_into_thunder_bluff_takes_a_lift(capitals_env):
    # From Mulgore up to the bank: up a lift (the mesas' cliffs are no way up), then along the
    # mesa's roads
    lua, ns = capitals_env
    bank = next((x, y) for n, x, y in city_places(ns, 1456) if n == "Thunder Bluff Bank")
    r = ns.Router.Route(1, *THUNDER_BLUFF_BELOW, *bank, lua.table(offroad=False))
    share, closed, last = check_capital_route(ns, 1, r)
    assert share > 0.85 and closed < 5 and last < 25  # (the streets: see above)
    pts, _ = route_pts(r)
    assert min(math.dist(p, q) for p in pts for q in ((-1286.2, 189.7), (-1308.4, 185.3))) < 12  # (the lift)
    # (asked: as Undercity's, the lift said: "Take the lift up", the route over it drawn as a ride)
    _, kinds = route_pts(r)
    assert ns.Router.KIND_LIFT_UP in kinds
    load(lua, ns, "Turns.lua")
    part = lua.table(pts=r.pts, kinds=r.kinds, cont=1, stop=1)
    ms = ns.Turns.Maneuvers(ns.Turns.Path(lua.table(parts=lua.table(part))))
    assert any(str(ms[i].text) == "Take the lift up" for i in range(1, len(ms) + 1))


def test_capital_stairs_are_said_in_the_directions(capitals_env):
    # (asked) a capital's stairs and ramps between levels (walknet's, written as source 6 with the nodes'
    # heights): Router.StairAt finds them along a route, up or down by the heights, and the directions say
    # "Take the stairs up" there
    lua, ns = capitals_env
    R = ns.Router
    assert R.StairAt(1, 0.0, 0.0, 1.0, 1.0) is None  # (builds Kalimdor's graph; no stairs out there)
    g = R.DebugGraph(1)
    found = None
    for i in range(1, len(g.e) + 1):
        e = g.e[i]
        za, zb = g.nz[e[1]], g.nz[e[2]]
        if e[4] == R.SOURCE_STAIR and za and zb and abs(zb - za) >= 6 and len(e) >= 8:
            found = e
            break
    assert found, "no stairs between levels in Kalimdor's capitals"
    e = found
    pts = [(e[k], e[k + 1]) for k in range(5, len(e) + 1, 2)]
    up = g.nz[e[2]] > g.nz[e[1]]
    (x1, y1), (x2, y2) = pts[0], pts[1]
    assert R.StairAt(1, x1, y1, x2, y2) == (1 if up else -1)
    assert R.StairAt(1, x2, y2, x1, y1) == (-1 if up else 1)
    load(lua, ns, "Turns.lua")
    lo_to_hi = pts if up else pts[::-1]
    lead = [(lo_to_hi[0][0] - 30, lo_to_hi[0][1])]  # (a walk up to their foot first, and on from the top: not arriving)
    (ax, ay), (bx, by) = lo_to_hi[-2], lo_to_hi[-1]
    d = math.hypot(bx - ax, by - ay) or 1
    tail = [(bx + (bx - ax) / d * 60, by + (by - ay) / d * 60)]
    walk = lead + lo_to_hi + tail
    part = lua.table(pts=lua.table(*[v for q in walk for v in q]), kinds=lua.table(*([0] * (len(walk) - 1))), cont=1, stop=1)
    ms = ns.Turns.Maneuvers(ns.Turns.Path(lua.table(parts=lua.table(part))))
    assert any(str(ms[i].kind) == "stairs" and str(ms[i].text) == "Take the stairs up" for i in range(1, len(ms) + 1))

def test_thunder_bluff_places_are_reached_on_its_roads(capitals_env):
    # Every service a guard points out, from the lifts' foot: on the mesas' roads and their
    # bridges, never a long way through the chasms between the mesas or their tents
    lua, ns = capitals_env
    for name, x, y in city_places(ns, 1456):
        r = ns.Router.Route(1, *THUNDER_BLUFF_BELOW, x, y, lua.table(offroad=False))
        share, closed, last = check_capital_route(ns, 1, r)
        assert share > 0.75 and closed < 10 and last < 25 and r.length < 1200, (name, share, closed, last, r.length)


DARNASSUS_OUTSIDE = (9986.0, 1864.0)  # (on Teldrassil's road below the south gate)


@pytest.mark.parametrize("name,spot", [("Craftsmen's Terrace", (10143.0, 2317.0)), ("the Temple of the Moon", (9622.0, 2522.0)),
                                       ("Tradesmen's Terrace", (9812.0, 2252.0)), ("Warrior's Terrace", (9950.0, 2316.7))])
def test_route_into_darnassus_follows_its_paths(capitals_env, name, spot):
    lua, ns = capitals_env
    r = ns.Router.Route(1, *DARNASSUS_OUTSIDE, *spot, lua.table(offroad=False))
    share, closed, last = check_capital_route(ns, 1, r)
    assert share > 0.85 and closed < 5 and last < 25, (name, share, closed, last)
    assert r.length < 2.5 * math.dist(DARNASSUS_OUTSIDE, spot), (name, r.length)


def test_capitals_leave_routes_elsewhere_unchanged(env):
    # Trips nowhere near a capital route the same with the capitals loaded.
    trips = [(0, (2250.0, 250.0), (1841.0, 236.0)), (1, (1100.0, -4400.0), (850.0, -4450.0)),
             (1, (-2350.0, -350.0), (-2100.0, -500.0)), (1, (-84.0, -4743.0), (-62.0, -4229.0)),
             (0, (-9460.0, 60.0), (-9100.0, -200.0))]
    lua, ns = env
    capitals_world(lua, ns)
    got = [route_pts(ns.Router.Route(c, *a, *b, lua.table(offroad=o))) for c, a, b in trips for o in (False, True)]
    lua2 = lupa.LuaRuntime()
    lua2.execute(PRELUDE)
    ns2 = lua2.table()
    ns2.IsSecret = lua2.eval("function(v) return false end")
    load(lua2, ns2, "Geo.lua")
    capitals_world(lua2, ns2, capitals=False)
    want = [route_pts(ns2.Router.Route(c, *a, *b, lua2.table(offroad=o))) for c, a, b in trips for o in (False, True)]
    assert got == want


def test_add_and_remove_stops_on_an_active_route(nav_env):
    lua, ns = nav_env
    N = ns.Nav
    N.SetStops(stops(lua, (-600.0, -4180.0), (-440.0, -4700.0)))  # square, star
    assert N.AddStop(lua.table(x=-800.0, y=-4400.0, cont=1))
    assert [N.stops[i].icon for i in (1, 2, 3)] == [6, 1, 4]  # appended with the next free marker
    r = N.Route(-500.0, -4500.0, 1)
    last = N.EachSegment(r, 1, lambda *a: None)
    assert (last[0], last[1]) == pytest.approx((-800.0, -4400.0), abs=0.5)  # route now ends there
    N.RemoveStop(2)  # drop the star
    assert [N.stops[i].icon for i in (1, 2)] == [6, 4]
    assert N.route is None  # rerouted on the next request
    r = N.Route(-500.0, -4500.0, 1)
    seen = set()
    N.EachSegment(r, 1, lambda x1, y1, x2, y2, kind, stop, *rest: seen.add(stop))
    assert seen == {1, 2}


def test_busy_search_queue_never_drops_legs_between_stops(offroad):
    lua, ns = offroad
    R = ns.Router
    R.SYNC_WALKS = False
    moving = lua.table(offroad=True, transient=True)  # walks from the player's position
    fixed = lua.table(offroad=True)  # a leg between two stops
    # short trips across the wall need a walk around it (queued, not known yet)
    R.Route(1, 0.0, 280.0, 600.0, 280.0, moving)
    before = R.Route(1, 0.0, 300.0, 600.0, 300.0, fixed)
    for k in range(20):  # the player keeps moving: many searches from new spots
        R.Route(1, 0.0, 320.0 + 3 * k, 600.0, 320.0, moving)
    lua.eval("function(R) while R.HasWork() do R.Pump(math.huge, function() return 0 end) end end")(R)
    after = R.Route(1, 0.0, 300.0, 600.0, 300.0, fixed)
    assert not R.HasWork()  # its walk finished (it wasn't dropped): nothing re-queued
    assert before.pending and not after.pending  # and the route uses it: through the pass
    pts, kinds = route_pts(after)
    assert any(abs(y) < 60 for x, y in pts if 250 < x < 350)


def test_following_the_route_trims_instead_of_recalculating(nav_env):
    lua, ns = nav_env
    N = ns.Nav
    lua.execute("now = 0; GetTime = function() return now end")
    N.SetStops(stops(lua, (-600.0, -4180.0), (-440.0, -4700.0)))
    r = N.Route(-800.0, -4400.0, 1)
    base_len, base_total = r.walkYards, r.totalYards
    pts = [r.pts[i] for i in range(1, len(r.pts) + 1)]
    pts = list(zip(pts[0::2], pts[1::2]))
    # walk a few points along the first part of the route
    k = min(4, len(pts) - 2)
    x, y = pts[k]
    walked = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i in range(k))
    lua.execute("now = 5")
    r2 = N.Route(x + 3.0, y, 1)  # a few yards beside the line
    same = lua.eval("rawequal")
    assert same(r2, r)  # same route object: followed, not recalculated
    assert r2.walkYards == pytest.approx(base_len - walked, abs=4)
    assert r2.totalYards == pytest.approx(base_total - walked, abs=4)
    assert (r2.pts[1], r2.pts[2]) == pytest.approx((x, y), abs=4)  # drawn from the player on
    # far off the route: recalculated
    lua.execute("now = 10")
    far = (-1400.0, -3600.0)  # nowhere near this route
    assert min(math.hypot(px - far[0], py - far[1]) for px, py in pts) > 200
    r3 = N.Route(far[0], far[1], 1)
    assert not same(r3, r)


def test_the_walked_part_is_trimmed_off_between_recalculations(nav_env):
    lua, ns = nav_env
    N = ns.Nav
    lua.execute("now = 0; GetTime = function() return now end")
    N.SetStops(stops(lua, (-600.0, -4180.0), (-440.0, -4700.0)))
    r = N.Route(-800.0, -4400.0, 1)
    base = r.walkYards
    same = lua.eval("rawequal")
    # a few yards along it, well before a recalculation is due (under 2 s, under 15 yd moved)
    pts = [r.pts[i] for i in range(1, len(r.pts) + 1)]
    (ax, ay), (bx, by) = (pts[0], pts[1]), (pts[2], pts[3])
    seg = math.hypot(bx - ax, by - ay)
    step = min(6.0, seg * 0.8)
    x, y = ax + (bx - ax) / seg * step, ay + (by - ay) / seg * step
    lua.execute("now = 0.5")
    r2 = N.Route(x, y, 1)
    assert same(r2, r)  # not recalculated
    assert (r2.pts[1], r2.pts[2]) == pytest.approx((x, y), abs=0.5)  # drawn from the player on
    assert r2.walkYards == pytest.approx(base - step, abs=0.5)
    # under TRIM_MOVED_YD further: left as it is
    lua.execute("now = 0.6")
    r3 = N.Route(x + 0.5, y, 1)
    assert (r3.pts[1], r3.pts[2]) == pytest.approx((x, y), abs=0.01)


# ---- Turn-by-turn (Turns.lua) --------------------------------------------------------------

@pytest.fixture
def turns(env):
    lua, ns = env
    load(lua, ns, "Turns.lua")
    return lua, ns


def path_of(lua, ns, pts, kinds, stop=1, extra_parts=(), legs=None):
    flat = [v for p in pts for v in p]
    parts = [lua.table(cont=1, pts=lua.table(*flat), kinds=lua.table(*kinds), stop=stop)] + list(extra_parts)
    route = lua.table(parts=lua.table(*parts), legs=legs or lua.table(lua.table(walk=True)))
    return ns.Turns.Path(route)


def maneuvers(lua, ns, path, label="stop 1"):
    ms = ns.Turns.Maneuvers(path, label)
    return [(ms[i].kind, round(ms[i].dist), ms[i].text) for i in range(1, len(ms) + 1)], ms


def test_turn_left_at_a_corner(turns):
    lua, ns = turns
    # east 500 yd (east = -Y), then north 500 yd (+X): a left turn, seen from above
    p = path_of(lua, ns, [(0, 0), (0, -250), (0, -500), (250, -500), (500, -500)], [0, 0, 0, 0])
    got, _ = maneuvers(lua, ns, p)
    assert got == [("turn", 500, "Turn left"), ("arrive", 1000, "Arrive at stop 1")]


def _stairs_in(lua, ns, x0, x1, y0, y1):
    # (Router.StairAt as a stand-in: a stretch whose middle is in the box is stairs, up going east or north)
    ns.Router = lua.eval(f"""{{ StairAt = function(cont, ax, ay, bx, by)
      local mx, my = (ax + bx) / 2, (ay + by) / 2
      if mx < {x0} or mx > {x1} or my < {y0} or my > {y1} then return nil end
      return (by < ay or bx > ax) and 1 or -1
    end }}""")


def test_stairs_then_a_turn_are_said_together(turns):
    # (asked) "Stairs up in 10 yd, then turn left": stairs on the way (a capital's, Router.StairAt) said
    # where they start, with a turn just after them
    lua, ns = turns
    _stairs_in(lua, ns, -1, 1, -121, -99)
    p = path_of(lua, ns, [(0, 0), (0, -100), (0, -120), (0, -130), (250, -130), (500, -130)], [0, 0, 0, 0, 0])
    got, ms = maneuvers(lua, ns, p)
    assert got == [("stairs", 100, "Take the stairs up"), ("turn", 130, "Turn left"), ("arrive", 630, "Arrive at stop 1")]
    fmt = lua.eval("function(d) return string.format('%d yd', d) end")
    assert ns.Turns.NowText(ms[1], fmt) == "Stairs up in 100 yd, then turn left"
    ms[1].dist = 2
    assert ns.Turns.NowText(ms[1], fmt) == "Take the stairs up, then turn left"
    # (the other way: down)
    p = path_of(lua, ns, [(500, -130), (250, -130), (0, -130), (0, -120), (0, -100), (0, 0)], [0, 0, 0, 0, 0])
    got, _ = maneuvers(lua, ns, p)
    assert ("stairs", 510, "Take the stairs down") in got


def test_turns_on_the_stairs_are_not_said(turns):
    # (a spiral's bends, or a landing's corner: "Take the stairs up" covers them)
    lua, ns = turns
    _stairs_in(lua, ns, -1, 41, -141, -99)
    p = path_of(lua, ns, [(0, 0), (0, -100), (0, -140), (40, -140), (500, -140)], [0, 0, 0, 0])
    got, ms = maneuvers(lua, ns, p)
    assert got == [("stairs", 100, "Take the stairs up"), ("arrive", 640, "Arrive at stop 1")]
    assert not ms[1].after

def test_stairs_by_the_routes_heights_on_a_level_of_floors(turns):
    # (Undercity, a dungeon: the route's points have heights; a steep stretch rising 4 yd or more is stairs,
    # a bump isn't)
    lua, ns = turns
    pts = [(0, 0), (0, -100), (0, -110), (0, -150), (0, -170), (0, -300)]
    zs = [0, 0, 2.5, 2.5, 12.5, 12.5]
    part = lua.table(cont=20036, pts=lua.table(*[v for q in pts for v in q]), kinds=lua.table(0, 0, 0, 0, 0),
                     stop=1, zs=lua.table(*zs))
    p = ns.Turns.Path(lua.table(parts=lua.table(part), legs=lua.table(lua.table(walk=True))))
    got, _ = maneuvers(lua, ns, p)
    assert got == [("stairs", 150, "Take the stairs up"), ("arrive", 300, "Arrive at stop 1")]

def test_the_next_turn_reads_what_to_do_now_first(turns):
    # (asked) "Continue straight, then slight right in 13 yd": what to do now, then the next maneuver;
    # at the turn, "Slight right now"
    lua, ns = turns
    T = ns.Turns
    yd = lua.eval("function(v) return string.format('%d yd', v) end")
    m = lambda kind, dist, text: lua.table(kind=kind, dist=dist, text=text)
    assert T.NowText(m("turn", 13, "Slight right"), yd) == "Continue straight, then slight right in 13 yd"
    assert T.NowText(m("turn", 13, "Slight right"), yd, True) == "Straight, then slight right in 13 yd"
    assert T.NowText(m("turn", 5, "Turn left onto the road"), yd) == "Turn left onto the road now"
    assert T.NowText(m("arrive", 52, "Arrive at Stormwind Mage Trainer"), yd) == \
        "Continue straight, then arrive at Stormwind Mage Trainer in 52 yd"
    assert T.NowText(m("arrive", 4, "Arrive at Stormwind Mage Trainer"), yd) == "Arrive at Stormwind Mage Trainer"
    assert T.NowText(m("drop", 20, "Jump down here"), yd) == "Continue straight, then jump down in 20 yd"


def test_turn_words_and_curves(turns):
    lua, ns = turns
    T = ns.Turns
    assert [T.TurnText(a) for a in (40, -80, 130, -170)] == ["Slight left", "Turn right", "Sharp left", "Make a U-turn"]
    # a gentle curve made of many small bends is one turn, not several
    import math as m
    arc = [(0.0, -float(i * 20)) for i in range(10)]  # east 180 yd
    cx, cy, r = 60.0, -180.0, 60.0  # quarter circle bending left (towards north)
    arc += [(cx - r * m.cos(t), cy - r * m.sin(t)) for t in [k * m.pi / 20 for k in range(1, 11)]]
    arc += [(arc[-1][0] + 20 * k, arc[-1][1]) for k in range(1, 10)]
    p = path_of(lua, ns, arc, [0] * (len(arc) - 1))
    got, _ = maneuvers(lua, ns, p)
    assert [g[0] for g in got] == ["turn", "arrive"] and got[0][2] == "Turn left"


def test_joining_and_leaving_the_road(turns):
    lua, ns = turns
    # off-road east, then along a road north (join + left turn = one instruction), then off it
    p = path_of(lua, ns, [(0, 0), (0, -200), (300, -200), (300, -400)], [1, 0, 1])
    got, _ = maneuvers(lua, ns, p)
    assert got[0] == ("turn", 200, "Turn left onto the road")
    assert got[1][2].endswith("off the road")  # turning east again, off the road


def test_board_a_transport_and_toward_a_place(turns):
    lua, ns = turns
    ns.Pois = lua.eval("{ [1] = { {3, 350, -500, 'Razor Hill', 1} } }")
    ride = lua.table(0, 1.0, 2.0, 1, 3.0, 4.0, 200, "zeppelin", "Brill, Tirisfal Glades", "Jaggedswine Farm, Durotar")
    transport = lua.table(cont=1, pts=lua.table(500.0, -500.0, 900.0, -900.0), kinds=lua.table(2), stop=1)
    p = path_of(lua, ns, [(0, 0), (0, -250), (0, -500), (250, -500), (500, -500)], [0, 0, 0, 0],
                extra_parts=[transport], legs=lua.table(lua.table(walk=True), lua.table(ride=ride, **{"from": 1})))
    got, ms = maneuvers(lua, ns, p)
    assert ms[1].toward == "Razor Hill"  # the named place ahead after the turn
    assert got[-1] == ("board", 1000, "Board the zeppelin to Jaggedswine Farm, Durotar")


def test_arrow_angle(turns):
    lua, ns = turns
    T = ns.Turns
    # facing north (0), target to the west (+Y): a quarter turn to the left
    assert T.RelativeAngle(0, 0, 0, 0, 100) == pytest.approx(math.pi / 2)
    # facing west, target north: a quarter turn to the right
    assert T.RelativeAngle(0, 0, math.pi / 2, 100, 0) == pytest.approx(-math.pi / 2)
    assert T.Compass(-1, 1) == "south-west"


def test_road_bends_are_only_turns_at_junctions(turns):
    lua, ns = turns
    load(lua, ns, "Router.lua")
    # east 500 yd along a road, then 45 degrees to the left (north-east) for 400 yd
    import math as m
    bend = (0.0, -500.0)
    far = (400 * m.cos(m.radians(45)), -500 - 400 * m.sin(m.radians(45)))
    pts = [(0.0, 0.0), (0.0, -250.0), bend, ((bend[0] + far[0]) / 2, (bend[1] + far[1]) / 2), far]
    edges = "{1,2,500,0, 0,0, 0,-250, 0,-500}, {2,3,400,0, 0,-500, %f,%f}" % far
    lua.execute("ns_ = ...", ns)
    set_roads = lua.eval("function(ns, src) ns.Roads = assert(load('return ' .. src))() end")
    # the road just bends there: a plain curve, not announced
    set_roads(ns, "{ [1] = { n = { 0,0, 0,-500, %f,%f }, e = { %s } } }" % (far[0], far[1], edges))
    ns.Router.Reset()
    got, _ = maneuvers(lua, ns, path_of(lua, ns, pts, [0, 0, 0, 0]))
    assert [g[0] for g in got] == ["arrive"]
    # a third road meets there: a junction, so the bend is a turn
    set_roads(ns, "{ [1] = { n = { 0,0, 0,-500, %f,%f, -300,-500 }, e = { %s, {2,4,300,0, 0,-500, -300,-500} } } }"
              % (far[0], far[1], edges))
    ns.Router.Reset()
    got, _ = maneuvers(lua, ns, path_of(lua, ns, pts, [0, 0, 0, 0]))
    assert got[0][:2] == ("turn", 500) and got[0][2] == "Slight left"


# ---- Waypoint import (Import.lua) ---------------------------------------------------------

@pytest.fixture
def importer(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Import.lua")
    return lua, ns


def test_parse_tomtom_way_lines(importer):
    lua, ns = importer
    I = ns.Import
    text = """/way Elwynn Forest 43.2 65.1 First Stop (Vendor)
/way Elwynn Forest 52.0 40.5 Second Stop (Quest NPC)
/way elwynn 60.1, 22.8 Third Stop (Cave Entrance)
/way Elwynn Forest 24.5 80.2 Final Destination
/way Elwin Forest 10 10 Typo
/way 50 50
"""
    stops, errors = I.Parse(text, 1411)  # current zone: Durotar
    got = [stops[i] for i in range(1, len(stops) + 1)]
    assert [s.name for s in got] == ["First Stop (Vendor)", "Second Stop (Quest NPC)", "Third Stop (Cave Entrance)",
                                     "Final Destination", "Durotar 50.0, 50.0"]
    assert list(errors.values()) == ["Line 5: unknown zone 'Elwin Forest'"]
    elwynn = ns.Maps[I.FindMap("Elwynn Forest")]
    b = elwynn.bounds
    first = got[0]
    assert first.cont == 0
    assert first.x == pytest.approx(b[3] - 0.651 * (b[3] - b[1]))  # 65.1 down the map
    assert first.y == pytest.approx(b[4] - 0.432 * (b[4] - b[2]))  # 43.2 across
    assert got[4].cont == 1  # "/way 50 50": in the current zone (Durotar)


def test_import_sets_the_route(importer):
    lua, ns = importer
    I = ns.Import
    stops, _ = I.Parse("/way Durotar 50 50 A\n/way Durotar 52 44 B", 1411)
    assert I.Apply(stops, False) == 2
    assert [ns.Nav.stops[i].name for i in (1, 2)] == ["A", "B"]
    assert [ns.Nav.stops[i].icon for i in (1, 2)] == [6, 1]  # square, star
    more, _ = I.Parse("/way #1411 40 40 C", 1411)
    assert I.Apply(more, True) == 3 and ns.Nav.stops[3].name == "C" and ns.Nav.stops[3].icon == 4


def test_pasted_way_lines_run_together(importer):
    lua, ns = importer
    # several lines pasted into the chat box can arrive on one line
    text = ("/way Elwynn Forest 43.2 65.1 First Stop (Vendor) /way Elwynn Forest 52.0 40.5 Second Stop "
            "/WAY Elwynn Forest 60.1 22.8 Third")
    stops, errors = ns.Import.ParseWays(text, 1411)
    assert [stops[i].name for i in range(1, len(stops) + 1)] == ["First Stop (Vendor)", "Second Stop", "Third"]
    assert len(errors) == 0
    stops, _ = ns.Import.ParseWays("/way Durotar 50 50 A\n/way Durotar 52 44 B", 1411)
    assert len(stops) == 2


# ---- Recorded roads used right away -----------------------------------------------------------

def test_recorded_missing_road_is_routed_on(router):
    lua, ns = router
    # a track from the middle of the first leg (0,-500) north to (600,-500)
    ns.db = lua.eval("{ tracks = { { op = 'add', continent = 1, pts = { 5,-500, 200,-500, 400,-500, 600,-500 } } } }")
    ns.Router.Reset()
    r = ns.Router.Route(1, 0.0, 30.0, 620.0, -500.0)
    pts, kinds = route_pts(r)
    assert r.road > 1000  # along the first leg to the junction, then up the recorded road
    assert any(abs(x - 400) < 1 and abs(y + 500) < 1 for x, y in pts)  # on the track
    assert r.length < 30 + 500 + 600 + 60  # not around via B and C
    # the shipped data isn't changed
    assert len(ns.Roads[1].e) == 2


def test_recorded_false_road_is_removed(router):
    lua, ns = router
    # drive along the second leg B -> C and mark it false
    ns.db = lua.eval("{ tracks = { { op = 'remove', continent = 1, pts = { 0,-1000, 500,-1000, 1000,-1000 } } } }")
    ns.Router.Reset()
    r = ns.Router.Route(1, 0.0, 30.0, 1030.0, -1000.0)
    assert r.road < 1001  # only the first leg is road now; the rest goes off-road


def test_erasing_part_of_a_road_cuts_it(router):
    lua, ns = router
    # a stroke across the middle of the second leg B -> C: that stretch goes, both sides stay
    ns.db = lua.eval("{ tracks = { { op = 'remove', drawn = true, continent = 1, pts = { 500,-1100, 500,-900 } } } }")
    ns.Router.Reset()
    edges = ns.Router.Edges(1)[0]
    assert len(edges) == 3
    for e in edges.values():
        for i in range(5, len(e), 2):
            assert not (abs(e[i] - 500) < 10 and abs(e[i + 1] + 1000) < 10)


def drawn_edges(ns):
    return [e for e in ns.Router.Edges(1)[0].values() if e[4] == ns.Router.SOURCE_RECORDED]


def test_drawn_road_along_an_existing_one_replaces_that_stretch(router):
    lua, ns = router
    # drawn along the second leg (5 yd off it) from x 200 to 500, then away north to y -1300
    ns.db = lua.eval("{ tracks = { { op = 'add', drawn = true, continent = 1, time = 1, "
                     "pts = { 200,-1005, 350,-1004, 500,-1006, 500,-1150, 500,-1300 } } } }")
    ns.Router.Reset()
    edges = list(ns.Router.Edges(1)[0].values())
    # one road there, the drawn one: the leg's stretch beside it is gone
    for e in edges:
        if e[4] != ns.Router.SOURCE_RECORDED:
            assert not any(220 < e[i] < 480 for i in range(5, len(e), 2))
    # and the leg's ends join it: along the leg, onto the drawn road and up it, then on to C
    r = ns.Router.Route(1, 0.0, 30.0, 500.0, -1310.0, lua.table(offroad=False))
    assert r.road > 1000 + 300 + 250 and r.length < 30 + 1000 + 520 + 320 + 40
    r = ns.Router.Route(1, 0.0, 30.0, 1030.0, -1000.0, lua.table(offroad=False))
    assert r.length < 30 + 2000 + 30 + 40


def test_drawn_road_that_stops_short_joins_the_road(router):
    lua, ns = router
    # ends 18 yd from the first leg (x = 0): joined to it anyway
    ns.db = lua.eval("{ tracks = { { op = 'add', drawn = true, continent = 1, time = 1, pts = { 300,-500, 150,-500, 18,-500 } } } }")
    ns.Router.Reset()
    e = drawn_edges(ns)[0]
    assert (e[len(e) - 1], e[len(e)]) == pytest.approx((0, -500), abs=0.01)
    r = ns.Router.Route(1, 0.0, 30.0, 310.0, -500.0, lua.table(offroad=False))
    assert r.road > 700  # down the first leg, then along the drawn road


def test_drawing_the_same_road_twice_keeps_one(router):
    lua, ns = router
    ns.db = lua.eval("""{ tracks = {
      { op = 'add', drawn = true, continent = 1, time = 1, pts = { 300,-500, 150,-500, 5,-500 } },
      { op = 'add', drawn = true, continent = 1, time = 2, pts = { 305,-506, 150,-494, 2,-503 } } } }""")
    ns.Router.Reset()
    assert len(drawn_edges(ns)) == 1


def test_drawn_roads_the_data_has_are_left_out_and_dropped(router):
    lua, ns = router
    ns.db = lua.eval("{ tracks = { { op = 'add', drawn = true, continent = 1, time = 7, pts = { 300,-500, 150,-500, 5,-500 } } } }")
    ns.RoadTracksIn = lua.eval("{ [7] = true }")
    ns.Router.Reset()
    assert drawn_edges(ns) == []
    ns.Print = lua.eval("function() end")
    load(lua, ns, "Record.lua")
    ns.Record.Prune()
    assert len(ns.db.tracks) == 0


def test_shipped_overrides_and_drawn_roads_draw_as_roads(router):
    lua, ns = router
    ns.Roads[1].e[2][4] = 2  # (an override in the data)
    ns.db = lua.eval("{ tracks = { { op = 'add', continent = 1, time = 1, pts = { 300,-500, 150,-500, 5,-500 } } } }")
    ns.Router.Reset()
    segs = ns.GPS.LayoutRoads(0.0, -500.0, 1, 0, 3000.0, 130.0)
    colors = {segs[i][5] for i in range(1, len(segs) + 1)}
    assert colors == {0}


def test_recorded_roads_keep_the_ruins_roads_and_the_citys(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua")
    ns.db = lua.eval("""{ tracks = {
      { op = 'add', drawn = true, continent = 0, pts = { 1900, 236, 1880, 236, 1860, 236 } },
      { op = 'remove', drawn = true, continent = 10001, pts = { 1400, 50, 1402, 52 } } } }""")
    R = ns.Router
    R.Reset()
    # the ruins' walked way from the gate is still a road
    found = any(abs(e[5] - 1882) < 2 and abs(e[6] - 236) < 2 or abs(e[len(e) - 1] - 1882) < 2 and abs(e[len(e)] - 236) < 2
                for e in R.Edges(0)[0].values())
    assert found
    # the city's routes still work with a record on its level (its roads on floors over floors)
    r = R.Route(10001, 1590.6, 204.0, 1658.9, 275.8, lua.table(offroad=False))
    assert len(r.pts) > 4 and r.zs


# ---- Opt-in feedback (Feedback.lua) ------------------------------------------------------------

def test_faster_trip_is_kept_only_when_opted_in(nav_env):
    lua, ns = nav_env
    lua.execute("""
      now = 0; GetTime = function() return now end; time = function() return 1790000000 end
      GetBuildInfo = function() return "1.60.1", "70009" end
      pos = { 0, 0, 1 }
    """)
    ns.settings = lua.eval("{ gps = { shareTrips = false, offroad = false } }")
    load(lua, ns, "Feedback.lua")
    F = ns.Feedback
    ns.Geo.PlayerWorld = lua.eval("function() return pos[1], pos[2], pos[3] end")
    # the once-a-second ticker: captured, then called by hand
    lua.globals().C_Timer = lua.eval("{ NewTicker = function(_, fn) TICK = fn; return {} end }")
    F.Init()
    TICK = lua.globals().TICK
    ns.Nav.SetDestination(-600.0, -4180.0, 1, "Target")
    lua.execute("pos = { -800, -4400, 1 }")
    ns.Nav.Route(-800.0, -4400.0, 1)
    def walk_there(seconds):
        for k in range(11):
            lua.execute(f"now = {seconds * k / 10}; pos = {{ {-800 + 20 * k}, {-4400 + 22 * k}, 1 }}")
            TICK()
        F.Arrived(ns.Nav.dest)
    walk_there(30)  # way faster than the estimate, but sharing is off
    assert F.Counts() == (0, 0)
    ns.settings.gps.shareTrips = True
    ns.Nav.SetDestination(-600.0, -4180.0, 1, "Target")
    ns.Nav.Route(-800.0, -4400.0, 1)
    walk_there(30)
    roads, trips = F.Counts()
    assert trips == 1
    t = ns.db.feedback.trips[1]
    assert t.actual == 30 and t.estimate > 30 / 0.85 and len(t.pts) >= 20
    # a trip that took as long as estimated isn't kept
    ns.Nav.SetDestination(-600.0, -4180.0, 1, "Target")
    ns.Nav.Route(-800.0, -4400.0, 1)
    walk_there(10000)
    assert F.Counts() == (0, 1)


def test_recorded_road_shows_in_the_road_overlay_right_away(router):
    lua, ns = router
    ns.db = lua.eval("{ tracks = {} }")
    ns.Router.Reset()
    before = ns.GPS.LayoutRoads(0.0, -500.0, 1, 0, 1000.0, 130.0)
    # record a road, then the recording is saved (Record.Changed resets the router)
    lua.eval("function(db) db.tracks[1] = { op = 'add', continent = 1, pts = { 5,-500, 200,-500, 400,-500, 600,-500 } } end")(ns.db)
    ns.Router.Reset()
    after = ns.GPS.LayoutRoads(0.0, -500.0, 1, 0, 1000.0, 130.0)
    colors = [after[i][5] for i in range(1, len(after) + 1)]
    assert len(after) > len(before)
    assert set(colors) == {0}  # drawn roads are roads like any


def test_poi_double_click_adds_a_stop_to_the_route(nav_env):
    lua, ns = nav_env
    ns.settings = lua.eval("{ gps = { fastestOrder = false } }")
    ns.Geo.PlayerWorld = lua.eval("function() return -800.0, -4400.0, 1 end")
    ns.Nav.SetStops(stops(lua, (-600.0, -4180.0), (-440.0, -4700.0)))
    assert ns.GPS.AddStopAt(-300.0, -4600.0, "Razor Hill")
    assert len(ns.Nav.stops) == 3 and ns.Nav.stops[3].name == "Razor Hill"
    assert ns.Nav.stops[3].icon not in (ns.Nav.stops[1].icon, ns.Nav.stops[2].icon)
    # and further stops can still be added after it
    assert ns.GPS.AddStopAt(-350.0, -4500.0)
    assert len(ns.Nav.stops) == 4



def test_poi_double_click_waits_for_confirm_route(nav_env):
    lua, ns = nav_env
    ns.settings = lua.eval("{ gps = { fastestOrder = false, zoom = 400 } }")
    ns.Geo.PlayerWorld = lua.eval("function() return -800.0, -4400.0, 1 end")
    ns.Nav.Clear()
    assert ns.GPS.AddStopAt(-300.0, -4600.0, "Razor Hill")
    assert len(ns.Nav.stops) == 0  # placed, not routed yet
    ns.GPS.ConfirmRoute()
    assert len(ns.Nav.stops) == 1 and ns.Nav.dest.name == "Razor Hill"


def test_export_route_as_way_lines_round_trips(importer):
    lua, ns = importer
    I = ns.Import
    stops_in, _ = I.Parse("/way Durotar 52.0 41.0 Razor Hill\n/way Elwynn Forest 43.2 65.1 Goldshire-ish", None)
    text, skipped = I.ExportText(stops_in)
    assert skipped == 0
    lines = text.split("\n")
    assert lines[0].startswith("/way Durotar 52.0 41.0") and lines[0].endswith("Razor Hill")
    assert lines[1].startswith("/way Elwynn Forest 43.2 65.1")
    back, errors = I.Parse(text, None)
    assert len(list(errors.values())) == 0 and len(back) == 2
    for i in (1, 2):
        a, b = stops_in[i], back[i]
        assert (a.x, a.y) == pytest.approx((b.x, b.y), abs=5)  # rounded to 0.1% of a zone: a few yards
        assert a.cont == b.cont and a.name == b.name


def test_export_a_stop_down_in_undercity(importer):
    # (reported: "No route to copy") a stop on the city's level is written on its map
    lua, ns = importer
    I = ns.Import
    ns.CityLevels = lua.eval('{ [10001] = { base = 0, name = "Undercity", map = 1458 } }')
    bank = lua.eval('{ { x = 1595.6, y = 232.5, cont = 10001, name = "Undercity Bank" } }')
    text, skipped = I.ExportText(bank)
    assert skipped == 0 and text.startswith("/way Undercity ") and text.endswith("Undercity Bank")


def test_share_route_in_game_messages(importer):
    lua, ns = importer
    I = ns.Import
    stops_in, _ = I.Parse("/way Durotar 52.0 41.0 Razor Hill\n/way Durotar 45.0 10.0", None)
    msgs = I.ShareMessages(stops_in, "ab12")
    assert len(msgs) == 2 and all(len(msgs[i]) < 255 for i in (1, 2))
    # arrives out of order; a broken message and someone else's are ignored
    assert I.Receive("garbage", "Friend", 0) is None
    assert I.Receive(msgs[2], "Friend", 0) is None
    assert I.Receive("1\tab12\t1\t2\t99\t0\t0\tbad continent", "Friend", 1) is None
    got = I.Receive(msgs[1], "Friend", 1)
    assert got is not None and len(got) == 2
    assert got[1].name == "Razor Hill" and got[2].name == stops_in[2].name
    assert abs(got[1].x - stops_in[1].x) < 0.1 and got[1].cont == stops_in[1].cont
    # a stop from long ago doesn't complete a new route
    assert I.Receive(msgs[2], "Other", 0) is None
    assert I.Receive(msgs[1], "Other", 100) is None


def test_route_across_pieces_of_the_road_network_uses_roads(nav_env):
    # Durotar's roads and the ones near this Kalimdor spot aren't connected in the data;
    # the route still follows roads, joining the pieces across the gaps
    lua, ns = nav_env
    r = ns.Router.Route(1, 1318.1, -4658.0, 5250.0, -2400.0, lua.eval("{}"))
    assert r.road > 0.6 * r.length


def test_fade_while_moving_target(env):
    lua, ns = env
    st = lua.eval("{ fadeMoving = true, movingAlpha = 0.4 }")
    T = ns.GPS.FadeTarget
    assert T(st, True, False, 1.0) == pytest.approx(0.4)
    assert T(st, True, False, 0.8) == pytest.approx(0.5)  # a share of the map's own opacity
    assert T(st, False, False, 1.0) == 1  # standing still
    assert T(st, True, True, 1.0) == 1  # pointing at the map
    assert T(st, True, False, 0.3) == 1  # already fainter than the moving opacity
    st.fadeMoving = False
    assert T(st, True, False, 1.0) == 1


def test_keep_current_route_when_recalculation_is_longer(nav_env):
    lua, ns = nav_env
    K = ns.Nav.KeepOld
    old = lua.eval("{ totalYards = 1000, totalRide = 0 }")
    longer = lua.eval("{ totalYards = 1400, totalRide = 0, pending = true }")
    assert K(old, longer, 7.0, 0)  # provisional and longer: keep the current route
    longer.pending = False
    assert K(old, longer, 7.0, 0)  # final but longer: keep it for a while...
    old.keptSince = 0
    assert not K(old, longer, 7.0, 25)  # ...then take the new one
    similar = lua.eval("{ totalYards = 1050, totalRide = 0 }")
    assert not K(old, similar, 7.0, 0)  # about as long: just take it
    shorter = lua.eval("{ totalYards = 800, totalRide = 0 }")
    assert not K(old, shorter, 7.0, 0)
    # rides count at walking speed
    ride = lua.eval("{ totalYards = 600, totalRide = 200, pending = true }")
    assert K(old, ride, 7.0, 0)


def test_a_provisional_straight_line_never_stays_over_the_roads(nav_env):
    # (reported) standing still a minute, the route became a straight line over the hills: each
    # refresh's terrain search gave a provisional straight line (shorter), and when the roads
    # came back worked out they were "clearly longer", so the straight line was kept
    lua, ns = nav_env
    K = ns.Nav.KeepOld
    straight = lua.eval("{ totalYards = 633, totalRide = 0, pending = true }")
    roads = lua.eval("{ totalYards = 1409, totalRide = 0 }")
    assert not K(straight, roads, 7.0, 0)  # worked out: over a provisional one at once
    assert K(roads, straight, 7.0, 0)  # and a provisional one doesn't replace it meanwhile


def test_reroute_keeps_route_until_player_leaves_it(nav_env):
    lua, ns = nav_env
    lua.globals().AGPS_ROUTER = ns.Router
    lua.execute("""
      AGPS_T = 0
      GetTime = function() return AGPS_T end
      AGPS_LONG = false
      AGPS_ROUTER.Route = function(cont, sx, sy, tx, ty)
        if AGPS_LONG then
          local mx, my = (sx + tx) / 2 + 400, (sy + ty) / 2 -- off to the side
          local d = math.sqrt((mx - sx) ^ 2 + (my - sy) ^ 2) + math.sqrt((tx - mx) ^ 2 + (ty - my) ^ 2)
          return { pts = { sx, sy, mx, my, tx, ty }, kinds = { 0, 0 }, length = d, road = d, pending = true }
        end
        local d = math.sqrt((tx - sx) ^ 2 + (ty - sy) ^ 2)
        return { pts = { sx, sy, tx, ty }, kinds = { 0 }, length = d, road = d }
      end
    """)
    ns.Nav.SetDestination(0.0, 1000.0, 1, "There")
    r1 = ns.Nav.Route(0.0, 0.0, 1)
    assert r1.totalYards == pytest.approx(1000, abs=1)
    lua.execute("AGPS_LONG = true; AGPS_T = 25")  # a recalculation now would come out longer
    ns.Nav.Invalidate(False)
    r2 = ns.Nav.Route(0.0, 100.0, 1)  # still on the route
    assert lua.eval("rawequal")(r2, r1) and r2.totalYards == pytest.approx(900, abs=1)
    lua.execute("AGPS_T = 50")
    ns.Nav.Invalidate(False)
    r3 = ns.Nav.Route(300.0, 200.0, 1)  # walked well away from it: the new route is used
    assert not lua.eval("rawequal")(r3, r1)


def test_off_the_walk_to_the_road_the_route_is_worked_out_again(nav_env):
    # (asked) the player's movement suggests a new point on the road to join: walking to the
    # road but off the way drawn there (10 yd and more), the route is worked out from them again
    lua, ns = nav_env
    lua.globals().AGPS_ROUTER = ns.Router
    lua.execute("""
      AGPS_T = 0
      GetTime = function() return AGPS_T end
      AGPS_ROUTER.Route = function(cont, sx, sy, tx, ty)
        local d = math.sqrt((100 - sx) ^ 2 + sy ^ 2) + math.sqrt((tx - 100) ^ 2 + (ty - 0) ^ 2)
        return { pts = { sx, sy, 100, 0, tx, ty }, kinds = { 1, 0 }, length = d, road = d - 100 }
      end
    """)
    N = ns.Nav
    N.SetDestination(100.0, 1000.0, 1, "There")
    r1 = N.Route(0.0, 0.0, 1)
    lua.execute("AGPS_T = 3")
    assert lua.eval("rawequal")(N.Route(40.0, 5.0, 1), r1)  # near the way to the road: followed
    lua.execute("AGPS_T = 6")
    r2 = N.Route(60.0, 20.0, 1)  # off it (20 yd): from here again
    assert not lua.eval("rawequal")(r2, r1) and (r2.pts[1], r2.pts[2]) == (60.0, 20.0)
    lua.execute("AGPS_T = 9")
    r3 = N.Route(115.0, 300.0, 1)  # along the road itself, a little off it: followed
    assert lua.eval("rawequal")(r3, r2)


def test_the_route_joins_the_road_where_its_heading(env):
    # (asked) south of Brill, heading west: the route went out to the road's nearest point to
    # the east and back round. Now it walks round the houses' fences and onto the road where
    # it's heading (without the offroad option, which is gone)
    lua, ns, at = tirisfal_env(env)
    P = ns.Passability
    s, t = at(60.5, 54.7), at(50.0, 50.0)
    r = ns.Router.Route(0, *s, *t, lua.table(offroad=False))
    pts, kinds = route_pts(r)
    k = list(kinds).index(0)  # (the first road point)
    assert pts[k][1] > at(59.5, 0)[1]  # joined west of Brill's fences, not east of the start
    assert r.length < 580  # (was 606)
    for i in range(k):  # the walk to the road: over open ground
        assert P.SegmentCost(0, *pts[i], *pts[i + 1]) is not None


def test_a_short_walk_over_open_ground_isnt_sent_along_a_bit_of_road(env):
    # (reported) north of a junction west of Stillwater Pond: 58 yd back to the junction, 88 yd up
    # the road and 190 yd off it again to the stop (322 yd, most of it off the road anyway),
    # when the stop was 201 yd straight over open ground
    lua, ns, at = tirisfal_env(env)
    s, t = at(43.9, 47.6), at(44.55, 41.0)
    assert ns.Passability.SegmentCost(0, *s, *t) is not None
    r = ns.Router.Route(0, *s, *t, lua.table(offroad=False))
    pts, _ = route_pts(r)
    assert len(pts) == 2 and r.length < 205


def test_the_offroad_option_is_gone(env):
    # (asked) no offroad toggle: routes always keep to the roads, joining them where they're heading
    addon = Path(__file__).parents[2] / "addon" / "AzerothGPS"
    for f in ("Core.lua", "Config.lua", "Options.lua", "GPSFrame.lua"):
        text = (addon / f).read_text(encoding="utf-8")
        assert "Off-road" not in text and "Off-Road" not in text and "/agps offroad" not in text, f
    core = (addon / "Core.lua").read_text(encoding="utf-8")
    assert "if gps then gps.offroad = nil end" in core  # (a saved setting cleared)


def test_a_route_option_changed_works_the_trip_out_again_at_once(nav_env):
    # (asked) toggling flight paths, the hearthstone, teleports or the zones avoided: the route is
    # worked out again right away (a longer one isn't held back while on the old), the stops put
    # in the fastest order again, and the map redrawn now
    lua, ns = nav_env
    lua.globals().AGPS_ROUTER = ns.Router
    lua.execute("""
      AGPS_T = 0
      GetTime = function() return AGPS_T end
      AGPS_LONG = false
      AGPS_ROUTER.Route = function(cont, sx, sy, tx, ty)
        if AGPS_LONG then
          local mx, my = (sx + tx) / 2 + 400, (sy + ty) / 2
          local d = math.sqrt((mx - sx) ^ 2 + (my - sy) ^ 2) + math.sqrt((tx - mx) ^ 2 + (ty - my) ^ 2)
          return { pts = { sx, sy, mx, my, tx, ty }, kinds = { 0, 0 }, length = d, road = d }
        end
        local d = math.sqrt((tx - sx) ^ 2 + (ty - sy) ^ 2)
        return { pts = { sx, sy, tx, ty }, kinds = { 0 }, length = d, road = d }
      end
    """)
    N = ns.Nav
    ns.settings = lua.eval("{ gps = { fastestOrder = true } }")
    N.SetDestination(0.0, 1000.0, 1, "There")
    r1 = N.Route(0.0, 0.0, 1)
    redrawn, ordered = [], []
    ns.GPS.Redraw = lambda: redrawn.append(1)
    lua.execute("AGPS_LONG = true; AGPS_T = 5")
    N.Invalidate()  # (a search finished: a longer route is held back while on the old one)
    assert lua.eval("rawequal")(N.Route(0.0, 50.0, 1), r1)
    N.OptionsChanged()  # (the player turned something off: the new one at once)
    r2 = N.Route(0.0, 60.0, 1)
    assert not lua.eval("rawequal")(r2, r1) and r2.totalYards > 1100
    assert redrawn
    N.stops = lua.eval("{ { x = 0, y = 1000, cont = 1 }, { x = 0, y = 500, cont = 1 } }")
    real = N.OrderStops
    N.OrderStops = lambda *a: ordered.append(1)
    try:
        N.OptionsChanged()
        assert ordered  # several stops, fastest order: put in order again
        ns.settings.gps.fastestOrder = False
        ordered.clear()
        N.OptionsChanged()
        assert not ordered
    finally:
        N.OrderStops = real
    opts = (Path(__file__).parents[2] / "addon" / "AzerothGPS" / "Options.lua").read_text(encoding="utf-8")
    for key in ("avoidHighZones", "useFlights", "useHearthstone", "useTeleports", "avoidHostile"):
        at = opts.index(f"GPS().{key} = v")
        assert "ns.Nav.OptionsChanged()" in opts[at:at + 120], key


def test_collapsed_steps_show_only_the_trip_times(env):
    lua, ns = env
    C = ns.GPS.CollapsedStatus
    assert C("1/3  574 yd\nAll stops: Walk 5m 02s    Mount 3m 10s") == "All stops: Walk 5m 02s    Mount 3m 10s"
    assert C("Arrived") == "Arrived"
    assert C(None) == ""


def test_offroad_joins_the_road_partway_along(env):
    # From south of Brill toward Silverpine: cut across to where the road is heading
    # rather than first going to the nearest junction (about half the distance here).
    lua, ns, _ = tirisfal_env(env)
    P = ns.Passability
    r = ns.Router.Route(0, 2038.5, 113.9, 908.6, 630.1, lua.table(offroad=False))
    # (the straight line is blocked now; the far gap links are picked by place, so the route doesn't
    # change with roads edited across the continent: 2,242 yd, with either data set)
    assert r.length < 1.9 * math.dist((2038.5, 113.9), (908.6, 630.1))
    pts, kinds = route_pts(r)
    for i, k in enumerate(kinds):
        if k == 1 and 0 < i < len(kinds) - 1:  # (the ends' legs have their own slack: a stop on rocky ground)
            assert P.SegmentCost(0, *pts[i], *pts[i + 1]) is not None, (pts[i], pts[i + 1])


def flights_env(nav_env, known):
    lua, ns = nav_env
    load(lua, ns, "Data/Pois.lua", "Data/Flights.lua")
    nodes = "".join(f"{{ nodeID = {n}, known = true }}," for n in known)
    ns.CharDB = lua.eval("function(store) return function() return store end end")(
        lua.eval(f"{{ taxiNodes = {{ [1415] = {{ nodes = {{ {nodes} }} }} }}, flights = {{}} }}"))
    ns.Nav.FlightsChanged()
    return lua, ns


def test_route_takes_a_known_flight(nav_env):
    lua, ns = flights_env(nav_env, [11, 17])  # Undercity, Hammerfall
    lua.execute("function AGPS_STOP(x, y) return { x = x, y = y, cont = 0 } end")
    legs, secs = ns.Nav.Plan(0, 1560.0, 260.0, 7.0, lua.eval("AGPS_STOP")(-910.0, -3490.0))
    kinds = [("fly " + legs[i].ride[10]) if legs[i].ride else "walk" for i in range(1, len(legs) + 1)]
    assert kinds == ["walk", "fly Hammerfall, Arathi", "walk"]
    assert secs < 400  # vs ~15 minutes on foot


def test_a_flight_is_weighed_against_the_walk_as_routed(nav_env):
    # (reported, /agps debug) level 14 from Brill into Arathi Highlands: the straight line over
    # Lordamere Lake and Alterac planned a walk; routed, it went round by Silverpine (7.6k yd) right
    # past the Sepulcher's flight master, and the flight there from Undercity wasn't taken
    lua, ns = flights_env(nav_env, [10, 11])  # the Sepulcher, Undercity
    load(lua, ns, "Data/Zones.lua", "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua", "GPSFrame.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("UnitLevel = function() return 14 end")
    N = ns.Nav
    N.SetDestination(-1441.0, -2332.0, 0, "Arathi")
    r = N.Route(2254.0, 293.0, 0)
    flights = [r.legs[i].ride[10] for i in range(1, len(r.legs) + 1) if r.legs[i].ride]
    assert "The Sepulcher, Silverpine Forest" in flights
    assert r.totalYards < 7000  # (on foot the whole way: 7.6k)


def test_a_walk_still_being_searched_doesnt_decide_against_the_flight_for_good(nav_env):
    # (reported) the flight came once, then after a stop elsewhere and back it didn't: a walk
    # still being searched is provisional (about straight, short) and beat the flight, and that
    # was remembered; used for now, it's decided again when the search is done
    lua, ns = flights_env(nav_env, [10, 11])
    load(lua, ns, "Data/Zones.lua", "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua", "GPSFrame.lua")
    R, N = ns.Router, ns.Nav
    R.Reset()
    R.SYNC_WALKS = True
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("UnitLevel = function() return 14 end")
    lua.globals().AGPS_R = R
    lua.execute("""
      AGPS_PENDING = true
      local route = AGPS_R.Route
      AGPS_R.Route = function(cont, sx, sy, tx, ty, opts)
        if AGPS_PENDING and math.abs(sx - 2254) < 60 and math.abs(sy - 293) < 60 and tx == -1441 then -- (the walk the whole way, still searched; the comparison's from about there)
          local d = math.sqrt((tx - sx) ^ 2 + (ty - sy) ^ 2)
          return { pts = { sx, sy, tx, ty }, kinds = { 1 }, length = d, road = 0, pending = true }
        end
        return route(cont, sx, sy, tx, ty, opts)
      end
    """)
    N.SetDestination(-1441.0, -2332.0, 0, "Arathi")

    def flies():
        r = N.Route(2254.0, 293.0, 0)
        return any(r.legs[i].ride for i in range(1, len(r.legs) + 1))
    assert not flies()  # (meanwhile: the straight line looks shorter)
    lua.execute("AGPS_PENDING = false")
    N.Invalidate(True)
    assert flies()  # the search done: the flight


def test_a_zone_too_high_said_yes_to_isnt_asked_again_after_a_reload(nav_env):
    # (reported) routing through a zone too high, asked and said yes to: after a /reload, with
    # the route still on, the question came up again. The answers are saved with the stops.
    lua, ns = nav_env
    N = ns.Nav
    N.redOk = lua.eval("{ [1417] = true }")  # (yes for Arathi Highlands)
    N.SetStops(lua.eval("{ { x = -1441, y = -2332, cont = 0 } }"), False, "red")
    N.redOk = lua.eval("{}")  # (a /reload: nothing in memory)
    N.Restore()
    assert N.redOk[1417] and len(N.stops) == 1
    N.Clear()  # (a new route: asked again)
    N.Restore()
    assert not N.redOk[1417] and len(N.stops) == 0


def _flight_env(nav_env, known):
    lua, ns = flights_env(nav_env, known)
    load(lua, ns, "Data/Zones.lua", "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua", "GPSFrame.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("UnitLevel = function() return 14 end")
    return lua, ns


def _flights(r):
    out = []
    for i in range(1, len(r.legs) + 1):
        t = r.legs[i].ride
        if t and t.pts:
            out.append((t[9], t[10], [(round(t.pts[j]), round(t.pts[j + 1])) for j in range(1, len(t.pts) + 1, 2)]))
    return out


def test_a_flight_master_learned_on_the_way_is_flown_to(nav_env):
    # (asked) Brill into Arathi at level 14: knowing Undercity and the Sepulcher, the flight to the
    # Sepulcher and a long walk; Tarren Mill learned too, the flight to Tarren Mill instead, drawn
    # as the dotted line from Undercity straight to it (the flight's own path)
    lua, ns = _flight_env(nav_env, [10, 11, 13])  # the Sepulcher, Undercity, Tarren Mill
    ns.Nav.SetDestination(-1441.0, -2332.0, 0, "Arathi")
    r = ns.Nav.Route(2254.0, 293.0, 0)
    (a, b, pts), = _flights(r)
    assert (a, b) == ("Undercity, Tirisfal", "Tarren Mill, Hillsbrad") and len(pts) == 2
    assert r.totalYards < 4000  # (via the Sepulcher: 6.4k on foot)


def test_a_flight_master_passed_on_the_way_is_recommended(nav_env):
    # (asked) the walk from the Sepulcher into Arathi goes by Tarren Mill's flight master, not
    # learned yet: a detour to learn it (a step where the walk passes it, a brown line on the map;
    # the next trips may fly there); learned, not
    lua, ns = _flight_env(nav_env, [10, 11])
    N = ns.Nav
    ns.CharDB().faction = "Horde"
    N.SetDestination(-1441.0, -2332.0, 0, "Arathi")
    r = N.Route(2254.0, 293.0, 0)
    (hint,) = N.LearnOnRoute(r).values()
    assert hint.name == "Tarren Mill" and 350 < hint.off < 450
    assert (hint.x, hint.y) == (-0.1, -859.9) and hint.rx and hint.ry
    # (the walk from the Sepulcher split where it passes: walk, detour, the rest of the walk)
    steps = [N.Steps()[i] for i in range(1, len(N.Steps()) + 1)]
    k = next(i for i, t in enumerate(steps) if "learn the flight path at Tarren Mill" in t)
    assert steps[k].startswith("|cffc08040Detour") and steps[k - 1].startswith("Walk 3.") and steps[k + 1].startswith("Walk 2.")
    assert steps[k - 2].startswith("Take the flight to The Sepulcher")
    assert "learn the flight path" not in N.Status(2254.0, 293.0, 0)
    ns.CharDB().faction = "Alliance"  # (not their faction's: Southshore's instead, near that walk too; not an obsolete "zzOLD" one)
    r.learnAt = None
    names = [h.name for h in N.LearnOnRoute(r).values()]
    assert "Southshore" in names and "Tarren Mill" not in names and not any(n.startswith("zz") for n in names)
    lua, ns = _flight_env(nav_env, [10, 11, 13])  # (learned)
    ns.CharDB().faction = "Horde"
    ns.Nav.SetDestination(-1441.0, -2332.0, 0, "Arathi")
    r = ns.Nav.Route(2254.0, 293.0, 0)
    assert "Tarren Mill" not in [h.name for h in (ns.Nav.LearnOnRoute(r) or lua.table()).values()]


def test_every_flight_master_passed_is_a_detour_and_the_flight_is_still_taken(nav_env):
    # (reported) toward Hammerfall: only one flight master to learn was suggested (Tarren Mill's
    # too, on the way), its detour came as step 1 before an 8.6k yd walk, and the route walked from
    # Brill all the way (the plan with a ride, asked for, walked to the flight master and on: no
    # ride in it to compare). Each detour where the walk passes it; one at the walk's end, after it.
    lua, ns = _flight_env(nav_env, [10, 11])
    N = ns.Nav
    ns.CharDB().faction = "Horde"
    N.SetDestination(-1300.0, -3400.0, 0, "Hammerfall way")
    r = N.Route(2254.0, 293.0, 0)
    assert [h.name for h in N.LearnOnRoute(r).values()] == ["Tarren Mill", "Hammerfall"]
    steps = [N.Steps()[i] for i in range(1, len(N.Steps()) + 1)]
    assert any("Take the flight to The Sepulcher" in t for t in steps)
    tm = next(i for i, t in enumerate(steps) if "at Tarren Mill" in t)
    hf = next(i for i, t in enumerate(steps) if "at Hammerfall" in t)
    assert steps[tm - 1].startswith("Walk ") and steps[tm + 1].startswith("Walk ") and "Hammerfall way" in steps[tm + 1]
    assert hf == len(steps) - 1  # (at the walk's end: after it)
    assert not any(t.startswith("Walk 2 yd") for t in steps)


def test_a_connecting_flight_is_drawn_through_its_stops(nav_env):
    # (asked) Undercity to Hammerfall: the direct path known only its ends; with Tarren Mill known
    # the flight goes through it (faster), and the dotted line goes through it too
    for known, via in (([11, 17], 2), ([11, 13, 17], 3)):
        lua, ns = _flight_env(nav_env, known)
        ns.Nav.SetDestination(-1000.0, -3500.0, 0, "Hammerfall")
        r = ns.Nav.Route(2254.0, 293.0, 0)
        (a, b, pts), = _flights(r)
        assert (a, b) == ("Undercity, Tirisfal", "Hammerfall, Arathi") and len(pts) == via, (known, pts)


def test_a_bit_of_blocked_ground_on_both_ways_doesnt_send_the_route_back_by_air(nav_env):
    # (reported) from a stop by Hammerfall to the Wetlands: walk to Hammerfall's flight master (not
    # learned), fly back to the Sepulcher and walk all the way down again. Both walks crossed the
    # same stretch the terrain calls blocked (Thandol Span), each ruled "no walk", and the tie went
    # to the ride. Blocked yards are weighed (the router's cost), not ruled out.
    lua, ns = _flight_env(nav_env, [10, 11])
    N = ns.Nav
    ns.CharDB().faction = "Horde"
    N.SetStops(lua.eval("{ { x = -1090, y = -3203, cont = 0 }, { x = -3780, y = -2750, cont = 0 } }"), False, "red")
    r = N.Route(2254.0, 293.0, 0)
    st2 = r.stretches[2]
    assert st2 and not any(st2.legs[i].ride for i in range(1, len(st2.legs) + 1))


def test_debug_tells_how_the_trip_was_planned(nav_env):
    # (a flight not taken in game, taken offline: /agps debug says why) the level, the zones too
    # high, the flight masters known, the plan and the walk straight there
    lua, ns = flights_env(nav_env, [10, 11])  # the Sepulcher, Undercity
    load(lua, ns, "Data/Zones.lua", "GPSFrame.lua")
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("UnitLevel = function() return 14 end UnitPosition = function() return 290.0, 2060.0, 0, 0 end")
    ns.Nav.SetDestination(-1050.0, -750.0, 0, "Arathi")
    text = ns.Nav.DescribePlan()
    assert "level=14" in text and "Arathi Highlands" in text and "flight masters known=2" in text
    assert "plan " in text and "walk straight there" in text


def test_a_flight_beats_a_walk_through_zones_too_high(nav_env):
    # (reported) level 13 from Tarren Mill into Western Plaguelands: the straight line looked a short
    # walk (over Alterac Mountains, 30-40), so no flight; the walk then went the long way round.
    # Planning weighs those yards as the router does (not the zones a walk starts and ends in).
    lua, ns = flights_env(nav_env, [11, 13])  # Undercity, Tarren Mill
    load(lua, ns, "Data/Zones.lua", "GPSFrame.lua")
    ns.settings = lua.eval("{ gps = {} }")
    stop = lua.eval("{ x = 1993.0, y = -967.0, cont = 0 }")

    def flies():
        legs, _ = ns.Nav.Plan(0, -20.0, -900.0, 7.0, stop)
        return any(legs[i].ride for i in range(1, len(legs) + 1))
    lua.execute("UnitLevel = function() return 60 end")
    assert not flies()  # (Alterac's fine at 60: the walk)
    lua.execute("UnitLevel = function() return 13 end")
    assert flies()


def test_planning_doesnt_walk_through_a_zone_too_high_by_a_dock_in_it(nav_env):
    # (reported: to Hillsbrad at level 13, offroad on or off, the same way) the plan split the walk
    # at a transport's end in Alterac Mountains (too high), which made Alterac a walk's end and so
    # not charged: 1.6k yd through it. Only the trip's own ends are exempt.
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua", "Data/Zones.lua", "GPSFrame.lua")
    R, N = ns.Router, ns.Nav
    R.Reset()
    R.SYNC_WALKS = True
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("UnitLevel = function() return 13 end")
    alterac = next(k for k in ns.Maps.keys() if ns.Maps[k].name == "Alterac Mountains" and ns.Maps[k].type == 3)
    stop = lua.table(x=-700.0, y=-600.0, cont=0)  # Hillsbrad (too high too: the stop's own zone)
    legs, _ = N.Plan(0, 1594.9, 290.8, 7.0, stop)
    assert len(legs) == 1 and legs[1].walk  # (one walk: not two, split at a point in Alterac)
    for off in (False, True):
        ns.settings.gps.offroad = off
        N.Clear()
        N.SetDestination(-700.0, -600.0, 0, "stop")
        r = N.Route(1594.9, 290.8, 0)
        through = 0
        for i in range(1, len(r.parts) + 1):
            p = r.parts[i]
            for k in range(1, len(p.pts) - 2, 2):
                through += R.ZoneYards(0, p.pts[k], p.pts[k + 1], p.pts[k + 2], p.pts[k + 3])[alterac] or 0
        assert through < 100, (off, through)


def test_connecting_flight_and_option_off(nav_env):
    # Sepulcher to Light's Hope has no direct flight: one flight, connecting at Undercity
    lua, ns = flights_env(nav_env, [10, 11, 68])
    stop = lua.eval("{ x = 2320.0, y = -5280.0, cont = 0 }")
    legs, _ = ns.Nav.Plan(0, 480.0, 1530.0, 7.0, stop)
    rides = [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride]
    assert len(rides) == 1 and rides[0][9].startswith("The Sepulcher") and rides[0][10].startswith("Light's Hope")
    assert len(rides[0].pts) == 6  # via Undercity
    ns.settings = lua.eval("{ gps = { useFlights = false } }")
    ns.Nav.FlightsChanged()
    legs, _ = ns.Nav.Plan(0, 480.0, 1530.0, 7.0, stop)
    assert all(not legs[i].ride for i in range(1, len(legs) + 1))


def _rides(legs):
    return [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride]


def test_a_ride_left_out_is_not_taken_on_this_route(nav_env):
    # (asked) right-click "Remove?" on a ride's pin: that zeppelin isn't taken again on this route
    # (rerouting, after a /reload), and is back with a new route
    lua, ns = nav_env
    N = ns.Nav
    N.SetDestination(1600.0, -4400.0, 1, "Orgrimmar")
    zep = _rides(N.Plan(0, 1600.0, 240.0, 7.0)[0])[0]
    assert zep[8] == "zeppelin"
    key = N.RideKey(zep)
    N.SkipRide(zep)
    legs, _ = N.Plan(0, 1600.0, 240.0, 7.0)
    assert legs and all(N.RideKey(t) != key for t in _rides(legs))
    assert list(ns.CharDB().skipRides.values()) == [key]  # (saved with the stops)
    N.skipRides = lua.eval("{}")
    N.Restore()  # (a /reload)
    assert N.skipRides[key]
    assert all(N.RideKey(t) != key for t in _rides(N.Plan(0, 1600.0, 240.0, 7.0)[0]))
    N.SetDestination(1600.0, -4400.0, 1, "Orgrimmar")  # (a new route: the ride back)
    assert not N.skipRides[key]
    assert N.RideKey(_rides(N.Plan(0, 1600.0, 240.0, 7.0)[0])[0]) == key
    N.SkipRide(zep)
    N.Clear()
    assert not N.skipRides[key] and not ns.CharDB().skipRides


def test_a_flight_connection_left_out_breaks_the_flights_over_it(nav_env):
    # (asked) "Remove?" on a flight's pin leaves out that one connection between two flight masters:
    # a flight connecting over it can't be taken either on this route ("so be it"), the others can
    lua, ns = flights_env(nav_env, [10, 11, 68])
    N = ns.Nav
    load(lua, ns, "Turns.lua")
    N.SetDestination(2320.0, -5280.0, 0, "Light's Hope")
    stop = N.dest
    r = N.Route(480.0, 1530.0, 0)
    pins = N.RidePins(r)
    titles = [pins[i].title for i in range(1, len(pins) + 1)]
    assert len(titles) == 2  # Sepulcher to Undercity, Undercity to Light's Hope: one pin each
    assert titles[0].startswith("Flight: The Sepulcher") and " to Undercity" in titles[0]
    assert titles[1].startswith("Flight: Undercity") and " to Light's Hope" in titles[1]
    assert pins[1].kind == "flight" and pins[2].hop == 2
    N.SkipRide(pins[2].ride, pins[2].hop)
    legs, _ = N.Plan(0, 480.0, 1530.0, 7.0, stop)
    assert not any(t[10].startswith("Light's Hope") for t in _rides(legs))
    # (the Sepulcher to Undercity still flies)
    to_uc = _rides(N.Plan(0, 480.0, 1530.0, 7.0, lua.eval("{ x = 1560.0, y = 260.0, cont = 0 }"))[0])
    assert len(to_uc) == 1 and to_uc[0][10].startswith("Undercity")
    # (either way: Light's Hope to Undercity is the same connection)
    back = _rides(N.Plan(0, 2270.0, -5340.0, 7.0, lua.eval("{ x = 1560.0, y = 260.0, cont = 0 }"))[0])
    assert not any(t[9].startswith("Light's Hope") for t in back)


def test_a_teleport_left_out_is_not_used_on_this_route(nav_env):
    lua, ns = nav_env
    N = ns.Nav
    hearth = lua.eval("""{ { 0, 1560.0, 260.0, 0, -900.0, -3480.0, 10, "your Hearthstone", "", "Hammerfall", "your Hearthstone",
      use = true, item = 6948 } }""")
    stop = lua.eval("{ x = -910.0, y = -3490.0, cont = 0 }")
    N.SetDestination(-910.0, -3490.0, 0, "Hammerfall")
    assert N.RideKey(hearth[1]) == "u:i6948"
    rides = _rides(N.Plan(0, 1560.0, 260.0, 7.0, stop, hearth)[0])
    assert rides and rides[0].use
    pins = N.RidePins(lua.eval("function(t) return { legs = { { ride = t, from = 1 } } } end")(hearth[1]))
    assert len(pins) == 1 and pins[1].kind == "teleport" and pins[1].title == "Your Hearthstone to Hammerfall"
    assert pins[1].x == -900.0  # (where it lands)
    N.SkipRide(hearth[1])
    assert not any(t.use for t in _rides(N.Plan(0, 1560.0, 260.0, 7.0, stop, hearth)[0]))

def test_route_learns_a_new_flight_master_on_the_way(nav_env):
    # Near Tarren Mill (not learned yet), to Undercity (known): walk to Tarren Mill, learn
    # it and fly, rather than the long walk. Horde only; flights never land at unknown ones.
    lua, ns = flights_env(nav_env, [11])
    ns.CharDB().faction = "Horde"
    ns.Nav.FlightsChanged()
    stop = lua.eval("{ x = 1560.0, y = 260.0, cont = 0 }")
    legs, secs = ns.Nav.Plan(0, 60.0, -800.0, 7.0, stop)
    rides = [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride]
    assert len(rides) == 1 and rides[0].learn and rides[0][9].startswith("Tarren Mill")
    assert rides[0][11] == "new flight master"
    assert secs < 300
    load(lua, ns, "Turns.lua")
    ns.Nav.SetDestination(1560.0, 260.0, 0, "Undercity")
    assert ns.Nav.Route(60.0, -800.0, 0)
    steps = ns.Nav.StepsText(3)
    assert "to the new flight master (Tarren Mill, Hillsbrad)" in steps
    assert "Learn the flight path, then take the flight to Undercity, Tirisfal" in steps
    ns.Nav.Clear()
    ns.CharDB().faction = "Alliance"
    ns.Nav.FlightsChanged()
    legs, _ = ns.Nav.Plan(0, 60.0, -800.0, 7.0, stop)
    assert all(not legs[i].ride for i in range(1, len(legs) + 1))
    # to Tarren Mill itself: no flight lands there while it's unknown
    ns.CharDB().faction = "Horde"
    ns.Nav.FlightsChanged()
    legs, _ = ns.Nav.Plan(0, 1560.0, 260.0, 7.0, lua.eval("{ x = 0.0, y = -860.0, cont = 0 }"))
    assert all(not legs[i].ride for i in range(1, len(legs) + 1))


def test_no_flights_without_known_flight_masters(nav_env):
    lua, ns = flights_env(nav_env, [])
    legs, _ = ns.Nav.Plan(0, 1560.0, 260.0, 7.0, lua.eval("{ x = -910.0, y = -3490.0, cont = 0 }"))
    assert all(not legs[i].ride for i in range(1, len(legs) + 1))


def test_flight_in_route_steps_and_directions(nav_env):
    lua, ns = flights_env(nav_env, [11, 17])
    load(lua, ns, "Turns.lua")
    ns.Nav.SetDestination(-910.0, -3490.0, 0, "Hammerfall")
    r = ns.Nav.Route(1350.0, 150.0, 0)  # a walk from the flight master
    assert r and r.rideSeconds > 0
    steps = ns.Nav.StepsText(3)
    assert "to the flight master (Undercity, Tirisfal)" in steps
    assert "Take the flight to Hammerfall, Arathi" in steps
    status = ns.Nav.Status(1350.0, 150.0, 0)
    assert "to the flight master (then to Hammerfall, Arathi)" in status


def test_route_while_flying_waits_for_the_landing(nav_env):
    lua, ns = flights_env(nav_env, [10, 11])  # The Sepulcher, Undercity
    lua.execute("""
      AGPS_FLYING = { from = "The Sepulcher, Silverpine Forest", to = "Undercity, Tirisfal", start = 0 }
      AGPS_TAXI = { Current = function() return AGPS_FLYING end }
    """)
    ns.Taxi = lua.eval("AGPS_TAXI")
    ns.Nav.SetDestination(1400.0, 150.0, 0, "Past Undercity")
    r = ns.Nav.Route(900.0, 1000.0, 0)  # in the air over Silverpine
    assert r.flying and r.flying.to == "Undercity, Tirisfal"
    assert (r.pts[1], r.pts[2]) == (900.0, 1000.0)  # the flight's line starts at the player
    assert r.legs[1].ride.flying and r.rideSeconds >= r.flying.seconds
    assert "Flying to Undercity, Tirisfal" in ns.Nav.Status(900.0, 1000.0, 0)
    assert "Flying to Undercity, Tirisfal" in ns.Nav.StepsText(3)
    # further along: the same route, the line shorter; nothing recalculated
    r2 = ns.Nav.Route(1200.0, 700.0, 0)
    assert r2.flying and (r2.pts[1], r2.pts[2]) == (1200.0, 700.0)
    # landed: an ordinary route again
    lua.execute("AGPS_FLYING = nil")
    r3 = ns.Nav.Route(1568.0, 268.0, 0)
    assert not r3.flying


def test_no_mount_time_without_riding(nav_env):
    lua, ns = nav_env
    lua.execute("""
      AGPS_RANK = 0
      GetNumSkillLines = function() return 1 end
      GetSkillLineInfo = function() return "Riding", false, nil, AGPS_RANK end
      AGPS_TAXI = false
      UnitOnTaxi = function() return AGPS_TAXI end
      GetUnitSpeed = function() return 32, 7, 7, 4.7 end
      IsMounted = function() return AGPS_TAXI end
    """)
    lua.execute("AGPS_TAXI = true")  # on a flight: the game says mounted, at flight speed
    _, _, mount, mounted, _ = ns.Nav.Speeds()
    assert mount is None and not mounted
    assert ns.CharDB().mountSpeed is None  # the flight's speed isn't kept as a mount's


def test_movement_ability_time_shown_and_used_while_on(nav_env):
    lua, ns = nav_env
    lua.execute("""
      AGPS_T = 0; GetTime = function() return AGPS_T end
      GetNumSkillLines = function() return 0 end
      UnitOnTaxi = function() return false end
      IsMounted = function() return false end
      AGPS_RUN = 7.35  -- (a 5% Speed stat)
      GetUnitSpeed = function() return AGPS_RUN, AGPS_RUN, 7, 4.7 end
      IsPlayerSpell = function(id) return id == 2645 end  -- a shaman with Ghost Wolf
      AGPS_WOLF = false
      C_UnitAuras = { GetPlayerAuraBySpellID = function(id) if AGPS_WOLF and id == 2645 then return {} end end }
    """)
    N = ns.Nav
    cur, walk, mount, mounted, ab = N.Speeds()
    assert walk == pytest.approx(7.35)  # the plain run speed, the Speed stat in it
    assert ab.spell == 2645 and not ab.active
    assert ab.speed == pytest.approx(7.35 * 1.4)  # estimated until seen
    # turned on: the server's speed learned, and it's the walking speed now
    lua.execute("AGPS_WOLF = true AGPS_RUN = 10.5 AGPS_T = 1")
    cur, walk, mount, mounted, ab = N.Speeds()
    assert ab.active and walk == pytest.approx(10.5)
    assert ns.CharDB().moveSpeeds[2645] == pytest.approx(10.5)
    # off again: walking at the plain speed, the wolf's learned time beside it
    lua.execute("AGPS_WOLF = false AGPS_RUN = 7.35 AGPS_T = 2")
    cur, walk, mount, mounted, ab = N.Speeds()
    assert walk == pytest.approx(7.35) and not ab.active and ab.speed == pytest.approx(10.5)
    # no ability known: none
    lua.execute("IsPlayerSpell = function() return false end AGPS_T = 20")
    assert N.MoveAbility() is None


def test_cat_form_counts_only_with_feline_swiftness(nav_env):
    lua, ns = nav_env
    lua.execute("""
      GetTime = function() return 0 end
      AGPS_KNOWN = { [768] = true }
      IsPlayerSpell = function(id) return AGPS_KNOWN[id] or false end
    """)
    assert ns.Nav.MoveAbility() is None  # Cat Form alone adds no speed
    lua.execute("AGPS_KNOWN[24866] = true GetTime = function() return 30 end")  # Feline Swiftness rank 2
    ab = ns.Nav.MoveAbility()
    assert ab.spell == 768 and ab.speed == pytest.approx(7 * 1.3)


def test_reorders_stops_when_another_order_becomes_clearly_faster(nav_env):
    lua, ns = nav_env
    lua.execute("AGPS_T = 100 GetTime = function() return AGPS_T end")
    ns.settings = lua.eval("{ gps = { fastestOrder = true } }")
    far, near = (-1500.0, -4700.0), (-600.0, -4180.0)
    ns.Nav.SetStops(stops(lua, far, near))  # placed far first
    assert ns.Nav.stops[1].x == far[0]
    # the player is walking toward the near one: visiting it first is clearly faster
    assert ns.Nav.MaybeReorder(-620.0, -4200.0, 1)
    assert ns.Nav.stops[1].x == near[0] and ns.Nav.stops[2].x == far[0]
    # right away again: not checked (every few seconds, after moving)
    assert not ns.Nav.MaybeReorder(-620.0, -4200.0, 1)
    # about as fast either way: the order stays
    ns.Nav.SetStops(stops(lua, (-700.0, -4180.0), (-500.0, -4180.0)))
    lua.execute("AGPS_T = 200")
    assert not ns.Nav.MaybeReorder(-600.0, -3000.0, 1)


def test_zephras_isle_has_map_data_and_a_way_there(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Minimap.lua")
    assert len(list(ns.MinimapTiles[2991].keys())) > 50  # terrain view tiles
    assert ns.Maps[2521].continent == 2991 and ns.Maps[2521].bounds
    e, _ = ns.Router.Edges(2991)
    assert len(e) > 50  # its roads
    # from Mulgore, the zeppelin to the island
    legs, _ = ns.Nav.Plan(1, -800.0, 360.0, 7.0, lua.eval("{ x = 2197.0, y = 772.0, cont = 2991 }"))
    rides = [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride]
    assert rides and rides[0][10].endswith("Zephras Isle")


def test_click_through_while_moving_or_in_combat(env):
    lua, ns = env
    W = ns.GPS.ClickThroughWanted
    st = lua.eval("{ clickThroughMoving = true, clickThroughCombat = false }")
    assert W(st, True, False) is True and W(st, False, True) is False and W(st, False, False) is False
    st = lua.eval("{ clickThroughMoving = false, clickThroughCombat = true }")
    assert W(st, True, False) is False and W(st, False, True) is True


def test_search_places(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Pois.lua")
    res = ns.GPS.SearchPlaces("razor", 8)
    names = [res[i].name for i in range(1, len(res) + 1)]
    assert names and names[0].startswith("Razor Hill")
    assert len(ns.GPS.SearchPlaces("r", 8)) == 0  # needs 2+ letters
    res = ns.GPS.SearchPlaces("zephras", 8)
    assert any(res[i].cont == 2991 for i in range(1, len(res) + 1))


def test_markers_skip_cross_and_skull(nav_env):
    lua, ns = nav_env
    icons = [ns.Nav.MarkerFor(k) for k in range(1, 9)]
    assert 7 not in icons and 8 not in icons and icons[6:] == icons[:2]  # starts over after six


def test_farming_loop_goes_round(nav_env):
    lua, ns = nav_env
    nodes = lua.eval("""{ { x = 0, y = 0, cont = 1, name = "Copper Vein" }, { x = 300, y = 0, cont = 1, name = "Copper Vein" },
      { x = 300, y = 300, cont = 1, name = "Tin Vein" }, { x = 0, y = 300, cont = 1, name = "Copper Vein" } }""")
    ns.Nav.SetLoop(nodes, -10.0, -10.0)
    assert ns.Nav.loop and len(ns.Nav.stops) == 4 and (ns.Nav.stops[1].x, ns.Nav.stops[1].y) == (0, 0)
    first = ns.Nav.stops[1]
    ns.Nav.Status(1.0, 1.0, 1)  # at the first node: it goes to the end, on to the next
    assert len(ns.Nav.stops) == 4 and lua.eval("rawequal")(ns.Nav.stops[4], first)
    ns.Nav.Clear()
    assert not ns.Nav.loop


def test_shared_map_pin_becomes_a_stop(importer):
    # A map pin link from chat ("worldmap:<map>:<x>:<y>", 1/10000 of the map): a stop at
    # that spot, named after the zone and coordinates; added to a route, or a new one.
    lua, ns = importer
    I, N = ns.Import, ns.Nav
    b = ns.Maps[1411].bounds
    pin = I.ParseMapPin("worldmap:1411:4213:6534")
    assert pin.cont == 1 and pin.name == "Map pin (Durotar 42.1, 65.3)"
    assert pin.x == pytest.approx(b[3] - 0.6534 * (b[3] - b[1]))
    assert pin.y == pytest.approx(b[4] - 0.4213 * (b[4] - b[2]))
    assert I.ParseMapPin("item:6948") is None and I.ParseMapPin("worldmap:999999:1:1") is None
    ns.Print = lua.eval("function() end")
    N.Clear()
    I.AddMapPin(pin)
    assert len(N.stops) == 1 and N.stops[1].name == pin.name
    I.AddMapPin(I.ParseMapPin("worldmap:1411:5000:5000"))
    assert len(N.stops) == 2  # added to the route


def test_guard_directions_become_a_saved_city_location_and_a_stop(importer):
    # A guard marks "Alchemy Trainer" on the map (a gossip point of interest): saved for all
    # characters with the alchemy icon, shown on the map, and made a stop (once).
    lua, ns = importer
    load(lua, ns, "Layers.lua")
    L, N = ns.Layers, ns.Nav
    lua.execute("""
      C_Map = C_Map or {}
      C_Map.GetBestMapForUnit = function() return 1411 end
      C_GossipInfo = {
        GetPoiForUiMapID = function(mapID) return 77 end,
        GetPoiInfo = function(mapID, id) return { name = "Alchemy Trainer", textureIndex = 5, position = { x = 0.5, y = 0.4 } } end,
      }
    """)
    ns.Print = lua.eval("function() end")
    ns.settings = lua.eval("{ gps = { layerCity = true, fastestOrder = false } }")
    assert L.CityIcon("Alchemy Trainer").endswith("Trade_Alchemy")
    assert L.CityIcon("Warrior Trainer").endswith("INV_Sword_27")
    assert L.CityIcon("Something Else") == L.CITY_DEFAULT_ICON
    N.Clear()
    L.OnGossipPoi()
    L.OnGossipPoi()  # the event repeats: still one stop, one saved place
    x, y, cont = L.MapToWorld(1411, 0.5, 0.4)
    assert len(N.stops) == 1 and N.stops[1].name == "Alchemy Trainer" and N.stops[1].tex.endswith("Trade_Alchemy")
    assert N.StopIcon(N.stops[1]) == N.stops[1].tex
    saved = L.CityDB()[cont]
    assert len(saved) == 1 and saved[1][3] == "Alchemy Trainer"
    marks = L.Marks(cont, x, y, 100, lua.table())
    assert any(marks[i][4] == "Alchemy Trainer" for i in range(1, len(marks) + 1))
    ns.settings.gps.layerCity = False
    marks = L.Marks(cont, x, y, 100, lua.table())
    assert not any(marks[i][4] == "Alchemy Trainer" for i in range(1, len(marks) + 1))


def test_approach_zoom_near_a_stop(importer):
    # Within 50 yd of the next stop (following the player): zoom in to 70 yd, not beyond the
    # zoom you had; back out (nil) beyond 70 yd, when it's off, or once you've arrived.
    lua, ns = importer
    G, N = ns.GPS, ns.Nav
    ns.settings = lua.eval("{ gps = { approachZoom = true, zoom = 400 } }")
    N.SetDestination(-600.0, -4180.0, 1, "Spot")
    assert G.ApproachTarget(-600.0, -4240.0, 1) is None  # 60 yd: not yet
    
    assert G.ApproachTarget(-600.0, -4220.0, 1) == 70  # 40 yd
    assert G.ApproachTarget(-600.0, -4245.0, 1) == 70  # 65 yd: still (until 70)
    assert G.ApproachTarget(-600.0, -4260.0, 1) is None  # 80 yd: back out
    ns.settings.gps.zoom = 50
    assert G.ApproachTarget(-600.0, -4220.0, 1) == 50  # already closer: stays
    ns.settings.gps.approachZoom = False
    assert G.ApproachTarget(-600.0, -4220.0, 1) is None


def test_import_nodes_and_pick_them_in_an_area(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Import.lua", "Layers.lua")
    added, skipped, errors = ns.Layers.ImportNodes(
        "/way #1411 52.0 41.0 Copper Vein\n/way #1411 53.0 42.0 Peacebloom\n/way #1411 50.0 40.0 Tree")
    assert added == 2 and len(list(errors.values())) == 1
    cont = ns.Maps[1411].continent
    node = ns.db.nodes[cont][1]
    assert node[6] is True  # unconfirmed
    ns.Layers.AddNode(cont, node[1] + 3, node[2] + 3, "Copper Vein", "ore")  # gathered there
    assert ns.db.nodes[cont][1][6] is None
    x, y = node[1], node[2]
    poly = lua.eval("function(x, y) return { x - 50, y - 50, x + 50, y - 50, x + 50, y + 50, x - 50, y + 50 } end")(x, y)
    inside = ns.Layers.NodesInPolygon(cont, poly, lua.eval("{ ore = true }"))
    assert len(inside) == 1 and inside[1].name == "Copper Vein"


def test_route_starts_with_the_hearthstone_when_faster(nav_env):
    lua, ns = nav_env
    lua.execute("""
      AGPS_TP = { Available = function(cont, px, py)
        return { { cont, px, py, 0, 2270.0, 245.0, 25, "your Hearthstone", "", "Brill", "your Hearthstone", use = true } }
      end }
    """)
    ns.Teleports = lua.eval("AGPS_TP")
    ns.Nav.SetDestination(2250.0, 250.0, 0, "Brill inn")  # home is Brill; the player is in Durotar
    r = ns.Nav.Route(300.0, -4700.0, 1)
    assert r.legs[1].ride and r.legs[1].ride.use
    assert "Use your Hearthstone (to Brill)" in ns.Nav.StepsText(3) or "Use your Hearthstone" in ns.Nav.Status(300.0, -4700.0, 1)
    # a stop right here: no hearthstone
    ns.Nav.SetDestination(320.0, -4690.0, 1, "Nearby")
    r = ns.Nav.Route(300.0, -4700.0, 1)
    assert not (r.legs[1].ride and r.legs[1].ride.use)


def test_the_hearthstone_only_when_it_saves_more_than_800_yards(nav_env):
    # (asked) home is Brill: a stop at the inn 500 yd off isn't worth the hearthstone's cooldown;
    # from farther (it saves more than 800 yd of walking), it is
    lua, ns = nav_env
    lua.execute("""
      AGPS_TP = { Available = function(cont, px, py)
        return { { cont, px, py, 0, 2270.0, 245.0, 25, "your Hearthstone", "", "Brill", "your Hearthstone", use = true, item = 6948 } }
      end }
    """)
    ns.Teleports = lua.eval("AGPS_TP")
    N = ns.Nav

    def hearths(py):
        N.SetDestination(2270.0, 245.0, 0, "Brill inn")
        r = N.Route(2270.0, py, 0)
        return bool(r.legs[1].ride and r.legs[1].ride.use)
    assert not hearths(245.0 - 500)
    assert hearths(245.0 - 1200)


def test_hearthstone_on_the_stretch_where_it_saves_most(nav_env):
    # A trip ending near home: hearth from the last stop but one, not walk back. And the
    # hearthstone is used once per trip, even when it would help on two stretches.
    lua, ns = nav_env
    lua.execute("""
      AGPS_TP = { Available = function(cont, px, py)
        return { { cont, px, py, 0, 2270.0, 245.0, 25, "your Hearthstone", "", "Brill", "your Hearthstone", use = true } }
      end }
    """)
    ns.Teleports = lua.eval("AGPS_TP")
    N = ns.Nav

    def uses(r):
        return [any(st.legs[k].ride and st.legs[k].ride.use for k in range(1, len(st.legs) + 1))
                for st in (r.stretches[i] for i in range(1, len(r.stretches) + 1))]

    # from the Undercity to Tarren Mill, then to near Brill
    N.SetStops(
        lua.table(lua.table(x=0.0, y=-860.0, cont=0), lua.table(x=2250.0, y=250.0, cont=0)))
    r = N.Route(1560.0, 260.0, 0)
    assert uses(r) == [False, True]
    assert "Use your Hearthstone (to Brill)" in N.StepsText(9)
    # Durotar -> Brill -> Orgrimmar -> Brill: the hearthstone once only
    N.SetStops(lua.table(lua.table(x=2250.0, y=250.0, cont=0), lua.table(x=1600.0, y=-4400.0, cont=1),
                         lua.table(x=2260.0, y=260.0, cont=0)))
    r = N.Route(300.0, -4700.0, 1)
    assert sum(uses(r)) == 1


def test_offroad_start_on_rocks_walks_off_them(env):
    # Zephras Isle, Rise of Spirits: the player stands on a rock outcrop the slope data calls
    # impassable. The route walks off it and around (about 180 yd), not via the village road.
    lua, ns = env
    load(lua, ns, "Data/Roads.lua", "Data/Terrain.lua", "Passability.lua", "Router.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    ns.Passability.ClearCache()
    assert ns.Passability.At(2991, 4007.0, 1556.0) == 2  # standing on "blocked" ground
    r = ns.Router.Route(2991, 4007.0, 1556.0, 4158.0, 1607.0, lua.table(offroad=True))
    assert r.length < 260


def test_gathering_recognized_at_any_rank_or_by_node_name(env):
    lua, ns = env
    ns.db = lua.eval("{}")
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    G = ns.Layers.GatherKind
    assert G(2575, "Copper Vein") == "ore"
    assert G(3564, "Iron Deposit") == "ore"  # a higher rank's spell
    assert G(11993, "Sungrass") == "herb"
    assert G(123456, "Copper Vein") == "ore"  # unknown spell, known node name
    assert G(123456, "Some Mob") is None


def test_offroad_walks_out_of_a_pocket_instead_of_cutting_the_cliff(env):
    # Dustwallow Marsh (from agps route-check): the start is in an open pocket walled by
    # steep ground; the route walks the long way out rather than straight through the wall.
    lua, ns = env
    load(lua, ns, "Data/Roads.lua", "Data/Terrain.lua", "Passability.lua", "Router.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    ns.Passability.ClearCache()
    r = ns.Router.Route(1, -3837.3, -2589.4, -3018.6, -3070.5, lua.table(offroad=True))
    pts = [r.pts[i] for i in range(1, len(r.pts) + 1)]
    kinds = [r.kinds[i] for i in range(1, len(r.kinds) + 1)]
    P = ns.Passability
    for i, k in enumerate(kinds):  # no off-road stretch crosses more than a few cells of wall
        if k != 1:
            continue
        x1, y1, x2, y2 = pts[2 * i], pts[2 * i + 1], pts[2 * i + 2], pts[2 * i + 3]
        n = max(1, int(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 / 3))
        run = best = 0
        for j in range(n + 1):
            t = j / n
            run = run + 3 if P.At(1, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t) == 2 else 0
            best = max(best, run)
        assert best < 40


def test_right_clicked_herb_or_ore_without_the_profession_is_saved(env):
    lua, ns = env
    ns.db = lua.eval("{}")
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    L = ns.Layers
    L.NoteWorldObject("Peacebloom", 10.0)  # the tooltip showed it
    assert L.OnGatherError("Requires Herbalism", 11.0, 100.0, 200.0, 1)
    L.NoteWorldObject("Copper Vein", 20.0)
    assert L.OnGatherError("Requires Mining", 21.0, 300.0, 200.0, 1)
    nodes = ns.db.nodes[1]
    assert [(nodes[i][3], nodes[i][4]) for i in (1, 2)] == [("Peacebloom", "herb"), ("Copper Vein", "ore")]
    L.NoteWorldObject("Tin Vein", 30.0)
    assert not L.OnGatherError("Requires Mining", 40.0, 500.0, 200.0, 1)  # too long after the tooltip
    assert not L.OnGatherError("Not enough mana", 30.5, 500.0, 200.0, 1)


def test_hearthstone_ready_with_the_newer_item_api(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Pois.lua", "Teleports.lua")
    lua.execute("""
      GetItemCount = nil
      C_Item = { GetItemCount = function(id) return id == 6948 and 1 or 0 end }
      C_Container = { GetItemCooldown = function() return 0, 0, 1 end }
      GetBindLocation = function() return "Brill" end
      IsPlayerSpell = function() return false end
    """)
    ns.settings = lua.eval("{ gps = { useHearthstone = true, useTeleports = true } }")
    rows = ns.Teleports.Available(1, 300.0, -4700.0)
    assert len(rows) == 1 and rows[1][8] == "your Hearthstone" and rows[1][10] == "Brill" and rows[1][4] == 0
    ns.settings.gps.useHearthstone = False
    ns.Teleports.Changed()
    assert len(ns.Teleports.Available(1, 300.0, -4700.0)) == 0


def test_engineers_teleporters_with_their_specialization(nav_env):
    # (asked) more ways to travel: an engineer's Ultrasafe Transporter: Gadgetzan and Dimensional
    # Ripper - Everlook, when in the bags, off cooldown, and with the specialization that uses it;
    # each row says what the use button uses (item or spell)
    lua, ns = nav_env
    load(lua, ns, "Data/Pois.lua", "Teleports.lua")
    lua.execute("""
      AGPS_ITEMS = { [6948] = 1, [18986] = 1, [18984] = 1 }
      AGPS_KNOWN = { [20219] = true } -- Gnomish Engineer (the Transporter's), not Goblin (the Ripper's)
      GetItemCount = function(id) return AGPS_ITEMS[id] or 0 end
      GetItemCooldown = function() return 0, 0, 1 end
      GetBindLocation = function() return "Brill" end
      IsPlayerSpell = function(id) return AGPS_KNOWN[id] or false end
      GetItemInfo = nil
    """)
    ns.settings = lua.eval("{ gps = { useHearthstone = true, useTeleports = true } }")
    T = ns.Teleports
    T.Changed()
    rows = {r[8]: r for r in T.Available(0, 2250.0, 250.0).values()}
    assert set(rows) == {"your Hearthstone", "Ultrasafe Transporter: Gadgetzan"}
    assert rows["your Hearthstone"].item == 6948
    g = rows["Ultrasafe Transporter: Gadgetzan"]
    assert g.item == 18986 and g[10] == "Gadgetzan" and g[4] == 1 and g.use
    ns.settings.gps.useTeleports = False  # (the option: teleports and teleport items)
    T.Changed()
    assert [r[8] for r in T.Available(0, 2250.0, 250.0).values()] == ["your Hearthstone"]


def test_the_use_button_uses_the_routes_first_teleport(nav_env):
    # (asked) the route starting with a teleport: a button beside the directions uses it (the
    # player's click, a secure button); set only out of combat
    lua, ns = nav_env
    G, N = ns.GPS, ns.Nav
    hearth = lua.eval("{ 0, 1, 2, 0, 3, 4, 25, 'your Hearthstone', '', 'Brill', 'your Hearthstone', use = true, item = 6948 }")
    N.route = lua.eval("function(t) return { legs = { { ride = t, from = 1 }, { walk = true } } } end")(hearth)
    assert lua.eval("rawequal")(N.UseNow(), hearth)
    N.route = lua.eval("{ legs = { { walk = true }, { ride = { use = true, item = 6948 }, from = 1 } } }")
    assert N.UseNow() is None  # (walk first: not yet)
    assert G.UseKey(hearth) == "item:6948"
    assert G.UseKey(lua.eval("{ use = true, spell = 556 }")) == "spell:556"
    lua.execute("""
      AGPS_ATTR, AGPS_SHOWN = {}, false
      AGPS_PANEL = { GetFrameStrata = function() return "MEDIUM" end, GetFrameLevel = function() return 5 end }
      AGPS_BTN = { panel = AGPS_PANEL,
        icon = { SetTexture = function() end },
        SetAttribute = function(_, k, v) AGPS_ATTR[k] = v end,
        Show = function() AGPS_SHOWN = true end, Hide = function() AGPS_SHOWN = false end,
        ClearAllPoints = function() end, SetPoint = function() end,
        SetFrameStrata = function() end, SetFrameLevel = function() end }
      InCombatLockdown = function() return AGPS_COMBAT end
      AGPS_COMBAT = false
    """)
    G.useBtn = lua.eval("AGPS_BTN")
    G.UpdateUseButton(hearth)
    assert lua.eval("AGPS_ATTR.type") == "item" and lua.eval("AGPS_ATTR.item") == "item:6948" and lua.eval("AGPS_SHOWN")
    lua.execute("AGPS_COMBAT = true")
    G.UpdateUseButton(None)  # (in combat: left as it is; hidden as combat started)
    assert lua.eval("AGPS_SHOWN")
    lua.execute("AGPS_COMBAT = false")
    G.UpdateUseButton(None)
    assert not lua.eval("AGPS_SHOWN")
    G.useBtn = None


def test_turning_flights_off_applies_right_away(nav_env):
    lua, ns = flights_env(nav_env, [11, 17])
    lua.execute("AGPS_T = 0 GetTime = function() return AGPS_T end")
    ns.settings = lua.eval("{ gps = { useFlights = true } }")
    ns.Nav.SetDestination(-910.0, -3490.0, 0, "Hammerfall")
    r = ns.Nav.Route(1350.0, 150.0, 0)
    assert any(r.legs[i].ride for i in range(1, len(r.legs) + 1))
    ns.settings.gps.useFlights = False
    ns.Nav.FlightsChanged()
    lua.execute("AGPS_T = 1")
    r = ns.Nav.Route(1350.0, 150.0, 0)  # at once, though walking is much longer
    assert not any(r.legs[i].ride for i in range(1, len(r.legs) + 1))


def test_home_from_the_inn_building(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Pois.lua", "Teleports.lua")
    lua.execute('GetBindLocation = function() return "Gallows\' End Tavern" end')
    home = ns.Teleports.Home()
    assert home.cont == 0 and abs(home.x - 2259) < 50 and abs(home.y - 245) < 50  # Brill


def test_quest_area_stays_drawn_while_retraced(env):
    lua, ns = env
    ns.db = lua.eval("{}")
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("""
      AGPS_T = 1000
      GetTime = function() return AGPS_T end
      AGPS_DONE = false
      C_QuestLog = {
        GetQuestsOnMap = function() return { { questID = 7, x = 0.4, y = 0.6 } } end,
        IsComplete = function() return false end,
        GetQuestObjectives = function() return { { finished = AGPS_DONE }, { finished = false } } end,
      }
      C_Minimap = { IsInsideQuestBlob = function(q, u, v)
        return q == 7 and (u - 0.4) ^ 2 + (v - 0.6) ^ 2 <= 0.01 end }
    """)
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    L = ns.Layers
    maps = lua.table(1411)
    b = ns.Maps[1411].bounds
    cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
    L.Areas(1, cx, cy, 1e6, maps)
    L.TraceAll()
    before = len(L.Areas(1, cx, cy, 1e6, maps))
    assert before > 40
    # an objective finished: the area is traced again, and meanwhile the old one stays drawn
    lua.execute("AGPS_DONE = true; AGPS_T = 2000")
    assert len(L.Areas(1, cx, cy, 1e6, maps)) == before


def test_panned_view_comes_back_after_a_reload(router):
    lua, ns = router
    lua.execute("UnitGUID = function() return 'Player-1' end; time = function() return 1000 end")
    G = ns.GPS
    assert G.SaveView() is None  # following the player: nothing to keep
    G.RestoreView(lua.eval("{ x = 120, y = -340, rot = 0, cont = 1, cross = true, who = 'Player-1', t = 990 }"))
    v = G.SaveView()
    assert (v.x, v.y, v.cont) == (120, -340, 1)
    G.Follow()
    # another character, or a login much later: not restored
    G.RestoreView(lua.eval("{ x = 5, y = 5, cont = 1, who = 'Player-2', t = 990 }"))
    G.RestoreView(lua.eval("{ x = 5, y = 5, cont = 1, who = 'Player-1', t = 1 }"))
    assert G.SaveView() is None


def test_road_tools_stay_on_until_toggled_off(router):
    lua, ns = router
    ns.Print = lua.eval("function() end")
    G = ns.GPS
    G.ToggleRoadMode()
    assert G.roadMode
    G.FinishRoad(lua.eval("{ pts = { 1, 1 }, cont = 1 }"))  # (a stroke too short: nothing saved, still on)
    assert G.roadMode
    G.ToggleRoadMode()
    assert not G.roadMode


def test_right_click_from_terrain_opens_the_continent_map_with_its_zones(nav_env):
    lua, ns = nav_env
    # (not the small overview maps 1463 / 1464 some continents also have)
    assert ns.GPS.ContinentMap(0) == 1415 and ns.GPS.ContinentMap(1) == 1414


def test_routes_go_around_the_other_factions_guards(router):
    lua, ns = router
    # Horde guards across the middle of the first leg; a road around them (drawn)
    ns.Hostile = lua.eval("{ [1] = { A = { 0, -500, 100 }, H = {} } }")
    ns.db = lua.eval("{ tracks = { { op = 'add', drawn = true, continent = 1, time = 1, "
                     "pts = { 0,-300, -400,-300, -400,-700, 0,-700 } } } }")
    lua.execute("FACTION = 'A'")
    ns.Nav = lua.eval("{ Faction = function() return FACTION end }")
    R = ns.Router
    R.Reset()
    assert R.HostileYards(1, 0, -300, 0, -700) == pytest.approx(200, abs=10)
    def passes_guards(r):
        pts = [(r.pts[i], r.pts[i + 1]) for i in range(1, len(r.pts), 2)]
        return any(abs(x) < 20 and -560 < y < -440 for x, y in pts) or any(
            abs(x1) < 1 and abs(x2) < 1 and min(y1, y2) < -500 < max(y1, y2)
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]))
    r = R.Route(1, 0.0, 30.0, 0.0, -1030.0, lua.table(offroad=False))
    assert not passes_guards(r)  # an Alliance character: around them
    lua.execute("FACTION = 'H'")
    r = R.Route(1, 0.0, 30.0, 0.0, -1030.0, lua.table(offroad=False))
    assert passes_guards(r)  # a Horde character: they're its own guards


def test_a_jog_off_the_line_and_back_is_straight_on(turns):
    lua, ns = turns
    # east 300 yd, a quick jog 25 yd north and back over 50 yd, then on east
    p = path_of(lua, ns, [(0, 0), (0, -300), (25, -325), (0, -350), (0, -700)], [1, 1, 1, 1])
    got, _ = maneuvers(lua, ns, p)
    assert [g[0] for g in got] == ["arrive"]


def test_route_smoothing_takes_out_a_jog(router):
    lua, ns = router
    R = ns.Router
    r = lua.eval("""{ pts = { 0,0, 0,-300, 20,-315, 0,-330, 0,-600 }, kinds = { 1, 1, 1, 1 }, length = 0, road = 0 }""")
    R.Smooth(1, r)
    pts = [(r.pts[i], r.pts[i + 1]) for i in range(1, len(r.pts), 2)]
    assert all(abs(x) < 1 for x, _ in pts)  # the jog north is gone
    assert pts[0] == (0, 0) and pts[-1] == (0, -600) and len(r.kinds) == len(pts) - 1
    # a real bend (not coming back) stays
    r = lua.eval("""{ pts = { 0,0, 0,-300, 30,-310, 200,-320 }, kinds = { 1, 1, 1 }, length = 0, road = 0 }""")
    R.Smooth(1, r)
    assert len(r.pts) >= 6 and any(r.pts[i] > 150 for i in range(1, len(r.pts), 2))


def test_an_s_bend_that_shifts_the_route_keeps_its_turns(turns):
    lua, ns = turns
    # east 300, north 50 (left), then east again (right): the route moved over 50 yd
    p = path_of(lua, ns, [(0, 0), (0, -300), (50, -300), (50, -700)], [1, 1, 1])
    got, _ = maneuvers(lua, ns, p)
    assert [g[0] for g in got] == ["turn", "turn", "arrive"]


def test_a_jog_on_hilly_ground_is_left_as_it_is(router):
    lua, ns = router
    load(lua, ns, "Passability.lua")
    R = ns.Router
    jog = """{ pts = { 0,0, 0,-300, 20,-315, 0,-330, 0,-600 }, kinds = { 1, 1, 1, 1 }, length = 0, road = 0 }"""
    # flat: the jog goes
    r = R.Smooth(1, lua.eval(jog))
    assert all(abs(r.pts[i]) < 1 for i in range(1, len(r.pts), 2))
    # hilly all around (12 x 12 cells of 100 yd, every one 1: "W" = a run of 12 ones)
    ns.Hills = lua.eval("{ [1] = { tx0 = 31, ty0 = 31, cell = 100, w = 12, h = 12, rows = { %s } } }"
                        % ", ".join(["'W'"] * 12))
    assert ns.Passability.Hilly(1, 20.0, -315.0)
    r = R.Smooth(1, lua.eval(jog))
    assert any(abs(r.pts[i]) > 10 for i in range(1, len(r.pts), 2))  # the winding stays


def test_ironforge_icon_opens_its_interior_map(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua", "Data/Interiors.lua")
    G = ns.GPS
    ids = {ns.Maps[k].name: k for k in ns.Maps.keys() if ns.Maps[k].type == 3}
    got = G.CityInterior(ids["Ironforge"])
    assert got is not None
    assert G.CityInterior(ids["Orgrimmar"]) is None and G.CityInterior(ids["Stormwind City"]) is None


def test_erasing_with_a_circle_takes_out_the_roads_inside_it(router):
    lua, ns = router
    import math as m
    loop = [v for k in range(13) for v in (500 + 40 * m.cos(k * m.pi / 6), -1000 + 40 * m.sin(k * m.pi / 6))]
    assert ns.GPS.IsLoop(lua.table(*loop), 250.0)
    assert not ns.GPS.IsLoop(lua.table(0, 0, 50, 0, 100, 0, 150, 0), 150.0)  # a line isn't
    ns.db = lua.eval("{ tracks = { { op = 'remove', drawn = true, area = true, continent = 1, time = 1, pts = { %s } } } }"
                     % ",".join(f"{v:.1f}" for v in loop))
    ns.Router.Reset()
    edges = ns.Router.Edges(1)[0]
    for e in edges.values():
        for i in range(5, len(e), 2):
            assert m.hypot(e[i] - 500, e[i + 1] + 1000) >= 38  # nothing left inside
    assert len(edges) == 3  # the leg cut in two, the other leg as it was


def test_road_data_text_to_copy_and_read_back(nav_env, tmp_path):
    lua, ns = nav_env
    lua.execute('GetBuildInfo = function() return "1.60.1", "70009" end')
    load(lua, ns, "Feedback.lua")
    ns.db = lua.eval("""{ tracks = {
      { op = 'add', continent = 0, time = 5, pts = { 1, 2, 3.25, 4 } },
      { op = 'remove', area = true, continent = 1, time = 6, pts = { 0,0, 10,0, 10,10, 0,10, 0,0 } } },
      feedback = { roads = { { op = 'add', continent = 0, time = 5, pts = { 1, 2, 3, 4 } } } } }""")
    text, n = ns.Feedback.RoadsText()
    assert n == 2  # (the one kept for sharing too, once)
    lines = text.split("\n")
    assert lines[0].startswith("AzerothGPS roads 1") and lines[1] == "R add 0 5 1.0,2.0 3.2,4.0" or lines[1] == "R add 0 5 1.0,2.0 3.3,4.0"
    from azerothgps.roads.tracks import import_shared, parse_shared
    got = parse_shared(text)
    assert [(t["op"], t["area"], t["continent"], t["time"]) for t in got] == [("add", False, 0, 5), ("remove", True, 1, 6)]
    per = {}
    assert import_shared(text, tmp_path, per) == 2 and per == {0: 1, 1: 1}
    assert import_shared(text, tmp_path) == 0  # already there


def test_a_drawn_wall_blocks_walking_but_not_roads(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua")
    P, R = ns.Passability, ns.Router
    # open ground in Durotar; a wall drawn across between two points
    a, b = (-950.0, -4050.0), (-950.0, -3900.0)
    assert P.SegmentCost(1, *a, *b) is not None
    ns.db = lua.eval("{ tracks = { { op = 'wall', drawn = true, continent = 1, time = 1, pts = { -1030,-3975, -870,-3975 } } } }")
    P.RefreshWalls()
    assert P.CrossesWall(1, *a, *b) and P.SegmentCost(1, *a, *b) is None
    c, path = P.FindPath(1, *a, *b)
    assert c is not None and c > 150  # round the wall's end
    pts = [(path[i], path[i + 1]) for i in range(1, len(path), 2)]
    assert not any(P.CrossesWall(1, *p, *q) for p, q in zip(pts, pts[1:]))
    # the wall isn't a road, and erasing it (a stroke along it) takes it out
    R.Reset()
    assert not any(e[4] == R.SOURCE_RECORDED for e in R.Edges(1)[0].values())
    lua.eval("function(db) db.tracks[2] = { op = 'unwall', drawn = true, continent = 1, time = 2, pts = { -1030,-3977, -870,-3976 } } end")(ns.db)
    P.RefreshWalls()
    assert not P.CrossesWall(1, *a, *b)


def test_walls_in_the_road_data_text(nav_env, tmp_path):
    lua, ns = nav_env
    lua.execute('GetBuildInfo = function() return "1.60.1", "70009" end')
    load(lua, ns, "Feedback.lua")
    ns.db = lua.eval("""{ tracks = {
      { op = 'wall', continent = 0, time = 5, pts = { 0,0, 50,0 } },
      { op = 'unwall', area = true, continent = 0, time = 6, pts = { 0,0, 10,0, 10,10, 0,10, 0,0 } } } }""")
    text, n = ns.Feedback.RoadsText()
    assert n == 2 and "R wall 0 5" in text and "R unwallarea 0 6" in text
    from azerothgps.roads.tracks import import_shared, walls
    assert import_shared(text, tmp_path) == 2
    assert walls(tmp_path) == {}  # (the wall is inside the erase loop)


# Floors over floors (reported: Undercity strokes drawn before they had a floor erased 222 pieces across
# floors): an edit changes the floor nearest the player's height under it, as recorded with it.
UC_STACK = (1593.5, 157.3)  # (a walkway at -43.5 over a road at -62, 2.3 yd apart: the game's heights)


def road_heights_near(lua, n, e, zs, x, y, r):
    """The heights of the roads in e within r of (x, y), at their nearest points."""
    out = []
    for i in range(1, len(e) + 1):
        ed = e[i]
        best, along = None, 0.0
        for k in range(5, len(ed) - 2, 2):
            ax, ay, cx, cy = ed[k], ed[k + 1], ed[k + 2], ed[k + 3]
            vx, vy = cx - ax, cy - ay
            L2 = vx * vx + vy * vy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2))
            d = math.hypot(ax + vx * t - x, ay + vy * t - y)
            if best is None or d < best[0]:
                best = (d, along + math.sqrt(L2) * t)
            along += math.sqrt(L2)
        if best and best[0] <= r:
            za, zb = zs[ed[1]], zs[ed[2]]
            h = za if zb is None else zb if za is None else za + (zb - za) * max(0.0, min(1.0, best[1] / max(ed[3], 1)))
            out.append(h)
    return out


def edges_near(g, x, y, r):
    """The roads of graph g (their numbers) with a point within r of (x, y)."""
    out = []
    for ei in range(1, len(g.e) + 1):
        ed = g.e[ei]
        for k in range(5, len(ed) - 2, 2):
            ax, ay, cx, cy = ed[k], ed[k + 1], ed[k + 2], ed[k + 3]
            vx, vy = cx - ax, cy - ay
            L2 = vx * vx + vy * vy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2))
            if math.hypot(ax + vx * t - x, ay + vy * t - y) <= r:
                out.append(ei)
                break
    return out


def uc_erase(lua, ns, UC, z):
    """Undercity's roads after a short erase stroke across UC_STACK, drawn at height z (None: no floor)."""
    x, y = UC_STACK
    t = lua.table(op="remove", continent=UC, time=1, pts=lua.table(x - 3, y - 3, x + 3, y + 3))
    if z is not None:
        t.z = z
    roads = ns.Roads[UC]
    n, e, zs = ns.Router.WithTracks(lua.table(n=roads.n, e=roads.e, z=roads.z), lua.table(t), UC)
    return road_heights_near(lua, n, e, zs, x, y, 3)


def test_an_undercity_erasure_takes_out_only_the_floor_it_was_drawn_on(nav_env):
    lua, ns, UC = undercity_env(nav_env)
    x, y = UC_STACK
    roads = ns.Roads[UC]
    before = road_heights_near(lua, roads.n, roads.e, roads.z, x, y, 3)
    assert any(abs(h + 62) < 1 for h in before) and any(abs(h + 43.5) < 1 for h in before)
    # (no floor: both, as before floors were recorded)
    assert not any(abs(h + 62) < 1 or abs(h + 43.5) < 1 for h in uc_erase(lua, ns, UC, None))
    # down on the lower road: it goes, the walkway over it stays
    low = uc_erase(lua, ns, UC, -61.0)
    assert not any(abs(h + 62) < 1 for h in low) and any(abs(h + 43.5) < 1 for h in low)
    # up on the walkway: it goes, the road under it stays
    high = uc_erase(lua, ns, UC, -44.0)
    assert any(abs(h + 62) < 1 for h in high) and not any(abs(h + 43.5) < 1 for h in high)


def test_a_floor_cut_first_doesnt_leave_the_floor_over_it_as_the_only_one(nav_env):
    # (the floors under an erasure are those before it: once the road down there was cut, the walkway
    # 3 yd over it was the only road near and went too; tests/test_roads.py has the same offline)
    lua, ns, UC = undercity_env(nav_env)
    roads = lua.eval("""{ n = { 0,0, 0,100, 3,0, 3,100 }, z = { 0, 0, 20, 20 },
      e = { { 1,2,100,0, 0,0, 0,50, 0,100 }, { 3,4,100,0, 3,0, 3,50, 3,100 } } }""")
    for z, gone in ((1.0, {0}), (19.0, {3})):
        t = lua.table(op="remove", continent=UC, time=1, z=z, pts=lua.table(-5, 50, 8, 50))
        n, e, zs = ns.Router.WithTracks(roads, lua.table(t), UC)
        cut = {x for x in (0, 3) if not edges_near(lua.table(e=e), x, 50, 0.5)}
        assert cut == gone, (z, cut)


def test_an_undercity_road_drawn_on_a_floor_joins_that_floor_at_its_height(nav_env):
    lua, ns, UC = undercity_env(nav_env)
    x, y = UC_STACK
    roads = ns.Roads[UC]
    # a road drawn from the spot out 30 yd, by someone down on the lower road: its end at the spot
    # joins the lower road (at -62), not the walkway 2 yd over it
    for z, want in ((-61.0, -62.0), (-44.0, -43.5)):
        t = lua.table(op="add", continent=UC, time=1, z=z, pts=lua.table(x, y, x + 20, y - 22))
        n, e, zs = ns.Router.WithTracks(lua.table(n=roads.n, e=roads.e, z=roads.z), lua.table(t), UC)
        mine = [e[i] for i in range(1, len(e) + 1) if e[i][4] == ns.Router.SOURCE_RECORDED]
        assert mine
        ends = [zs[ed[k]] for ed in mine for k in (1, 2)
                if math.hypot(n[2 * ed[k] - 1] - x, n[2 * ed[k]] - y) < 4]
        assert ends and all(h is not None and abs(h - want) < 2 for h in ends), (z, ends)


def test_down_in_the_cleft_an_erasure_takes_out_the_cleft_road_not_the_drag_over_it(nav_env):
    # (Orgrimmar's Cleft of Shadow under the Drag: a floor under the capital's, its roads a cave's)
    lua, ns, UC = undercity_env(nav_env)
    R = ns.Router
    x, y = 1672.0, -4302.0  # (a Cleft road 1.4 yd under a Drag street; split 15.5)
    v = R.CaveDown(1, x, y, None, 5.0), R.CaveDown(1, x, y, None, 30.0)
    assert v == (True, False)

    def after(z):
        R.Reset()
        t = lua.table(op="remove", continent=1, time=1, pts=lua.table(x - 2, y - 2, x + 2, y + 2))
        if z is not None:
            t.z = z
        ns.db.tracks = lua.table(t)
        edges, g = R.Edges(1)
        near = {True: 0, False: 0}
        for ei in edges_near(g, x, y, 2):
            near[bool(g.cave[ei])] += 1
        return near

    assert after(None) == {True: 0, False: 0} and after(5.0) != after(30.0)  # (no floor: both)
    ns.db.tracks = lua.table()
    R.Reset()
    edges, g = R.Edges(1)
    assert {bool(g.cave[ei]) for ei in edges_near(g, x, y, 2)} == {True, False}  # (both there before)
    down, up = after(5.0), after(30.0)
    assert down[True] == 0 and down[False] > 0
    assert up[True] > 0 and up[False] == 0
    ns.db.tracks = lua.table()
    R.Reset()


def test_a_road_drawn_down_in_the_cleft_and_the_cave_roads_it_splits_stay_the_caves(nav_env):
    # (the pieces of a cave's road a drawn road split were the land's: a route up top could start on
    # them); a road drawn down there is the cave's own
    lua, ns, UC = undercity_env(nav_env)
    R = ns.Router
    x, y = 1672.0, -4302.0
    R.Reset()
    ns.db.tracks = lua.table(lua.table(op="add", continent=1, time=1, z=5.0, pts=lua.table(x, y, x + 6, y + 9)))
    edges, g = R.Edges(1)
    mine = [ei for ei in range(1, len(g.e) + 1) if g.e[ei][4] == R.SOURCE_RECORDED]
    assert mine and all(g.cave[ei] for ei in mine)
    split = [ei for ei in edges_near(g, x, y, 0.5) if g.e[ei][4] != R.SOURCE_RECORDED]
    assert split and all(g.cave[ei] for ei in split)
    ns.db.tracks = lua.table()
    R.Reset()


def test_walls_on_floors_over_floors(nav_env):
    lua, ns, UC = undercity_env(nav_env)
    P, R = ns.Passability, ns.Router
    x, y = UC_STACK
    wall = lambda z, t: lua.table(op="wall", continent=UC, time=t, z=z, pts=lua.table(x - 6, y + 6, x + 6, y - 6))
    # a wall drawn down on the lower road cuts that road, not the walkway over it
    ns.db.tracks = lua.table(wall(-61.0, 1))
    P.RefreshWalls()
    R.Reset()
    edges, g = R.Edges(UC)
    hs = road_heights_near(lua, g.n, g.e, g.z, x, y, 1.5)
    assert not any(abs(h + 62) < 1 for h in hs) and any(abs(h + 43.5) < 1 for h in hs)
    # an eraser takes out the walls on its own floor only
    ns.db.tracks = lua.table(wall(-61.0, 1), wall(-44.0, 2),
                             lua.table(op="unwall", continent=UC, time=3, z=-44.0, pts=lua.table(x - 6, y + 6, x + 6, y - 6)))
    lines = P.WallLines(UC)
    assert len(lines) == 1 and lines[1].fl.z == -61.0
    ns.db.tracks = lua.table()
    P.RefreshWalls()
    R.Reset()


def test_the_road_tools_pick_the_floor_you_edit(nav_env):
    # (the game gives addons no player height: the floor edited is picked, Shift + mouse wheel) the
    # floors to pick from where the map is centered, and the other floor's roads faint
    lua, ns, UC = undercity_env(nav_env)
    G, R = ns.GPS, ns.Router
    x, y = UC_STACK
    edges, g = R.Edges(UC)
    floors = G.EditFloors(UC, x, y)
    zs = [floors[i].z for i in range(1, len(floors) + 1)]
    assert zs == sorted(zs) and len(zs) >= 2 and zs[0] < -50 and zs[-1] > -46  # (the road's floor, the walkway's)
    near = [ei for ei in edges_near(g, x, y, 3) if g.otherFloors[ei]]
    lo = next(ei for ei in near if abs(g.otherFloors[ei].h + 62) < 0.5)
    hi = next(ei for ei in near if abs(g.otherFloors[ei].h + 43.5) < 1)
    down, up = lua.table(z=-62.0), lua.table(z=-43.5)
    assert not G.OtherFloor(g, lo, UC, down) and G.OtherFloor(g, hi, UC, down)
    assert G.OtherFloor(g, lo, UC, up) and not G.OtherFloor(g, hi, UC, up)
    assert not G.OtherFloor(g, lo, UC, None)  # (none picked: all floors)


def test_floors_in_the_road_data_text_and_the_import(nav_env, tmp_path):
    lua, ns = nav_env
    lua.execute('GetBuildInfo = function() return "1.60.1", "70009" end')
    load(lua, ns, "Feedback.lua")
    ns.db = lua.eval("""{ tracks = {
      { op = 'remove', continent = 10001, time = 5, z = -61.04, indoors = true, pts = { 1, 2, 3, 4 } },
      { op = 'add', continent = 1, time = 6, z = 5, down = true, pts = { 1, 2, 3, 4 } } } }""")
    text, n = ns.Feedback.RoadsText()
    lines = text.split("\n")
    assert "R remove 10001 5 z=-61.0 indoors=1 1.0,2.0 3.0,4.0" in lines and "R add 1 6 z=5.0 down=1 1.0,2.0 3.0,4.0" in lines
    from azerothgps.roads.tracks import import_shared, load_overrides, parse_shared
    got = parse_shared(text)
    assert [(t.get("z"), t.get("indoors"), t.get("down")) for t in got] == [(-61.0, True, None), (5.0, None, True)]
    assert import_shared(text, tmp_path) == 2
    props = [f["properties"] for f in load_overrides(tmp_path / "roads_10001.geojson")["features"]]
    assert props[0]["z"] == -61.0 and props[0]["indoors"] is True


def test_zone_of_a_city_is_the_zone_around_it(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua", "Layers.lua")
    ids = {ns.Maps[k].name: k for k in ns.Maps.keys() if ns.Maps[k].type == 3}
    L = ns.Layers
    assert L.ZoneOf(ids["Undercity"]) == ids["Tirisfal Glades"]
    assert L.ZoneOf(ids["Durotar"]) == ids["Durotar"]


def test_quest_route_stops_in_a_city_still_go_in_the_fastest_order(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Data/Cities.lua")
    ns.settings = lua.eval("{ gps = { fastestOrder = true, cityKeepOrder = true } }")
    N = ns.Nav
    N.stops = lua.eval("{ { x = 1480, y = 280, cont = 10001 }, { x = 1590, y = 204, cont = 10001 } }")
    assert N.KeepCityOrder()  # placed by hand: your order
    N.stops = lua.eval("{ { x = 1480, y = 280, cont = 10001, questRoute = true }, { x = 1590, y = 204, cont = 10001, questRoute = true } }")
    assert not N.KeepCityOrder()  # the quest route: fastest


def test_the_city_order_is_kept_only_among_the_citys_own_stops(nav_env):
    # (reported) a stop outside the city with stops down in it: the whole route kept the order
    # placed. Now: the fastest order, the city's stops still in theirs among themselves.
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Data/Cities.lua")
    ns.settings = lua.eval("{ gps = { fastestOrder = true, cityKeepOrder = true } }")
    N = ns.Nav
    N.PlayerLevel = lua.eval("function(c) return c end")
    far, a, b = (2250.0, 280.0), (1480.0, 280.0), (1590.0, 204.0)  # Brill; two spots down in Undercity
    N.stops = lua.eval(f"{{ {{ x = {far[0]}, y = {far[1]}, cont = 0, name = 'brill' }}, "
                       f"{{ x = {b[0]}, y = {b[1]}, cont = 10001, name = 'b' }}, {{ x = {a[0]}, y = {a[1]}, cont = 10001, name = 'a' }} }}")
    assert not N.KeepCityOrder()
    N.OrderStops(1570.0, 230.0, 10001)
    names = [N.stops[i].name for i in range(1, len(N.stops) + 1)]
    assert names.index("b") < names.index("a")  # (b placed before a: still so)
    assert names[-1] == "brill"  # (Brill's the far one: last)
    N.stops = lua.eval(f"{{ {{ x = {b[0]}, y = {b[1]}, cont = 10001 }}, {{ x = {a[0]}, y = {a[1]}, cont = 10001 }} }}")
    assert N.KeepCityOrder()  # (all down in the city: your order)


def test_undercity_flight_master_is_down_in_the_city(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Pois.lua")
    fm = [ns.Pois[0][i] for i in range(1, len(ns.Pois[0]) + 1)
          if ns.Pois[0][i][1] == 1 and ns.Pois[0][i][4] == "Undercity, Tirisfal"]
    assert fm and fm[0][7] == 10001
    others = [ns.Pois[0][i] for i in range(1, len(ns.Pois[0]) + 1) if ns.Pois[0][i][1] == 1 and ns.Pois[0][i][7]]
    assert len(others) == 1  # (only it)


def test_flying_from_undercity_starts_at_its_flight_master_down_in_the_city(nav_env):
    lua, ns = flights_env(nav_env, [11, 17])  # Undercity, Hammerfall
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua")
    ns.Nav.FlightsChanged()
    lua.execute("function AGPS_STOP(x, y) return { x = x, y = y, cont = 0 } end")
    # in the Trade Quarter, down in the city, a few yards from the bat handler
    legs, secs = ns.Nav.Plan(10001, 1585.0, 280.0, 7.0, lua.eval("AGPS_STOP")(-910.0, -3490.0))
    kinds = [("ride " + str(legs[i].ride[8])) if legs[i].ride else "walk" for i in range(1, len(legs) + 1)]
    assert kinds[:2] == ["walk", "ride flight"]  # straight to the flight master: no lift first


def test_a_flight_from_undercity_is_drawn_over_the_land(nav_env):
    # (reported: the flight's dotted line gone) its flight master is down in the city, so the
    # flight's part was on the city's level, which the map doesn't draw while the player is up top
    lua, ns = flights_env(nav_env, [11, 17])  # Undercity, Hammerfall
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua")
    ns.Router.Reset()
    ns.Router.SYNC_WALKS = True
    N = ns.Nav
    N.FlightsChanged()
    N.SetDestination(-910.0, -3490.0, 0, "Hammerfall")
    r = N.Route(2250.0, 280.0, 0)  # Brill: up on the land
    flights = [r.parts[i] for i in range(1, len(r.parts) + 1)
               if r.parts[i].kinds and len(r.parts[i].pts) >= 4 and r.parts[i].kinds[1] == N.KIND_TRANSPORT
               and (r.parts[i].pts[1] - r.parts[i].pts[len(r.parts[i].pts) - 1]) ** 2 > 100]
    assert flights and all(f.cont == 0 for f in flights)


def test_the_route_tour_stays_on_the_terrain_view(env):
    # (reported, a recording) a long route's overview zoomed out past the terrain's tiles, and the
    # zone maps' art took over halfway through the zoom: the terrain view stops at its tiles
    lua, ns = env
    G = ns.GPS
    G.Follow()
    ns.settings = lua.eval("{ gps = { style = 'minimap', zoom = 300 } }")
    assert G.TourZoom(9000.0) < G.MINIMAP_MAX_ZOOM and G.TourZoom(800.0) == 800.0
    ns.settings.gps.style = "zone"  # (the map style: its maps, all of the route)
    assert G.TourZoom(9000.0) == 9000.0


def test_show_walls_outlines_the_mountains(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua")
    G, P = ns.GPS, ns.Passability
    # Durotar's hills around Razor Hill: blocked and open ground both near
    e = G.BlockEdges(1, 300.0, -4700.0, 300.0)
    n = len(e) // 4
    assert n > 10
    # each border lies between a blocked and an open sample
    for k in range(0, min(n, 50)):
        ax, ay, bx, by = e[4 * k + 1], e[4 * k + 2], e[4 * k + 3], e[4 * k + 4]
        mx, my = (ax + bx) / 2, (ay + by) / 2
        if ax == bx:  # (a border across x)
            sides = {P.At(1, mx - 4, my) == 2, P.At(1, mx + 4, my) == 2}
        else:
            sides = {P.At(1, mx, my - 4) == 2, P.At(1, mx, my + 4) == 2}
        assert sides == {True, False}
    assert lua.eval("rawequal")(G.BlockEdges(1, 300.0, -4700.0, 300.0), e)  # (kept while the view stays near)


def test_a_wall_along_the_ruins_edge_closes_it(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua")
    P = ns.Passability
    ns.Walls = lua.eval("{}")  # (not the shipped ones: the player may have changed them)
    ns.db = lua.eval("{ tracks = { { op = 'wall', drawn = true, continent = 0, time = 1, pts = { 1380,400, 1380,90 } } } }")
    P.RefreshWalls()
    # (from the Ruins' courtyard straight out over the lake: not that way)
    assert P.CrossesWall(0, 1420.0, 240.0, 1330.0, 240.0)
    assert P.SegmentCost(0, 1420.0, 240.0, 1330.0, 240.0) is None


def test_a_drawn_wall_cuts_the_road_it_crosses(router):
    lua, ns = router
    load(lua, ns, "Passability.lua")
    P, R = ns.Passability, ns.Router
    # a wall across the second leg (B (0,-1000) -> C (1000,-1000)) at x = 500
    ns.db = lua.eval("{ tracks = { { op = 'wall', drawn = true, continent = 1, time = 1, pts = { 500,-1100, 500,-900 } } } }")
    P.RefreshWalls()
    R.Reset()
    edges = R.Edges(1)[0]
    for e in edges.values():
        pts = [(e[i], e[i + 1]) for i in range(5, len(e), 2)]
        assert not any(P.CrossesWall(1, *a, *b) for a, b in zip(pts, pts[1:]))
    assert len(edges) == 3  # the first leg, and the second in two


def test_the_wall_eraser_opens_the_terrain_under_it(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua")
    P = ns.Passability
    # a blocked spot in Durotar's hills near Razor Hill
    spot = next((x, y) for x in range(0, 600, 10) for y in range(-5000, -4400, 10) if P.At(1, float(x), float(y)) == 2)
    x, y = spot
    loop = ",".join(f"{x + dx},{y + dy}" for dx, dy in ((-20, -20), (20, -20), (20, 20), (-20, 20), (-20, -20)))
    ns.db = lua.eval("{ tracks = { { op = 'unwall', area = true, drawn = true, continent = 1, time = 1, pts = { %s } } } }" % loop)
    P.RefreshWalls()
    assert P.At(1, float(x), float(y)) == 0 and P.IsOpen(1, float(x), float(y))
    # a wall drawn over it closes it again (walls win)
    lua.eval("function(db) db.tracks[2] = { op = 'wall', drawn = true, continent = 1, time = 2, pts = { %s,%s, %s,%s } } end"
             % (x - 30, y, x + 30, y))(ns.db)
    P.RefreshWalls()
    assert P.At(1, float(x), float(y)) == 2


def test_waiting_counts_roads_and_walls_apart(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Feedback.lua")
    ns.db = lua.eval("""{ tracks = { { op = 'add', time = 1 }, { op = 'remove', time = 2 },
      { op = 'wall', time = 3 }, { op = 'unwall', time = 4 }, { op = 'wall', time = 5 } } }""")
    ns.RoadTracksIn = lua.eval("{ [5] = true }")  # (that one's in the data now)
    assert tuple(ns.Feedback.DrawnCounts()) == (2, 2)


def test_height_hint_is_about_the_next_ride_when_one_comes_first(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua")
    N = ns.Nav
    lua.execute("AGPS_CHAR = {} GetSubZoneText = function() return 'Trade Quarter' end")
    ns.CharDB = lua.eval("function() return AGPS_CHAR end")
    ns.Geo.PlayerMap = lua.eval("function() return 1458 end")
    # the stop is up top (a surface quest turn-in); the next thing is a flight boarded down here
    N.dest = lua.eval("{ x = 2000, y = 300, cont = 0 }")
    N.route = lua.eval("{ legs = { { walk = true }, { ride = { 10001, 1569, 268, 0, -916, -3497, 60, 'flight' }, from = 1 } } }")
    way = N.HeightHint(1596.0, 266.0, 10001)
    assert way != "up" or N.HeightText(1596.0, 266.0, 10001).find("lift") == -1  # not "up a lift" for the flight master


def test_nothing_to_share_once_the_data_has_it(nav_env):
    lua, ns = nav_env
    lua.execute('GetBuildInfo = function() return "1.60.1", "70009" end')
    load(lua, ns, "Feedback.lua", "Record.lua")
    ns.Print = lua.eval("function() end")
    ns.db = lua.eval("""{ tracks = { { op = 'add', continent = 0, time = 5, pts = { 0,0, 50,0 } } },
      feedback = { roads = { { op = 'add', continent = 0, time = 5, pts = { 0,0, 50,0 } },
                             { op = 'wall', continent = 0, time = 6, pts = { 0,0, 0,50 } } }, trips = {} } }""")
    ns.RoadTracksIn = lua.eval("{ [5] = true }")  # (road 5 is in the data now)
    text, n = ns.Feedback.RoadsText()
    assert n == 1 and "R wall 0 6" in text and "R add 0 5" not in text
    assert tuple(ns.Feedback.Counts())[0] == 1 and tuple(ns.Feedback.DrawnCounts()) == (0, 0)
    ns.Record.Prune()
    assert len(ns.db.tracks) == 0 and len(ns.db.feedback.roads) == 1


def test_a_stroke_drawn_elsewhere_from_down_in_a_city_is_on_the_continent(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Cities.lua", "Record.lua")
    ns.Print = lua.eval("function() end")
    lua.execute("C_Map = C_Map or {} C_Map.GetBestMapForUnit = function() return 1458 end C_Map.GetMapInfo = function() return { name = 'Undercity' } end time = function() return 1 end")
    ns.Nav.PlayerLevel = lua.eval("function(c) return 10001 end")  # (the player is down in Undercity)
    ns.GPS.shownLevel, ns.GPS.shownCont = 10001, 0  # (its map shown)
    ns.db = lua.eval("{ tracks = {} }")
    # looking at Duskwood from there, a road drawn
    ns.GPS.FinishRoad(lua.eval("{ cont = 0, pts = { -10900,400, -10880,450, -10860,500 } }"))
    assert ns.db.tracks[1].continent == 0
    # drawn over the city itself: on its level
    ns.GPS.FinishRoad(lua.eval("{ cont = 0, pts = { 1560,250, 1570,270, 1590,280 } }"))
    assert ns.db.tracks[2].continent == 10001


@pytest.fixture
def api(env):
    lua, ns = env
    load(lua, ns, "Api.lua")
    return lua, ns, lua.globals().AzerothGPS


def test_api_places_zephras_isle_on_its_world_map_inset(api):
    # (StreetView asked) a spot on Zephras Isle, on the world view in another continent's
    # coordinates: on the isle's inset there, not nil
    lua, ns, A = api
    load(lua, ns, "Data/Maps.lua")
    assert A.version >= 7
    b = ns.Maps[2521].bounds
    cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
    x, y = A.ToContinent(2991, cx, cy, 0)
    it = ns.GPS.WORLD_INSETS[1]
    ib = ns.GPS.InsetBounds(it, ns.Geo.WorldArtBounds(0))
    assert ib[1] < x < ib[3] and ib[2] < y < ib[4]
    assert abs(x - (ib[1] + ib[3]) / 2) < 1 and abs(y - (ib[2] + ib[4]) / 2) < 1  # (the isle's middle: the inset's)
    x2, _ = A.ToContinent(2991, b[3], cy, 0)  # (its north edge: the inset's top)
    assert abs(x2 - ib[3]) < 1
    assert A.ToContinent(0, 1600.0, 240.0, 2991) is None  # (the other way: none)


def multi(lua, f, *args):
    """All the values a Lua function returns (lupa keeps only the first)."""
    t = lua.eval("function(f, ...) return { f(...) } end")(f, *args)
    return tuple(t[i] for i in range(1, len(t) + 1))


def test_public_api_exposes_documented_functions(api):
    lua, ns, A = api
    for name in ("Instance", "InstanceFloors", "PlayerWorld", "Facing", "BaseContinent", "LocateWorld", "MapToWorld", "Roads",
                 "NearestRoad", "RoadEdge", "MapFrame", "MapCanvas", "MapButtonParent", "MapShown",
                 "View", "CursorWorld", "WorldToMap", "SetOverlay", "ShowRoads", "Redraw", "MapButton",
                 "HoldMap", "LookAt", "Follow", "ShowMap", "TopPanelInset", "OnLayout", "ShowWorld", "ToContinent"):
        assert A[name] is not None, name
    assert A.version == 10
    assert A.TopPanelInset() == 4  # (no window frame in the tests)
    assert A.MapButton("recenter") is None  # (no map built in the tests)


def test_public_api_hold_map_takes_double_clicks_until_let_go(api):
    lua, ns, A = api
    G = ns.GPS
    got = lua.eval("{}")
    click = lua.eval("function(t) return function(x, y, c) t.x, t.y, t.c = x, y, c end end")(got)
    assert not G.Held()
    A.HoldMap("game", True, click)
    assert G.Held()
    assert G.HeldClick(10, 20, 1) is True
    assert (got.x, got.y, got.c) == (10, 20, 1)
    A.HoldMap("game", False)
    assert not G.Held()
    assert G.HeldClick(1, 2, 0) is False


def test_a_held_map_style_overrides_the_setting_until_let_go(api):
    # (StreetView asked, API 9: a game's difficulty locks every player's map style) a holder's style is
    # what the map draws, the setting untouched; holding again updates it; letting go brings the player's
    # own back; no style, as before
    lua, ns, A = api
    G = ns.GPS
    ns.settings = lua.eval('{ gps = { style = "minimap", zoom = 300 } }')
    assert G.Style() == "minimap"
    A.HoldMap("game", True, None, lua.eval('{ style = "zone" }'))
    assert G.Style() == "zone" and G.HeldStyle() == "zone" and ns.settings.gps.style == "minimap"
    assert G.IsMapStyle(G.Style())
    A.HoldMap("game", True, None, lua.eval('{ style = "unrevealed" }'))  # (a joiner learns the level a moment later)
    assert G.Style() == "unrevealed" and G.IsMapStyle("unrevealed")
    A.HoldMap("game", True, None, lua.eval('{ style = "sideways" }'))  # (not a style: none held)
    assert G.Style() == "minimap"
    A.HoldMap("game", True, None, lua.eval('{ style = "minimap" }'))
    ns.settings.gps.style = "zone"
    assert G.Style() == "minimap"  # (held: the terrain view, whatever the player picked)
    A.HoldMap("game", False)
    assert G.Style() == "zone" and G.HeldStyle() is None
    A.HoldMap("game", True)  # (no opts: today's behavior)
    assert G.Style() == "zone"
    A.HoldMap("game", False)


def test_the_unrevealed_style_draws_no_explored_areas(api):
    # (API 9) "unrevealed": the world map's base art only, no area overlays at all (the same for every
    # character); "zone" all of them
    lua, ns, A = api
    load(lua, ns, "Data/Maps.lua")
    G = ns.GPS
    mid = next(k for k in sorted(ns.Maps.keys()) if ns.Maps[k].overlays and len(ns.Maps[k].overlays) > 0
               and ns.Maps[k].tiles and ns.Maps[k].bounds)
    b = ns.Maps[mid].bounds
    cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
    zoom = max(b[3] - b[1], b[4] - b[2])
    n = {style: len(G.LayoutZone(cx, cy, mid, 0, zoom, 200, None, G.SpoilerMode(style)))
         for style in ("zone", "unrevealed")}
    tiles = lua.eval("function(G, m, x, y, z) local t = G.LayoutZone(x, y, m, 0, z, 200, nil, 'none') return #t end")
    assert G.SpoilerMode("unrevealed") == "none" and G.SpoilerMode("nospoiler") is True and not G.SpoilerMode("zone")
    assert 0 < n["unrevealed"] < n["zone"], n
    assert n["unrevealed"] == tiles(G, mid, cx, cy, zoom)

def test_api_saves_and_restores_the_whole_view(api):
    # (StreetView asked: a game ending put a browsed continent or world map back as a zoomed-out
    # terrain view) the view as it was: a continent's map, the world map, following the player
    lua, ns, A = api
    load(lua, ns, "Data/Maps.lua")
    ns.settings = lua.eval("{ gps = { zoom = 300 } }")
    lua.execute("time = os.time")
    G = ns.GPS
    browsing = lua.eval("function(G) local b = G.BrowseState() return b end")
    following = lua.eval("function(G) local b, f = G.BrowseState() return b == nil and f == nil end")
    kalimdor = G.ContinentMap(1)
    world = next(k for k in ns.Maps.keys() if ns.Maps[k].worldFrames)
    for mid in (kalimdor, world):
        G.Browse(mid, 1)
        state = A.SaveView()
        A.LookAt(0, 1600.0, 240.0, 3000.0)
        assert browsing(G) != mid
        A.RestoreView(state)
        assert browsing(G) == mid, mid
    G.Follow()
    state = A.SaveView()
    assert state.follow
    A.LookAt(0, 1600.0, 240.0, 3000.0)
    A.RestoreView(state)
    assert following(G)
    A.RestoreView(None)  # (none: following)
    A.RestoreView(lua.eval("{ x = 1, y = 2, instance = 99999 }"))  # (a dungeon no longer there: following)
    assert following(G)


def test_no_docks_or_dungeon_entrances_while_the_map_is_held(api):
    # (StreetView asked: during its game, the zeppelins', boats' and dungeons' markers hidden)
    lua, ns, A = api
    G = ns.GPS
    assert G.ShowsTravelMarkers()
    A.HoldMap("StreetGuess", True)
    assert not G.ShowsTravelMarkers()
    A.HoldMap("StreetGuess", False)
    assert G.ShowsTravelMarkers()


def test_no_road_or_wall_tools_while_the_map_is_held(api):
    lua, ns, A = api
    G = ns.GPS
    said = lua.eval("{}")
    ns.Print = lua.eval("function(t) return function(msg) t[#t + 1] = msg end end")(said)
    G.SetRoadMode(True)
    assert G.roadMode
    A.HoldMap("game", True, None)  # (a game on the map starts)
    assert not G.roadMode and not G.wallMode  # (turned off)
    assert G.SetRoadMode(True) is False and not G.roadMode  # (refused while held, and said why)
    assert G.SetWallMode(True) is False and not G.wallMode
    assert G.StartDrawing("farm") is False and not G.drawMode
    assert said[len(said)] == "not during a game on the map"
    ns.settings = lua.eval("{ gps = { showWalls = true } }")
    assert G.ShowsWalls() is False  # (no wall outlines over the game's map)
    A.HoldMap("game", False)
    assert G.ShowsWalls() is True and ns.settings.gps.showWalls  # (the option untouched)
    assert not G.roadMode  # (not back by itself)
    G.SetRoadMode(True)  # (turned on again after the game: fine)
    assert G.roadMode
    G.SetRoadMode(False)


def test_nearest_road_waits_for_the_background_build(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Api.lua")
    A, R = lua.globals().AzerothGPS, ns.Router
    R.WARM = True  # (as in game: the roads built in the background after a /reload)
    assert A.NearestRoad(1, -600.0, -4400.0) is None  # not built in this frame
    clock = lua.eval("function() return os.clock() * 1000 end")
    while R.HasWork():
        R.Pump(clock() + 200, clock)
    x, y, dist, edge = multi(lua, A.NearestRoad, 1, -600.0, -4400.0)
    assert dist is not None and dist < 200


def test_public_api_to_continent_goes_there_and_back(api):
    lua, ns, A = api
    load(lua, ns, "Data/Maps.lua")
    x, y = multi(lua, A.ToContinent, 0, -9000.0, 400.0, 1)  # Eastern Kingdoms, in Kalimdor's coordinates
    assert (x, y) != (-9000.0, 400.0)
    assert multi(lua, A.ToContinent, 1, x, y, 0) == pytest.approx((-9000.0, 400.0))
    assert multi(lua, A.ToContinent, 0, 5.0, 6.0, 0) == (5.0, 6.0)


def test_public_api_map_to_world_inverts_locate(api):
    lua, ns, A = api
    ns.Maps = lua.eval("{ [1411] = { name = 'Durotar', type = 3, continent = 1,"
                       " bounds = { -1716.67, -7250, 1808.33, -1962.5 } } }")
    mapID, name, u, v = multi(lua, A.LocateWorld, 1, -568.5, -4436.9)
    assert mapID == 1411 and name == "Durotar"
    assert (u, v) == pytest.approx((0.46797, 0.67428), abs=1e-4)
    x, y, cont = multi(lua, A.MapToWorld, 1411, u, v)
    assert (x, y, cont) == pytest.approx((-568.5, -4436.9, 1))


def test_public_api_world_to_map_and_forced_roads(api):
    lua, ns, A = api
    # The initial view: centered on (0, 0), north up, 1 UI unit per yard.
    dx, dy = multi(lua, A.WorldToMap, 10.0, -5.0)  # 10 yd north, 5 yd east
    assert (dx, dy) == pytest.approx((5.0, 10.0))
    assert ns.GPS.ForcedRoadColor() is None
    A.ShowRoads("sv", True, lua.eval("{ 0, 0, 1 }"))
    c = ns.GPS.ForcedRoadColor()
    assert [c[1], c[2], c[3]] == [0, 0, 1]
    A.ShowRoads("sv", False)
    assert ns.GPS.ForcedRoadColor() is None
    A.SetOverlay("sv", lua.eval("function(ctx) end"))
    assert ns.GPS.overlays["sv"] is not None
    A.SetOverlay("sv", None)
    assert ns.GPS.overlays["sv"] is None


def test_terrain_view_city_icons_are_the_cities_with_an_inside_map(env):
    lua, ns = env
    load(lua, ns, "Data/Maps.lua", "Data/Interiors.lua")
    names = {c.name for c in ns.GPS.InteriorCities(0).values()}
    assert {"Ironforge", "Undercity"} <= names and "Stormwind City" not in names


def test_no_u_turn_to_the_road_while_a_walk_around_is_searched(env):
    # Tirisfal, a corpse run: the body ~95 yd south, a small steep patch on the straight line.
    # While the walk around it was searched the route went back north to the road (a 284 yd
    # U-turn), and every step started the search over, so it stayed that way.
    lua, ns, at = tirisfal_env(env)
    R = ns.Router
    px, py, bx, by = 2192.7, 430.5, 2099.7, 409.5
    assert ns.Passability.SegmentCost(0, px, py, bx, by) is None  # (blocked in a straight line)
    R.Reset()
    R.SYNC_WALKS = False
    now = lua.eval("function() return os.clock() * 1000 end")
    try:
        for offroad in (True, False):
            R.Reset()
            opts = lua.table(offroad=offroad, transient=True)
            r = R.Route(0, px, py, bx, by, opts)
            assert r.pending and r.length < 130  # meanwhile: about straight, not the long way round
            while R.HasWork():
                R.Pump(now() + 50, now)
            r = R.Route(0, px, py, bx, by, opts)
            assert not r.pending and r.length < 130
            # a few yards on: the walk found is joined, not searched again
            r = R.Route(0, px - 4, py - 3, bx, by, opts)
            assert not r.pending and r.length < 130 and not R.HasWork()
    finally:
        R.SYNC_WALKS = True


def test_routes_keep_out_of_zones_too_high_for_the_player(nav_env):
    # Level 13 from Brill to Tarren Mill: not over Alterac Mountains (30-40, red for them) but
    # by Silverpine; Hillsbrad (the destination's zone) is fine. At 60, the short way.
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Zones.lua", "GPSFrame.lua")
    R = ns.Router
    R.Reset()
    R.SYNC_WALKS = True
    ns.settings = lua.eval("{ gps = {} }")

    def zone(name):
        return next(k for k in ns.Maps.keys() if ns.Maps[k].name == name and ns.Maps[k].type == 3)

    def at(name, u, v):
        b = ns.Maps[zone(name)].bounds
        return b[3] - v / 100 * (b[3] - b[1]), b[4] - u / 100 * (b[4] - b[2])

    (sx, sy), (tx, ty) = at("Tirisfal Glades", 61, 52), at("Hillsbrad Foothills", 61, 20)
    alterac = zone("Alterac Mountains")
    assert R.ZoneAt(0, sx, sy) == zone("Tirisfal Glades") and R.ZoneAt(0, tx, ty) == zone("Hillsbrad Foothills")

    def through(r, z):
        pts = [r.pts[i] for i in range(1, len(r.pts) + 1)]
        yd = 0
        for i in range(0, len(pts) - 3, 2):
            yd += (R.ZoneYards(0, pts[i], pts[i + 1], pts[i + 2], pts[i + 3])[z] or 0)
        return yd

    for offroad in (False, True):
        opts = lua.table(offroad=offroad)
        lua.execute("UnitLevel = function() return 60 end")
        high = R.Route(0, sx, sy, tx, ty, opts)
        assert through(high, alterac) > 500  # (the short way: over the mountains)
        lua.execute("UnitLevel = function() return 13 end")
        low = R.Route(0, sx, sy, tx, ty, opts)
        assert through(low, alterac) < 50 and through(low, zone("Silverpine Forest")) > 1000
        ns.settings.gps.avoidHighZones = False  # (the option off: the short way again)
        assert through(R.Route(0, sx, sy, tx, ty, opts), alterac) > 500
        ns.settings.gps.avoidHighZones = None


def test_a_stop_in_a_zone_too_high_is_confirmed_first(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Zones.lua", "GPSFrame.lua")
    N, R = ns.Nav, ns.Router
    ns.settings = lua.eval("{ gps = {} }")
    ns.Print = lua.eval("function() end")

    def at(name, u, v):
        k = next(k for k in ns.Maps.keys() if ns.Maps[k].name == name and ns.Maps[k].type == 3)
        b = ns.Maps[k].bounds
        return b[3] - v / 100 * (b[3] - b[1]), b[4] - u / 100 * (b[4] - b[2])

    brill, tarren = at("Tirisfal Glades", 61, 52), at("Hillsbrad Foothills", 61, 20)
    lua.execute("UnitLevel = function() return 13 end")
    lua.execute(f"UnitPosition = function() return {brill[0]}, {brill[1]}, 0, 0 end")
    lua.execute("StaticPopupDialogs = {}; ASKED = nil; StaticPopup_Show = function(which, text, _, data) ASKED = { text = text, data = data } end")
    stop = lua.table(x=tarren[0], y=tarren[1], cont=0, name="Tarren Mill")
    ok, asked = N.SetStops(lua.table(stop))
    assert ok is False and asked and len(N.stops) == 0  # not yet: asked first
    popup = lua.eval("ASKED")
    assert "Tarren Mill is in Hillsbrad Foothills (level 20-30)" in popup.text and "your level 13" in popup.text
    popup.data[1]()  # Yes
    assert len(N.stops) == 1 and N.stops[1].name == "Tarren Mill"
    N.Clear()
    lua.execute("ASKED = nil")
    # No: nothing set (the popup just closes)
    N.SetStops(lua.table(stop))
    assert lua.eval("ASKED") is not None and len(N.stops) == 0
    # adding one to a route: asked the same way
    lua.execute("ASKED = nil")
    N.SetStops(lua.table(lua.table(x=brill[0] + 50, y=brill[1], cont=0, name="Brill")))
    assert lua.eval("ASKED") is None and len(N.stops) == 1  # (in the player's level: no question)
    ok, asked = N.AddStop(stop)
    assert not ok and asked and len(N.stops) == 1
    lua.eval("ASKED").data[1]()
    assert len(N.stops) == 2
    # the player in that zone already, or the option off: no question
    N.Clear()
    lua.execute("ASKED = nil")
    lua.execute(f"UnitPosition = function() return {tarren[0] + 30}, {tarren[1]}, 0, 0 end")
    assert N.SetStops(lua.table(stop)) and lua.eval("ASKED") is None
    N.Clear()
    lua.execute(f"UnitPosition = function() return {brill[0]}, {brill[1]}, 0, 0 end")
    ns.settings.gps.avoidHighZones = False
    assert N.SetStops(lua.table(stop)) and lua.eval("ASKED") is None


def test_zeppelin_timetable_learned_from_a_ride(env):
    # Brill's zeppelin to Durotar: standing on the tower, then carried off it without walking
    # (aboard): that departure, and the cycle, give every later arrival and departure.
    lua, ns = env
    lua.execute("GetRealmName = function() return 'Test' end")
    lua.execute("CreateFrame = function() return { RegisterEvent = function() end, SetScript = function() end } end")
    ns.db = lua.eval("{}")
    load(lua, ns, "Data/Transports.lua", "Taxi.lua")
    T = ns.Taxi
    i = next(k for k in range(1, len(ns.Transports) + 1)
             if ns.Transports[k][9] == "Jaggedswine Farm, Durotar" and ns.Transports[k][10] == "Brill, Tirisfal Glades")
    t = ns.Transports[i]
    bx, by = t[5], t[6]  # the Brill end (side 2)
    assert T.DockAt(0, bx + 10, by) == (i, 2)
    assert T.TransportTimes(i, 2, 1000) is None  # never seen
    # waiting on the tower (walking about a little), then aboard: carried off at 10 yd/s
    now, server = 0.0, 5000
    T.TransportTick(now, server, bx + 12, by, 0, 7.0)
    T.TransportTick(now + 0.5, server, bx + 12, by, 0, 0.0)  # (standing: not carried yet)
    x = bx + 12
    for k in range(1, 20):
        x += 5
        T.TransportTick(now + 0.5 + k * 0.5, server + 10 + k // 2, x, by, 0, 0.0)
    seen = T.Sightings()[f"{t[9]} | {t[10]}"]
    assert seen.side == 2 and seen.at == 5010  # (left when the carrying began)
    # a cycle later: it leaves Brill again right then; it's at Durotar after the ride there
    arr, dep, age = T.TransportTimes(i, 2, 5010 + t.cycle - 30)
    assert dep == pytest.approx(30, abs=0.01) and arr == pytest.approx((30 - t.wait2) % t.cycle, abs=0.01)
    arr1, dep1, _ = T.TransportTimes(i, 1, 5010 + 1)
    assert arr1 == pytest.approx(t.ride2 - 1, abs=0.01)  # (Brill to Durotar: ride2, dock 2 round to 1)
    assert dep1 == pytest.approx(t.ride2 + t.wait1 - 1, abs=0.01)
    # walking off the tower down the stairs isn't a departure
    T2 = T.Sightings()
    T2[f"{t[9]} | {t[10]}"] = None
    for k in range(20):
        T.TransportTick(100 + k * 0.5, 9000 + k, bx + 10 + k * 4, by, 0, 7.0)
    assert T.Sightings()[f"{t[9]} | {t[10]}"] is None


def test_boats_and_zeppelins_only_of_the_players_faction(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Hostile.lua")
    N = ns.Nav

    def row(a, b):
        return next(ns.Transports[k] for k in range(1, len(ns.Transports) + 1)
                    if ns.Transports[k][9] == a and ns.Transports[k][10] == b)

    zep = row("Jaggedswine Farm, Durotar", "Brill, Tirisfal Glades")
    menethil = row("Menethil Harbor, Wetlands", "Theramore Isle, Dustwallow Marsh")
    booty = row("Ratchet, The Barrens", "Booty Bay, Stranglethorn Vale")
    store = lua.eval("{}")
    ns.CharDB = lua.eval("function(s) return function() return s end end")(store)
    store.faction = "Horde"
    assert N.TransportUsable(zep) and not N.TransportUsable(menethil) and N.TransportUsable(booty)
    store.faction = "Alliance"
    assert not N.TransportUsable(zep) and N.TransportUsable(menethil) and N.TransportUsable(booty)
    # planning: an Alliance character from Brill to Orgrimmar isn't put on the zeppelin
    d = lua.table(cont=1, x=1600.0, y=-4400.0)
    legs = N.Plan(0, 2066.0, 290.0, 7.0, d)
    legs = legs[0] if isinstance(legs, tuple) else legs
    rides = [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride] if legs else []
    assert all(r[9] != "Jaggedswine Farm, Durotar" and r[10] != "Brill, Tirisfal Glades" for r in rides)
    store.faction = "Horde"
    legs = N.Plan(0, 2066.0, 290.0, 7.0, d)[0]
    assert any(legs[i].ride and legs[i].ride[10] == "Brill, Tirisfal Glades" for i in range(1, len(legs) + 1))


def test_stormwind_to_ironforge_takes_the_deeprun_tram_for_the_alliance(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Hostile.lua")
    N = ns.Nav
    store = lua.eval("{}")
    ns.CharDB = lua.eval("function(s) return function() return s end end")(store)
    d = lua.table(cont=0, x=-4900.0, y=-1100.0)  # Ironforge
    store.faction = "Alliance"
    legs, secs = N.Plan(0, -8500.0, 600.0, 7.0, d)  # Stormwind's Dwarven District
    rides = [legs[i].ride for i in range(1, len(legs) + 1) if legs[i].ride]
    assert len(rides) == 1 and rides[0][8] == "tram" and rides[0][10] == "Ironforge"
    assert secs < 8 * 60
    # the Horde doesn't ride it (both its ends in Alliance cities)
    store.faction = "Horde"
    legs, _ = N.Plan(0, -8500.0, 600.0, 7.0, d)
    assert not any(legs[i].ride and legs[i].ride[8] == "tram" for i in range(1, len(legs) + 1))


def test_every_addon_file_compiles_under_the_games_lua_5_1():
    # The tests run Lua 5.5; the game runs 5.1, whose limits are tighter (a function may use at
    # most 60 variables from outside it: G.Init went over once and the whole map failed to load).
    lua51 = pytest.importorskip("lupa.lua51")
    lua = lua51.LuaRuntime()
    comp = lua.eval("function(src, name) local f, err = loadstring(src, '@' .. name) return err end")
    errors = []
    for p in sorted(ADDON.rglob("*.lua")):
        err = comp(p.read_text(encoding="utf-8"), p.name)
        if err:
            errors.append(err)
    assert not errors, errors


def test_a_route_walking_through_a_zone_too_high_asks_first(nav_env):
    lua, ns = nav_env
    load(lua, ns, "Data/Terrain.lua", "Passability.lua", "Data/Zones.lua", "GPSFrame.lua")
    N, R = ns.Nav, ns.Router
    ns.settings = lua.eval("{ gps = {} }")
    ns.Print = lua.eval("function() end")

    def zone(name):
        return next(k for k in ns.Maps.keys() if ns.Maps[k].name == name and ns.Maps[k].type == 3)

    def at(name, u, v):
        b = ns.Maps[zone(name)].bounds
        return b[3] - v / 100 * (b[3] - b[1]), b[4] - u / 100 * (b[4] - b[2])

    brill, alterac, tarren = at("Tirisfal Glades", 61, 52), at("Alterac Mountains", 50, 50), at("Hillsbrad Foothills", 61, 20)
    lua.execute("UnitLevel = function() return 13 end")
    lua.execute(f"UnitPosition = function() return {brill[0]}, {brill[1]}, 0, 0 end")
    lua.execute("StaticPopupDialogs = {}; ASKED = nil; StaticPopup_Show = function(which, text, _, data) ASKED = { text = text, data = data } end")
    N.stops = lua.table(lua.table(x=tarren[0], y=tarren[1], cont=0, name="Tarren Mill"))
    N.dest = N.stops[1]
    # a route over the mountains (as when there's no other way for the character's faction)
    route = lua.eval("function(a, b, c, d, e, f) return { parts = { { cont = 0, kinds = { 0, 0 }, pts = { a, b, c, d, e, f } } } } end")(
        brill[0], brill[1], alterac[0], alterac[1], tarren[0], tarren[1])
    zones = N.RedOnRoute(route, brill[0], brill[1], 0)
    assert zones and zones[1][1] == "Alterac Mountains"  # (Hillsbrad is where it goes: not asked about)
    # asked on the map's confirm; No clears the route
    N.route = route
    N.CheckRedRoute(brill[0], brill[1], 0, 100)
    popup = lua.eval("ASKED")
    assert popup and "The only way there walks through Alterac Mountains" in popup.text
    popup.data[2]()
    assert len(N.stops) == 0
    # Yes: not asked again for that zone on this route
    N.stops = lua.table(lua.table(x=tarren[0], y=tarren[1], cont=0, name="Tarren Mill"))
    N.redOk = lua.table()
    N.redOk[zone("Alterac Mountains")] = True
    assert N.RedOnRoute(route, brill[0], brill[1], 0) is None


def test_a_dungeons_way_in_is_learned_and_shared(env, tmp_path, monkeypatch):
    lua, ns = env
    lua.execute("CreateFrame = function() return { RegisterEvent = function() end, SetScript = function() end } end")
    lua.execute("GetBuildInfo = function() return '1.60.1', '70009' end")
    ns.db = lua.eval("{}")
    ns.Nav = lua.eval("{ CurrentInstance = function() return nil end }")
    load(lua, ns, "Taxi.lua", "Feedback.lua")
    T, F = ns.Taxi, ns.Feedback
    # walking up to Karazhan Crypts' door, then the loading screen into it (map 2875)
    T.NoteOutside(10.0, -11050.0, -1990.0, 0)
    T.NoteOutside(10.5, -11055.0, -1995.0, 0)
    assert T.NoteEntrance(2875, 20.0)
    assert T.NoteEntrance(2875, 30.0)  # (again, the same door: counted, not a second one)
    e = ns.db.entrances[2875]
    assert len(e) == 1 and e[1][1] == 0 and e[1][2] == -11055.0 and e[1].n == 2
    assert not T.NoteEntrance(2875, 1000.0)  # (the spot outside too old: nothing)
    text, n = F.RoadsText()
    assert "E 2875 0 -11055.0,-1995.0" in text
    # into the data (overrides/instance_entrances.json)
    from azerothgps import instances as X
    monkeypatch.setattr(X, "ENTRANCES", tmp_path / "instance_entrances.json")
    assert X.merge_entrances(X.parse_shared_entrances(text), log=lambda *a: None) == 1
    assert X.merge_entrances(X.parse_shared_entrances(text), log=lambda *a: None) == 0  # (known now)


def test_a_gentle_bend_is_straight_on(turns):
    lua, ns = turns
    # off-road east, then a 30 degree bend (running straight along the route: no "Slight right")
    p = path_of(lua, ns, [(0, 0), (0, -300), (-150, -560), (-300, -820)], [1, 1, 1])
    got, _ = maneuvers(lua, ns, p)
    assert [g[0] for g in got] == ["arrive"]
    # a real turn still is one
    p = path_of(lua, ns, [(0, 0), (0, -300), (300, -300), (600, -300)], [1, 1, 1])
    got, _ = maneuvers(lua, ns, p)
    assert got[0][2] == "Turn left"


def test_stops_routed_and_drawn_ahead_is_an_option(nav_env):
    # (asked) how many stops are routed and drawn at a time: a slider, 1 to 8, 3 by default (less
    # to work out and draw; the next come in as they're reached)
    lua, ns = nav_env
    N = ns.Nav
    N.stops = lua.eval("{ {x=1,y=1,cont=0}, {x=2,y=2,cont=0}, {x=3,y=3,cont=0}, {x=4,y=4,cont=0}, {x=5,y=5,cont=0} }")
    ns.settings = lua.eval("{ gps = {} }")
    assert N.PlannedStops() == 3  # (the default)
    ns.settings.gps.stopsAhead = 8
    assert N.PlannedStops() == 5
    ns.settings.gps.stopsAhead = 1
    assert N.PlannedStops() == 1
    ns.settings.gps.stopsAhead = 20
    assert N.PlannedStops() == 5  # (at most PLAN_AHEAD, 8)
    addon = Path(__file__).parents[2] / "addon" / "AzerothGPS"
    assert "stopsAhead = 3" in (addon / "Core.lua").read_text(encoding="utf-8")
    assert 'slider("Stops routed and drawn ahead", 1, 8, 1' in (addon / "Options.lua").read_text(encoding="utf-8")


def test_the_stops_not_routed_yet_are_listed_too(nav_env):
    # (asked) with the route worked out a few stops ahead (the option), the steps still list the
    # stops after them: about how far (the straight line, as planning counts), not routed yet
    lua, ns = nav_env
    N = ns.Nav
    ns.settings = lua.eval("{ gps = { stopsAhead = 2 } }")
    N.SetStops(lua.eval("""{ { x = -600, y = -4180, cont = 1 }, { x = -650, y = -4250, cont = 1 },
      { x = -700, y = -4300, cont = 1 }, { x = -760, y = -4350, cont = 1, name = 'Last' } }"""))
    N.Route(-550.0, -4150.0, 1)
    steps = [N.Steps()[i] for i in range(1, len(N.Steps()) + 1)]
    assert "not routed yet" not in steps[0]
    later = [t for t in steps if "not routed yet" in t]
    assert len(later) == 2 and "stop 3" in later[0] and "Last" in later[1] and later[0].startswith("|cff9d9d9dAbout ")


def test_the_map_windows_title_is_centered(env):
    # (reported: "AzerothGPS" sat right of the window's middle) the client's PortraitFrameTemplate puts
    # its TitleContainer 58 in from the left (past the portrait) and 24 from the right
    lua, ns = env
    chrome = lua.eval("""(function()
      local tc = { pts = { { "TOPLEFT", nil, "TOPLEFT", 58, -1 }, { "TOPRIGHT", nil, "TOPRIGHT", -24, -1 } } }
      function tc:GetPoint(i) local p = self.pts[i] return p[1], p[2], p[3], p[4], p[5] end
      function tc:ClearAllPoints() self.pts = {} end
      function tc:SetPoint(a, rel, b, x, y) self.pts[#self.pts + 1] = { a, rel, b, x, y } end
      return { TitleContainer = tc }
    end)()""")
    assert ns.GPS.CenterTitle(chrome)
    pts = chrome.TitleContainer.pts
    (a1, x1, y1), (a2, x2, y2) = [(pts[i][1], pts[i][4], pts[i][5]) for i in (1, 2)]
    assert (a1, a2) == ("TOPLEFT", "TOPRIGHT") and x1 == -x2 and y1 == y2 == -1



def test_in_ironforge_the_route_keeps_to_its_halls_though_the_game_says_outdoors(capitals_env):
    # (reported: in Ironforge the routes ran straight across the Great Forge and over the Forlorn
    # Cavern's pool) IsIndoors said outdoors in its halls, and over its floor under the mountain that
    # made the player up on the mountain, with no roads of the city's: the player's height tells now
    # (the city's grid's `split`, between its floor and the ground over it)
    lua, ns = capitals_env
    R = ns.Router
    forge, cavern, z = (-4763.4, -1107.8), (-4628.4, -1100.1), 502.0
    assert R.CaveDown(0, *forge, False, z)
    r = R.Route(0, *forge, *cavern, lua.table(offroad=False, z=z, indoors=False, tz=z))
    share, closed, last = check_capital_route(ns, 0, r)
    assert share > 0.6 and closed < 5 and last < 40, (share, closed, last)


def test_out_of_stormwind_the_route_takes_the_gate_and_the_roads(capitals_env):
    # (reported: from Stormwind to the Redridge border, a straight line out through the city's wall, then
    # the Deeprun Tram and a 34-minute walk) the erasures drawn at its gate had left its streets no road
    # out to Elwynn's: the nearest street runs out to the gate again (capitals.remouth)
    lua, ns = capitals_env
    pts_off = []
    for start in ((-8832.0, 625.0), (-8750.0, 430.0)):  # (the Trade District, Old Town)
        r = ns.Router.Route(0, *start, -9613.0, -2072.0, lua.table(offroad=False))
        pts, kinds = route_pts(r)
        off = sum(math.dist(pts[i], pts[i + 1]) for i, k in enumerate(kinds) if k != 0)
        pts_off.append(off)
        assert off < 300, (start, off, r.length)
        assert min(_seg_dist(p, q, (-9095.0, 412.0)) for p, q in zip(pts, pts[1:])) < 40  # (out by the gate)


def test_on_a_road_a_shortcut_to_another_road_must_save_a_fair_bit(env):
    # (reported, a video: riding Mulgore's road, the route swapped every few seconds between the road and a
    # shortcut over the fields onto another road) on a road already, a leg off it costs LEAVE_ROAD_FACTOR
    # a yard: from A, the L by B to C is 2000 yd; 300 yd across onto D and down it to C, 1905: kept on the L
    lua, ns = env
    load(lua, ns, "Router.lua")
    lua.eval("function(src) return assert(load('local _, ns = ...; ' .. src)) end")("""
      ns.Roads = { [1] = { n = { 0,0, 0,-1000, 400,-1000, 1000,-1000, 300,0 },
        e = { {1,2,1000,0, 0,0, 0,-1000}, {2,3,400,0, 0,-1000, 400,-1000}, {3,4,600,0, 400,-1000, 1000,-1000},
              {5,3,1005,0, 300,0, 400,-1000} } } }""")(None, ns)
    R = ns.Router
    R.Reset()
    r = R.Route(1, 0.0, 0.0, 1000.0, -1000.0, lua.table(offroad=False))
    pts, kinds = route_pts(r)
    assert (0, -1000) in [tuple(round(v) for v in p) for p in pts]  # (by B: on the road it's on)
    R.LEAVE_ROAD_FACTOR = 1.0
    R.Reset()
    r = R.Route(1, 0.0, 0.0, 1000.0, -1000.0, lua.table(offroad=False))
    pts, kinds = route_pts(r)
    assert (300, 0) in [tuple(round(v) for v in p) for p in pts]  # (without it: across to D)


def test_a_ride_to_zephras_isle_is_drawn_too(nav_env):
    # (reported: on a hop by Zephras Isle's zeppelins, only one ride had its line) a ride's line is its
    # boarding dock to its landing, both in the boarding continent's coordinates: the isle's weren't
    # (an inset on the world map), and a ride from the land onto it wasn't drawn at all
    lua, ns = nav_env
    Geo, N = ns.Geo, ns.Nav
    x, y = Geo.IntoAny(1, -800.0, 360.0, 2991)  # (Mulgore, in the isle's coordinates)
    bx, by = Geo.IntoAny(2991, x, y, 1)
    assert abs(bx + 800) < 0.5 and abs(by - 360) < 0.5  # (and back)
    N.SetStops(lua.eval("{ { x = 2197.0, y = 772.0, cont = 2991, name = 'Isle' } }"), False, "red")
    try:
        r = N.Route(-800.0, 360.0, 1)
        rides = [r.parts[i] for i in range(1, len(r.parts) + 1) if r.parts[i].kinds[1] == N.KIND_TRANSPORT]
        assert rides, "the zeppelin to the isle: drawn"
    finally:
        N.Clear()


def test_a_capital_stop_with_a_height_takes_the_road_on_its_floor(capitals_env):
    # (asked: Ironforge's trainers "need to go up stairs and back down") the Priest trainer stands on the
    # ground floor under the Hall of Mysteries' balcony: its nearest road was up there (stairs up, a step
    # down); the capitals' roads have their floors' heights (`nz`) and a stop with a height (the NPC's)
    # takes a road on its floor
    lua, ns = capitals_env
    R = ns.Router
    b = ns.Maps[1455].bounds
    tx, ty = b[3] - 0.090 * (b[3] - b[1]), b[4] - 0.244 * (b[4] - b[2])  # (the Priest trainer, 24.4, 9.0)
    edges, g = R.Edges(0)
    assert g.nz  # (the capitals' road heights)
    r = R.Route(0, *IRONFORGE_OUTSIDE, tx, ty, lua.table(offroad=False, tz=501.2))
    pts, _ = route_pts(r)
    high = []
    for x, y in pts:
        for n in range(1, len(g.n) // 2 + 1):
            h = g.nz[n]
            if h and h > 515 and abs(g.n[2 * n - 1] - x) < 1 and abs(g.n[2 * n] - y) < 1:
                high.append((round(x), round(y), h))
    assert not high, high  # (not up on the balcony)


# ---- Pins (Pins.lua, app/azerothgps/pins.py) ------------------------------------------------------

def test_pins_are_kept_shared_and_shipped(env, tmp_path):
    # (asked) pins the player makes, exported with the map data like roads and walls: the share text's
    # "P" lines read back offline, written into Data/Pins.lua for everyone; the player's own copy then
    # dropped at login, and a shared one they remove hidden and its removal shared
    from azerothgps.pins import merge_pins, parse_shared_pins, pins_lua

    lua, ns = env
    lua.execute("time = function() return 1790000000 end")
    ns.db = lua.eval("{}")
    load(lua, ns, "Pins.lua")
    P = ns.Pins
    map02 = r"Interface\Icons\INV_Misc_Map02"
    first = lua.eval("{ level = 20036, x = -47.25, y = -785.5, z = 18.4 }")
    first.icon, first.name = map02, "  Van Cleef's |cffff0000ship|r\n "
    P.Add(first)
    P.Add(lua.eval('{ level = 0, x = 1600, y = 240, down = true, icon = 136001, name = "" }'))
    pins = P.All()
    assert len(pins) == 2 and pins[1].time != pins[2].time  # (unique ids, made in the same second)
    assert pins[1].name == "Van Cleef's cffff0000shipr"  # (one line, no escape codes)
    assert pins[2].name == "Pin"
    lines = [P.ShareLines()[i] for i in range(1, len(P.ShareLines()) + 1)]
    assert lines[0] == ("P add 20036 1790000000 -47.2,-785.5 z=18.4 icon=" + map02 + " name=Van Cleef's cffff0000shipr")
    assert lines[1] == "P add 0 1790000001 1600.0,240.0 down=1 icon=136001 name=Pin"
    added, removed = parse_shared_pins("AzerothGPS roads 1 (addon 1.1.0)\n" + "\n".join(lines) + "\nR add 0 1 1,1 2,2\n")
    assert [(p["level"], p["time"], p.get("z"), p.get("down"), p["icon"], p["name"]) for p in added] == [
        (20036, 1790000000, 18.4, None, map02, "Van Cleef's cffff0000shipr"),
        (0, 1790000001, None, True, 136001, "Pin")]
    store = tmp_path / "pins.json"
    assert merge_pins(added, removed, store, log=lambda *a: None) == 2
    assert merge_pins(added, removed, store, log=lambda *a: None) == 0  # (each once)
    # the data as shipped: the player's own copies dropped at login, the shared ones shown
    from azerothgps.pins import load_pins

    loader = lua.eval("function(src) return assert(load(src, '@Data/Pins.lua')) end")
    loader(pins_lua(load_pins(store)))("AzerothGPS", ns)
    assert ns.PinsIn[1790000000] and ns.SharedPins[1].shipped and ns.SharedPins[1].name == "Van Cleef's cffff0000shipr"
    assert ns.SharedPins[1].icon == map02 and ns.SharedPins[2].down is True
    P.Prune()
    pins = P.All()
    assert len(P.Own()) == 0 and len(pins) == 2 and all(pins[i].shipped for i in (1, 2))
    assert len(P.ShareLines()) == 0  # (nothing new to share)
    # removing a shared one: hidden here, its removal shared and applied offline
    P.Remove(pins[1])
    assert len(P.All()) == 1 and P.ShareLines()[1] == "P remove 1790000000"
    added, removed = parse_shared_pins("P remove 1790000000")
    assert merge_pins(added, removed, store, log=lambda *a: None) == 1
    assert [p["time"] for p in load_pins(store)] == [1790000001]


def test_shared_pins_text_is_data_only():
    # (the share text is pasted by players: names one clean line, icons only a file id or an icon's path)
    from azerothgps.pins import parse_shared_pins

    added, _ = parse_shared_pins('P add 0 5 1,2 icon=foo";os.exit() name=a|b\x07c\n'
                                 "P add 0 6 1,2 icon=Interface/Icons/Spell_Fire_Fire name=x name=y\n"
                                 "P add 0 nope 1,2 icon=1 name=z\nP add 0 7 1 icon=1 name=z")
    assert [(p["time"], p["icon"], p["name"]) for p in added] == [
        (5, r"Interface\Icons\INV_Misc_QuestionMark", "ab c"), (6, "Interface/Icons/Spell_Fire_Fire", "x name=y")]


def test_copy_map_data_includes_only_the_kinds_picked(env):
    # (asked) Copy Map Data: roads, walls, routes (the faster trips kept) and pins, all in by default; an
    # unticked one is left out; the routes' traces simplified; `agps import-shared` reads the routes back
    from azerothgps.sharedtrips import parse_shared_trips

    lua, ns = env
    ns.db = lua.eval("""{ tracks = {
        { op = "add", continent = 0, time = 11, pts = { 1, 2, 30, 40 } },
        { op = "wall", continent = 0, time = 12, pts = { 5, 6, 7, 8 } } },
      feedback = { trips = { { continent = 1, time = 13, estimate = 300, actual = 200, mounted = true,
        to = { 50, 60, 1 }, pts = { 0, 0, 10, 0.5, 20, 0, 30, 0, 40, 25 } } } } }""")
    ns.settings = lua.eval("{ gps = {} }")
    lua.execute("time = function() return 1790000000 end")
    load(lua, ns, "Pins.lua", "Feedback.lua")
    ns.Pins.Add(lua.eval('{ level = 0, x = 1, y = 2, name = "Spot" }'))
    F, gps = ns.Feedback, ns.settings.gps

    def text():
        return F.RoadsText()[0]

    lines = text().splitlines()
    assert lines[0].startswith("AzerothGPS roads 1")
    assert lines[1:] == ["R add 0 11 1.0,2.0 30.0,40.0", "R wall 0 12 5.0,6.0 7.0,8.0",
                         "T 1 13 300 200 1 to=50.0,60.0,1 0,0 30,0 40,25",  # (the trace simplified)
                         r"P add 0 1790000000 1.0,2.0 icon=Interface\Icons\INV_Misc_QuestionMark name=Spot"]
    for key, gone in (("copyWalls", "R wall"), ("copyRoutes", "T "), ("copyPins", "P "), ("copyRoads", "R add")):
        gps[key] = False
        assert not any(l.startswith(gone) for l in text().splitlines()), key
    assert F.RoadsText()[0] == "" and F.RoadsText()[1] == 0  # (nothing picked)
    counts = F.KindCounts()
    assert (counts.roads, counts.walls, counts.routes, counts.pins) == (1, 1, 1, 1)  # (there all the same)
    trips = parse_shared_trips("T 1 13 300 200 1 to=50.0,60.0,1 0,0 30,0 40,25\nT 1 nope\nR add 0 11 1,2 3,4")
    assert trips == [{"continent": 1, "time": 13, "estimate": 300, "actual": 200, "mounted": True, "from": [0.0, 0.0],
                      "to": [50.0, 60.0, 1], "pts": [0.0, 0.0, 30.0, 0.0, 40.0, 25.0], "source": "shared"}]

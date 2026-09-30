"""The map's setup and redraw run offline, under the game's Lua 5.1, with a stand-in for the game's UI
(wowmock.lua): every addon file loaded in the toc's order, the addon's start-up events fired, a route
set, and the map redrawn. A redraw failing (caught in the game: nothing drawn after the failing line,
the route and the directions panel gone) fails here. (The flight-path detour line: `x, y = a and f()`
left y nil, and every redraw failed.)"""

from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parents[2] / "addon" / "AzerothGPS"
MOCK = Path(__file__).resolve().parent / "wowmock.lua"


def _toc_files():
    out = []
    for line in (ADDON / "AzerothGPS.toc").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.replace("\\", "/"))
    return out


@pytest.fixture(scope="module")
def game():
    lua51 = pytest.importorskip("lupa.lua51")
    lua = lua51.LuaRuntime()
    lua.execute(MOCK.read_text(encoding="utf-8"))
    lua.execute("""
      strsplit = function(sep, s, n)
        local out, pat = {}, "([^" .. sep .. "]*)"
        for part in (s .. sep):gmatch(pat .. sep) do out[#out + 1] = part end
        return unpack(out)
      end
      strtrim = function(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
      strjoin = function(sep, ...) return table.concat({ ... }, sep) end
      tinsert, tremove, wipe = table.insert, table.remove, function(t) for k in pairs(t) do t[k] = nil end return t end
      format = string.format
      date = os.date
      time = os.time
    """)
    ns = lua.table()
    lua.globals().AGPS_NS = ns
    loader = lua.eval("function(src, name) return assert(loadstring(src, '@' .. name)) end")
    for name in _toc_files():
        loader((ADDON / name).read_text(encoding="utf-8"), name)("AzerothGPS", ns)
    fire = lua.eval("AGPS_FIRE")
    fire("ADDON_LOADED", "AzerothGPS")
    fire("PLAYER_LOGIN")
    assert not list(ns.initErrors.values()), list(ns.initErrors.values())
    ns.Router.WARM, ns.Router.SYNC_WALKS = False, True
    return lua, ns


def _redraw(lua, ns):
    G = ns.GPS
    G.Update()  # (not the frame's pcall: a failure fails the test)


def test_the_map_redraws_without_a_route(game):
    lua, ns = game
    ns.Nav.Clear()
    _redraw(lua, ns)


def test_the_map_redraws_with_a_route_by_a_flight_master_to_learn(game):
    # (reported) the route passing Tarren Mill's flight master, not learned: its detour line drawn,
    # and the rest of the redraw (the route, the directions panel) not lost to a failure there
    lua, ns = game
    cdb = ns.CharDB()
    cdb.taxiNodes = lua.eval("{ [1415] = { nodes = { { nodeID = 10, known = true }, { nodeID = 11, known = true } } } }")
    cdb.faction = "Horde"
    ns.Nav.FlightsChanged()
    ns.Nav.SetStops(lua.eval("{ { x = -1441, y = -2332, cont = 0 } }"), False, "red")
    for t in range(3):
        lua.execute(f"AGPS_T = {200 + t}")
        _redraw(lua, ns)
    r = ns.Nav.route
    assert r and ns.Nav.LearnOnRoute(r)
    assert "Detour" in ns.Nav.StepsText(9)


def _detour_pins(lua):
    return [w for w in lua.eval("AGPS_WIDGETS").values() if w.learnNode and w._shown]


def test_a_detour_is_removed_for_this_route_by_its_pin(game):
    # (asked) the detour to a flight master to learn: a pin on the map; right-click, Remove: not
    # suggested again on this route (rerouting, a /reload), back with a new route
    lua, ns = game
    N, G = ns.Nav, ns.GPS
    cdb = ns.CharDB()
    cdb.taxiNodes = lua.eval("{ [1415] = { nodes = { { nodeID = 10, known = true }, { nodeID = 11, known = true } } } }")
    cdb.faction = "Horde"
    N.FlightsChanged()
    stop = lua.eval("{ { x = -1441, y = -2332, cont = 0 } }")
    N.SetStops(stop, False, "red")
    lua.execute("AGPS_T = 300")
    G.Update()
    pins = _detour_pins(lua)
    assert len(pins) == 1 and pins[0].learnNode == 13 and "Tarren Mill" in pins[0].title
    G.AskRemove(pins[0])
    ask = next(w for w in lua.eval("AGPS_WIDGETS").values() if w._text == "Remove?")
    ask._scripts.OnClick(ask)
    lua.execute("AGPS_T = 301")
    G.Update()
    assert not N.LearnOnRoute(N.route) and not _detour_pins(lua)
    assert "Detour" not in N.StepsText(9)
    N.skipLearn = lua.eval("{}")  # (a /reload: back from the saved stops)
    N.Restore()
    lua.execute("AGPS_T = 302")
    G.Update()
    assert not N.LearnOnRoute(N.route)
    N.SetStops(stop)  # (a new route: asked about Arathi first, the detours back...)
    N.SetStops(stop, False, "red")  # (...and the yes to it)
    lua.execute("AGPS_T = 303")
    G.Update()
    assert N.LearnOnRoute(N.route) and N.LearnOnRoute(N.route).node == 13

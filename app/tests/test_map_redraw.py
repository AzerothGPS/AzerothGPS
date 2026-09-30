"""The map's setup and redraw run offline, under the game's Lua 5.1, with a stand-in for the game's UI
(wowmock.lua): every addon file loaded in the toc's order, the addon's start-up events fired, a route
set, and the map redrawn. A redraw failing (caught in the game: nothing drawn after the failing line,
the route and the directions panel gone) fails here. (The flight-path detour line: `x, y = a and f()`
left y nil, and every redraw failed.)"""

from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parents[2] / "addon" / "AzerothGPS"


@pytest.fixture(scope="module")
def game():
    pytest.importorskip("lupa.lua51")
    from azerothgps.gameharness import start  # (the same harness `agps trip-sweep` runs)
    return start()


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
    ns.settings.gps.zoom = 2400  # (out far enough to show Tarren Mill's flight master from Brill)
    N.SetStops(stop, False, "red")
    lua.execute("AGPS_T = 300")
    G.Update()
    pins = _detour_pins(lua)
    assert len(pins) == 1 and pins[0].learnNode == 13 and "Tarren Mill" in pins[0].title
    # (the flight master's own icon, not a new marker; the map's icon under it left out, as under a
    # stop made from a map icon)
    assert pins[0].icon._tex == r"Interface\TaxiFrame\UI-Taxi-Icon-Gray"
    taxi = [w for w in lua.eval("AGPS_WIDGETS").values() if w._shown and w.icon and w.icon._tex
            and "UI-Taxi-Icon" in str(w.icon._tex) and not w.learnNode and w.name and "Tarren Mill" in w.name]
    assert not taxi
    G.AskRemove(pins[0])
    ask = next(w for w in lua.eval("AGPS_WIDGETS").values() if w._text == "Remove?")
    ask._scripts.OnClick(ask)
    lua.execute("AGPS_T = 301")
    G.Update()
    assert not N.LearnOnRoute(N.route) and not _detour_pins(lua)
    assert [w for w in lua.eval("AGPS_WIDGETS").values() if w._shown and w.icon and w.icon._tex  # (the map's icon back)
            and "UI-Taxi-Icon" in str(w.icon._tex) and w.name and "Tarren Mill" in w.name]
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
    assert N.LearnOnRoute(N.route) and N.LearnOnRoute(N.route)[1].node == 13


def test_the_dev_hooks_for_sharing(game):
    # (the private dev addon, AzerothGPS_Dev: AzerothGPS_Extend runs its setup with ns; the one way
    # out, Import.io.send; messages in, Import.OnAddonMessage; the popup, Import.Offer)
    lua, ns = game
    lua.globals().AzerothGPS_Extend(lua.eval("function(n) AGPS_EXTENDED = n end"))
    assert lua.eval("rawequal")(lua.eval("AGPS_EXTENDED"), ns)  # (after login: at once)
    I = ns.Import
    sent, offered = [], []
    real_send, real_offer = I.io.send, I.Offer
    try:
        I.io.send = lambda prefix, msg, channel, target: sent.append((prefix, msg, channel, target))
        I.Offer = lambda sender, stops: offered.append((sender, [stops[i].name for i in range(1, len(stops) + 1)]))
        ns.Nav.SetStops(lua.eval("{ { x = 2250, y = 250, cont = 0, name = 'Brill' }, { x = 1600, y = 240, cont = 0, name = 'Ruins' } }"), False, "red")
        assert I.Send("WHISPER", "Friend-Realm") == 2 and len(sent) == 2 and sent[0][0] == "AzerothGPS"
        for _, msg, _, _ in sent:  # (back in as another player's)
            I.OnAddonMessage("AzerothGPS", msg, "WHISPER", "Friend-Realm")
        assert offered == [("Friend-Realm", ["Brill", "Ruins"])]
    finally:
        I.io.send, I.Offer = real_send, real_offer


def test_no_dev_tool_ships_with_the_addon():
    # (the dev tools live in the private AzerothGPS-Dev repo, installed with install-addon --dev)
    files = [p.name.lower() for p in ADDON.rglob("*")]
    assert not any("dev" in f and f.endswith((".lua", ".toc", ".xml")) and f != "devnull" for f in files), \
        [f for f in files if "dev" in f]
    toc = (ADDON / "AzerothGPS.toc").read_text(encoding="utf-8").lower()
    assert "azerothgps_dev" not in toc


def test_heading_up_puts_the_player_low_on_the_map(game):
    # (asked) with "Turn the map with me" on, following: the player's icon low on the map (more of
    # the way ahead shown), not in the middle; north-up keeps them in the middle
    lua, ns = game
    G, Geo = ns.GPS, ns.Geo
    st = ns.settings.gps
    lua.execute("GetPlayerFacing = function() return 0.7 end")

    def player_on_screen():
        lua.execute("AGPS_T = AGPS_T + 1")
        G.Update()
        x, y, cont, rot, s, half = G.ViewState()
        dx, dy = Geo.ScreenOffset(x, y, lua.eval("AGPS_POS[1]"), lua.eval("AGPS_POS[2]"))
        ax, ay = Geo.Rotate(dx * s, dy * s, rot)
        return ax / half, ay / half
    try:
        st.rotate = True
        ax, ay = player_on_screen()
        assert abs(ax) < 0.01 and abs(ay + ns.GPS.HEADING_UP_LOW) < 0.01, (ax, ay)
        st.rotate = False
        ax, ay = player_on_screen()
        assert abs(ax) < 0.01 and abs(ay) < 0.01
    finally:
        st.rotate = False
        lua.execute("GetPlayerFacing = function() return 0 end")


def test_running_a_route_with_a_flight_stays_within_the_frame(game):
    # (reported: lag spikes rerouting along a route with a flight in it) the walk-vs-ride check in
    # the background, its slices short; in the frame, once the flight is the route, only the walk
    # from the player (crossing into another square: the last answer, not the whole walk routed)
    lua, ns = game
    R, N, G = ns.Router, ns.Nav, ns.GPS
    cdb = ns.CharDB()
    cdb.taxiNodes = lua.eval("{ [1415] = { nodes = { { nodeID = 10, known = true }, { nodeID = 11, known = true } } } }")
    cdb.faction = "Horde"
    N.FlightsChanged()
    lua.execute("""
      AGPS_LONG = 0
      local route = AGPS_NS.Router.Route
      AGPS_NS.Router.Route = function(cont, sx, sy, tx, ty, opts)
        local r = route(cont, sx, sy, tx, ty, opts)
        if not coroutine.running() and r and r.length > 3000 then AGPS_LONG = AGPS_LONG + 1 end
        return r
      end
      AGPS_POS[1], AGPS_POS[2] = 2254.0, 293.0
    """)
    clock = lua.eval("function() return os.clock() * 1000 end")

    def flies():
        return N.route and any(N.route.legs[i].ride for i in range(1, len(N.route.legs) + 1))
    try:
        R.Reset()
        R.WARM, R.SYNC_WALKS = True, False
        N.SetStops(lua.eval("{ { x = -1441, y = -2332, cont = 0 } }"), False, "red")
        t = 600.0
        for _ in range(600):  # (the roads built, the first route, the comparison: the flight)
            t += 0.05
            lua.execute(f"AGPS_T = {t}")
            G.Update()
            if R.HasWork():
                R.Pump(clock() + 5, clock)
            if flies() and not R.HasWork():
                break
        assert flies()
        lua.execute("AGPS_LONG = 0")
        x, y, worst = 2254.0, 293.0, 0.0
        for step in range(400):  # (about 20 s running toward the lift, weaving)
            t += 0.05
            x, y = x - 0.33, y + (0.25 if step % 60 < 30 else -0.25)
            lua.execute(f"AGPS_T = {t}; AGPS_POS[1], AGPS_POS[2] = {x}, {y}")
            G.Update()
            if R.HasWork():
                a = clock()
                R.Pump(clock() + 1, clock)
                worst = max(worst, clock() - a)
        assert lua.eval("AGPS_LONG") == 0, "the whole walk was routed in the frame while running"
        assert worst < 40, f"a background slice ran {worst:.0f} ms"
        assert flies()
    finally:
        R.WARM, R.SYNC_WALKS = False, True
        lua.execute("AGPS_POS[1], AGPS_POS[2] = 2254.0, 293.0")


def test_riding_a_zeppelin_doesnt_work_the_route_out_again(game):
    # (reported: a CPU spike with a route set, riding a zeppelin) carried along standing still, the
    # route isn't worked out again (as on a flight); walking again, it is
    lua, ns = game
    T, N, R = ns.Taxi, ns.Nav, ns.Router
    N.SetStops(lua.eval("{ { x = 1600, y = 240, cont = 0, name = 'Ruins' } }"), False, "red")
    lua.execute("""
      AGPS_ROUTES = 0
      local route = AGPS_NS.Router.Route
      AGPS_NS.Router.Route = function(...) AGPS_ROUTES = AGPS_ROUTES + 1 return route(...) end
    """)
    x, y = 2254.0, 293.0
    t0 = float(lua.eval("AGPS_T")) + 10  # (the game's clock: on from where the other tests left it)
    lua.execute(f"AGPS_T = {t0}")
    assert N.Route(x, y, 0)
    for k in range(4):  # (standing on the deck, carried 10 yd a check)
        x -= 10
        T.TransportTick(100 + k * 0.5, 1000 + k, x, y, 0, 0)
    assert T.Riding()
    lua.execute("AGPS_ROUTES = 0")
    for k in range(6):  # (far off the route: at a ride's speed every check was)
        x, y = x - 60, y + 90
        lua.execute(f"AGPS_T = {t0 + 5 + k * 5}")
        T.TransportTick(102 + k * 0.5, 1004 + k, x, y, 0, 0)
        assert N.Route(x, y, 0)
    assert lua.eval("AGPS_ROUTES") == 0
    T.TransportTick(106, 1010, x - 1, y, 0, 7)  # (walking off it)
    assert not T.Riding()
    lua.execute(f"AGPS_T = {t0 + 100}")
    N.Route(x, y, 0)
    assert lua.eval("AGPS_ROUTES") > 0

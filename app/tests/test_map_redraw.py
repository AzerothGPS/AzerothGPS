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


def test_every_stop_has_its_marker_though_the_route_is_drawn_a_few_ahead(game):
    # (asked) the option "stops routed and drawn ahead" limits the route worked out and drawn; the
    # stops' markers all show (only those in the map's view are placed)
    lua, ns = game
    N, G = ns.Nav, ns.GPS
    st = ns.settings.gps
    zoom, ahead = st.zoom, st.stopsAhead
    try:
        st.zoom, st.stopsAhead = 1500, 2
        N.SetStops(lua.eval("""{ { x = 2300, y = 250, cont = 0 }, { x = 2350, y = 150, cont = 0 },
          { x = 2200, y = 100, cont = 0 }, { x = 2150, y = 350, cont = 0 }, { x = 2400, y = 400, cont = 0 },
          { x = -9000, y = 400, cont = 0 } }"""), False, "red")
        lua.execute("AGPS_T = AGPS_T + 100")
        G.Update()
        assert N.PlannedStops() == 2
        shown = sorted(int(w.stopIndex) for w in lua.eval("AGPS_WIDGETS").values() if w.stopIndex and w._shown)
        assert shown == [1, 2, 3, 4, 5]  # (not the 6th: far off the map)
    finally:
        st.zoom, st.stopsAhead = zoom, ahead
        N.Clear()


def test_debug_probes_party_members_positions(game):
    # (asked: showing party members on the map, with or without the addon on their side) /agps debug
    # says what the game gives an addon for each member: by unit, no names saved
    lua, ns = game
    lua.execute("""
      AGPS_PARTY = { party1 = { 2200, 300 }, party2 = { 2100, 250 } }
      UnitExists = function(u) return AGPS_PARTY[u] ~= nil end
      UnitIsUnit = function(a, b) return a == b end
      UnitIsConnected = function(u) return AGPS_PARTY[u] ~= nil end
      IsInRaid = function() return false end
      local pos = UnitPosition
      UnitPosition = function(u)
        local p = AGPS_PARTY[u]
        if p then return p[1], p[2], 0, 0 end
        return pos(u)
      end
    """)
    try:
        ns.RunProbe("test")
        rec = ns.db.probes[len(ns.db.probes)]
        party = next(r for r in rec.results.values() if r.name == "party positions")
        assert party.ok and "party1: UnitPosition=2200,300" in party.value and "party2:" in party.value
        assert "Tester" not in party.value
    finally:
        lua.execute("AGPS_PARTY = {}")


def test_party_members_are_dots_on_the_map(game):
    # (asked) party members on the map where the game gives their position: a dot each in their
    # class's color; the option off: none
    lua, ns = game
    G = ns.GPS
    st = ns.settings.gps
    lua.execute("""
      AGPS_PARTY = { party1 = { 2260, 300 } }
      UnitExists = function(u) return AGPS_PARTY[u] ~= nil end
      UnitIsUnit = function(a, b) return a == b end
      IsInRaid = function() return false end
      UnitClass = function(u) return "Mage", "MAGE" end
      RAID_CLASS_COLORS = { MAGE = { r = 0.25, g = 0.78, b = 0.92 } }
      AGPS_POS_REAL = UnitPosition
      UnitPosition = function(u)
        local p = AGPS_PARTY[u]
        if p then return p[1], p[2], 0, 0 end
        return AGPS_POS_REAL(u)
      end
    """)
    try:
        lua.execute("AGPS_T = AGPS_T + 1")
        G.Update()
        dots = [w for w in lua.eval("AGPS_WIDGETS").values() if w.dot and w._shown]
        assert len(dots) == 1 and dots[0].name == "Tester"  # (the mock's UnitName)
        assert dots[0].dot._tex == "color:0.25,0.78,0.92"  # (the mage's class color, not the fallback)
        st.showParty = False
        lua.execute("AGPS_T = AGPS_T + 1")
        G.Update()
        assert not [w for w in lua.eval("AGPS_WIDGETS").values() if w.dot and w._shown]
    finally:
        st.showParty = True
        lua.execute("AGPS_PARTY = {} UnitPosition = AGPS_POS_REAL")


def test_party_members_show_their_class_icon(game):
    # (asked) a round class icon, not a plain dot: the game's own (atlas), else the class sheet cut to the
    # class; the dot's color only when neither is there
    lua, ns = game
    G = ns.GPS
    lua.execute("""
      AGPS_PARTY = { party1 = { 2260, 300 } }
      UnitExists = function(u) return AGPS_PARTY[u] ~= nil end
      UnitIsUnit = function(a, b) return a == b end
      IsInRaid = function() return false end
      UnitClass = function(u) return "Mage", "MAGE" end
      CLASS_ICON_TCOORDS = { MAGE = { 0.25, 0.5, 0, 0.25 } }
      AGPS_POS_REAL = UnitPosition
      UnitPosition = function(u)
        local p = AGPS_PARTY[u]
        if p then return p[1], p[2], 0, 0 end
        return AGPS_POS_REAL(u)
      end
    """)
    try:
        lua.execute("AGPS_T = AGPS_T + 1")
        G.Update()
        (pin,) = [w for w in lua.eval("AGPS_WIDGETS").values() if w.dot and w._shown]
        assert pin.dot._tex == G.CLASS_SHEET
        # (asked) round: the icon and its class-colored ring each cut to a circle by the portrait mask
        for part in (pin.dot, pin.edge):
            assert part._masks and part._masks[1]._tex == G.ROUND_MASK
    finally:
        lua.execute("AGPS_PARTY = {} UnitPosition = AGPS_POS_REAL CLASS_ICON_TCOORDS = nil")


def _texts(lua):
    return [str(w._text) for w in lua.eval("AGPS_WIDGETS").values() if w._text]


def test_the_options_window_builds_with_its_performance_page(game):
    # (asked) a Performance page in the options: lighter settings for low-end PCs, a preset for them
    # and back; the whole window built under the game's Lua 5.1 (a failure there: no options window)
    lua, ns = game
    ns.Options.Show()
    texts = _texts(lua)
    for label in ("Performance", "Use Low-End Settings", "Restore Defaults", "Map redraws per second",
                  "Work out a route you've left at most every", "Gentle background work", "Turn the arrow every frame",
                  "Other settings to improve performance"):
        assert label in texts, label
    # (asked) the stops routed ahead on the Performance page only, not Routing's too
    assert texts.count("Stops routed and drawn ahead") == 1


def test_the_options_pages_in_order(game):
    # (asked) the options' pages in this order; Help improve says a /reload saves every edit before copying
    lua, ns = game
    ns.Options.Show()
    order = ["General", "Performance", "Opacity", "Routing", "Directions", "Map", "Quick buttons", "Road tools",
             "Wall tools", "Help improve"]
    ws = lua.eval("AGPS_WIDGETS")
    ws = [ws[i] for i in range(1, len(ws) + 1)]  # (in the order made)
    # (the list on the left: a button per page, its name a font string on it)
    tabs = [str(w._text) for w in ws if w._kind == "FontString" and w._parent and w._parent._kind == "Button"
            and str(w._text) in order]
    assert tabs == order
    notes = [str(w._text) for w in ws if "/reload" in str(w._text) and "Copy Map Data" in str(w._text)]
    assert notes, "the note on Help improve"


def test_low_end_settings_and_back(game):
    lua, ns = game
    O, st, N = ns.Options, ns.settings.gps, ns.Nav
    try:
        O.UseLowEnd()
        for k in ("hz", "rerouteSeconds", "stopsAhead", "gentleBackground", "arrowHz"):
            assert st[k] == O.LOW_END[k], k
        assert O.IsLowEnd()
        assert st.hz < 20 and st.stopsAhead < 3 and st.gentleBackground and st.arrowHz > 0
        O.PerfDefaults()
        for k in ("hz", "rerouteSeconds", "stopsAhead", "gentleBackground", "arrowHz"):
            assert st[k] == ns.DEFAULTS.gps[k], k
        assert not O.IsLowEnd()
    finally:
        O.PerfDefaults()


def _frames(lua, seconds, fps=60, move=None):
    """The game's frames: every OnUpdate script run, `seconds` of them at `fps`."""
    lua.execute("""
      AGPS_TICK = function(dt)
        for _, w in pairs(AGPS_WIDGETS) do
          local f = w._scripts and w._scripts.OnUpdate
          if f then f(w, dt) end
        end
      end
    """)
    tick = lua.eval("AGPS_TICK")
    t = float(lua.eval("AGPS_T"))
    for i in range(int(seconds * fps)):
        t += 1 / fps
        lua.execute(f"AGPS_T = {t}")
        if move:
            move(i)
        tick(1 / fps)


def test_the_map_redraws_at_most_as_often_as_set(game):
    # (Performance: "Map redraws per second") moving, the map redraws that many times a second, no more
    lua, ns = game
    st = ns.settings.gps
    lua.execute("""
      AGPS_REDRAWS = 0
      local update = AGPS_NS.GPS.Update
      AGPS_NS.GPS.Update = function(...) AGPS_REDRAWS = AGPS_REDRAWS + 1 return update(...) end
    """)
    x = [2254.0]

    def run(i):
        x[0] -= 0.12
        lua.execute(f"AGPS_POS[1] = {x[0]}")
    try:
        counts = {}
        for hz in (20, 10, 5):
            st.hz = hz
            _frames(lua, 0.2, move=run)  # (settled)
            lua.execute("AGPS_REDRAWS = 0")
            _frames(lua, 3, move=run)
            counts[hz] = int(lua.eval("AGPS_REDRAWS"))
        for hz, n in counts.items():
            assert hz * 3 * 0.8 <= n <= hz * 3 + 1, (hz, n)
    finally:
        st.hz = ns.DEFAULTS.gps.hz
        lua.execute("AGPS_POS[1], AGPS_POS[2] = 2254.0, 293.0")


def test_the_arrow_turns_every_frame_or_as_often_as_set(game):
    # (Performance: "Turn the arrow every frame") off: 20 times a second, whatever the frame rate
    lua, ns = game
    st = ns.settings.gps

    def turns(seconds):
        p = ns.perf["arrow window"]
        n0 = p.n if p else 0
        _frames(lua, seconds, fps=100)
        return ns.perf["arrow window"].n - n0
    try:
        st.arrowHz = 0
        assert turns(1) >= 95
        st.arrowHz = 20
        n = turns(2)
        assert 36 <= n <= 41, n
    finally:
        st.arrowHz = ns.DEFAULTS.gps.arrowHz


def test_gentle_background_work_takes_smaller_slices(game):
    # (Performance: "Gentle background work") smaller slices of each frame for the searches and the
    # road data being built (smoother on a slow PC, done a little later)
    lua, ns = game
    G, st = ns.GPS, ns.settings.gps
    try:
        st.gentleBackground = False
        assert G.PumpBudget(16, False) == 1
        assert G.PumpBudget(40, True) == G.WARM_MS  # (the road data: up to 5 ms, a quarter of the frame)
        assert G.PumpBudget(8, True) == 2
        st.gentleBackground = True
        assert G.PumpBudget(16, False) == G.GENTLE_MS < 1
        assert G.PumpBudget(40, True) == G.GENTLE_WARM_MS < G.WARM_MS
        assert G.PumpBudget(4, True) == G.GENTLE_MS  # (a tenth of a fast frame is less than the least)
    finally:
        st.gentleBackground = False


def test_a_route_left_is_worked_out_again_as_often_as_set(game):
    # (Performance: "Work out a route you've left at most every") off the route, it's worked out
    # again from the player at most that often (less work; it catches up a little later)
    lua, ns = game
    N, st = ns.Nav, ns.settings.gps

    def recalcs(secs):
        st.rerouteSeconds = secs
        N.SetStops(lua.eval("{ { x = 1600, y = 240, cont = 0, name = 'Ruins' } }"), False, "red")
        t = float(lua.eval("AGPS_T")) + 60
        lua.execute(f"AGPS_T = {t}")
        x, y = 2254.0, 293.0
        assert N.Route(x, y, 0)
        n0 = ns.perf["route calculation"].n
        for k in range(24):  # (12 s drifting sideways off the route, 40 yd every half second)
            t += 0.5
            y += 40
            lua.execute(f"AGPS_T = {t}; AGPS_POS[1], AGPS_POS[2] = {x}, {y}")
            N.Route(x, y, 0)
        return ns.perf["route calculation"].n - n0
    try:
        often, seldom = recalcs(2), recalcs(6)
        assert 5 <= often <= 7, often
        assert 1 <= seldom <= 2, seldom
    finally:
        st.rerouteSeconds = ns.DEFAULTS.gps.rerouteSeconds
        N.Clear()
        lua.execute("AGPS_POS[1], AGPS_POS[2] = 2254.0, 293.0")


def test_the_performance_page_tells_the_addons_share_of_the_time(game):
    lua, ns = game
    O = ns.Options
    assert O.UsageText() == "AzerothGPS's work: measuring..."
    assert O.UsageText(200, 10) == "AzerothGPS's work: 20.0 ms a second, 2.0% of the time"
    # (only the timings that don't overlap: a redraw's parts are in it already)
    lua.execute("""
      local p = AGPS_NS.perf
      AGPS_SAVED = p
      AGPS_NS.perf = {
        redraw = { total = 10 }, ["redraw: icons"] = { total = 4 }, ["arrow window"] = { total = 2 },
        ["terrain search"] = { total = 3 }, ["router: build roads"] = { total = 3 }, ["route calculation"] = { total = 5 },
      }
    """)
    try:
        assert ns.PerfTotal() == 15
    finally:
        lua.execute("AGPS_NS.perf = AGPS_SAVED")


def test_the_road_tools_show_the_roads_and_the_map_data_button_sits_under_undo(game):
    # (asked) the road tools on show the road network (the wall tools the walls, as before); "Show
    # extracted roads/walls" is a map button now, under Undo, showing both (or neither)
    lua, ns = game
    G, st = ns.GPS, ns.settings.gps
    lua.execute("""
      AGPS_ROADS = 0
      local lay = AGPS_NS.GPS.LayoutRoads
      AGPS_NS.GPS.LayoutRoads = function(...) AGPS_ROADS = AGPS_ROADS + 1 return lay(...) end
    """)
    try:
        st.showRoads, st.showWalls, st.devTools, st.wallTools = False, False, True, True
        lua.execute("AGPS_T = AGPS_T + 1")
        G.Update()
        assert lua.eval("AGPS_ROADS") == 0
        G.SetRoadMode(True)
        lua.execute("AGPS_T = AGPS_T + 1")
        G.Update()
        assert lua.eval("AGPS_ROADS") > 0  # (the road tools on: the roads drawn)
        G.SetRoadMode(False)
        G.SetWallMode(True)
        assert G.ShowsWalls()  # (the wall tools on: the walls)
        G.SetWallMode(False)
        assert not G.ShowsWalls()
        # the button: under Undo, over the wall and road tools
        ids = [str(t.id) for t in G.QuickSlots().values()]
        tools = [i for i in ids if i in ("roadTools", "wallTools", "showMapData", "roadUndo")]
        assert tools == ["roadTools", "wallTools", "showMapData", "roadUndo"]
        assert G.ToggleMapData() and st.showRoads and st.showWalls
        assert not G.ToggleMapData() and not st.showRoads and not st.showWalls
    finally:
        G.SetRoadMode(False)
        G.SetWallMode(False)
        st.showRoads, st.showWalls, st.devTools, st.wallTools = False, False, False, False


def test_undo_takes_back_roads_and_walls_in_the_order_drawn(game):
    # (asked) one Undo for both: the last change, road or wall, first
    lua, ns = game
    Rec = ns.Record
    ns.db.tracks = lua.eval("{}")
    road = lua.eval("{ op = 'add', drawn = true, continent = 0, time = 1000, pts = { 2200, 300, 2210, 300, 2220, 305 } }")
    wall = lua.eval("{ op = 'wall', drawn = true, continent = 0, time = 1001, pts = { 2230, 320, 2240, 330 } }")
    try:
        Rec.Save(road)
        Rec.Save(wall)
        Rec.Undo()
        assert [str(t.op) for t in ns.db.tracks.values()] == ["add"]  # (the wall, drawn last, first)
        Rec.Undo()
        assert len(ns.db.tracks) == 0
    finally:
        ns.db.tracks = lua.eval("{}")


def test_ironforge_s_roads_show_on_its_inside_map(game):
    # (reported: drawn roads over Ironforge showed on the mountain in the outside view, and went once
    # the map showed the city's inside) a capital's inside map is its streets: its roads show there
    lua, ns = game
    G, st = ns.GPS, ns.settings.gps
    lua.execute("""
      AGPS_ROADS = 0
      local lay = AGPS_NS.GPS.LayoutRoads
      AGPS_NS.GPS.LayoutRoads = function(...) AGPS_ROADS = AGPS_ROADS + 1 return lay(...) end
      AGPS_INDOORS_REAL = IsIndoors
      IsIndoors = function() return true end
      AGPS_POS[1], AGPS_POS[2], AGPS_POS[3] = -4840.0, -1100.0, 0
    """)
    zoom = st.zoom
    try:
        st.showRoads, st.zoom = True, 200.0
        lua.execute("AGPS_T = AGPS_T + 1")
        G.Update()
        assert G.inside is not None  # (the city's inside map shown)
        assert lua.eval("AGPS_ROADS") > 0
    finally:
        st.showRoads, st.zoom = False, zoom
        lua.execute("IsIndoors = AGPS_INDOORS_REAL AGPS_POS[1], AGPS_POS[2], AGPS_POS[3] = 2254.0, 293.0, 0")

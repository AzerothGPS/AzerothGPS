"""Trip sweep (`agps trip-sweep`): random trips planned and followed as in the game, the whole addon
running (app/azerothgps/gameharness.py: every file under Lua 5.1, the game's UI stood in for), with
what `route-sweep` doesn't reach: flights, the zones too high for the level, the detours to flight
masters not learned, and the frame budget while the player runs along.

Each trip: a random faction and level (low levels see many zones too high), a random share of that
faction's flight masters on the continent known, a start and a stop at towns and places far apart.
The route is worked out with the terrain searches in the background (the roads built in the
background too, the first time), then the player runs along it for a while. Flagged:

  * frame:     a redraw (the route worked out in it) over FRAME_MS, after the first route
  * slice:     a slice of background work over SLICE_MS
  * longwalk:  running along a route with a ride, a whole walk (over LONG_YD) routed in the frame
  * noroute:   no route at all
  * slowride:  the route flies or rides, and walking all the way is clearly faster (RIDE_SHARE, RIDE_SLACK)
  * missedride: the route walks all the way, and the best way with a ride is clearly faster
               (both weighed as the addon does: the zones too high for the level count extra)
  * detour:    a detour to a flight master that shouldn't be one (known already, the other faction's,
               out of reach, an obsolete "zz" one), or one missing from the steps

Writes data/debug/trip-sweep/report.json (flagged trips, worst first, with everything to replay them).
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

FRAME_MS = 50  # (lupa's Lua 5.1: about the game's speed)
SLICE_MS = 40
LONG_YD = 3000
RIDE_SHARE, RIDE_SLACK = 1.2, 60  # clearly faster: by this share and this many seconds
LEVELS = (5, 10, 14, 20, 30, 40, 50, 60)
TRIP_MIN_YD, TRIP_MAX_YD = 1500, 9000
RUN_FRAMES = 300  # 15 s at 20 redraws a second
WALK = 7.0  # yards a second on foot


def _places(ns, cont):
    """Towns and named places on continent `cont`: (x, y, name)."""
    out = []
    for p in (ns.Pois[cont] or {}).values():
        if p[1] in (2, 3):
            out.append((float(p[2]), float(p[3]), str(p[4])))
    return out


def _masters(ns, cont, fac):
    """The flight masters of faction `fac` ("H" / "A") on continent `cont`: [node id]."""
    out = []
    for p in (ns.Pois[cont] or {}).values():
        if p[1] == 1 and p[6] and fac in str(p[6]) and not str(p[4]).startswith("zz"):
            out.append(int(p[5]))
    return out


def _secs(r):
    return (r.totalYards or 0) / WALK + (r.totalRide or 0) if r else math.inf


def _weighed(lua, ns, r, cont, a, b):
    """Seconds for route `r` as the addon weighs it (Nav.WeighedWalk: the zones too high for the level
    counted extra, not the trip's own ends; water at swimming's cost), plus its rides."""
    if not r:
        return math.inf
    R, N = ns.Router, ns.Nav
    exempt = lua.table()
    exempt[R.ZoneAt(cont, a[0], a[1])] = True
    exempt[R.ZoneAt(cont, b[0], b[1])] = True
    secs = 0.0
    for part in r.parts.values():
        pts, kinds = part.pts, part.kinds
        if all(kinds[i] != N.KIND_TRANSPORT for i in range(1, len(kinds) + 1)):
            if N.Unwalkable(part):  # (no way on foot found: a line across the sea or the mountains)
                return math.inf
            secs += N.WeighedWalk(part.cont, pts, WALK, exempt)
    return secs + (r.totalRide or 0)


def _rides(r):
    return bool(r and r.legs and any(r.legs[i].ride for i in range(1, len(r.legs) + 1)))


def sweep(trips: int = 20, minutes: float | None = None, seed: int | None = None, log=print) -> dict:
    from .gameharness import start

    seed = seed if seed is not None else random.randrange(1 << 30)
    rnd = random.Random(seed)
    lua, ns = start()
    R, N, G = ns.Router, ns.Nav, ns.GPS
    lua.execute("""
      AGPS_LONG = 0
      local route = AGPS_NS.Router.Route
      AGPS_NS.Router.Route = function(cont, sx, sy, tx, ty, opts)
        local r = route(cont, sx, sy, tx, ty, opts)
        if not coroutine.running() and r and r.length > AGPS_LONG_YD then AGPS_LONG = AGPS_LONG + 1 end
        return r
      end
    """.replace("AGPS_LONG_YD", str(LONG_YD)))
    clock = lua.eval("function() return os.clock() * 1000 end")
    ns.settings.gps.zoom = 800
    deadline = time.time() + minutes * 60 if minutes else None
    flagged, done = [], 0
    while (done < trips and not deadline) or (deadline and time.time() < deadline):
        done += 1
        cont = rnd.choice((0, 1))
        faction = rnd.choice(("Horde", "Alliance"))
        level = rnd.choice(LEVELS)
        places = _places(ns, cont)
        for _ in range(200):
            a, b = rnd.choice(places), rnd.choice(places)
            if TRIP_MIN_YD <= math.hypot(a[0] - b[0], a[1] - b[1]) <= TRIP_MAX_YD:
                break
        masters = _masters(ns, cont, faction[0])
        known = [m for m in masters if rnd.random() < rnd.uniform(0.2, 0.9)] or masters[:1]
        trip = {"cont": cont, "faction": faction, "level": level, "from": a, "to": b, "known": known, "issues": []}
        issues = trip["issues"]
        # the character
        lua.execute(f"AGPS_LEVEL = {level}; UnitFactionGroup = function() return '{faction}' end")
        cdb = ns.CharDB()
        cdb.faction = faction
        cdb.taxiNodes = lua.eval("{ [1415] = { nodes = { " + "".join(f"{{ nodeID = {n}, known = true }}," for n in known) + " } } }")
        ns.Teleports.Changed()
        N.FlightsChanged()
        # the route, as in the game: searches (and the roads, the first time) in the background
        lua.execute(f"AGPS_POS[1], AGPS_POS[2], AGPS_POS[3] = {a[0]}, {a[1]}, {cont}")
        R.WARM, R.SYNC_WALKS = True, False
        N.SetStops(lua.eval(f"{{ {{ x = {b[0]}, y = {b[1]}, cont = {cont}, name = 'stop' }} }}"), False, "red")
        t = float(lua.eval("AGPS_T")) + 10
        first, worst_frame, worst_slice = None, 0.0, 0.0
        try:
            for f in range(900):
                t += 0.05
                lua.execute(f"AGPS_T = {t}")
                s0 = time.perf_counter()
                G.Update()
                ms = (time.perf_counter() - s0) * 1000
                if R.HasWork():
                    c0 = clock()
                    R.Pump(clock() + 5, clock)
                    worst_slice = max(worst_slice, clock() - c0)
                if N.route and first is None:
                    first = ms
                elif first is not None:
                    worst_frame = max(worst_frame, ms)
                if N.route and not R.HasWork() and f > 20:
                    break
            if not N.route:
                issues.append({"kind": "noroute"})
            else:
                # running along it, weaving a little
                lua.execute("AGPS_LONG = 0")
                r = N.route
                pts = [(r.pts[i], r.pts[i + 1]) for i in range(1, len(r.pts) + 1, 2)]
                x, y, k = a[0], a[1], 1
                for step in range(RUN_FRAMES):
                    t += 0.05
                    while k < len(pts) - 1 and math.hypot(pts[k][0] - x, pts[k][1] - y) < 2:
                        k += 1
                    tx, ty = pts[min(k, len(pts) - 1)]
                    d = math.hypot(tx - x, ty - y) or 1
                    side = 0.15 if step % 60 < 30 else -0.15
                    x, y = x + (tx - x) / d * 0.35 - (ty - y) / d * side, y + (ty - y) / d * 0.35 + (tx - x) / d * side
                    lua.execute(f"AGPS_T = {t}; AGPS_POS[1], AGPS_POS[2] = {x}, {y}")
                    s0 = time.perf_counter()
                    G.Update()
                    worst_frame = max(worst_frame, (time.perf_counter() - s0) * 1000)
                    if R.HasWork():
                        c0 = clock()
                        R.Pump(clock() + 1, clock)
                        worst_slice = max(worst_slice, clock() - c0)
                if int(lua.eval("AGPS_LONG")) > 0 and _rides(N.route):  # (walking all the way: the walk is the route)
                    issues.append({"kind": "longwalk", "count": int(lua.eval("AGPS_LONG"))})
            if worst_frame > FRAME_MS:
                issues.append({"kind": "frame", "ms": round(worst_frame)})
            if worst_slice > SLICE_MS:
                issues.append({"kind": "slice", "ms": round(worst_slice)})
            trip.update(first_ms=round(first or 0), worst_frame_ms=round(worst_frame), worst_slice_ms=round(worst_slice))
            # the settled routes from the start: as chosen, and on foot all the way
            R.WARM, R.SYNC_WALKS = False, True
            lua.execute(f"AGPS_POS[1], AGPS_POS[2] = {a[0]}, {a[1]}")
            N.Invalidate(True, True)
            chosen = N.Route(a[0], a[1], cont)
            if chosen:
                steps = [N.Steps()[i] for i in range(1, len(N.Steps()) + 1)]
                trip["steps"] = steps
                ns.settings.gps.useFlights = False
                N.FlightsChanged()
                walk = N.Route(a[0], a[1], cont)
                ns.settings.gps.useFlights = True
                N.FlightsChanged()
                cs, ws = _weighed(lua, ns, chosen, cont, a, b), _weighed(lua, ns, walk, cont, a, b)
                trip.update(chosen_s=None if cs == math.inf else round(cs), walk_s=None if ws == math.inf else round(ws),
                            rides=_rides(chosen), plain_chosen_s=round(_secs(chosen)))
                if _rides(chosen) and not _rides(walk) and ws < math.inf and cs > ws * RIDE_SHARE + RIDE_SLACK:
                    issues.append({"kind": "slowride", "chosen_s": round(cs), "walk_s": round(ws)})
                if not _rides(chosen):
                    legs, _ = N.Plan(cont, a[0], a[1], WALK, N.stops[1], None, 1e9)
                    if legs and any(legs[i].ride for i in range(1, len(legs) + 1)):
                        secs = 0.0
                        for i in range(1, len(legs) + 1):
                            leg = legs[i]
                            if leg.ride:
                                secs += leg.ride[7] or 0
                            else:
                                rr = R.Route(leg.cont, leg.x1, leg.y1, leg.x2, leg.y2, lua.table(offroad=False))
                                secs += _weighed(lua, ns, lua.table(parts=lua.table(lua.table(
                                    cont=leg.cont, pts=rr.pts, kinds=rr.kinds, blocked=rr.blocked, unconnected=rr.unconnected)),
                                    totalRide=0), leg.cont, a, b) if rr else math.inf
                        trip["ride_s"] = round(secs)
                        if secs * RIDE_SHARE + RIDE_SLACK < cs:
                            issues.append({"kind": "missedride", "chosen_s": round(cs), "ride_s": round(secs)})
                # the detours
                known_set = set(known)
                for h in (N.LearnOnRoute(N.route) or lua.table()).values():
                    bad = []
                    if h.off > N.LEARN_NEAR_YD:
                        bad.append("out of reach")
                    if int(h.node) in known_set:
                        bad.append("known already")
                    if str(h.name).startswith("zz"):
                        bad.append("obsolete")
                    if int(h.node) not in _masters(ns, cont, faction[0]):
                        bad.append("not their faction's")
                    if not any(f"at {h.name}" in s for s in steps):
                        bad.append("not in the steps")
                    if bad:
                        issues.append({"kind": "detour", "name": str(h.name), "why": bad})
            elif not any(i["kind"] == "noroute" for i in issues):
                issues.append({"kind": "noroute"})
        except Exception as e:  # (a failure in the addon's Lua: that's a finding too)
            issues.append({"kind": "error", "error": str(e)[:500]})
        finally:
            R.WARM, R.SYNC_WALKS = False, True
        if issues:
            flagged.append(trip)
        log(f"  trip {done}: {'Horde' if faction == 'Horde' else 'Alliance'} {level}, {a[2]} -> {b[2]}: "
            + (", ".join(i["kind"] for i in issues) if issues else "ok"))
    weight = {"error": 9, "noroute": 8, "missedride": 7, "slowride": 6, "longwalk": 5, "frame": 4, "slice": 3, "detour": 2}
    flagged.sort(key=lambda tr: -max(weight.get(i["kind"], 1) for i in tr["issues"]))
    return {"seed": seed, "trips": done, "flagged": flagged}


def write_report(result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "report.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return out

"""Route quality check (`agps route-check`): runs the addon's own routing (its Lua, under
lupa) on random trips in every zone and flags bad off-road routes.

For each trip the off-road route is compared with the shortest walk the terrain grid
allows (Passability's grid search with generous limits: the best the data knows):

  * detour:  the route is much longer than that walk (routing picked a poor way round)
  * blocked: an off-road stretch of the route crosses terrain the grid calls impassable
             (away from the ends, where the player or the stop may stand on rocks)

Trips from or to a spot over a cave (Data/Caves.lua) are left out: such a spot is down in the
cave, which the flat reference walk can't judge (the caves have their own checks: `agps caves`
and the tests).

Writes data/debug/route-check/report.json (every flagged trip, worst first) and prints a
table per zone. Flagged trips can be turned into regression tests in app/tests.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from .paths import ADDON_DIR

DETOUR_SHARE, DETOUR_YD = 1.4, 150  # flagged when longer than max(share x, + yd) the grid walk
ROAD_DETOUR_SHARE, ROAD_DETOUR_YD = 2.5, 300  # the same for road routes (they keep to the roads)
BLOCKED_RUN_YD = 25  # flagged when an off-road stretch crosses this much impassable ground
END_ALLOW_YD = 60  # blocked ground this close to either end doesn't count


def _runtime():
    import lupa

    lua = lupa.LuaRuntime()
    lua.execute('issecretvalue = nil\nCreateFrame = function() error("no frames here") end\n'
                "GetTime = function() return 0 end")
    ns = lua.table()
    ns.IsSecret = lua.eval("function(v) return false end")
    ns.db = lua.eval("{}")
    loader = lua.eval("function(src, name) return assert(load(src, '@' .. name)) end")
    for name in ("Geo.lua", "GPSFrame.lua", "Data/Maps.lua", "Data/Roads.lua", "Data/Terrain.lua", "Data/Caves.lua",
                 "Passability.lua", "Router.lua"):
        loader((ADDON_DIR / name).read_text(encoding="utf-8"), name)("AzerothGPS", ns)
    ns.Router.SYNC_WALKS = True
    return lua, ns


def _pts(r) -> tuple[list[tuple[float, float]], list[int]]:
    flat = [r.pts[i] for i in range(1, len(r.pts) + 1)]
    kinds = [r.kinds[i] for i in range(1, len(r.kinds) + 1)]
    return [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)], kinds


GRID_WRONG_YD = 40.0  # blocked cells this close to a road that runs over blocked cells: the grid's error


def _in_cave(P, cont, x, y) -> bool:
    """Whether (x, y) is over one of the caves' own cells (Data/Caves.lua)."""
    r = P.OverlayRaw(cont, x, y) if P.OverlayRaw else None
    v, grid = r if isinstance(r, tuple) else (r, None)
    return v is not None and grid is not None and bool(grid.cave)


def _blocked_run(P, cont, pts, kinds, start, stop) -> float:
    """Longest run (yards) of impassable ground crossed by the route's off-road stretches,
    ignoring END_ALLOW_YD around the start and the stop, and ground beside a road that
    itself runs over "impassable" cells (a road there, e.g. drawn in game, says the grid is
    wrong there: getting on or off it isn't a routing error)."""
    wrong = []
    for i, k in enumerate(kinds):
        if k == 0:
            for (x, y) in (pts[i], pts[i + 1]):
                if P.At(cont, x, y) == 2:
                    wrong.append((x, y))
    worst, run = 0.0, 0.0
    for i, k in enumerate(kinds):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        seg = math.hypot(x2 - x1, y2 - y1)
        n = max(1, int(seg / 3))
        for j in range(n + 1):
            x, y = x1 + (x2 - x1) * j / n, y1 + (y2 - y1) * j / n
            near_end = math.hypot(x - start[0], y - start[1]) < END_ALLOW_YD or                 math.hypot(x - stop[0], y - stop[1]) < END_ALLOW_YD
            beside = any(math.hypot(x - wx, y - wy) < GRID_WRONG_YD for wx, wy in wrong)
            if k == 1 and not near_end and not beside and P.At(cont, x, y) == 2:
                run += seg / n
                worst = max(worst, run)
            else:
                run = 0.0
    return worst


def check(samples: int = 20, seed: int = 1, only: str | None = None, log=print, modes=("offroad",)) -> dict:
    """Random trips per zone, routed in each of `modes` ("offroad", "road")."""
    from .extract.pipeline import CONTINENTS

    lua, ns = _runtime()
    P, R = ns.Passability, ns.Router
    limits = (P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS)  # the addon's own, for its routes
    rnd = random.Random(seed)
    zones = []
    for mid in ns.Maps.keys():
        m = ns.Maps[mid]
        if m.type == 3 and m.bounds and m.continent in CONTINENTS and ns.Terrain[m.continent]:
            if only and only.lower() not in m.name.lower():
                continue
            zones.append((m.name, mid, m.continent, [m.bounds[i] for i in range(1, 5)]))
    zones.sort()
    flagged, table = [], []
    for name, mid, cont, (x0, y0, x1, y1) in zones:
        tried = done = detours = blocked = unreachable = 0
        while done < samples and tried < samples * 15:
            tried += 1
            sx, sy = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
            tx, ty = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
            straight = math.hypot(tx - sx, ty - sy)
            if not (100 <= straight <= 1500) or P.At(cont, sx, sy) != 0 or P.At(cont, tx, ty) != 0:
                continue
            if _in_cave(P, cont, sx, sy) or _in_cave(P, cont, tx, ty):
                continue  # (a spot over a cave is down in it: the grid's flat walk can't judge that way)
            # the reference walk: search as far as it takes
            P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS = 400000, 900 * 900
            ref = P.FindPath(cont, sx, sy, tx, ty)
            P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS = limits
            R.Reset()  # routes search again with the addon's limits
            if ref is None:
                unreachable += 1
                continue
            done += 1
            grid = ref[0] if isinstance(ref, tuple) else ref
            for mode in modes:
                R.Reset()
                r = R.Route(cont, sx, sy, tx, ty, lua.table(offroad=(mode == "offroad")))
                pts, kinds = _pts(r)
                run = _blocked_run(P, cont, pts, kinds, (sx, sy), (tx, ty))
                share, extra = (DETOUR_SHARE, DETOUR_YD) if mode == "offroad" else (ROAD_DETOUR_SHARE, ROAD_DETOUR_YD)
                issue = None
                if r.length > max(grid * share, grid + extra):
                    detours += 1
                    issue = "detour"
                if run >= BLOCKED_RUN_YD:
                    blocked += 1
                    issue = "blocked" if not issue else issue + "+blocked"
                if issue:
                    flagged.append({"zone": name, "uiMap": mid, "cont": cont, "mode": mode, "issue": issue,
                                    "start": [round(sx, 1), round(sy, 1)], "stop": [round(tx, 1), round(ty, 1)],
                                    "route_yd": round(r.length), "grid_walk_yd": round(grid),
                                    "straight_yd": round(straight), "blocked_run_yd": round(run)})
        table.append((name, done, detours, blocked, unreachable))
        log(f"  {name:32s} trips {done:3d}  detours {detours:2d}  blocked {blocked:2d}  (no walk {unreachable})")
    flagged.sort(key=lambda f: f["route_yd"] / max(1, f["grid_walk_yd"]), reverse=True)
    return {"samples": samples, "seed": seed, "modes": list(modes), "zones": [
        {"zone": z, "trips": d, "detours": de, "blocked": b, "unreachable": u} for z, d, de, b, u in table],
        "flagged": flagged}


def write_report(result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "report.json"
    p.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return p

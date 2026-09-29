"""Route sweep (`agps route-sweep`): random trips in random zones, routed the way the game
does it (terrain searches in the background, the player moving meanwhile), looking for what
`route-check` doesn't:

  * snapback:  the provisional route (a search still running) heads away from the stop while
               the settled one heads toward it (a U-turn to a road the other way)
  * flipflop:  walking the first stretch while searches run, the route's first leg keeps
               reversing direction
  * uturn:     the settled route goes well away from the stop and back, when the terrain allows
               a much shorter walk
  * hairpin:   a spike in the route: a turn of more than HAIRPIN_DEG next to a leg shorter than
               SPIKE_YD (not at the stop)
  * zigzag:    ZIGZAG_TURNS or more turns of over 60 degrees within ZIGZAG_YD on the terrain

Writes data/debug/route-sweep/report.json (flagged trips with their coordinates and zone,
worst first). Flagged trips can be turned into regression tests in app/tests.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from .routecheck import _in_cave, _pts, _runtime

AWAY_COS = -0.3  # a first stretch heading this far from the stop's direction: "away"
TOWARD_COS = 0.3
FIRST_YD = 60  # how much of the route's start sets its heading
UTURN_RISE_YD, UTURN_SHARE = 100, 0.3  # going this much further from the stop, then back
UTURN_REF_SHARE = 1.5  # ... when the route is this much longer than the terrain's walk
HAIRPIN_DEG, SPIKE_YD = 150, 25
ZIGZAG_YD, ZIGZAG_TURNS = 40, 3
WALK_STEP_YD, WALK_STEPS, WALK_PUMP_MS = 4, 12, 3


def _heading(pts, tx, ty) -> float:
    """Cosine between the route's first FIRST_YD and the straight way to the stop."""
    (sx, sy) = pts[0]
    x, y, done = sx, sy, 0.0
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        seg = math.hypot(bx - ax, by - ay)
        if done + seg >= FIRST_YD and seg > 0:
            t = (FIRST_YD - done) / seg
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            break
        x, y, done = bx, by, done + seg
    vx, vy, wx, wy = x - sx, y - sy, tx - sx, ty - sy
    a, b = math.hypot(vx, vy), math.hypot(wx, wy)
    return (vx * wx + vy * wy) / (a * b) if a > 1e-6 and b > 1e-6 else 1.0


def _rise(pts, tx, ty) -> float:
    """The most the route gets further from the stop than it already was (yards)."""
    best, low = 0.0, math.inf
    for (x, y) in pts:
        d = math.hypot(tx - x, ty - y)
        low = min(low, d)
        best = max(best, d - low)
    return best


def _angles(pts, tx, ty) -> tuple[int, int]:
    """Hairpins (spikes) and the worst zigzag count along the route."""
    segs = [(a, b) for a, b in zip(pts, pts[1:]) if math.hypot(b[0] - a[0], b[1] - a[1]) > 0.5]
    hair, turns = 0, []
    along = 0.0
    for (a, b), (c, d) in zip(segs, segs[1:]):
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (d[0] - c[0], d[1] - c[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        along += l1
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
        deg = math.degrees(math.acos(cos))
        at_stop = math.hypot(tx - b[0], ty - b[1]) < 15
        if deg > HAIRPIN_DEG and min(l1, l2) < SPIKE_YD and not at_stop:
            hair += 1
        if deg > 60:
            turns.append(along)
    zig = 0
    for i, t in enumerate(turns):
        zig = max(zig, sum(1 for u in turns[i:] if u - t <= ZIGZAG_YD))
    return hair, zig


def sweep(trips: int = 60, seed: int | None = None, only: str | None = None, log=print) -> dict:
    from .extract.pipeline import CONTINENTS

    seed = seed if seed is not None else random.randrange(1 << 30)
    lua, ns = _runtime()
    P, R = ns.Passability, ns.Router
    limits = (P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS)
    now = lua.eval("function() return os.clock() * 1000 end")
    rnd = random.Random(seed)
    zones = []
    for mid in ns.Maps.keys():
        m = ns.Maps[mid]
        if m.type == 3 and m.bounds and m.continent in CONTINENTS and ns.Terrain[m.continent]:
            if only and only.lower() not in m.name.lower():
                continue
            zones.append((m.name, int(mid), m.continent, [m.bounds[i] for i in range(1, 5)]))
    zones.sort()
    flagged, done, tried = [], 0, 0
    while done < trips and tried < trips * 40 and zones:
        tried += 1
        name, mid, cont, (x0, y0, x1, y1) = rnd.choice(zones)
        sx, sy = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        ang, dist = rnd.uniform(0, 2 * math.pi), rnd.uniform(60, 900)
        tx, ty = sx + math.cos(ang) * dist, sy + math.sin(ang) * dist
        if P.At(cont, sx, sy) != 0 or P.At(cont, tx, ty) != 0:
            continue
        if _in_cave(P, cont, sx, sy) or _in_cave(P, cont, tx, ty):
            continue
        P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS = 400000, 900 * 900
        ref = P.FindPath(cont, sx, sy, tx, ty)
        P.PATH_MAX_EXPANSIONS, P.PATH_MAX_CELLS = limits
        if ref is None:
            continue
        grid = ref[0] if isinstance(ref, tuple) else ref
        done += 1
        for offroad in (True, False):
            issues = []
            opts = lua.table(offroad=offroad, transient=True)
            # as in game: the searches in the background
            R.Reset()
            R.SYNC_WALKS = False
            first = R.Route(cont, sx, sy, tx, ty, opts)
            fpts, _ = _pts(first)
            # walking the provisional route a little while searches run: does it keep flipping?
            x, y, flips, last = sx, sy, 0, _heading(fpts, tx, ty) > 0
            for _ in range(WALK_STEPS):
                r = R.Route(cont, x, y, tx, ty, opts)
                p, _k = _pts(r)
                h = _heading(p, tx, ty) > 0
                flips += h != last
                last = h
                if len(p) > 1:
                    (ax, ay), (bx, by) = p[0], p[1]
                    seg = math.hypot(bx - ax, by - ay)
                    if seg > 0:
                        x, y = ax + (bx - ax) / seg * min(WALK_STEP_YD, seg), ay + (by - ay) / seg * min(WALK_STEP_YD, seg)
                R.Pump(now() + WALK_PUMP_MS, now)
            while R.HasWork():
                R.Pump(now() + 200, now)
            settled = R.Route(cont, sx, sy, tx, ty, opts)
            R.SYNC_WALKS = True
            spts, _ = _pts(settled)
            h_first, h_settled = _heading(fpts, tx, ty), _heading(spts, tx, ty)
            if first.pending and h_first < AWAY_COS and h_settled > TOWARD_COS:
                issues.append("snapback")
            if flips >= 3:
                issues.append("flipflop")
            rise = _rise(spts, tx, ty)
            if rise > max(UTURN_RISE_YD, UTURN_SHARE * dist) and settled.length > grid * UTURN_REF_SHARE + 50:
                issues.append("uturn")
            hair, zig = _angles(spts, tx, ty)
            if hair:
                issues.append("hairpin")
            if zig >= ZIGZAG_TURNS:
                issues.append("zigzag")
            if issues:
                flagged.append({"zone": name, "uiMap": mid, "cont": cont, "mode": "offroad" if offroad else "road",
                                "issues": issues, "start": [round(sx, 1), round(sy, 1)], "stop": [round(tx, 1), round(ty, 1)],
                                "straight_yd": round(dist), "grid_walk_yd": round(grid),
                                "first_yd": round(first.length), "settled_yd": round(settled.length),
                                "first_heading": round(h_first, 2), "settled_heading": round(h_settled, 2),
                                "flips": flips, "rise_yd": round(rise), "hairpins": hair, "zigzag": zig})
                log(f"  {name}: {'offroad' if offroad else 'road'} {', '.join(issues)} "
                    f"({sx:.0f}, {sy:.0f}) -> ({tx:.0f}, {ty:.0f})")
    rank = {"snapback": 0, "flipflop": 1, "uturn": 2, "hairpin": 3, "zigzag": 4}
    flagged.sort(key=lambda f: min(rank[i] for i in f["issues"]))
    return {"seed": seed, "trips": done, "flagged": flagged}


def write_report(result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "report.json"
    p.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return p

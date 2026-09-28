"""Caves and mines on the open continents (Data/Caves.lua).

A cave is a WMO placed in the continent's ADT tiles (MODF): minor dungeons such as mines,
mountain caves, dens, crypts, hives and tunnels (world/wmo/dungeon/md_*, CAVE_KINDS). Each is
walked in from the surface, so it is merged into its continent's level, like the Ruins of
Lordaeron over Undercity (cities.py):
- a grid laid over the continent's (ns.Terrain["cave<uid>"], `overlay = true`, `cave = true`),
  listed in ns.CityHalls[continent], from the model's collidable floors and walls
  (walknet.py): the floors reached on foot from the ground at its mouth (its outdoor groups
  meeting walkable terrain), the lowest in each cell. 0 open, 2 closed, 1 the continent's
  (outside it, and its rock where the ground over it is walkable), 3 its floor under walkable
  ground (a mine under a hill: who stands there may be up top or down in it);
- its roads (the floors' centerlines, stairs found in 3D, one-way drops off ledges, out onto
  the ground at each mouth), all caves of a continent in one entry of
  ns.RoadOverlays[continent]. From each mouth a road runs on to the continent's nearest road
  reached on foot (RoadFinder: a walk over its grid), and ends on it (`joins`: the addon ties
  it there, Router.JoinOnto).
`agps caves` renders each one (data/debug/caves/) and lists what's covered and skipped.
"""

from __future__ import annotations

import json
import math
import struct
from collections import defaultdict

import numpy as np

from . import interiors as I
from . import walknet
from .extract import adt
from .extract.spike import ClientData
from .roads.terrain import MCNK_HEADER, encode_row

CELL = walknet.CELL
FLOOR_SLOPE = 0.64  # a floor's normal at least this upright (about 50 degrees: what a character walks up)
SMOOTH = 2.0  # yards: roads simplified this far from their centerlines
GROUND_REACH = 24.0  # yards: the ground outside a mouth taken into the cave's grid
PRUNE = 12.0  # yards: dead-end road stubs shorter than this go (a cave's side pockets stay)
FILL = 12  # cells: closed spots inside a floor up to this big (boulders) are no fork in its road
ENTRANCE_MAX = 500.0  # yards: a mouth's road runs on to the continent's nearest road this near
MIN_ROAD = 30.0  # yards: a cave with less road than this is left out (a nook in a cliff)
# Minor dungeons walked into from the surface (world/wmo/dungeon/<kind>/...): caves, mines,
# dens, tunnels, crypts, barrows, hives, and the cave in front of the Wailing Caverns.
CAVE_KINDS = ("md_caveden", "md_cavetunnels", "md_goldmine", "md_hordemine", "md_mountaincave", "md_spidermine",
              "md_animalden", "md_dwarven tunnels", "md_timbermawhold", "md_hive", "md_barrowdens",
              "md_barrowdensonerm", "md_crypt", "md_cryptonerm", "md_cryptschool", "md_cryptsimpleent",
              "md_ogremound", "md_anvilmarpass", "md_stratholme_plaguewood_tunnel", "worgenmicro", "kl_wailing")


class Ground:
    """The continent's terrain: height, and whether it's walkable (not too steep, not under
    water, not a hole), sampled anywhere (bilinear over the chunks' outer vertices)."""

    def __init__(self, cd: ClientData, cont: int):
        m = next(r for r in cd.table("Map") if r["ID"] == cont)
        self.cd = cd
        self.wdt = adt.parse_wdt(cd.casc.read(m["WdtFileDataID"]))
        self.tiles: dict = {}

    def _tile(self, tx: int, ty: int):
        if (tx, ty) in self.tiles:
            return self.tiles[(tx, ty)]
        from .roads.terrain import tile_grid
        t = self.wdt.tiles.get((tx, ty))
        out = None
        if t and t.root:
            root = self.cd.casc.read(t.root)
            steep, water = tile_grid(root)
            V = np.full((129, 129), np.nan)
            holes = np.zeros((128, 128), bool)
            for magic, a, b in adt.iter_chunks(root):
                if magic != "MCNK":
                    continue
                flags = struct.unpack_from("<I", root, a)[0]
                ix, iy = struct.unpack_from("<II", root, a + 4)
                if ix >= 16 or iy >= 16:
                    continue
                base = struct.unpack_from("<f", root, a + 0x68 + 8)[0]
                for m2, a2, b2 in adt.iter_chunks(root, a + MCNK_HEADER, b):
                    if m2 == "MCVT" and b2 - a2 >= 145 * 4:
                        mcvt = np.frombuffer(root[a2:a2 + 145 * 4], np.float32)
                        V[iy * 8:iy * 8 + 9, ix * 8:ix * 8 + 9] = np.array([mcvt[i * 17:i * 17 + 9] for i in range(9)]) + base
                        break
                h = np.zeros((8, 8), bool)
                if flags & 0x10000:  # high-res holes: a byte per row of quads, a bit per column
                    hb = struct.unpack_from("<8B", root, a + 0x14)
                    for i in range(8):
                        for j in range(8):
                            h[i, j] = bool(hb[i] >> j & 1)
                else:  # 4x4, each 2x2 quads
                    lo = struct.unpack_from("<H", root, a + 0x3C)[0]
                    for i in range(8):
                        for j in range(8):
                            h[i, j] = bool(lo >> ((i // 2) * 4 + j // 2) & 1)
                holes[iy * 8:iy * 8 + 8, ix * 8:ix * 8 + 8] = h
            out = (V, steep | water | holes, holes)
        self.tiles[(tx, ty)] = out
        return out

    def sample(self, X, Y):
        """(height, walkable) at world points (arrays)."""
        X, Y = np.asarray(X, float), np.asarray(Y, float)
        T, Q = adt.TILE_YD, adt.TILE_YD / 128
        h = np.full(X.shape, np.nan)
        ok = np.zeros(X.shape, bool)
        tx = np.floor(32 - Y / T).astype(int)
        ty = np.floor(32 - X / T).astype(int)
        for key in set(zip(tx.ravel().tolist(), ty.ravel().tolist())):
            t = self._tile(*key)
            if t is None:
                continue
            V, bad, _ = t
            sel = (tx == key[0]) & (ty == key[1])
            fi = ((32 - key[1]) * T - X[sel]) / Q
            fj = ((32 - key[0]) * T - Y[sel]) / Q
            i = np.clip(fi.astype(int), 0, 127)
            j = np.clip(fj.astype(int), 0, 127)
            u, v = fi - i, fj - j
            h[sel] = (V[i, j] * (1 - u) * (1 - v) + V[i + 1, j] * u * (1 - v) + V[i, j + 1] * (1 - u) * v
                      + V[i + 1, j + 1] * u * v)
            ok[sel] = ~bad[i, j]
        return h, ok & np.isfinite(h)


def cave_name(cd: ClientData, p, w, names_by) -> str:
    return names_by.get((w.wmo_id, p.name_set), "") or names_by.get((w.wmo_id, 0), "")


def find_caves(cd: ClientData, cont: int) -> list:
    """The caves placed on a continent: (placement, model path, name)."""
    areas = {r["ID"]: r["AreaName_lang"] for r in cd.table("AreaTable")}
    names_by = {}
    for r in cd.table("WMOAreaTable"):
        if r["WMOGroupID"] == -1:
            names_by[(r["WMOID"], r["NameSetID"])] = r["AreaName_lang"] or areas.get(r["AreaTableID"], "") or ""
    out = []
    for p in I.placements(cd, cont):
        path = cd.name(p.wmo) or ""
        parts = path.split("/")
        if len(parts) < 4 or parts[2] != "dungeon" or parts[3] not in CAVE_KINDS:
            continue
        w = I.read_wmo(cd, p.wmo)
        if not w:
            continue
        out.append((p, path, cave_name(cd, p, w, names_by)))
    out.sort(key=lambda t: t[0].uid)
    return out


OPEN, CONT, CLOSED, FLOOR_UNDER = 0, 1, 2, 3  # the overlay's cell values (see caves_lua)
SHORT = 15  # the grids' short runs (4 values: see terrain.encode_row)


def build_cave(cd: ClientData, p, ground: Ground, label: str, log=print, cont_at=None) -> dict | None:
    """One cave's grid (over the continent's) and roads, in world coordinates. `cont_at(X, Y)`:
    the continent's own grid values there (arrays), to tell the ground open over the cave."""
    from scipy import ndimage

    xf = walknet.Placed(p)
    floors, walls, liquids = walknet.model_faces(cd, p.wmo, FLOOR_SLOPE)
    if not floors:
        return None
    # (its mouth: the floors of its outdoor groups, MOGI flag 0x8, where the ground leads in)
    groups = I.read_wmo(cd, p.wmo).groups
    outdoor = {gi for gi, (flags, _bb) in enumerate(groups) if flags & 0x8}
    fl, wl, lq = [], [], []
    for gi, z, tri in floors:
        w3 = [xf(v) for v in tri]
        fl.append(([(q[0], q[1]) for q in w3], [q[2] for q in w3], False, gi in outdoor))
    for gi, (zlo, zhi), tri in walls:
        w3 = [xf(v) for v in tri]
        zs = [q[2] for q in w3]
        wl.append(((min(zs), max(zs)), [(q[0], q[1]) for q in w3], zs))
    for gi, (x0, y0, x1, y1), lz in liquids:
        corners = [xf((qx, qy, lz)) for qx, qy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        lq.append(([(q[0], q[1]) for q in corners], sum(q[2] for q in corners) / 4))
    u = walknet.build(fl, wl, lq, label=label, ground=ground.sample, ground_reach=GROUND_REACH, prune=PRUNE, fill=FILL,
                      log=lambda *a: None)
    H, W = u["H"], u["W"]
    # the cave's own cells: the model's footprint (its floors, the rock between them), and
    # the ground taken in at its mouth
    fp = ndimage.binary_closing(u["model"] | (u["has"] & ~u["ground"]), iterations=3)
    fp = ndimage.binary_fill_holes(fp) & ~u["ground"]
    walk = u["walk"]
    # (the ground at its mouths stays the continent's: only the cave's own cells are its)
    cells = np.where(fp, np.where(walk, OPEN, CLOSED), CONT).astype(np.uint8)
    # under open ground (a mine under a hill): the ground over it is walkable too, so the
    # continent's grid stays in charge of the rock there (CONT), and its floors are marked
    # (FLOOR_UNDER): who stands there may be up top or down below
    rows, cols = np.mgrid[0:H, 0:W]
    X, Y = u["px_to_world"](rows, cols)
    gh, _ = ground.sample(X, Y)
    up = (cont_at(X, Y) != 2) if cont_at else np.isfinite(gh)  # (its rock: closed only where the continent's grid is too)
    cells[fp & ~walk & up] = CONT
    cells[fp & walk & up & (gh > u["top"] + walknet.HEAD + 2)] = FLOOR_UNDER
    u.update({"footprint": fp, "overlay": cells})
    return u


START_SLACK = 16.0  # yards: blocked ground passed at a mouth (it opens in a steep hillside)
WALK_BLOCKED = 12.0  # a yard over ground the continent's grid calls blocked costs this many
WALK_BLOCKED_MAX = 30.0  # yards: a way out crossing more of that is none


class RoadFinder:
    """The way from a cave's mouth to the continent's nearest road reached on foot: a walk
    over the continent's own grid (Data/Terrain.lua's, as the addon's walks around go), up to
    ENTRANCE_MAX yards."""

    def __init__(self, grid: dict, roads):
        self.cells, self.tx0, self.ty0, self.cell = grid["cells"], grid["tileX0"], grid["tileY0"], grid["cellYd"]
        self.k = walknet.TILE / self.cell
        self.road = {}  # grid cell -> a point of a road in it
        for e in roads.edges.values():
            for p_, q in zip(e.pts, e.pts[1:]):
                n = int(math.hypot(*(q - p_)) / 2) + 1
                for i in range(n + 1):
                    x, y = p_ + (q - p_) * i / n
                    self.road.setdefault(self.rc(x, y), (float(x), float(y)))

    def rc(self, x, y):
        return int(((32 - x / walknet.TILE) - self.ty0) * self.k), int(((32 - y / walknet.TILE) - self.tx0) * self.k)

    def xy(self, r, c):
        return (32 - self.ty0 - (r + 0.5) / self.k) * walknet.TILE, (32 - self.tx0 - (c + 0.5) / self.k) * walknet.TILE

    def walk(self, a, inside):
        """From a (a mouth) to the nearest road: (yards, points ending on the road), or None.
        `inside(x, y)`: the cave's own cells (rock or floor), not walked through."""
        from skimage.graph import MCP_Geometric

        R = int(ENTRANCE_MAX / self.cell) + 1
        r0, c0 = self.rc(*a)
        H_, W_ = self.cells.shape
        ra, rb, ca, cb = max(r0 - R, 0), min(r0 + R + 1, H_), max(c0 - R, 0), min(c0 + R + 1, W_)
        sub = self.cells[ra:rb, ca:cb]
        # (blocked cells at a heavy cost: the grid closes a thin ridge now and then that the
        # ground itself doesn't; a way crossing more than WALK_BLOCKED_MAX of them is none)
        cost = np.where(sub == 2, WALK_BLOCKED, np.where(sub == 1, 1.5, 1.0))
        rr, cc = np.mgrid[ra:rb, ca:cb]
        near = np.hypot(rr - r0, cc - c0) * self.cell <= START_SLACK
        cost[near & (sub == 2)] = 2.0
        X, Y = self.xy(rr, cc)
        own = np.vectorize(inside)(X, Y)
        cost[own & (np.hypot(rr - r0, cc - c0) > 1.5)] = np.inf
        ends = [(r - ra, c - ca) for (r, c) in self.road if ra <= r < rb and ca <= c < cb and np.isfinite(cost[r - ra, c - ca])]
        if not ends:
            return None
        m = MCP_Geometric(cost)
        cum, _ = m.find_costs([(r0 - ra, c0 - ca)], ends, find_all_ends=False)
        best = min(ends, key=lambda q: cum[q])
        if not np.isfinite(cum[best]) or cum[best] * self.cell > ENTRANCE_MAX * 2:
            return None
        cells_ = [(r + ra, c + ca) for r, c in m.traceback(best)]
        steep = sum(self.cell * math.hypot(q[0] - p_[0], q[1] - p_[1]) for p_, q in zip(cells_, cells_[1:])
                    if self.cells[q] == 2 and not near[q[0] - ra, q[1] - ca])
        if steep > WALK_BLOCKED_MAX:
            return None
        end = self.road[cells_[-1]]
        pts = [a] + [self.xy(*q) for q in cells_[1:-1]] + [end]

        def clear(p_, q):  # (a straight line over cells a walk may take)
            n = max(1, int(math.hypot(q[0] - p_[0], q[1] - p_[1]) / (self.cell / 3)))
            for i in range(n + 1):
                x, y = p_[0] + (q[0] - p_[0]) * i / n, p_[1] + (q[1] - p_[1]) * i / n
                r, c = self.rc(x, y)
                if not (ra <= r < rb and ca <= c < cb) or cost[r - ra, c - ca] > 2:
                    return False
            return True

        out, i = [pts[0]], 0
        while i < len(pts) - 1:
            j = len(pts) - 1
            while j > i + 1 and not clear(pts[i], pts[j]):
                j -= 1
            out.append(pts[j])
            i = j
        return float(cum[best]) * self.cell, out


def shipped_roads(cont: int):
    """The continent's roads as the addon ships them (Data/Roads.lua): a RoadGraph. (The caves'
    ways out end on these; data/roads_<map>.json is what they're written from.)"""
    import re

    from .paths import ADDON_DIR
    from .roads.graph import RoadGraph

    g = RoadGraph()
    path = ADDON_DIR / "Data" / "Roads.lua"
    if not path.exists():
        return g
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^  \[%d\] = \{\n    n = \{([^}]*)\},\n    e = \{\n(.*?)\n    \},\n  \}," % cont, text, re.S | re.M)
    if not m:
        return g
    v = [float(t) for t in m.group(1).split(",") if t]
    for i in range(0, len(v), 2):
        g.add_node((v[i], v[i + 1]))
    for line in m.group(2).splitlines():
        f = [float(t) for t in line.strip().strip("{},").split(",") if t]
        if len(f) >= 8:
            g.add_edge(int(f[0]) - 1, int(f[1]) - 1, np.array(f[4:]).reshape(-1, 2))
    return g


def build_continent(cd: ClientData, cont: int, data_dir, log=print, only=None, report=None) -> list[dict]:
    """Every cave on a continent: its overlay grid, roads and mouths (with the entrance
    roads out to the continent's roads)."""
    from scipy import ndimage
    from .roads.graph import RoadGraph

    from .roads.terrain import continent_grid

    ground = Ground(cd, cont)
    roads = shipped_roads(cont)
    if not roads.edges:  # (no addon data yet: the extracted network)
        roads_path = data_dir / f"roads_{cont}.json"
        roads = RoadGraph.from_json(json.loads(roads_path.read_text(encoding="utf-8"))) if roads_path.exists() else RoadGraph()
    cg = continent_grid(cd, cont, log=lambda *a: None)
    ck = walknet.TILE / cg["cellYd"]

    finder = RoadFinder(cg, roads)

    def cont_at(X, Y):  # the continent's grid (Data/Terrain.lua) at world points
        r = np.clip((((32 - X / walknet.TILE) - cg["tileY0"]) * ck).astype(int), 0, cg["cells"].shape[0] - 1)
        c = np.clip((((32 - Y / walknet.TILE) - cg["tileX0"]) * ck).astype(int), 0, cg["cells"].shape[1] - 1)
        return cg["cells"][r, c]

    out = []
    caves = find_caves(cd, cont)
    log(f"  caves [{cont}]: {len(caves)} placed")
    for p, path, name in caves:
        if only and not any(o.lower() in (name or "").lower() or o == str(p.uid) for o in only):
            continue
        label = f"{name or path.split('/')[-1]} ({p.uid})"
        try:
            u = build_cave(cd, p, ground, label, log, cont_at)
        except Exception as ex:  # (a model this reader can't take)
            log(f"    {label}: skipped ({ex!r})")
            if report is not None:
                report.append((cont, name, p.uid, path, "skipped", f"unreadable model ({ex!r})"))
            continue
        if u is None:
            continue
        g = u["graph"]
        if g.total_length() < MIN_ROAD:
            log(f"    {label}: skipped (only {g.total_length():.0f} yd of road)")
            if report is not None:
                report.append((cont, name, p.uid, path, "skipped", f"too small: {g.total_length():.0f} yd of road"))
            continue
        W_, H_ = u["W"], u["H"]
        fp = u["footprint"]

        def in_rock(x, y):
            r, c = u["world_to_px"](x, y)
            return 0 <= r < H_ and 0 <= c < W_ and bool(fp[r, c]) and not bool(u["walk"][r, c])

        # mouths: the roads on the ground outside each opening (a node there, or one made on a
        # road through it)
        glab, npatch = ndimage.label(u["ground"] & u["walk"], structure=np.ones((3, 3)))

        def patch_of(x, y):
            r, c = u["world_to_px"](x, y)
            return int(glab[r, c]) if 0 <= r < H_ and 0 <= c < W_ else 0

        by_patch = defaultdict(list)
        for nid, (x, y) in g.nodes.items():
            if patch_of(x, y):
                by_patch[patch_of(x, y)].append(nid)
        for eid, e in list(g.edges.items()):
            for i in range(1, len(e.pts) - 1):
                k = patch_of(*e.pts[i])
                if k and not by_patch.get(k):
                    by_patch[k].append(g.split_edge(eid, i - 1, e.pts[i]))
                    break
        mouths = [n for lst in by_patch.values() for n in lst]
        if not mouths:
            log(f"    {label}: skipped (no way in found from the ground)")
            if report is not None:
                report.append((cont, name, p.uid, path, "skipped", "no way in from the ground (no walkable ground at its floors' height)"))
            continue
        # (road pieces not reached from a mouth, walked or by stairs: left out)
        comp = {}
        for i, edges_ in enumerate(g.components()):
            for eid in edges_:
                comp[g.edges[eid].a] = comp[g.edges[eid].b] = i
        keep_c = {comp.get(n) for n in mouths}
        for eid, e in list(g.edges.items()):
            if comp.get(e.a) not in keep_c:
                g.remove_edge(eid)
        g.drop_isolated_nodes()
        # the way in: from each piece of ground at a mouth, the road out of it nearest a road of
        # the continent's (walking) runs on to that road
        def inside(x, y):
            r, c = u["world_to_px"](x, y)
            return 0 <= r < H_ and 0 <= c < W_ and bool(fp[r, c])

        joins = []
        for patch, lst in sorted(by_patch.items()):
            ways = []
            for nid in lst:
                if nid in g.nodes:
                    w = finder.walk(tuple(float(v) for v in g.nodes[nid]), inside)
                    if w:
                        ways.append((w[0], nid, w[1]))
            if not ways:
                nid = next((n for n in lst if n in g.nodes), None)
                if nid is not None:
                    x, y = g.nodes[nid]
                    log(f"      mouth ({x:.0f}, {y:.0f}): no road within {ENTRANCE_MAX:.0f} yd on foot")
                    joins.append((nid, None))
                continue
            yards, nid, pts = min(ways)
            end = g.add_node(pts[-1])
            g.add_edge(nid, end, pts, source="entrance")
            joins.append((end, pts[-1]))
        mouths = [n for n in mouths if n in g.nodes]
        u.update({"name": name, "path": path, "uid": p.uid, "placement": p, "joins": joins, "mouths": mouths})
        out.append(u)
        log(f"    {label}: {len(g.nodes)} nodes, {g.total_length():.0f} yd of road, {len(mouths)} mouths, "
            f"{sum(1 for _, q in joins if q)} joined, grid {u['W']}x{u['H']}")
        if report is not None:
            under = int((u["overlay"] == FLOOR_UNDER).sum()) / max(int(((u["overlay"] == FLOOR_UNDER) | (u["overlay"] == OPEN)).sum()), 1)
            report.append((cont, name, p.uid, path, "covered",
                           f"({p.x:.0f}, {p.y:.0f}): {g.total_length():.0f} yd of road, {len(mouths)} mouths, "
                           f"{sum(1 for _, q in joins if q)} joined to a road, {under * 100:.0f}% of its floor under walkable ground"))
    return out


def render_debug(u: dict, out_dir, scale: int = 4) -> None:
    """A cave's grid and roads as a PNG (and the grid as text) under out_dir: floors shaded by
    height, closed cells dark, the continent's cells white, the mouth's ground green; roads
    red, stairs blue, drops magenta, entrance roads orange, mouths ringed."""
    from pathlib import Path

    from PIL import Image, ImageDraw

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cells, top, has = u["overlay"], u["top"], u["has"]
    H, W = cells.shape
    open_ = (cells == OPEN) | (cells == FLOOR_UNDER)
    zs = top[has & open_]
    lo, hi = (float(zs.min()), float(zs.max())) if zs.size else (0.0, 1.0)
    img = np.full((H, W, 3), 255, np.uint8)
    shade = np.clip((top - lo) / max(hi - lo, 1e-6), 0, 1)
    img[open_] = np.stack([60 + 180 * shade, 60 + 180 * shade, 140 + 115 * shade], -1)[open_].astype(np.uint8)
    under = cells == FLOOR_UNDER  # (under open ground: tinted purple)
    img[under] = np.stack([110 + 140 * shade, 50 + 100 * shade, 140 + 115 * shade], -1)[under].astype(np.uint8)
    img[u["ground"] & u["walk"]] = (150, 220, 150)
    img[cells == CLOSED] = (70, 70, 70)
    im = Image.fromarray(img).resize((W * scale, H * scale), Image.NEAREST)
    dr = ImageDraw.Draw(im)

    def px(x, y):
        c, r = u["cellxy"](x, y)
        return c * scale, r * scale

    g = u["graph"]
    for e in g.edges.values():
        col = {"stair": (0, 0, 255), "entrance": (255, 140, 0)}.get(e.source, (220, 0, 0))
        if e.source.startswith("drop:"):
            col = (255, 0, 255)
        dr.line([px(*q) for q in e.pts], fill=col, width=2)
    for nid in u.get("mouths", []):
        x, y = px(*g.nodes[nid])
        dr.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(0, 120, 0), width=2)
    name = f"{u['uid']}_{(u.get('name') or 'cave').replace(' ', '_').replace(chr(39), '')}"
    im.save(out_dir / f"{name}.png")
    rows = ["".join(". #:"[v] if v < 4 else "?" for v in row) for row in cells]  # (open, the continent's, closed, floor under walkable ground)
    (out_dir / f"{name}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cave_roads(u: dict) -> tuple[list, list, dict]:
    """A cave's roads as written: nodes [(x, y)], edges [(a, b, points)] (node indices from 0),
    drops {edge index: yards}; simplified where they stay on the floor."""
    g = u["graph"]
    order = {nid: i for i, nid in enumerate(sorted(g.nodes))}
    nodes = [tuple(g.nodes[n]) for n in sorted(g.nodes)]
    edges, drops = [], {}
    for eid, e in g.edges.items():
        ends = [tuple(g.nodes[e.a])] + [tuple(q) for q in e.pts[1:-1]] + [tuple(g.nodes[e.b])]
        if e.source.startswith("drop:"):
            drops[len(edges)] = int(e.source[5:])
            pts = ends
        elif e.source == "entrance":
            pts = ends
        elif e.source == "stair" and eid in u["stair_z"]:
            pts = walknet.simplify_3d(ends, u["stair_z"][eid], SMOOTH, u["floor_at"])
        else:
            pts = walknet.unzig(walknet.simplify(ends, SMOOTH, u["is_open"], u["height_at"]), u["is_open"], u["height_at"])
        edges.append((order[e.a], order[e.b], pts))
    return nodes, edges, drops


def pack_points(pts) -> str:
    """A road's points after its first, each as the move from the last in whole yards (x, then
    y): two characters of the rows' alphabet each, the value plus 2048 (Router.lua unpacks)."""
    from .roads.terrain import ALPHABET

    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        for d in (x1 - x0, y1 - y0):
            v = int(d) + 2048
            assert 0 <= v < 4096, d
            out.append(ALPHABET[v >> 6] + ALPHABET[v & 63])
    return "".join(out)


def _crop(cells: np.ndarray):
    """The grid's rows and columns holding the cave's own cells: (r0, r1, c0, c1)."""
    rr, cc = np.nonzero(cells != CONT)
    if not rr.size:
        return 0, 1, 0, 1
    return int(rr.min()), int(rr.max()) + 1, int(cc.min()), int(cc.max()) + 1


def caves_lua(cd: ClientData, continents=(0, 1), log=print, data_dir=None, debug_dir=None, report=None) -> str:
    """Data/Caves.lua: every cave's grid over its continent's, and its roads."""
    from .paths import data_dir as _data_dir

    data_dir = data_dir or _data_dir()
    out = [f"-- GENERATED by `agps gen-addon-data` from client {cd.casc.version}. Do not edit by hand.",
           "-- Caves and mines on the continents (app/azerothgps/caves.py). Each one's grid is laid over its",
           "-- continent's (ns.Terrain[key], listed in ns.CityHalls[continent]): cells 0 open, 1 the continent's",
           "-- (its rock under walkable ground too), 2 closed, 3 its floor under walkable ground; short runs of",
           "-- up to 15, long ones' lengths in 2 digits, the rows in one string split by slashes. All of a",
           "-- continent's caves' roads are one entry of ns.RoadOverlays[continent]: joins, the ends of the",
           "-- roads out of the mouths (joined onto the continent's road there); bridge, the nodes outside",
           "-- that may be linked across gaps; drops, one-way roads off ledges (yards fallen). A road's",
           "-- points are packed: from its first node, each move in whole yards (caves.pack_points).",
           "local _, ns = ...",
           "ns.CityHalls = ns.CityHalls or {}",
           "ns.RoadOverlays = ns.RoadOverlays or {}",
           "ns.Caves = ns.Caves or {}"]
    k = walknet.TILE / CELL
    for cont in continents:
        built = build_continent(cd, cont, data_dir, log=log, report=report)
        if debug_dir:
            for u in built:
                render_debug(u, debug_dir)
        out.append(f"-- ns.Caves[{cont}] = {{ {{ name, grid key, x, y (its placement) }}, ... }}")
        out.append(f"ns.Caves[{cont}] = {{")
        for u in built:
            p = u["placement"]
            out.append(f"  {{ {_lua_str(u['name'] or '')}, \"cave{u['uid']}\", {p.x:.1f}, {p.y:.1f} }},")
        out.append("}")
        for u in built:
            cells = u["overlay"]
            r0, r1, c0, c1 = _crop(cells)
            sub = cells[r0:r1, c0:c1]
            out.append(f"ns.Terrain[\"cave{u['uid']}\"] = {{ tx0 = {u['tx0'] + c0 / k:.6f}, ty0 = {u['ty0'] + r0 / k:.6f}, "
                       f"cell = {CELL:.0f}, w = {sub.shape[1]}, h = {sub.shape[0]}, short = {SHORT}, long = 2, slack = 0, overlay = true, cave = true,")
            out.append('  rows = "' + "/".join(encode_row(row, SHORT, 2) for row in sub) + '" }')
        n_all, e_all, joins, bridge, drops = [], [], [], [], {}
        for u in built:
            base = len(n_all)
            nodes, edges, dr = cave_roads(u)
            order = {nid: i for i, nid in enumerate(sorted(u["graph"].nodes))}
            n_all += nodes
            for i, h in dr.items():
                drops[len(e_all) + i] = h
            e_all += [(a + base, b + base, pts) for a, b, pts in edges]
            joins += [order[j] + base for j, q in u["joins"] if q is not None and j in order]
            bridge += sorted({order[j] + base for j in u["mouths"] if j in order}
                             | {order[j] + base for j, q in u["joins"] if j in order})
        out.append("do -- the caves' roads (the format of Data/Roads.lua)")
        out.append(f"  local halls = ns.CityHalls[{cont}] or {{}}")
        out.append(f"  ns.CityHalls[{cont}] = halls")
        out.append(f"  for _, c in ipairs(ns.Caves[{cont}]) do halls[#halls + 1] = c[2] end")
        out.append(f"  local overlays = ns.RoadOverlays[{cont}] or {{}}")
        out.append(f"  ns.RoadOverlays[{cont}] = overlays")
        out.append("  overlays[#overlays + 1] = { cave = true,")
        out.append("  n = {" + ",".join(f"{x:.0f},{y:.0f}" for x, y in n_all) + "},")
        out.append("  e = {")
        for i, (a, b, pts) in enumerate(e_all):
            # (whole yards, from its nodes' own: see pack_points)
            pts = [tuple(int(round(v)) for v in n_all[a])] + [(int(round(x)), int(round(y))) for x, y in pts[1:-1]] +                 [tuple(int(round(v)) for v in n_all[b])]
            pts = [q for i_, q in enumerate(pts) if i_ == 0 or q != pts[i_ - 1]] if len(pts) > 2 else pts
            if len(pts) == 1:
                pts = pts * 2
            length = sum(math.hypot(q[0] - p_[0], q[1] - p_[1]) for p_, q in zip(pts, pts[1:]))
            src = 3 if i in drops else 0
            out.append(f"    {{{a + 1},{b + 1},{length:.0f},{src},\"{pack_points(pts)}\"}},")
        out.append("  },")
        out.append("  joins = {" + ",".join(str(j + 1) for j in joins) + "},")
        out.append("  bridge = {" + ",".join(str(j + 1) for j in bridge) + "},")
        out.append("  drops = {" + ", ".join(f"[{i + 1}] = {h}" for i, h in sorted(drops.items())) + "},")
        out.append("  }")
        out.append("end")
        log(f"  caves [{cont}]: {len(built)} written, {len(n_all)} road nodes, {len(e_all)} roads, {len(joins)} joined")
    return "\n".join(out) + "\n"

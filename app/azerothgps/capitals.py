"""Capital cities at ground level (Data/Capitals.lua): their streets are big city models
(WMOs), not ground textures, so the road extraction finds none in them.

Each capital is merged into its continent's level, like the caves (caves.py) and the Ruins of
Lordaeron (cities.py):
- a grid laid over the continent's (ns.Terrain["capital_<name>"], `overlay = true`), listed in
  ns.CityHalls[continent]: 0 open, 2 closed, 1 the continent's (outside the city's models);
  from the models' collidable floors and walls (walknet.py): the floors reached on foot from
  the ground at the city's gates, and in each cell the top one of them (its bridges and ramps
  over its streets; stairs and ramps between them are found in 3D);
- its roads (the floors' centerlines, the stairs, one-way drops off ledges), one entry of
  ns.RoadOverlays[continent] per capital, joined onto the continent's roads at the gates
  (`joins`: Router.JoinOnto ties them there);
- lifts (Thunder Bluff's elevators from Mulgore): a road from the shaft's top onto the land's road at its
  foot, its length counting the wait and the ride (LIFT_SECONDS).
`agps capitals` renders each one (data/debug/capitals/) with a summary; `--write` writes the file.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np

from . import interiors as I
from . import walknet
from .caves import (CELL, CLOSED, CONT, FLOOR_UNDER, OPEN, SHORT, Ground, RoadFinder, _crop, _lua_str, cave_roads, pack_points,
                    shipped_roads)
from .extract.spike import ClientData
from .roads.terrain import encode_row

FLOOR_SLOPE = 0.64  # a floor's normal at least this upright (about 50 degrees)
LIFT_REACH = 40.0  # yards: a lift's shaft joins the roads this near it, up top and at its foot
LIFT_SECONDS = 20  # waiting for a lift and the ride
GATE_REACH = 80.0  # yards: the ground this near a gate is where the city is walked into
GROUND_REACH = 30.0  # yards: the ground outside a gate taken into the city's grid
PRUNE = 12.0  # yards: dead-end road stubs shorter than this go
FILL = 0  # cells: closed spots inside a floor up to this big are no fork in its road (none: in a
# city a small closed spot may be a ledge's foot under a bridge, not a pillar)
MIN_PIECE = 40.0  # yards: road pieces not joined to the gates' this long or shorter are left out
# The streets: the city's floors give roads everywhere a character can walk (every square and hall
# sprouts branches and loops); the NPCs that walk the city (guards' patrols, couriers: the path files
# `agps npc-paths` reads) walk its streets. A road edge along a patrol is a street; the rest are kept
# only as the shortest ways from the streets to the gates, lifts and places (`streets`).
STREET_NEAR_YD = 6.0  # a road point this near a patrol is on a street
STREET_SHARE = 0.6  # ... an edge with this share of its points so is a street
STREET_MIN_YD = 25.0  # street pieces shorter than this (a patrol's turn in a doorway) don't count
PLACE_REACH_YD = 60.0  # a place's way starts at the city's road this near it
PATH_SOURCES = ("cmangos-classic-db", "azerothcore")


def terrain_liquids(cd: ClientData, cont: int, box) -> list:
    """The terrain's water (the ADTs' MH2O) over world box (x0, y0, x1, y1), as walknet.build's
    liquids: (xy polygon of each quad, surface height). A city model's floor under it (Stormwind's
    canal beds) is no way to walk, as under the model's own water."""
    import struct

    from .extract import adt

    x0, y0, x1, y1 = box
    T, Q = adt.TILE_YD, adt.TILE_YD / 128
    m = next(r for r in cd.table("Map") if r["ID"] == cont)
    wdt = adt.parse_wdt(cd.casc.read(m["WdtFileDataID"]))
    out = []
    for tx in range(int(32 - y1 / T), int(32 - y0 / T) + 1):
        for ty in range(int(32 - x1 / T), int(32 - x0 / T) + 1):
            t = wdt.tiles.get((tx, ty))
            if not t or not t.root:
                continue
            root = cd.casc.read(t.root)
            for magic, a, _b in adt.iter_chunks(root):
                if magic != "MH2O":
                    continue
                for ci in range(256):
                    off_inst, n_layers, _ = struct.unpack_from("<III", root, a + ci * 12)
                    if not n_layers or not off_inst:
                        continue
                    cy, cx = divmod(ci, 16)
                    for li in range(n_layers):
                        p = a + off_inst + li * 24
                        _t, _f, _mn, mx, qx0, qy0, w, h, off_mask, _ov = struct.unpack_from("<HHffBBBBII", root, p)
                        cells = np.zeros((8, 8), bool)
                        if off_mask:
                            nbits = w * h
                            raw = root[a + off_mask: a + off_mask + (nbits + 7) // 8]
                            bits = np.unpackbits(np.frombuffer(raw, np.uint8), bitorder="little")[:nbits]
                            cells[qy0:qy0 + h, qx0:qx0 + w] = bits.reshape(h, w).astype(bool)
                        else:
                            cells[qy0:qy0 + h, qx0:qx0 + w] = True
                        for yy, xx in zip(*np.nonzero(cells)):
                            i, j = cy * 8 + yy, cx * 8 + xx
                            X0, Y0 = (32 - ty) * T - i * Q, (32 - tx) * T - j * Q
                            X1, Y1 = X0 - Q, Y0 - Q
                            if X1 <= x1 and X0 >= x0 and Y1 <= y1 and Y0 >= y0:
                                out.append(([(X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)], float(mx)))
    return out


def patrol_points(cont: int, inside, data_dir=None) -> np.ndarray:
    """The NPCs' walks inside the city (inside(x, y)), a point every yard: (n, 2) world."""
    import json

    from .paths import data_dir as _data_dir

    base = Path(data_dir or _data_dir()) / "thirdparty"
    pts = []
    for src in PATH_SOURCES:
        f = base / src / f"paths_{cont}.geojson"
        if not f.exists():
            continue
        for feat in json.loads(f.read_text(encoding="utf-8"))["features"]:
            c = feat["geometry"]["coordinates"]
            for a, b in zip(c, c[1:]):
                d = math.dist(a[:2], b[:2])
                if d == 0 or d > 60 or not (inside(a[0], a[1]) or inside(b[0], b[1])):
                    continue  # (a jump, or outside the city)
                for k in range(int(d) + 1):
                    t = k / max(1, int(d))
                    pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return np.array(pts, float).reshape(-1, 2)


def _near_polyline(P, x, y) -> float:
    """Distance from (x, y) to the polyline P (n, 2)."""
    best = math.inf
    for (ax, ay), (bx, by) in zip(P[:-1], P[1:]):
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2)) if L2 > 0 else 0.0
        best = min(best, math.hypot(ax + vx * t - x, ay + vy * t - y))
    return best


def streets(g, patrols: np.ndarray, terminals: list, log=print, label="", keep=()) -> dict:
    """Prune the city's road graph `g` (in place) to its streets and the ways to `terminals`
    (node ids: the gates' roads, the nodes by the places): the edges along a patrol (STREET_*), then,
    from the biggest street piece outward, the shortest way over the rest of the roads to each other
    street piece and each terminal, until all are joined. Returns counts."""
    import heapq

    from scipy.spatial import cKDTree

    edges = dict(g.edges)
    if not edges:
        return {}
    street = set()
    if len(patrols):
        tree = cKDTree(patrols)
        for eid, e in edges.items():
            P = np.asarray(e.pts, float)
            d, _ = tree.query(P)
            if np.mean(d <= STREET_NEAR_YD) >= STREET_SHARE:
                street.add(eid)
    street |= set(keep) & set(edges)  # (edges something else joins onto: the floors under others)
    adj = defaultdict(list)
    for eid, e in edges.items():
        adj[e.a].append((e.b, eid, e.length))
        adj[e.b].append((e.a, eid, e.length))
    # the street pieces (connected by street edges), the short ones left out
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for eid in street:
        e = edges[eid]
        parent[find(e.a)] = find(e.b)
    pieces = defaultdict(lambda: [set(), set(), 0.0])  # root -> (nodes, edges, yards)
    for eid in street:
        e = edges[eid]
        pc = pieces[find(e.a)]
        pc[0].update((e.a, e.b))
        pc[1].add(eid)
        pc[2] += e.length
    groups = [(nodes, es) for nodes, es, yd in pieces.values() if yd >= STREET_MIN_YD]
    groups += [({t}, set()) for t in terminals if t in g.nodes]
    if not groups:
        return {}
    groups.sort(key=lambda gr: -sum(edges[e].length for e in gr[1]))
    # (each piece of the road graph on its own: Thunder Bluff's mesas are joined by their lifts over
    # the land, not over the city's roads)
    for eid, e in edges.items():
        parent[find(e.a)] = find(e.b)
    by_comp = defaultdict(list)
    for gr in groups:
        by_comp[find(next(iter(gr[0])))].append(gr)
    keep_nodes, keep_edges = set(), set()
    joined, unjoined = 0, 0
    for comp_groups in by_comp.values():
        keep_nodes |= comp_groups[0][0]
        keep_edges |= comp_groups[0][1]
        todo = comp_groups[1:]
        joined += _join(todo, keep_nodes, keep_edges, adj)
        unjoined += len([gr for gr in todo if not gr[0] <= keep_nodes])
    # the shortest way between every two terminals (a gate and a place, two places) over the whole
    # road graph: a route between them isn't sent round by the joining above
    ends = [t for t in dict.fromkeys(terminals) if t in g.nodes]
    for t in ends:
        dist, came = {t: 0.0}, {}
        heap = [(0.0, t)]
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist.get(n, math.inf):
                continue
            for m, eid, L in adj[n]:
                nd = d + L
                if nd < dist.get(m, math.inf):
                    dist[m], came[m] = nd, (n, eid)
                    heapq.heappush(heap, (nd, m))
        for o in ends:
            n = o
            while n in came:
                p, eid = came[n]
                keep_edges.add(eid)
                n = p
    return _prune(g, edges, street, keep_edges, terminals, joined, unjoined, log, label)


def _join(todo, keep_nodes, keep_edges, adj) -> int:
    """Join each group in `todo` (node set, edge set) to what's kept, nearest first, by the shortest
    way over the roads (adj); keep_nodes and keep_edges grow. How many were joined."""
    import heapq

    joined = 0
    while todo:
        todo = [gr for gr in todo if not gr[0] <= keep_nodes]  # (joined on the way to another)
        if not todo:
            break
        # the nearest group not yet joined, over the whole road graph from what's kept
        dist, came = {n: 0.0 for n in keep_nodes}, {}
        heap = [(0.0, n) for n in keep_nodes]
        heapq.heapify(heap)
        owner = {}
        for gi, (nodes, _es) in enumerate(todo):
            for n in nodes:
                owner.setdefault(n, gi)
        hit = None
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist.get(n, math.inf):
                continue
            if n in owner and n not in keep_nodes:
                hit = n
                break
            for m, eid, L in adj[n]:
                nd = d + L
                if nd < dist.get(m, math.inf):
                    dist[m], came[m] = nd, (n, eid)
                    heapq.heappush(heap, (nd, m))
        if hit is None:
            break  # (the rest can't be reached over the roads: left as they were cut)
        n = hit
        while n in came:
            p, eid = came[n]
            keep_edges.add(eid)
            keep_nodes.update((p, n))
            n = p
        gi = owner[hit]
        keep_nodes |= todo[gi][0]
        keep_edges |= todo[gi][1]
        todo.pop(gi)
        joined += 1
    return joined


def _prune(g, edges, street, keep_edges, terminals, joined, unjoined, log, label) -> dict:
    """Drop the roads not kept (and, of two between the same points, the longer; and stubs to
    nowhere); log and return the counts."""
    # (two ways between the same two points, round a statue: the shorter)
    by_pair = {}
    for eid in list(keep_edges):
        e = edges[eid]
        k = (min(e.a, e.b), max(e.a, e.b))
        if k in by_pair and edges[by_pair[k]].length <= e.length:
            keep_edges.discard(eid)
        else:
            if k in by_pair:
                keep_edges.discard(by_pair[k])
            by_pair[k] = eid
    dropped = 0.0
    for eid, e in edges.items():
        if eid not in keep_edges:
            dropped += e.length
            g.remove_edge(eid)
    # (stubs to nowhere: dead ends shorter than PRUNE that aren't a gate's or a place's way)
    ends = set(terminals)
    while True:
        deg = defaultdict(int)
        for e in g.edges.values():
            deg[e.a] += 1
            deg[e.b] += 1
        stubs = [eid for eid, e in g.edges.items() if e.length < PRUNE
                 and ((deg[e.a] == 1 and e.a not in ends) or (deg[e.b] == 1 and e.b not in ends))
                 and not (deg[e.a] == 1 and deg[e.b] == 1)]
        if not stubs:
            break
        for eid in stubs:
            dropped += g.edges[eid].length
            g.remove_edge(eid)
    g.drop_isolated_nodes()
    out = {"street_yd": round(sum(edges[e].length for e in street)), "kept_yd": round(g.total_length()),
           "dropped_yd": round(dropped), "joined": joined, "unjoined": unjoined}
    log(f"  {label}: streets {out['street_yd']} yd of patrols' roads; kept {out['kept_yd']} yd, dropped "
        f"{out['dropped_yd']} yd; {joined} pieces and places joined, {unjoined} not reached")
    return out


@dataclass
class Capital:
    name: str
    cont: int
    ui_map: int
    wmos: tuple  # the models' placements (MODF unique ids) the city is made of
    gates: tuple  # world (x, y) just outside each way in, on the ground
    places: tuple = ()  # (name, x, y): spots the checks route to (bank, flight master, ...)
    lifts: tuple = ()  # (x, y, z at the foot): lift shafts from the land below up into the city
    join_blocked: float = 30.0  # yards of blocked ground a way from a gate to the land's road may cross
    outside: tuple = ()  # (x, y): a spot on the land's road outside, where the checks start
    indoor: bool = False  # under a mountain (Ironforge): like a cave, the land over it is the continent's
    ground_above: float | None = None  # the ground higher than this is the city's too (Thunder Bluff's mesas)
    ground_reach: float = GROUND_REACH  # yards: the ground taken in from the models' floors


CAPITALS = [
    Capital("Orgrimmar", 1, 1454, (165042,), ((1352.0, -4372.0),),
            places=(("Wind Rider Master", 1677.6, -4315.7),), outside=(1310.0, -4388.0)),
    Capital("Ironforge", 0, 1455, (7706,), ((-5040.0, -805.0),),
            places=(("Gryphon Master", -4821.8, -1155.4), ("Deeprun Tram", -4838.0, -1318.0)),
            outside=(-5100.0, -741.0), indoor=True),
    # (the city's model; its harbor's docks are models of their own on the land's ground, left to it)
    Capital("Stormwind City", 0, 1453, (10047,), ((-9095.0, 412.0),),
            places=(("Gryphon Master", -8832.8, 478.6), ("Harbor boat", -8654.5, 1344.4)), outside=(-9120.0, 397.0)),
    # (the buildings, bridges and platforms on the mesas; the mesas' tops are its ground: the lifts from
    # Mulgore come up onto them)
    Capital("Thunder Bluff", 1, 1456, (179660, 179678, 179663, 179674, 179659, 179664, 179655, 179682, 179651, 179652,
                                       179656, 179681, 179679, 179661, 179675, 179650, 179658, 179677, 179605, 179654,
                                       179680, 179662), ((-1290.0, 188.0), (-1033.0, -40.0)),
            places=(("Wind Rider Master", -1197.2, 29.7),), outside=(-1334.0, 176.0), ground_above=100.0,
            ground_reach=150.0, join_blocked=0.0,
            lifts=((-1286.2, 189.7, 68.6), (-1308.4, 185.3, 68.6), (-1028.0, -28.4, 69.0), (-1037.3, -49.2, 69.0))),
    # (the city's model and its south gate, on Teldrassil's ground: all of it the city's)
    Capital("Darnassus", 1, 1457, (352798, 293133), ((9984.0, 1954.0),), outside=(9986.0, 1864.0), ground_above=0.0,
            ground_reach=150.0, places=(("Cenarion Enclave", 10250.0, 2516.7), ("Craftsmen's Terrace", 10183.3, 2283.3),
                                        ("Warrior's Terrace", 9950.0, 2316.7), ("Tradesmen's Terrace", 9716.7, 2283.3))),
]


def city_faces(cd: ClientData, cap: Capital, log=print):
    """The city's models' faces in the world: floors, walls (with their vertices' heights, like
    a cave's rock) and liquids, in walknet.build's format."""
    placed = {p.uid: p for p in I.placements(cd, cap.cont) if p.uid in cap.wmos}
    area_names = {(r["WMOID"], r["WMOGroupID"]): r["AreaName_lang"] or "" for r in cd.table("WMOAreaTable")}
    fl, wl, lq, named = [], [], [], []
    for uid in cap.wmos:
        p = placed.get(uid)
        if p is None:
            log(f"  {cap.name}: model {uid} not placed")
            continue
        xf = walknet.Placed(p)
        names = I.group_names(cd, I.read_wmo(cd, p.wmo), area_names)
        floors, walls, liquids = walknet.model_faces(cd, p.wmo, FLOOR_SLOPE)
        for gi, z, tri in floors:
            w3 = [xf(v) for v in tri]
            fl.append(([(q[0], q[1]) for q in w3], [q[2] for q in w3], False, True))
            if gi < len(names) and names[gi]:  # (the areas' names: the checks route to each)
                named.append((names[gi], sum(q[0] for q in w3) / 3, sum(q[1] for q in w3) / 3, sum(q[2] for q in w3) / 3))
        for gi, (zlo, zhi), tri in walls:
            w3 = [xf(v) for v in tri]
            zs = [q[2] for q in w3]
            wl.append(((min(zs), max(zs)), [(q[0], q[1]) for q in w3], zs))
        for gi, (x0, y0, x1, y1), lz in liquids:
            corners = [xf((qx, qy, lz)) for qx, qy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
            lq.append(([(q[0], q[1]) for q in corners], sum(q[2] for q in corners) / 4))
    return fl, wl, lq, named


def build_capital(cd: ClientData, cap: Capital, ground: Ground, finder: RoadFinder | None, log=print,
                  cont_at=None) -> dict | None:
    """One capital's grid (over the continent's), roads and gates, in world coordinates."""
    from scipy import ndimage

    fl, wl, lq, named = city_faces(cd, cap, log)
    if not fl:
        return None
    gates = np.array(cap.gates, float)
    # (the terrain's water over the city too: Stormwind's canals are the land's, their beds the model's)
    xs = [q[0] for f in fl for q in f[0]]
    ys = [q[1] for f in fl for q in f[0]]
    tl = terrain_liquids(cd, cap.cont, (min(xs), min(ys), max(xs), max(ys)))
    lq = lq + tl
    log(f"  {cap.name}: {len(tl)} quads of the terrain's water over the city")

    def ground_at_gates(X, Y):
        """The continent's ground, walkable only near the gates (the city is walked into there,
        not over its rim from the hills behind it)."""
        h, ok = ground.sample(X, Y)
        X, Y = np.asarray(X, float), np.asarray(Y, float)
        near = np.zeros(X.shape, bool)
        for gx, gy in gates:
            near |= np.hypot(X - gx, Y - gy) <= GATE_REACH
        if cap.ground_above is not None:  # (a city on its ground, Thunder Bluff's mesa tops: all of it)
            near |= h > cap.ground_above
        return h, ok & near

    u = walknet.build(fl, wl, lq, label=cap.name, ground=ground_at_gates, ground_reach=cap.ground_reach, prune=PRUNE,
                      fill=FILL, top_reached=True, road_pieces=True, ground_under=True, log=log)
    H, W = u["H"], u["W"]
    g = u["graph"]
    # the city's own cells: its models' footprint (floors, and the rock and walls between them)
    fp = ndimage.binary_closing(u["model"] | (u["has"] & ~u["ground"]), iterations=3)
    fp = ndimage.binary_fill_holes(fp) & ~u["ground"]
    if cap.ground_above is not None:
        # (a city on its own ground: that ground is its too, so a way onto it from the land below
        # is a straight line up its cliffs, not a walk the land's coarser grid finds up them)
        fp |= u["ground"] & u["walk"]
    walk = u["walk"]
    cells = np.where(fp, np.where(walk, OPEN, CLOSED), CONT).astype(np.uint8)
    if cap.indoor and cont_at is not None:
        # (a city under a mountain, like a cave: where the land over it is walkable, its rock is
        # the continent's grid, and its floor there is under walkable ground, FLOOR_UNDER)
        rows, cols = np.mgrid[0:H, 0:W]
        X, Y = u["px_to_world"](rows, cols)
        gh, _ = ground.sample(X, Y)
        up = cont_at(X, Y) != 2
        cells[fp & ~walk & up] = CONT
        cells[fp & walk & up & (gh > u["top"] + walknet.HEAD + 2)] = FLOOR_UNDER
    u.update({"footprint": fp, "overlay": cells, "name": cap.name, "capital": cap})
    # each named area's spot (the checks route to them): of its floors walked on (open, the
    # floor the grid shows), the one nearest their middle
    by_name = defaultdict(list)
    for name, x, y, z in named:
        r, c = u["world_to_px"](x, y)
        if 0 <= r < H and 0 <= c < W and u["walk"][r, c] and abs(u["top"][r, c] - z) < walknet.LEDGE:
            by_name[name].append((x, y))
    areas = []
    for name, pts in sorted(by_name.items()):
        if len(pts) >= 10:
            mx, my = np.median(np.array(pts), axis=0)
            areas.append((name,) + min(pts, key=lambda q: math.hypot(q[0] - mx, q[1] - my)))
    u["areas"] = areas

    # the gates: the roads on the ground outside each way in (a node there, or one made on a
    # road through it)
    glab, _ = ndimage.label(u["ground"] & walk, structure=np.ones((3, 3)))

    def patch_of(x, y):
        r, c = u["world_to_px"](x, y)
        return int(glab[r, c]) if 0 <= r < H and 0 <= c < W else 0

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
    # (road pieces not reached from a gate, walked or by stairs: left out)
    comp = {}
    for i, edges_ in enumerate(g.components()):
        for eid in edges_:
            comp[g.edges[eid].a] = comp[g.edges[eid].b] = i
    keep_c = {comp.get(n) for n in mouths}
    dropped = 0.0
    for eid, e in list(g.edges.items()):
        if comp.get(e.a) not in keep_c:
            dropped += e.length
            g.remove_edge(eid)
    g.drop_isolated_nodes()
    log(f"  {cap.name}: {dropped:.0f} yd of road not reached from a gate left out")

    def inside(x, y):
        r, c = u["world_to_px"](x, y)
        return 0 <= r < H and 0 <= c < W and bool(fp[r, c])

    # the streets: the roads along the NPCs' walks, and the ways from them to the gates, the lifts
    # and the places (the rest of the floors' roads, every square's branches and loops, dropped)
    if g.nodes:
        from scipy.spatial import cKDTree

        ids = list(g.nodes)
        ntree = cKDTree(np.array([g.nodes[n] for n in ids], float))
        spots = [(x, y) for _n, x, y in map_places(cap, u)] + [(lx, ly) for lx, ly, _lz in cap.lifts]
        # (the gates' roads near the city's gates: a city on its own ground has a way out of every
        # patch of it, not all gates)
        terminals = [n for n in mouths if n in g.nodes
                     and min(math.dist(g.nodes[n], gt) for gt in cap.gates) <= 2 * GATE_REACH]
        # (each place's and lift's nearest road: the edge itself kept, its ends terminals; the nearest
        # point is often along an edge, not at a node)
        keep = set()
        # (the roads joined to the gates' first: a piece of road on its own beside a place (its way out
        # a patch of ground far off) would take the place's way, and the gates' roads by it be dropped)
        parent = {}

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for e in g.edges.values():
            parent[find(e.a)] = find(e.b)
        gated = {find(t) for t in terminals}
        eids = list(g.edges)
        epts = [(k, q) for k, eid in enumerate(eids) for q in _densify(g.edges[eid].pts, 2.0)]
        etree = cKDTree(np.array([q for _k, q in epts], float))
        mpts = [(k, q) for k, q in epts if find(g.edges[eids[k]].a) in gated]
        mtree = cKDTree(np.array([q for _k, q in mpts], float)) if mpts else None
        for x, y in spots:
            d, i = mtree.query((x, y)) if mtree is not None else (math.inf, 0)
            pick = mpts[int(i)][0] if d <= PLACE_REACH_YD else None
            if pick is None:
                d, i = etree.query((x, y))
                pick = epts[int(i)][0] if d <= PLACE_REACH_YD else None
            if pick is not None:
                e = g.edges[eids[pick]]
                keep.add(eids[pick])
                terminals += [e.a, e.b]
            else:
                d, i = ntree.query((x, y))
                if d <= PLACE_REACH_YD:
                    terminals.append(ids[int(i)])
        # the floors under others first: their roads join the city's, whose edges there are kept
        u["under"] = build_under(fl, wl, lq, u, ground_at_gates, log)
        for jx, jy in (u["under"] or {}).get("join_xy", []):
            for eid, e in g.edges.items():
                P = np.asarray(e.pts, float)
                if np.min(np.hypot(P[:, 0] - jx, P[:, 1] - jy)) <= 1.0 or _near_polyline(P, jx, jy) <= 0.5:
                    keep.add(eid)
                    terminals += [e.a, e.b]
        u["streets"] = streets(g, patrol_points(cap.cont, inside), terminals, log, cap.name, keep=keep)

    joins = []
    for patch, lst in sorted(by_patch.items()):
        ways = []
        for nid in lst:
            if nid in g.nodes and finder is not None:
                w = finder.walk(tuple(float(v) for v in g.nodes[nid]), inside, cap.join_blocked)
                if w:
                    ways.append((w[0], nid, w[1]))
        if not ways:
            continue
        yards, nid, pts = min(ways)
        end = g.add_node(pts[-1])
        g.add_edge(nid, end, pts, source="entrance")
        joins.append((end, pts[-1]))
    # lifts: from the city's road nearest the shaft up top, down the shaft, onto the land's road
    # nearest its foot (at the foot's height: not one up on the city's ground over it)
    for lx, ly, lz in cap.lifts:
        near = sorted((math.hypot(q[0] - lx, q[1] - ly), n) for n, q in g.nodes.items())
        if not near or near[0][0] > LIFT_REACH:
            # (the streets kept an edge past the shaft, not a node by it: a node on that edge there)
            best = None
            for eid, e in g.edges.items():
                for i in range(len(e.pts) - 1):
                    d = math.hypot(e.pts[i + 1][0] - lx, e.pts[i + 1][1] - ly)
                    if i + 1 < len(e.pts) - 1 and d <= LIFT_REACH and (best is None or d < best[0]):
                        best = (d, eid, i)
            if best:
                e = g.edges[best[1]]
                n = g.split_edge(best[1], best[2], e.pts[best[2] + 1])
                near = [(best[0], n)]
        land = []
        if finder is not None:
            cand = [q for q in finder.road.values() if math.hypot(q[0] - lx, q[1] - ly) <= LIFT_REACH]
            if cand:
                h, _ = ground.sample(np.array([q[0] for q in cand]), np.array([q[1] for q in cand]))
                land = sorted((math.hypot(q[0] - lx, q[1] - ly), q) for q, z in zip(cand, h) if abs(z - lz) < 8)
        if not near or near[0][0] > LIFT_REACH or not land:
            log(f"  {cap.name}: lift at ({lx:.0f}, {ly:.0f}) not joined")
            continue
        end = g.add_node(land[0][1])
        g.add_edge(near[0][1], end, [g.nodes[near[0][1]], (lx, ly), land[0][1]], source="lift")
        joins.append((end, land[0][1]))
    u.update({"joins": joins, "mouths": [n for n in mouths if n in g.nodes]})
    log(f"  {cap.name}: {len(g.nodes)} nodes, {g.total_length():.0f} yd of road, {len(u['mouths'])} gate roads, "
        f"{len(joins)} joined, grid {W}x{H}")
    return u


STACK_GAP = 6  # yards: a floor this far under another reached one is a level of its own there
UNDER_MIN = 30  # cells: smaller floors under another are left to the one over them
UNDER_MARGIN = 6  # cells: an under floor's roads run on this far out from under (to the city's roads)
UNDER_JOIN = 12.0  # yards: ... and join the city's road this near their ends (on the same floor)


UP_TOP_YD = 8.0  # yards: around a flight master or a dock, a stop is on the floor over the others


def up_top_spots(cont: int) -> list:
    """Flight masters (Data/Pois.lua) and transport docks (Data/Transports.lua) on `cont`."""
    import re

    from .paths import ADDON_DIR

    out = []
    pois = (ADDON_DIR / "Data" / "Pois.lua").read_text(encoding="utf-8")
    m = re.search(r"^  \[%d\] = \{\n(.*?)\n  \},$" % cont, pois, re.S | re.M)
    if m:
        out += [(float(x), float(y)) for x, y in re.findall(r"\{1,(-?[\d.]+),(-?[\d.]+),\"", m.group(1))]
    tr = (ADDON_DIR / "Data" / "Transports.lua").read_text(encoding="utf-8")
    for c1, x1, y1, c2, x2, y2 in re.findall(r"\{ (\d+), (-?[\d.]+), (-?[\d.]+), (\d+), (-?[\d.]+), (-?[\d.]+),", tr):
        out += [(float(x1), float(y1))] if int(c1) == cont else []
        out += [(float(x2), float(y2))] if int(c2) == cont else []
    return out


def _densify(pts, step=1.0):
    out = [tuple(pts[0])]
    for p, q in zip(pts, pts[1:]):
        n = max(1, int(math.ceil(math.hypot(q[0] - p[0], q[1] - p[1]) / step)))
        out += [(p[0] + (q[0] - p[0]) * i / n, p[1] + (q[1] - p[1]) * i / n) for i in range(1, n + 1)]
    return out


def build_under(fl, wl, lq, u, ground_fn, log=print) -> dict | None:
    """The floors under the city's reached floors (a street under a bridge, the Cleft of Shadow
    under the Drag, a hall's ground floor under its roof walk): the grid shows each cell's top
    one, so these are a level of their own, laid over it like a cave's (`cave`, cells 3 where
    the floor under is open, else 1): a stop there is down on it, the player when lower than
    `split`. Their roads (the lowest floors' network, walknet with the lowest per cell) cut to
    around them, and joined onto the city's roads where they come out from under."""
    from scipy import ndimage

    bands = u["bands"]
    NB = bands.shape[0]
    has = bands.any(0)
    lowb = np.where(has, np.argmax(bands, 0), -1)
    topb = np.where(has, NB - 1 - np.argmax(bands[::-1], 0), -1)
    stacked = has & (topb - lowb >= STACK_GAP)
    if not stacked.any():
        return None
    lo = walknet.build(fl, wl, lq, label=u["name"] + " (under)", ground=ground_fn, ground_reach=u["capital"].ground_reach,
                       prune=PRUNE, fill=FILL, top_reached=False, road_pieces=True, ground_under=True, log=lambda *a: None)
    assert (lo["H"], lo["W"]) == (u["H"], u["W"])
    under = stacked & lo["walk"]
    lab, n = ndimage.label(ndimage.binary_closing(under, iterations=1) & under, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())
    keep = [i for i in range(1, n + 1) if sizes[i] >= UNDER_MIN]
    if not keep:
        return None
    region = np.isin(lab, keep)
    zone = ndimage.binary_dilation(region, iterations=UNDER_MARGIN) & lo["walk"]
    H, W = u["H"], u["W"]

    def in_zone(x, y):
        r, c = u["world_to_px"](x, y)
        return 0 <= r < H and 0 <= c < W and bool(zone[r, c])

    # the lower floors' roads, cut to the zone: runs inside it; a run's end where it was cut
    # is a way out from under
    nodes, edges, drops = cave_roads(lo)
    ends = {tuple(round(v, 3) for v in q) for q in nodes}
    runs = []  # (points, drop yards or None, [cut at start, cut at end])
    for i, (a, b, pts) in enumerate(edges):
        pts = [tuple(nodes[a])] + [tuple(q) for q in pts[1:-1]] + [tuple(nodes[b])]
        if i in drops:
            if in_zone(*pts[0]) or in_zone(*pts[-1]):
                runs.append((pts, drops[i], [not in_zone(*pts[0]), not in_zone(*pts[-1])]))
            continue
        dense = _densify(pts)
        cur = []
        for q in dense:
            if in_zone(*q):
                cur.append(q)
            elif cur:
                runs.append((cur, None, None))
                cur = []
        if cur:
            runs.append((cur, None, None))
    from .roads.graph import RoadGraph

    g = RoadGraph()
    at: dict = {}

    def node(q):
        key = (round(q[0], 1), round(q[1], 1))
        if key not in at:
            at[key] = g.add_node(q)
        return at[key]

    cuts = set()
    for pts, drop, cut in runs:
        if len(pts) < 2:
            continue
        if drop is None:
            cut = [tuple(round(v, 3) for v in pts[0]) not in ends, tuple(round(v, 3) for v in pts[-1]) not in ends]
            pts = walknet.simplify(pts, 0.5)
        a, b = node(pts[0]), node(pts[-1])
        if a == b:
            continue
        g.add_edge(a, b, pts, source=f"drop:{drop}" if drop is not None else "terrain")
        if cut[0]:
            cuts.add(a)
        if cut[1]:
            cuts.add(b)
    # joined onto the city's roads (as written) near each way out, on the same floor
    main_nodes, main_edges, main_drops = cave_roads(u)
    segs = []  # (a, b, the edge's index), drops too (only to keep joins clear of them)
    for i, (a, b, pts) in enumerate(main_edges):
        pts = [tuple(main_nodes[a])] + [tuple(q) for q in pts[1:-1]] + [tuple(main_nodes[b])]
        segs += [(p, q, i) for p, q in zip(pts, pts[1:])]

    def near(x, y, a, b):
        (ax, ay), (bx, by) = a, b
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2)) if L2 > 0 else 0.0
        qx, qy = ax + vx * t, ay + vy * t
        return math.hypot(qx - x, qy - y), qx, qy

    # (not onto a drop off a ledge, nor a stair: it may run under the floor the grid shows)
    no_join = set(main_drops) | {i for i, e in enumerate(u["graph"].edges.values()) if e.source == "stair"}
    joins, bridge, join_xy = [], [], []
    for m in sorted(cuts):
        x, y = g.nodes[m]
        hm = lo["height_at"](x, y)
        best = None
        for a, b, ei in segs:
            if ei in no_join:
                continue
            d, qx, qy = near(x, y, a, b)
            if d <= UNDER_JOIN and (best is None or d < best[0]):
                hq = u["height_at"](qx, qy)
                # (on the same floor, and no other road passing close by: one over or under
                # it, which the addon's join could take instead)
                if hm is not None and hq is not None and abs(hq - hm) < walknet.LEDGE and \
                        walknet.clear((x, y), (qx, qy), u["is_open"], 1, u["height_at"]) and \
                        all(near(qx, qy, a2, b2)[0] > 3.0 for a2, b2, e2 in segs if e2 != ei):
                    best = (d, qx, qy)
        bridge.append(m)
        if best:
            j = g.add_node((best[1], best[2]))
            g.add_edge(m, j, [(x, y), (best[1], best[2])], source="entrance")
            joins.append(j)
            join_xy.append((best[1], best[2]))
    # (pieces with no way out: left out)
    comp = {}
    for i, edges_ in enumerate(g.components()):
        for eid in edges_:
            comp[g.edges[eid].a] = comp[g.edges[eid].b] = i
    out_c = {comp.get(j) for j in joins}
    for eid, e in list(g.edges.items()):
        if comp.get(e.a) not in out_c:
            g.remove_edge(eid)
    g.drop_isolated_nodes()
    joins = [j for j in joins if j in g.nodes]
    bridge = [m for m in bridge if m in g.nodes]
    # the grids: one per piece under (its own split height). Around a flight master or a dock
    # (up on a tower, over the street) a stop is up top: left to the floor over it.
    tops = np.zeros((H, W), bool)
    for x, y in up_top_spots(u["capital"].cont):
        r, c = u["world_to_px"](x, y)
        R_ = int(UP_TOP_YD / CELL)
        tops[max(r - R_, 0):r + R_ + 1, max(c - R_, 0):c + R_ + 1] = True
    grids = []
    for i in keep:
        cells = (lab == i) & ~tops
        if not cells.any():
            continue
        split = float((np.median(lowb[cells]) + np.median(topb[cells])) / 2 + u["Z0"] + 0.5)
        grids.append({"cells": np.where(cells, 3, CONT).astype(np.uint8), "split": split})
    log(f"  {u['name']}: {len(keep)} floors under others ({int(region.sum())} cells), {len(g.nodes)} road nodes, "
        f"{g.total_length():.0f} yd of road under, {len(joins)} joined of {len(cuts)} ways out")
    return {"graph": g, "joins": joins, "bridge": bridge, "grids": grids, "region": region, "zone": zone, "low": lo,
            "join_xy": join_xy}


def build_all(cd: ClientData, data_dir, log=print, only=None) -> list[dict]:
    from .roads.terrain import continent_grid

    out = []
    by_cont = defaultdict(list)
    for cap in CAPITALS:
        if only and not any(o.lower() in cap.name.lower() for o in only):
            continue
        by_cont[cap.cont].append(cap)
    for cont, caps in sorted(by_cont.items()):
        ground = Ground(cd, cont)
        roads = shipped_roads(cont)
        cg = continent_grid(cd, cont, log=lambda *a: None)
        finder = RoadFinder(cg, roads) if roads.edges else None
        ck = walknet.TILE / cg["cellYd"]

        def cont_at(X, Y, cg=cg, ck=ck):  # the continent's grid (Data/Terrain.lua) at world points
            r = np.clip((((32 - X / walknet.TILE) - cg["tileY0"]) * ck).astype(int), 0, cg["cells"].shape[0] - 1)
            c = np.clip((((32 - Y / walknet.TILE) - cg["tileX0"]) * ck).astype(int), 0, cg["cells"].shape[1] - 1)
            return cg["cells"][r, c]

        for cap in caps:
            u = build_capital(cd, cap, ground, finder, log, cont_at)
            if u is not None:
                out.append(u)
    return out


def key_of(cap: Capital) -> str:
    return "capital_" + cap.name.lower().replace(" ", "_")


def capitals_lua(cd: ClientData, log=print, data_dir=None, debug_dir=None, built=None) -> str:
    """Data/Capitals.lua: each capital's grid over its continent's, its roads and lifts."""
    from .paths import data_dir as _data_dir

    data_dir = data_dir or _data_dir()
    if built is None:
        built = build_all(cd, data_dir, log=log)
    if debug_dir:
        for u in built:
            render_debug(u, debug_dir)
    k = walknet.TILE / CELL
    out = [f"-- GENERATED by `agps gen-addon-data` from client {cd.casc.version}. Do not edit by hand.",
           "-- Capital cities at ground level (app/azerothgps/capitals.py): their streets are city models, so",
           "-- each gets a grid laid over its continent's (ns.Terrain[key], listed in ns.CityHalls[continent]):",
           "-- cells 0 open, 1 the continent's, 2 closed; short runs of up to 15, long ones' lengths in 2 digits,",
           "-- the rows in one string split by slashes. Its roads are an entry of ns.RoadOverlays[continent]:",
           "-- joins, the ends of the roads out of its gates (joined onto the continent's road there); drops,",
           "-- one-way roads off ledges (yards fallen). A road's points are packed: from its first node, each",
           "-- move in whole yards (caves.pack_points).",
           "local _, ns = ...",
           "ns.CityHalls = ns.CityHalls or {}",
           "ns.RoadOverlays = ns.RoadOverlays or {}",
           "ns.Capitals = ns.Capitals or {}"]
    by_cont = defaultdict(list)
    for u in built:
        by_cont[u["capital"].cont].append(u)
    for cont, lst in sorted(by_cont.items()):
        out.append(f"-- ns.Capitals[{cont}] = {{ {{ name, grid key, uiMap }}, ... }}")
        out.append(f"ns.Capitals[{cont}] = {{")
        for u in lst:
            cap = u["capital"]
            out.append(f"  {{ {_lua_str(cap.name)}, \"{key_of(cap)}\", {cap.ui_map} }},")
        out.append("}")
        def grid(key, cells, tx0, ty0, extra=""):
            r0, r1, c0, c1 = _crop(cells)
            sub = cells[r0:r1, c0:c1]
            out.append(f"ns.Terrain[\"{key}\"] = {{ tx0 = {tx0 + c0 / k:.6f}, ty0 = {ty0 + r0 / k:.6f}, "
                       f"cell = {CELL:.0f}, w = {sub.shape[1]}, h = {sub.shape[0]}, short = {SHORT}, long = 2, slack = 0, "
                       f"overlay = true,{extra}")
            out.append('  rows = "' + "/".join(encode_row(row, SHORT, 2) for row in sub) + '" }')

        def roads(label, parts, cave):
            """One entry of the overlays: the parts (nodes, edges, drops, joins, bridge or None,
            extra yards per edge) one after the other, their node numbers moved on."""
            n_all, e_all, joins, bridge, drops = [], [], [], [], {}
            for nodes, edges, dr, jn, br, extra in parts:
                base = len(n_all)
                for i, (a, b, pts) in enumerate(edges):
                    pts = [tuple(int(round(v)) for v in nodes[a])] + [(int(round(x)), int(round(y))) for x, y in pts[1:-1]] + \
                        [tuple(int(round(v)) for v in nodes[b])]
                    pts = [q for i_, q in enumerate(pts) if i_ == 0 or q != pts[i_ - 1]] if len(pts) > 2 else pts
                    if len(pts) == 1:
                        pts = pts * 2
                    length = sum(math.hypot(q[0] - p_[0], q[1] - p_[1]) for p_, q in zip(pts, pts[1:]))
                    length += (extra or {}).get(i, 0)  # (a lift: its wait and ride, as yards walked)
                    if i in dr:
                        drops[len(e_all)] = dr[i]
                    e_all.append((a + base, b + base, length, pts))
                n_all += nodes
                joins += [j + base for j in jn]
                bridge += [j + base for j in (br or [])]
            if not e_all:
                return
            out.append(f"  overlays[#overlays + 1] = {{ capital = {_lua_str(label)},{' cave = true,' if cave else ''}")
            out.append("  n = {" + ",".join(f"{x:.0f},{y:.0f}" for x, y in n_all) + "},")
            out.append("  e = {")
            for i, (a, b, length, pts) in enumerate(e_all):
                out.append(f"    {{{a + 1},{b + 1},{length:.0f},{3 if i in drops else 0},\"{pack_points(pts)}\"}},")
            out.append("  },")
            out.append("  joins = {" + ",".join(str(j + 1) for j in joins) + "},")
            if cave:
                out.append("  bridge = {" + ",".join(str(j + 1) for j in bridge) + "},")
            out.append("  drops = {" + ", ".join(f"[{i + 1}] = {h}" for i, h in sorted(drops.items())) + "},")
            out.append("  }")
        halls = []  # (the floors under others first: their cells win over the city's own)
        for u in lst:
            cap = u["capital"]
            for i, gr in enumerate((u.get("under") or {}).get("grids", [])):
                key = f"{key_of(cap)}_under{i + 1}"
                grid(key, gr["cells"], u["tx0"], u["ty0"], f" cave = true, capital = true, split = {gr['split']:.1f},")
                halls.append(key)
        for u in lst:
            grid(key_of(u["capital"]), u["overlay"], u["tx0"], u["ty0"],
                 " capital = true," + (" cave = true," if u["capital"].indoor else ""))
            halls.append(key_of(u["capital"]))
        out.append("do -- the capitals' roads (the format of Data/Roads.lua)")
        out.append(f"  local halls = ns.CityHalls[{cont}] or {{}}")
        out.append(f"  ns.CityHalls[{cont}] = halls")
        out.append("  for _, key in ipairs({ " + ", ".join(f'"{h}"' for h in halls) + " }) do halls[#halls + 1] = key end")
        out.append(f"  local overlays = ns.RoadOverlays[{cont}] or {{}}")
        out.append(f"  ns.RoadOverlays[{cont}] = overlays")
        # (one entry for the capitals' roads on the land's level, then one like the caves' for
        # those under others and a city under a mountain's: their joins may end on the first's)
        land, under = [], []
        for u in lst:
            nodes, edges, drops = cave_roads(u)
            order = {nid: i for i, nid in enumerate(sorted(u["graph"].nodes))}
            joins = [order[j] for j, q in u["joins"] if q is not None and j in order]
            lift_yd = {i: LIFT_SECONDS * 7 for i, e in enumerate(u["graph"].edges.values()) if e.source == "lift"}
            if u["capital"].indoor:  # (like a cave's: gap links only at its gates, not into the mountain)
                bridge = sorted({order[j] for j in u["mouths"] if j in order} | set(joins))
                under.append((nodes, edges, drops, joins, bridge, lift_yd))
            else:
                land.append((nodes, edges, drops, joins, None, lift_yd))
            log(f"  {u['capital'].name}: {len(nodes)} road nodes, {len(edges)} roads, {len(joins)} joined")
            un = u.get("under")
            if un and un["graph"].edges:
                g = un["graph"]
                order = {nid: i for i, nid in enumerate(sorted(g.nodes))}
                unodes = [tuple(g.nodes[n]) for n in sorted(g.nodes)]
                uedges, udrops = [], {}
                for e in g.edges.values():
                    if e.source.startswith("drop:"):
                        udrops[len(uedges)] = int(float(e.source[5:]))
                    uedges.append((order[e.a], order[e.b], [tuple(q) for q in e.pts]))
                # (no gap links to or from them: a straight line there may be up or down a level)
                under.append((unodes, uedges, udrops, [order[j] for j in un["joins"]], [], {}))
        roads("capitals", land, cave=False)
        roads("capitals (under others, in a mountain)", under, cave=True)
        out.append("end")
    return "\n".join(out) + "\n"


JUMP_TOL = 3.0  # yards: a step up or down from one sample to the next (half a yard on)
JUMP_CLIP = 5  # samples: a corner clipped (no floor about the height) before it counts
JUMP_MAX = 8.0  # yards: a jump bigger than this between levels is flagged (steep stairs are less)


def walk_3d(u: dict, pts, kinds, lifts=()) -> tuple:
    """Whether a route stays on the city's floors in 3D: the heights a walk along it may be at
    (every floor within JUMP_TOL of the last sample's), sample by sample, half a yard apart;
    drops (kind 4) may go down, and a lift's shaft (lifts: (x, y, z)) up or down. The worst jump
    between levels (yards) and where, or (0, None)."""
    bands, wall3, Z0 = u["bands"], u["wall3"], u["Z0"]
    H, W = u["H"], u["W"]
    zs, worst, where, miss = None, 0.0, None, 0
    for i, kd in enumerate(kinds):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / 0.5))
        for s in range(n + 1):
            x, y = x1 + (x2 - x1) * s / n, y1 + (y2 - y1) * s / n
            r, c = u["world_to_px"](x, y)
            if not (0 <= r < H and 0 <= c < W) or any(math.hypot(x - lx, y - ly) < LIFT_REACH / 2 for lx, ly, _ in lifts):
                zs = None
                continue
            fz = [Z0 + b + 0.5 for b in np.nonzero(bands[:, r, c] & ~wall3[:, r, c])[0]]
            if not fz:
                continue
            if zs is None:
                zs = fz
                continue
            nz = [f for f in fz if any((f <= z + JUMP_TOL) if kd == 4 else abs(f - z) <= JUMP_TOL for z in zs)]
            if not nz:
                miss += 1
                if miss <= JUMP_CLIP:
                    continue
                jump = min(abs(f - z) for f in fz for z in zs)
                if jump > worst:
                    part = "road" if kd == 0 else ("last leg" if i == len(kinds) - 1 else "leg")
                    worst, where = jump, (part, round(x), round(y))
                nz = fz
            miss = 0
            zs = nz
    return worst, where


def check_routes(built: list, log=print) -> list:
    """Routes (the addon's own, under lupa, over the data as written) from outside each gate to
    the capital's places: their share on roads, the last leg, and the 3D walk (walk_3d). Rows
    of text; the ones with a jump over JUMP_MAX or a long last leg are marked "!"."""
    from .routecheck import _pts, _runtime

    lua, ns = _runtime()
    R = ns.Router
    out = []
    for u in built:
        cap = u["capital"]
        start = cap.outside or cap.gates[0]
        for name, x, y in map_places(cap, u):
            R.Reset()
            r = R.Route(cap.cont, *start, x, y, lua.table(offroad=False))
            pts, kinds = _pts(r)
            road = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
                       for i, k in enumerate(kinds) if k == 0)
            last = math.hypot(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
            jump, where = walk_3d(u, pts, kinds, cap.lifts)
            closed = 0.0  # (yards of the legs off the roads through the city's closed cells)
            for i, k in enumerate(kinds):
                if k == 1:
                    (x1, y1), (x2, y2) = pts[i], pts[i + 1]
                    d = math.hypot(x2 - x1, y2 - y1)
                    n = max(1, int(d))
                    closed += sum(d / (n + 1) for s in range(n + 1)
                                  if ns.Passability.Overlay(cap.cont, x1 + (x2 - x1) * s / n, y1 + (y2 - y1) * s / n) == 2)
            bad = jump > JUMP_MAX or closed > 5
            out.append(f"{'!' if bad else ' '} {cap.name}: {name}: {r.length:.0f} yd, {road / max(r.length, 1):.0%} on roads, "
                       f"last leg {last:.0f} yd, {closed:.0f} yd off the roads through closed cells, 3D jump {jump:.0f} yd"
                       + (f" ({where[0]} at {where[1]}, {where[2]})" if where else ""))
            log(out[-1])
    return out


def map_places(cap: Capital, u: dict | None = None) -> list:
    """The city's places (Data/CityPlaces.lua, map %) in world yards, the check's own, and the
    city's named areas (u["areas"])."""
    import re

    from .paths import ADDON_DIR

    out = [tuple(p) for p in cap.places] + [("(area) " + n, x, y) for n, x, y in (u or {}).get("areas", [])]
    text = (ADDON_DIR / "Data" / "CityPlaces.lua").read_text(encoding="utf-8")
    m = re.search(r"\[%d\] = \{ city = [^\n]*\n(.*?)\n  \}," % cap.ui_map, text, re.S)
    maps = (ADDON_DIR / "Data" / "Maps.lua").read_text(encoding="utf-8")
    b = re.search(r"\[%d\] = \{[^\n]*\n\s*bounds = \{([^}]*)\}" % cap.ui_map, maps)
    if m and b:
        minX, minY, maxX, maxY = (float(v) for v in b.group(1).split(","))
        # (each with its NPC's height as a 4th value now: cityplaces.py)
        for u_, v_, name in re.findall(r"\{ ([\d.]+), ([\d.]+), \"([^\"]+)\"(?:, -?[\d.]+)? \}", m.group(1)):
            out.append((name, maxX - float(v_) / 100 * (maxX - minX), maxY - float(u_) / 100 * (maxY - minY)))
    return out


def render_debug(u: dict, out_dir, scale: int = 2) -> None:
    """A capital's grid and roads as a PNG (and the grid as text): floors shaded by height,
    closed cells dark, the continent's cells white, the gates' ground green, floors under
    others purple; roads red, stairs blue, drops magenta, entrance roads orange, roads under
    cyan, gates ringed, places as yellow dots; a line every 100 yards (labeled)."""
    from pathlib import Path

    from PIL import Image, ImageDraw

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cells, top, has = u["overlay"], u["top"], u["has"]
    H, W = cells.shape
    open_ = cells == OPEN
    zs = top[has & open_]
    lo, hi = (float(zs.min()), float(zs.max())) if zs.size else (0.0, 1.0)
    img = np.full((H, W, 3), 255, np.uint8)
    shade = np.clip((top - lo) / max(hi - lo, 1e-6), 0, 1)
    img[open_] = np.stack([60 + 180 * shade, 60 + 180 * shade, 140 + 115 * shade], -1)[open_].astype(np.uint8)
    img[u["ground"] & u["walk"]] = (150, 220, 150)
    img[cells == CLOSED] = (70, 70, 70)
    un = u.get("under") or {}
    for gr in un.get("grids", []):  # (floors under others: tinted purple)
        img[gr["cells"] == 3] = (190, 120, 220)
    im = Image.fromarray(img).resize((W * scale, H * scale), Image.NEAREST)
    dr = ImageDraw.Draw(im)

    def px(x, y):
        c, r = u["cellxy"](x, y)
        return c * scale, r * scale

    # every 100 yards
    x_hi, y_hi = u["px_to_world"](0, 0)
    x_lo, y_lo = u["px_to_world"](H - 1, W - 1)
    for gx in range(int(math.ceil(x_lo / 100)) * 100, int(x_hi) + 1, 100):
        a, b = px(gx, y_hi), px(gx, y_lo)
        dr.line([a, b], fill=(200, 200, 200), width=1)
        dr.text((2, a[1] + 1), f"x {gx}", fill=(90, 90, 90))
    for gy in range(int(math.ceil(y_lo / 100)) * 100, int(y_hi) + 1, 100):
        a, b = px(x_hi, gy), px(x_lo, gy)
        dr.line([a, b], fill=(200, 200, 200), width=1)
        dr.text((a[0] + 1, 2), f"y {gy}", fill=(90, 90, 90))
    g = u["graph"]
    for e in g.edges.values():
        col = {"stair": (0, 0, 255), "entrance": (255, 140, 0)}.get(e.source, (220, 0, 0))
        if e.source.startswith("drop:"):
            col = (255, 0, 255)
        dr.line([px(*q) for q in e.pts], fill=col, width=2)
    if un.get("graph") is not None:  # (the roads under: cyan)
        for e in un["graph"].edges.values():
            dr.line([px(*q) for q in e.pts], fill=(0, 190, 210), width=2)
    for nid in u.get("mouths", []):
        x, y = px(*g.nodes[nid])
        dr.ellipse([x - 6, y - 6, x + 6, y + 6], outline=(0, 120, 0), width=2)
    for name, x, y in map_places(u["capital"], u):
        a, b = px(x, y)
        dr.ellipse([a - 4, b - 4, a + 4, b + 4], fill=(255, 220, 0), outline=(0, 0, 0))
        dr.text((a + 5, b - 5), name.split(" ", 1)[-1] if " " in name else name, fill=(0, 0, 0))
    name = u["name"].replace(" ", "_")
    im.save(out_dir / f"{name}.png")
    rows = ["".join(". #"[v] if v < 3 else "?" for v in row) for row in cells]  # (open, the continent's, closed)
    (out_dir / f"{name}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

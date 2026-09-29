"""Floors over floors: a dungeon's walk network in layers (for Data/Instances.lua).

walknet keeps one floor per cell (the top one reached), and joins the grid's pieces by stairs
found in 3D. A keep's rooms over rooms, a spiral stair round itself, a hall under a gallery:
the floors under the top one are lost there, and the routes jumped between floors. Here the
floors walked from the entrance and the bosses (walknet's reached bands, not through walls)
are split into layers, each at most one floor per cell (grown on foot, steps of up to a
ledge; where a layer meets itself over a cell, the rest of that floor is another layer);
each layer gets its own roads (the centerlines of its floor), every node its height; and
where two layers meet on foot, a stair joins their roads.

The result replaces the instance's graph: node heights (`node_z`), each node's layer
(`node_layer`), each road's heights along it (`edge_z`, for the stairs), and per layer the
floor (`layer_mask`, `layer_top`) for simplifying its roads on it.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict

import numpy as np

from . import walknet
from .roads.graph import RoadGraph, skeleton_to_graph

CELL = walknet.CELL
LEDGE = walknet.LEDGE
NEIGH8 = walknet.NEIGH8
MIN_LAYER = 4  # cells: smaller bits of floor are left out (a step's edge, a ledge's corner)
LINK_APART = 16.0  # yards: stairs between the same two layers at least this far apart
LINK_REACH = 40.0  # yards: a stair's ends this near their layers' roads (over their floors)
GAP_MAX = 60.0  # yards: pieces still apart (with the way in or a boss) joined across a gap this wide at most


def floors(u: dict) -> np.ndarray:
    """The floors reached on foot, one voxel per floor per cell (the top of each run of bands
    in a column: a sloping floor fills more than one), not under a wall."""
    f = u["bands"] & ~u["wall3"]
    top = f.copy()
    top[:-1] &= ~f[1:]
    return top


def split(f: np.ndarray, seeds=(), log=print):
    """Layers: {voxel (b, r, c): layer}, and the layers' contacts {(la, lb): [(voxel a, voxel b)]}."""
    NB, H, W = f.shape
    R = int(math.ceil(LEDGE * math.sqrt(2)))
    layer = np.full(f.shape, -1, np.int32)
    col = np.full((H, W), -1, np.int32)  # the growing layer's band in each column
    order = [tuple(int(v) for v in s) for s in seeds] + [tuple(int(v) for v in v_) for v_ in np.argwhere(f)]
    contacts: dict = defaultdict(list)
    sizes = []
    L = 0
    for start in order:
        if not f[start] or layer[start] >= 0:
            continue
        touched = [start[1:]]
        layer[start] = L
        col[start[1], start[2]] = start[0]
        todo = [start]
        n = 1
        while todo:
            b, r, c = todo.pop()
            for dr, dc in NEIGH8:
                r2, c2 = r + dr, c + dc
                if not (0 <= r2 < H and 0 <= c2 < W):
                    continue
                lim = LEDGE * math.hypot(dr, dc)
                for b2 in range(max(0, b - R), min(NB, b + R + 1)):
                    if abs(b2 - b) > lim or not f[b2, r2, c2]:
                        continue
                    other = layer[b2, r2, c2]
                    if other == L:
                        continue
                    if other >= 0:
                        contacts[(other, L)].append(((b2, r2, c2), (b, r, c)))
                        continue
                    if col[r2, c2] >= 0:
                        continue  # (this layer is over this cell already: another layer's floor)
                    layer[b2, r2, c2] = L
                    col[r2, c2] = b2
                    touched.append((r2, c2))
                    todo.append((b2, r2, c2))
                    n += 1
        for r, c in touched:
            col[r, c] = -1
        sizes.append(n)
        L += 1
    log(f"  layers: {L} ({sum(1 for s in sizes if s >= MIN_LAYER)} of {MIN_LAYER}+ cells), "
        f"{sum(len(v) for v in contacts.values())} contacts between them")
    return layer, sizes, contacts


def build(u: dict, seeds_xyz=(), prune: float = 12.0, fill: int = 12, log=print) -> dict:
    """The layered walk network of instance walk data `u` (walknet.build's, seeds reached)."""
    from scipy import ndimage
    from skimage.morphology import remove_small_holes, skeletonize

    f = floors(u)
    NB, H, W = f.shape
    Z0 = u["Z0"]
    cellxy, px_to_world = u["cellxy"], u["px_to_world"]
    seeds = []
    for x, y, z in seeds_xyz:
        cx, cy = cellxy(x, y)
        r0, c0 = int(cy), int(cx)
        best = None
        for r in range(max(r0 - 3, 0), min(r0 + 4, H)):
            for c in range(max(c0 - 3, 0), min(c0 + 4, W)):
                for b in np.nonzero(f[:, r, c])[0]:
                    d = abs(Z0 + b + 0.5 - z) + CELL * math.hypot(r - r0, c - c0)
                    if best is None or d < best[0]:
                        best = (d, (int(b), r, c))
        if best:
            seeds.append(best[1])
    layer, sizes, contacts = split(f, seeds, log)
    nl = len(sizes)
    keep = [s >= MIN_LAYER for s in sizes]

    g = RoadGraph()
    node_z, node_layer, edge_z = {}, {}, {}
    masks, tops = {}, {}
    lb, lr, lc = np.nonzero(layer >= 0)
    lid = layer[lb, lr, lc]
    by_layer = defaultdict(list)
    for i in range(len(lid)):
        by_layer[int(lid[i])].append(i)
    road_px: dict = {}  # layer -> {(r, c): (edge id, point index)}
    for L in range(nl):
        if not keep[L]:
            continue
        idx = by_layer[L]
        rr, cc, bb = lr[idx], lc[idx], lb[idx]
        r0, r1, c0, c1 = rr.min(), rr.max() + 1, cc.min(), cc.max() + 1
        mask = np.zeros((r1 - r0 + 2, c1 - c0 + 2), bool)
        top = np.full(mask.shape, np.nan)
        mask[rr - r0 + 1, cc - c0 + 1] = True
        top[rr - r0 + 1, cc - c0 + 1] = Z0 + bb + 0.5
        # (a ledge's foot within one layer: a neighbor a ledge above; the road keeps off it)
        lip = np.zeros_like(mask)
        for dr, dc in NEIGH8:
            sh = np.roll(np.roll(top, dr, 0), dc, 1)
            with np.errstate(invalid="ignore"):
                lip |= mask & (sh >= top + LEDGE * math.hypot(dr, dc))
        walk = mask & ~lip
        masks[L], tops[L] = (r0 - 1, c0 - 1, walk), top

        def to_world(r, c, r0=r0, c0=c0):
            return px_to_world(r + r0 - 1, c + c0 - 1)

        sub = RoadGraph()
        if walk.sum() >= 2 * MIN_LAYER:
            skel = skeletonize(remove_small_holes(walk, max_size=fill) if fill else walk)
            sub = skeleton_to_graph(skel & walk, to_world, keep_pixels=True)
            sub.prune_spurs(prune)
            sub.contract_degree2()
            sub.drop_isolated_nodes()
        if not sub.nodes:  # (a bit of floor with no centerline: one node, its middlemost cell)
            if not walk.any():
                continue
            dist = ndimage.distance_transform_edt(walk)
            r, c = np.unravel_index(int(np.argmax(dist)), dist.shape)
            sub.add_node(to_world(r, c))
        remap = {}
        for nid, p in sub.nodes.items():
            n2 = g.add_node(p)
            remap[nid] = n2
            node_layer[n2] = L
            node_z[n2] = _z_at(u, tops[L], masks[L], p)
        road_px[L] = {}
        for eid, e in sub.edges.items():
            e2 = g.add_edge(remap[e.a], remap[e.b], e.pts, e.source)
            for i, q in enumerate(e.pts):
                road_px[L].setdefault(_px(u, q), (e2, i))
    log(f"  layers: roads {len(g.nodes)} nodes, {len(g.edges)} edges, {g.total_length():.0f} yd on "
        f"{sum(keep)} layers")

    # a layer's roads in pieces (its floor cut by a ledge's foot, a pillar, a narrow bit the
    # centerline skipped): joined by the shortest ways over the layer's floor (steps of up to a
    # ledge), the nearest pieces first, until they're one
    comp_of = {}
    for ci, edges in enumerate(g.components()):
        for eid in edges:
            comp_of[eid] = ci
    njoin = 0
    for L, at in road_px.items():
        r0, c0, walk = masks[L]
        top = tops[L]
        full = ~np.isnan(top)  # (the whole layer, ledges' feet too: steps are checked)
        src = {}
        for (r, c), (eid, i) in at.items():
            if eid in comp_of:
                src[(r - r0, c - c0)] = comp_of[eid]
        if len(set(src.values())) < 2:
            continue
        dist, owner, prev = {}, {}, {}
        todo = []
        for q, ci in src.items():
            dist[q], owner[q] = 0.0, ci
            todo.append((0.0, q))
        heapq.heapify(todo)
        meets = []
        while todo:
            d, (r, c) = heapq.heappop(todo)
            if d > dist[(r, c)] or d > LINK_REACH:
                continue
            for dr, dc in NEIGH8:
                r2, c2 = r + dr, c + dc
                if not (0 <= r2 < top.shape[0] and 0 <= c2 < top.shape[1]) or not full[r2, c2]:
                    continue
                if abs(top[r2, c2] - top[r, c]) > LEDGE * math.hypot(dr, dc):
                    continue
                nd = d + CELL * math.hypot(dr, dc)
                q2 = (r2, c2)
                if q2 in owner and owner[q2] != owner[(r, c)]:
                    meets.append((d + CELL * math.hypot(dr, dc) + dist[q2], (r, c), q2))
                    continue
                if nd < dist.get(q2, math.inf):
                    dist[q2], owner[q2], prev[q2] = nd, owner[(r, c)], (r, c)
                    heapq.heappush(todo, (nd, q2))
        parent = {}

        def find(a):
            while parent.get(a, a) != a:
                a = parent[a]
            return a
        meets.sort()
        for cost, qa, qb in meets:
            ca, cb = find(owner[qa]), find(owner[qb])
            if ca == cb:
                continue

            def back(q):  # the cells from q back to its road
                path = [q]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                return path
            pa, pb = back(qa), back(qb)
            ea = at.get((pa[-1][0] + r0, pa[-1][1] + c0))
            eb = at.get((pb[-1][0] + r0, pb[-1][1] + c0))
            if not ea or not eb:
                continue
            na = _split(g, ea[0], ea[1], node_layer, node_z, road_px, L, u, tops, masks)
            eb = at.get((pb[-1][0] + r0, pb[-1][1] + c0))  # (the split may have renumbered it)
            nb = _split(g, eb[0], eb[1], node_layer, node_z, road_px, L, u, tops, masks)
            if na == nb:
                continue
            cells = pa[::-1] + pb
            pts = [tuple(g.nodes[na])] + [px_to_world(r + r0, c + c0) for r, c in cells] + [tuple(g.nodes[nb])]
            zs = [node_z[na]] + [float(top[r, c]) for r, c in cells] + [node_z[nb]]
            eid = g.add_edge(na, nb, pts, source="stair")
            edge_z[eid] = zs
            parent[ca] = cb
            njoin += 1
    log(f"  layers: {njoin} ways joining a layer's pieces of road")

    # stairs: where two layers meet on foot, their roads joined through the contact (the way
    # over each layer's floor to its nearest road)
    def on_layer(L, r, c):
        o = masks.get(L)
        if o is None:
            return False
        rr, cc = r - o[0], c - o[1]
        return 0 <= rr < o[2].shape[0] and 0 <= cc < o[2].shape[1] and bool(o[2][rr, cc])

    def to_road(L, r, c):
        """From cell (r, c) of layer L over its floor to its nearest road: (yards, node, cells)."""
        at = road_px.get(L)
        if at is None:
            return math.inf, None, []
        dist, prev, todo = {(r, c): 0.0}, {}, [(0.0, r, c)]
        while todo:
            d, r1, c1 = heapq.heappop(todo)
            if d > dist[(r1, c1)]:
                continue
            if (r1, c1) in at:
                eid, i = at[(r1, c1)]
                path, q = [], (r1, c1)
                while q in prev:
                    path.append(q)
                    q = prev[q]
                path.append(q)
                return d, _split(g, eid, i, node_layer, node_z, road_px, L, u, tops, masks), path
            for dr, dc in NEIGH8:
                r2, c2 = r1 + dr, c1 + dc
                nd = d + CELL * math.hypot(dr, dc)
                if nd <= LINK_REACH and nd < dist.get((r2, c2), math.inf) and (on_layer(L, r2, c2) or (r2, c2) in at):
                    dist[(r2, c2)], prev[(r2, c2)] = nd, (r1, c1)
                    heapq.heappush(todo, (nd, r2, c2))
        # (a layer with a lone node: straight to it)
        lone = [n for n, l_ in node_layer.items() if l_ == L]
        if len(lone) == 1:
            x, y = g.nodes[lone[0]]
            p = px_to_world(r, c)
            dd = math.hypot(x - p[0], y - p[1])
            if dd <= LINK_REACH:
                return dd, lone[0], [(r, c)]
        return math.inf, None, []

    # bits of floor too small for roads of their own (a stair's steps cut into layers by the
    # floors over them) that two layers both touch: those two meet through them
    small_parent = {}

    def sfind(a):
        while small_parent.get(a, a) != a:
            a = small_parent[a]
        return a
    for (la, lb_) in contacts:
        if not keep[la] and not keep[lb_]:
            small_parent[sfind(la)] = sfind(lb_)
    touching = defaultdict(dict)  # small group -> { kept layer: (its voxel, the small one's) }
    for (la, lb_), pairs in contacts.items():
        for k, s_, flip in ((la, lb_, False), (lb_, la, True)):
            if keep[k] and not keep[s_]:
                va, vb = pairs[0]
                touching[sfind(s_)].setdefault(k, (vb, va) if flip else (va, vb))
    for grp, ks in touching.items():
        ls = sorted(ks)
        for i_ in range(len(ls)):
            for j_ in range(i_ + 1, len(ls)):
                (ka, _sa), (kb, _sb) = ks[ls[i_]], ks[ls[j_]]
                if math.hypot(ka[1] - kb[1], ka[2] - kb[2]) * CELL <= LINK_REACH:
                    contacts[(ls[i_], ls[j_])].append((ka, kb))

    nlinks = 0
    why = defaultdict(int)
    for (la, lb_), pairs in sorted(contacts.items()):
        if not (keep[la] and keep[lb_]):
            why["small layer"] += 1
            continue
        taken = []
        for va, vb in pairs:
            xa, ya = px_to_world(va[1], va[2])
            if any(math.hypot(xa - x2, ya - y2) < LINK_APART for x2, y2 in taken):
                continue
            da, na, pa = to_road(la, va[1], va[2])
            db, nb, pb = to_road(lb_, vb[1], vb[2])
            if na is None or nb is None or na == nb:
                why["no road a" if na is None else "no road b" if nb is None else "same node"] += 1
                continue
            taken.append((xa, ya))
            cells = pa[::-1] + pb  # (layer a's road ... the contact ... layer b's road)
            pts = [tuple(g.nodes[na])] + [px_to_world(r, c) for r, c in cells] + [tuple(g.nodes[nb])]
            zs = [node_z[na]] + [_z_cell(u, tops, masks, la if k < len(pa) else lb_, r, c)
                                 for k, (r, c) in enumerate(cells)] + [node_z[nb]]
            eid = g.add_edge(na, nb, pts, source="stair")
            edge_z[eid] = zs
            nlinks += 1
    log(f"  layers: {nlinks} stairs between layers (not joined: {dict(why)})")

    # what's still apart (the models' floors not quite meeting, a tunnel's mouth over a cove):
    # pieces with the way in or a boss on them joined to the rest across the smallest gap
    # (yards across, and up or down counting double), within GAP_MAX
    comps = g.components()
    if len(comps) > 1:
        cnodes = []
        for edges in comps:
            ns_ = set()
            for eid in edges:
                ns_.add(g.edges[eid].a)
                ns_.add(g.edges[eid].b)
            cnodes.append(sorted(ns_))

        def near_seed(ns_):
            for x, y, z in seeds_xyz:
                for n in ns_:
                    nx, ny = g.nodes[n]
                    if math.hypot(nx - x, ny - y) < 30 and abs(node_z.get(n, z) - z) < 10:
                        return True
            return False
        wanted = [near_seed(ns_) for ns_ in cnodes]
        parent = list(range(len(cnodes)))

        def cfind(a):
            while parent[a] != a:
                a = parent[a]
            return a
        pairs_ = []
        for i_ in range(len(cnodes)):
            for j_ in range(i_ + 1, len(cnodes)):
                if not (wanted[i_] and wanted[j_]):
                    continue
                best = None
                for a in cnodes[i_]:
                    ax, ay = g.nodes[a]
                    for b in cnodes[j_]:
                        bx, by = g.nodes[b]
                        d = math.hypot(ax - bx, ay - by)
                        if d > GAP_MAX:
                            continue
                        cost = d + 2 * abs(node_z.get(a, 0) - node_z.get(b, 0))
                        if best is None or cost < best[0]:
                            best = (cost, a, b)
                if best:
                    pairs_.append((best[0], i_, j_, best[1], best[2]))
        pairs_.sort()
        ngap = 0
        for cost, i_, j_, a, b in pairs_:
            if cfind(i_) == cfind(j_):
                continue
            parent[cfind(i_)] = cfind(j_)
            eid = g.add_edge(a, b, [tuple(g.nodes[a]), tuple(g.nodes[b])], source="stair")
            edge_z[eid] = [node_z.get(a, 0), node_z.get(b, 0)]
            ngap += 1
        log(f"  layers: {ngap} gaps crossed between pieces with the way in or a boss")
    return {"graph": g, "node_z": node_z, "node_layer": node_layer, "edge_z": edge_z, "masks": masks, "tops": tops,
            "layer": layer}


def _px(u, q):
    cx, cy = u["cellxy"](q[0], q[1])
    return int(cy), int(cx)


def _z_cell(u, tops, masks, L, r, c) -> float:
    o = masks[L]
    rr, cc = r - o[0], c - o[1]
    t = tops[L]
    if 0 <= rr < t.shape[0] and 0 <= cc < t.shape[1] and not np.isnan(t[rr, cc]):
        return float(t[rr, cc])
    # (next to the layer's floor: its nearest cell's)
    best = None
    for dr in range(-2, 3):
        for dc in range(-2, 3):
            r2, c2 = rr + dr, cc + dc
            if 0 <= r2 < t.shape[0] and 0 <= c2 < t.shape[1] and not np.isnan(t[r2, c2]):
                d = dr * dr + dc * dc
                if best is None or d < best[0]:
                    best = (d, float(t[r2, c2]))
    return best[1] if best else float(np.nanmean(t))


def _z_at(u, top, o, p) -> float:
    r, c = _px(u, p)
    rr, cc = r - o[0], c - o[1]
    if 0 <= rr < top.shape[0] and 0 <= cc < top.shape[1] and not np.isnan(top[rr, cc]):
        return float(top[rr, cc])
    return _z_cell(u, {0: top}, {0: o}, 0, r, c)


def _split(g, eid, i, node_layer, node_z, road_px, L, u, tops, masks) -> int:
    """Road `eid` split at its point i (a node there; the point's index kept up to date)."""
    e = g.edges[eid]
    if i == 0:
        return e.a
    if i == len(e.pts) - 1:
        return e.b
    nid = g.add_node(tuple(e.pts[i]))
    node_layer[nid] = L
    node_z[nid] = _z_at(u, tops[L], masks[L], e.pts[i])
    del g.edges[eid]
    e1 = g.add_edge(e.a, nid, e.pts[: i + 1], e.source)
    e2 = g.add_edge(nid, e.b, e.pts[i:], e.source)
    at = road_px[L]
    for k, q in enumerate(e.pts):
        px = _px(u, q)
        if at.get(px, (None,))[0] == eid:
            at[px] = (e1, k) if k <= i else (e2, k - i)
    return nid


def roads(lay: dict, u: dict, smooth: float = 2.0) -> tuple[list, list, dict, list]:
    """The layered roads as written: nodes [(x, y)], edges [(a, b, points)] (node indices from 0),
    drops {} and the nodes' heights [z]; each road simplified on its own layer's floor."""
    g = lay["graph"]
    order = {nid: i for i, nid in enumerate(sorted(g.nodes))}
    nodes = [tuple(g.nodes[n]) for n in sorted(g.nodes)]
    zs = [float(lay["node_z"].get(n, 0.0)) for n in sorted(g.nodes)]

    def layer_fns(L):
        r0, c0, m = lay["masks"][L]
        top = lay["tops"][L]

        def cell(x, y):
            r, c = _px(u, (x, y))
            return r - r0, c - c0

        def is_open(x, y):
            r, c = cell(x, y)
            return 0 <= r < m.shape[0] and 0 <= c < m.shape[1] and bool(m[r, c])

        def height(x, y):
            r, c = cell(x, y)
            if 0 <= r < top.shape[0] and 0 <= c < top.shape[1] and not np.isnan(top[r, c]):
                return float(top[r, c])
            return None
        return is_open, height

    fns = {}
    edges = []
    for eid, e in g.edges.items():
        ends = [tuple(g.nodes[e.a])] + [tuple(q) for q in e.pts[1:-1]] + [tuple(g.nodes[e.b])]
        if e.source == "stair" and eid in lay["edge_z"]:
            pts = walknet.simplify_3d(ends, lay["edge_z"][eid], smooth, u["floor_at"])
        else:
            L = lay["node_layer"].get(e.a)
            if L not in fns:
                fns[L] = layer_fns(L) if L in lay["masks"] else None
            f = fns[L]
            pts = walknet.unzig(walknet.simplify(ends, smooth, f[0], f[1]), f[0], f[1]) if f else ends
        edges.append((order[e.a], order[e.b], pts))
    return nodes, edges, {}, zs

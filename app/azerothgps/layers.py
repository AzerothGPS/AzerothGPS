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


def wall_voxels(u: dict, walls) -> np.ndarray:
    """Every wall face as voxels (band, row, col) it passes through, standing on a floor or not
    (a railing over a drop): walls as given to walknet.build, ((zlo, zhi), world triangle)."""
    from PIL import Image, ImageDraw
    NB, H, W, Z0 = u["NB"], u["H"], u["W"], u["Z0"]
    out = np.zeros((NB, H, W), bool)
    for w in walls:
        (zlo, zhi), tri = w[0], w[1]
        pts = [u["cellxy"](*q) for q in tri]
        c0, r0 = max(int(min(p[0] for p in pts)) - 1, 0), max(int(min(p[1] for p in pts)) - 1, 0)
        c1, r1 = min(int(max(p[0] for p in pts)) + 2, W), min(int(max(p[1] for p in pts)) + 2, H)
        b0, b1 = max(0, int(zlo - Z0)), min(NB - 1, int(zhi - Z0))
        if c1 <= c0 or r1 <= r0 or b1 < b0:
            continue
        m = Image.new("L", (c1 - c0, r1 - r0), 0)
        d = ImageDraw.Draw(m)
        loc = [(p[0] - c0, p[1] - r0) for p in pts]
        d.polygon(loc, fill=255)
        d.line(loc + [loc[0]], fill=255)
        out[b0:b1 + 1, r0:r1, c0:c1] |= (np.array(m) > 0)[None]
    return out


SEAM_SPAN = 2  # cells: a gap in the floor this wide at most is a doorway's threshold


def fill_seams(f: np.ndarray, u: dict, wallvox: np.ndarray, span: int = SEAM_SPAN) -> tuple[np.ndarray, int]:
    """Floors across gaps of up to `span` cells between floors at about the same height on either
    side, with nothing there near that height (no floor, no wall): a doorway's threshold, a
    seam between two models' floors. (A model's floors often stop short of each other there.)"""
    g = f.copy()
    NB, H, W = f.shape
    bands = u["bands"]
    added = 0
    for b, r, c in np.argwhere(f):
        for dr, dc in ((1, 0), (0, 1), (1, 1), (1, -1)):
            for s_ in range(2, span + 2):  # (the far side s_ cells on; the ones between empty)
                r2, c2 = r + dr * s_, c + dc * s_
                if not (0 <= r2 < H and 0 <= c2 < W):
                    break
                mids = [(r + dr * t, c + dc * t) for t in range(1, s_)]
                clear = all(not bands[max(0, b - 3):b + 4, rr, cc].any() and not wallvox[max(0, b - 1):b + 3, rr, cc].any()
                            for rr, cc in mids)
                if not clear:
                    break
                if f[max(0, b - 2):b + 3, r2, c2].any():
                    for rr, cc in mids:
                        if not g[b, rr, cc]:
                            g[b, rr, cc] = True
                            added += 1
                    break
    return g, added


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
                lim = walknet.step_lim(dr, dc)
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


def build(u: dict, seeds_xyz=(), prune: float = 12.0, fill: int = 12, log=print, walls=None,
          gap_max: float = GAP_MAX, spurs=(), completing: bool = False) -> dict:
    """The layered walk network of instance walk data `u` (walknet.build's, seeds reached).
    `walls` (as given to walknet.build): the floor's gaps at doorways filled (fill_seams).
    `gap_max`: pieces with the way in joined across a gap this wide at most (straight).
    `spurs`: places (x, y, z) each joined by a road over its floor to the nearest road on it."""
    from scipy import ndimage
    from skimage.morphology import remove_small_holes, skeletonize

    f = floors(u)
    if walls is not None:
        f, nseam = fill_seams(f, u, wall_voxels(u, walls))
        log(f"  layers: {nseam} floor cells filled at doorways")
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
            # (to_road's cells run from the road to the contact: layer a's road ... the contact,
            # then the contact ... layer b's road)
            cells = pa + pb[::-1]
            zs_ = [_z_cell(u, tops, masks, la if k < len(pa) else lb_, r, c) for k, (r, c) in enumerate(cells)]
            # (the way itself, in 3D: from road a's floor to road b's over the floor, step by step:
            # a stair's steps between floors, its heights where they are)
            sa, sb = _voxel_at(f, u, g.nodes[na], node_z[na]), _voxel_at(f, u, g.nodes[nb], node_z[nb])
            way = _voxel_path(f, sa, sb) if sa and sb and sa != sb else []
            if way is None:  # (no way on foot between them, over the floors: not a stair, a floor over another)
                why["no way on foot"] += 1
                taken.pop()
                continue
            if way:
                cells = [(r, c) for _b, r, c in [sa] + way + [sb]]
                zs_ = [Z0 + b_ + 0.5 for b_, _r, _c in [sa] + way + [sb]]
            pts = [tuple(g.nodes[na])] + [px_to_world(r, c) for r, c in cells] + [tuple(g.nodes[nb])]
            zs = [node_z[na]] + zs_ + [node_z[nb]]
            eid = g.add_edge(na, nb, pts, source="stair")
            edge_z[eid] = zs
            nlinks += 1
    log(f"  layers: {nlinks} stairs between layers (not joined: {dict(why)})")

    # places to reach (a trainer, a banker: `spurs`, (x, y, z)): a road from each over its floor
    # to the nearest road on it, so the way to one follows the floor to the door, not straight
    # from the nearest road across whatever is between
    nspur, unjoined = 0, []
    for x, y, z in spurs:
        cx, cy = cellxy(x, y)
        r0_, c0_ = int(cy), int(cx)
        best = None
        for r in range(max(r0_ - 2, 0), min(r0_ + 3, H)):
            for c in range(max(c0_ - 2, 0), min(c0_ + 3, W)):
                for b in np.nonzero(layer[:, r, c] >= 0)[0]:
                    L = int(layer[b, r, c])
                    d = abs(Z0 + b + 0.5 - z) + CELL * math.hypot(r - r0_, c - c0_)
                    if keep[L] and L in masks and abs(Z0 + b + 0.5 - z) <= LEDGE and (best is None or d < best[0]):
                        best = (d, L, r, c, b)
        if not best:
            unjoined.append((x, y, z, "no floor there"))
            continue
        _d, L, r, c, b = best
        # (the nearest road node reached from it on foot over the floors, step by step: a layer's
        # heights can be off at its edge, and its nearest road be on a walkway over the place)
        sv = (int(b), r, c)
        n, way = None, None
        near = sorted((math.hypot(g.nodes[m][0] - x, g.nodes[m][1] - y), m) for m in g.nodes if m in node_z)
        for dn, m in near[:SPUR_TRIES]:
            if dn > LINK_REACH:
                break
            mv = _voxel_at(f, u, g.nodes[m], node_z[m])
            w = _voxel_path(f, mv, sv, int(LINK_REACH / CELL) + 2) if mv else None
            if w is not None and (len(w) + 1) * CELL <= SPUR_DETOUR * dn + 2 * LINK_REACH / 4:
                n, way = m, [mv] + w + [sv]
                break
        if n is None:
            unjoined.append((x, y, z, "no road reached on foot within reach"))
            continue
        spot = g.add_node((x, y))
        node_layer[spot], node_z[spot] = L, Z0 + b + 0.5
        pts = [tuple(g.nodes[n])] + [px_to_world(rr, cc) for _b, rr, cc in way] + [(x, y)]
        zs = [node_z[n]] + [Z0 + b_ + 0.5 for b_, _r, _c in way] + [node_z[spot]]
        eid = g.add_edge(n, spot, pts, source="stair")
        edge_z[eid] = zs
        nspur += 1
    if spurs:
        log(f"  layers: {nspur} of {len(spurs)} places joined to their floor's roads")

    if completing:  # (roads where the floors go and the roads went the long way round)
        complete(g, node_z, node_layer, edge_z, f, u, log)

    # what's still apart (the models' floors not quite meeting, a tunnel's mouth over a cove):
    # pieces with the way in or a boss on them joined to the rest across the smallest gap
    # (yards across, and up or down counting double), within GAP_MAX
    comps = g.components()
    cnodes = []
    for edges in comps:
        ns_ = set()
        for eid in edges:
            ns_.add(g.edges[eid].a)
            ns_.add(g.edges[eid].b)
        cnodes.append(sorted(ns_))
    # (and lone nodes, a bit of floor with no road of its own: a lift's platform boxed in by its
    # shaft, joined when it has the way in)
    on_road = {n for ns_ in cnodes for n in ns_}
    cnodes += [[n] for n in sorted(g.nodes) if n not in on_road]
    if len(cnodes) > 1:

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
                        if d > gap_max:
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
            "layer": layer, "floors": f, "unjoined": unjoined if spurs else []}


def point_heights(lay: dict, u: dict, eid, pts) -> list:
    """The floor's height at each of road `eid`'s points `pts` (its layer's; a stair's own), or None."""
    g = lay["graph"]
    e = g.edges[eid]
    ez = lay["edge_z"].get(eid)
    if ez:
        full = [tuple(g.nodes[e.a])] + [tuple(q) for q in e.pts[1:-1]] + [tuple(g.nodes[e.b])]
        out = []
        for q in pts:
            j = min(range(len(full)), key=lambda i: math.hypot(full[i][0] - q[0], full[i][1] - q[1]))
            out.append(ez[min(j, len(ez) - 1)])
        return out
    L = lay["node_layer"].get(e.a)
    if L not in lay["masks"]:
        return [None] * len(pts)
    r0, c0, _m = lay["masks"][L]
    top = lay["tops"][L]
    out = []
    for q in pts:
        r, c = _px(u, q)
        r, c = r - r0, c - c0
        h = top[r, c] if 0 <= r < top.shape[0] and 0 <= c < top.shape[1] else np.nan
        out.append(None if np.isnan(h) else float(h))
    return out


SPUR_TRIES = 12  # the nearest road nodes tried for a place's road (spurs)
SPUR_DETOUR = 2.0  # ...: on foot at most this many times as far as straight (and 20 yd)
SHORT_REACH = 45.0  # yards: complete(): road nodes this near each other on foot are checked
SHORT_RATIO, SHORT_SLACK = 1.5, 10.0  # ...: a road between them when the roads take longer than this


def complete(g, node_z: dict, node_layer: dict, edge_z: dict, f: np.ndarray, u: dict, log=print) -> int:
    """Roads where the floors go: road nodes near each other on foot (SHORT_REACH over the floors,
    steps of up to a ledge) that the roads join only the long way round (more than SHORT_RATIO
    times, plus SHORT_SLACK) get a road along the way on foot, with its heights (a stair between
    floors, a passage the roads missed). How many added."""
    NB, H, W = f.shape
    Z0, px_to_world = u["Z0"], u["px_to_world"]
    R_ = int(math.ceil(LEDGE * math.sqrt(2)))
    at = {}  # node -> its floor voxel
    by_vox = {}
    for n, xy in g.nodes.items():
        v = _voxel_at(f, u, xy, node_z.get(n, Z0))
        if v:
            at[n] = v
            by_vox.setdefault(v, []).append(n)
    adj = defaultdict(list)
    for eid, e in g.edges.items():
        adj[e.a].append((e.b, e.length))
        adj[e.b].append((e.a, e.length))

    def road_within(a, b, limit):
        dist, todo = {a: 0.0}, [(0.0, a)]
        while todo:
            d, n = heapq.heappop(todo)
            if n == b:
                return True
            if d > dist[n] or d > limit:
                continue
            for m, w in adj[n]:
                nd = d + w
                if nd <= limit and nd < dist.get(m, math.inf):
                    dist[m] = nd
                    heapq.heappush(todo, (nd, m))
        return False
    added = 0
    for a in sorted(at):
        s0 = at[a]
        dist, prev, todo = {s0: 0.0}, {}, [(0.0, s0)]
        found = []
        while todo:
            d, v = heapq.heappop(todo)
            if d > dist[v]:
                continue
            for b in by_vox.get(v, ()):
                if b != a and b > a:
                    found.append((d, b, v))
            b_, r, c = v
            for dr, dc in NEIGH8:
                r2, c2 = r + dr, c + dc
                if not (0 <= r2 < H and 0 <= c2 < W):
                    continue
                lim = walknet.step_lim(dr, dc)
                for b2 in range(max(0, b_ - R_), min(NB, b_ + R_ + 1)):
                    if abs(b2 - b_) <= lim and f[b2, r2, c2] and clear_step(f, b_, r, c, b2, r2, c2):
                        w = (b2, r2, c2)
                        nd = d + CELL * math.hypot(dr, dc)
                        if nd <= SHORT_REACH and nd < dist.get(w, math.inf):
                            dist[w], prev[w] = nd, v
                            heapq.heappush(todo, (nd, w))
        for d, b, v in sorted(found):
            if road_within(a, b, SHORT_RATIO * d + SHORT_SLACK):
                continue
            way = [v]
            while way[-1] in prev:
                way.append(prev[way[-1]])
            way = way[::-1]  # (a's voxel ... b's)
            pts = [tuple(g.nodes[a])] + [px_to_world(r, c) for _b, r, c in way[1:-1]] + [tuple(g.nodes[b])]
            zs = [node_z.get(a, Z0)] + [Z0 + b2 + 0.5 for b2, _r, _c in way[1:-1]] + [node_z.get(b, Z0)]
            eid = g.add_edge(a, b, pts, source="stair")
            edge_z[eid] = zs
            length = g.edges[eid].length
            adj[a].append((b, length))
            adj[b].append((a, length))
            added += 1
    log(f"  layers: {added} roads where the floors go and the roads went round")
    return added


BODY_BANDS = 2  # yards of headroom a step up or down needs: no floor in between (a ceiling)


def clear_step(f: np.ndarray, b: int, r: int, c: int, b2: int, r2: int, c2: int) -> bool:
    """Whether a step from floor voxel (b, r, c) to (b2, r2, c2) passes no other floor: none in
    either column between the two heights, nor a body's height over the higher (a walk can't
    go through a floor: between floors stacked a few yards apart, zig-zagging down two columns)."""
    lo, hi = min(b, b2), max(b, b2) + BODY_BANDS
    for bb, rr, cc in ((b, r, c), (b2, r2, c2)):
        col = f[lo:hi + 1, rr, cc]
        if col.sum() > (1 if lo <= bb <= hi else 0):
            return False
    return True


def _voxel_at(f: np.ndarray, u: dict, xy, z) -> tuple | None:
    """The floor voxel (band, row, col) at world (x, y) nearest height z (within a ledge), or None."""
    NB, H, W = f.shape
    cx, cy = u["cellxy"](xy[0], xy[1])
    r, c = int(cy), int(cx)
    if not (0 <= r < H and 0 <= c < W):
        return None
    bands = np.nonzero(f[:, r, c])[0]
    if not len(bands):
        return None
    b = min(bands, key=lambda b_: abs(u["Z0"] + b_ + 0.5 - z))
    return (int(b), r, c) if abs(u["Z0"] + b + 0.5 - z) <= LEDGE else None


def _voxel_path(f: np.ndarray, va, vb, reach: int = 30) -> list | None:
    """The floor voxels (band, row, col) walked from va to vb (steps up to a ledge; within
    `reach` cells of them), both ends left out ([] side by side); None when there's no way."""
    NB, H, W = f.shape
    R = int(math.ceil(LEDGE * math.sqrt(2)))
    r0, r1 = max(0, min(va[1], vb[1]) - reach), min(H, max(va[1], vb[1]) + reach + 1)
    c0, c1 = max(0, min(va[2], vb[2]) - reach), min(W, max(va[2], vb[2]) + reach + 1)
    start, goal = tuple(int(v) for v in va), tuple(int(v) for v in vb)
    dist, prev, todo = {start: 0.0}, {}, [(0.0, start)]
    while todo:
        d, v = heapq.heappop(todo)
        if v == goal:
            path = []
            while v in prev:
                v = prev[v]
                if v != start:
                    path.append(v)
            return path[::-1]
        if d > dist[v]:
            continue
        b, r, c = v
        for dr, dc in NEIGH8:
            r2, c2 = r + dr, c + dc
            if not (r0 <= r2 < r1 and c0 <= c2 < c1):
                continue
            lim = walknet.step_lim(dr, dc)
            for b2 in range(max(0, b - R), min(NB, b + R + 1)):
                if abs(b2 - b) <= lim and f[b2, r2, c2] and clear_step(f, b, r, c, b2, r2, c2):
                    w = (b2, r2, c2)
                    nd = d + CELL * math.hypot(dr, dc) + abs(b2 - b) * 0.5
                    if nd < dist.get(w, math.inf):
                        dist[w], prev[w] = nd, v
                        heapq.heappush(todo, (nd, w))
    return None


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

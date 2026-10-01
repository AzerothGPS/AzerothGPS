"""Road graph: skeleton -> nodes/edges, cleanup, gap bridging, overrides.

All geometry here is in world yards: points are (X north, Y west). Edges carry
their polyline including both end nodes' positions.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage


@dataclass
class Edge:
    a: int
    b: int
    pts: np.ndarray  # (M, 2) world yards, pts[0] at node a, pts[-1] at node b
    source: str = "terrain"  # "terrain" | "bridge" | "override"

    @property
    def length(self) -> float:
        d = np.diff(self.pts, axis=0)
        return float(np.hypot(d[:, 0], d[:, 1]).sum())


@dataclass
class RoadGraph:
    nodes: dict[int, np.ndarray] = field(default_factory=dict)  # id -> (2,) world
    edges: dict[int, Edge] = field(default_factory=dict)
    _next_node: int = 0
    _next_edge: int = 0

    # ---- construction -------------------------------------------------------
    def add_node(self, p) -> int:
        nid = self._next_node
        self._next_node += 1
        self.nodes[nid] = np.asarray(p, np.float64)
        return nid

    def add_edge(self, a: int, b: int, pts, source: str = "terrain") -> int:
        pts = np.asarray(pts, np.float64)
        pts[0], pts[-1] = self.nodes[a], self.nodes[b]
        eid = self._next_edge
        self._next_edge += 1
        self.edges[eid] = Edge(a, b, pts, source)
        return eid

    def incident(self) -> dict[int, list[int]]:
        inc: dict[int, list[int]] = {n: [] for n in self.nodes}
        for eid, e in self.edges.items():
            inc[e.a].append(eid)
            if e.b != e.a:
                inc[e.b].append(eid)
        return inc

    def degree(self) -> dict[int, int]:
        deg = {n: 0 for n in self.nodes}
        for e in self.edges.values():
            deg[e.a] += 1
            deg[e.b] += 1
        return deg

    def remove_edge(self, eid: int) -> None:
        self.edges.pop(eid, None)

    def drop_isolated_nodes(self) -> None:
        used = {e.a for e in self.edges.values()} | {e.b for e in self.edges.values()}
        for n in list(self.nodes):
            if n not in used:
                del self.nodes[n]

    def total_length(self) -> float:
        return sum(e.length for e in self.edges.values())

    # ---- cleanup ------------------------------------------------------------
    def contract_degree2(self) -> None:
        """Join the two edges at every degree-2 node into one."""
        changed = True
        while changed:
            changed = False
            inc = self.incident()
            for n, eids in inc.items():
                if len(eids) != 2 or n not in self.nodes:
                    continue
                e1, e2 = self.edges.get(eids[0]), self.edges.get(eids[1])
                if e1 is None or e2 is None or e1 is e2:
                    continue
                p1 = e1.pts if e1.b == n else e1.pts[::-1]  # ... -> n
                o1 = e1.a if e1.b == n else e1.b
                p2 = e2.pts if e2.a == n else e2.pts[::-1]  # n -> ...
                o2 = e2.b if e2.a == n else e2.a
                if o1 == n or o2 == n:
                    continue  # self-loop; leave it
                src = e1.source if e1.source == e2.source else "terrain"
                self.remove_edge(eids[0])
                self.remove_edge(eids[1])
                del self.nodes[n]
                self.add_edge(o1, o2, np.vstack([p1, p2[1:]]), src)
                changed = True
                break  # incidence changed; recompute

    def prune_spurs(self, max_len: float, rounds: int = 3) -> None:
        """Remove dead-end edges shorter than max_len (skeleton whiskers)."""
        for _ in range(rounds):
            deg = self.degree()
            removed = False
            for eid, e in list(self.edges.items()):
                dead_a, dead_b = deg[e.a] == 1, deg[e.b] == 1
                if (dead_a or dead_b) and not (dead_a and dead_b) and e.length < max_len:
                    self.remove_edge(eid)
                    removed = True
            self.remove_short_loops(max_len)
            self.drop_isolated_nodes()
            self.contract_degree2()
            if not removed:
                break

    def remove_short_loops(self, max_len: float) -> None:
        for eid, e in list(self.edges.items()):
            if e.a == e.b and e.length < max_len:
                self.remove_edge(eid)

    def merge_close_nodes(self, dist: float) -> None:
        """Collapse edges shorter than dist between two junctions into one node."""
        changed = True
        while changed:
            changed = False
            for eid, e in list(self.edges.items()):
                if e.a != e.b and e.length < dist:
                    keep, gone = e.a, e.b
                    self.nodes[keep] = (self.nodes[keep] + self.nodes[gone]) / 2
                    self.remove_edge(eid)
                    for other in self.edges.values():
                        if other.a == gone:
                            other.a = keep
                        if other.b == gone:
                            other.b = keep
                    del self.nodes[gone]
                    for other in self.edges.values():  # keep polylines anchored to nodes
                        other.pts[0], other.pts[-1] = self.nodes[other.a], self.nodes[other.b]
                    changed = True
                    break
        self.remove_short_loops(dist * 2)

    def components(self) -> list[set[int]]:
        """Connected components as sets of edge IDs."""
        parent: dict[int, int] = {n: n for n in self.nodes}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for e in self.edges.values():
            ra, rb = find(e.a), find(e.b)
            if ra != rb:
                parent[ra] = rb
        comps: dict[int, set[int]] = {}
        for eid, e in self.edges.items():
            comps.setdefault(find(e.a), set()).add(eid)
        return list(comps.values())

    def remove_small_components(self, min_len: float) -> None:
        for comp in self.components():
            if sum(self.edges[eid].length for eid in comp) < min_len:
                for eid in comp:
                    self.remove_edge(eid)
        self.drop_isolated_nodes()

    def simplify(self, tol: float) -> None:
        from skimage.measure import approximate_polygon

        for e in self.edges.values():
            if len(e.pts) > 2:
                e.pts = approximate_polygon(e.pts, tol)

    # ---- geometry helpers ----------------------------------------------------
    def end_direction(self, node: int, eid: int, span: float = 20.0) -> np.ndarray:
        """Unit vector pointing out of `node` along the road's end (away from the edge)."""
        e = self.edges[eid]
        pts = e.pts if e.a == node else e.pts[::-1]
        acc, i = 0.0, 1
        while i < len(pts) - 1 and acc < span:
            acc += float(np.hypot(*(pts[i] - pts[i - 1])))
            i += 1
        v = pts[0] - pts[min(i, len(pts) - 1)]
        n = np.hypot(*v)
        return v / n if n > 0 else np.zeros(2)

    def nearest_on_edges(self, p: np.ndarray, exclude: set[int] = frozenset()):
        """(distance, edge id, segment index, projected point) of the closest edge point."""
        best = (math.inf, -1, -1, None)
        for eid, e in self.edges.items():
            if eid in exclude:
                continue
            a, b = e.pts[:-1], e.pts[1:]
            ab = b - a
            L2 = (ab ** 2).sum(axis=1)
            t = np.clip(((p - a) * ab).sum(axis=1) / np.where(L2 > 0, L2, 1), 0, 1)
            proj = a + ab * t[:, None]
            d = np.hypot(*(proj - p).T)
            i = int(np.argmin(d))
            if d[i] < best[0]:
                best = (float(d[i]), eid, i, proj[i])
        return best

    def split_edge(self, eid: int, seg: int, point: np.ndarray) -> int:
        """Insert a node on edge `eid` at `point` (on segment `seg`). Returns the node."""
        e = self.edges.pop(eid)
        n = self.add_node(point)
        first = np.vstack([e.pts[: seg + 1], point])
        second = np.vstack([point, e.pts[seg + 1 :]])
        self.add_edge(e.a, n, first, e.source)
        self.add_edge(n, e.b, second, e.source)
        return n

    # ---- serialization ------------------------------------------------------
    def to_json(self, extra: dict | None = None) -> dict:
        ids = {n: i for i, n in enumerate(sorted(self.nodes))}
        return {
            **(extra or {}),
            "nodes": [[round(float(p[0]), 1), round(float(p[1]), 1)] for _, p in sorted(self.nodes.items())],
            "edges": [
                {"a": ids[e.a], "b": ids[e.b], "len": round(e.length, 1), "src": e.source,
                 "pts": [[round(float(x), 1), round(float(y), 1)] for x, y in e.pts]}
                for e in self.edges.values()
            ],
        }

    @classmethod
    def from_json(cls, doc: dict) -> "RoadGraph":
        g = cls()
        for p in doc["nodes"]:
            g.add_node(p)
        for e in doc["edges"]:
            g.add_edge(e["a"], e["b"], e["pts"], e.get("src", "terrain"))
        return g


# ---- skeleton -> graph -----------------------------------------------------------

_NEIGH = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def skeleton_to_graph(skel: np.ndarray, px_to_world, keep_pixels: bool = False) -> RoadGraph:
    """Convert a 1-px skeleton to a RoadGraph. px_to_world(row, col) -> (X, Y).
    `keep_pixels`: a node sits on its pixel cluster's pixel nearest the cluster's middle (not
    the middle, which can be off the skeleton), and its edges run through the cluster's
    pixels to it (not straight across)."""
    skel = skel.astype(bool)
    kernel = np.ones((3, 3), np.uint8)
    kernel[1, 1] = 0
    deg = ndimage.convolve(skel.astype(np.uint8), kernel, mode="constant") * skel
    node_mask = skel & (deg != 2)
    labels, n_clusters = ndimage.label(node_mask, structure=np.ones((3, 3)))
    g = RoadGraph()
    cluster_node: dict[int, int] = {}
    rep: dict[int, tuple[int, int]] = {}
    if n_clusters:
        centers = ndimage.center_of_mass(node_mask, labels, range(1, n_clusters + 1))
        if keep_pixels:
            members: dict[int, list] = {}
            for r, c in np.argwhere(node_mask):
                members.setdefault(int(labels[r, c]), []).append((int(r), int(c)))
        for k, (r, c) in enumerate(centers, start=1):
            if keep_pixels:
                rep[k] = min(members[k], key=lambda q: (q[0] - r) ** 2 + (q[1] - c) ** 2)
                r, c = rep[k]
            cluster_node[k] = g.add_node(px_to_world(r, c))

    H, W = skel.shape
    tree: dict[int, dict] = {}

    def to_rep(px: tuple[int, int]) -> list:
        """The cluster's pixels from its node's pixel to `px` (inside the cluster)."""
        k = int(labels[px])
        if k not in rep:
            return [px]
        par = tree.get(k)
        if par is None:  # breadth-first from the node's pixel, once per cluster
            par = {rep[k]: None}
            todo = [rep[k]]
            for q in todo:
                for dr, dc in _NEIGH:
                    nq = (q[0] + dr, q[1] + dc)
                    if 0 <= nq[0] < H and 0 <= nq[1] < W and labels[nq] == k and nq not in par:
                        par[nq] = q
                        todo.append(nq)
            tree[k] = par
        out, q = [], (int(px[0]), int(px[1]))
        while q is not None:
            out.append(q)
            q = par.get(q)
        return out[::-1]

    def neighbours(r: int, c: int):
        for dr, dc in _NEIGH:
            rr, cc = r + dr, c + dc
            if 0 <= rr < H and 0 <= cc < W and skel[rr, cc]:
                yield rr, cc

    visited = np.zeros_like(skel)
    seen_pairs: set[tuple] = set()

    def trace(start: tuple[int, int], first: tuple[int, int]) -> None:
        a = cluster_node[labels[start]]
        path = [start]
        prev, cur = start, first
        while True:
            if labels[cur]:  # reached a node cluster
                b = cluster_node[labels[cur]]
                path.append(cur)
                if len(path) == 2:  # two node pixels touching: record once
                    key = (min(start, cur), max(start, cur))
                    if key in seen_pairs or a == b:
                        return
                    seen_pairs.add(key)
                if keep_pixels:
                    path = to_rep(path[0])[:-1] + path + to_rep(path[-1])[::-1][1:]
                pts = [px_to_world(r, c) for r, c in path]
                g.add_edge(a, b, pts)
                return
            visited[cur] = True
            path.append(cur)
            nxt = None
            for q in neighbours(*cur):
                if q != prev and not visited[q] and (labels[q] == 0 or len(path) > 2 or labels[q] != labels[start]):
                    # prefer orthogonal steps; they keep staircase corners on the line
                    if nxt is None or (q[0] == cur[0] or q[1] == cur[1]):
                        nxt = q
                        if labels[q]:
                            break
            if nxt is None:  # ran into our own traced pixels (small loop); close it
                return
            prev, cur = cur, nxt

    node_pixels = np.argwhere(node_mask)
    for r, c in node_pixels:
        for q in neighbours(r, c):
            if labels[q] == labels[r, c]:
                continue
            if not labels[q] and visited[q]:
                continue
            trace((r, c), q)

    # Closed loops with no junctions: seed a node on each.
    remaining = skel & ~visited & ~node_mask
    while remaining.any():
        r, c = map(int, np.argwhere(remaining)[0])
        n = g.add_node(px_to_world(r, c))
        labels_val = labels.max() + 1
        labels[r, c] = labels_val
        cluster_node[labels_val] = n
        nbrs = list(neighbours(r, c))
        if nbrs:
            trace((r, c), nbrs[0])
        remaining[r, c] = False
        remaining &= ~visited
    return g


# ---- gap bridging -----------------------------------------------------------------

def _angle(u: np.ndarray, v: np.ndarray) -> float:
    nu, nv = np.hypot(*u), np.hypot(*v)
    if nu == 0 or nv == 0:
        return 180.0
    return math.degrees(math.acos(max(-1.0, min(1.0, float(u @ v) / (nu * nv)))))


class _EdgeSamples:
    """Points every few yards along the roads, to find the road a dead end heads for."""

    STEP = 3.0

    def __init__(self, g: RoadGraph) -> None:
        from scipy.spatial import cKDTree

        pts = []
        for e in g.edges.values():
            d = np.diff(e.pts, axis=0)
            for p, v in zip(e.pts[:-1], d):
                n = max(1, int(np.hypot(*v) // self.STEP))
                pts.append(p + v * (np.arange(n)[:, None] / n))
            pts.append(e.pts[-1:])
        self.pts = np.vstack(pts) if pts else np.zeros((0, 2))
        self.tree = cKDTree(self.pts) if len(self.pts) else None

    def ahead(self, g: RoadGraph, p: np.ndarray, direction: np.ndarray, reach: float, own: set[int],
              max_angle: float):
        """(distance, edge, segment, point) of the nearest road point within reach that lies
        within max_angle of direction from p (not on the edges in own), or None."""
        if self.tree is None or not np.any(direction):
            return None
        idx = self.tree.query_ball_point(p, reach)
        if not idx:
            return None
        q = self.pts[idx] - p
        dist = np.hypot(q[:, 0], q[:, 1])
        cos = (q @ direction) / np.where(dist > 0, dist, 1)
        ok = (dist > 0.5) & (cos >= math.cos(math.radians(max_angle)))
        for i in np.argsort(np.where(ok, dist, np.inf)):
            if not ok[i]:
                return None
            # The samples predate this pass's edge splits: find the edge there now.
            d, eid, seg, point = g.nearest_on_edges(self.pts[idx[i]])
            if eid < 0 or eid in own or d > 1.0:
                continue
            return float(np.hypot(*(point - p))), eid, seg, point
        return None


def bridge_gaps(g: RoadGraph, end_end_max: float = 120.0, end_edge_max: float = 20.0,
                max_angle: float = 30.0, crosses_water=None, far_end_max: float = 0.0,
                far_edge_max: float = 0.0, clear=None, far_min_leg: float = 60.0) -> int:
    """Connect dead ends that point at each other (bridges, fords, texture gaps)
    and dead ends that stop just short of another road (T junctions).

    crosses_water(p, q) -> bool vetoes short end-to-edge links over water; end-to-end
    links may cross water (that is what bridges look like in terrain textures).

    Longer links join roads whose texture fades out for a while (a road painted with the
    zone's plain dirt between stretches of road texture): ends facing each other up to
    far_end_max apart, and ends heading straight at another road up to far_edge_max
    from it. Those need clear(p, q) -> bool (walkable ground all the way, no water), and
    each end's own road at least far_min_leg long before its first junction: a proper road
    heading somewhere, not a whisker of a town square or of cracked ground.
    """
    added = 0
    inc = g.incident()
    ends = [n for n, eids in inc.items() if len(eids) == 1]
    dirs = {n: g.end_direction(n, inc[n][0]) for n in ends}
    used: set[int] = set()
    reach = max(end_end_max, far_end_max if clear is not None else 0.0)
    leg = {n: g.edges[inc[n][0]].length for n in ends}

    # 1) end <-> end, mutually aligned, closest pairs first
    pairs = []
    for i, a in enumerate(ends):
        for b in ends[i + 1 :]:
            d = float(np.hypot(*(g.nodes[b] - g.nodes[a])))
            if d <= reach and inc[a][0] != inc[b][0]:
                gap = g.nodes[b] - g.nodes[a]
                if _angle(dirs[a], gap) <= max_angle and _angle(dirs[b], -gap) <= max_angle:
                    if d > end_end_max and (min(leg[a], leg[b]) < far_min_leg
                                            or not clear(g.nodes[a], g.nodes[b])):
                        continue
                    pairs.append((d, a, b))
    for d, a, b in sorted(pairs):
        if a in used or b in used:
            continue
        g.add_edge(a, b, [g.nodes[a], g.nodes[b]], "bridge")
        used |= {a, b}
        added += 1

    # 2) end -> nearest point on another road (T junction)
    samples = None
    for a in ends:
        if a in used or a not in g.nodes:
            continue
        own = set(g.incident().get(a, []))
        dist, eid, seg, point = g.nearest_on_edges(g.nodes[a], exclude=own)
        if eid < 0 or dist < 0.5:
            continue
        if dist > end_edge_max:
            if clear is None or far_edge_max <= 0 or leg[a] < far_min_leg:
                continue
            if samples is None:
                samples = _EdgeSamples(g)
            hit = samples.ahead(g, g.nodes[a], dirs[a], far_edge_max, own, max_angle)
            if hit is None:
                continue
            dist, eid, seg, point = hit
            if not clear(g.nodes[a], point):
                continue
        elif _angle(dirs[a], point - g.nodes[a]) > 60:
            continue
        if crosses_water is not None and crosses_water(g.nodes[a], point):
            continue
        n = g.split_edge(eid, seg, point)
        g.add_edge(a, n, [g.nodes[a], point], "bridge")
        used.add(a)
        added += 1
    return added


# ---- overrides --------------------------------------------------------------------

SNAP_YD = 15.0
REMOVE_YD = 10.0
# Roads the player drew in game (source "recorded"), the way the addon uses them before
# they're in the data (Router.WithTracks): the stretches along a road are that road, the
# ends join a road this close, and an erased track cuts out the road under it.
# As Router.lua's TRACK_* values: along a road = within "trim" yd and within 30 degrees of
# parallel for "along_min" yd; crossing one = within "cross" yd of it otherwise.
DRAWN = {"trim": 12.0, "snap": 25.0, "min_run": 20.0, "cut": 12.0, "along_min": 15.0, "cross": 3.0,
         "min_piece": 6.0}
DRAWN_CITY = {"trim": 4.0, "snap": 8.0, "min_run": 6.0, "cut": 12.0, "along_min": 4.0, "cross": 1.5,
              "min_piece": 3.0}  # (a city's levels overlap)
ALONG_COS = 0.866
STUB_YD = 15.0  # a cut road's dead-end stub shorter than this goes (Router.TRACK_STUB)
FLOOR_STACK_YD = 8.0  # Router.FLOOR_STACK_YD
LAYER_Z = 5.0  # Router.LAYER_Z


def _closest(pts: np.ndarray, p) -> tuple[float, float]:
    """Distance from p to the polyline pts, and yards along it to the nearest point (the first)."""
    a, b = pts[:-1], pts[1:]
    ab = b - a
    L = np.hypot(*ab.T)
    L2 = np.where(L > 0, L * L, 1)
    t = np.clip(((p - a) * ab).sum(axis=1) / L2, 0, 1)
    d = np.hypot(*(a + ab * t[:, None] - p).T)
    i = int(np.argmin(d))
    return float(d[i]), float(L[:i].sum() + L[i] * t[i])


class LayerFloors:
    """Floors over floors on a level with heights, for a drawn edit made at height `z` (as the addon's
    Router.WithTracks has it): of the roads within FLOOR_STACK_YD (or the edit's reach) of a spot on the
    edit, it changes those about at the height (LAYER_Z) of the one nearest `z` (where one floor alone is
    there, that one). `nz`: each node's height (a road's changes evenly between its ends); the nodes the
    edit makes get theirs there too. The floors are those of the roads as they were when it's made (one
    the edit has cut away already doesn't make the floor over it the only one there)."""

    def __init__(self, g: "RoadGraph", nz: dict, z: float):
        self.g, self.nz, self.z = g, nz, float(z)
        self.before = [(e, e.pts.copy(), e.pts.min(axis=0), e.pts.max(axis=0)) for e in g.edges.values() if len(e.pts) >= 2]

    def edge_height(self, e: Edge, along: float):
        za, zb = self.nz.get(e.a), self.nz.get(e.b)
        if za is None or zb is None:
            return za if za is not None else zb
        return za + (zb - za) * max(0.0, min(1.0, along / max(e.length, 1.0)))

    def floor_here(self, x: float, y: float, r: float | None = None):
        p = np.array([x, y])
        hs = []
        r = max(r or 0.0, FLOOR_STACK_YD)
        for e, pts, lo, hi in self.before:
            if lo[0] - r > x or hi[0] + r < x or lo[1] - r > y or hi[1] + r < y:
                continue
            d, along = _closest(pts, p)
            if d <= r:
                h = self.edge_height(e, along)
                if h is not None:
                    hs.append(h)
        return min(hs, key=lambda h: abs(h - self.z)) if hs else None

    def ok(self, e: Edge, x: float, y: float, along: float, r: float | None = None) -> bool:
        """Whether road e (`along` yards along it) is on the edit's floor under its spot (x, y)."""
        h = self.edge_height(e, along)
        f = self.floor_here(x, y, r) if h is not None else None
        return f is None or abs(h - f) <= LAYER_Z

    def height(self, x: float, y: float) -> float:
        """A new node's height there: the floor nearest the edit's, else its own."""
        f = self.floor_here(x, y)
        return f if f is not None else self.z


def _attach(g: RoadGraph, p: np.ndarray, snap: float = SNAP_YD) -> int:
    """Node at p: an existing node within SNAP_YD, a split point on an edge, or new."""
    best, bd = None, min(snap, SNAP_YD)
    for n, q in g.nodes.items():
        d = float(np.hypot(*(q - p)))
        if d < bd:
            best, bd = n, d
    if best is not None:
        return best
    dist, eid, seg, point = g.nearest_on_edges(p)
    if eid >= 0 and dist < snap:
        return g.split_edge(eid, seg, point)
    return g.add_node(p)


def _in_polygon(poly: np.ndarray, p) -> bool:
    x, y = p
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def cut_under(g: RoadGraph, line, reach: float, parallel: bool = False, area: bool = False, floor=None) -> list[int]:
    """Cut the stretches of road within `reach` of `line` (or of any of a list of lines) out
    of the edges they're on; the rest of each edge stays (split where it was cut). Returns
    the new road ends (nodes). `parallel`: only where the road runs about parallel to it.
    `floor` (LayerFloors): only the roads on its floor, and the new ends get their heights."""
    from skimage.measure import approximate_polygon

    lines = [np.asarray(line, np.float64)] if not isinstance(line, list) else [np.asarray(x, np.float64) for x in line]
    boxes = [(x.min(axis=0) - reach, x.max(axis=0) + reach) for x in lines]
    ends: list[int] = []
    for eid, e in list(g.edges.items()):
        near = [x for x, (lo, hi) in zip(lines, boxes)
                if not ((e.pts.max(axis=0) < lo).any() or (e.pts.min(axis=0) > hi).any())]
        if not near:
            continue
        dense, dirs, dal = [e.pts[0]], [e.pts[1] - e.pts[0]], [0.0]
        along = 0.0
        for a, b in zip(e.pts[:-1], e.pts[1:]):
            L = float(np.hypot(*(b - a)))
            m = max(1, int(np.ceil(L / 2)))
            dense.extend(a + (b - a) * (k / m) for k in range(1, m + 1))
            dirs.extend([b - a] * m)
            dal.extend(along + L * k / m for k in range(1, m + 1))
            along += L
        dense = np.asarray(dense)
        if area:  # (the lines are loops: the road inside them goes)
            under = np.array([any(_in_polygon(x, q) for x in near) for q in dense])
        else:
            under = np.array([any(_under(q, r, x, reach, parallel) for x in near) for q, r in zip(dense, dirs)])
        if floor is not None:  # (on the edit's floor under it: the line's nearest spot, in a loop the road's own)
            under = np.array([bool(u) and floor.ok(e, *(q if area else _under_spot(q, r, near, reach, parallel)), al, reach)
                              for u, q, r, al in zip(under, dense, dirs, dal)])
        if not under.any():
            continue
        g.remove_edge(eid)
        # (a junction the cut took away from under another road: that road's end now)
        ends += [x for x, u in ((e.a, under[0]), (e.b, under[-1])) if u]
        i, n = 0, len(dense)
        while i < n:
            if under[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and not under[j + 1]:
                j += 1
            run = dense[i : j + 1]
            if len(run) >= 2:
                a = e.a if i == 0 else g.add_node(run[0])
                b = e.b if j == n - 1 else g.add_node(run[-1])
                if floor is not None:  # (the cut ends: the road's heights there)
                    for x, k, new in ((a, i, i != 0), (b, j, j != n - 1)):
                        if new:
                            floor.nz[x] = floor.edge_height(e, dal[k])
                ends += [x for x, new in ((a, i != 0), (b, j != n - 1)) if new]
                g.cut_nodes = getattr(g, "cut_nodes", set()) | {x for x, new in ((a, i != 0), (b, j != n - 1)) if new}
                g.add_edge(a, b, approximate_polygon(run, 0.5), e.source)
            i = j + 1
    g.drop_isolated_nodes()
    return ends


def _under(p: np.ndarray, r: np.ndarray, line: np.ndarray, reach: float, parallel: bool) -> bool:
    """Whether p (on a road going r) is within `reach` of `line` (about parallel to it)."""
    if len(line) < 2:
        return bool(np.hypot(*(p - line[0])) <= reach)
    a, b = line[:-1], line[1:]
    ab = b - a
    L2 = (ab ** 2).sum(axis=1)
    t = np.clip(((p - a) * ab).sum(axis=1) / np.where(L2 > 0, L2, 1), 0, 1)
    d = np.hypot(*(a + ab * t[:, None] - p).T)
    ok = d <= reach
    if parallel:
        nv, nr = np.sqrt(L2), np.hypot(*r)
        ok &= (nv > 0) & (nr > 0) & (np.abs(ab @ r) / np.where(nv * nr > 0, nv * nr, 1) >= ALONG_COS)
    return bool(ok.any())


def _under_spot(p: np.ndarray, r: np.ndarray, lines, reach: float, parallel: bool):
    """The spot on `lines` that p (on a road going r) is under, as _under finds it (the first)."""
    for line in lines:
        if len(line) < 2:
            if np.hypot(*(p - line[0])) <= reach:
                return line[0]
            continue
        a, b = line[:-1], line[1:]
        ab = b - a
        L2 = (ab ** 2).sum(axis=1)
        t = np.clip(((p - a) * ab).sum(axis=1) / np.where(L2 > 0, L2, 1), 0, 1)
        q = a + ab * t[:, None]
        ok = np.hypot(*(q - p).T) <= reach
        if parallel:
            nv, nr = np.sqrt(L2), np.hypot(*r)
            ok &= (nv > 0) & (nr > 0) & (np.abs(ab @ r) / np.where(nv * nr > 0, nv * nr, 1) >= ALONG_COS)
        if ok.any():
            return q[int(np.argmax(ok))]
    return p


def _dist_to_polyline(p: np.ndarray, line: np.ndarray) -> float:
    a, b = line[:-1], line[1:]
    ab = b - a
    L2 = (ab ** 2).sum(axis=1)
    t = np.clip(((p - a) * ab).sum(axis=1) / np.where(L2 > 0, L2, 1), 0, 1)
    return float(np.hypot(*(a + ab * t[:, None] - p).T).min())


def apply_overrides(g: RoadGraph, path: Path, city: bool = False, floors=None, keep=None) -> dict:
    """Apply hand-made fixes from a GeoJSON FeatureCollection.

    Each feature is a LineString in world yards ([X, Y] pairs, as shown in the
    map UI's click popup) with properties.op:
      "add"    - add this road; its ends snap to nearby roads (15 yd)
      "remove" - delete road edges lying within 10 yd of this line
    Roads drawn in game (properties.source "recorded") go on in their order after the
    hand-made removes, as the addon has them (DRAWN; DRAWN_CITY on a `city` level).
    `floors(props)`: a drawn edit's floor (LayerFloors) on a level with floors over floors, or None.
    `keep(props)`: only the features it passes.
    """
    stats = {"added": 0, "removed": 0}
    if not Path(path).exists():
        return stats
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    feats = doc.get("features", [])
    par = DRAWN_CITY if city else DRAWN
    for f in feats:
        props = f.get("properties", {})
        if props.get("op") != "remove" or props.get("source") == "recorded":
            continue
        line = np.asarray(f["geometry"]["coordinates"], np.float64)
        if len(line) < 2:
            continue
        for eid, e in list(g.edges.items()):
            samples = e.pts if len(e.pts) > 2 else np.linspace(e.pts[0], e.pts[-1], 5)
            near = np.mean([_dist_to_polyline(p, line) <= REMOVE_YD for p in samples])
            if near >= 0.6:
                g.remove_edge(eid)
                stats["removed"] += 1
    g.drop_isolated_nodes()
    for f in feats:
        props = f.get("properties", {})
        if keep is not None and not keep(props):
            continue
        drawn = props.get("source") == "recorded"
        line = np.asarray(f["geometry"]["coordinates"], np.float64)
        if len(line) < 2:
            continue
        floor = floors(props) if floors is not None and drawn else None
        if props.get("op") == "remove":
            if drawn:
                if props.get("area"):
                    stats["removed"] += len(cut_under(g, line, 0.0, area=True, floor=floor))
                else:
                    stats["removed"] += len(cut_under(g, line, par["cut"], floor=floor))
            continue
        if props.get("op") != "add":
            continue
        if drawn:  # (truth: as the addon has it)
            stats["added"] += add_drawn(g, line, par, floor)
            continue
        # Recorded tracks often ride along known roads too; keep only the new parts.
        pieces = off_network_runs(g, line) if props.get("trim") else [line]
        snap = par["snap"] if drawn else SNAP_YD
        for piece in pieces:
            a = _attach(g, piece[0], snap)
            b = _attach(g, piece[-1], snap)
            if a != b:
                g.add_edge(a, b, piece, "override")
                stats["added"] += 1
    prune_cut_stubs(g)
    return stats


def prune_cut_stubs(g: RoadGraph) -> None:
    """Dead-end stubs the cuts left (a road cut short beside a drawn one) go."""
    cut = getattr(g, "cut_nodes", set())
    for _ in range(3):
        if not cut:
            return
        deg = g.degree()
        gone = [eid for eid, e in g.edges.items() if e.length < STUB_YD and
                ((e.a in cut and deg[e.a] == 1) or (e.b in cut and deg[e.b] == 1))]
        for eid in gone:
            g.remove_edge(eid)
        if not gone:
            break
    g.drop_isolated_nodes()


TRIM_YD = 12.0  # track points this close to a known road are "on" it
MIN_RUN_YD = 20.0


def off_network_runs(g: RoadGraph, line: np.ndarray, trim: float | None = None,
                     min_run: float | None = None) -> list[np.ndarray]:
    """Split a recorded track into the stretches that are not on an existing road.

    Each stretch keeps one on-road point at each end so it joins the network.
    """
    from scipy.spatial import cKDTree
    from skimage.measure import approximate_polygon

    samples = []
    for e in g.edges.values():
        d = np.diff(e.pts, axis=0)
        for p, v in zip(e.pts[:-1], d):
            n = max(1, int(np.hypot(*v) // 3))
            samples.append(p + v * (np.arange(n)[:, None] / n))
        samples.append(e.pts[-1:])
    if not samples:
        return [line]
    tree = cKDTree(np.vstack(samples))
    trim = TRIM_YD if trim is None else trim
    min_run = MIN_RUN_YD if min_run is None else min_run
    # (the line every 2 yards: a crossing is found even between its points)
    dense = [line[0]]
    for a, b in zip(line[:-1], line[1:]):
        m = max(1, int(np.ceil(np.hypot(*(b - a)) / 2)))
        dense.extend(a + (b - a) * (k / m) for k in range(1, m + 1))
    line = np.asarray(dense)
    off = tree.query(line)[0] > trim
    runs, i = [], 0
    while i < len(line):
        if not off[i]:
            i += 1
            continue
        j = i
        while j < len(line) and off[j]:
            j += 1
        run = line[max(i - 1, 0) : min(j + 1, len(line))]
        whole = i == 0 and j == len(line)
        rl = np.hypot(*np.diff(run, axis=0).T).sum() if len(run) >= 2 else 0
        if len(run) >= 2 and (rl >= min_run or (whole and rl >= min(min_run, 8))):
            runs.append(approximate_polygon(run, 2.0))
        i = j
    return runs


def _attach_drawn(g: RoadGraph, p: np.ndarray, reach: float, only: set | None = None, floor=None):
    """As the addon's attach: the node at the nearest point of the roads (of `only` if
    given; on `floor`'s floor) within `reach`, an edge's end if that's within 3 yd along it,
    else the edge split there (both halves join `only`). (node, point) or (None, None)."""
    best = None
    for eid, e in g.edges.items():
        if only is not None and eid not in only:
            continue
        a, b = e.pts[:-1], e.pts[1:]
        ab = b - a
        L = np.hypot(*ab.T)
        L2 = np.where(L > 0, L * L, 1)
        t = np.clip(((p - a) * ab).sum(axis=1) / L2, 0, 1)
        q = a + ab * t[:, None]
        d = np.hypot(*(q - p).T)
        i = int(np.argmin(d))
        if best is None or d[i] < best[0]:
            along = float(L[:i].sum() + L[i] * t[i])
            if floor is None or floor.ok(e, p[0], p[1], along, reach):
                best = (float(d[i]), eid, i, q[i], along, float(L.sum()))
    if best is None or best[0] > reach:
        return None, None
    _, eid, seg, q, along, total = best
    e = g.edges[eid]
    if along < 3:
        return e.a, g.nodes[e.a]
    if along > total - 3:
        return e.b, g.nodes[e.b]
    before = set(g.edges)
    h = floor.edge_height(e, along) if floor is not None else None
    n = g.split_edge(eid, seg, q)
    if floor is not None:
        floor.nz[n] = h
    if only is not None:
        only.discard(eid)
        only.update(set(g.edges) - before)
    return n, q


def add_drawn(g: RoadGraph, line: np.ndarray, par: dict, floor=None) -> int:
    """A road drawn in game, as the addon has it (Router.WithTracks): where it runs along a
    road (close, about parallel, for a while, or at its ends) it replaces that stretch and
    the road's cut ends join it; where it crosses a road it's split and joined there; its
    ends join a road within par["snap"]. `floor` (LayerFloors): only that floor's roads, and
    its new nodes at that floor's height. Returns the edges added."""
    own = [True]
    dense = [line[0]]
    for a, b in zip(line[:-1], line[1:]):
        m = max(1, int(np.ceil(np.hypot(*(b - a)) / 2)))
        for k in range(1, m + 1):
            dense.append(a + (b - a) * (k / m))
            own.append(k == m)
    P = np.asarray(dense)
    M = len(P)
    lo, hi = P.min(axis=0) - par["trim"], P.max(axis=0) + par["trim"]

    def near_segments():
        es = [e for e in g.edges.values()
              if not ((e.pts.max(axis=0) < lo).any() or (e.pts.min(axis=0) > hi).any())]
        if not es:
            return None
        S = np.vstack([np.hstack([e.pts[:-1], e.pts[1:]]) for e in es])
        # (each segment's road and yards along it to its start: the floor check)
        owner = [e for e in es for _ in range(len(e.pts) - 1)]
        start = np.concatenate([np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(e.pts, axis=0).T))[:-1]]) for e in es])
        return S[:, :2], S[:, 2:] - S[:, :2], owner, start

    reach_used = max(par["trim"], par["cross"])

    def nearest(segs, pt):
        if segs is None:
            return np.inf, np.zeros(2)
        a, v, owner, start = segs
        L2 = (v ** 2).sum(axis=1)
        t = np.clip(((pt - a) * v).sum(axis=1) / np.where(L2 > 0, L2, 1), 0, 1)
        d = np.hypot(*(a + v * t[:, None] - pt).T)
        if floor is None:
            i = int(np.argmin(d))
            return float(d[i]), v[i]
        # (the nearest on the edit's floor; only those near enough to matter)
        for i in np.argsort(d, kind="stable"):
            if d[i] > reach_used:
                break
            if floor.ok(owner[i], pt[0], pt[1], float(start[i] + np.sqrt(L2[i]) * t[i]), par["trim"]):
                return float(d[i]), v[i]
        return np.inf, np.zeros(2)

    segs = near_segments()
    along = np.zeros(M, bool)
    for j in range(M):
        d, v = nearest(segs, P[j])
        w = P[min(j + 1, M - 1)] - P[max(j - 1, 0)]
        nv, nw = np.hypot(*v), np.hypot(*w)
        along[j] = d <= par["trim"] and nv > 0 and nw > 0 and abs(float(v @ w)) / (nv * nw) >= ALONG_COS
    along_lines = []
    j = 0
    while j < M:
        if along[j]:
            k = j
            while k + 1 < M and along[k + 1]:
                k += 1
            if j == 0 or k == M - 1 or (k - j) * 2 >= par["along_min"]:
                along_lines.append(P[j : k + 1] if k > j else P[[j, j]])
            j = k + 1
        else:
            j += 1
    cut_ends = cut_under(g, along_lines, par["trim"], parallel=True, floor=floor) if along_lines else []
    segs = near_segments()
    cd = [nearest(segs, P[q])[0] for q in range(M)]
    splits = []
    q = 1
    while q < M - 1:
        if cd[q] <= par["cross"]:
            c1, best = q, q
            while c1 < M - 2 and cd[c1 + 1] <= par["cross"]:
                c1 += 1
                if cd[c1] < cd[best]:
                    best = c1
            splits.append(best)
            q = c1 + 1
        else:
            q += 1
    splits.append(M - 1)
    mine: set = set()
    joined: set = set()
    added = 0
    s0 = 0
    for s1 in splits:
        if s1 > s0:
            keep = [s0] + [i for i in range(s0 + 1, s1) if own[i] and np.hypot(*(P[i] - P[s0])) >= 2
                           and np.hypot(*(P[i] - P[s1])) >= 2] + [s1]
            pts = P[keep].copy()
            na, pa = _attach_drawn(g, pts[0], par["snap"] if s0 == 0 else par["cross"] + 1, floor=floor)
            nb, pb = _attach_drawn(g, pts[-1], par["snap"] if s1 == M - 1 else par["cross"] + 1, floor=floor)
            if na is None:
                na = g.add_node(pts[0])
                if floor is not None:
                    floor.nz[na] = floor.height(*pts[0])
            if nb is None:
                nb = g.add_node(pts[-1])
                if floor is not None:
                    floor.nz[nb] = floor.height(*pts[-1])
            if na != nb:
                before = set(g.edges)
                g.add_edge(na, nb, pts, "override")
                mine |= set(g.edges) - before
                joined |= {na, nb}
                added += 1
        s0 = s1
    # (only those left a dead end: a road still going through a node needs nothing)
    deg: dict = {}
    for eid, e in g.edges.items():
        if eid not in mine:
            deg[e.a] = deg.get(e.a, 0) + 1
            deg[e.b] = deg.get(e.b, 0) + 1
    for ce in cut_ends:
        if ce in joined or ce not in g.nodes or deg.get(ce) != 1:
            continue
        joined.add(ce)
        nm, pm = _attach_drawn(g, g.nodes[ce], par["trim"] + 4, mine, floor=floor)
        if nm is not None and nm != ce:
            before = set(g.edges)
            g.add_edge(ce, nm, [g.nodes[ce], pm], "override")
            mine |= set(g.edges) - before
            added += 1
    return added

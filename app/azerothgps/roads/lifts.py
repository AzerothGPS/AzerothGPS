"""Lifts outside the capitals (asked, 2026-10-01; Thunder Bluff's are capitals.py's, Undercity's cities.py's):
a road from the lift's top landing down its shaft to the bottom one, written as source 5 (Router.SOURCE_LIFT),
so a route over it is kind KIND_LIFT_DOWN / UP, drawn as a ride, and Turns says "Take the lift down" (or up);
its length counts the wait and the ride (capitals.LIFT_SECONDS).

The lifts are the server's elevators (gameobjects of type 11, the CMaNGOS dump under data/thirdparty: each
shaft's car spawned at its top or its bottom); the landings were measured against the terrain's heights (the
road ends at the top and at the bottom, caves.Ground) once, 2026-10-01, so the road build needs no client data.

LAND: the continents' (roads.build.finish_continent: a landing with no road node near it gets one, joined to
the nearest road within LANDING_JOIN_YD). INSTANCE: the dungeons' (instances.instances_lua: their road
nodes at those heights)."""

from __future__ import annotations

import math

LANDING_NODE_YD = 15  # a road node this close to a landing is it
LANDING_JOIN_YD = 70  # else the landing joins the nearest road this close (a spur)

# (x, y) on the continent; the shaft between them is drawn through
LAND = {
    1: [
        # The Great Lift, the Barrens down to Thousand Needles: the Barrens' road ends 78 yd from the
        # shafts up top (ground 86), Thousand Needles' at their foot (ground -52); cars at 85 and -44.
        {"name": "The Great Lift", "top": (-4591.0, -1849.0), "shaft": (-4668.0, -1839.0), "bottom": (-4674.0, -1836.0)},
        # Freewind Post's, on its mesa in Thousand Needles: no road up top (the post and its flight master
        # are off the roads); cars at 89 and -41, the valley road passing their foot.
        {"name": "Freewind Post", "top": (-5399.0, -2505.0), "shaft": (-5390.0, -2497.0), "bottom": (-5382.0, -2489.0)},
    ],
}

# instance map id -> lifts: landings (x, y, z) at its roads' nodes' heights
INSTANCE = {
    # Gnomeregan's elevator ("Vator2", spawned up top at -272): its upper road ends 20 yd from the shaft,
    # the floor 44 yd under it 28 yd away
    90: [{"name": "Gnomeregan's lift", "top": (-796.0, 307.0, -272.0), "shaft": (-807.0, 324.0),
          "bottom": (-826.0, 345.0, -316.0)}],
}


def wait_yards() -> float:
    from ..capitals import LIFT_SECONDS

    return LIFT_SECONDS * 7  # (as the capitals' lifts: the wait and the ride, as yards walked)


def add_land_lifts(g, continent: int, log=print) -> int:
    """The continent's lifts into road graph `g` (source "lift", its points from the top landing to the
    bottom one: Router's down is along them). Returns how many."""
    n = 0
    for lift in LAND.get(continent, []):
        ends = []
        for key in ("top", "bottom"):
            x, y = lift[key]
            node = _node_at(g, x, y)
            if node is None:
                node = g.add_node((x, y))
                spur = _join(g, node, x, y)
                if spur is None:
                    log(f"  [{continent}] {lift['name']}: no road within {LANDING_JOIN_YD} yd of its {key}: a dead end")
            ends.append(node)
        top, bottom = ends
        pts = [tuple(g.nodes[top]), lift["shaft"], tuple(g.nodes[bottom])]
        eid = g.add_edge(top, bottom, pts, source="lift")
        g.edges[eid].wait = wait_yards()
        n += 1
    if n:
        log(f"  [{continent}] {n} lift(s): {', '.join(l['name'] for l in LAND[continent])}")
    return n


def _node_at(g, x, y):
    best = min(((math.hypot(p[0] - x, p[1] - y), nid) for nid, p in g.nodes.items()), default=None)
    return best[1] if best and best[0] <= LANDING_NODE_YD else None


def _join(g, node, x, y):
    """A spur from `node` at (x, y) to the nearest point of a road within LANDING_JOIN_YD (that road split
    there): the new edge's id, or None."""
    best = None
    for eid, e in list(g.edges.items()):
        if e.source == "lift" or node in (e.a, e.b):
            continue
        for i in range(len(e.pts) - 1):
            (ax, ay), (bx, by) = e.pts[i], e.pts[i + 1]
            vx, vy = bx - ax, by - ay
            L2 = vx * vx + vy * vy
            t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2)) if L2 > 0 else 0.0
            px, py = ax + vx * t, ay + vy * t
            d = math.hypot(px - x, py - y)
            if d <= LANDING_JOIN_YD and (best is None or d < best[0]):
                best = (d, eid, i, (px, py))
    if best is None:
        return None
    _, eid, i, p = best
    mid = g.split_edge(eid, i, p)
    return g.add_edge(node, mid, [(x, y), tuple(g.nodes[mid])], source="terrain")


def add_instance_lifts(map_id: int, nodes: list, edges: list, zs: list | None, log=print) -> set:
    """The dungeon's lifts onto its roads as written (nodes [(x, y)], edges [(a, b, pts)], zs the nodes'
    heights): an edge from the node at its top landing to the one at its bottom (each within
    LANDING_NODE_YD and 8 yd of the landing's height). Returns the new edges' indices."""
    out = set()
    for lift in INSTANCE.get(map_id, []):
        ends = []
        for key in ("top", "bottom"):
            x, y, z = lift[key]
            cand = [(math.hypot(nx - x, ny - y), i) for i, (nx, ny) in enumerate(nodes)
                    if math.hypot(nx - x, ny - y) <= LANDING_NODE_YD and (not zs or abs(zs[i] - z) <= 8)]
            ends.append(min(cand)[1] if cand else None)
        if None in ends:
            log(f"  {lift['name']}: no road at its {'top' if ends[0] is None else 'bottom'}: left out")
            continue
        a, b = ends
        edges.append((a, b, [tuple(nodes[a]), lift["shaft"], tuple(nodes[b])]))
        out.add(len(edges) - 1)
        log(f"  {lift['name']}: a lift road, {zs[a] - zs[b]:.0f} yd down" if zs else f"  {lift['name']}: a lift road")
    return out

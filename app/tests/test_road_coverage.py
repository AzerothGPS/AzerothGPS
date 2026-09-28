"""Road coverage: roads that used to be missing from the extracted network.

The data checks read the shipped Data/Roads.lua: two known places must be joined by road,
with each place near a road and the road not far longer than the straight line.
"""

import heapq
import math
import re

import numpy as np
import pytest

from azerothgps.extract.spike import is_road, load_road_rules
from azerothgps.paths import ADDON_DIR
from azerothgps.roads.graph import RoadGraph, bridge_gaps


# ---- the shipped network -----------------------------------------------------------

def _parse_roads(text: str) -> dict:
    roads, cur, inside = {}, None, False
    for line in text.splitlines():
        # (only ns.Roads: the tables after it, e.g. ns.Walls, look alike)
        if line.startswith("ns."):
            inside = line.startswith("ns.Roads")
            continue
        if not inside:
            continue
        m = re.match(r"\s*\[(\d+)\] = \{", line)
        s = line.strip()
        if m:
            cur = int(m.group(1))
            roads[cur] = {"n": [], "e": []}
        elif cur is not None and s.startswith("n = {"):
            v = [float(x) for x in s[5:-2].split(",")]
            roads[cur]["n"] = list(zip(v[0::2], v[1::2]))
        elif cur is not None and re.match(r"\{\d", s):
            v = [float(x) for x in s[1:-2].split(",")]
            roads[cur]["e"].append((int(v[0]) - 1, int(v[1]) - 1, v[2], list(zip(v[4::2], v[5::2]))))
    return roads


@pytest.fixture(scope="module")
def roads():
    return _parse_roads((ADDON_DIR / "Data" / "Roads.lua").read_text(encoding="utf-8"))


def _snap(net, p):
    """(distance, edge index, distance along the edge) of the road point nearest p."""
    best = (math.inf, -1, 0.0)
    for i, (_a, _b, _len, pts) in enumerate(net["e"]):
        acc = 0.0
        for u, v in zip(pts[:-1], pts[1:]):
            ab = np.subtract(v, u)
            L = float(np.hypot(*ab))
            t = 0.0 if L == 0 else min(1.0, max(0.0, float(np.dot(np.subtract(p, u), ab)) / (L * L)))
            d = float(np.hypot(*(np.add(u, ab * t) - p)))
            if d < best[0]:
                best = (d, i, acc + L * t)
            acc += L
    return best


def road_trip(net, p, q):
    """(snap distance at p, at q, road distance between the snapped points or inf)."""
    sp, sq = _snap(net, p), _snap(net, q)
    adj = {}
    for a, b, L, _ in net["e"]:
        adj.setdefault(a, []).append((b, L))
        adj.setdefault(b, []).append((a, L))
    ea, eb = net["e"][sp[1]], net["e"][sq[1]]
    goal = {eb[0]: sq[2], eb[1]: eb[2] - sq[2]}
    best = abs(sp[2] - sq[2]) if sp[1] == sq[1] else math.inf
    pq, done = [(sp[2], ea[0]), (ea[2] - sp[2], ea[1])], set()
    heapq.heapify(pq)
    while pq:
        d, n = heapq.heappop(pq)
        if n in done:
            continue
        done.add(n)
        if n in goal:
            best = min(best, d + goal[n])
        for m, L in adj.get(n, []):
            if m not in done:
                heapq.heappush(pq, (d + L, m))
    return sp[0], sq[0], best


# (continent, from, to): world (X north, Y west) of places a road runs between.
TRIPS = {
    # Dun Morogh: its roads are painted with a cracked-rock texture, not a "road" one.
    "Kharanos to Gol'Bolar Quarry": (0, (-5586.0, -482.1), (-5783.3, -1583.3)),
    # Winterspring: the Everlook roads are painted with the zone's dirt.
    "Everlook to Starfall Village": (1, (6799.2, -4742.4), (7183.3, -3950.0)),
    # Badlands: sand-painted roads, south from Kargath.
    "Kargath to the south road": (0, (-6634.0, -2180.1), (-7266.0, -2328.0)),
    # Desolace: the main north-south road (cracked ground), once only a few bits.
    "Desolace north to south": (1, (62.0, 1716.0), (-1527.0, 1221.0)),
    # The Barrens: Crossroads to Ratchet (unchanged, a check the joins break nothing).
    "Crossroads to Ratchet": (1, (-414.0, -2646.0), (-955.0, -3660.0)),
}


@pytest.mark.parametrize("name", sorted(TRIPS))
def test_road_between_places(roads, name):
    cont, p, q = TRIPS[name]
    dp, dq, d = road_trip(roads[cont], p, q)
    straight = math.dist(p, q)
    assert dp < 60 and dq < 60, f"{name}: ends {dp:.0f} / {dq:.0f} yd from a road"
    assert d < 1.8 * straight, f"{name}: road {d:.0f} yd for {straight:.0f} yd straight"


# ---- extraction rules -------------------------------------------------------------

def test_strict_textures_count_as_road():
    rules = load_road_rules()
    for name in ("tileset/desolace/desolacecracks_s.blp", "tileset/ironforge/ironforgerock09browncracks_s.blp",
                 "tileset/the badlands/badlandssand_s.blp", "tileset/winterspring grove/winterspringdirt_s.blp"):
        assert name in rules["strict"] and is_road(name, rules)
    assert not is_road("tileset/desolace/desolacedirtfootprints_s.blp", rules)


def _line_graph(*segments):
    g = RoadGraph()
    for a, b in segments:
        na, nb = g.add_node(a), g.add_node(b)
        g.add_edge(na, nb, np.linspace(a, b, 10))
    return g


def test_far_ends_join_over_open_ground_only():
    # A road whose texture fades out for 200 yd: the two stretches face each other.
    segs = (((0, 0), (0, 300)), ((0, 500), (0, 800)))
    g = _line_graph(*segs)
    assert bridge_gaps(g, far_end_max=250, clear=lambda p, q: True) == 1
    g.contract_degree2()
    assert len(g.edges) == 1 and g.total_length() == pytest.approx(800)
    # not over a cliff or water, and not without the long-join settings
    assert bridge_gaps(_line_graph(*segs), far_end_max=250, clear=lambda p, q: False) == 0
    assert bridge_gaps(_line_graph(*segs)) == 0


def test_far_join_needs_real_roads():
    # A 30 yd whisker (a town square's edge, a crack) doesn't reach out 200 yd.
    g = _line_graph(((0, 0), (0, 300)), ((0, 500), (0, 530)))
    assert bridge_gaps(g, far_end_max=250, clear=lambda p, q: True) == 0


def test_road_end_heading_at_a_road_joins_it():
    # A side road stops 50 yd short of the main road, heading straight at it.
    g = _line_graph(((0, 0), (0, 400)), ((300, 200), (50, 200)))
    assert bridge_gaps(g, far_edge_max=60, clear=lambda p, q: True) == 1
    assert max(g.degree().values()) == 3
    # heading along the road instead of at it: no join
    g2 = _line_graph(((0, 0), (0, 400)), ((50, 500), (50, 450)))
    assert bridge_gaps(g2, far_edge_max=60, clear=lambda p, q: True) == 0

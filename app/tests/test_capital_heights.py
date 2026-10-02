"""Capital roads' node heights follow the floor (capitals.split_by_height). Asked by the StreetView session,
2026-10-02: a city spot's height is read straight between its road's two nodes, and on long roads climbing
between levels 31 roads put cameras in rock, 18 yd under Orgrimmar's street, or in the air in Darnassus."""

import math

from azerothgps.capitals import SPLIT_Z_TOL, split_by_height


def ramp(x, y):  # flat at 0 up to x = 10, up to 20 at x = 20, flat after; nothing past x = 45
    if x > 45:
        return None
    return 0.0 if x < 10 else 20.0 if x > 20 else (x - 10) * 2.0


def heights_along(nodes, edges, hs, i):
    """(x, z read straight between the piece's ends) every yard along edge i's piece."""
    a, b, pts = edges[i]
    out = []
    length = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))
    along = 0.0
    for p, q in zip(pts, pts[1:]):
        seg = math.hypot(q[0] - p[0], q[1] - p[1])
        for j in range(int(seg)):
            t = j / seg
            x = p[0] + (q[0] - p[0]) * t
            out.append((x, hs[a] + (hs[b] - hs[a]) * (along + j) / length))
        along += seg
    return out


def test_a_road_climbing_between_levels_gets_nodes_where_it_bends():
    nodes = [(0.0, 0.0), (40.0, 0.0)]
    edges = [(0, 1, [(0.0, 0.0), (40.0, 0.0)])]
    n2, e2, h2 = split_by_height(nodes, edges, [0.0, 20.0], ramp)
    assert len(n2) > 2 and e2[0][0] == 0  # (new nodes; the road's first piece keeps its index)
    for i in range(len(e2)):
        for x, z in heights_along(n2, e2, h2, i):
            assert abs(z - ramp(x, 0)) <= SPLIT_Z_TOL + 0.5, (i, x, z)
    # (the pieces join up end to end, from the first node to the last)
    ends = {(a, b) for a, b, _ in e2}
    assert any(a == 0 for a, _ in ends) and any(b == 1 for _, b in ends)


def test_a_flat_road_and_left_alone_ones_stay_whole():
    nodes = [(0.0, 0.0), (8.0, 0.0), (30.0, 0.0), (40.0, 0.0)]
    edges = [(0, 1, [(0.0, 0.0), (8.0, 0.0)]),  # (flat: nothing to do)
             (2, 3, [(30.0, 0.0), (40.0, 0.0)]),  # (flat up there too)
             (0, 3, [(0.0, 0.0), (40.0, 0.0)])]  # (a stair, say: skipped)
    n2, e2, h2 = split_by_height(nodes, edges, [0.0, 0.0, 20.0, 20.0], ramp, skip={2})
    assert n2 == nodes and e2 == edges


def test_an_unknown_node_height_takes_the_floor_next_to_it():
    nodes = [(0.0, 0.0), (50.0, 0.0)]
    edges = [(0, 1, [(0.0, 0.0), (44.0, 0.0), (50.0, 0.0)])]
    _, _, h2 = split_by_height(nodes, edges, [None, None], ramp)
    assert h2[0] == 0.0 and h2[1] == 20.0  # (the last floor read along it: 50 is past the floor's end)

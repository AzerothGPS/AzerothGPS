import json

import numpy as np
import pytest

from azerothgps.roads.graph import RoadGraph, apply_overrides, bridge_gaps, skeleton_to_graph

ident = lambda r, c: (float(r), float(c))  # 1 px = 1 yd, rows = X, cols = Y


def canvas(h=60, w=60):
    return np.zeros((h, w), bool)


def test_plus_sign():
    s = canvas()
    s[30, 5:55] = True
    s[5:55, 30] = True
    g = skeleton_to_graph(s, ident)
    g.contract_degree2()
    deg = g.degree()
    assert sorted(deg.values()) == [1, 1, 1, 1, 4]
    assert len(g.edges) == 4
    assert g.total_length() == pytest.approx(98, abs=3)


def test_straight_line():
    s = canvas()
    s[10, 5:50] = True
    g = skeleton_to_graph(s, ident)
    g.contract_degree2()
    assert len(g.edges) == 1 and len(g.nodes) == 2
    assert g.total_length() == pytest.approx(44, abs=1)


def test_diagonal_staircase_is_one_edge():
    s = canvas()
    for i in range(40):
        s[5 + i, 5 + i] = True
        s[5 + i, 6 + i] = True  # thick staircase like skeletonize can leave
    from skimage.morphology import skeletonize

    g = skeleton_to_graph(skeletonize(s), ident)
    g.contract_degree2()
    g.prune_spurs(5)
    assert len(g.edges) == 1


def test_closed_loop():
    s = canvas()
    s[10, 10:40] = True
    s[40, 10:40] = True
    s[10:41, 10] = True
    s[10:41, 39] = True
    g = skeleton_to_graph(s, ident)
    g.contract_degree2()
    assert len(g.edges) >= 1
    assert g.total_length() == pytest.approx(120, abs=6)


def test_spur_pruning_keeps_main_road():
    s = canvas(80, 80)
    s[40, 5:75] = True  # main road
    s[35:40, 40] = True  # 5-px whisker
    g = skeleton_to_graph(s, ident)
    g.contract_degree2()
    g.prune_spurs(10)
    assert len(g.edges) == 1
    assert g.total_length() == pytest.approx(69, abs=2)


def test_small_components_removed():
    s = canvas(80, 80)
    s[10, 5:75] = True
    s[50, 20:25] = True  # decorative speck
    g = skeleton_to_graph(s, ident)
    g.contract_degree2()
    g.remove_small_components(30)
    assert len(g.edges) == 1


def line_graph(*segments):
    g = RoadGraph()
    for a, b in segments:
        na, nb = g.add_node(a), g.add_node(b)
        g.add_edge(na, nb, np.linspace(a, b, 10))
    return g


def test_bridge_aligned_ends():
    # Road broken by a 40 yd river gap: ends face each other.
    g = line_graph(((0, 0), (0, 100)), ((0, 140), (0, 240)))
    assert bridge_gaps(g) == 1
    g.contract_degree2()
    assert len(g.edges) == 1 and g.total_length() == pytest.approx(240)


def test_no_bridge_for_parallel_roads():
    g = line_graph(((0, 0), (0, 100)), ((30, 0), (30, 100)))
    assert bridge_gaps(g) == 0


def test_t_junction_gap_closed_unless_water():
    g = line_graph(((0, 0), (0, 200)), ((50, 100), (12, 100)))  # stops 12 yd short, heading at the road
    assert bridge_gaps(g) == 1
    assert max(g.degree().values()) == 3
    g2 = line_graph(((0, 0), (0, 200)), ((50, 100), (12, 100)))
    assert bridge_gaps(g2, crosses_water=lambda p, q: True) == 0


def test_overrides(tmp_path):
    g = line_graph(((0, 0), (0, 100)), ((100, 0), (100, 100)))
    doc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"op": "add"},
         "geometry": {"type": "LineString", "coordinates": [[5, 100], [95, 100]]}},  # link the two ends
        {"type": "Feature", "properties": {"op": "remove"},
         "geometry": {"type": "LineString", "coordinates": [[100, -5], [100, 105]]}},  # drop second road
    ]}
    path = tmp_path / "roads_0.geojson"
    path.write_text(json.dumps(doc))
    stats = apply_overrides(g, path)
    assert stats == {"added": 1, "removed": 1}
    assert any(e.source == "override" for e in g.edges.values())
    assert all(abs(e.pts[:, 0].mean() - 100) > 1 for e in g.edges.values() if e.source == "terrain")


def test_json_roundtrip():
    g = line_graph(((0, 0), (0, 100)))
    g2 = RoadGraph.from_json(json.loads(json.dumps(g.to_json())))
    assert len(g2.edges) == 1 and g2.total_length() == pytest.approx(100)


def test_recorded_track_keeps_only_new_road():
    from azerothgps.roads.graph import off_network_runs

    g = line_graph(((0, 0), (0, 300)))  # existing road along Y at X=0
    # Ride 100 yd along the road, then branch off north for 150 yd.
    track = np.array([[0, y] for y in range(0, 101, 5)] + [[x, 100] for x in range(5, 151, 5)], float)
    runs = off_network_runs(g, track)
    assert len(runs) == 1
    run = runs[0]
    assert run[-1] == pytest.approx([150, 100])
    assert run[0][0] <= 12  # starts at the junction, not back at the road start


def test_trimmed_track_override_joins_network(tmp_path):
    g = line_graph(((0, 0), (0, 300)))
    track = [[0, y] for y in range(0, 101, 5)] + [[x, 100] for x in range(5, 151, 5)]
    doc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"op": "add", "trim": True},
         "geometry": {"type": "LineString", "coordinates": track}}]}
    path = tmp_path / "o.geojson"
    path.write_text(json.dumps(doc))
    assert apply_overrides(g, path)["added"] == 1
    assert max(g.degree().values()) == 3  # a T junction where the track left the road


def test_import_tracks_from_savedvariables(tmp_path):
    from azerothgps.roads.tracks import import_tracks

    sv = tmp_path / "WTF" / "ACC#1" / "SavedVariables"
    sv.mkdir(parents=True)
    (sv / "AzerothGPS.lua").write_text("""
AzerothGPSDB = {
  ["tracks"] = {
    { ["op"] = "add", ["continent"] = 1, ["zone"] = "Durotar", ["time"] = 1700000000,
      ["pts"] = { -600, -4180, -610, -4175, -620, -4170, -630, -4165 } },
  },
}
""")
    ov = tmp_path / "overrides"
    assert import_tracks(tmp_path / "WTF", ov) == 1
    assert import_tracks(tmp_path / "WTF", ov) == 0  # already imported
    doc = json.loads((ov / "roads_1.geojson").read_text())
    f = doc["features"][0]
    assert f["properties"]["op"] == "add" and f["properties"]["trim"] is True
    assert f["geometry"]["coordinates"][1] == [-610, -4175]


def test_drawn_roads_go_on_in_order_as_in_game(tmp_path):
    g = line_graph(((0, 0), (0, 300)))
    rec = {"source": "recorded", "trim": True}
    doc = {"type": "FeatureCollection", "features": [
        # stops 18 yd short of the road: joined to it anyway
        {"type": "Feature", "properties": {"op": "add", "time": 1, **rec},
         "geometry": {"type": "LineString", "coordinates": [[200, 150], [100, 150], [18, 150]]}},
        # drawn again, a little off: it replaces the first, not a second road beside it
        {"type": "Feature", "properties": {"op": "add", "time": 2, **rec},
         "geometry": {"type": "LineString", "coordinates": [[204, 146], [100, 155], [3, 152]]}},
        # erased across the road near its start: that stretch is cut out, the rest stays
        {"type": "Feature", "properties": {"op": "remove", "time": 3, **rec},
         "geometry": {"type": "LineString", "coordinates": [[-20, 40], [20, 40]]}},
    ]}
    path = tmp_path / "roads_0.geojson"
    path.write_text(json.dumps(doc))
    apply_overrides(g, path)
    ov = [e for e in g.edges.values() if e.source == "override"]  # (the second replaced the first)
    assert len(ov) == 1 and min(abs(e[0]) for e in ov[0].pts) < 0.01  # on the road
    for e in g.edges.values():
        assert not any(abs(x) < 5 and abs(y - 40) < 5 for x, y in e.pts)
    assert g.total_length() > 300 - 30 + 190


def test_shipped_times_list_the_drawn_roads_in_the_overrides(tmp_path):
    from azerothgps.roads.tracks import shipped_times

    (tmp_path / "roads_0.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"op": "add", "source": "recorded", "time": 5},
         "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
        {"type": "Feature", "properties": {"op": "add"},
         "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}}]}))
    assert shipped_times(tmp_path) == [5]


def test_despeckle_closes_ridge_gaps_and_fills_pockets():
    from azerothgps.roads.terrain import MIN_OPEN, despeckle

    cells = np.zeros((120, 120), np.uint8)
    cells[:, 59:62] = 2  # a ridge across the map ...
    cells[50, 59:62] = 0  # ... with a one-cell gap through it
    cells[10:24, 10:24] = 2  # a mountain ...
    cells[14:20, 14:20] = 0  # ... with a small flat top
    out = despeckle(cells)
    assert out[50, 60] == 2  # the gap is closed
    assert (out[14:20, 14:20] == 2).all()  # the unreachable top is blocked
    assert out[100, 30] == 0 and out[100, 90] == 0  # open ground on both sides stays open
    assert 36 < MIN_OPEN


def test_a_drawn_erase_loop_cuts_the_roads_inside(tmp_path):
    import math as m
    g = line_graph(((0, 0), (0, 300)))
    loop = [[40 * m.cos(k * m.pi / 6), 150 + 40 * m.sin(k * m.pi / 6)] for k in range(13)]
    doc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"op": "remove", "source": "recorded", "time": 1, "area": True},
         "geometry": {"type": "LineString", "coordinates": loop}}]}
    path = tmp_path / "roads_0.geojson"
    path.write_text(json.dumps(doc))
    apply_overrides(g, path)
    assert len(g.edges) == 2
    assert all(abs(y - 150) >= 38 for e in g.edges.values() for _, y in e.pts)

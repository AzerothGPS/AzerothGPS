"""Walking paths of NPCs that travel (couriers, caravans, patrols, escorts), as extra roads.

`agps npc-paths` reads the path files under data/thirdparty/<source>/paths_<map>.geojson
(LineStrings in world yards) and writes overrides/paths_<map>.geojson: the long ones only
(wanderers around a camp say nothing about roads), split where they jump. The road build
applies them to the extracted network before the hand and drawn overrides
(`apply_paths`): only their stretches off the roads are added, joined to the roads at
their ends, and only when they look like a way somewhere (not a loop around a camp).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .graph import RoadGraph, _attach, off_network_runs

SOURCES = ("cmangos-classic-db", "azerothcore")
MIN_EXTENT_YD = 400.0  # a path's bounding box diagonal: shorter ones are wanderers
MAX_HOP_YD = 150.0  # consecutive points farther apart than this: split there
TRIM_YD = 20.0  # path points this close to a road are on it
MIN_RUN_YD = 60.0  # shorter stretches off the roads are left out
MIN_STRAIGHT = 0.4  # a stretch's end-to-end distance over its length at least this
SNAP_YD = 40.0  # a stretch's end joins a road this close


def collect(data_dir: Path, continent: int) -> list[list[list[float]]]:
    """The long paths on a continent, split where they jump."""
    out = []
    for src in SOURCES:
        f = Path(data_dir) / "thirdparty" / src / f"paths_{continent}.geojson"
        if not f.exists():
            continue
        for feat in json.loads(f.read_text(encoding="utf-8"))["features"]:
            c = feat["geometry"]["coordinates"]
            xs, ys = [p[0] for p in c], [p[1] for p in c]
            if len(c) < 2 or math.hypot(max(xs) - min(xs), max(ys) - min(ys)) < MIN_EXTENT_YD:
                continue
            piece = [c[0]]
            for a, b in zip(c, c[1:]):
                if math.dist(a, b) > MAX_HOP_YD:
                    if len(piece) >= 2:
                        out.append(piece)
                    piece = [b]
                elif math.dist(a, b) > 0:
                    piece.append(b)
            if len(piece) >= 2:
                out.append(piece)
    return out


def write_overrides(data_dir: Path, overrides_dir: Path, continents) -> dict[int, int]:
    done = {}
    for cont in continents:
        paths = collect(data_dir, cont)
        if not paths:
            continue
        doc = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"op": "add"},
             "geometry": {"type": "LineString", "coordinates": [[round(x, 1), round(y, 1)] for x, y in p]}}
            for p in paths]}
        (Path(overrides_dir) / f"paths_{cont}.geojson").write_text(json.dumps(doc), encoding="utf-8")
        done[cont] = len(paths)
    return done


def apply_paths(g: RoadGraph, path: Path) -> dict:
    """The paths' stretches off the network, as roads (source "path")."""
    stats = {"added": 0, "yd": 0}
    if not Path(path).exists():
        return stats
    for feat in json.loads(Path(path).read_text(encoding="utf-8"))["features"]:
        line = np.asarray(feat["geometry"]["coordinates"], np.float64)
        if len(line) < 2:
            continue
        for run in off_network_runs(g, line, TRIM_YD, MIN_RUN_YD):
            length = float(np.hypot(*np.diff(run, axis=0).T).sum())
            if length < MIN_RUN_YD or np.hypot(*(run[-1] - run[0])) < MIN_STRAIGHT * length:
                continue
            a = _attach(g, run[0], SNAP_YD)
            b = _attach(g, run[-1], SNAP_YD)
            if a != b:
                g.add_edge(a, b, run, "path")
                stats["added"] += 1
                stats["yd"] += round(length)
    return stats

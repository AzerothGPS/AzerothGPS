"""Buildings on the continents as ground routes can't walk through (addon/AzerothGPS/Data/Buildings.lua).

The continents' passability grid (Data/Terrain.lua) knows the terrain only: slopes and water. A
building (a model placed in the ADTs: Goldshire's inn, a farmhouse, a tower) is open ground to it,
and routes off the roads walked straight through them. Here each building's solid faces (the ones
a character collides with, as the caves' and cities' are read) are cut at a body's height over the
ground: its walls, with the gaps of its doors. Those are drawn on a yard grid, the doorways closed
and the inside filled up to a big hall's size (a fort's yard stays open): the building's footprint. A cell of the continent's grid is blocked where a
footprint covers BLOCK_SHARE of it, and each building blocks at least its best-covered cell (a hut
smaller than a cell). A cell a road runs through stays open (roads are the truth: a gatehouse's arch, a
road along a wall). The addon adds these cells to the grid's blocked ones (Passability's Cell), so
legs off the roads, walks around obstacles and the prepared blocks (hpa.py) all go around them; a
stop inside a building (an innkeeper) is still reached, as a stop in blocked ground is.

Left out: caves and mines (their own grids, caves.py), the capitals' models (capitals.py), and
models bigger than MAX_SIZE_YD (a city, a mountain: not a building).
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np

from . import interiors as I
from . import walknet
from .caves import CAVE_KINDS, Ground
from .extract.spike import ClientData
from .paths import ADDON_DIR

FILE = ADDON_DIR / "Data" / "Buildings.lua"
TILE = 1600 / 3
BODY_YD = 1.2  # the cut: this far over the ground under each face (a body's height)
WALL_SLOPE = 0.5  # faces steeper than this are walls (walknet.model_faces)
DOOR_YD = 2  # the closing's reach: gaps up to about twice this (doorways) are shut before filling
ROOM_MAX_YD2 = 2500.0  # an inside filled up to this big (a hall, an inn); a bigger one is a yard (a fort's) left open
BLOCK_SHARE = 0.4  # a grid cell is blocked where a footprint covers this share of it
MIN_BEST_YD2 = 12.0  # a building's best-covered cell is blocked when it covers at least this much of it
MAX_SIZE_YD = 250.0  # bigger models aren't buildings (a city, a mountain's inside)


def grid_frames(path: Path | None = None) -> dict:
    """The continents' grids as Data/Terrain.lua has them: cont -> (tx0, ty0, cell, w, h)."""
    text = (path or ADDON_DIR / "Data" / "Terrain.lua").read_text(encoding="utf-8")
    text = text[:text.find("ns.Hills")]  # (the hills' coarser grids come after, in the same form)
    out = {}
    for m in re.finditer(r"^  \[(\d+)\] = \{ tx0 = (-?\d+), ty0 = (-?\d+), cell = ([\d.]+), w = (\d+), h = (\d+), rows",
                         text, re.M):
        out[int(m.group(1))] = (int(m.group(2)), int(m.group(3)), float(m.group(4)), int(m.group(5)), int(m.group(6)))
    return out


def to_cell(frame, X, Y):
    """World points -> the grid's (row, col), 1-based as the addon's (Passability's ToCell)."""
    tx0, ty0, cell, _w, _h = frame
    k = TILE / cell
    col = np.floor(((32 - Y / TILE) - tx0) * k).astype(int) + 1
    row = np.floor(((32 - X / TILE) - ty0) * k).astype(int) + 1
    return row, col


def buildings(cd: ClientData, cont: int) -> list:
    """The continent's placements that are buildings."""
    from .capitals import CAPITALS

    skip = {uid for c in CAPITALS if c.cont == cont for uid in c.wmos}
    out = []
    for p in I.placements(cd, cont):
        if p.uid in skip:
            continue
        x0, y0, x1, y1 = p.bounds
        if x1 - x0 > MAX_SIZE_YD or y1 - y0 > MAX_SIZE_YD:
            continue
        path = cd.name(p.wmo) or ""
        parts = path.split("/")
        if len(parts) >= 4 and parts[2] == "dungeon" and parts[3] in CAVE_KINDS:
            continue
        out.append(p)
    return out


_WALLS: dict = {}


def model_walls(cd: ClientData, wmo: int) -> np.ndarray:
    """A model's wall faces in its own frame: (n, 3, 3)."""
    if wmo not in _WALLS:
        try:
            _floors, walls, _liq = walknet.model_faces(cd, wmo, WALL_SLOPE)
        except Exception:
            walls = []
        _WALLS[wmo] = np.array([tri for _gi, _z, tri in walls], float).reshape(-1, 3, 3)
    return _WALLS[wmo]


def cut(cd: ClientData, p, ground: Ground) -> np.ndarray:
    """A placed building's walls at a body's height over the ground: segments (m, 2, 2) world (X, Y)."""
    T = model_walls(cd, p.wmo)
    if not len(T):
        return np.zeros((0, 2, 2))
    xf = walknet.Placed(p)
    W = T @ xf.m.T + xf.o  # (n, 3, 3) world
    cx, cy = W[:, :, 0].mean(axis=1), W[:, :, 1].mean(axis=1)
    gh, _ok = ground.sample(cx, cy)
    h = gh + BODY_YD
    pts = []
    for i in range(3):
        a, b = W[:, i], W[:, (i + 1) % 3]
        da, db = a[:, 2] - h, b[:, 2] - h
        cross = (da * db < 0) & np.isfinite(h)
        s = np.where(cross, da / np.where(cross, da - db, 1), 0)
        pts.append((cross, a[:, :2] + (b[:, :2] - a[:, :2]) * s[:, None]))
    segs = []
    n_cross = pts[0][0].astype(int) + pts[1][0] + pts[2][0]
    two = n_cross == 2
    for i in range(3):
        for j in range(i + 1, 3):
            sel = two & pts[i][0] & pts[j][0]
            if sel.any():
                segs.append(np.stack([pts[i][1][sel], pts[j][1][sel]], axis=1))
    return np.concatenate(segs) if segs else np.zeros((0, 2, 2))


def footprint(segs: np.ndarray):
    """A building's footprint from its walls: (x0, y0, mask) on a yard grid (rows X, cols Y)."""
    from scipy import ndimage

    if not len(segs):
        return None
    P = segs.reshape(-1, 2)
    x0, y0 = math.floor(P[:, 0].min()) - 4, math.floor(P[:, 1].min()) - 4
    H, W = int(math.ceil(P[:, 0].max())) - x0 + 5, int(math.ceil(P[:, 1].max())) - y0 + 5
    m = np.zeros((H, W), bool)
    L = np.hypot(segs[:, 1, 0] - segs[:, 0, 0], segs[:, 1, 1] - segs[:, 0, 1])
    for k in range(int(max(1, math.ceil(L.max() * 2))) + 1):
        t = np.minimum(1.0, k / np.maximum(1e-9, L * 2))
        X = segs[:, 0, 0] + (segs[:, 1, 0] - segs[:, 0, 0]) * t
        Y = segs[:, 0, 1] + (segs[:, 1, 1] - segs[:, 0, 1]) * t
        m[(X - x0).astype(int), (Y - y0).astype(int)] = True
    shut = ndimage.binary_closing(m, structure=np.ones((2 * DOOR_YD + 1, 2 * DOOR_YD + 1), bool)) | m
    inside = ndimage.binary_fill_holes(shut) & ~shut
    lab, n = ndimage.label(inside)
    if n:
        sizes = np.bincount(lab.ravel())
        inside &= sizes[lab] <= ROOM_MAX_YD2  # (rooms; not a courtyard or a fort's yard)
    return x0, y0, shut | inside


def blocked_cells(cd: ClientData, cont: int, frame, log=print, box=None) -> tuple[set, list]:
    """The grid cells the continent's buildings block, and each building's footprint (for renders).
    `box`: (X0, Y0, X1, Y1) world, only the buildings there."""
    ground = Ground(cd, cont)
    cells: set = set()
    shapes = []
    ps = buildings(cd, cont)
    if box:
        ps = [p for p in ps if p.bounds[2] >= box[0] and p.bounds[0] <= box[2] and p.bounds[3] >= box[1] and p.bounds[1] <= box[3]]
    for n, p in enumerate(ps):
        if n % 500 == 0:
            log(f"  [{cont}] building {n} of {len(ps)}")
        fp = footprint(cut(cd, p, ground))
        if fp is None:
            continue
        x0, y0, m = fp
        ii, jj = np.nonzero(m)
        if not len(ii):
            continue
        X, Y = x0 + ii + 0.5, y0 + jj + 0.5
        r, c = to_cell(frame, X, Y)
        keys, counts = np.unique(r * 65536 + c, return_counts=True)
        area = frame[2] ** 2
        mine = set(int(k) for k in keys[counts >= BLOCK_SHARE * area])
        best = int(np.argmax(counts))
        if counts[best] >= MIN_BEST_YD2:
            mine.add(int(keys[best]))
        cells |= mine
        shapes.append((p, x0, y0, m, mine))
    return cells, shapes


def road_cells(cont: int, frame) -> set:
    """The grid cells the shipped roads (Data/Roads.lua) run through, sampled every yard."""
    from .caves import shipped_roads

    out = set()
    g = shipped_roads(cont)
    for e in (g.edges.values() if isinstance(g.edges, dict) else g.edges):
        P = np.asarray(e.pts, float)
        for a, b in zip(P[:-1], P[1:]):
            n = max(1, int(math.ceil(math.hypot(*(b - a)))))
            t = np.linspace(0, 1, n + 1)
            r, c = to_cell(frame, a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            out.update((r * 65536 + c).tolist())
    return out


def buildings_lua(cd: ClientData, continents=None, log=print) -> tuple[str, dict]:
    """Data/Buildings.lua: each continent's blocked cells as runs along rows (row, first col, count)."""
    if continents is None:
        from .extract.pipeline import CONTINENTS as continents
    frames = grid_frames()
    out = ["-- GENERATED by `agps buildings` (app/azerothgps/buildings.py) from client "
           f"{cd.casc.version}. Do not edit by hand.",
           "-- The continents' buildings, as grid cells routes don't walk through (the cells of",
           "-- Data/Terrain.lua's grid): per continent, runs along its rows: row, first column, count.",
           "local _, ns = ...", "ns.BuildingCells = {"]
    counts = {}
    for cont in continents:
        if cont not in frames:
            continue
        cells, _ = blocked_cells(cd, cont, frames[cont], log)
        cells -= road_cells(cont, frames[cont])
        runs = []
        for key in sorted(cells):
            r, c = divmod(key, 65536)
            if runs and runs[-1][0] == r and runs[-1][1] + runs[-1][2] == c:
                runs[-1][2] += 1
            else:
                runs.append([r, c, 1])
        counts[cont] = len(cells)
        flat = [str(v) for run in runs for v in run]
        out.append(f"  [{cont}] = {{")
        for i in range(0, len(flat), 30):
            out.append("    " + ",".join(flat[i:i + 30]) + ",")
        out.append("  },")
    out.append("}")
    return "\n".join(out) + "\n", counts


def render(cd: ClientData, cont: int, X: float, Y: float, R: float, out: Path, scale: float = 3.0) -> dict:
    """A picture of the buildings around world (X, Y), R yards each way (north up): the terrain's
    blocked cells (gray), the cells the buildings block (dark red), their footprints (red) and the
    roads (tan). For checking by eye; returns counts."""
    from PIL import Image, ImageDraw

    from .caves import shipped_roads
    from .roads.terrain import decode_row

    frame = grid_frames()[cont]
    cells, shapes = blocked_cells(cd, cont, frame, log=lambda *a: None, box=(X - R, Y - R, X + R, Y + R))
    cells -= road_cells(cont, frame)  # (as the data: a road keeps its cells open)
    S = scale
    Wpx = int(2 * R * S)
    img = Image.new("RGB", (Wpx, Wpx), (26, 32, 24))
    dr = ImageDraw.Draw(img, "RGBA")

    def px(x, y):  # (north up, west left)
        return (Y + R - y) * S, (X + R - x) * S

    tx0, ty0, cell, _w, _h = frame
    text = (ADDON_DIR / "Data" / "Terrain.lua").read_text(encoding="utf-8")
    rows = re.search(r"^  \[%d\] = \{ tx0.*?rows = \{\n(.*?)\n  \} \}," % cont, text, re.S | re.M).group(1).splitlines()
    k = TILE / cell

    def corner(r, c):  # a cell's north-west corner in world yards
        return (32 - ty0 - (r - 1) / k) * TILE, (32 - tx0 - (c - 1) / k) * TILE
    r0, c0 = to_cell(frame, np.array([X + R]), np.array([Y + R]))
    r1, c1 = to_cell(frame, np.array([X - R]), np.array([Y - R]))
    for r in range(int(r0[0]), int(r1[0]) + 1):
        vals = decode_row(rows[r - 1].strip().strip('",'))
        for c in range(int(c0[0]), int(c1[0]) + 1):
            x, y = corner(r, c)
            box = [px(x, y), px(x - cell, y - cell)]
            if vals[c - 1] == 2:
                dr.rectangle(box, fill=(90, 90, 90, 255))
            if r * 65536 + c in cells:
                dr.rectangle(box, fill=(120, 20, 20, 255), outline=(200, 60, 60, 255))
    g = shipped_roads(cont)
    for e in (g.edges.values() if isinstance(g.edges, dict) else g.edges):
        xy = [px(float(p[0]), float(p[1])) for p in e.pts]
        if any(0 <= a <= Wpx and 0 <= b <= Wpx for a, b in xy):
            dr.line(xy, fill=(180, 150, 90, 255), width=4)
    for p, x0, y0, m, _mine in shapes:
        ii, jj = np.nonzero(m)
        for i, j in zip(ii, jj):
            a, b = px(x0 + i + 1, y0 + j + 1)
            dr.rectangle([a, b, a + S - 1, b + S - 1], fill=(255, 70, 70, 150))
    dr.line([(10, Wpx - 10), (10 + 50 * S, Wpx - 10)], fill=(255, 255, 255, 255), width=3)
    img.save(out)
    return {"buildings": len(shapes), "cells": len(cells)}

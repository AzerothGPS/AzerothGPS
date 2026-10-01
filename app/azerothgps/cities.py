"""City levels: underground cities as their own routing level (Data/Cities.lua).

Undercity lies under the Ruins of Lordaeron: on a flat map its streets overlap the ruins
and the land around, so it gets its own level, a pseudo-continent (CITY_ID) that draws in
its base continent's coordinates (Geo.ToContinent treats it as the base) but connects to
the surface only through its lifts.

From the city's WMO (walknet.py builds the walk network of its floors):
- walkable floors (faces pointing up, by the vertex normals: the one-floor grid; for the
  layered roads, the faces a character collides with, from the MPY2 flags, either side up),
  minus the canal beds (water) and anything well above street level (arch tops,
  roofs), except the sewers, which climb;
- a passability grid of them (the same format as Data/Terrain.lua: 0 open, 2 blocked), so
  routes inside keep to the floors and off-road legs don't cross walls;
- roads: the centerlines of the walkable area (the grid thinned to a skeleton);
- the lifts to the ruins: where the lift shafts meet the Trade Quarter's raised ring.
Local z (the WMO's frame) is used for levels: streets about -125, the raised ring -106,
canal beds below -127, the ruins above 0.
"""

from __future__ import annotations

import math
import struct

import numpy as np
from PIL import Image, ImageDraw

from . import interiors as I
from . import walknet
from .extract import adt
from .extract.spike import ClientData
from .roads.terrain import encode_row

TILE = 1600 / 3
CELL = 2.0  # yards per grid cell
UNDERCITY_ID = 10001  # the pseudo-continent of Undercity's level
UNDERCITY_MAP = 1458  # its uiMap (Data/CityPlaces.lua)
LIFT_SECONDS = 25  # waiting for a lift and the ride
LIFT_Z = -104.0  # local z of the lifts' bottoms (the Trade Quarter's raised ring)
LIFT_GAP = 12.0  # yards: a lift's platform joined to the floor out of its shaft across this at most
Z_LOW, NB_BANDS = -150.0, 120  # local z: the city's lowest floor band (the Apothecarium's bottom, about -143), and bands up from it
LAYERED = True  # Undercity's roads on every floor (layers.py), not the top one's in each cell
Z_BEND = 1.5  # yards: a road's floor this far off the even change in height between its nodes: a node there
LAYER_REACH = 6.0  # yards: a road node's floor, this near the height it was given
CANAL_BED = -127.5  # local z: canal floors below this are water
HIGH = -95.0  # local z: floors above this are arch tops and roofs (not the sewers)
STREET = -125.0  # local z of the streets
LEDGE = 3.0  # yards: a drop this big between neighboring cells is a ledge
ROAD_JUMP, ROAD_JUMP_PER_YD = 1.5, 1.0  # yards: Undercity's roads cut where their height jumps more than this (a stair's less)
UC_STEP_CAP = 2.0  # yards: Undercity's steps on foot between neighboring cells, a diagonal's too (walknet.STEP_CAP)
RUINS_WAYS = [  # the Ruins of Lordaeron: the way in from the north gate, and the lifts
    # (from the road outside, down the gate's steps: their treads' edges would close the way)
    [(1882, 236), (1841, 236), (1790, 236), (1761, 238), (1718, 234), (1665, 238), (1630, 232), (1612, 236), (1596, 240)],
    [(1596, 240), (1596, 214), (1597, 190)],  # to the east lift
    [(1596, 240), (1570, 240), (1545, 240)],  # the south lift
    [(1596, 240), (1596, 266), (1595, 291)],  # the west lift
]
RUINS_SLOPE = 0.4  # up top in the ruins: steeper steps are floors too
FLOOR_SLOPE = 0.64  # a floor's normal at least this upright (the city's ramps and stairs are steep)
SMOOTH = 2.0  # yards: roads simplified this far from their centerlines (where it stays on the floor)
HEAD = 3.0  # yards: a face rising this far above a floor is a wall
HALL_KEY = "ruins_of_lordaeron"  # the Ruins' grid in ns.Terrain (over the continent's)
SLACK = 0.0  # yards: blocked cells ignored at a walk's ends (Passability's END_SLACK; walls here are real)
HEIGHT_Z0, HEIGHT_STEP = -140.0, 2.0  # the floor heights written for the addon


def solid_flags(data: bytes, sub: dict) -> list | None:
    """Whether each face of a WMO group is one a character collides with, from its poly flags
    (MOPY, or this client's MPY2: u16 flags and u16 material a face): collision-only ones
    (0x08) and rendered ones that aren't detail (0x20 without 0x04). None: no flags."""
    if "MPY2" in sub:
        pa, pb = sub["MPY2"]
        flags = [struct.unpack_from("<H", data, i)[0] for i in range(pa, pb, 4)]
    elif "MOPY" in sub:
        pa, pb = sub["MOPY"]
        flags = list(data[pa:pb:2])
    else:
        return None
    if not any(flags):
        return None
    return [bool(f & 0x08) or (bool(f & 0x20) and not f & 0x04) for f in flags]


def _floors(cd: ClientData, wmo: int, names: list[str], slope: float = None, solid: bool = False):
    """Walkable faces: (group, name, centroid local z, local triangle), and walls: steep faces
    (group, name, (zmin, zmax), local triangle). The floors run on under the walls, so the
    walls standing at walking height are what closes the way.
    `solid`: only the faces a character collides with (solid_flags), either side up: the city's
    collision faces are often wound upside down (a ramp's, a bridge's deck), and its drawn
    floors over them are decoration a character doesn't stand on."""
    w = I.read_wmo(cd, wmo)
    out, walls, gz = [], [], {}
    for gi in range(min(w.n_groups, len(w.group_files))):
        data = cd.casc.read(w.group_files[gi])
        for magic, a, b in adt.iter_chunks(data):
            if magic != "MOGP":
                continue
            sub = {m: (x, y) for m, x, y in adt.iter_chunks(data, a + 68, b)}
            va, vb = sub["MOVT"]
            verts = [struct.unpack_from("<3f", data, i) for i in range(va, vb, 12)]
            na, nb = sub.get("MONR", (0, 0))
            norms = [struct.unpack_from("<3f", data, i) for i in range(na, nb, 12)]
            ia, ib = sub["MOVI"]
            idx = struct.unpack_from(f"<{(ib - ia) // 2}H", data, ia)
            zs = [v[2] for v in verts]
            gz[gi] = (min(zs), max(zs)) if zs else (0, 0)
            hard = solid_flags(data, sub) if solid else None
            for k in range(len(idx) // 3):
                if hard is not None and (k >= len(hard) or not hard[k]):
                    continue
                i1, i2, i3 = idx[3 * k], idx[3 * k + 1], idx[3 * k + 2]
                a1, a2, a3 = verts[i1], verts[i2], verts[i3]
                ux, uy, uz = a2[0] - a1[0], a2[1] - a1[1], a2[2] - a1[2]
                vx, vy, vz = a3[0] - a1[0], a3[1] - a1[1], a3[2] - a1[2]
                nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
                L = math.sqrt(nx * nx + ny * ny + nz * nz)
                if L == 0:
                    continue
                if abs(nz) / L < (slope or FLOOR_SLOPE):  # a wall (or steeper than a walkable slope)
                    zs3 = (a1[2], a2[2], a3[2])
                    walls.append((gi, names[gi] if gi < len(names) else "", (min(zs3), max(zs3)), (a1, a2, a3)))
                    continue
                if abs(nz) / L < (slope or FLOOR_SLOPE):
                    continue
                if hard is None and norms and norms[i1][2] + norms[i2][2] + norms[i3][2] <= 0:
                    continue
                out.append((gi, names[gi] if gi < len(names) else "", (a1[2] + a2[2] + a3[2]) / 3, (a1, a2, a3)))
            break
    return out, walls, gz


LIQUID_TILE = 4.1666625  # yards: a WMO liquid tile


def _liquids(cd: ClientData, wmo: int) -> list:
    """The model's liquids (slime, water): tiles (group, (x0, y0, x1, y1) local, surface z)."""
    w = I.read_wmo(cd, wmo)
    out = []
    for gi in range(min(w.n_groups, len(w.group_files))):
        data = cd.casc.read(w.group_files[gi])
        for magic, a, b in adt.iter_chunks(data):
            if magic != "MOGP":
                continue
            sub = {m: (x, y) for m, x, y in adt.iter_chunks(data, a + 68, b)}
            if "MLIQ" not in sub:
                break
            la, lb = sub["MLIQ"]
            xv, yv, xt, yt = struct.unpack_from("<4i", data, la)
            cx, cy, _cz = struct.unpack_from("<3f", data, la + 16)
            if xv <= 0 or yv <= 0 or xt <= 0 or yt <= 0 or xv * yv > 100000:
                break
            vbase = la + 30
            hs = [struct.unpack_from("<f", data, vbase + i * 8 + 4)[0] for i in range(xv * yv)]
            tbase = vbase + xv * yv * 8
            for j in range(yt):
                for i in range(xt):
                    if tbase + j * xt + i >= lb:
                        continue
                    if data[tbase + j * xt + i] & 0x0F == 0x0F:  # (no liquid on this tile)
                        continue
                    h = (hs[j * xv + i] + hs[j * xv + i + 1] + hs[(j + 1) * xv + i] + hs[(j + 1) * xv + i + 1]) / 4
                    x0, y0 = cx + i * LIQUID_TILE, cy + j * LIQUID_TILE
                    out.append((gi, (x0, y0, x0 + LIQUID_TILE, y0 + LIQUID_TILE), h))
            break
    return out


def undercity(cd: ClientData, log=print) -> dict:
    """Undercity's level: grid, roads and lifts, in world coordinates."""
    area_names = {(r["WMOID"], r["WMOGroupID"]): r["AreaName_lang"] or "" for r in cd.table("WMOAreaTable")}
    best = None
    for p in I.placements(cd, 0):
        w = I.read_wmo(cd, p.wmo)
        if not w:
            continue
        names = I.group_names(cd, w, area_names)
        if "Trade Quarter" in names:
            area = (p.bounds[2] - p.bounds[0]) * (p.bounds[3] - p.bounds[1])
            if not best or area > best[0]:
                best = (area, p, names)
    _, p, names = best
    t = math.radians(p.yaw + 180)
    c, s = math.cos(t), math.sin(t)

    def world(v):
        return p.x + v[0] * c - v[1] * s, p.y + v[0] * s + v[1] * c

    floors, walls, gz = _floors(cd, p.wmo, names)
    under = {gi for gi, (lo, hi) in gz.items() if lo < -60}

    def down_there(floors, walls):
        """The floors down there: (world triangle, local heights, the sewers' own); the walls."""
        keep = []
        for gi, name, z, tri in floors:
            if gi not in under:
                continue
            if name == "Sewers" or (z <= HIGH and not (name == "Canals" and z < CANAL_BED)):
                keep.append(([world(v) for v in tri], [v[2] for v in tri], name == "Sewers"))
        wl = [(zz, [world(v) for v in tri]) for gi, name, zz, tri in walls if gi in under and name != "Sewers"]
        return keep, wl
    keep, wl = down_there(floors, walls)
    lq = [([world(q) for q in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))], lz)
          for gi, (x0, y0, x1, y1), lz in _liquids(cd, p.wmo) if gi in under]
    # (the sewers, which run over the streets, are walkable but not a level of the heights)
    u = walknet.build(keep, wl, lq, label="Undercity", z0=Z_LOW, nb=NB_BANDS, log=log)
    g, tx0, ty0, cells, top = u["graph"], u["tx0"], u["ty0"], u["cells"], u["top"]
    is_open, height_at, floor_at, stair_z, debug = u["is_open"], u["height_at"], u["floor_at"], u["stair_z"], u["debug"]

    # lifts: the three shafts' bottoms on the Trade Quarter's raised ring. Their caps are the
    # small "Ruins of Lordaeron" floors about 50 below the ruins, straight over the ring.
    caps = [(z, tri) for gi, name, z, tri in floors if name == "Ruins of Lordaeron" and -75 < z < -40]
    pts = np.array([np.mean([world(v) for v in tri], axis=0) for _, tri in caps]) if caps else np.zeros((0, 2))
    lifts = []
    used = np.zeros(len(pts), bool)
    for i in range(len(pts)):
        if used[i]:
            continue
        near = np.hypot(pts[:, 0] - pts[i, 0], pts[:, 1] - pts[i, 1]) < 20
        used |= near
        if near.sum() >= 10:
            lifts.append(tuple(pts[near].mean(0)))
    log(f"  Undercity: {len(lifts)} lifts at " + ", ".join(f"({x:.0f}, {y:.0f})" for x, y in lifts))

    # floors over floors (layers.py): roads on every floor, not only the top one in each cell (a
    # walkway over the bank's level, the canal walks under the bridges), from the faces a
    # character collides with, either side up; doorways' gaps in the floor filled; the lifts'
    # bottoms the ways in. Each road node's height: Roads' z (the game's: the model's + zoff).
    layered = None
    if LAYERED:
        from . import layers
        sfloors, swalls, _ = _floors(cd, p.wmo, names, solid=True)
        skeep, swl = down_there(sfloors, swalls)
        # (steps on foot of at most UC_STEP_CAP, a diagonal's too: the canals' rims, 4 yd up, were
        # one diagonal step, and roads went up on them and across the canal)
        cap, walknet.STEP_CAP = walknet.STEP_CAP, UC_STEP_CAP
        try:
            u2 = walknet.build(skeep, swl, lq, label="Undercity (floors over floors)", z0=Z_LOW, nb=NB_BANDS,
                               log=lambda *a: None)
            # (joins across gaps: only a lift's platform to the floor out of its shaft; the floors'
            # gaps at doorways are filled, and a longer straight join is a way through the air)
            # (and each of its places joined by a road over its floor: CityPlaces' heights, its NPCs')
            from .cityplaces import places
            spots = [(x, y, z - p.z) for _n, x, y, z in places(UNDERCITY_MAP)]
            layered = layers.build(u2, [(x, y, LIFT_Z) for x, y in lifts], log=log, walls=swl, gap_max=LIFT_GAP,
                                   spurs=spots, completing=True)
        finally:
            walknet.STEP_CAP = cap
        layered["u"] = u2
        lg = layered["graph"]
        log(f"  Undercity: floors over floors: {len(layered['masks'])} layers, roads {len(lg.nodes)} nodes, "
            f"{len(lg.edges)} edges, {lg.total_length():.0f} yd")
        for x, y, z, why in layered["unjoined"]:
            log(f"  Undercity: a place not joined to its floor's roads: ({x:.0f}, {y:.0f}) z {z:.0f}: {why}")

    # the Ruins of Lordaeron up top (the lifts' tops too): a grid and roads of their own
    # (the ruins' steps up into the throne room and the like are steep: counted as floors)
    rfloors, rwalls, _ = _floors(cd, p.wmo, names, RUINS_SLOPE)
    hall = ruins(cd, p, names, rfloors, rwalls, world, log, lifts)

    # the named areas up at the surface inside the city's model (the halls at the lifts' tops):
    # the game reports the city's map there too, but the player is up on the continent
    upper = sorted({name for gi, name, z, tri in floors if name and name != "Sewers" and z > -20})  # (the sewers are the city's)
    log(f"  Undercity: up top: {', '.join(upper)}")

    map_id = next((r["ID"] for r in cd.table("UiMap") if (r.get("Name_lang") or "") == "Undercity"), 0)
    return {"id": UNDERCITY_ID, "base": 0, "name": "Undercity", "map": map_id, "tx0": tx0, "ty0": ty0, "zoff": p.z, "layered": layered,
            "cells": cells, "graph": g, "lifts": lifts, "is_open": is_open, "upper": upper, "debug": debug, "hall": hall, "top": top, "wmo": p.wmo,
            "stair_z": stair_z, "floor_at": floor_at, "height_at": height_at}


def _ground(cd: ClientData, x0: float, x1: float, y0: float, y1: float, cell: float):
    """The continent's ground in a box, on a grid of `cell` yards (rows south from x1,
    columns east from y1): (height, open) arrays. Open: not too steep, not under liquid."""
    from .extract import adt
    from .roads.terrain import MCNK_HEADER, chunk_steep_quads, tile_grid
    m = next(r for r in cd.table("Map") if r["ID"] == 0)
    wdt = adt.parse_wdt(cd.casc.read(m["WdtFileDataID"]))
    Hn, Wn = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    height = np.full((Hn, Wn), np.nan)
    ok = np.zeros((Hn, Wn), bool)
    T, C = adt.TILE_YD, adt.CHUNK_YD
    Q = C / 8
    tiles = {(int(32 - y / T), int(32 - x / T)) for x in (x0, x1) for y in (y0, y1)}
    for tx, ty in tiles:
        t = wdt.tiles.get((tx, ty))
        if not t or not t.root:
            continue
        root = cd.casc.read(t.root)
        steep, water = tile_grid(root)  # 128x128 quads [row south, col east]
        topX, topY = (32 - ty) * T, (32 - tx) * T
        for magic, a, b in adt.iter_chunks(root):
            if magic != "MCNK":
                continue
            ix, iy = struct.unpack_from("<II", root, a + 4)
            base = struct.unpack_from("<f", root, a + 0x68 + 8)[0]
            mcvt = None
            for m2, a2, b2 in adt.iter_chunks(root, a + MCNK_HEADER, b):
                if m2 == "MCVT":
                    mcvt = np.frombuffer(root[a2:a2 + 145 * 4], np.float32)
                    break
            if mcvt is None:
                continue
            outer = np.array([[mcvt[i * 17 + j] for j in range(9)] for i in range(9)]) + base
            cx0, cy0 = topX - iy * C, topY - ix * C  # the chunk's north-west corner
            if cx0 - C > x1 or cx0 < x0 or cy0 - C > y1 or cy0 < y0:
                continue
            r0, r1 = max(0, int((x1 - cx0) / cell)), min(Hn - 1, int((x1 - (cx0 - C)) / cell) + 1)
            c0, c1 = max(0, int((y1 - cy0) / cell)), min(Wn - 1, int((y1 - (cy0 - C)) / cell) + 1)
            for r in range(r0, r1 + 1):
                x = x1 - (r + 0.5) * cell
                fi = (cx0 - x) / Q
                if not 0 <= fi < 8:
                    continue
                for c in range(c0, c1 + 1):
                    y = y1 - (c + 0.5) * cell
                    fj = (cy0 - y) / Q
                    if not 0 <= fj < 8:
                        continue
                    i, j = int(fi), int(fj)
                    u, v = fi - i, fj - j
                    h = (outer[i, j] * (1 - u) * (1 - v) + outer[i + 1, j] * u * (1 - v)
                         + outer[i, j + 1] * (1 - u) * v + outer[i + 1, j + 1] * u * v)
                    height[r, c] = h
                    qr, qc = iy * 8 + i, ix * 8 + j
                    ok[r, c] = not steep[qr, qc] and not water[qr, qc]
    return height, ok


def ruins(cd: ClientData, p, names, floors, walls, world, log=print, lifts=()) -> dict:
    """The Ruins of Lordaeron, up top: the ground inside its walls and the city model's floors
    there (its steps, halls and the lifts' tops), walls closing them, the pools of slime
    closed; what's reachable on foot from the ground. A grid over the continent's (cells
    outside the ruins say so), and its roads."""
    from skimage.morphology import skeletonize
    from scipy import ndimage
    from .roads.graph import skeleton_to_graph
    # (the model's floors up here, less a few strays: the walled compound)
    ruin = [[world(v) for v in tri] for gi, name, z, tri in floors if name != "Sewers" and -25 < z < 60]
    xs = np.array([q[0] for t in ruin for q in t])
    ys = np.array([q[1] for t in ruin for q in t])
    # (room round it for the blocked ground at its foot: see `banks`)
    x0, x1 = np.percentile(xs, 0.5) - 40, np.percentile(xs, 99.5) + 40
    y0, y1 = np.percentile(ys, 0.5) - 40, np.percentile(ys, 99.5) + 40
    cell = CELL
    H, W = int((x1 - x0) / cell) + 1, int((y1 - y0) / cell) + 1
    ground, gok = _ground(cd, x0, x1, y0, y1, cell)
    zlo = np.nanmin(ground) - 5
    Z0r, NBr = float(np.floor(zlo)), 90
    bands = np.zeros((NBr, H, W), bool)

    def cellrc(x, y):
        return (x1 - x) / cell, (y1 - y) / cell

    gb = np.where(np.isfinite(ground), np.clip((ground - Z0r).astype(int), 0, NBr - 1), -1)
    for r, c in np.argwhere(gok & (gb >= 0)):
        bands[gb[r, c], r, c] = True
    # the model's floors up here (not the sewers), their heights across each triangle
    nf = 0
    for gi, name, z, tri in floors:
        if name == "Sewers" or not -25 < z < 60:
            continue
        wz = [v[2] + p.z for v in tri]
        pts = [cellrc(*world(v)) for v in tri]  # (row, col)
        (r1_, c1_), (r2_, c2_), (r3_, c3_) = pts
        rr0, rr1 = max(int(min(r1_, r2_, r3_)), 0), min(int(max(r1_, r2_, r3_)) + 1, H - 1)
        cc0, cc1 = max(int(min(c1_, c2_, c3_)), 0), min(int(max(c1_, c2_, c3_)) + 1, W - 1)
        if rr1 < rr0 or cc1 < cc0:
            continue
        det = (r2_ - r3_) * (c1_ - c3_) + (c3_ - c2_) * (r1_ - r3_)
        if abs(det) < 1e-9:
            continue
        RR, CC = np.meshgrid(np.arange(rr0, rr1 + 1) + 0.5, np.arange(cc0, cc1 + 1) + 0.5, indexing="ij")
        l1 = ((r2_ - r3_) * (CC - c3_) + (c3_ - c2_) * (RR - r3_)) / det
        l2 = ((r3_ - r1_) * (CC - c3_) + (c1_ - c3_) * (RR - r3_)) / det
        l3 = 1 - l1 - l2
        inside = (l1 >= -0.05) & (l2 >= -0.05) & (l3 >= -0.05)
        zz = l1 * wz[0] + l2 * wz[1] + l3 * wz[2]
        ir, ic = np.nonzero(inside)
        bi = np.clip((zz[ir, ic] - Z0r).astype(int), 0, NBr - 1)
        bands[bi, ir + rr0, ic + cc0] = True
        nf += 1
    # seams with no floor (a doorway's threshold) between floors of one height: filled
    filled = 0
    for _ in range(2):
        anyb0 = bands.any(axis=0)
        low = np.where(anyb0, np.argmax(bands, axis=0), -1)
        for vr, vc in np.argwhere(~anyb0):
            nb = [low[r2, c2] for r2 in range(max(vr - 1, 0), min(vr + 2, H)) for c2 in range(max(vc - 1, 0), min(vc + 2, W))
                  if low[r2, c2] >= 0]
            if len(nb) >= 3 and max(nb) - min(nb) < LEDGE:
                bands[int(round(sum(nb) / len(nb))), vr, vc] = True
                filled += 1
    # walls standing on a floor there, to head height
    wall3 = np.zeros_like(bands)
    for gi, name, (wzl, wzh), tri in walls:
        wzl, wzh = wzl + p.z, wzh + p.z
        if name == "Sewers" or wzh - wzl < 2:
            continue
        b0, b1 = max(0, int(wzl - 1.5 - Z0r)), min(NBr - 1, int(min(wzl + 1.5, wzh - HEAD) - Z0r))
        if b1 < b0:
            continue
        pts = [cellrc(*world(v)) for v in tri]
        r0_, c0_ = max(int(min(q[0] for q in pts)) - 1, 0), max(int(min(q[1] for q in pts)) - 1, 0)
        r1_, c1_ = min(int(max(q[0] for q in pts)) + 2, H), min(int(max(q[1] for q in pts)) + 2, W)
        if r1_ <= r0_ or c1_ <= c0_:
            continue
        m = Image.new("L", (c1_ - c0_, r1_ - r0_), 0)
        md = ImageDraw.Draw(m)
        loc = [(q[1] - c0_, q[0] - r0_) for q in pts]
        md.polygon(loc, fill=255)
        md.line(loc + [loc[0]], fill=255, width=1)
        wall3[b0:b1 + 1, r0_:r1_, c0_:c1_] |= (np.array(m) > 0)[None] & bands[b0:b1 + 1, r0_:r1_, c0_:c1_]
    # reachable on foot from the ground outside (the box's edge): steps of a ledge's height
    free = bands & ~wall3
    reach = np.zeros_like(bands)
    todo = []
    for r in range(H):
        for c in (0, W - 1):
            if gb[r, c] >= 0 and free[gb[r, c], r, c]:
                reach[gb[r, c], r, c] = True
                todo.append((gb[r, c], r, c))
    for c in range(W):
        for r in (0, H - 1):
            if gb[r, c] >= 0 and free[gb[r, c], r, c] and not reach[gb[r, c], r, c]:
                reach[gb[r, c], r, c] = True
                todo.append((gb[r, c], r, c))
    R_ = int(math.ceil(LEDGE * math.sqrt(2)))
    while todo:
        b, r, c = todo.pop()
        for dr_, dc in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
            r2, c2 = r + dr_, c + dc
            if not (0 <= r2 < H and 0 <= c2 < W):
                continue
            lim = LEDGE * math.hypot(dr_, dc)
            for b2 in range(max(0, b - R_), min(NBr, b + R_ + 1)):
                if abs(b2 - b) <= lim and free[b2, r2, c2] and not reach[b2, r2, c2]:
                    reach[b2, r2, c2] = True
                    todo.append((b2, r2, c2))
    anyr = reach.any(axis=0)
    # (the lowest floor reached in each cell: up here the way is on the ground, under arches
    # and bridges, not on top of them)
    topb = np.where(anyr, np.argmax(reach, axis=0), -1)
    top = np.where(anyr, Z0r + topb + 0.5, -1e4)
    walk = anyr.copy()
    for dr_, dc in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
        rs, rd = (slice(max(dr_, 0), H + min(dr_, 0)), slice(max(-dr_, 0), H + min(-dr_, 0)))
        cs, cd_ = (slice(max(dc, 0), W + min(dc, 0)), slice(max(-dc, 0), W + min(-dc, 0)))
        nb = np.full((H, W), np.nan)
        nb[rd, cd_] = np.where(anyr[rs, cs], top[rs, cs], np.nan)
        with np.errstate(invalid="ignore"):
            walk &= ~(nb >= top + LEDGE * math.hypot(dr_, dc))  # (a ledge's foot)
    # the ways walked in game (RUINS_WAYS): open along them (doorways' thresholds and frames)
    ways = np.zeros((H, W), bool)
    for way in RUINS_WAYS:
        for (ax, ay), (bx, by) in zip(way, way[1:]):
            n = max(1, int(math.hypot(bx - ax, by - ay) / (cell / 2)))
            for k in range(n + 1):
                wr, wc = int((x1 - (ax + (bx - ax) * k / n)) / cell), int((y1 - (ay + (by - ay) * k / n)) / cell)
                for r2 in range(max(wr - 1, 0), min(wr + 2, H)):
                    for c2 in range(max(wc - 1, 0), min(wc + 2, W)):
                        walk[r2, c2] = ways[r2, c2] = True
    # the lifts' tops: their floor open (the cars and their doors)
    for lx, ly in lifts:
        lr, lc = int((x1 - lx) / cell), int((y1 - ly) / cell)
        for r2 in range(max(lr - 3, 0), min(lr + 4, H)):
            for c2 in range(max(lc - 3, 0), min(lc + 4, W)):
                if (r2 - lr) ** 2 + (c2 - lc) ** 2 <= 9:
                    walk[r2, c2] = True
    # the ruins' own cells: inside the model's footprint (else the continent's grid)
    mine = np.zeros((H, W), bool)
    fp = Image.new("L", (W, H), 0)
    fdr = ImageDraw.Draw(fp)
    for gi, name, z, tri in floors:
        if name != "Sewers" and -25 < z < 60:
            fdr.polygon([(cellrc(*world(v))[1], cellrc(*world(v))[0]) for v in tri], fill=255)
    mine = ndimage.binary_closing(np.array(fp) > 0, iterations=6)
    mine = ndimage.binary_fill_holes(mine)
    # its outer walls, standing on the ground just outside the floors: its cells too, closed
    # (on the continent's grid a leg from a road end beside one is let through: its end slack),
    # but for the ways walked in game (the gate)
    outer = wall3.any(axis=0) & ~walk & ~mine & ndimage.binary_dilation(mine, iterations=10)
    mine |= outer
    # and the continent's blocked ground round it (the mound's steep banks): the Ruins' closed
    # cells, so no leg out of a road end beside them is let through on the end slack. (Outside its
    # floors the continent's slopes decide, not the steps up to a ledge's height allowed on them.)
    from .roads.terrain import continent_grid
    cg = continent_grid(cd, 0, log=lambda *a: None)
    ck = TILE / cg["cellYd"]
    RR, CC = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    X, Y = x1 - (RR + 0.5) * cell, y1 - (CC + 0.5) * cell
    gr = np.clip((((32 - X / TILE) - cg["tileY0"]) * ck).astype(int), 0, cg["cells"].shape[0] - 1)
    gc = np.clip((((32 - Y / TILE) - cg["tileX0"]) * ck).astype(int), 0, cg["cells"].shape[1] - 1)
    banks = (cg["cells"][gr, gc] == 2) & ~ways & ~mine & ndimage.binary_dilation(mine, iterations=12)
    mine |= banks
    walk &= ~banks
    log(f"  Ruins: {int(outer.sum())} cells of outer wall, {int(banks.sum())} of blocked ground round it")
    cells = np.where(~mine, 1, np.where(walk, 0, 2)).astype(np.uint8)
    log(f"  Ruins: {filled} floorless seams filled")
    log(f"  Ruins: {nf} floor faces, grid {W}x{H} of {cell} yd, {mine.mean() * 100:.0f}% the ruins', "
        f"{(walk & mine).sum() / max(mine.sum(), 1) * 100:.0f}% of that walkable")

    # roads: the walkable area's centerlines, inside the ruins
    tx0, ty0 = 32 - y1 / TILE, 32 - x1 / TILE
    k = TILE / cell

    def px_to_world(r, col):
        return x1 - (r + 0.5) * cell, y1 - (col + 0.5) * cell

    area = walk & mine
    g = skeleton_to_graph(skeletonize(area), px_to_world, keep_pixels=True)
    g.prune_spurs(20.0)
    g.contract_degree2()
    # (bits of road on their own, too small to be a way anywhere: left out)
    parent = {n: n for n in g.nodes}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for e in g.edges.values():
        parent[find(e.a)] = find(e.b)
    total = {}
    for e in g.edges.values():
        total[find(e.a)] = total.get(find(e.a), 0) + e.length
    for eid, e in list(g.edges.items()):
        if total.get(find(e.a), 0) < 40:
            g.remove_edge(eid)
    g.contract_degree2()
    g.drop_isolated_nodes()
    # the ways walked in game: the gate, the courtyard, through the throne room to the lifts'
    # hall, and from there to each lift (world yards); joined to the roads at their ends
    for way in RUINS_WAYS:
        ids = []
        for q in (way[0], way[-1]):
            near = min(g.nodes.items(), key=lambda kv: math.hypot(kv[1][0] - q[0], kv[1][1] - q[1]), default=None)
            if near and math.hypot(near[1][0] - q[0], near[1][1] - q[1]) < 4:
                ids.append(near[0])
            else:
                ids.append(g.add_node(q))
        g.add_edge(ids[0], ids[1], list(way), source="way")
        for nid in ids:  # (tied to the nearest generated road too)
            others = [(math.hypot(q[0] - g.nodes[nid][0], q[1] - g.nodes[nid][1]), m) for m, q in g.nodes.items() if m not in ids]
            if others:
                d, m = min(others)
                if 0 < d < 25:
                    g.add_edge(nid, m, [g.nodes[nid], g.nodes[m]], source="way")
    log(f"  Ruins: roads {len(g.nodes)} nodes, {len(g.edges)} edges, {g.total_length():.0f} yd")

    def is_open(x, y):
        r, c = int((x1 - x) / cell), int((y1 - y) / cell)
        return 0 <= r < H and 0 <= c < W and bool(area[r, c])

    def height_at(x, y):
        r, c = int((x1 - x) / cell), int((y1 - y) / cell)
        return float(top[r, c]) if 0 <= r < H and 0 <= c < W and anyr[r, c] else None

    return {"tx0": tx0, "ty0": ty0, "cells": cells, "graph": g, "is_open": is_open, "height_at": height_at,
            "debug": {"top": top, "walk": walk, "mine": mine, "x1": x1, "y1": y1, "bands": bands, "wall3": wall3,
                      "reach": reach, "Z0": Z0r, "ground": ground, "gok": gok}}


# (the road helpers, shared with the caves: walknet.py)
_clear, _simplify, _unzig, _simplify_3d = walknet.clear, walknet.simplify, walknet.unzig, walknet.simplify_3d


def cities_lua(cd: ClientData, log=print) -> str:
    u = undercity(cd, log)
    lay = u.get("layered")
    g, cells = (lay["graph"] if lay else u["graph"]), u["cells"]
    # roads drawn down there in game (`agps roads` / `agps watch-roads` import them)
    from .paths import RESOURCES
    from .roads.graph import LayerFloors, apply_overrides

    # (a drawn edit with a height (the game's) changes its floor's roads only, as in the addon; its
    # new nodes get that floor's height, the others the top floor's in _layered_roads)
    def floors(props):
        if not lay or props.get("z") is None:
            return None
        return LayerFloors(g, lay["node_z"], float(props["z"]) - u["zoff"])

    ov = apply_overrides(g, RESOURCES / "overrides" / f"roads_{u['id']}.geojson", city=True, floors=floors)
    if ov["added"] or ov["removed"]:
        log(f"  Undercity: drawn roads {ov}")
    out = [f"-- GENERATED by `agps gen-addon-data` from client {cd.casc.version}. Do not edit by hand.",
           "-- City levels (app/azerothgps/cities.py): underground cities as their own routing level,",
           "-- a pseudo-continent drawn in its base continent's coordinates, reached by its lifts.",
           "local _, ns = ...",
           "ns.CityLevels = ns.CityLevels or {}",
           "-- (upper: the areas up at the surface inside the city, where the game reports its map too)",
           "-- (zoff: its heights here are the model's own; the game's (world) are these plus zoff)",
           f"ns.CityLevels[{u['id']}] = {{ base = {u['base']}, name = \"{u['name']}\", map = {u['map']}, wmo = {u['wmo']}, zoff = {u['zoff']:.2f}, "
           f"upper = {{ {', '.join('[' + chr(34) + n + chr(34) + '] = true' for n in u['upper'])} }} }}",
           "-- roads (the format of Data/Roads.lua)",
           f"ns.Roads[{u['id']}] = {{"]
    if lay:
        out += _layered_roads(u, lay)
    else:
        out += _flat_roads(u, g)
    out.append("}")
    out += _heights_and_rest(u, cells, drops=[] if lay else u["_drops"])
    return "\n".join(out) + "\n"


def _layered_roads(u: dict, lay: dict) -> list[str]:
    """Roads on every floor: nodes, each one's height (the game's: the model's plus zoff), roads
    simplified on their own floor (layers.roads), then laid on the floors: a yard at a time, each
    point's height the floor's there nearest the last point's (a ramp's, a stair's), and a node
    where that bends from an even change in height between the road's nodes (the addon takes a
    road's height to change evenly between them) by more than Z_BEND."""
    from . import layers
    g, nz = lay["graph"], lay["node_z"]
    for n, (x, y) in g.nodes.items():
        if n not in nz:  # (a drawn road's new node: the top floor's height there, or the nearest node's)
            h = u["height_at"](x, y)
            if h is None:
                near = min((m for m in g.nodes if m in nz), key=lambda m: math.hypot(g.nodes[m][0] - x, g.nodes[m][1] - y))
                h = nz[near]
            nz[n] = h
    u2, f = lay["u"], lay["floors"]
    NB, H, W = f.shape
    Z0 = u2["Z0"]

    def floor_near(x, y, z, reach=LAYER_REACH):
        """The height of the floor at (x, y) nearest z (within `reach`), or None."""
        cx, cy = u2["cellxy"](x, y)
        r, c = int(cy), int(cx)
        best = None
        for rr in range(max(0, r - 1), min(H, r + 2)):
            for cc in range(max(0, c - 1), min(W, c + 2)):
                for b in np.nonzero(f[:, rr, cc])[0]:
                    fz = Z0 + b + 0.5
                    d = abs(fz - z) + (0 if (rr, cc) == (r, c) else 0.5)
                    if d <= reach and (best is None or d < best[0]):
                        best = (d, fz)
        return best[1] if best else None

    nodes, edges, _drops, zs = layers.roads(lay, u2, SMOOTH)
    nodes = list(nodes)
    # (each node on its floor: its layer's height there, else the floor nearest the one it was given)
    node_ids = sorted(g.nodes)
    for i, n in enumerate(node_ids):
        L = lay["node_layer"].get(n)
        h = None
        if L in lay["masks"]:
            r0, c0, _m = lay["masks"][L]
            top = lay["tops"][L]
            rr, cc = layers._px(u2, nodes[i])
            rr, cc = rr - r0, cc - c0
            if 0 <= rr < top.shape[0] and 0 <= cc < top.shape[1] and not np.isnan(top[rr, cc]):
                h = float(top[rr, cc])
        zs[i] = h if h is not None else (floor_near(nodes[i][0], nodes[i][1], zs[i]) or zs[i])
    runs = []
    for (a, b, pts), (eid, e) in zip(edges, g.edges.items()):
        ez = lay["edge_z"].get(eid)
        if e.source == "stair" and ez and len(ez) == len(e.pts):
            # (a stair: its whole way, cell by cell, with its own heights: simplified in 2D, a
            # stair down a ledge's steps became a step straight down)
            dense = [tuple(nodes[a])] + [tuple(q) for q in e.pts[1:-1]] + [tuple(nodes[b])]
            kept = [True] * len(dense)
            hs = [zs[a]] + list(ez[1:-1]) + [zs[b]]
        else:
            # (a road on one floor: a point every yard along it, its own points kept, each at its
            # floor's height there, else the floor nearest the last point's)
            pts = [tuple(nodes[a])] + [tuple(q) for q in pts[1:-1]] + [tuple(nodes[b])]
            dense, kept = [], []
            for i in range(len(pts) - 1):
                (x1, y1), (x2, y2) = pts[i], pts[i + 1]
                n = max(1, int(math.hypot(x2 - x1, y2 - y1)))
                for s_ in range(n):
                    dense.append((x1 + (x2 - x1) * s_ / n, y1 + (y2 - y1) * s_ / n))
                    kept.append(s_ == 0)
            dense.append(pts[-1])
            kept.append(True)
            on = layers.point_heights(lay, u2, eid, dense)
            hs = [zs[a]]
            for q, h in zip(dense[1:-1], on[1:-1]):
                # (its floor's height, when that's a step on from the last point's: a point on a
                # cell's edge can read the cell past a ledge; else the floor nearest the last one)
                if h is None or abs(h - hs[-1]) > LEDGE + 1.0:
                    h = floor_near(q[0], q[1], hs[-1], LEDGE + 1.0) or hs[-1]
                hs.append(h)
            hs.append(zs[b])
        cum = [0.0]
        for p_, q in zip(dense, dense[1:]):
            cum.append(cum[-1] + math.hypot(q[0] - p_[0], q[1] - p_[1]))
        ids = {0: a, len(dense) - 1: b}
        # (a jump between neighboring points, steeper than a stair: not walked, a wall's or a canal's
        # rim up from the floor beside it read as the same floor; the road is cut there)
        jumps = set()
        for m in range(len(dense) - 1):
            if abs(hs[m + 1] - hs[m]) > ROAD_JUMP + ROAD_JUMP_PER_YD * (cum[m + 1] - cum[m]):
                jumps.add(m)
                for k in (m, m + 1):
                    if k not in ids:
                        nodes.append(dense[k])
                        zs.append(hs[k])
                        ids[k] = len(nodes) - 1

        def split(i, j):
            if j - i < 2:
                return
            worst, at = Z_BEND, None
            span = max(cum[j] - cum[i], 1e-6)
            for m in range(i + 1, j):
                dev = abs(hs[m] - (hs[i] + (hs[j] - hs[i]) * (cum[m] - cum[i]) / span))
                if dev > worst:
                    worst, at = dev, m
            if at is not None:
                nodes.append(dense[at])
                zs.append(hs[at])
                ids[at] = len(nodes) - 1
                split(i, at)
                split(at, j)
        ends = sorted(ids)
        for i, j in zip(ends, ends[1:]):
            if not (j == i + 1 and i in jumps):
                split(i, j)
        cuts = sorted(ids)
        for i, j in zip(cuts, cuts[1:]):
            if j == i + 1 and i in jumps:
                continue
            way = [dense[i]] + [dense[m] for m in range(i + 1, j) if kept[m]] + [dense[j]]
            runs.append((ids[i], ids[j], way))
    out = ["  n = {" + ",".join(f"{x:.1f},{y:.1f}" for x, y in nodes) + "},",
           "  z = {" + ",".join(f"{z + u['zoff']:.1f}" for z in zs) + "},",
           "  e = {"]
    for a, b, pts in runs:
        length = sum(math.hypot(q[0] - p_[0], q[1] - p_[1]) for p_, q in zip(pts, pts[1:]))
        out.append(f"    {{{a + 1},{b + 1},{length:.1f},0,{','.join(f'{x:.1f},{y:.1f}' for x, y in pts)}}},")
    out.append("  },")
    return out


def _flat_roads(u: dict, g) -> list[str]:
    """The top floor's roads (each cell's top floor: before floors over floors), and its drops."""
    out = []
    order = {nid: i + 1 for i, nid in enumerate(sorted(g.nodes))}
    flat = ",".join(f"{g.nodes[nid][0]:.1f},{g.nodes[nid][1]:.1f}" for nid in sorted(g.nodes))
    out.append(f"  n = {{{flat}}},")
    out.append("  e = {")
    drops = []
    for i, (eid, e) in enumerate(g.edges.items(), start=1):
        if e.source.startswith("drop:"):  # (one way, a to b, straight: its own list below)
            drops.append(f"[{i}] = {e.source[5:]}")
            pts = ",".join(f"{x:.1f},{y:.1f}" for x, y in e.pts)
            out.append(f"    {{{order[e.a]},{order[e.b]},{e.length:.1f},3,{pts}}},")
            continue
        ends = [g.nodes[e.a]] + [tuple(p) for p in e.pts[1:-1]] + [g.nodes[e.b]]  # (a junction may have moved)
        if e.source == "override":  # (drawn in game: as drawn)
            pts = ",".join(f"{x:.1f},{y:.1f}" for x, y in ends)
        elif e.source == "stair" and eid in u["stair_z"]:
            # (a stair runs through cells the 2D grid closes: simplified in 3D, on its floors)
            pts = ",".join(f"{x:.1f},{y:.1f}" for x, y in _simplify_3d(ends, u["stair_z"][eid], SMOOTH, u["floor_at"]))
        else:
            sm = _simplify(np.array(ends), SMOOTH, u["is_open"], u["height_at"])
            pts = ",".join(f"{x:.1f},{y:.1f}" for x, y in _unzig(sm, u["is_open"], u["height_at"]))
        out.append(f"    {{{order[e.a]},{order[e.b]},{e.length:.1f},0,{pts}}},")
    out.append("  },")
    u["_drops"] = drops
    return out


def _heights_and_rest(u: dict, cells, drops: list) -> list[str]:
    out = []
    # each cell's floor height, for "12 yd below": a character per cell, HEIGHT_STEP yards a
    # step up from HEIGHT_Z0 ("0" first); "." no floor. Rows as the grid's.
    out.append(f"-- floor heights (the model's own, relative): (byte - 48) * {HEIGHT_STEP:.0f} + {HEIGHT_Z0:.0f}; \".\" none")
    out.append("ns.CityHeights = ns.CityHeights or {}")
    out.append(f"ns.CityHeights[{u['id']}] = {{ z0 = {HEIGHT_Z0:.0f}, step = {HEIGHT_STEP:.0f}, rows = {{")
    for r in u["top"]:
        row = "".join("." if z < -1e3 else chr(48 + max(0, min(43, int(round((z - HEIGHT_Z0) / HEIGHT_STEP))))) for z in r)
        out.append(f'  "{row}",')
    out.append("} }")
    out.append("-- drops off ledges: road (edge index) = yards fallen; one way, a to b")
    out.append("ns.RoadDrops = ns.RoadDrops or {}")
    out.append(f"ns.RoadDrops[{u['id']}] = {{ {', '.join(drops)} }}")
    out.append("-- walkable floors (the format of Data/Terrain.lua)")
    out.append(f"ns.Terrain[{u['id']}] = {{ tx0 = {u['tx0']:.6f}, ty0 = {u['ty0']:.6f}, cell = {CELL:.6f}, "
               f"w = {cells.shape[1]}, h = {cells.shape[0]}, slack = {SLACK:.0f}, rows = {{")
    for r in cells:
        out.append(f'  "{encode_row(r)}",')
    out.append("} }")
    h = u["hall"]
    out.append("-- the Ruins of Lordaeron up top (the continent's level): its own grid over the continent's")
    out.append("-- (0 open, 2 closed, 1 not the ruins': the continent's grid there), and its roads")
    out.append(f"ns.Terrain[\"{HALL_KEY}\"] = {{ tx0 = {h['tx0']:.6f}, ty0 = {h['ty0']:.6f}, cell = {CELL:.6f}, "
               f"w = {h['cells'].shape[1]}, h = {h['cells'].shape[0]}, slack = 0, overlay = true, rows = {{")
    for r in h["cells"]:
        out.append(f'  "{encode_row(r)}",')
    out.append("} }")
    out.append("ns.CityHalls = ns.CityHalls or {}")
    out.append(f"ns.CityHalls[{u['base']}] = {{ \"{HALL_KEY}\" }}")
    hg = h["graph"]
    horder = {nid: i + 1 for i, nid in enumerate(sorted(hg.nodes))}
    out.append("ns.RoadOverlays = ns.RoadOverlays or {}")
    out.append(f"ns.RoadOverlays[{u['base']}] = {{ {{")
    out.append("  n = {" + ",".join(f"{hg.nodes[n][0]:.1f},{hg.nodes[n][1]:.1f}" for n in sorted(hg.nodes)) + "},")
    out.append("  e = {")
    for e in hg.edges.values():
        pts_ = [hg.nodes[e.a]] + [tuple(q) for q in e.pts[1:-1]] + [hg.nodes[e.b]]
        if e.source == "way":
            pts = ",".join(f"{x:.1f},{y:.1f}" for x, y in pts_)
            out.append(f"    {{{horder[e.a]},{horder[e.b]},{e.length:.1f},0,{pts}}},")
            continue
        sm = _simplify(np.array(pts_), SMOOTH, h["is_open"], h["height_at"])
        pts = ",".join(f"{x:.1f},{y:.1f}" for x, y in _unzig(sm, h["is_open"], h["height_at"]))
        out.append(f"    {{{horder[e.a]},{horder[e.b]},{e.length:.1f},0,{pts}}},")
    out.append("  },")
    out.append("} }")
    out.append("-- lifts to the Ruins of Lordaeron (as transports: city end, surface end; z1: the city end's")
    out.append("-- height, the game's: the roads there are on floors over floors)")
    for x, y in u["lifts"]:
        out.append(f"ns.Transports[#ns.Transports + 1] = {{ {u['id']}, {x:.1f}, {y:.1f}, {u['base']}, {x:.1f}, {y:.1f}, "
                   f"{LIFT_SECONDS}, \"lift\", \"Undercity\", \"Ruins of Lordaeron\", \"lift\", z1 = {LIFT_Z + u['zoff']:.1f} }}")
    return out

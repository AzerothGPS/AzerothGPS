"""Walk networks of WMO models (a city, a cave): walkable floors, walls by height, a
passability grid, stairs and drops found in 3D, and a road skeleton, in world yards.

The input is the model's faces already placed in the world (x, y) with heights in one frame
(Undercity uses its model's local z, caves the world z):
- floors: triangles pointing up (see cities._floors), with their vertices' heights;
- walls: steep faces, (zlo, zhi) and their triangle;
- liquids: surfaces (a polygon and its height) that floors under them are no way to walk.
Optionally the continent's ground (`ground`): where a cave's mouth opens onto the terrain,
the walkable ground outside it is taken in too, so the roads run out of the mouth.

The grid is each cell's top floor (heights interpolated per triangle, small floors over a
lower one left out): walls standing on a floor close it, and so does a ledge's foot. Cells
of CELL yards, rows south and columns east from terrain tile (tx0, ty0) (Data/Terrain.lua's
format).
"""

from __future__ import annotations

import heapq
import math
import struct

import numpy as np
from PIL import Image, ImageDraw

TILE = 1600 / 3
CELL = 2.0  # yards per grid cell
LEDGE = 3.0  # yards: a drop this big between neighboring cells is a ledge
HEAD = 3.0  # yards: a face rising this far above a floor is a wall
BODY = 2.0  # yards: the space a character standing on a floor takes up (a cave's rock through it closes the floor)
BUMP = 1.0  # yards: rock rising less than this is a step, not a wall
REACH = 0.5  # yards: rock this near a cell's middle (at a body's height) closes it
ISLAND = 80  # cells: a floor smaller than this over a lower one is overhead
DROP_MAX = 40.0  # yards: the highest drop off a ledge offered (the addon checks the player's health)
DROP_APART = 20.0  # yards: drops between the same two levels at least this far apart
DROP_REACH = 15.0  # yards: a drop's top and bottom this near their levels' roads
STAIR_REACH = 30.0  # yards: a stair's ends this near their levels' roads (in a straight line on the floor)
STAIR_MAX = 80.0  # yards: the longest way a stair between levels is looked for
STAIR_APART = 30.0  # yards: stairs between the same two levels at least this far apart
NEIGH8 = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


class Placed:
    """A model placement's transform: local (x, y, z) -> world (X, Y, Z). The yaw turns about
    the up axis (t = rot.y + 180 degrees, see interiors.py); a tilted placement turns about its
    y axis by rot.x, then its x axis by rot.z (checked against every tilted MODF's extents)."""

    def __init__(self, p):
        t, a, b = math.radians(p.yaw + 180), math.radians(getattr(p, "rx", 0.0)), math.radians(getattr(p, "rz", 0.0))
        rz = np.array([[math.cos(t), -math.sin(t), 0], [math.sin(t), math.cos(t), 0], [0, 0, 1]])
        ry = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
        rx = np.array([[1, 0, 0], [0, math.cos(b), -math.sin(b)], [0, math.sin(b), math.cos(b)]])
        self.m = rz @ ry @ rx
        self.o = np.array([p.x, p.y, p.z])

    def __call__(self, v):
        w = self.m @ np.asarray(v, float) + self.o
        return float(w[0]), float(w[1]), float(w[2])


def _raster_tri(pts, W, H):
    """A triangle's cells: (r0, c0, sub-grid rows/cols of cell centers, barycentrics, inside)."""
    (x1, y1), (x2, y2), (x3, y3) = pts
    c0, c1 = max(int(min(x1, x2, x3)), 0), min(int(max(x1, x2, x3)) + 1, W - 1)
    r0, r1 = max(int(min(y1, y2, y3)), 0), min(int(max(y1, y2, y3)) + 1, H - 1)
    det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(det) < 1e-9 or c1 < c0 or r1 < r0:
        return None
    cc, rr = np.meshgrid(np.arange(c0, c1 + 1) + 0.5, np.arange(r0, r1 + 1) + 0.5)
    l1 = ((y2 - y3) * (cc - x3) + (x3 - x2) * (rr - y3)) / det
    l2 = ((y3 - y1) * (cc - x3) + (x1 - x3) * (rr - y3)) / det
    l3 = 1 - l1 - l2
    inside = (l1 >= -0.05) & (l2 >= -0.05) & (l3 >= -0.05)
    return r0, c0, (l1, l2, l3), inside


def build(floors, walls, liquids, *, label: str, z0: float | None = None, nb: int | None = None,
          ground=None, ground_reach: float = 24.0, prune: float = 12.0, fill: int = 0, log=print) -> dict:
    """The walk network of a model's faces.

    floors: [(xy triangle [(x, y)] * 3, vertex heights (3), outline_only)] -- outline_only:
      walkable in 2D but not a height level (Undercity's sewers, which climb over the streets);
    walls: [((zlo, zhi), xy triangle)]; liquids: [(xy polygon, surface height)];
    z0, nb: the height bands (a yard each) from z0 (default: the floors' range);
    ground(xs, ys) -> (height, walkable) arrays: the continent's ground (for a cave's mouth).
    """
    from scipy import ndimage
    from skimage.morphology import closing, disk, remove_small_holes, remove_small_objects, skeletonize

    from .roads.graph import skeleton_to_graph

    keep = [f[0] for f in floors]
    keep_vz = [f[1] for f in floors]
    keep_flat = [f[2] for f in floors]
    # (a floor's 4th item: whether it's where the model opens onto the ground, a cave's mouth;
    # when none says so, all may be)
    keep_mouth = [f[3] if len(f) > 3 else True for f in floors]
    if not any(keep_mouth):
        keep_mouth = [True] * len(floors)
    xs = [q[0] for tri in keep for q in tri]
    ys = [q[1] for tri in keep for q in tri]
    pad = 10 + (ground_reach if ground is not None else 0)
    minX, maxX, minY, maxY = min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad
    # grid: col east (Y falling), row south (X falling), from tile (tx0, ty0)
    tx0, ty0 = 32 - maxY / TILE, 32 - maxX / TILE
    k = TILE / CELL
    W, H = int((maxY - minY) / CELL) + 2, int((maxX - minX) / CELL) + 2
    if z0 is None:
        allz = [z for vz in keep_vz for z in vz]
        z0 = float(math.floor(min(allz))) - 4
        nb = int(math.ceil(max(allz) - z0)) + 6
    Z0, NB = z0, nb

    def cellxy(x, y):
        return ((32 - y / TILE) - tx0) * k, ((32 - x / TILE) - ty0) * k

    def px_to_world(r, col):  # cell centre (row, col) -> world
        return (32 - ty0 - (r + 0.5) / k) * TILE, (32 - tx0 - (col + 0.5) / k) * TILE

    img = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(img)
    for tri in keep:
        dr.polygon([cellxy(*q) for q in tri], fill=255)
    walk = np.array(img) > 0
    walk = closing(walk, disk(1))  # (seams between floor pieces; before the walls go in)
    # ledges: where a cell's floor is LEDGE or more above a neighbor's, the upper cell (the
    # lip) closes: no stepping off a raised walk. Stairs rise less than that per cell. (The
    # top floor per cell; outline-only floors stay out of it.)
    # (heights across each floor triangle: a stair's ramp is often one or two long ones)
    top = np.full((H, W), -1e4)
    bands = np.zeros((NB, H, W), bool)
    mouth_bands = np.zeros((NB, H, W), bool) if ground is not None else None
    for tri, vz, flat, mouth in zip(keep, keep_vz, keep_flat, keep_mouth):
        if flat:
            continue
        pts = [cellxy(*q) for q in tri]
        ras = _raster_tri(pts, W, H)
        if ras is None:
            continue
        r0, c0, (l1, l2, l3), inside = ras
        z = l1 * vz[0] + l2 * vz[1] + l3 * vz[2]
        sub = top[r0:r0 + z.shape[0], c0:c0 + z.shape[1]]
        np.maximum(sub, np.where(inside, z, -1e4), out=sub)
        rr_i, cc_i = np.nonzero(inside)
        bi = np.clip((z[rr_i, cc_i] - Z0).astype(int), 0, NB - 1)
        bands[bi, rr_i + r0, cc_i + c0] = True
        if mouth and mouth_bands is not None:
            mouth_bands[bi, rr_i + r0, cc_i + c0] = True
        # (a triangle too small to hold a cell's middle: its middle's cell)
        if not inside.any():
            mc, mr = int(sum(q[0] for q in pts) / 3), int(sum(q[1] for q in pts) / 3)
            if 0 <= mr < H and 0 <= mc < W:
                top[mr, mc] = max(top[mr, mc], sum(vz) / 3)
    # Small floors over a lower one are overhead, not a level: a buttress's or an arch's
    # top, a stall's roof. (Surfaces: floors joined within a ledge's drop; kept when big, or
    # with nothing under them.)
    zjoin = bands.copy()
    zjoin[1:] |= bands[:-1]
    zjoin[:-1] |= bands[1:]
    surf, nsurf = ndimage.label(zjoin, structure=np.ones((3, 3, 3)))
    bi, ri, ci = np.nonzero(bands)
    sid = surf[bi, ri, ci]
    below = np.zeros_like(bands)
    below[int(HEAD) + 1:] = np.cumsum(bands, axis=0)[:-int(HEAD) - 1] > 0  # a floor under, with headroom
    ncell = np.bincount(np.unique(sid.astype(np.int64) * (H * W) + ri * W + ci) // (H * W), minlength=nsurf + 1)
    nover = np.bincount(sid, weights=below[bi, ri, ci], minlength=nsurf + 1)
    nall = np.bincount(sid, minlength=nsurf + 1)
    overhead = (ncell < ISLAND) & (nover > 0.5 * np.maximum(nall, 1))
    drop = overhead[sid]
    bands[bi[drop], ri[drop], ci[drop]] = False
    log(f"  {label}: {int(overhead[1:].sum())} small floors overhead left out")
    # floors under a liquid's surface (slime pools and channels) are no way to walk
    liq_z = np.full((H, W), -1e4)
    for poly, lz in liquids:
        corners = [cellxy(*q) for q in poly]
        cc0, cc1 = max(int(min(q[0] for q in corners)), 0), min(int(max(q[0] for q in corners)) + 1, W)
        rr0, rr1 = max(int(min(q[1] for q in corners)), 0), min(int(max(q[1] for q in corners)) + 1, H)
        if cc1 > cc0 and rr1 > rr0:
            li = Image.new("L", (cc1 - cc0, rr1 - rr0), 0)
            ImageDraw.Draw(li).polygon([(q[0] - cc0, q[1] - rr0) for q in corners], fill=255)
            cov = np.array(li) > 0
            sub = liq_z[rr0:rr1, cc0:cc1]
            sub[cov] = np.maximum(sub[cov], lz)
    under_liq = 0
    for b in range(NB):
        drown = bands[b] & (Z0 + b + 0.5 < liq_z - 0.5)
        under_liq += int(drown.sum())
        bands[b] &= ~drown
    liquid = liq_z > -1e3
    log(f"  {label}: {int(liquid.sum())} cells under liquid, {under_liq} floor bands under it left out")
    anyb = bands.any(axis=0)
    topb = np.where(anyb, NB - 1 - np.argmax(bands[::-1], axis=0), -1)
    has = anyb
    top = np.where(has, Z0 + topb + 0.5, -1e4)
    # walkable cells with no floor height (seams the outline fills between floor pieces):
    # their neighbors' height when those agree (a seam on one level), else closed (a gap
    # between levels: a road there would step up or down a ledge). Outline-only floors keep theirs.
    flat_img = Image.new("L", (W, H), 0)
    sdr = ImageDraw.Draw(flat_img)
    for tri, flat in zip(keep, keep_flat):
        if flat:
            sdr.polygon([cellxy(*q) for q in tri], fill=255)
    flat_mask = np.array(flat_img) > 0
    gaps = 0
    for vr, vc in np.argwhere(walk & ~has & ~flat_mask):
        nb_ = [top[r2, c2] for r2 in range(max(vr - 1, 0), min(vr + 2, H)) for c2 in range(max(vc - 1, 0), min(vc + 2, W))
               if has[r2, c2]]
        if nb_ and max(nb_) - min(nb_) < LEDGE:
            top[vr, vc] = sum(nb_) / len(nb_)
            topb[vr, vc] = int(np.clip(top[vr, vc] - Z0, 0, NB - 1))
            bands[topb[vr, vc], vr, vc] = True
            has[vr, vc] = True
        else:
            walk[vr, vc] = False
            gaps += 1
    log(f"  {label}: {gaps} cells closed between levels (no floor)")
    walk &= ~(liquid & ~has)
    model = walk.copy()  # (the model's own floors, before any ground)
    # the ground outside a cave's mouth: walkable terrain next to the model's floors at about
    # their height (those where it opens onto the ground, when the model says), and on from there over walkable ground (steps under a ledge's height) up
    # to `ground_reach` yards. Not under the model (a cave's rock over its tunnels).
    ground_cells = np.zeros((H, W), bool)
    if ground is not None:
        rows, cols = np.mgrid[0:H, 0:W]
        gx = (32 - ty0 - (rows + 0.5) / k) * TILE
        gy = (32 - tx0 - (cols + 0.5) / k) * TILE
        gh, gok = ground(gx, gy)
        cand = gok & np.isfinite(gh) & ~(model | has) & ~liquid
        gb = np.where(cand, np.clip((gh - Z0).astype(int), 0, NB - 1), -1)
        cand &= (gh > Z0) & (gh < Z0 + NB - 1)
        dist = np.full((H, W), np.inf)
        todo = []
        mb = bands & mouth_bands
        for r, c in np.argwhere(cand):
            for dr_, dc in NEIGH8:
                r2, c2 = r + dr_, c + dc
                if 0 <= r2 < H and 0 <= c2 < W and model[r2, c2] and mb[
                        max(0, gb[r, c] - int(LEDGE)):gb[r, c] + int(LEDGE) + 1, r2, c2].any():
                    dist[r, c] = 0.0
                    todo.append((0.0, int(r), int(c)))
                    break
        heapq.heapify(todo)
        while todo:
            d, r, c = heapq.heappop(todo)
            if d > dist[r, c]:
                continue
            for dr_, dc in NEIGH8:
                r2, c2 = r + dr_, c + dc
                if not (0 <= r2 < H and 0 <= c2 < W) or not cand[r2, c2]:
                    continue
                step = CELL * math.hypot(dr_, dc)
                if abs(gh[r2, c2] - gh[r, c]) >= LEDGE * math.hypot(dr_, dc) or d + step > ground_reach:
                    continue
                if d + step < dist[r2, c2]:
                    dist[r2, c2] = d + step
                    heapq.heappush(todo, (d + step, r2, c2))
        ground_cells = np.isfinite(dist)
        for r, c in np.argwhere(ground_cells):
            bands[gb[r, c], r, c] = True
            top[r, c] = Z0 + gb[r, c] + 0.5
            topb[r, c] = gb[r, c]
        has |= ground_cells
        walk |= ground_cells
        log(f"  {label}: {int(ground_cells.sum())} cells of ground at the mouth")
    # walls, per height: a steep face standing on a floor there and rising to head height
    # closes that floor where it stands (a building's wall, a raised walk's side seen from
    # below). Doorways, steps, curbs and counters stay open; arches overhead don't stand on
    # a floor.
    wall3 = np.zeros((NB, H, W), bool)
    nwall = 0
    for wall_ in walls:
        (zlo, zhi), tri = wall_[0], wall_[1]
        if len(wall_) > 2:
            # (a wall with its vertices' heights, a cave's rough rock: it closes a floor where
            # its surface passes through the space a character standing there takes up, from
            # its foot to a body's height; rock leaning out overhead doesn't)
            if zhi - zlo < BUMP:
                continue
            (x1, y1), (x2, y2), (x3, y3) = [cellxy(*q) for q in tri]
            za, zb_, zc = wall_[2]
            # (points on its surface every quarter yard or so; a cell closes where one passes
            # within a character's reach of its middle: a narrow tunnel keeps its middle open)
            n = int(max(math.hypot(x2 - x1, y2 - y1), math.hypot(x3 - x1, y3 - y1), math.hypot(x3 - x2, y3 - y2),
                        abs(zb_ - za) / CELL, abs(zc - za) / CELL, abs(zc - zb_) / CELL) * CELL * 4) + 1
            i_, j_ = np.mgrid[0:n + 1, 0:n + 1]
            sel = i_ + j_ <= n
            l1, l2 = i_[sel] / n, j_[sel] / n
            l3 = 1 - l1 - l2
            fc, fr = l1 * x1 + l2 * x2 + l3 * x3, l1 * y1 + l2 * y2 + l3 * y3
            sc, sr = np.floor(fc).astype(int), np.floor(fr).astype(int)
            sz = l1 * za + l2 * zb_ + l3 * zc
            inb = (sr >= 0) & (sr < H) & (sc >= 0) & (sc < W) & (
                np.hypot(fc - sc - 0.5, fr - sr - 0.5) * CELL <= REACH)
            hit_any = False
            for off in range(-1, int(BODY) + 1):  # floors from a body's height below the surface to just above it
                bb = np.floor(sz - off - Z0).astype(int)
                ok_ = inb & (bb >= 0) & (bb < NB)
                ok_[ok_] &= bands[bb[ok_], sr[ok_], sc[ok_]]
                if ok_.any():
                    wall3[bb[ok_], sr[ok_], sc[ok_]] = True
                    hit_any = True
            nwall += hit_any
            continue
        if zhi - zlo < 2:
            continue
        b0, b1 = max(0, int(zlo - 1.5 - Z0)), min(NB - 1, int(min(zlo + 1.5, zhi - HEAD) - Z0))
        if b1 < b0:
            continue
        pts = [cellxy(*q) for q in tri]
        c0, r0 = max(int(min(q[0] for q in pts)) - 1, 0), max(int(min(q[1] for q in pts)) - 1, 0)
        c1, r1 = min(int(max(q[0] for q in pts)) + 2, W), min(int(max(q[1] for q in pts)) + 2, H)
        if c1 <= c0 or r1 <= r0:
            continue
        m = Image.new("L", (c1 - c0, r1 - r0), 0)
        md = ImageDraw.Draw(m)
        loc = [(x - c0, y - r0) for x, y in pts]
        md.polygon(loc, fill=255)
        md.line(loc + [loc[0]], fill=255, width=1)
        hit = (np.array(m) > 0)[None] & bands[b0:b1 + 1, r0:r1, c0:c1]
        if hit.any():
            wall3[b0:b1 + 1, r0:r1, c0:c1] |= hit
            nwall += 1
    log(f"  {label}: {nwall} wall faces")
    if ground is not None and ground_cells.any():
        # a cave: only the floors reached on foot from the ground at its mouth (steps of up to
        # a ledge's height, not through walls), and in each cell the lowest of them: the way
        # is on the cave's floor, under its arches and the rock over its mouth, not on them
        free = bands & ~wall3
        R_ = int(math.ceil(LEDGE * math.sqrt(2)))
        reached = np.zeros_like(bands)
        todo = []
        for r, c in np.argwhere(ground_cells):
            b = int(topb[r, c])
            if free[b, r, c]:
                reached[b, r, c] = True
                todo.append((b, int(r), int(c)))
        while todo:
            b, r, c = todo.pop()
            for dr_, dc in NEIGH8:
                r2, c2 = r + dr_, c + dc
                if not (0 <= r2 < H and 0 <= c2 < W):
                    continue
                lim = LEDGE * math.hypot(dr_, dc)
                for b2 in range(max(0, b - R_), min(NB, b + R_ + 1)):
                    if abs(b2 - b) <= lim and free[b2, r2, c2] and not reached[b2, r2, c2]:
                        reached[b2, r2, c2] = True
                        todo.append((b2, r2, c2))
        anyr = reached.any(axis=0)
        log(f"  {label}: {int((has & ~anyr).sum())} cells of floor not reached from the mouth")
        bands = reached
        topb = np.where(anyr, np.argmax(reached, axis=0), -1)
        top = np.where(anyr, Z0 + topb + 0.5, -1e4)
        has = anyr
        walk &= anyr
    # the grid (2D) is each cell's top floor: closed where a wall stands on it, and at the foot
    # of a ledge, where a neighbor's top is a ledge's height above (stairs rise less than that
    # per cell). (The foot, not the lip: a narrow bridge or walk is all lip, and would go.)
    wall = has & np.take_along_axis(wall3, np.clip(topb, 0, NB - 1)[None], 0)[0]
    lip = np.zeros((H, W), bool)
    for dr_, dc in NEIGH8:
        rs, rd = (slice(max(dr_, 0), H + min(dr_, 0)), slice(max(-dr_, 0), H + min(-dr_, 0)))
        cs, cd_ = (slice(max(dc, 0), W + min(dc, 0)), slice(max(-dc, 0), W + min(-dc, 0)))
        nb_ = np.full((H, W), np.nan)
        nb_[rd, cd_] = np.where(has[rs, cs], top[rs, cs], np.nan)
        with np.errstate(invalid="ignore"):
            lip |= has & (nb_ >= top + LEDGE * math.hypot(dr_, dc))
    log(f"  {label}: {int(lip.sum())} ledge cells")
    walk &= ~(wall | lip)
    debug = {"top": top, "lip": lip, "bands": bands, "Z0": Z0, "floor": walk.copy()}  # (for checks)
    walk = remove_small_objects(walk, max_size=30)
    cells = np.where(walk, 0, 2).astype(np.uint8)
    log(f"  {label}: {len(keep)} floor faces, grid {W}x{H} cells of {CELL} yd, {walk.mean() * 100:.0f}% walkable")

    # roads: the walkable area's centerlines (the walls keep them off the walls)
    # (`fill`: closed spots of up to this many cells inside the floor, a boulder or a pillar,
    # are no reason for the road to fork round them)
    skel = skeletonize(remove_small_holes(walk, max_size=fill) if fill else walk)
    labels, ncomp = ndimage.label(walk)
    sizes = np.bincount(labels.ravel())[1:]
    log(f"  {label}: walkable in {ncomp} pieces, the biggest {sizes.max() if ncomp else 0} cells "
        f"({(sizes.max() / sizes.sum() * 100) if ncomp else 0:.0f}%)")
    g = skeleton_to_graph(skel, px_to_world, keep_pixels=True)
    g.prune_spurs(prune)
    g.contract_degree2()
    g.drop_isolated_nodes()

    def world_to_px(x, y):
        c, r = cellxy(x, y)
        return int(r), int(c)

    def is_open(x, y):
        r, c = world_to_px(x, y)
        return 0 <= r < H and 0 <= c < W and bool(walk[r, c])

    def height_at(x, y):
        r, c = world_to_px(x, y)
        return float(top[r, c]) if 0 <= r < H and 0 <= c < W and has[r, c] else None

    def floor_at(x, y, z):
        """A floor about at height z there, with no wall standing on it."""
        r, c = world_to_px(x, y)
        if not (0 <= r < H and 0 <= c < W):
            return False
        b = int(z - Z0)
        for bb in range(max(b - 2, 0), min(b + 3, NB)):
            if bands[bb, r, c] and not wall3[bb, r, c]:
                return True
        return False

    # a junction sits at its skeleton cluster's middle, which can be off the floor: move it
    # onto the nearest point of its edges that is on the floor
    inc = g.incident()
    moved = 0
    for nid, (x, y) in list(g.nodes.items()):
        if is_open(x, y):
            continue
        ends = []  # the first point on the floor along each of its edges
        for eid in inc.get(nid, []):
            e = g.edges[eid]
            pts = e.pts if e.a == nid else e.pts[::-1]
            q = next((tuple(q) for q in pts if is_open(*q)), None)
            if q is not None:
                ends.append(q)
        if ends:
            g.nodes[nid] = min(ends, key=lambda q: math.hypot(q[0] - x, q[1] - y))
            moved += 1
    log(f"  {label}: {moved} junctions moved onto the floor")

    # stairs: the grid keeps each level apart (a stair running on under a raised walk can't
    # be told from the walk above it in 2D), so they're found in 3D: cells by height, steps
    # of up to a ledge's drop per cell, walls by height. The shortest ways between pieces of
    # the grid become roads of their own, joining the pieces' roads.
    piece, _ = ndimage.label(walk, structure=np.ones((3, 3)))
    R = int(math.ceil(LEDGE * math.sqrt(2)))
    best: dict = {}  # (band, row, col) -> (yards, piece, parent)
    heap = []
    for pr, pc_ in np.argwhere(walk):
        node = (int(topb[pr, pc_]), int(pr), int(pc_))
        best[node] = (0.0, int(piece[pr, pc_]), None)
    for node in best:
        heap.append((0.0, node))
    meets = []
    while heap:
        d, node = heapq.heappop(heap)
        bd, pc, _ = best[node]
        if d > bd:
            continue
        b0, r0, c0 = node
        for dr_, dc in NEIGH8:
            r1, c1 = r0 + dr_, c0 + dc
            if not (0 <= r1 < H and 0 <= c1 < W):
                continue
            reach = LEDGE * math.hypot(dr_, dc)
            for b1 in range(max(0, b0 - R), min(NB, b0 + R + 1)):
                if not bands[b1, r1, c1] or wall3[b1, r1, c1] or abs(b1 - b0) > reach:
                    continue
                step = CELL * math.hypot(dr_, dc) + abs(b1 - b0) * 0.5
                other = best.get((b1, r1, c1))
                if other is not None and other[1] != pc:
                    meets.append((d + step + other[0], pc, other[1], node, (b1, r1, c1)))
                    continue
                nd = d + step
                if nd <= STAIR_MAX and (other is None or nd < other[0]):
                    best[(b1, r1, c1)] = (nd, pc, node)
                    heapq.heappush(heap, (nd, (b1, r1, c1)))

    def chain(node):
        out = []
        while node is not None:
            out.append(node)
            node = best[node][2]
        return out

    node_piece = {}
    for nid, (x, y) in g.nodes.items():
        pr, pc_ = world_to_px(x, y)
        if 0 <= pr < H and 0 <= pc_ < W and piece[pr, pc_]:
            node_piece[nid] = int(piece[pr, pc_])

    def reach_node(x, y, pc, most):
        """Where a stair or drop joins the roads of piece `pc`: the nearest point along one of
        its roads reached in a straight line over open floor (within `most` yards), made a
        node (the road split there), so the way doesn't run on past it and back:
        (yards, node), or (inf, None)."""
        cands = []
        for eid, e in g.edges.items():
            if e.source != "terrain" or node_piece.get(e.a) != pc:
                continue
            d = np.hypot(e.pts[:, 0] - x, e.pts[:, 1] - y)
            for i in np.argsort(d)[:3]:
                if d[i] <= most:
                    cands.append((float(d[i]), eid, int(i)))
        cands.sort()
        for dd, eid, i in cands:
            e = g.edges.get(eid)
            if e is None or not clear((x, y), tuple(e.pts[i]), is_open):
                continue
            if i == 0:
                return dd, e.a
            if i == len(e.pts) - 1:
                return dd, e.b
            nid = g.add_node(tuple(e.pts[i]))
            node_piece[nid] = pc
            g.remove_edge(eid)
            g.add_edge(e.a, nid, e.pts[: i + 1], e.source)
            g.add_edge(nid, e.b, e.pts[i:], e.source)
            return dd, nid
        return math.inf, None

    meets.sort()
    taken: list = []
    stair_z: dict = {}  # a stair's heights along it (its points'), for simplifying it in 3D
    nstairs = 0
    for cost, pa, pb, na, nb_ in meets:
        if cost > STAIR_MAX:
            break
        key = (min(pa, pb), max(pa, pb))
        mx, my = px_to_world(na[1], na[2])
        if any(k2 == key and math.hypot(mx - x2, my - y2) < STAIR_APART for k2, x2, y2 in taken):
            continue
        cells_ = chain(na)[::-1] + chain(nb_)
        path = [px_to_world(pr, pc_) for _, pr, pc_ in cells_]
        ends = [reach_node(x, y, pc, STAIR_REACH)[1] for (x, y), pc in ((path[0], pa), (path[-1], pb))]
        if None in ends or ends[0] == ends[1]:
            continue
        taken.append((key, mx, my))
        eid = g.add_edge(ends[0], ends[1], [path[0]] + path + [path[-1]], source="stair")
        zs = [Z0 + b + 0.5 for b, _, _ in cells_]
        stair_z[eid] = [zs[0]] + zs + [zs[-1]]
        nstairs += 1
    log(f"  {label}: {nstairs} stairs between levels")

    # drops: off a ledge's top onto the floor below it (one way; the addon takes them when
    # the fall is one the player survives): the lip, the ledge's foot, then open floor
    cand = []
    for dr_, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
        for ur, uc in np.argwhere(walk):
            fr, fc, lr, lc = ur + dr_, uc + dc, ur + 2 * dr_, uc + 2 * dc
            if not (0 <= lr < H and 0 <= lc < W) or not walk[lr, lc] or not has[fr, fc]:
                continue
            h = top[ur, uc] - top[lr, lc]
            if LEDGE * 2 <= h <= DROP_MAX and top[fr, fc] <= top[lr, lc] + 1 and piece[ur, uc] != piece[lr, lc]:
                cand.append((float(h), int(piece[ur, uc]), int(piece[lr, lc]), (int(ur), int(uc)), (int(lr), int(lc))))
    cand.sort()
    kept: list = []
    ndrops = 0
    for h, pa, pb, up, lo in cand:
        ux, uy = px_to_world(*up)
        lx, ly = px_to_world(*lo)
        if any(k_[0] == (pa, pb) and math.hypot(ux - k_[1], uy - k_[2]) < DROP_APART for k_ in kept):
            continue
        ends = [reach_node(x, y, pc, DROP_REACH) for (x, y), pc in (((ux, uy), pa), ((lx, ly), pb))]
        if ends[0][0] > DROP_REACH or ends[1][0] > DROP_REACH or ends[0][1] == ends[1][1]:
            continue
        kept.append(((pa, pb), ux, uy))
        na, nb_ = ends[0][1], ends[1][1]
        g.add_edge(na, nb_, [g.nodes[na], (ux, uy), (lx, ly), g.nodes[nb_]], source=f"drop:{h:.0f}")
        ndrops += 1
    log(f"  {label}: {ndrops} drops off ledges")
    debug.update({"piece": piece, "meets": meets, "taken": taken, "wall3": wall3})
    log(f"  {label}: roads {len(g.nodes)} nodes, {len(g.edges)} edges, {g.total_length():.0f} yd")
    return {"tx0": tx0, "ty0": ty0, "W": W, "H": H, "cells": cells, "walk": walk, "has": has, "top": top, "topb": topb,
            "bands": bands, "wall3": wall3, "Z0": Z0, "NB": NB, "model": model, "ground": ground_cells,
            "graph": g, "stair_z": stair_z, "is_open": is_open, "height_at": height_at, "floor_at": floor_at,
            "cellxy": cellxy, "px_to_world": px_to_world, "world_to_px": world_to_px, "piece": piece, "debug": debug}


def clear(a, b, is_open, corner: int = 0, height=None) -> bool:
    """Whether the straight line a-b stays on open cells (checked every half yard), clipping
    at most `corner` samples all along (a cell's corner), and only on one floor (`height`:
    not a ledge's foot between two levels)."""
    n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.5))
    if corner and height:
        ha, hb = height(*a), height(*b)
        if ha is None or hb is None or abs(ha - hb) >= LEDGE:
            corner = 0
    run = 0  # (the samples clipped, all along)
    for i in range(n + 1):
        x, y = a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n
        if not is_open(x, y):
            run += 1
            h = height(x, y) if (corner and height) else None
            if run > corner or i == 0 or i == n or (height and (h is None or abs(h - ha) >= LEDGE)):
                return False
    return True


def simplify(pts, eps: float, is_open=None, height=None) -> list:
    """Douglas-Peucker: the points of a polyline within `eps` yards of it (and, with
    `is_open`, only shortcuts that stay on open cells)."""
    pts = [tuple(p) for p in pts]
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    L = math.hypot(dx, dy) or 1e-9
    far, fi = -1.0, 0
    for i in range(1, len(pts) - 1):
        d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / L
        if d > far:
            far, fi = d, i
    if far <= eps and (is_open is None or clear(pts[0], pts[-1], is_open, 1, height)):
        return [pts[0], pts[-1]]
    if far <= eps:
        fi = len(pts) // 2
    return simplify(pts[: fi + 1], eps, is_open, height)[:-1] + simplify(pts[fi:], eps, is_open, height)


def unzig(pts: list, is_open, height=None, turn: float = 50.0, short: float = 8.0) -> list:
    """Sharp little turns taken out: a point where the road turns more than `turn` degrees
    next to a leg shorter than `short` yards goes, when the straight line past it stays on
    the floor (a corner clipped at most), until none are left."""
    pts = [tuple(q) for q in pts]
    cos_t = math.cos(math.radians(turn))
    changed = True
    while changed and len(pts) > 2:
        changed = False
        for i in range(1, len(pts) - 1):
            a, b, c = pts[i - 1], pts[i], pts[i + 1]
            v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
            l1, l2 = math.hypot(*v1), math.hypot(*v2)
            if l1 < 1e-6 or l2 < 1e-6:
                del pts[i]
                changed = True
                break
            sharp = (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2) < cos_t
            if sharp and min(l1, l2) < short and clear(a, c, is_open, 1, height):
                del pts[i]
                changed = True
                break
    # the sharp corners left (against a wall): rounded, a little way along each leg
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[i], pts[i + 1]
        v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 > 1e-6 and l2 > 1e-6 and (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2) < cos_t:
            f1, f2 = min(0.5, 2.0 / l1), min(0.5, 2.0 / l2)
            p1 = (b[0] - v1[0] * f1, b[1] - v1[1] * f1)
            p2 = (b[0] + v2[0] * f2, b[1] + v2[1] * f2)
            if clear(p1, p2, is_open, 1, height):
                out += [p1, p2]
                continue
        out.append(b)
    out.append(pts[-1])
    return out


def simplify_3d(pts: list, zs: list, eps: float, floor_at) -> list:
    """Douglas-Peucker over points with heights: a shortcut only where the floor runs at the
    heights between its ends all along it (checked every half yard)."""
    def ok(i, j):
        (x1, y1), (x2, y2), z1, z2 = pts[i], pts[j], zs[i], zs[j]
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / 0.5))
        return all(floor_at(x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n, z1 + (z2 - z1) * k / n) for k in range(n + 1))

    def rec(i, j):
        if j - i < 2:
            return [pts[i], pts[j]]
        (x1, y1), (x2, y2) = pts[i], pts[j]
        L = math.hypot(x2 - x1, y2 - y1) or 1e-9
        far, fi = -1.0, i + 1
        for k in range(i + 1, j):
            d = abs((y2 - y1) * (pts[k][0] - x1) - (x2 - x1) * (pts[k][1] - y1)) / L
            if d > far:
                far, fi = d, k
        if far <= eps and ok(i, j):
            return [pts[i], pts[j]]
        if far <= eps:
            fi = (i + j) // 2
        return rec(i, fi)[:-1] + rec(fi, j)

    return rec(0, len(pts) - 1)


def model_faces(cd, wmo: int, slope: float, groups=None):
    """A model's faces in its own frame: floors (group, centroid z, triangle) and walls
    (group, (zmin, zmax), triangle), by the face's slope; and its liquids (group, local
    (x0, y0, x1, y1), surface z). `groups`: only these."""
    from . import interiors as I
    from .extract import adt

    w = I.read_wmo(cd, wmo)
    floors, walls, liquids = [], [], []
    for gi in range(min(w.n_groups, len(w.group_files))):
        if groups is not None and gi not in groups:
            continue
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
            # faces a character collides with (MOPY flags): collision-only ones (0x08) and
            # rendered ones that aren't detail (0x20 without 0x04); the rest is decoration a
            # character walks through (a cave's rubble, hanging rock). A group with no flags
            # at all (Undercity's) has every face.
            pa, pb = sub.get("MOPY", (0, 0))
            mopy = data[pa:pb:2]
            solid = None
            if any(mopy):
                solid = [bool(f & 0x08) or (bool(f & 0x20) and not f & 0x04) for f in mopy]
            for kk in range(len(idx) // 3):
                if solid is not None and kk < len(solid) and not solid[kk]:
                    continue
                i1, i2, i3 = idx[3 * kk], idx[3 * kk + 1], idx[3 * kk + 2]
                a1, a2, a3 = verts[i1], verts[i2], verts[i3]
                ux, uy, uz = a2[0] - a1[0], a2[1] - a1[1], a2[2] - a1[2]
                vx, vy, vz = a3[0] - a1[0], a3[1] - a1[1], a3[2] - a1[2]
                nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
                L = math.sqrt(nx * nx + ny * ny + nz * nz)
                if L == 0:
                    continue
                if abs(nz) / L < slope:
                    zs3 = (a1[2], a2[2], a3[2])
                    walls.append((gi, (min(zs3), max(zs3)), (a1, a2, a3)))
                    continue
                if norms and norms[i1][2] + norms[i2][2] + norms[i3][2] <= 0:
                    continue
                floors.append((gi, (a1[2] + a2[2] + a3[2]) / 3, (a1, a2, a3)))
            if "MLIQ" in sub:
                la, lb = sub["MLIQ"]
                xv, yv, xt, yt = struct.unpack_from("<4i", data, la)
                cx, cy, _cz = struct.unpack_from("<3f", data, la + 16)
                if 0 < xv * yv <= 100000 and xt > 0 and yt > 0:
                    T = 4.1666625
                    vbase = la + 30
                    hs = [struct.unpack_from("<f", data, vbase + i * 8 + 4)[0] for i in range(xv * yv)]
                    tbase = vbase + xv * yv * 8
                    for j in range(yt):
                        for i in range(xt):
                            if tbase + j * xt + i >= lb or data[tbase + j * xt + i] & 0x0F == 0x0F:
                                continue
                            h = (hs[j * xv + i] + hs[j * xv + i + 1] + hs[(j + 1) * xv + i] + hs[(j + 1) * xv + i + 1]) / 4
                            x0, y0 = cx + i * T, cy + j * T
                            liquids.append((gi, (x0, y0, x0 + T, y0 + T), h))
            break
    return floors, walls, liquids

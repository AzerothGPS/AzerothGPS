"""The offline prep for searching the terrain by blocks (`agps terrain-hpa`): Data/TerrainHPA.lua.

Each continent's passability grid (Data/Terrain.lua, with the capitals' and the ruins' grids laid
over it and the shipped walls, exactly as Passability.lua's cost rule sees them: its `BaseRow`)
is cut into blocks of K x K cells. Along every border between two blocks, each run of cells open on
both sides is a way through: one in its middle, or one at each end when it's RUN_SPLIT wide or more
(Passability.lua's BuildBlock does the same for blocks the player's own walls change). Within a
block, the walks between its ways through (8-connected, a diagonal step only past two open cells,
water SWIM_COST a cell) are worked out here, so the game searches the blocks' ways through first
and the cells only across the blocks the walk goes through.

Per block (only those with ways through): the count, each way's cell in the block (row * K +
col), then the walk between each pair (i < j) in quarter cells, 4095 for none; two characters of
Passability.lua's alphabet each. `stamp` is a hash of what it was made from (tests check it).
"""

from __future__ import annotations

import hashlib
import math
import time

import numpy as np

K = 32
RUN_SPLIT = 8  # Passability.lua's P.HPA_RUN_SPLIT
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
CONTS = (0, 1, 2991)
FILES = ("Data/Maps.lua", "Data/Roads.lua", "Data/Transports.lua", "Data/Terrain.lua", "Data/Cities.lua", "Data/Caves.lua",
         "Data/Capitals.lua", "Passability.lua")


def runtime():
    """The addon's own Lua with the data the cost rule reads (no player walls: ns.db empty)."""
    import lupa

    from .paths import ADDON_DIR

    lua = lupa.LuaRuntime()
    lua.execute('issecretvalue = nil\nGetTime = function() return 0 end')
    ns = lua.table()
    ns.IsSecret = lua.eval("function(v) return false end")
    ns.db = lua.eval("{}")
    loader = lua.eval("function(src, name) return assert(load(src, '@' .. name)) end")
    for name in FILES:
        loader((ADDON_DIR / name).read_text(encoding="utf-8"), name)("AzerothGPS", ns)
    ns.Passability.RefreshWalls()
    return lua, ns


def stamp(lua, ns, cont) -> str:
    """A hash of what the blocks come from: the grid, the grids laid over it, the shipped walls
    and wall erasers, and the rule's numbers."""
    h = hashlib.sha1()
    P = ns.Passability

    def grid(g):
        h.update(repr((g.w, g.h, g.cell, g.tx0, g.ty0, bool(g.overlay), bool(g.cave), bool(g.split),
                       g.short, g.long)).encode())
        rows = P.Rows(g)
        for i in range(1, len(rows) + 1):
            h.update(rows[i].encode())
            h.update(b"/")

    def points(lists):
        for i in range(1, len(lists) + 1 if lists else 1):
            w = lists[i]
            pts = w.pts if w.pts else w
            h.update(",".join(f"{pts[k]:.2f}" for k in range(1, len(pts) + 1)).encode())
            h.update(b"|" + (b"a" if w.area else b""))

    h.update(repr((K, RUN_SPLIT, P.SWIM_COST)).encode())
    grid(ns.Terrain[cont])
    halls = ns.CityHalls[cont] if ns.CityHalls else None
    for i in range(1, len(halls) + 1 if halls else 1):
        o = ns.Terrain[halls[i]]
        if o and o.overlay:
            h.update(str(halls[i]).encode())
            grid(o)
    points(ns.Walls[cont] if ns.Walls else None)
    points(ns.WallOpens[cont] if ns.WallOpens else None)
    return h.hexdigest()[:16]


def values(lua, ns, cont) -> np.ndarray:
    """The cost rule's value of every cell (h x w; row 0 is grid row 1): 0 open, 1 water, 2 closed."""
    g = ns.Terrain[cont]
    row = ns.Passability.BaseRow
    text = "".join(row(cont, r) for r in range(1, g.h + 1))
    return (np.frombuffer(text.encode(), dtype=np.uint8) - 48).reshape(g.h, g.w)


def _runs(ok: np.ndarray) -> list[int]:
    """The ways through along one border: per run of open pairs, its middle, or both its ends."""
    out, s = [], None
    for k in range(len(ok) + 1):
        o = k < len(ok) and bool(ok[k])
        if o and s is None:
            s = k
        if not o and s is not None:
            e = k - 1
            if e - s + 1 >= RUN_SPLIT:
                out += [s, e]
            else:
                out.append((s + e) // 2)
            s = None
    return out


def ways(V: np.ndarray) -> dict[int, list[int]]:
    """Each block's ways through (cells in the block, row * K + col), sorted."""
    h, w = V.shape
    nx, ny = w // K, h // K
    openc = V != 2
    nodes: dict[int, set] = {}
    for br in range(ny):
        for bc in range(nx):
            b, r0, c0 = br * nx + bc, br * K, bc * K
            if bc < nx - 1:  # the border with the block east of it (the next column)
                for k in _runs(openc[r0:r0 + K, c0 + K - 1] & openc[r0:r0 + K, c0 + K]):
                    nodes.setdefault(b, set()).add(k * K + K - 1)
                    nodes.setdefault(b + 1, set()).add(k * K)
            if br < ny - 1:  # ... and the one in the next row
                for k in _runs(openc[r0 + K - 1, c0:c0 + K] & openc[r0 + K, c0:c0 + K]):
                    nodes.setdefault(b, set()).add((K - 1) * K + k)
                    nodes.setdefault(b + nx, set()).add(k)
    return {b: sorted(s) for b, s in nodes.items()}


# the 8 steps inside a block: (dr, dc, length)
STEPS = [(dr, dc, math.sqrt(2) if dr and dc else 1.0) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if dr or dc]


def walks(V: np.ndarray, b: int, nodes: list[int], nx: int, swim: float) -> np.ndarray:
    """The walks (cells, water weighted) between a block's ways through: n x n, inf for none."""
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra

    br, bc = divmod(b, nx)
    sub = V[br * K:(br + 1) * K, bc * K:(bc + 1) * K]
    openc = sub != 2
    mult = np.where(sub == 1, swim, 1.0)
    rows, cols, wts = [], [], []
    idx = np.arange(K * K).reshape(K, K)
    for dr, dc, ln in STEPS:
        # from (r, c) to (r + dr, c + dc), both in the block
        rs = slice(max(0, -dr), K - max(0, dr))
        cs = slice(max(0, -dc), K - max(0, dc))
        rt = slice(max(0, dr), K + min(0, dr))
        ct = slice(max(0, dc), K + min(0, dc))
        ok = openc[rs, cs] & openc[rt, ct]
        if dr and dc:  # (a diagonal: both cells beside it open)
            ok &= openc[rt, cs] & openc[rs, ct]
        rows.append(idx[rs, cs][ok])
        cols.append(idx[rt, ct][ok])
        wts.append(mult[rt, ct][ok] * ln)
    g = csr_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(K * K, K * K))
    d = dijkstra(g, directed=True, indices=nodes)
    return d[:, nodes]


def two(v: int) -> str:
    return ALPHABET[v // 64] + ALPHABET[v % 64]


def build(lua, ns, cont, log=print) -> str:
    """Data/TerrainHPA.lua's entry for `cont`."""
    t = time.time()
    g = ns.Terrain[cont]
    assert g.w % K == 0 and g.h % K == 0, (cont, g.w, g.h)
    V = values(lua, ns, cont)
    log(f"  {cont}: values {V.shape} ({time.time() - t:.0f}s)")
    nx, ny = g.w // K, g.h // K
    swim = float(ns.Passability.SWIM_COST)
    out = []
    count = 0
    for b, nodes in sorted(ways(V).items()):
        d = walks(V, b, nodes, nx, swim)
        n = len(nodes)
        s = [two(n)] + [two(l) for l in nodes]
        for i in range(n):
            for j in range(i + 1, n):
                v = d[i, j]
                s.append(two(4095 if not np.isfinite(v) else min(4094, int(round(v * 4)))))
        out.append(f'[{b}]="{"".join(s)}",')
        count += n
    log(f"  {cont}: {len(out)} blocks, {count} ways through ({time.time() - t:.0f}s)")
    lines = [f"ns.TerrainHPA[{cont}] = {{ K = {K}, nx = {nx}, ny = {ny}, w = {g.w}, h = {g.h}, "
             f'stamp = "{stamp(lua, ns, cont)}", c = {{']
    for i in range(0, len(out), 8):
        lines.append(" ".join(out[i:i + 8]))
    lines.append("} }")
    return "\n".join(lines)


def write(log=print, rt=None) -> str:
    from .paths import ADDON_DIR

    lua, ns = rt or runtime()
    parts = ["-- GENERATED by `agps terrain-hpa` (app/azerothgps/hpa.py). Do not edit by hand.",
             "-- The terrain grids by blocks, for Passability.FindPath: see hpa.py.",
             "local _, ns = ...",
             "ns.TerrainHPA = ns.TerrainHPA or {}"]
    for cont in CONTS:
        if ns.Terrain[cont]:
            parts.append(build(lua, ns, cont, log))
    p = ADDON_DIR / "Data" / "TerrainHPA.lua"
    p.write_text("\n".join(parts) + "\n", encoding="utf-8", newline="\n")
    return str(p)


def refresh(log=print) -> bool:
    """Write Data/TerrainHPA.lua again when what it's made from changed (a stamp differs, e.g.
    walls drawn in game now shipped in Roads.lua). True when it was written."""
    import re

    from .paths import ADDON_DIR

    p = ADDON_DIR / "Data" / "TerrainHPA.lua"
    have = dict(re.findall(r'ns\.TerrainHPA\[(\d+)\] = \{[^\n]*?stamp = "([0-9a-f]+)"',
                           p.read_text(encoding="utf-8"))) if p.exists() else {}
    lua, ns = runtime()
    want = {str(c): stamp(lua, ns, c) for c in CONTS if ns.Terrain[c]}
    if want == have:
        return False
    log("the terrain, the grids over it or the shipped walls changed: preparing the blocks again")
    write(log, (lua, ns))
    return True

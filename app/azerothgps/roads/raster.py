"""Continent rasters from terrain: per-texture weights and liquid coverage.

Raster convention: row = south, col = east, PX_PER_CHUNK pixels per 33.3 yd chunk
(16 -> ~2.08 yd/px). The raster covers the bounding box of the continent's
terrain tiles, recorded in RasterGrid so pixels map back to world coordinates.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..extract import adt
from ..extract.spike import ClientData

PX_PER_CHUNK = 16
PX_PER_TILE = PX_PER_CHUNK * 16
YD_PER_PX = adt.CHUNK_YD / PX_PER_CHUNK


@dataclass(frozen=True)
class RasterGrid:
    """Maps raster pixels <-> world coordinates for one continent."""

    continent: int
    tile_x0: int
    tile_y0: int
    width: int  # px
    height: int  # px

    def px_to_world(self, row: float, col: float) -> tuple[float, float]:
        """Pixel centre (row, col) -> world (X north, Y west)."""
        tx = self.tile_x0 + (col + 0.5) / PX_PER_TILE
        ty = self.tile_y0 + (row + 0.5) / PX_PER_TILE
        return (32 - ty) * adt.TILE_YD, (32 - tx) * adt.TILE_YD

    def world_to_px(self, wx: float, wy: float) -> tuple[float, float]:
        tx, ty = adt.world_to_tile(wx, wy)
        return (ty - self.tile_y0) * PX_PER_TILE - 0.5, (tx - self.tile_x0) * PX_PER_TILE - 0.5

    def to_json(self) -> dict:
        return {"continent": self.continent, "tileX0": self.tile_x0, "tileY0": self.tile_y0,
                "width": self.width, "height": self.height, "ydPerPx": YD_PER_PX}


class ContinentTerrain:
    """Loads a continent's WDT and iterates its tiles' texture layers."""

    def __init__(self, cd: ClientData, continent: int) -> None:
        self.cd = cd
        self.continent = continent
        cont = next(r for r in cd.table("Map") if r["ID"] == continent)
        self.wdt = adt.parse_wdt(cd.casc.read(cont["WdtFileDataID"]))
        tiles = [k for k, t in self.wdt.tiles.items() if t.tex0]
        xs = [x for x, _ in tiles]
        ys = [y for _, y in tiles]
        self.grid = RasterGrid(continent, min(xs), min(ys),
                               (max(xs) - min(xs) + 1) * PX_PER_TILE, (max(ys) - min(ys) + 1) * PX_PER_TILE)
        self.tiles = sorted(tiles)

    def tile_origin(self, tx: int, ty: int) -> tuple[int, int]:
        return (ty - self.grid.tile_y0) * PX_PER_TILE, (tx - self.grid.tile_x0) * PX_PER_TILE

    def iter_layers(self, tiles=None):
        """Yield (tx, ty, texture_names, tex0) per tile; tiles that fail to read are skipped."""
        for tx, ty in tiles or self.tiles:
            try:
                tex = adt.parse_tex0(self.cd.casc.read(self.wdt.tiles[(tx, ty)].tex0), self.wdt.big_alpha)
            except Exception:
                continue
            names = [self.cd.name(f) for f in tex.textures]
            yield tx, ty, names, tex

    def texture_raster(self, predicate: Callable[[str], bool], tiles=None,
                       coverage: dict[str, float] | None = None) -> np.ndarray:
        """Summed weight (0..1, uint8-scaled) of every texture where predicate(name) holds.

        If `coverage` is given, it is filled with chunk-equivalents covered per texture.
        """
        return self.texture_rasters([predicate], tiles, coverage)[0]

    def texture_rasters(self, predicates: list[Callable[[str], bool]], tiles=None,
                        coverage: dict[str, float] | None = None) -> list[np.ndarray]:
        """texture_raster for several predicates in one pass over the terrain."""
        outs = [np.zeros((self.grid.height, self.grid.width), np.uint8) for _ in predicates]
        k = 64 // PX_PER_CHUNK
        for tx, ty, names, tex in self.iter_layers(tiles):
            r0, c0 = self.tile_origin(tx, ty)
            wants = [[pred(n) for n in names] for pred in predicates]
            for ci, layers in enumerate(tex.chunks):
                cy, cx = divmod(ci, 16)
                accs = [None] * len(predicates)
                for ti, w in adt.layer_weights(layers):
                    name = names[ti] if ti < len(names) else f"tex#{ti}"
                    if coverage is not None:
                        coverage[name] = coverage.get(name, 0.0) + float(w.mean())
                    for j, want in enumerate(wants):
                        if ti < len(want) and want[ti]:
                            accs[j] = w if accs[j] is None else accs[j] + w
                r, c = r0 + cy * PX_PER_CHUNK, c0 + cx * PX_PER_CHUNK
                for out, acc in zip(outs, accs):
                    if acc is not None:
                        small = acc.reshape(PX_PER_CHUNK, k, PX_PER_CHUNK, k).mean(axis=(1, 3))
                        out[r : r + PX_PER_CHUNK, c : c + PX_PER_CHUNK] = np.clip(small * 255, 0, 255).astype(np.uint8)
        return outs

    def liquid_mask(self, tiles=None) -> np.ndarray:
        """True where terrain has liquid (MH2O), at 8x8 cells per chunk upscaled to the raster."""
        out = np.zeros((self.grid.height, self.grid.width), bool)
        cell = PX_PER_CHUNK // 8
        for tx, ty in tiles or self.tiles:
            t = self.wdt.tiles[(tx, ty)]
            if not t.root:
                continue
            try:
                data = self.cd.casc.read(t.root)
            except Exception:
                continue
            for magic, a, b in adt.iter_chunks(data):
                if magic != "MH2O":
                    continue
                r0, c0 = self.tile_origin(tx, ty)
                for ci in range(256):
                    off_inst, n_layers, _off_attr = struct.unpack_from("<III", data, a + ci * 12)
                    if not n_layers or not off_inst:
                        continue
                    cy, cx = divmod(ci, 16)
                    for li in range(n_layers):
                        p = a + off_inst + li * 24
                        _type, _fmt, _mn, _mx, x0, y0, w, h, off_mask, _off_vh = struct.unpack_from("<HHffBBBBII", data, p)
                        cells = np.zeros((8, 8), bool)
                        if off_mask:
                            nbits = w * h
                            raw = data[a + off_mask : a + off_mask + (nbits + 7) // 8]
                            bits = np.unpackbits(np.frombuffer(raw, np.uint8), bitorder="little")[:nbits]
                            cells[y0 : y0 + h, x0 : x0 + w] = bits.reshape(h, w).astype(bool)
                        else:
                            cells[y0 : y0 + h, x0 : x0 + w] = True
                        big = np.kron(cells, np.ones((cell, cell), bool))
                        r, c = r0 + cy * PX_PER_CHUNK, c0 + cx * PX_PER_CHUNK
                        out[r : r + PX_PER_CHUNK, c : c + PX_PER_CHUNK] |= big
        return out

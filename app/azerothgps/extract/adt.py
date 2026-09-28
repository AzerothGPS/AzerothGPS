"""WDT / split-ADT (_tex0) parsing: texture layers and alpha maps per chunk."""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

TILE_YD = 1600.0 / 3.0  # 533.33 yd
CHUNK_YD = TILE_YD / 16
ALPHA_RES = 64  # texels per chunk edge

MPHD_BIG_ALPHA = 0x4
MPHD_HEIGHT_TEXTURING = 0x80
MCLY_USE_ALPHA = 0x100
MCLY_COMPRESSED = 0x200


def iter_chunks(data: bytes, start: int = 0, end: int | None = None):
    """Yield (magic, payload_start, payload_end). Magics are stored reversed."""
    pos, end = start, len(data) if end is None else end
    while pos + 8 <= end:
        magic = data[pos : pos + 4][::-1].decode("ascii", "replace")
        (size,) = struct.unpack_from("<I", data, pos + 4)
        yield magic, pos + 8, pos + 8 + size
        pos += 8 + size


@dataclass
class WdtTile:
    root: int
    obj0: int
    obj1: int
    tex0: int
    lod: int
    map_texture: int
    map_texture_n: int
    minimap: int


@dataclass
class Wdt:
    flags: int
    tiles: dict[tuple[int, int], WdtTile]  # (tx, ty) -> file ids

    @property
    def big_alpha(self) -> bool:
        return bool(self.flags & (MPHD_BIG_ALPHA | MPHD_HEIGHT_TEXTURING))


def parse_wdt(data: bytes) -> Wdt:
    flags = 0
    tiles: dict[tuple[int, int], WdtTile] = {}
    for magic, a, b in iter_chunks(data):
        if magic == "MPHD":
            flags = struct.unpack_from("<I", data, a)[0]
        elif magic == "MAID":
            for i in range(4096):
                ids = struct.unpack_from("<8I", data, a + 32 * i)
                if ids[0] or ids[3]:
                    ty, tx = divmod(i, 64)
                    tiles[(tx, ty)] = WdtTile(*ids)
    return Wdt(flags, tiles)


@dataclass
class Tex0:
    textures: list[int | str]  # FileDataIDs (MDID) or names (MTEX), indexed by MCLY textureId
    # chunks[cy*16+cx] = list of (texture_index, alpha[64,64] float32 0..1 or None for base)
    chunks: list[list[tuple[int, np.ndarray | None]]]


def _decompress_alpha(buf: bytes, pos: int) -> np.ndarray:
    out = bytearray()
    while len(out) < 4096 and pos < len(buf):
        ctl = buf[pos]
        pos += 1
        n = ctl & 0x7F
        if ctl & 0x80:
            out += bytes([buf[pos]]) * n
            pos += 1
        else:
            out += buf[pos : pos + n]
            pos += n
    out = out[:4096].ljust(4096, b"\0")
    return np.frombuffer(bytes(out), np.uint8).reshape(64, 64)


def _read_alpha(mcal: bytes, offset: int, flags: int, big_alpha: bool) -> np.ndarray:
    if flags & MCLY_COMPRESSED:
        a = _decompress_alpha(mcal, offset)
    elif big_alpha:
        a = np.frombuffer(mcal[offset : offset + 4096].ljust(4096, b"\0"), np.uint8).reshape(64, 64)
    else:
        raw = np.frombuffer(mcal[offset : offset + 2048].ljust(2048, b"\0"), np.uint8)
        a = np.empty(4096, np.uint8)
        a[0::2] = (raw & 0x0F) * 17
        a[1::2] = (raw >> 4) * 17
        a = a.reshape(64, 64)
    return a.astype(np.float32) / 255.0


def parse_tex0(data: bytes, big_alpha: bool) -> Tex0:
    textures: list[int | str] = []
    chunks: list[list[tuple[int, np.ndarray | None]]] = []
    for magic, a, b in iter_chunks(data):
        if magic == "MDID":
            textures = list(struct.unpack_from(f"<{(b - a) // 4}I", data, a))
        elif magic == "MTEX" and not textures:
            textures = [n.decode("utf-8", "replace").lower() for n in data[a:b].split(b"\0") if n]
        elif magic == "MCNK":
            layers_raw, mcal = [], b""
            for m2, a2, b2 in iter_chunks(data, a, b):
                if m2 == "MCLY":
                    for i in range(a2, b2, 16):
                        layers_raw.append(struct.unpack_from("<IIII", data, i))
                elif m2 == "MCAL":
                    mcal = data[a2:b2]
            layers: list[tuple[int, np.ndarray | None]] = []
            for li, (tex, flags, off, _eff) in enumerate(layers_raw):
                if li == 0 or not flags & MCLY_USE_ALPHA:
                    layers.append((tex, None))
                else:
                    layers.append((tex, _read_alpha(mcal, off, flags, big_alpha)))
            chunks.append(layers)
    return Tex0(textures, chunks)


def layer_weights(layers: list[tuple[int, np.ndarray | None]]) -> list[tuple[int, np.ndarray]]:
    """Per-layer visible weight (64x64). Base layer gets whatever the others leave."""
    out = []
    total = np.zeros((64, 64), np.float32)
    for tex, alpha in layers[1:]:
        w = alpha if alpha is not None else np.zeros((64, 64), np.float32)
        out.append((tex, w))
        total += w
    if layers:
        out.insert(0, (layers[0][0], np.clip(1.0 - total, 0.0, 1.0)))
    return out


MCNK_AREA_OFFSET = 0x34


def parse_root_area_ids(data: bytes) -> np.ndarray:
    """Area (AreaTable ID) per chunk from a root ADT, as a 16x16 [cy, cx] grid."""
    out = np.zeros((16, 16), np.int32)
    i = 0
    for magic, a, _b in iter_chunks(data):
        if magic == "MCNK":
            ix, iy = struct.unpack_from("<II", data, a + 4)
            area = struct.unpack_from("<I", data, a + MCNK_AREA_OFFSET)[0]
            if ix < 16 and iy < 16:
                out[iy, ix] = area
            else:  # unexpected index; fall back to file order
                out[divmod(i, 16)] = area
            i += 1
    return out


def world_to_tile(wx: float, wy: float) -> tuple[float, float]:
    """World (x north, y west) -> fractional ADT tile coords (tx east, ty south)."""
    return 32.0 - wy / TILE_YD, 32.0 - wx / TILE_YD

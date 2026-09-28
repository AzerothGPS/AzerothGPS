"""Minimal read-only CASC reader for a local WoW install.

Resolves FileDataID -> content key (root) -> encoding key (encoding) ->
archive location (local .idx) -> BLTE-decoded bytes. Enough to read DB2,
BLP and ADT files; no writing, no network.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

LOCALE_ENUS = 0x2
LOCALE_ALL = 0xFFFFFFFF
CONTENT_LOW_VIOLENCE = 0x80
CONTENT_NO_NAME_HASH = 0x10000000


class CascError(Exception):
    pass


class EncryptedError(CascError):
    pass


def read_build_info(wow_path: Path) -> list[dict[str, str]]:
    lines = (wow_path / ".build.info").read_text(encoding="utf-8").splitlines()
    header = [h.split("!")[0] for h in lines[0].split("|")]
    return [dict(zip(header, l.split("|"))) for l in lines[1:] if l.strip()]


def _config(path: Path) -> dict[str, list[str]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.split()
    return out


def blte_decode(data: bytes, zero_encrypted: bool = False) -> bytes:
    """Decode BLTE. With zero_encrypted, chunks we have no key for become zeros
    (DB2s keep unreleased-content sections in encrypted chunks)."""
    if data[:4] != b"BLTE":
        raise CascError("not BLTE")
    header_size = struct.unpack(">I", data[4:8])[0]
    if header_size == 0:
        return _blte_chunk(data[8:])
    count = int.from_bytes(data[9:12], "big")
    chunks = []
    pos = 12
    for _ in range(count):
        chunks.append(struct.unpack(">II", data[pos : pos + 8]))
        pos += 24
    pos = header_size
    out = bytearray()
    for comp, decomp in chunks:
        try:
            out += _blte_chunk(data[pos : pos + comp])
        except EncryptedError:
            if not zero_encrypted:
                raise
            out += bytes(decomp)
        pos += comp
    return bytes(out)


def _blte_chunk(chunk: bytes) -> bytes:
    mode = chunk[:1]
    if mode == b"N":
        return chunk[1:]
    if mode == b"Z":
        return zlib.decompress(chunk[1:])
    if mode == b"F":
        return blte_decode(chunk[1:])
    if mode == b"E":
        raise EncryptedError("encrypted chunk")
    if mode == b"4":
        import lz4.block  # optional

        return lz4.block.decompress(chunk[1:])
    raise CascError(f"unknown BLTE mode {mode!r}")


@dataclass
class _Loc:
    archive: int
    offset: int
    size: int


class CascStorage:
    def __init__(self, wow_path: Path, product: str) -> None:
        self.wow_path = Path(wow_path)
        rows = [r for r in read_build_info(self.wow_path) if r.get("Product") == product]
        if not rows:
            raise CascError(f"product {product} not in .build.info")
        self.build_info = rows[0]
        self.version = self.build_info.get("Version", "?")
        bk = self.build_info["Build Key"]
        self.data_dir = self.wow_path / "Data"
        self.build_config = _config(self.data_dir / "config" / bk[:2] / bk[2:4] / bk)
        self._load_indices()
        self._load_encoding()
        self._load_root()

    # --- local indices -----------------------------------------------------
    def _load_indices(self) -> None:
        latest: dict[int, Path] = {}
        for p in (self.data_dir / "data").glob("*.idx"):
            bucket, ver = int(p.stem[:2], 16), int(p.stem[2:], 16)
            if bucket not in latest or ver > int(latest[bucket].stem[2:], 16):
                latest[bucket] = p
        self.index: dict[bytes, _Loc] = {}
        for p in latest.values():
            data = p.read_bytes()
            (hdr_size,) = struct.unpack_from("<I", data, 0)
            _ver, _bucket, _extra, size_len, off_len, key_len, off_bits = struct.unpack_from("<HBBBBBB", data, 8)
            pos = (8 + hdr_size + 0x0F) & ~0x0F
            (entries_size,) = struct.unpack_from("<I", data, pos)
            pos += 8
            entry_len = key_len + off_len + size_len
            mask = (1 << off_bits) - 1
            for i in range(pos, pos + entries_size, entry_len):
                key = data[i : i + key_len]
                packed = int.from_bytes(data[i + key_len : i + key_len + off_len], "big")
                size = int.from_bytes(data[i + key_len + off_len : i + entry_len], "little")
                self.index.setdefault(key, _Loc(packed >> off_bits, packed & mask, size))

    def read_ekey(self, ekey: bytes, zero_encrypted: bool = False) -> bytes:
        loc = self.index.get(ekey[:9])
        if loc is None:
            raise CascError(f"ekey {ekey.hex()} not in local storage")
        with open(self.data_dir / "data" / f"data.{loc.archive:03d}", "rb") as f:
            f.seek(loc.offset + 30)  # skip the 30-byte archive entry header
            raw = f.read(loc.size - 30)
        return blte_decode(raw, zero_encrypted)

    # --- encoding: ckey -> ekey --------------------------------------------
    def _load_encoding(self) -> None:
        ekey = bytes.fromhex(self.build_config["encoding"][1])
        data = self.read_ekey(ekey)
        if data[:2] != b"EN":
            raise CascError("bad encoding file")
        ckey_size, ekey_size = data[3], data[4]
        ce_page_kb = struct.unpack_from(">H", data, 5)[0]
        ce_pages = struct.unpack_from(">I", data, 9)[0]
        espec_size = struct.unpack_from(">I", data, 18)[0]
        pos = 22 + espec_size + ce_pages * (ckey_size + 16)
        page_size = ce_page_kb * 1024
        self.encoding: dict[bytes, bytes] = {}
        for p in range(ce_pages):
            i, end = pos + p * page_size, pos + (p + 1) * page_size
            while i < end:
                n = data[i]
                if n == 0:
                    break
                ckey = data[i + 6 : i + 6 + ckey_size]
                self.encoding[ckey] = data[i + 6 + ckey_size : i + 6 + ckey_size + ekey_size]
                i += 6 + ckey_size + n * ekey_size

    def read_ckey(self, ckey: bytes, zero_encrypted: bool = False) -> bytes:
        ekey = self.encoding.get(ckey)
        if ekey is None:
            raise CascError(f"ckey {ckey.hex()} not in encoding")
        return self.read_ekey(ekey, zero_encrypted)

    # --- root: FileDataID -> ckey ------------------------------------------
    def _load_root(self) -> None:
        data = self.read_ckey(bytes.fromhex(self.build_config["root"][0]))
        self.root: dict[int, bytes] = {}
        pos = 0
        version = 0
        if data[:4] == b"TSFM":
            hdr_size, version = struct.unpack_from("<II", data, 4)
            if hdr_size == 0x18:
                pos = 0x18
            else:  # pre-versioned MFST header
                version, pos = 0, 12
        while pos < len(data):
            (n,) = struct.unpack_from("<I", data, pos)
            if version >= 2:
                locale, u1, u2, u3 = struct.unpack_from("<IIIB", data, pos + 4)
                content = u1 | u2 | (u3 << 17)
                pos += 17
            else:
                content, locale = struct.unpack_from("<II", data, pos + 4)
                pos += 12
            deltas = struct.unpack_from(f"<{n}i", data, pos)
            pos += 4 * n
            ckeys = pos
            pos += 16 * n
            if not (content & CONTENT_NO_NAME_HASH):
                pos += 8 * n
            usable = (locale & LOCALE_ENUS or locale == LOCALE_ALL) and not (content & CONTENT_LOW_VIOLENCE)
            if not usable:
                continue
            fdid = -1
            for i, d in enumerate(deltas):
                fdid += d + 1
                self.root.setdefault(fdid, data[ckeys + 16 * i : ckeys + 16 * (i + 1)])

    def has(self, fdid: int) -> bool:
        return fdid in self.root

    def read(self, fdid: int, zero_encrypted: bool = False) -> bytes:
        ckey = self.root.get(fdid)
        if ckey is None:
            raise CascError(f"FileDataID {fdid} not in root")
        return self.read_ckey(ckey, zero_encrypted)


class Listfile:
    """Community listfile: FileDataID <-> lowercase path."""

    def __init__(self, path: Path) -> None:
        self.by_id: dict[int, str] = {}
        self.by_name: dict[str, int] = {}
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                fid, _, name = line.rstrip("\n").partition(";")
                if fid.isdigit():
                    n = name.lower()
                    self.by_id[int(fid)] = n
                    self.by_name[n] = int(fid)

    def id(self, name: str) -> int:
        return self.by_name[name.lower().replace("\\", "/")]

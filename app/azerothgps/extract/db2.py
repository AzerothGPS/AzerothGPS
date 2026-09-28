"""WDC5 DB2 reader driven by WoWDBDefs (.dbd) column definitions."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path


class Db2Error(Exception):
    pass


# --- DBD ----------------------------------------------------------------------


@dataclass
class DbdField:
    name: str
    kind: str  # int, float, string, locstring
    signed: bool
    array: int  # 1 for scalars
    noninline: bool
    is_id: bool
    is_relation: bool


def parse_dbd(path: Path, layout_hash: int) -> list[DbdField]:
    text = Path(path).read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    kinds: dict[str, str] = {}
    for line in blocks[0].splitlines()[1:]:
        m = re.match(r"(\w+)(?:<[^>]*>)?\s+(\w+)", line.strip())
        if m:
            kinds[m.group(2)] = m.group(1)
    want = f"{layout_hash:08X}"
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        layouts = [l for l in lines if l.startswith("LAYOUT")]
        if not any(want in l for l in layouts):
            continue
        fields = []
        for l in lines:
            if l.startswith(("LAYOUT", "BUILD", "COMMENT")) or not l.strip():
                continue
            m = re.match(r"(?:\$([\w,]+)\$)?(\w+)(?:<(u?)(\d+)>)?(?:\[(\d+)\])?", l.strip())
            if not m:
                continue
            anns = (m.group(1) or "").split(",")
            name = m.group(2)
            fields.append(DbdField(
                name=name,
                kind=kinds.get(name, "int"),
                signed=m.group(3) != "u",
                array=int(m.group(5) or 1),
                noninline="noninline" in anns,
                is_id="id" in anns,
                is_relation="relation" in anns,
            ))
        return fields
    raise Db2Error(f"layout {want} not found in {path}")


# --- WDC5 ---------------------------------------------------------------------

_HDR = struct.Struct("<4sI128s9IHH7I")
_SECTION = struct.Struct("<Q8I")


@dataclass
class _Storage:
    offset_bits: int
    size_bits: int
    additional: int
    type: int
    v1: int
    v2: int
    v3: int


def _bits(rec: bytes, bit_off: int, n: int) -> int:
    start = bit_off >> 3
    chunk = int.from_bytes(rec[start : start + ((bit_off & 7) + n + 7) // 8], "little")
    return (chunk >> (bit_off & 7)) & ((1 << n) - 1)


def _signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def _as_float(v: int) -> float:
    return struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]


def read_db2(data: bytes, dbd_path: Path) -> list[dict]:
    if data[:4] != b"WDC5":
        raise Db2Error(f"unsupported DB2 magic {data[:4]!r}")
    h = _HDR.unpack_from(data, 0)
    (_, _, _, rec_count, field_count, rec_size, _str_size, _table_hash, layout_hash,
     _min_id, _max_id, _locale, flags, id_index, _total_fields, _bp_off, _lookup,
     fsi_size, common_size, pallet_size, n_sections) = h
    pos = _HDR.size
    sections = []
    for _ in range(n_sections):
        sections.append(_SECTION.unpack_from(data, pos))
        pos += _SECTION.size
    pos += 4 * field_count  # field_structure (size, offset) -- storage info has what we need
    storage = []
    for _ in range(fsi_size // 24):
        storage.append(_Storage(*struct.unpack_from("<HHIIIII", data, pos)))
        pos += 24
    pallet_base = pos
    common_base = pallet_base + pallet_size

    # Per-field slices of the pallet and common-data blocks.
    pallet_off, common = [], []
    po = co = 0
    for s in storage:
        pallet_off.append(po)
        if s.type in (3, 4):
            po += s.additional
        cmap = {}
        if s.type == 2:
            for i in range(s.additional // 8):
                k, v = struct.unpack_from("<II", data, common_base + co + 8 * i)
                cmap[k] = v
            co += s.additional
        common.append(cmap)

    fields = parse_dbd(dbd_path, layout_hash)
    inline = [f for f in fields if not f.noninline]
    if len(inline) != len(storage):
        raise Db2Error(f"DBD has {len(inline)} inline fields, file has {len(storage)}")
    id_field = next((f.name for f in fields if f.is_id), "ID")
    rel_field = next((f.name for f in fields if f.is_relation and f.noninline), None)

    if flags & 0x1:
        raise Db2Error("offset-map (sparse) DB2 not supported yet")

    total_rec_bytes = sum(s[2] * rec_size for s in sections)
    strings = b"".join(data[s[1] + s[2] * rec_size : s[1] + s[2] * rec_size + s[3]] for s in sections)

    rows: list[dict] = []
    global_index = 0
    for tact_hash, file_off, n_rec, str_size, _rec_end, id_size, rel_size, _om_count, copy_count in sections:
        p = file_off + n_rec * rec_size + str_size
        ids = struct.unpack_from(f"<{id_size // 4}I", data, p) if id_size else ()
        p += id_size
        copies = [struct.unpack_from("<II", data, p + 8 * i) for i in range(copy_count)]
        p += 8 * copy_count
        rel: dict[int, int] = {}
        if rel_size:
            n_rel = struct.unpack_from("<I", data, p)[0]
            for i in range(n_rel):
                fid, idx = struct.unpack_from("<II", data, p + 12 + 8 * i)
                rel[idx] = fid
        sec_rows = []
        for r in range(n_rec):
            rec = data[file_off + r * rec_size : file_off + (r + 1) * rec_size]
            if tact_hash and not any(rec):
                global_index += 1
                continue  # encrypted section we could not decrypt (zero-filled)
            row: dict = {}
            for f, s in zip(inline, storage):
                vals = []
                if s.type == 0:
                    per = s.size_bits // f.array
                    for i in range(f.array):
                        vals.append(_bits(rec, s.offset_bits + i * per, per))
                elif s.type in (1, 5):
                    vals.append(_bits(rec, s.offset_bits, s.size_bits))
                elif s.type == 2:
                    vals.append(None)  # resolved after the ID is known
                elif s.type == 3:
                    idx = _bits(rec, s.offset_bits, s.size_bits)
                    vals.append(struct.unpack_from("<I", data, pallet_base + pallet_off[storage.index(s)] + 4 * idx)[0])
                elif s.type == 4:
                    idx = _bits(rec, s.offset_bits, s.size_bits)
                    base = pallet_base + pallet_off[storage.index(s)] + 4 * idx * s.v3
                    vals.extend(struct.unpack_from(f"<{s.v3}I", data, base))
                row[f.name] = (vals, s, f)
            rid = ids[r] if ids else None
            if rid is None:
                idf = inline[id_index]
                rid = row[idf.name][0][0]
            out: dict = {}
            for name, (vals, s, f) in row.items():
                if s.type == 2:
                    vals = [common[storage.index(s)].get(rid, s.v1)]
                conv = []
                for i, v in enumerate(vals):
                    bits = s.size_bits // max(len(vals), 1) if s.type == 0 else (32 if s.type in (2, 3, 4) else s.size_bits)
                    if f.kind == "float":
                        conv.append(_as_float(v))
                    elif f.kind in ("string", "locstring"):
                        field_pos = global_index * rec_size + s.offset_bits // 8 + i * 4
                        at = field_pos + v - total_rec_bytes
                        end = strings.find(b"\0", at)
                        conv.append(strings[at:end].decode("utf-8", "replace") if 0 <= at < len(strings) else "")
                    elif f.signed and (s.type == 5 or s.type == 0 or s.type in (2, 3, 4)):
                        conv.append(_signed(v, bits) if bits else v)
                    else:
                        conv.append(v)
                out[name] = conv if f.array > 1 or len(conv) > 1 else conv[0]
            out[id_field] = rid
            if rel_field is not None and r in rel:
                out[rel_field] = rel[r]
            sec_rows.append(out)
            global_index += 1
        by_id = {row[id_field]: row for row in sec_rows}
        for new_id, src in copies:
            if src in by_id:
                sec_rows.append({**by_id[src], id_field: new_id})
        rows.extend(sec_rows)
    return rows

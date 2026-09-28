"""Interior (WMO) minimaps for the addon: cities like Undercity and building interiors.

Findings (docs/coordinates.md, "Interiors"):
- WMO minimap images are `world/minimaps/wmo/<wmo path>_<group:3>_<bx:2>_<by:2>.blp`,
  2 px per yard, 128 yd per block. Blocks stack from the group's bbox minimum corner;
  inside an image, columns run +x and the top row is the highest local y.
  Images are cropped to the group, so they may be smaller than 256x256.
- Placement (ADT obj0 MODF): world X = 17066.67 - pos.z, Y = 17066.67 - pos.x, Z = pos.y;
  local (lx, ly) -> world: X = X0 + lx cos(t) - ly sin(t), Y = Y0 + lx sin(t) + ly cos(t),
  t = rot.y + 180 degrees (verified in game in Undercity: the Trade Quarter and the
  throne room land in the rooms the minimap names). World Z = Z0 + lz.
- Forever re-authored some WMOs under new FileDataIDs with no known name (listfile
  "autogen-names"); their group geometry matches the classic WMO, so they are matched
  to the classic WMO's minimap images by fingerprint (group count + bounding box).
"""

from __future__ import annotations

import io
import math
import re
import struct
from collections import defaultdict
from dataclasses import dataclass, field

from PIL import Image

from .extract import adt
from .extract.spike import ClientData

PLACEMENT_OFFSET = 17066.666
MINIMAP_RE = re.compile(r"^world/minimaps/wmo/(.+)_(\d{3})_(\d{2})_(\d{2})\.blp$")
MAX_TILT_DEG = 1.0  # placements tilted around x/z are skipped (the 2D map can't show them)


@dataclass
class WmoInfo:
    fid: int
    n_groups: int
    bbox: tuple
    groups: list  # (flags, bbox6) per group
    wmo_id: int = 0  # WMOAreaTable.WMOID
    group_files: tuple = ()  # GFID: FileDataID per group (LOD 0 first)


@dataclass
class Placement:
    wmo: int
    uid: int
    x: float
    y: float
    z: float
    yaw: float  # degrees
    tilt: float
    bounds: tuple  # world (minX, minY, maxX, maxY) from MODF extents
    name_set: int = 0  # MODF nameSet: which of the model's names (WMOAreaTable.NameSetID) this one has
    rx: float = 0.0  # MODF rotation around its x and z axes (degrees): the tilt
    rz: float = 0.0


@dataclass
class MinimapSet:
    source_wmo: int
    blocks: dict = field(default_factory=lambda: defaultdict(list))  # group -> [(bx, by, fid, w, h)]


def read_wmo(cd: ClientData, fid: int) -> WmoInfo | None:
    try:
        data = cd.casc.read(fid)
    except Exception:
        return None
    n, bbox, groups, wmo_id, gfids = 0, None, [], 0, ()
    for magic, a, b in adt.iter_chunks(data):
        if magic == "MOHD":
            n = struct.unpack_from("<II", data, a)[1]
            wmo_id = struct.unpack_from("<I", data, a + 32)[0]
            bbox = struct.unpack_from("<6f", data, a + 36)
        elif magic == "GFID":
            gfids = struct.unpack_from(f"<{(b - a) // 4}I", data, a)
        elif magic == "MOGI":
            groups = [(struct.unpack_from("<I", data, i)[0], struct.unpack_from("<6f", data, i + 4))
                      for i in range(a, b, 32)]
    if bbox is None:
        return None
    return WmoInfo(fid, n, bbox, groups, wmo_id, gfids)


MOGP_GROUP_ID = 56  # offset of the group's unique ID (WMOAreaTable.WMOGroupID) in the MOGP header


def group_names(cd: ClientData, w: WmoInfo, area_names: dict) -> list[str]:
    """Area name per group ("" if none): what GetMinimapZoneText() shows inside it."""
    out = []
    for gi in range(w.n_groups):
        name = ""
        if gi < len(w.group_files):
            try:
                data = cd.casc.read(w.group_files[gi])
                for magic, a, _b in adt.iter_chunks(data):
                    if magic == "MOGP":
                        gid = struct.unpack_from("<I", data, a + MOGP_GROUP_ID)[0]
                        name = area_names.get((w.wmo_id, gid), "")
                        break
            except Exception:
                pass
        out.append(name)
    return out


def fingerprint(w: WmoInfo) -> tuple:
    return (w.n_groups,) + tuple(round(v, 1) for v in w.bbox)


def placements(cd: ClientData, continent: int) -> list[Placement]:
    m = next(r for r in cd.table("Map") if r["ID"] == continent)
    wdt = adt.parse_wdt(cd.casc.read(m["WdtFileDataID"]))
    seen: dict[int, Placement] = {}
    for t in wdt.tiles.values():
        if not t.obj0:
            continue
        try:
            data = cd.casc.read(t.obj0)
        except Exception:
            continue
        for magic, a, b in adt.iter_chunks(data):
            if magic != "MODF":
                continue
            for i in range(a, b, 64):
                nid, uid = struct.unpack_from("<II", data, i)
                px, py, pz = struct.unpack_from("<3f", data, i + 8)
                rx, ry, rz = struct.unpack_from("<3f", data, i + 20)
                ext = struct.unpack_from("<6f", data, i + 32)  # (the world box: x, y (up), z min; max)
                flags, _doodads, name_set = struct.unpack_from("<3H", data, i + 56)
                if not flags & 0x8 or uid in seen:  # 0x8: nid is a FileDataID
                    continue
                xs = (PLACEMENT_OFFSET - ext[2], PLACEMENT_OFFSET - ext[5])
                ys = (PLACEMENT_OFFSET - ext[0], PLACEMENT_OFFSET - ext[3])
                seen[uid] = Placement(nid, uid, PLACEMENT_OFFSET - pz, PLACEMENT_OFFSET - px, py, ry,
                                      max(abs(rx), abs(rz)), (min(xs), min(ys), max(xs), max(ys)), name_set, rx, rz)
    return list(seen.values())


def minimap_sets(cd: ClientData) -> dict[str, MinimapSet]:
    """WMO path (lower-case, no extension) -> minimap blocks, for files present in this client."""
    sets: dict[str, MinimapSet] = {}
    for fid, name in cd.listfile.by_id.items():
        m = MINIMAP_RE.match(name)
        if not m or not cd.casc.has(fid):
            continue
        path, g, bx, by = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
        wmo_fid = cd.listfile.by_name.get(f"world/wmo/{path}.wmo")
        if wmo_fid is None:
            continue
        s = sets.setdefault(path, MinimapSet(wmo_fid))
        s.blocks[g].append((bx, by, fid))
    return sets


def build(cd: ClientData, continents=None, log=print) -> dict:
    if continents is None:
        from .extract.pipeline import CONTINENTS as continents  # the shared list
    return build_places(cd, ((c, placements(cd, c)) for c in continents), log=log)


def build_places(cd: ClientData, by_map, log=print) -> dict:
    """The interior maps of placed WMOs: `by_map` = (map id, [Placement, ...]) pairs (a
    continent's ADT placements, or a dungeon's models). {"wmos": ..., "places": ...}"""
    sets = minimap_sets(cd)
    by_wmo: dict[int, MinimapSet] = {s.source_wmo: s for s in sets.values()}
    fp_index: dict[tuple, int] = {}
    infos: dict[int, WmoInfo] = {}
    for wfid in by_wmo:
        w = read_wmo(cd, wfid)
        if w:
            infos[wfid] = w
            fp_index.setdefault(fingerprint(w), wfid)
    log(f"  interiors: {len(by_wmo)} WMOs with minimap images")

    area_names = {(r["WMOID"], r["WMOGroupID"]): r["AreaName_lang"]
                  for r in cd.table("WMOAreaTable") if r["AreaName_lang"]}
    sizes: dict[int, tuple[int, int]] = {}
    out_wmos: dict[int, dict] = {}  # placed WMO fid -> {groups...}
    out_places: list[dict] = []
    for cont, pl in by_map:
        used = 0
        for p in pl:
            if p.tilt > MAX_TILT_DEG:
                continue
            if p.wmo not in out_wmos:
                src = p.wmo if p.wmo in by_wmo else None
                geo = infos.get(p.wmo) or read_wmo(cd, p.wmo)
                if src is None and geo is not None:
                    src = fp_index.get(fingerprint(geo))  # re-authored copy of a classic WMO
                if src is None or geo is None:
                    out_wmos[p.wmo] = None
                    continue
                blocks = by_wmo[src].blocks
                names = group_names(cd, geo, area_names)
                groups = []
                for gi, (flags, bb) in enumerate(geo.groups):
                    bl = []
                    for bx, by, fid in sorted(blocks.get(gi, [])):
                        if fid not in sizes:
                            sizes[fid] = Image.open(io.BytesIO(cd.casc.read(fid))).size
                        bl.append((fid, bx, by) + sizes[fid])
                    if bl:
                        groups.append({"bbox": bb, "flags": flags, "blocks": bl, "name": names[gi]})
                out_wmos[p.wmo] = {"source": src, "groups": groups} if groups else None
            if out_wmos.get(p.wmo):
                out_places.append({"cont": cont, "wmo": p.wmo, "x": p.x, "y": p.y, "z": p.z,
                                   "yaw": math.radians((p.yaw + 180.0) % 360.0), "bounds": p.bounds})
                used += 1
        log(f"  interiors: map {cont}: {used} placed buildings with interior maps")
    return {"wmos": {k: v for k, v in out_wmos.items() if v}, "places": out_places}


def places_lua(doc: dict) -> list[str]:
    """A dungeon's interior maps, added to Interiors.lua's (loaded before): its WMOs' groups
    and where they're placed, keyed by its map id (what the game reports inside)."""
    out = []
    for wfid in sorted(doc["wmos"]):
        w = doc["wmos"][wfid]
        out.append(f"ns.WMOs[{wfid}] = ns.WMOs[{wfid}] or {{ groups = {{")
        for g in w["groups"]:
            bb = ",".join(f"{v:.1f}" for v in g["bbox"])
            bl = ",".join("{%d,%d,%d,%d,%d}" % b for b in g["blocks"])
            name = g["name"].replace("\\", "\\\\").replace('"', '\\"')
            indoor = "true" if g["flags"] & 0x2000 else "false"
            out.append(f'  {{{bb}, n = "{name}", ["in"] = {indoor}, blocks = {{{bl}}}}},')
        out.append("} }")
    for cont in sorted({p["cont"] for p in doc["places"]}):
        out.append(f"ns.Interiors[{cont}] = {{")
        for p in doc["places"]:
            if p["cont"] == cont:
                b = p["bounds"]
                out.append(f"  {{{p['wmo']},{p['x']:.2f},{p['y']:.2f},{p['z']:.2f},{p['yaw']:.5f},"
                           f"{b[0]:.1f},{b[1]:.1f},{b[2]:.1f},{b[3]:.1f}}},")
        out.append("}")
    return out


def interiors_lua(cd: ClientData, doc: dict) -> str:
    out = [f"-- GENERATED by `agps gen-addon-data` from client {cd.casc.version}. Do not edit by hand.",
           "-- Interior (WMO) minimaps. See app/azerothgps/interiors.py for the conventions.",
           "local _, ns = ...",
           "-- ns.WMOs[wmo] = { groups = { {minX,minY,minZ,maxX,maxY,maxZ, n = area name, in = indoor,",
           "--   blocks = { {fileID,bx,by,w,h}, ... }}, ... } }",
           "ns.WMOs = {"]
    for wfid in sorted(doc["wmos"]):
        w = doc["wmos"][wfid]
        out.append(f"  [{wfid}] = {{ groups = {{")
        for g in w["groups"]:
            bb = ",".join(f"{v:.1f}" for v in g["bbox"])
            bl = ",".join("{%d,%d,%d,%d,%d}" % b for b in g["blocks"])
            name = g["name"].replace("\\", "\\\\").replace('"', '\\"')
            indoor = "true" if g["flags"] & 0x2000 else "false"
            out.append(f'    {{{bb}, n = "{name}", ["in"] = {indoor}, blocks = {{{bl}}}}},')
        out.append("  } },")
    out.append("}")
    out.append("-- ns.Interiors[continent] = { {wmo, x, y, z, yaw, minX, minY, maxX, maxY}, ... }  (world yards, radians)")
    out.append("ns.Interiors = {")
    for cont in sorted({p["cont"] for p in doc["places"]}):
        out.append(f"  [{cont}] = {{")
        for p in doc["places"]:
            if p["cont"] == cont:
                b = p["bounds"]
                out.append(f"    {{{p['wmo']},{p['x']:.2f},{p['y']:.2f},{p['z']:.2f},{p['yaw']:.5f},"
                           f"{b[0]:.1f},{b[1]:.1f},{b[2]:.1f},{b[3]:.1f}}},")
        out.append("  },")
    out.append("}")
    return "\n".join(out) + "\n"

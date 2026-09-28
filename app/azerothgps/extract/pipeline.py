"""`azerothgps extract`: everything the runtime needs, from the local client.

Outputs (all under data/, git-ignored):
  uimaps.json          map frames (world bounds) + art size per uiMap
  art/<uiMapID>.png    composed in-game map art
  pois.json            flight masters, area POIs, town/subzone labels
  areas_<mapID>.npz    AreaTable ID per terrain chunk (33.3 yd), for place names
  manifest.json        client build + extraction time
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import adt
from .spike import ClientData, compose_map_art
from .tables import build_uimaps

CONTINENTS = (0, 1, 2991)  # Eastern Kingdoms, Kalimdor, Zephras Isle (WoW Forever)
FACTION_ALLIANCE = 0x1
FACTION_HORDE = 0x2


def extract_art(cd: ClientData, out: Path, maps: list[dict], log=print) -> None:
    art_dir = out / "art"
    art_dir.mkdir(parents=True, exist_ok=True)
    have_art = {r["UiMapID"] for r in cd.table("UiMapXMapArt")}
    for m in maps:
        if m["id"] not in have_art:
            continue
        img = compose_map_art(cd, m["id"])
        img.save(art_dir / f"{m['id']}.png", optimize=True)
        m["artW"], m["artH"] = img.size
    log(f"  art: {sum('artW' in m for m in maps)} maps")


def extract_area_grid(cd: ClientData, continent: int) -> tuple[np.ndarray, int]:
    """AreaTable ID per chunk over the whole continent: (1024, 1024) grid [row=south, col=east]."""
    cont = next(r for r in cd.table("Map") if r["ID"] == continent)
    wdt = adt.parse_wdt(cd.casc.read(cont["WdtFileDataID"]))
    grid = np.zeros((64 * 16, 64 * 16), np.int32)
    n = 0
    for (tx, ty), t in wdt.tiles.items():
        if not t.root:
            continue
        try:
            ids = adt.parse_root_area_ids(cd.casc.read(t.root))
        except Exception:
            continue  # missing/encrypted tile
        grid[ty * 16 : ty * 16 + 16, tx * 16 : tx * 16 + 16] = ids
        n += 1
    return grid, n


def chunk_center_world(row: int, col: int) -> tuple[float, float]:
    """World (X north, Y west) of a chunk centre in the continent chunk grid."""
    return (32 * adt.TILE_YD - (row + 0.5) * adt.CHUNK_YD, 32 * adt.TILE_YD - (col + 0.5) * adt.CHUNK_YD)


def town_labels(cd: ClientData, continent: int, grid: np.ndarray) -> list[dict]:
    """One label per subzone, at the chunk nearest the subzone's centroid."""
    areas = {r["ID"]: r for r in cd.table("AreaTable")}
    cells: dict[int, list[tuple[int, int]]] = defaultdict(list)
    rows, cols = np.nonzero(grid)
    for r, c in zip(rows.tolist(), cols.tolist()):
        cells[int(grid[r, c])].append((r, c))
    out = []
    for area_id, pts in cells.items():
        a = areas.get(area_id)
        if a is None or a["ParentAreaID"] == 0 or len(pts) < 2:
            continue  # zones themselves are labelled by the map art
        arr = np.array(pts, np.float32)
        centre = arr.mean(axis=0)
        r, c = pts[int(np.argmin(((arr - centre) ** 2).sum(axis=1)))]
        wx, wy = chunk_center_world(r, c)
        ancestors, cur = [], a["ParentAreaID"]
        while cur and cur in areas and cur not in ancestors:  # zone, city, parent subzone...
            ancestors.append(cur)
            cur = areas[cur]["ParentAreaID"]
        out.append({"type": "town", "id": area_id, "name": a["AreaName_lang"], "continent": continent,
                    "wx": round(wx, 1), "wy": round(wy, 1), "ancestors": ancestors, "chunks": len(pts)})
    return out


def taxi_pois(cd: ClientData) -> list[dict]:
    out = []
    for r in cd.table("TaxiNodes"):
        faction = [f for bit, f in ((FACTION_ALLIANCE, "alliance"), (FACTION_HORDE, "horde")) if r["Flags"] & bit]
        if not faction or r["ContinentID"] not in CONTINENTS:
            continue  # transports / unused nodes
        wx, wy, _ = r["Pos"]
        out.append({"type": "taxi", "id": r["ID"], "name": r["Name_lang"], "continent": r["ContinentID"],
                    "wx": round(wx, 1), "wy": round(wy, 1), "factions": faction})
    return out


def area_pois(cd: ClientData) -> list[dict]:
    out = []
    for r in cd.table("AreaPOI"):
        if r["ContinentID"] not in CONTINENTS or not r["Name_lang"]:
            continue
        wx, wy, _ = r["Pos"]
        out.append({"type": "poi", "id": r["ID"], "name": r["Name_lang"], "continent": r["ContinentID"],
                    "wx": round(wx, 1), "wy": round(wy, 1), "icon": r["Icon"], "importance": r["Importance"]})
    return out


def run_extract(cd: ClientData, out: Path, log=print) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    maps = build_uimaps(cd)
    extract_art(cd, out, maps, log)

    pois = taxi_pois(cd) + area_pois(cd)
    for cont in CONTINENTS:
        grid, n = extract_area_grid(cd, cont)
        np.savez_compressed(out / f"areas_{cont}.npz", grid=grid)
        towns = town_labels(cd, cont, grid)
        pois += towns
        log(f"  continent {cont}: {n} terrain tiles, {len(towns)} town labels")

    doc = {"build": cd.casc.version, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "maps": maps}
    (out / "uimaps.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    (out / "pois.json").write_text(json.dumps({"build": cd.casc.version, "pois": pois}, indent=1), encoding="utf-8")
    manifest = {"build": cd.casc.version, "product": cd.casc.build_info.get("Product"),
                "time": doc["time"], "seconds": round(time.time() - t0, 1),
                "counts": {"maps": len(maps), "art": sum("artW" in m for m in maps),
                           "pois": {k: sum(p["type"] == k for p in pois) for k in ("taxi", "poi", "town")}}}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest

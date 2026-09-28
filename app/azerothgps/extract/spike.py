"""Phase 0 extraction spike: zone map art + terrain layers -> road mask overlay.

Reads only the local install. Writes to data/spike/ (git-ignored).
"""

from __future__ import annotations

import csv
import io
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from . import adt
from .casc import CascStorage, Listfile
from .db2 import read_db2

from ..paths import RESOURCES

ROAD_RULES = RESOURCES / "overrides" / "road_textures.yaml"
PX_PER_CHUNK = 16  # 64 alpha texels -> 16 px: ~2.08 yd/px
PX_PER_TILE = PX_PER_CHUNK * 16


def load_road_rules(path: Path = ROAD_RULES) -> dict[str, list[str]]:
    """Tiny YAML subset: top-level keys holding `- item` lists or `[]`."""
    rules: dict[str, list[str]] = {}
    key = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "-")):
            key, _, rest = line.partition(":")
            key = key.strip()
            rules[key] = []
        elif line.strip().startswith("- ") and key:
            rules[key].append(line.strip()[2:].strip().strip("'\"").lower())
    return rules


def is_road(name: str, rules: dict[str, list[str]]) -> bool:
    if name in rules.get("deny", []):
        return False
    if name in rules.get("allow", []) or name in rules.get("strict", []):
        return True
    if any(k in name for k in rules.get("exclude_keywords", [])):
        return False
    return any(k in name for k in rules.get("include_keywords", []))


class ClientData:
    def __init__(self, wow_path: Path, product: str, ref_dir: Path) -> None:
        self.casc = CascStorage(wow_path, product)
        self.listfile = Listfile(ref_dir / "listfile.csv")
        self.dbd_dir = ref_dir / "dbd"
        self._tables: dict[str, list[dict]] = {}

    def table(self, name: str) -> list[dict]:
        if name not in self._tables:
            fid = self.listfile.id(f"dbfilesclient/{name.lower()}.db2")
            dbd = self.dbd_dir / f"{name}.dbd"
            if not dbd.exists():  # (a few tables' layouts for this client, written by hand: extract/dbd/)
                dbd = Path(__file__).parent / "dbd" / f"{name}.dbd"
            self._tables[name] = read_db2(self.casc.read(fid, zero_encrypted=True), dbd)
        return self._tables[name]

    def name(self, fid: int | str) -> str:
        return fid if isinstance(fid, str) else self.listfile.by_id.get(fid, f"fdid:{fid}")


def compose_map_art(cd: ClientData, ui_map_id: int, explored: bool = True) -> Image.Image:
    art_ids = [r["UiMapArtID"] for r in cd.table("UiMapXMapArt") if r["UiMapID"] == ui_map_id]
    if not art_ids:
        raise RuntimeError(f"no map art for uiMap {ui_map_id}")
    art = next(r for r in cd.table("UiMapArt") if r["ID"] == art_ids[0])
    style = next(r for r in cd.table("UiMapArtStyleLayer") if r["UiMapArtStyleID"] == art["UiMapArtStyleID"])
    tw, th = style["TileWidth"], style["TileHeight"]
    tiles = [r for r in cd.table("UiMapArtTile") if r["UiMapArtID"] == art["ID"] and r["LayerIndex"] == 0]
    cols = max(t["ColIndex"] for t in tiles) + 1
    rows = max(t["RowIndex"] for t in tiles) + 1
    canvas = Image.new("RGBA", (cols * tw, rows * th))
    for t in tiles:
        img = Image.open(io.BytesIO(cd.casc.read(t["FileDataID"]))).convert("RGBA")
        canvas.paste(img, (t["ColIndex"] * tw, t["RowIndex"] * th))
    if explored:
        _apply_explored_overlays(cd, art["ID"], canvas)
    return canvas.crop((0, 0, style["LayerWidth"], style["LayerHeight"]))


OVERLAY_TILE = 256


def _apply_explored_overlays(cd: ClientData, art_id: int, canvas: Image.Image) -> None:
    """Draw every WorldMapOverlay (the "explored" art) so the map looks fully discovered."""
    tiles_by_overlay: dict[int, list[dict]] = defaultdict(list)
    for t in cd.table("WorldMapOverlayTile"):
        if t["LayerIndex"] == 0:
            tiles_by_overlay[t["WorldMapOverlayID"]].append(t)
    for ov in cd.table("WorldMapOverlay"):
        if ov["UiMapArtID"] != art_id:
            continue
        layer = Image.new("RGBA", canvas.size)
        for t in tiles_by_overlay.get(ov["ID"], []):
            x = ov["OffsetX"] + t["ColIndex"] * OVERLAY_TILE
            y = ov["OffsetY"] + t["RowIndex"] * OVERLAY_TILE
            img = Image.open(io.BytesIO(cd.casc.read(t["FileDataID"]))).convert("RGBA")
            # Edge tiles are padded to 256; keep only the overlay's real extent.
            w = min(img.width, ov["TextureWidth"] - t["ColIndex"] * OVERLAY_TILE)
            h = min(img.height, ov["TextureHeight"] - t["RowIndex"] * OVERLAY_TILE)
            if w > 0 and h > 0:
                layer.paste(img.crop((0, 0, w, h)), (x, y))
        canvas.alpha_composite(layer)


def zone_assignment(cd: ClientData, ui_map_id: int) -> dict:
    rows = [r for r in cd.table("UiMapAssignment") if r["UiMapID"] == ui_map_id
            and r["UiMin"] == [0.0, 0.0] and r["UiMax"] == [1.0, 1.0]]
    if not rows:
        raise RuntimeError(f"no full-map UiMapAssignment for uiMap {ui_map_id}")
    return min(rows, key=lambda r: r["OrderIndex"])


def run_zone(cd: ClientData, zone: str, out: Path, rules: dict) -> dict:
    ui = next((r for r in cd.table("UiMap") if r["Type"] == 3 and r["Name_lang"].lower().startswith(zone.lower())), None)
    if ui is None:
        raise RuntimeError(f"zone {zone!r} not found in UiMap")
    slug = ui["Name_lang"].replace(" ", "")
    print(f"[{slug}] uiMap {ui['ID']}")

    art = compose_map_art(cd, ui["ID"])
    art.save(out / f"{slug}_map.png")

    asg = zone_assignment(cd, ui["ID"])
    minx, miny, _, maxx, maxy, _ = asg["Region"]
    cont = next(r for r in cd.table("Map") if r["ID"] == asg["MapID"])
    wdt = adt.parse_wdt(cd.casc.read(cont["WdtFileDataID"]))
    print(f"[{slug}] continent {cont['Directory']} world X {minx:.0f}..{maxx:.0f} Y {miny:.0f}..{maxy:.0f}")

    tx0, ty0 = adt.world_to_tile(maxx, maxy)  # north-west corner
    tx1, ty1 = adt.world_to_tile(minx, miny)  # south-east corner
    itx0, ity0 = int(np.floor(tx0)), int(np.floor(ty0))
    ntx, nty = int(np.floor(tx1)) - itx0 + 1, int(np.floor(ty1)) - ity0 + 1
    road = np.zeros((nty * PX_PER_TILE, ntx * PX_PER_TILE), np.float32)
    coverage: dict[str, float] = defaultdict(float)
    road_names: set[str] = set()
    for tx in range(itx0, itx0 + ntx):
        for ty in range(ity0, ity0 + nty):
            t = wdt.tiles.get((tx, ty))
            if not t or not t.tex0:
                continue
            tex = adt.parse_tex0(cd.casc.read(t.tex0), wdt.big_alpha)
            names = [cd.name(f) for f in tex.textures]
            for ci, layers in enumerate(tex.chunks):
                cy, cx = divmod(ci, 16)
                r0 = (ty - ity0) * PX_PER_TILE + cy * PX_PER_CHUNK
                c0 = (tx - itx0) * PX_PER_TILE + cx * PX_PER_CHUNK
                for ti, w in adt.layer_weights(layers):
                    name = names[ti] if ti < len(names) else f"tex#{ti}"
                    coverage[name] += float(w.mean())
                    if is_road(name, rules):
                        road_names.add(name)
                        small = w.reshape(PX_PER_CHUNK, 4, PX_PER_CHUNK, 4).mean(axis=(1, 3))
                        road[r0 : r0 + PX_PER_CHUNK, c0 : c0 + PX_PER_CHUNK] += small

    with open(out / f"textures_{slug}.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["texture", "chunks_covered", "road"])
        for name, c in sorted(coverage.items(), key=lambda kv: -kv[1]):
            wr.writerow([name, round(c, 2), int(is_road(name, rules))])

    # Crop the tile-aligned raster to the zone's map region.
    crop = (
        int(round((tx0 - itx0) * PX_PER_TILE)), int(round((ty0 - ity0) * PX_PER_TILE)),
        int(round((tx1 - itx0) * PX_PER_TILE)), int(round((ty1 - ity0) * PX_PER_TILE)),
    )
    road = road[crop[1] : crop[3], crop[0] : crop[2]]
    mask = _clean_mask(road > 0.35)
    Image.fromarray((mask * 255).astype(np.uint8)).save(out / f"{slug}_roadmask.png")

    # Overlay at 2x the map art so thin roads stay visible.
    big = art.resize((art.width * 2, art.height * 2), Image.LANCZOS).convert("RGB")
    m = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).resize(big.size, Image.BILINEAR)) > 96
    ov = np.asarray(big).copy()
    ov[m] = (ov[m] * 0.2 + np.array([255, 30, 30]) * 0.8).astype(np.uint8)
    Image.fromarray(ov).save(out / f"{slug}_overlay.png")
    return {
        "uiMapID": ui["ID"], "name": ui["Name_lang"], "continentMapID": asg["MapID"],
        "region": asg["Region"], "tiles": [itx0, ity0, ntx, nty], "road_textures": sorted(road_names),
        "road_px": int(mask.sum()), "yd_per_px": adt.CHUNK_YD / PX_PER_CHUNK,
    }


def _clean_mask(mask: np.ndarray) -> np.ndarray:
    from skimage.morphology import closing, disk, remove_small_objects

    mask = closing(mask, disk(2))
    return remove_small_objects(mask, max_size=40)


def run_spike(wow_path: Path, product: str, zones: list[str], data_dir: Path) -> int:
    ref = data_dir / "ref"
    if not (ref / "listfile.csv").exists():
        print(f"missing {ref / 'listfile.csv'} (community listfile) and {ref / 'dbd'}/*.dbd")
        return 2
    out = data_dir / "spike"
    out.mkdir(parents=True, exist_ok=True)
    t = time.time()
    cd = ClientData(wow_path, product, ref)
    print(f"client {product} {cd.casc.version}: {len(cd.casc.root)} files ({time.time() - t:.1f}s)")
    rules = load_road_rules()
    manifest = {"product": product, "build": cd.casc.version, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "zones": []}
    for z in zones:
        manifest["zones"].append(run_zone(cd, z, out, rules))
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0

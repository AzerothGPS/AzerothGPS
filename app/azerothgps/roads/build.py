"""Build data/roads_<continent>.json from terrain textures (see docs/roads.md)."""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from ..extract import adt
from ..extract.spike import ClientData, is_road, load_road_rules
from ..paths import RESOURCES, wtf_account_dir
from ..routing.coords import Coords
from .graph import RoadGraph, apply_overrides, bridge_gaps, skeleton_to_graph
from .raster import YD_PER_PX, ContinentTerrain
from .terrain import continent_grid

# Thresholds on summed road-texture weight (0-255). Hysteresis keeps faint,
# blended stretches that connect to a clearly painted road.
HIGH = 100  # ~0.4
LOW = 40  # ~0.16
# Textures the rules list as "strict" also paint things other than roads (cracked ground
# around the roads, say) at lower strength: their roads start where painted at full
# strength and follow on only while still clearly painted.
STRICT_HIGH = 230  # ~0.9
STRICT_LOW = 90  # ~0.35
MIN_BLOB_PX = 40
SPUR_YD = 30.0
MERGE_YD = 6.0
MIN_COMPONENT_YD = 300.0  # isolated bits shorter than this are decoration
SIMPLIFY_YD = 1.5
FAR_END_YD = 250.0  # road ends facing each other this far apart join over open ground
FAR_EDGE_YD = 60.0  # a road end heading straight at another road this close joins it


def build_continent(cd: ClientData, continent: int, out: Path, log=print) -> RoadGraph:
    from skimage.filters import apply_hysteresis_threshold
    from skimage.morphology import closing, disk, remove_small_objects, skeletonize

    t0 = time.time()
    rules = load_road_rules()
    ct = ContinentTerrain(cd, continent)
    coverage: dict[str, float] = {}
    strict = set(rules.get("strict", []))
    ras, ras_strict = ct.texture_rasters(
        [lambda n: is_road(n, rules) and n not in strict, lambda n: n in strict], coverage=coverage)
    _write_texture_csv(out / f"textures_{continent}.csv", coverage, rules)
    log(f"  [{continent}] road raster {ras.shape[1]}x{ras.shape[0]} px ({time.time() - t0:.0f}s)")

    water = ct.liquid_mask()
    mask = apply_hysteresis_threshold(ras, LOW, HIGH)
    mask |= apply_hysteresis_threshold(ras_strict, STRICT_LOW, STRICT_HIGH)
    mask = closing(mask, disk(2))
    mask = remove_small_objects(mask, max_size=MIN_BLOB_PX)
    skel = skeletonize(mask)
    log(f"  [{continent}] skeleton {int(skel.sum())} px ({time.time() - t0:.0f}s)")

    grid = ct.grid
    g = skeleton_to_graph(skel, grid.px_to_world)
    g.contract_degree2()
    g.prune_spurs(SPUR_YD)
    g.merge_close_nodes(MERGE_YD)
    g.contract_degree2()
    g.simplify(SIMPLIFY_YD)

    def crosses_water(p, q) -> bool:
        for t in np.linspace(0.2, 0.8, 7):
            r, c = grid.world_to_px(*(p + (q - p) * t))
            ri, ci = int(round(r)), int(round(c))
            if 0 <= ri < water.shape[0] and 0 <= ci < water.shape[1] and water[ri, ci]:
                return True
        return False

    clear = _clear_line(continent_grid(cd, continent, log=lambda *a: None))
    # Join before dropping short bits: a road whose texture fades out now and then is a
    # string of short pieces, each of which alone looks like decoration.
    bridged = bridge_gaps(g, crosses_water=crosses_water, far_end_max=FAR_END_YD,
                          far_edge_max=FAR_EDGE_YD, clear=clear)
    g.contract_degree2()
    g.remove_small_components(MIN_COMPONENT_YD)
    extra = {"continent": continent, "build": cd.casc.version, "grid": grid.to_json(),
             "params": {"high": HIGH, "low": LOW, "strictHigh": STRICT_HIGH, "strictLow": STRICT_LOW,
                        "spurYd": SPUR_YD, "mergeYd": MERGE_YD,
                        "minComponentYd": MIN_COMPONENT_YD, "ydPerPx": YD_PER_PX,
                        "farEndYd": FAR_END_YD, "farEdgeYd": FAR_EDGE_YD}}
    # (the network before the overrides, kept: new overrides go on it in seconds)
    (out / f"roads_{continent}_base.json").write_text(json.dumps(g.to_json(extra)), encoding="utf-8")
    log(f"  [{continent}] bridged {bridged} ({time.time() - t0:.0f}s)")
    return finish_continent(g, continent, out, extra, log)


def finish_continent(g: RoadGraph, continent: int, out: Path, extra: dict, log=print) -> RoadGraph:
    """The overrides on the network (NPCs' travel paths first, then the hand-made and drawn
    fixes); written as data/roads_<continent>.json."""
    from .npcpaths import apply_paths

    pa = apply_paths(g, RESOURCES / "overrides" / f"paths_{continent}.geojson")
    ov = apply_overrides(g, RESOURCES / "overrides" / f"roads_{continent}.geojson")
    cut = cut_capitals(g, continent)
    log(f"  [{continent}] graph: {len(g.nodes)} nodes, {len(g.edges)} edges, "
        f"{g.total_length() / 1000:.1f}k yd; paths {pa}; overrides {ov}; cut in the capitals {cut:.0f} yd")
    (out / f"roads_{continent}.json").write_text(json.dumps(g.to_json(extra)), encoding="utf-8")
    return g


def capital_cells(continent: int) -> list:
    """The capitals' own cells on a continent, from Data/Capitals.lua (their grids over the
    continent's; Undercity is a level of its own, not here; nor the cities on their own ground): [(tx0, ty0, cell, rows)], rows decoded,
    a cell the city's own where its value is 0, 2 or 3 (1: the continent's there)."""
    import re

    from ..capitals import CAPITALS, key_of
    from ..paths import ADDON_DIR
    from .terrain import decode_row

    path = ADDON_DIR / "Data" / "Capitals.lua"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    out = []
    for cap in CAPITALS:
        # (a city on its own ground, Thunder Bluff's mesas, Darnassus: the land's paths there are
        # its paths, and its lifts join the land's roads at their feet)
        if cap.cont != continent or cap.ground_above is not None:
            continue
        m = re.search(r'^ns\.Terrain\["%s"\] = \{ tx0 = ([\d.-]+), ty0 = ([\d.-]+), cell = ([\d.]+), w = \d+, h = \d+, '
                      r'short = (\d+), long = (\d+),[^\n]*\n  rows = "([^"]*)"' % key_of(cap), text, re.M)
        if not m:
            continue
        short, long_ = int(m.group(4)), int(m.group(5))
        rows = [decode_row(r, short, long_) for r in m.group(6).split("/")]
        out.append((float(m.group(1)), float(m.group(2)), float(m.group(3)), rows))
    return out


def capital_cores(continent: int) -> list:
    """capital_cells' own cells less a CUT_MARGIN_YD band round their edge (the grid takes in the
    ground at the gates: the land's roads up to a gate are the way in, its gate roads join them there):
    [(tx0, ty0, cell, bool array)]."""
    from scipy import ndimage

    from ..capitals import CUT_MARGIN_YD

    out = []
    for tx0, ty0, cell, rows in capital_cells(continent):
        W = max(len(r) for r in rows)
        own = np.zeros((len(rows), W), bool)
        for i, r in enumerate(rows):
            own[i, :len(r)] = np.isin(np.asarray(r), (0, 2, 3))
        # (the margin at its outer edge only: ground inside it left to the land's grid, a park, isn't an edge)
        own = ndimage.binary_fill_holes(own)
        out.append((tx0, ty0, cell, ndimage.binary_erosion(own, iterations=max(1, int(CUT_MARGIN_YD / cell)))))
    return out


def cut_capitals(g: RoadGraph, continent: int) -> float:
    """The land's roads (traced from the ground's textures, and NPCs' paths) cut where they run over
    a capital's own cells: the capital's own roads (Data/Capitals.lua, its streets) are the way there,
    and the two drawn over each other were a jumble (Stormwind's, some over its harbor's water). Roads
    drawn in game stay (capitals.drawn_fixes puts those over a city on its roads too). The yards cut."""
    grids = capital_cores(continent)
    if not grids:
        return 0.0
    T = adt.TILE_YD

    def own(x, y) -> bool:
        for tx0, ty0, cell, core in grids:
            k = T / cell
            c = int(np.floor(((32 - y / T) - tx0) * k))
            r = int(np.floor(((32 - x / T) - ty0) * k))
            if 0 <= r < core.shape[0] and 0 <= c < core.shape[1] and core[r, c]:
                return True
        return False

    cut = 0.0
    for eid, e in list(g.edges.items()):
        P = np.asarray(e.pts, float)
        dense = []
        for a, b in zip(P[:-1], P[1:]):
            n = max(1, int(np.ceil(np.hypot(*(b - a)) / 2.0)))
            dense += [tuple(a + (b - a) * t) for t in np.linspace(0, 1, n, endpoint=False)]
        dense.append(tuple(P[-1]))
        if e.source == "override":
            continue  # (roads drawn in game stay whole: over a city, capitals.drawn_fixes adds them to its roads too)
        inside = [own(x, y) for x, y in dense]
        if not any(inside):
            continue
        # the stretches outside, each a road of its own; an end on the city's edge is a dead end
        g.remove_edge(eid)
        runs, cur = [], []
        for p, ins in zip(dense, inside):
            if ins:
                if len(cur) >= 2:
                    runs.append(cur)
                cur = []
            else:
                cur.append(p)
        if len(cur) >= 2:
            runs.append(cur)
        kept = 0.0
        for run in runs:
            a = e.a if run[0] == dense[0] else g.add_node(run[0])
            b = e.b if run[-1] == dense[-1] else g.add_node(run[-1])
            if a != b:
                g.add_edge(a, b, np.array(run), source=e.source)
                kept += sum(np.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(run, run[1:]))
        cut += e.length - kept
    g.drop_isolated_nodes()
    return cut


def reapply_overrides(data_dir: Path, continents, log=print) -> list[int]:
    """The overrides again on the kept networks (no terrain rebuild): the continents done."""
    done = []
    for cont in continents:
        base = Path(data_dir) / f"roads_{cont}_base.json"
        if not base.exists():
            log(f"  [{cont}] no {base.name} yet: run `agps roads` once")
            continue
        doc = json.loads(base.read_text(encoding="utf-8"))
        extra = {k: v for k, v in doc.items() if k not in ("nodes", "edges")}
        finish_continent(RoadGraph.from_json(doc), cont, Path(data_dir), extra, log)
        done.append(cont)
    return done


def _clear_line(pg: dict):
    """clear(p, q): the straight line p-q stays on open ground (passability 0) all the way."""
    cells, cell = pg["cells"], pg["cellYd"]
    tx0, ty0 = pg["tileX0"], pg["tileY0"]
    per_tile = adt.TILE_YD / cell

    def clear(p, q) -> bool:
        n = max(2, int(np.hypot(*(q - p)) / (cell / 2)) + 1)
        for t in np.linspace(0.0, 1.0, n):
            tx, ty = adt.world_to_tile(*(p + (q - p) * t))
            r, c = int((ty - ty0) * per_tile), int((tx - tx0) * per_tile)
            if not (0 <= r < cells.shape[0] and 0 <= c < cells.shape[1]) or cells[r, c] != 0:
                return False
        return True

    return clear


def _write_texture_csv(path: Path, coverage: dict[str, float], rules: dict) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["texture", "chunks_covered", "road"])
        for name, c in sorted(coverage.items(), key=lambda kv: -kv[1]):
            w.writerow([name, round(c, 2), int(is_road(name, rules))])


def render_zone_debug(g: RoadGraph, coords: Coords, ui_map_id: int, art_path: Path, out_path: Path,
                      scale: int = 2) -> None:
    """Road graph over the zone's map art: roads red, bridged gaps cyan, overrides green,
    junctions yellow, dead ends blue."""
    f = coords.frames[ui_map_id]
    art = Image.open(art_path).convert("RGB")
    W, H = art.width * scale, art.height * scale
    img = art.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(img)

    def px(p):
        x, y = coords.world_to_map(ui_map_id, p[0], p[1])
        return x * W, y * H

    colors = {"terrain": (230, 30, 30), "bridge": (0, 230, 255), "override": (40, 230, 40)}
    for e in g.edges.values():
        d.line([px(p) for p in e.pts], fill=colors.get(e.source, (230, 30, 30)), width=3)
    deg = g.degree()
    for n, p in g.nodes.items():
        x, y = px(p)
        if -5 <= x <= W + 5 and -5 <= y <= H + 5:
            col = (255, 220, 0) if deg[n] >= 3 else (60, 120, 255) if deg[n] == 1 else None
            if col:
                d.ellipse((x - 4, y - 4, x + 4, y + 4), fill=col, outline=(0, 0, 0))
    d.text((8, H - 18), f"{f.name}  roads red · bridged cyan · overrides green · junction yellow · dead end blue",
           fill=(255, 255, 255))
    img.save(out_path)


def build_roads(cd: ClientData, data_dir: Path, continents=None, log=print) -> dict:
    if continents is None:
        from ..extract.pipeline import CONTINENTS as continents  # the shared list
    from .tracks import import_tracks

    n = import_tracks(wtf_account_dir(), RESOURCES / "overrides")
    if n:
        log(f"  imported {n} recorded track(s) into overrides/")
    coords = Coords.load(data_dir / "uimaps.json")
    dbg = data_dir / "debug" / "roads"
    dbg.mkdir(parents=True, exist_ok=True)
    summary = {}
    for cont in continents:
        g = build_continent(cd, cont, data_dir, log)
        n = 0
        for f in coords.frames.values():
            art = data_dir / "art" / f"{f.id}.png"
            if f.continent == cont and art.exists() and _is_zone(coords, f.id, data_dir):
                render_zone_debug(g, coords, f.id, art, dbg / f"{f.name.replace(' ', '')}.png")
                n += 1
        summary[cont] = {"nodes": len(g.nodes), "edges": len(g.edges), "km": round(g.total_length() / 1000, 1),
                         "debugImages": n}
        log(f"  [{cont}] wrote {n} zone overlays to {dbg}")
    from ..paths import ADDON_DIR
    from .export import write_roads_lua

    p = write_roads_lua(data_dir, ADDON_DIR)
    log(f"  wrote {p} ({p.stat().st_size // 1024} KB)")
    return summary


def _is_zone(coords: Coords, ui_map_id: int, data_dir: Path) -> bool:
    maps = {m["id"]: m for m in json.loads((data_dir / "uimaps.json").read_text(encoding="utf-8"))["maps"]}
    return maps.get(ui_map_id, {}).get("type") == 3

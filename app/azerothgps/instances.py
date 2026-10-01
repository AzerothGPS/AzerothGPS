"""Dungeons and raids as their own routing levels (Data/Instances.lua).

Each instance map (the client's Map rows with an InstanceType: 1 party, 2 raid) becomes a
level of its own, like Undercity's (cities.py): a pseudo-continent LEVEL_BASE + its MapID
(the Deadmines, map 36: 20036), in the instance map's own world coordinates (what the game
reports inside), with
- a passability grid of its walkable floors (ns.Terrain[level]: 0 open, 1 water to swim, 2
  closed), roads along them (ns.Roads[level]), stairs between levels and one-way drops off
  ledges (ns.RoadDrops[level]), each cell's floor height (ns.CityHeights[level]), all from
  walknet.py over the instance's models: the one global WMO in the map's WDT, or the dungeon
  WMOs placed in its ADT tiles (the ones spawns stand in), with the terrain around them walked
  from their mouths. Only the floors reached on foot from the entrance or a boss are kept.
  Water deep enough to swim is a floor at its surface; magma and slime close the floors under.
- its entrances: the portal on the continent (where the game puts you when you leave it: the
  server's exit teleport, else the client's ghost entrance, Map.Corpse) and where you appear
  inside (the server's entering teleport), a transport between the continent's level and the
  instance's (ns.Transports, kind "portal", like Undercity's lifts);
- its bosses: the server's encounters (instance_encounters: the NPC killed), their spawn
  positions, the client's DungeonEncounter IDs by name, and rank 3 ("boss") NPCs spawned there.
Server data: the CMaNGOS classic database dump under data/thirdparty (hostile.DUMP).
`agps instances` renders each one into data/debug/instances/ (PNG + text grid) with
summary.txt; --write writes the file; --check routes from the entrance to every boss and
walks the routes over the floors in 3D.
"""

from __future__ import annotations

import gzip
import json
import math
import re
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import interiors as I
from . import walknet
from .extract import adt
from .extract.spike import ClientData
from .roads.terrain import ALPHABET, encode_row

LEVEL_BASE = 20000  # an instance's level: LEVEL_BASE + its MapID
CELL = walknet.CELL
FLOOR_SLOPE = 0.64  # a floor's normal at least this upright (as the caves')
SMOOTH = 2.0  # yards: roads simplified this far from their centerlines
PRUNE = 12.0  # yards: dead-end road stubs shorter than this go
FILL = 12  # cells: closed spots inside a floor up to this big are no fork in its road
GROUND_REACH = 400.0  # yards: an instance's terrain walked from its models' mouths
GROUND_NEAR = 40.0  # yards: ... only this near an NPC's spawn (or where you appear)
SWIM = (0, 1)  # liquid kinds swum through (water, ocean); magma (2) and slime (3) close their floors
WADE = 1.5  # yards: water this shallow over a floor is walked through (the floor stays)
STAIR_MAX = 200.0  # yards: the longest way a stair between levels is looked for (a keep's spiral stairs)
PORTAL_SECONDS = 15  # a portal: the loading screen
MIN_ROAD = 30.0  # yards: an instance with less road than this is left out
SHORT = 15  # the grid's short runs (as the caves': 4 values, 0 to 3)
HEIGHT_STEP = 2.0  # yards per step of the floor heights written
PAD = 60.0  # yards: an ADT instance's models within this of a spawn are its own
SERVER_CACHE = "instances_server.json"
BOSS_ORDER = Path(__file__).parent / "data" / "instance_bosses.json"  # the usual kill order (research)
SKIP_MAPS = {13, 29, 44, 169}  # test maps, an unused copy, the unused Emerald Dream


def level_id(map_id: int) -> int:
    return LEVEL_BASE + map_id


# --- server data (the CMaNGOS dump) ----------------------------------------------------


def server_data(data_dir: Path, log=print) -> dict:
    """What the instances need from the server's database: teleports, encounters, the NPCs'
    names and ranks, and the spawns on instance maps. Cached in data/debug/instances/."""
    from .hostile import DUMP, _rows

    dump = Path(data_dir) / DUMP
    cache = Path(data_dir) / "debug" / "instances" / SERVER_CACHE
    if cache.exists() and cache.stat().st_mtime >= dump.stat().st_mtime:
        doc = json.loads(cache.read_text(encoding="utf-8"))
        doc["spawns"] = {int(k): v for k, v in doc["spawns"].items()}
        doc["npcs"] = {int(k): v for k, v in doc["npcs"].items()}
        return doc
    log(f"  reading {dump.name} ...")
    txt = gzip.open(dump, "rt", encoding="utf-8", errors="replace").read()
    inst_maps = {int(r["map"]) for r in _rows(txt, "instance_template")}
    tele = [{"id": int(r["id"]), "name": r["name"], "map": int(r["target_map"]),
             "x": float(r["target_position_x"]), "y": float(r["target_position_y"]), "z": float(r["target_position_z"])}
            for r in _rows(txt, "areatrigger_teleport")]
    credit = {int(r["entry"]): (int(r["creditType"]), int(r["creditEntry"])) for r in _rows(txt, "instance_encounters")}
    enc = [{"map": int(r["MapId"]), "name": r["EncounterName"], "index": int(r["EncounterIndex"]),
            "credit": credit.get(int(r["Id"]), (None, None))}
           for r in _rows(txt, "instance_dungeon_encounters")]
    spawn_entry = defaultdict(list)
    for r in _rows(txt, "creature_spawn_entry"):
        spawn_entry[int(r["guid"])].append(int(r["entry"]))
    spawns = defaultdict(list)
    used = set()
    for r in _rows(txt, "creature"):
        m = int(r["map"])
        if m not in inst_maps:
            continue
        entries = [int(r["id"])] if int(r["id"]) else spawn_entry.get(int(r["guid"]), [])
        for e in entries:
            spawns[m].append((e, round(float(r["position_x"]), 1), round(float(r["position_y"]), 1),
                              round(float(r["position_z"]), 1)))
            used.add(e)
    for e in enc:
        used.add(e["credit"][1])
    npcs = {int(r["Entry"]): (r["Name"], int(r["Rank"])) for r in _rows(txt, "creature_template") if int(r["Entry"]) in used}
    doc = {"teleports": tele, "encounters": enc, "spawns": dict(spawns), "npcs": npcs, "maps": sorted(inst_maps)}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(doc), encoding="utf-8")
    return server_data(data_dir, log)


# --- what each instance is ------------------------------------------------------------


@dataclass
class Instance:
    map_id: int
    name: str
    raid: bool
    corpse: tuple | None  # (continent, x, y): the ghost's way in (Map.Corpse)
    entrances: list = field(default_factory=list)  # [(cont, x, y, z, ix, iy, iz, label)]
    bosses: list = field(default_factory=list)  # [dict]
    notes: list = field(default_factory=list)

    @property
    def level(self) -> int:
        return level_id(self.map_id)


def instance_maps(cd: ClientData) -> list:
    """The Map rows that are dungeons (InstanceType 1) or raids (2), dungeons first."""
    rows = [r for r in cd.table("Map") if r["InstanceType"] in (1, 2) and r["ID"] not in SKIP_MAPS]
    return sorted(rows, key=lambda r: (r["InstanceType"], r["ID"]))


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _tele_key(name: str) -> str:
    words = re.sub(r"\(.*?\)", " ", name.lower())
    words = re.sub(r"[^a-z' ]", " ", words).split()
    drop = {"entering", "exiting", "entrance", "exit", "instance", "start", "end", "inside", "the"}
    return " ".join(w for w in words if w not in drop)


def entrances(cd: ClientData, inst: Instance, server: dict, triggers: list) -> list:
    """The ways in: (cont, x, y, z, inside x, y, z, label) for each teleport into the instance
    from a continent (0, 1) paired with the spot the game puts you when you leave by it."""
    tele = server["teleports"]
    ins = [t for t in tele if t["map"] == inst.map_id]
    outs = [t for t in tele if t["map"] in (0, 1)]
    by_id = {t["ID"]: t for t in triggers}
    out = []
    inner = []  # ways in from another instance (Blackrock Spire's orb into Blackwing Lair)
    for t in ins:
        src = by_id.get(t["id"])
        if src is not None and src["ContinentID"] not in (0, 1):
            # (from inside another instance: its level, where its trigger is; used when there's
            # no way in from a continent)
            if src["ContinentID"] != inst.map_id:
                inner.append((level_id(src["ContinentID"]), src["Pos"][0], src["Pos"][1], src["Pos"][2],
                              t["x"], t["y"], t["z"], t["name"]))
            continue
        spot = None
        # the way back out: a trigger inside, near where you appear, taking you out
        for o in outs:
            s = by_id.get(o["id"])
            if s is not None and s["ContinentID"] == inst.map_id and \
                    math.hypot(s["Pos"][0] - t["x"], s["Pos"][1] - t["y"]) < 40:
                spot = (o["map"], o["x"], o["y"], o["z"])
        if spot is None:
            # (by name: "Deadmines - Entering" and "Deadmines - Exiting"), the one nearest the
            # ghost's way in when several
            k = _tele_key(t["name"])
            cands = [o for o in outs if _tele_key(o["name"]) == k and not (by_id.get(o["id"]) and
                                                                          by_id[o["id"]]["ContinentID"] != inst.map_id)]
            if not cands:
                first = k.split(" ")[0] if k else ""
                cands = [o for o in outs if first and _tele_key(o["name"]).split(" ")[0] == first]
            if inst.corpse:
                cands = [o for o in cands if o["map"] == inst.corpse[0]]
                cands.sort(key=lambda o: math.hypot(o["x"] - inst.corpse[1], o["y"] - inst.corpse[2]))
            if cands and (not inst.corpse or math.hypot(cands[0]["x"] - inst.corpse[1], cands[0]["y"] - inst.corpse[2]) < 600):
                o = cands[0]
                spot = (o["map"], o["x"], o["y"], o["z"])
        if spot is None and src is not None and src["ContinentID"] in (0, 1):
            spot = (src["ContinentID"], src["Pos"][0], src["Pos"][1], src["Pos"][2])  # (the trigger itself)
        if spot is None and inst.corpse:
            spot = (inst.corpse[0], inst.corpse[1], inst.corpse[2], None)
        if spot is None:
            continue
        if any(math.hypot(e[4] - t["x"], e[5] - t["y"]) < 20 and e[0] == spot[0] and
               math.hypot(e[1] - spot[1], e[2] - spot[2]) < 20 for e in out):
            continue  # (the same way in twice)
        out.append((spot[0], spot[1], spot[2], spot[3], t["x"], t["y"], t["z"], t["name"]))
    return out or inner


def bosses(cd: ClientData, inst: Instance, server: dict) -> list:
    """The bosses: the server's encounters (the NPC killed and where it stands), the client's
    DungeonEncounter IDs of that name, and the rank 3 NPCs spawned there. Each a dict: name,
    npc, x, y, z (None when it has no spawn: summoned in a fight), enc [IDs], index (the
    client's encounter order)."""
    npcs = server["npcs"]
    spawns = server["spawns"].get(inst.map_id, [])
    at = defaultdict(list)
    for e, x, y, z in spawns:
        at[e].append((x, y, z))
    client = [r for r in cd.table("DungeonEncounter") if r["MapID"] == inst.map_id]
    by_name = defaultdict(list)
    for r in client:
        by_name[_key(r["Name_lang"])].append(r)
    out, seen = [], set()

    def add(name, npc, index=None):
        if npc in seen:
            return
        seen.add(npc)
        pos = at.get(npc) or []
        if not pos and npc in npcs:
            # (summoned in the fight: the NPC it comes out of, "Sneed's Shredder")
            nm = npcs[npc][0]
            for e2, (n2, _r) in npcs.items():
                if e2 != npc and n2.startswith(nm) and at.get(e2):
                    pos = at[e2]
                    break
        rows = by_name.get(_key(name)) or by_name.get(_key(npcs.get(npc, ("",))[0])) or []
        if index is None and rows:
            index = min(r["F4"] for r in rows if r["F3"] in (0, 201)) if any(r["F3"] in (0, 201) for r in rows) else None
        x, y, z = pos[0] if pos else (None, None, None)
        out.append({"name": name, "npc": npc, "x": x, "y": y, "z": z, "enc": sorted(r["ID"] for r in rows),
                    "index": index, "spawns": len(pos)})

    for e in server["encounters"]:
        if e["map"] == inst.map_id and e["credit"][0] == 0 and e["credit"][1]:
            name = e["name"]
            # (the client's spelling when it has the encounter)
            rows = by_name.get(_key(name)) or by_name.get(_key(npcs.get(e["credit"][1], ("",))[0]))
            if rows:
                name = rows[0]["Name_lang"]
            add(name, e["credit"][1])
    # the client's encounters the server doesn't list: an NPC of that name spawned there
    for k, rows in by_name.items():
        if any(_key(b["name"]) == k for b in out):
            continue
        npc = next((e for e in at if _key(npcs.get(e, ("",))[0]) == k), None)
        if npc is not None:
            add(rows[0]["Name_lang"], npc)
    for e in at:
        if npcs.get(e, ("", 0))[1] == 3:
            add(npcs[e][0], e)
    out.sort(key=lambda b: (b["index"] is None, b["index"] if b["index"] is not None else 0, b["name"]))
    return out


def load_instances(cd: ClientData, server: dict, only=None) -> list:
    triggers = cd.table("AreaTrigger")
    out = []
    for r in instance_maps(cd):
        name = r["MapName_lang"]
        if only and not any(o.lower() in name.lower() or o == str(r["ID"]) for o in only):
            continue
        cm = r["CorpseMapID"]
        corpse = (cm, float(r["Corpse"][0]), float(r["Corpse"][1])) if cm in (0, 1) and any(r["Corpse"]) else None
        inst = Instance(r["ID"], name, r["InstanceType"] == 2, corpse)
        inst.entrances = entrances(cd, inst, server, triggers)
        inst.bosses = bosses(cd, inst, server)
        out.append(inst)
    return out


# --- the walk network ------------------------------------------------------------------


def wdt_placements(cd: ClientData, map_id: int) -> list:
    """The map's global WMO (a WDT MODF): its placement. Its position is in the model's own
    frame (no map offset): world X = -z, Y = -x, as an ADT placement's without the offset."""
    m = next(r for r in cd.table("Map") if r["ID"] == map_id)
    data = cd.casc.read(m["WdtFileDataID"])
    out = []
    for magic, a, b in adt.iter_chunks(data):
        if magic != "MODF":
            continue
        for i in range(a, b, 64):
            nid, uid = struct.unpack_from("<II", data, i)
            px, py, pz = struct.unpack_from("<3f", data, i + 8)
            rx, ry, rz = struct.unpack_from("<3f", data, i + 20)
            ext = struct.unpack_from("<6f", data, i + 32)
            flags, _dd, name_set = struct.unpack_from("<3H", data, i + 56)
            if not flags & 0x8:
                continue
            xs, ys = (-ext[2], -ext[5]), (-ext[0], -ext[3])
            out.append(I.Placement(nid, uid, -pz, -px, py, ry, max(abs(rx), abs(rz)),
                                   (min(xs), min(ys), max(xs), max(ys)), name_set, rx, rz))
    return out


def instance_models(cd: ClientData, inst: Instance, server: dict) -> tuple[list, bool]:
    """The instance's models: its global WMO, or the WMOs placed in its ADTs that its spawns
    (or where you appear) stand in or near. And whether it has terrain."""
    pl = wdt_placements(cd, inst.map_id)
    if pl:
        return pl, False
    spots = [(x, y) for _e, x, y, _z in server["spawns"].get(inst.map_id, [])] + [(e[4], e[5]) for e in inst.entrances]
    keep = []
    for p in I.placements(cd, inst.map_id):
        x0, y0, x1, y1 = p.bounds
        if any(x0 - PAD <= x <= x1 + PAD and y0 - PAD <= y <= y1 + PAD for x, y in spots):
            keep.append(p)
    return keep, True


def instance_faces(cd: ClientData, placements: list, log=print):
    """The models' faces in the world: floors, walls (walknet's formats), and the liquids:
    swum water as floors at its surface, magma and slime as liquids (closing what's under)."""
    fl, wl, lq, swim = [], [], [], []
    for p in placements:
        xf = walknet.Placed(p)
        groups = I.read_wmo(cd, p.wmo).groups
        outdoor = {gi for gi, (flags, _bb) in enumerate(groups) if flags & 0x8}
        floors, walls, liquids = walknet.model_faces(cd, p.wmo, FLOOR_SLOPE, liquid_kinds=True)
        for gi, _z, tri in floors:
            w3 = [xf(v) for v in tri]
            fl.append(([(q[0], q[1]) for q in w3], [q[2] for q in w3], False, gi in outdoor))
        for gi, _zz, tri in walls:
            w3 = [xf(v) for v in tri]
            zs = [q[2] for q in w3]
            wl.append(((min(zs), max(zs)), [(q[0], q[1]) for q in w3], zs))
        for gi, (x0, y0, x1, y1), lz, kind in liquids:
            corners = [xf((qx, qy, lz)) for qx, qy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
            poly = [(q[0], q[1]) for q in corners]
            h = sum(q[2] for q in corners) / 4
            if kind in SWIM:
                swim.append((poly, h, gi in outdoor))
            else:
                lq.append((poly, h))
    return fl, wl, lq, swim


def build_instance(cd: ClientData, inst: Instance, server: dict, log=print) -> dict | None:
    """The instance's grid, roads, heights, in its own world coordinates."""
    placements, terrain = instance_models(cd, inst, server)
    if not placements:
        inst.notes.append("no models found (no WMO in its WDT, none near its spawns)")
        return None
    fl, wl, lq, swim = instance_faces(cd, placements, log)
    if not fl:
        inst.notes.append("its models have no floors")
        return None
    # water: its surface is a floor (swimming) where the floor under is deeper than wading
    # (the floors under it stay out: walknet closes a floor under a liquid), and shallow water
    # is walked through (no liquid there)
    for poly, h, outdoor in swim:
        fl.append(([poly[0], poly[1], poly[2]], [h, h, h], False, outdoor))
        fl.append(([poly[0], poly[2], poly[3]], [h, h, h], False, outdoor))
        lq.append((poly, h - WADE))
    seeds = [(e[4], e[5], e[6]) for e in inst.entrances] + [(b["x"], b["y"], b["z"]) for b in inst.bosses if b["x"] is not None]
    ground = None
    if terrain:
        # the terrain around the models, walked from their mouths: only near where the
        # instance's NPCs stand (the land beyond its walls is there too, but not reached)
        from scipy.spatial import cKDTree

        from .caves import Ground
        land = Ground(cd, inst.map_id)
        spots = [(x, y) for _e, x, y, _z in server["spawns"].get(inst.map_id, [])] + [(e[4], e[5]) for e in inst.entrances]
        tree = cKDTree(np.array(spots))

        def ground(X, Y):
            h, ok = land.sample(X, Y)
            d, _ = tree.query(np.stack([np.ravel(X), np.ravel(Y)], 1), distance_upper_bound=GROUND_NEAR)
            return h, ok & np.isfinite(d).reshape(np.shape(X))
    u = walknet.build(fl, wl, lq, label=inst.name, ground=ground, ground_reach=GROUND_REACH, prune=PRUNE, fill=FILL,
                      top_reached=True, road_pieces=True, seeds=seeds, stair_max=STAIR_MAX, log=log)
    # the cells whose top floor is a water's surface: swum (1 in the grid)
    wet = np.zeros(u["cells"].shape, bool)
    if swim:
        # (a floor well over the water there, a bridge: not swum)
        wet = (u["cells"] == 0) & _water_top(u, swim)
    cells = u["cells"].copy()
    cells[wet] = 1
    u.update({"overlay": cells, "placements": placements, "terrain": terrain, "wet": wet})
    return u


def _water_top(u: dict, swim: list) -> np.ndarray:
    """Cells whose top floor is about a water surface's height (its surface is the floor)."""
    from PIL import Image, ImageDraw
    H, W = u["H"], u["W"]
    lvl = np.full((H, W), -1e4)
    for poly, h, _o in swim:
        img = Image.new("L", (W, H), 0)
        pts = [u["cellxy"](*q) for q in poly]
        c0, c1 = max(int(min(p[0] for p in pts)) - 1, 0), min(int(max(p[0] for p in pts)) + 2, W)
        r0, r1 = max(int(min(p[1] for p in pts)) - 1, 0), min(int(max(p[1] for p in pts)) + 2, H)
        if c1 <= c0 or r1 <= r0:
            continue
        ImageDraw.Draw(img).polygon(pts, fill=255)
        m = np.array(img)[r0:r1, c0:c1] > 0
        sub = lvl[r0:r1, c0:c1]
        sub[m] = np.maximum(sub[m], h)
    return np.abs(u["top"] - lvl) < 1.5


def keep_reached(u: dict, inst: Instance, log=print) -> None:
    """Road pieces not joined (walked, by stairs or drops) to an entrance or a boss: left out."""
    g = u["graph"]
    spots = [(e[4], e[5]) for e in inst.entrances] + [(b["x"], b["y"]) for b in inst.bosses if b["x"] is not None]
    comps = g.components()
    keep = set()
    for i, edges in enumerate(comps):
        pts = np.concatenate([g.edges[e].pts for e in edges])
        for x, y in spots:
            if np.hypot(pts[:, 0] - x, pts[:, 1] - y).min() < 40:
                keep.add(i)
    n = 0
    for i, edges in enumerate(comps):
        if i not in keep:
            for e in edges:
                g.remove_edge(e)
                n += 1
    g.drop_isolated_nodes()
    if n:
        log(f"  {inst.name}: {n} roads on pieces nowhere near the entrance or a boss left out")


# --- output ----------------------------------------------------------------------------


def _lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _crop(cells: np.ndarray):
    rr, cc = np.nonzero(cells != 2)
    if not rr.size:
        return 0, 1, 0, 1
    return int(rr.min()), int(rr.max()) + 1, int(cc.min()), int(cc.max()) + 1


def height_char(z: float, z0: float, step: float) -> str:
    """A floor height as a character: 48 + steps up from z0 (the backslash skipped), "." none."""
    if z < -1e3:
        return "."
    k = max(0, min(77, int(round((z - z0) / step))))
    b = 48 + k
    return chr(b + 1 if b >= 92 else b)


def height_runs(row: str) -> str:
    """A heights row as runs: each a height character then its length (ALPHABET, 1 to 64)."""
    out, i = [], 0
    while i < len(row):
        j = i
        while j < len(row) and row[j] == row[i] and j - i < 64:
            j += 1
        out.append(row[i] + ALPHABET[j - i - 1])
        i = j
    return "".join(out)


def zone_name(cd: ClientData, cont: int, x: float, y: float, cache: dict) -> str:
    """The zone at a continent spot (AreaTable over the area grid)."""
    from .extract.pipeline import extract_area_grid

    if cont not in cache:
        cache[cont] = extract_area_grid(cd, cont)[0]
    areas = cache.setdefault("areas", {r["ID"]: r for r in cd.table("AreaTable")})
    r, c = int((32 * adt.TILE_YD - x) / adt.CHUNK_YD), int((32 * adt.TILE_YD - y) / adt.CHUNK_YD)
    a = areas.get(int(cache[cont][r, c]))
    while a is not None and a["ParentAreaID"]:
        a = areas.get(a["ParentAreaID"])
    return (a or {}).get("AreaName_lang") or ""


def instance_roads(u: dict) -> tuple[list, list, dict, list | None]:
    """Nodes, edges, drops, and the nodes' heights (None without layers)."""
    if u.get("layered"):
        from .layers import roads
        return roads(u["layered"], u, SMOOTH)
    from .caves import cave_roads
    return (*cave_roads(u), None)


def _words(s: str) -> frozenset:
    return frozenset(re.findall(r"[a-z0-9]+", s.lower().replace("'", ""))) - {"the", "of"}


def boss_order() -> list:
    """The usual kill order per instance (data/instance_bosses.json, facts from public guides):
    [(names that may be the instance's, [{boss, optional, wing, npcs}])]. Instances sharing a
    map (Lower and Upper Blackrock Spire) are in the file's order."""
    if not BOSS_ORDER.exists():
        return []
    doc = json.loads(BOSS_ORDER.read_text(encoding="utf-8"))
    return [((key, it.get("map_hint") or key), it.get("order") or []) for key, it in doc.items()]


def order_bosses(inst: Instance, orders: list, server: dict | None = None) -> list | None:
    """The instance's bosses in the usual order (each gets `order`, from 0, and `optional`);
    bosses not in it after, in the client's encounter order. None when there's no order for
    it; else the names in the order that matched no boss here."""
    mine = _words(inst.name)
    steps = []
    for names, order in orders:
        ws = [_words(n) for n in names]
        if any(w == mine or (w and (w <= mine or mine <= w)) for w in ws):
            steps += order
    if not steps:
        return None
    by_key = {_key(b["name"]): b for b in inst.bosses}
    missing = []
    for i, s in enumerate(steps):
        cands = [s.get("boss") or ""] + list(s.get("npcs") or [])
        b = next((by_key[_key(n)] for n in cands if _key(n) in by_key), None)
        if b is None:  # (loosely: one name inside the other, "Grand Crusader Dathrohan" / "Balnazzar")
            b = next((bb for n in cands for k, bb in by_key.items() if _key(n) and (_key(n) in k or k in _key(n))), None)
        if b is None and server is not None:
            # (not an encounter: a rare or an optional one, spawned there under that name)
            npcs = server["npcs"]
            keys = {_key(n) for n in cands}
            spot = next(((e, x, y, z) for e, x, y, z in server["spawns"].get(inst.map_id, [])
                         if _key(npcs.get(e, ("",))[0]) in keys), None)
            if spot is not None:
                e, x, y, z = spot
                b = {"name": npcs[e][0], "npc": e, "x": x, "y": y, "z": z, "enc": [], "index": None,
                     "spawns": sum(1 for s2 in server["spawns"][inst.map_id] if s2[0] == e)}
                inst.bosses.append(b)
                by_key[_key(b["name"])] = b
        if b is None:
            missing.append(s.get("boss") or "?")
            continue
        if b.get("order") is None:
            b["order"], b["optional"] = i, bool(s.get("optional"))
    # an elite there that's neither in the order nor an encounter (Lord Victor Nefarius, who
    # starts Nefarian's fight): shown, but not a stop of the boss route
    for b in inst.bosses:
        if b.get("order") is None and not b["enc"]:
            b["optional"] = True
    inst.bosses.sort(key=lambda b: (b.get("order") is None, b.get("order") or 0,
                                    b["index"] if b["index"] is not None else 1e9))
    return missing


ENTRANCES = Path(__file__).resolve().parents[2] / "overrides" / "instance_entrances.json"
TERRAIN_SKIP = {2720, 2921, 3002}  # The Searing Basin (its one boss "Testwerk"), a second Naxxramas (one
# event boss), the Half-Pint Tavern (unannounced: no place in the world yet)


def terrain_instances(cd: ClientData, built_maps: set, log=print) -> list:
    """Dungeons and raids with no walk network here (WoW Forever's own: no spawns or entrances
    in the server data or the client), but with terrain and minimap tiles: their map in the
    addon (the tiles) and their bosses (names, DungeonEncounter IDs and order; no spots).
    Entrances from overrides/instance_entrances.json (learned in game or researched):
    {map id: [[continent, x, y], ...]}. Each: dict(map, name, raid, tiles, bosses, entrances)."""
    import json

    known = {}
    if ENTRANCES.exists():
        known = {int(k): v for k, v in json.loads(ENTRANCES.read_text(encoding="utf-8")).items()}
    enc = defaultdict(list)
    for r in cd.table("DungeonEncounter"):
        enc[r["MapID"]].append(r)
    out = []
    for r in instance_maps(cd):
        mid = r["ID"]
        if mid in built_maps or mid in SKIP_MAPS or mid in TERRAIN_SKIP or not enc.get(mid):
            continue
        wdt_fid = r["WdtFileDataID"]
        if not wdt_fid or not cd.casc.has(wdt_fid):
            continue
        wdt = adt.parse_wdt(cd.casc.read(wdt_fid))
        tiles = sorted((tx * 64 + ty, t.minimap) for (tx, ty), t in wdt.tiles.items() if t.minimap)
        if not tiles:
            continue
        bosses, seen = [], set()
        for e in sorted(enc[mid], key=lambda e: (e["F4"] if e["F3"] in (0, 201) else 1000, e["ID"])):
            if e["Name_lang"] in seen:
                continue
            seen.add(e["Name_lang"])
            bosses.append({"name": e["Name_lang"], "enc": sorted(x["ID"] for x in enc[mid] if x["Name_lang"] == e["Name_lang"])})
        out.append({"map": mid, "name": r["MapName_lang"], "raid": r["InstanceType"] == 2, "tiles": tiles,
                    "bosses": bosses, "entrances": known.get(mid, [])})
        log(f"  {r['MapName_lang']} ({mid} -> {level_id(mid)}): its map only, {len(bosses)} bosses (no spots), "
            f"{len(known.get(mid, []))} entrance(s) known")
    return out


def instances_lua(cd: ClientData, built: list, log=print) -> str:
    """Data/Instances.lua: each instance's level (grid, roads, heights), entrances as portals
    (ns.Transports) and its bosses."""
    k = walknet.TILE / CELL
    out = [f"-- GENERATED by `agps gen-addon-data` from client {cd.casc.version}. Do not edit by hand.",
           "-- Dungeons and raids (app/azerothgps/instances.py): each instance map is a level of its own,",
           f"-- {LEVEL_BASE} + its MapID, in its own world coordinates (like Undercity's, ns.CityLevels: base",
           "-- is the instance's map, instance = true). ns.Terrain[level]: its floors (0 open, 1 water to swim,",
           "-- 2 closed; short runs of up to 15, long ones' lengths in 2 digits, rows split by slashes);",
           "-- ns.Roads[level]: its roads (a road's points packed: from its first node, each move in whole",
           "-- yards, caves.pack_points); ns.RoadDrops[level]: one-way drops off ledges (yards fallen);",
           "-- ns.CityHeights[level]: each cell's floor height, runs of (height character, length);",
           "-- ns.Instances[level]: name, map, raid, entrances { cont, x, y, inside x, y, z }, bosses { name, npc,",
           "-- x, y, z, enc = DungeonEncounter IDs, order = the usual kill order when known }. Each entrance",
           "-- is a portal in ns.Transports (continent end, instance end).",
           "local _, ns = ...",
           "ns.CityLevels = ns.CityLevels or {}",
           "ns.Instances = ns.Instances or {}",
           "ns.CityHeights = ns.CityHeights or {}",
           "ns.RoadDrops = ns.RoadDrops or {}",
           "ns.Transports = ns.Transports or {}"]
    zcache: dict = {}
    for inst, u in built:
        L = inst.level
        out.append(f"-- {inst.name} (map {inst.map_id}, {'raid' if inst.raid else 'dungeon'})")
        out.append(f"ns.CityLevels[{L}] = {{ base = {inst.map_id}, name = {_lua_str(inst.name)}, instance = true"
                   f"{', raid = true' if inst.raid else ''} }}")
        ents = ", ".join(f"{{ {c}, {x:.1f}, {y:.1f}, {ix:.1f}, {iy:.1f}, {iz:.1f} }}" for c, x, y, _z, ix, iy, iz, _n in inst.entrances)
        bl = []
        for b in inst.bosses:
            if b["x"] is None:
                continue
            enc = ",".join(str(e) for e in b["enc"])
            order = f", order = {b['order'] + 1}" if b.get("order") is not None else ""
            order += ", optional = true" if b.get("optional") else ""
            bl.append(f"    {{ {_lua_str(b['name'])}, {b['npc']}, {b['x']:.1f}, {b['y']:.1f}, {b['z']:.1f}, enc = {{ {enc} }}{order} }},")
        out.append(f"ns.Instances[{L}] = {{ name = {_lua_str(inst.name)}, map = {inst.map_id}, raid = {str(inst.raid).lower()},")
        out.append(f"  entrances = {{ {ents} }},")
        if inst.corpse and inst.entrances and inst.entrances[0][0] not in (0, 1):
            # (in through another instance: its icon on the continent where the ghost's way in is)
            c, x, y = inst.corpse
            out.append(f"  ghost = {{ {c}, {x:.1f}, {y:.1f} }},")
        out.append("  bosses = {")
        out += bl
        out.append("  } }")
        cells = u["overlay"]
        r0, r1, c0, c1 = _crop(cells)
        sub = cells[r0:r1, c0:c1]
        tx0, ty0 = u["tx0"] + c0 / k, u["ty0"] + r0 / k
        out.append(f"ns.Terrain[{L}] = {{ tx0 = {tx0:.6f}, ty0 = {ty0:.6f}, cell = {CELL:.0f}, w = {sub.shape[1]}, "
                   f"h = {sub.shape[0]}, short = {SHORT}, long = 2, slack = 0,")
        out.append('  rows = "' + "/".join(encode_row(row, SHORT, 2) for row in sub) + '" }')
        # (heights only on and near the open floor: the rest is walls and rock, and runs of
        # "no floor" keep the rows short)
        from scipy import ndimage
        near = ndimage.binary_dilation(sub != 2, iterations=2)
        top = np.where(near, u["top"][r0:r1, c0:c1], -1e4)
        has = top > -1e3
        z0 = float(math.floor(top[has].min())) if has.any() else 0.0
        step = max(HEIGHT_STEP, math.ceil((float(top[has].max()) - z0) / 77) if has.any() else HEIGHT_STEP)
        out.append(f"ns.CityHeights[{L}] = {{ z0 = {z0:.0f}, step = {step:.0f}, runs = true, rows = {{")
        for row in top:
            out.append(f'  "{height_runs("".join(height_char(z, z0, step) for z in row))}",')
        out.append("} }")
        nodes, edges, drops, zs = instance_roads(u)
        from .roads.lifts import add_instance_lifts, wait_yards

        lifts = add_instance_lifts(inst.map_id, nodes, edges, zs, log)  # (Gnomeregan's: roads/lifts.py)
        out.append(f"ns.Roads[{L}] = {{")
        out.append("  n = {" + ",".join(f"{x:.0f},{y:.0f}" for x, y in nodes) + "},")
        if zs:  # (each node's height: the floors over floors are told apart by it)
            out.append("  z = {" + ",".join(f"{z:.0f}" for z in zs) + "},")
        out.append("  e = {")
        from .caves import pack_points
        for i, (a, b, pts) in enumerate(edges):
            pts = [tuple(int(round(v)) for v in nodes[a])] + [(int(round(x)), int(round(y))) for x, y in pts[1:-1]] + \
                  [tuple(int(round(v)) for v in nodes[b])]
            pts = [q for j, q in enumerate(pts) if j == 0 or q != pts[j - 1]] if len(pts) > 2 else pts
            if len(pts) == 1:
                pts = pts * 2
            length = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))
            if i in lifts:
                length += wait_yards()  # (its wait and ride: Router.SOURCE_LIFT, 5)
            src = 3 if i in drops else 5 if i in lifts else 0
            out.append(f"    {{{a + 1},{b + 1},{length:.0f},{src},\"{pack_points(pts)}\"}},")
        out.append("  },")
        out.append("}")
        out.append(f"ns.RoadDrops[{L}] = {{ " + ", ".join(f"[{i + 1}] = {h}" for i, h in sorted(drops.items())) + " }")
        names = {i.level: i.name for i, _u in built}
        for c, x, y, _z, ix, iy, iz, _n in inst.entrances:
            place = names.get(c) if c >= LEVEL_BASE else (zone_name(cd, c, x, y, zcache) or inst.name)
            if c >= LEVEL_BASE and c not in names:
                continue  # (from an instance not built: no way in)
            out.append(f"ns.Transports[#ns.Transports + 1] = {{ {c}, {x:.1f}, {y:.1f}, {L}, {ix:.1f}, {iy:.1f}, "
                       f"{PORTAL_SECONDS}, \"portal\", {_lua_str(place)}, {_lua_str(inst.name)}, \"portal\", iz = {iz:.1f} }}")
    # dungeons and raids with their map only (WoW Forever's own): the terrain's minimap tiles,
    # their bosses without spots, entrances when known
    out.append("-- dungeons and raids with their map only (no walk network): ns.MinimapTiles[map id], bosses")
    out.append("-- without spots (kills still count), ns.Instances[level].terrain = true")
    out.append("ns.MinimapTiles = ns.MinimapTiles or {}")
    for t in terrain_instances(cd, {inst.map_id for inst, _u in built}, log=log):
        L = level_id(t["map"])
        out.append(f"-- {t['name']} (map {t['map']}, {'raid' if t['raid'] else 'dungeon'}, its map only)")
        out.append(f"ns.CityLevels[{L}] = {{ base = {t['map']}, name = {_lua_str(t['name'])}, instance = true, terrain = true"
                   f"{', raid = true' if t['raid'] else ''} }}")
        ents = ", ".join(f"{{ {c}, {x:.1f}, {y:.1f} }}" for c, x, y in t["entrances"])
        bl = ", ".join(f"{{ {_lua_str(b['name'])}, 0, enc = {{ {','.join(str(e) for e in b['enc'])} }}, order = {i + 1} }}"
                       for i, b in enumerate(t["bosses"]))
        out.append(f"ns.Instances[{L}] = {{ name = {_lua_str(t['name'])}, map = {t['map']}, raid = {str(t['raid']).lower()}, "
                   f"terrain = true, entrances = {{ {ents} }}, bosses = {{ {bl} }} }}")
        out.append(f"ns.MinimapTiles[{t['map']}] = {{ " + " ".join(f"[{k}]={v}," for k, v in t["tiles"]) + " }")
    # the game's own minimap art of each instance's models (its map in the addon; the floors'
    # outline where there's none), like the buildings' in Interiors.lua, keyed by its map id
    out.append("-- ns.WMOs / ns.Interiors[map id]: the instances' interior maps (Interiors.lua's format)")
    out.append("ns.WMOs = ns.WMOs or {}")
    out.append("ns.Interiors = ns.Interiors or {}")
    art = I.build_places(cd, ((inst.map_id, u["placements"]) for inst, u in built), log=log)
    out.extend(I.places_lua(art))
    return "\n".join(out) + "\n"


# --- build all, render, check ----------------------------------------------------------


def build_all(cd: ClientData, data_dir, log=print, only=None, report=None) -> list:
    """Every instance with an entrance: (Instance, walk network). The rest go in `report`
    with the reason."""
    server = server_data(Path(data_dir), log)
    orders = boss_order()
    out = []
    for inst in load_instances(cd, server, only):
        missing = order_bosses(inst, orders, server)
        why = None
        if not inst.entrances:
            why = "no entrance (no teleport into it in the server's data, no ghost entrance in the client's)"
        u = None
        if why is None:
            try:
                u = build_instance(cd, inst, server, log=lambda *a: None)
            except Exception as ex:  # (a model this reader can't take)
                why = f"unreadable model ({ex!r})"
            if u is None and why is None:
                why = "; ".join(inst.notes) or "no walk network"
        if u is not None:
            keep_reached(u, inst, log=lambda *a: None)
            # floors over floors: the roads in layers, each node's height (layers.py)
            from . import layers
            seeds = [(e[4], e[5], e[6]) for e in inst.entrances] +                 [(b["x"], b["y"], b["z"]) for b in inst.bosses if b["x"] is not None]
            lay = layers.build(u, seeds, prune=PRUNE, fill=FILL, log=lambda *a: None)
            keep_reached({"graph": lay["graph"]}, inst, log=lambda *a: None)
            if lay["graph"].edges:
                u["layered"] = lay
            if u["graph"].total_length() < MIN_ROAD:
                why, u = f"only {u['graph'].total_length():.0f} yd of road", None
        if u is None:
            log(f"  {inst.name} ({inst.map_id}): skipped: {why}")
            if report is not None:
                report.append((inst, "skipped", why))
            continue
        placed = [b for b in inst.bosses if b["x"] is not None]
        off = [b["name"] for b in placed if not _on_floor(u, b)]
        g = u["graph"]
        text = (f"{g.total_length():.0f} yd of road, {len(g.nodes)} nodes, grid {u['W']}x{u['H']}, "
                f"{len(inst.entrances)} entrance(s), {len(placed)} bosses placed"
                + (f" ({', '.join(b['name'] for b in inst.bosses if b['x'] is None)} with no spawn)" if len(placed) < len(inst.bosses) else "")
                + (f", off the floors: {', '.join(off)}" if off else "")
                + (", boss order: the client's encounter index" if missing is None else "")
                + (f", in the order but not found here: {', '.join(missing)}" if missing else "")
                + (f", not in the order: {', '.join(b['name'] for b in inst.bosses if b.get('order') is None)}"
                   if missing is not None and any(b.get("order") is None for b in inst.bosses) else ""))
        log(f"  {inst.name} ({inst.map_id} -> {inst.level}): {text}")
        if report is not None:
            report.append((inst, "covered", text))
        out.append((inst, u))
    return out


def _on_floor(u: dict, b: dict, reach: float = 8.0) -> bool:
    """Whether a boss stands on (or within `reach` of) the grid's open floor."""
    r, c = u["world_to_px"](b["x"], b["y"])
    R = int(reach / CELL)
    sub = u["overlay"][max(r - R, 0):r + R + 1, max(c - R, 0):c + R + 1]
    return bool(sub.size) and bool((sub != 2).any())


def render_debug(inst: Instance, u: dict, out_dir, scale: int = 3) -> None:
    """An instance's grid and roads as a PNG (and the grid as text): floors shaded by height,
    water blue, closed cells dark; roads red, stairs blue, drops magenta; where you appear
    green, bosses as yellow dots with their names; a line every 100 yards."""
    from PIL import Image, ImageDraw

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cells, top = u["overlay"], u["top"]
    H, W = cells.shape
    open_ = cells == 0
    zs = top[(cells != 2) & (top > -1e3)]
    lo, hi = (float(zs.min()), float(zs.max())) if zs.size else (0.0, 1.0)
    img = np.full((H, W, 3), 40, np.uint8)
    shade = np.clip((top - lo) / max(hi - lo, 1e-6), 0, 1)
    img[open_] = np.stack([90 + 160 * shade, 90 + 160 * shade, 90 + 120 * shade], -1)[open_].astype(np.uint8)
    img[cells == 1] = (70, 130, 230)
    im = Image.fromarray(img).resize((W * scale, H * scale), Image.NEAREST)
    dr = ImageDraw.Draw(im)

    def px(x, y):
        c, r = u["cellxy"](x, y)
        return c * scale, r * scale

    x_hi, y_hi = u["px_to_world"](0, 0)
    x_lo, y_lo = u["px_to_world"](H - 1, W - 1)
    for gx in range(int(math.ceil(x_lo / 100)) * 100, int(x_hi) + 1, 100):
        a, b = px(gx, y_hi), px(gx, y_lo)
        dr.line([a, b], fill=(110, 110, 110), width=1)
        dr.text((2, a[1] + 1), f"x {gx}", fill=(200, 200, 200))
    for gy in range(int(math.ceil(y_lo / 100)) * 100, int(y_hi) + 1, 100):
        a, b = px(x_hi, gy), px(x_lo, gy)
        dr.line([a, b], fill=(110, 110, 110), width=1)
        dr.text((a[0] + 1, 2), f"y {gy}", fill=(200, 200, 200))
    g = u["graph"]
    for e in g.edges.values():
        col = {"stair": (0, 60, 255)}.get(e.source, (220, 0, 0))
        if e.source.startswith("drop:"):
            col = (255, 0, 255)
        dr.line([px(*q) for q in e.pts], fill=col, width=2)
    for e in inst.entrances:
        a, b = px(e[4], e[5])
        dr.ellipse([a - 7, b - 7, a + 7, b + 7], outline=(0, 230, 0), width=3)
        dr.text((a + 8, b - 6), "entrance", fill=(0, 255, 0))
    for i, b in enumerate(inst.bosses):
        if b["x"] is None:
            continue
        a, c = px(b["x"], b["y"])
        dr.ellipse([a - 5, c - 5, a + 5, c + 5], fill=(255, 220, 0), outline=(0, 0, 0))
        label = (f"{b['order'] + 1}. " if b.get("order") is not None else "") + b["name"]
        dr.text((a + 7, c - 6), label, fill=(255, 255, 160))
    name = f"{inst.map_id}_{re.sub(r'[^A-Za-z0-9]+', '_', inst.name)}"
    im.save(out_dir / f"{name}.png")
    rows = ["".join(".~#"[v] for v in row) for row in cells]  # (open, water, closed)
    (out_dir / f"{name}.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


JUMP_MAX = 8.0  # yards: a jump bigger than this between levels is flagged
LAST_MAX = 25.0  # yards: a last leg off the roads longer than this is flagged


def check_routes(built: list, log=print, text: str | None = None) -> list:
    """Routes (the addon's own, under lupa, over Data/Instances.lua as written, or `text`)
    from each entrance to every boss, and the 3D walk over the floors (capitals.walk_3d): "!"
    marks a jump between levels, a long last leg, or yards off the roads through closed cells."""
    from .capitals import walk_3d
    from .routecheck import _pts
    from .paths import ADDON_DIR

    import lupa

    lua = lupa.LuaRuntime()
    lua.execute('issecretvalue = nil\nCreateFrame = function() error("no frames here") end\n'
                "GetTime = function() return 0 end")
    ns = lua.table()
    ns.IsSecret = lua.eval("function(v) return false end")
    ns.db = lua.eval("{}")
    ns.Terrain = lua.eval("{}")
    ns.Roads = lua.eval("{}")
    loader = lua.eval("function(src, name) return assert(load(src, '@' .. name)) end")
    for name in ("Geo.lua", "Data/Instances.lua", "Passability.lua", "Router.lua"):
        src = text if (text is not None and name == "Data/Instances.lua") else (ADDON_DIR / name).read_text(encoding="utf-8")
        loader(src, name)("AzerothGPS", ns)
    ns.Router.SYNC_WALKS = True
    ns.Router.WARM = False
    R, P = ns.Router, ns.Passability
    out = []
    for inst, u in built:
        L = inst.level
        if not inst.entrances:
            continue
        for b in inst.bosses:
            if b["x"] is None:
                continue
            # (from the nearest way in: an instance of wings, the Scarlet Monastery's, has one each)
            e = min(inst.entrances, key=lambda e: math.hypot(e[4] - b["x"], e[5] - b["y"]))
            R.Reset()
            r = R.Route(L, e[4], e[5], b["x"], b["y"], lua.table(offroad=False))
            if not r or not r.pts:
                out.append(f"! {inst.name}: {b['name']}: no route")
                log(out[-1])
                continue
            pts, kinds = _pts(r)
            road = sum(math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) for i, kd in enumerate(kinds) if kd == 0)
            last = math.hypot(pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1])
            jump, where = walk_3d(u, pts, kinds)
            closed = 0.0
            for i, kd in enumerate(kinds):
                if kd == 1:
                    (x1, y1), (x2, y2) = pts[i], pts[i + 1]
                    d = math.hypot(x2 - x1, y2 - y1)
                    n = max(1, int(d))
                    closed += sum(d / (n + 1) for s in range(n + 1)
                                  if P.At(L, x1 + (x2 - x1) * s / n, y1 + (y2 - y1) * s / n) == 2)
            bad = jump > JUMP_MAX or last > LAST_MAX or closed > 10
            out.append(f"{'!' if bad else ' '} {inst.name}: {b['name']}: {r.length:.0f} yd, "
                       f"{road / max(r.length, 1):.0%} on roads, last leg {last:.0f} yd, {closed:.0f} yd off the roads "
                       f"through closed cells, 3D jump {jump:.0f} yd" + (f" ({where[0]} at {where[1]}, {where[2]})" if where else ""))
            log(out[-1])
    return out


def check_roads_3d(built: list) -> list:
    """Every road of each instance walked in 3D over its floors (capitals.walk_3d), from each end at its
    node's height where the roads have heights (floors over floors): "!" marks a jump between levels over
    JUMP_MAX (a gap, a join between floors, a road on no floor at its end's height); drops may go down.
    Rows of text."""
    from .capitals import walk_3d
    rows = []
    for inst, u in built:
        nodes, edges, drops, zs = instance_roads(u)
        # (each road's source, in the same order: a straight 2-point "stair" is a join across a gap between
        # pieces of floor, layers.py's GAP_MAX: where the floors found miss a way, maybe a lift or a door)
        src = [e.source for e in (u["layered"]["graph"] if u.get("layered") else u["graph"]).edges.values()]
        for i, (a, b, pts) in enumerate(edges):
            P = [tuple(q[:2]) for q in pts]
            if len(P) < 2:
                continue
            kinds = [4 if i in drops else 0] * (len(P) - 1)
            jump, where = walk_3d(u, P, kinds, z0=zs[a] if zs else None)
            if zs and i not in drops:  # (and back from the other end, at its height)
                j2, w2 = walk_3d(u, P[::-1], kinds, z0=zs[b])
                if j2 > jump:
                    jump, where = j2, w2
            length = sum(math.hypot(P[k + 1][0] - P[k][0], P[k + 1][1] - P[k][1]) for k in range(len(P) - 1))
            hz = (f" {zs[a]:.0f} to {zs[b]:.0f}" if zs else "")
            kind = "gap join" if len(P) == 2 and i < len(src) and src[i] == "stair" else (src[i] if i < len(src) else "?")
            rows.append(f"{'!' if jump > JUMP_MAX else ' '} {inst.name}: road {i} {kind}{' drop' if i in drops else ''} "
                        f"{length:.0f} yd from ({P[0][0]:.0f}, {P[0][1]:.0f}) to ({P[-1][0]:.0f}, {P[-1][1]:.0f}){hz}, "
                        f"3D jump {jump:.0f} yd" + (f" ({where[0]} at {where[1]}, {where[2]})" if where else ""))
    return rows


# --- entrances learned in game ------------------------------------------------------------


def merge_entrances(found: dict, log=print) -> int:
    """Add dungeons' ways in (learned in game: {map id: [[continent, x, y], ...]}) to
    overrides/instance_entrances.json, one per spot (within 40 yd of a known one: the same)."""
    doc = {}
    if ENTRANCES.exists():
        doc = {int(k): v for k, v in json.loads(ENTRANCES.read_text(encoding="utf-8")).items()}
    added = 0
    for mid, spots in found.items():
        have = doc.setdefault(int(mid), [])
        for c, x, y in spots:
            if any(h[0] == c and math.hypot(h[1] - x, h[2] - y) <= 40 for h in have):
                continue
            have.append([int(c), round(float(x), 1), round(float(y), 1)])
            added += 1
            log(f"  map {mid}: a way in at continent {c} ({x:.0f}, {y:.0f})")
    if added:
        ENTRANCES.parent.mkdir(parents=True, exist_ok=True)
        ENTRANCES.write_text(json.dumps({str(k): v for k, v in sorted(doc.items())}, indent=1), encoding="utf-8")
    return added


def parse_shared_entrances(text: str) -> dict:
    """The "E map-id continent x,y" lines of the share page's text (Feedback.RoadsText)."""
    out: dict = defaultdict(list)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[0] != "E":
            continue
        try:
            mid, c = int(parts[1]), int(parts[2])
            x, y = (float(v) for v in parts[3].split(","))
        except ValueError:
            continue
        out[mid].append((c, x, y))
    return dict(out)


def saved_entrances(savedvars: dict) -> dict:
    """The ways in the addon learned (AzerothGPSDB.entrances: {map id: {{cont, x, y, n}}})."""
    out: dict = defaultdict(list)
    for mid, spots in (savedvars.get("AzerothGPSDB", {}).get("entrances") or {}).items():
        for s in (spots.values() if isinstance(spots, dict) else spots):
            if isinstance(s, dict):
                s = [s.get(1), s.get(2), s.get(3)]
            if s and len(s) >= 3 and None not in s[:3]:
                out[int(mid)].append((int(s[0]), float(s[1]), float(s[2])))
    return dict(out)


# --- maps you pass through (not dungeons) ------------------------------------------------------

# Maps of their own the game puts you on between places: their map (the game's minimap art of their
# models) and name, no roads, entrances or bosses. The Deeprun Tram (asked, 2026-09-30: its map was blank).
TRANSIT_MAPS = (369,)


def transit_lua(cd: ClientData, log=print) -> str:
    """Data/Transit.lua: each transit map a level like an instance's (level_id, `instance` and `transit`:
    the map shows it as a dungeon's, its art; no dungeon features), and its models' interior maps
    (ns.WMOs / ns.Interiors[map id], Interiors.lua's format)."""
    out = [f"-- GENERATED by `agps transit --write` from client {cd.casc.version}. Do not edit by hand.",
           "-- Maps the game puts you on between places (the Deeprun Tram): shown like a dungeon's, by their art.",
           "local _, ns = ...",
           "ns.CityLevels = ns.CityLevels or {}",
           "ns.Instances = ns.Instances or {}",
           "ns.WMOs = ns.WMOs or {}",
           "ns.Interiors = ns.Interiors or {}"]
    by_map = []
    for mid in TRANSIT_MAPS:
        m = next(r for r in cd.table("Map") if r["ID"] == mid)
        name, lvl = m["MapName_lang"], level_id(mid)
        pl = wdt_placements(cd, mid)
        if not pl:
            log(f"  {name} ({mid}): no model in its WDT: left out")
            continue
        out.append(f"ns.CityLevels[{lvl}] = {{ base = {mid}, name = {_lua_str(name)}, instance = true, transit = true }}")
        out.append(f"ns.Instances[{lvl}] = {{ name = {_lua_str(name)}, map = {mid}, raid = false, transit = true, "
                   "entrances = {}, bosses = {} }")
        by_map.append((mid, pl))
        log(f"  {name} ({mid} -> {lvl}): {len(pl)} model(s)")
    art = I.build_places(cd, by_map, log=log)
    out.extend(I.places_lua(art))
    return "\n".join(out) + "\n"

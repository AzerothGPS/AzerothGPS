"""Import the roads drawn (or erased) in game (Draw a road / Erase a road) into overrides/*.geojson."""

from __future__ import annotations

import json
from pathlib import Path

from ..savedvars.parser import load_savedvariables

SV_NAME = "AzerothGPS.lua"
WALL_FLOOR_Z = 8.0  # Passability.WALL_FLOOR_Z: a wall eraser takes out the walls drawn within this of its height


def floor_of(t: dict) -> dict:
    """A drawn edit's floor, where floors lie over each other (the addon's Record `z`, `indoors`,
    `down`: the player's height, whether indoors, and down in a cave or under a capital's floor), as
    feature properties: only those it has."""
    out = {}
    if t.get("z") is not None:
        out["z"] = round(float(t["z"]), 1)
    if t.get("indoors") is not None:
        out["indoors"] = bool(t["indoors"])
    if t.get("down"):
        out["down"] = True
    return out


class WallLine(list):
    """A wall's points ([x, y] pairs), with its floor's height `z` when it has one."""
    z: float | None = None


def read_tracks(wtf_account_dir: Path) -> list[dict]:
    tracks = []
    for f in sorted(Path(wtf_account_dir).glob(f"*/SavedVariables/{SV_NAME}")):
        db = load_savedvariables(f).get("AzerothGPSDB") or {}
        raw = db.get("tracks") or []
        for t in raw if isinstance(raw, list) else []:
            pts = t.get("pts") or []
            if len(pts) < 4:
                continue
            tracks.append({
                "continent": int(t.get("continent", -1)),
                "op": t.get("op", "add"),
                "zone": t.get("zone", "?"),
                "time": int(t.get("time", 0)),
                "area": bool(t.get("area")),
                "coords": [[pts[i], pts[i + 1]] for i in range(0, len(pts) - 1, 2)],
                **floor_of(t),
            })
    return tracks


def parse_shared(text: str) -> list[dict]:
    """Roads from the share page's "Copy road data" text (Feedback.RoadsText), as tracks: "R op continent
    time [z=height] [indoors=1|0] [down=1] x,y x,y ..."."""
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6 or parts[0] != "R" or parts[1] not in ("add", "remove", "area", "wall", "unwall", "unwallarea"):
            continue
        fl, rest = {}, parts[4:]
        while rest and "=" in rest[0]:
            k, _, v = rest.pop(0).partition("=")
            fl[k] = v
        try:
            cont, t = int(parts[2]), int(parts[3])
            coords = [[float(a) for a in p.split(",")] for p in rest]
            floor = floor_of({"z": float(fl["z"]) if "z" in fl else None,
                              "indoors": (fl["indoors"] == "1") if "indoors" in fl else None,
                              "down": fl.get("down") == "1"})
        except ValueError:
            continue
        if len(coords) < 2 or any(len(c) != 2 for c in coords):
            continue
        op = {"area": "remove", "unwallarea": "unwall"}.get(parts[1], parts[1])
        out.append({"continent": cont, "op": op, "area": parts[1] in ("area", "unwallarea"),
                    "zone": "shared", "time": t, "coords": coords, **floor})
    return out


def import_shared(text: str, overrides_dir: Path, per_continent: dict | None = None) -> int:
    """Add the shared roads not in the overrides yet (by continent and time)."""
    added = 0
    by_cont: dict[int, list[dict]] = {}
    for t in parse_shared(text):
        by_cont.setdefault(t["continent"], []).append(t)
    for cont, tracks in by_cont.items():
        path = overrides_path(overrides_dir, cont)
        doc = load_overrides(path)
        seen = {f["properties"].get("time") for f in doc["features"] if f["properties"].get("source") == "recorded"}
        new = 0
        for t in tracks:
            if t["time"] in seen:
                continue
            seen.add(t["time"])
            doc["features"].append({
                "type": "Feature",
                "properties": {"op": t["op"], "source": "recorded", "zone": t["zone"], "time": t["time"], "trim": True,
                               **({"area": True} if t["area"] else {}), **floor_of(t)},
                "geometry": {"type": "LineString", "coordinates": t["coords"]},
            })
            new += 1
        if new:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
            if per_continent is not None:
                per_continent[cont] = per_continent.get(cont, 0) + new
        added += new
    return added


def walls(overrides_dir: Path) -> dict[int, list[list[float]]]:
    """The walls drawn in game per continent (or city level), as the addon has them
    (Passability.WallLines): each "wall" in order, an "unwall" taking out the walls near it
    (or inside it, drawn as a loop) on its floor (both drawn within WALL_FLOOR_Z of each other's
    height, when both have one). { continent: [ WallLine([[x, y], ...]), ... ] }"""
    import math

    def in_loop(poly, x, y):
        inside, j = False, len(poly) - 1
        for i in range(len(poly)):
            (xi, yi), (xj, yj) = poly[i], poly[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def near(line, x, y, r=12.0):
        for (ax, ay), (bx, by) in zip(line, line[1:]):
            vx, vy = bx - ax, by - ay
            L2 = vx * vx + vy * vy
            t = max(0.0, min(1.0, ((x - ax) * vx + (y - ay) * vy) / L2)) if L2 > 0 else 0.0
            if math.hypot(ax + vx * t - x, ay + vy * t - y) <= r:
                return True
        return False

    out: dict[int, list] = {}
    for f in sorted(Path(overrides_dir).glob("roads_*.geojson")):
        try:
            cont = int(f.stem.split("_", 1)[1])
        except ValueError:
            continue
        ws: list = []
        for feat in load_overrides(f)["features"]:
            props = feat.get("properties", {})
            line = feat["geometry"]["coordinates"]
            if props.get("op") == "wall":
                w = WallLine(line)
                w.z = props.get("z")
                ws.append(w)
            elif props.get("op") == "unwall":
                area, z = props.get("area"), props.get("z")
                ws = [w for w in ws if not (
                    (z is None or w.z is None or abs(w.z - z) <= WALL_FLOOR_Z)
                    and any(in_loop(line, x, y) if area else near(line, x, y) for x, y in w))]
        if ws:
            out[cont] = ws
    return out


def wall_opens(overrides_dir: Path) -> dict[int, list[dict]]:
    """The wall erasers drawn in game per continent: they also open the terrain's blocked
    ground under them (Passability.OpenAreas). { continent: [ {"pts": [[x, y], ...], "area": bool} ] }"""
    out: dict[int, list] = {}
    for f in sorted(Path(overrides_dir).glob("roads_*.geojson")):
        try:
            cont = int(f.stem.split("_", 1)[1])
        except ValueError:
            continue
        for feat in load_overrides(f)["features"]:
            props = feat.get("properties", {})
            if props.get("op") == "unwall":
                out.setdefault(cont, []).append({"pts": feat["geometry"]["coordinates"], "area": bool(props.get("area"))})
    return out


def dropped_times(overrides_dir: Path) -> set[int]:
    """Drawn roads set aside on purpose (overrides/dropped_tracks.json: {"times": [...]}): never imported,
    and listed as shipped so the addon forgets them (e.g. Undercity strokes drawn before they had a floor)."""
    f = Path(overrides_dir) / "dropped_tracks.json"
    return set(json.loads(f.read_text(encoding="utf-8")).get("times", [])) if f.exists() else set()


def shipped_times(overrides_dir: Path) -> list[int]:
    """The times of the drawn roads the overrides have (the addon drops those from its own list), and
    the dropped ones."""
    out = set(dropped_times(overrides_dir))
    for f in sorted(Path(overrides_dir).glob("roads_*.geojson")):
        for feat in load_overrides(f)["features"]:
            props = feat.get("properties", {})
            if props.get("source") == "recorded" and props.get("time"):
                out.add(int(props["time"]))
    return sorted(out)


def overrides_path(overrides_dir: Path, continent: int) -> Path:
    return Path(overrides_dir) / f"roads_{continent}.geojson"


def load_overrides(path: Path) -> dict:
    if Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return {"type": "FeatureCollection", "features": []}


def import_tracks(wtf_account_dir: Path, overrides_dir: Path, per_continent: dict | None = None) -> int:
    """Append tracks not yet imported (keyed by continent+time) to the GeoJSON overrides.
    `per_continent` (if given) gets the count added per continent."""
    added = 0
    by_cont: dict[int, list[dict]] = {}
    dropped = dropped_times(overrides_dir)
    for t in read_tracks(wtf_account_dir):
        if t["time"] in dropped:
            continue
        by_cont.setdefault(t["continent"], []).append(t)
    for cont, tracks in by_cont.items():
        path = overrides_path(overrides_dir, cont)
        doc = load_overrides(path)
        new = 0
        seen = {f["properties"].get("time") for f in doc["features"] if f["properties"].get("source") == "recorded"}
        for t in tracks:
            if t["time"] in seen:
                continue
            seen.add(t["time"])
            if per_continent is not None:
                per_continent[cont] = per_continent.get(cont, 0) + 1
            doc["features"].append({
                "type": "Feature",
                "properties": {"op": t["op"], "source": "recorded", "zone": t["zone"], "time": t["time"], "trim": True,
                               **({"area": True} if t.get("area") else {}), **floor_of(t)},
                "geometry": {"type": "LineString", "coordinates": t["coords"]},
            })
            added += 1
            new += 1
        if new:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return added

"""Extract small lookup tables the runtime needs into data/ as JSON."""

from __future__ import annotations

import json
import time
from pathlib import Path

from .spike import ClientData


def build_uimaps(cd: ClientData) -> list[dict]:
    """Every uiMap with its full-map world bounds (when it has one)."""
    full = {}
    for r in cd.table("UiMapAssignment"):
        if r["UiMin"] == [0.0, 0.0] and r["UiMax"] == [1.0, 1.0]:
            cur = full.get(r["UiMapID"])
            if cur is None or r["OrderIndex"] < cur["OrderIndex"]:
                full[r["UiMapID"]] = r
    out = []
    for m in cd.table("UiMap"):
        a = full.get(m["ID"])
        entry = {"id": m["ID"], "name": m["Name_lang"], "parent": m["ParentUiMapID"], "type": m["Type"]}
        if a is not None:
            minx, miny, _, maxx, maxy, _ = a["Region"]
            entry.update(continent=a["MapID"], areaId=a["AreaID"], minX=minx, minY=miny, maxX=maxx, maxY=maxy)
        out.append(entry)
    return sorted(out, key=lambda e: e["id"])


def extract_tables(cd: ClientData, data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "uimaps.json"
    doc = {"build": cd.casc.version, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "maps": build_uimaps(cd)}
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path

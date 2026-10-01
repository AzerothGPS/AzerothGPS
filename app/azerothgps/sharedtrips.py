"""Faster trips players shared ("Copy Map Data...", its "Routes": the T lines, Feedback.RoadsText; kept in
game with the option Share faster trips): `agps import-shared` keeps them in data/feedback/shared_trips.json,
in the format `agps feedback` exports its trips in, for finding the roads and shortcuts the network misses.

  T <continent> <time> <estimate s> <actual s> <mounted 1|0> to=<x>,<y>,<continent> <x,y> <x,y> ..."""

from __future__ import annotations

import json
from pathlib import Path

from .paths import data_dir

TRIPS = data_dir() / "feedback" / "shared_trips.json"


def parse_shared_trips(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 9 or parts[0] != "T" or not parts[6].startswith("to="):
            continue
        try:
            cont, t, est, act = int(parts[1]), int(parts[2]), int(float(parts[3])), int(float(parts[4]))
            tx, ty, tc = parts[6][3:].split(",")
            to = [float(tx), float(ty), int(float(tc))]
            pts = []
            for p in parts[7:]:
                x, y = p.split(",")
                pts += [float(x), float(y)]
        except ValueError:
            continue
        if len(pts) < 4:
            continue
        out.append({"continent": cont, "time": t, "estimate": est, "actual": act, "mounted": parts[5] == "1",
                    "from": pts[:2], "to": to, "pts": pts, "source": "shared"})
    return out


def merge_trips(trips: list[dict], path: Path = TRIPS) -> int:
    """Add the trips not kept yet (by continent and time): how many."""
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    have = {(t["continent"], t["time"]) for t in doc}
    new = [t for t in trips if (t["continent"], t["time"]) not in have]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc + new, indent=1) + "\n", encoding="utf-8")
    return len(new)

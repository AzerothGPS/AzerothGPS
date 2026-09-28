"""Watch the addon's SavedVariables file (written by WoW on /reload or logout)."""

from __future__ import annotations

import time
from pathlib import Path

from .parser import load_savedvariables

FILE_NAME = "AzerothGPS_Link.lua"


def _as_list(v) -> list:
    return v if isinstance(v, list) else []  # an empty Lua table parses as {}


def summarize(db: dict) -> dict:
    """Characters' known flight nodes and learned flight times, JSON-friendly."""
    chars = {}
    for key, c in (db.get("chars") or {}).items():
        maps = {}
        for map_id, entry in (c.get("taxiNodes") or {}).items():
            nodes = _as_list(entry.get("nodes"))
            maps[str(map_id)] = {
                "source": entry.get("source"),
                "time": entry.get("time"),
                "nodes": [
                    {"nodeId": n.get("nodeID"), "name": n.get("name"), "x": n.get("x"), "y": n.get("y"),
                     "known": bool(n.get("known")), "stateKnown": n.get("state") is not None}
                    for n in nodes
                ],
            }
        flights = [
            {"from": f.get("from"), "to": f.get("to"), "seconds": f.get("seconds"), "samples": f.get("samples")}
            for f in (c.get("flights") or {}).values()
        ] if isinstance(c.get("flights"), dict) else []
        chars[key] = {"faction": c.get("faction"), "taxi": maps, "flights": flights}
    return {"lastCharacter": db.get("lastChar"), "characters": chars}


class SavedVarsWatcher:
    def __init__(self, wtf_account_dir: Path) -> None:
        self.base = Path(wtf_account_dir)
        self.path: Path | None = None
        self.mtime: float | None = None
        self.data: dict | None = None
        self.error: str | None = None

    def _find(self) -> Path | None:
        files = sorted(self.base.glob(f"*/SavedVariables/{FILE_NAME}"), key=lambda p: p.stat().st_mtime)
        return files[-1] if files else None

    def poll(self) -> bool:
        """Re-read the file if it changed. Returns True when new data was loaded."""
        path = self._find()
        if path is None:
            return False
        mtime = path.stat().st_mtime
        if path == self.path and mtime == self.mtime:
            return False
        try:
            db = load_savedvariables(path).get("AzerothGPS_LinkDB") or {}
            self.data, self.error = summarize(db), None
        except Exception as e:  # file mid-write or unexpected content; retry next poll
            self.error = repr(e)
            return False
        self.path, self.mtime = path, mtime
        return True

    def snapshot(self) -> dict:
        return {
            "file": str(self.path) if self.path else None,
            "updated": self.mtime,
            "updatedText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.mtime)) if self.mtime else None,
            "error": self.error,
            **(self.data or {"lastCharacter": None, "characters": {}}),
        }

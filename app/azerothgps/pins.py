"""Pins players make on the map (the addon's Pins.lua): the shared ones are kept in overrides/pins.json and
written into Data/Pins.lua for everyone (ns.SharedPins; ns.PinsIn, their times, so the addon drops the
player's own copies). They come from the share page's text ("P" lines, Feedback.RoadsText:
`agps import-shared`) and from the saved variables (AzerothGPSDB.pins and pinsRemoved: the road watcher,
`agps watch-roads`, and `agps pins`), like the roads and walls drawn in game.

Shared text is data only: names are cleaned to one line without the game's escape codes ("|"), and an
icon is a file id or an icon's path or name (letters, digits and _ - . \\ / only)."""

from __future__ import annotations

import json
from pathlib import Path

from .paths import ADDON_DIR, RESOURCES

PINS = RESOURCES / "overrides" / "pins.json"
FILE = ADDON_DIR / "Data" / "Pins.lua"
NAME_MAX = 160  # bytes: the addon's NAME_MAX letters, as UTF-8
DEFAULT_ICON = "Interface\\Icons\\INV_Misc_QuestionMark"


def clean_name(s) -> str:
    s = "".join(" " if ord(c) < 32 else c for c in str(s or "")).replace("|", "").strip()
    return (s or "Pin").encode("utf-8")[:NAME_MAX].decode("utf-8", "ignore")


def clean_icon(v):
    """A file id (int), or an icon's path or name; None for anything else."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = "".join(ch for ch in str(v or "") if not ch.isspace())
    if s.isdigit():
        return int(s)
    if not s or len(s) > 200 or not all(ch.isascii() and (ch.isalnum() or ch in "_-.\\/") for ch in s):
        return None
    return s


def make_pin(level, t, x, y, z=None, down=None, icon=None, name=None) -> dict:
    p = {"level": int(level), "time": int(t), "x": round(float(x), 1), "y": round(float(y), 1)}
    if z is not None:
        p["z"] = round(float(z), 1)
    if down is not None:
        p["down"] = bool(down)
    p["icon"] = clean_icon(icon) or DEFAULT_ICON
    p["name"] = clean_name(name)
    return p


def parse_shared_pins(text: str) -> tuple[list[dict], set[int]]:
    """The "P" lines of the share page's text: the pins added, and the times of shared pins removed.
      P add <level> <time> <x,y> [z=<height>] [down=1|0] icon=<id or path> name=<the rest of the line>
      P remove <time>"""
    added, removed = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("P "):
            continue
        head, sep, name = line.partition(" name=")
        parts = head.split()
        if len(parts) == 3 and parts[1] == "remove":
            try:
                removed.add(int(parts[2]))
            except ValueError:
                pass
            continue
        if len(parts) < 5 or parts[1] != "add":
            continue
        fl = dict(p.partition("=")[::2] for p in parts[5:] if "=" in p)
        try:
            level, t = int(parts[2]), int(parts[3])
            x, y = (float(v) for v in parts[4].split(","))
            z = float(fl["z"]) if "z" in fl else None
        except ValueError:
            continue
        down = {"1": True, "0": False}.get(fl.get("down"))
        added.append(make_pin(level, t, x, y, z, down, fl.get("icon"), name if sep else ""))
    return added, removed


def saved_pins(savedvars: dict) -> tuple[list[dict], set[int]]:
    """The pins in the saved variables (AzerothGPSDB.pins) and the shared ones removed (pinsRemoved)."""
    db = savedvars.get("AzerothGPSDB") or {}
    pins = db.get("pins") or {}
    out = []
    for p in (pins.values() if isinstance(pins, dict) else pins):
        if not isinstance(p, dict):
            continue
        try:
            out.append(make_pin(p["level"], p["time"], p["x"], p["y"], p.get("z"), p.get("down"), p.get("icon"),
                                p.get("name")))
        except (KeyError, TypeError, ValueError):
            continue
    removed = set()
    rm = db.get("pinsRemoved") or {}
    for k, v in (rm.items() if isinstance(rm, dict) else enumerate(rm)):
        if v:
            try:
                removed.add(int(k))
            except (TypeError, ValueError):
                pass
    return out, removed


def load_pins(path: Path = PINS) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def merge_pins(added: list[dict], removed: set[int], path: Path = PINS, log=print) -> int:
    """Add the pins not in overrides/pins.json yet (by time) and take out the ones removed: the number of
    changes."""
    doc = load_pins(path)
    have = {p["time"] for p in doc}
    n = 0
    for p in added:
        if p["time"] in have or p["time"] in removed:
            continue
        doc.append(p)
        have.add(p["time"])
        n += 1
        log(f"  pin {p['name']!r} on level {p['level']} at ({p['x']:.0f}, {p['y']:.0f})")
    keep = [p for p in doc if p["time"] not in removed]
    for p in doc:
        if p["time"] in removed:
            log(f"  pin {p['name']!r} removed")
    n += len(doc) - len(keep)
    if n:
        path.parent.mkdir(parents=True, exist_ok=True)
        keep.sort(key=lambda p: p["time"])
        path.write_text(json.dumps(keep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return n


def _lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ") + '"'


def pins_lua(doc: list[dict]) -> str:
    """Data/Pins.lua for the shared pins."""
    out = ["-- Generated by `agps import-shared` / `agps watch-roads` / `agps pins` (app/azerothgps/pins.py) from",
           "-- overrides/pins.json: the pins players shared (Pins.lua), shown to everyone. Don't edit by hand.",
           "local _, ns = ...",
           "ns.SharedPins = {"]
    for p in sorted(doc, key=lambda p: p["time"]):
        f = [f"level = {int(p['level'])}", f"x = {p['x']:.1f}", f"y = {p['y']:.1f}"]
        if p.get("z") is not None:
            f.append(f"z = {p['z']:.1f}")
        if p.get("down") is not None:
            f.append("down = " + ("true" if p["down"] else "false"))
        icon = clean_icon(p.get("icon")) or DEFAULT_ICON
        f.append(f"icon = {icon}" if isinstance(icon, int) else f"icon = {_lua_str(icon)}")
        f += [f"name = {_lua_str(clean_name(p.get('name')))}", f"time = {int(p['time'])}", "shipped = true"]
        out.append("  { " + ", ".join(f) + " },")
    out.append("}")
    out.append("ns.PinsIn = {" + "".join(f" [{int(p['time'])}] = true," for p in doc) + " }")
    return "\n".join(out) + "\n"


def write_pins_lua(path: Path = FILE, pins: Path = PINS) -> Path:
    path.write_text(pins_lua(load_pins(pins)), encoding="utf-8", newline="\n")
    return path


def import_saved(wtf_account_dir: Path, path: Path = PINS, log=print) -> int:
    """The pins in every character's saved variables into overrides/pins.json: the number of changes."""
    from .savedvars.parser import load_savedvariables

    added, removed = [], set()
    for f in sorted(wtf_account_dir.glob("*/SavedVariables/AzerothGPS.lua")):
        a, r = saved_pins(load_savedvariables(f))
        added += a
        removed |= r
    return merge_pins(added, removed, path, log=log)

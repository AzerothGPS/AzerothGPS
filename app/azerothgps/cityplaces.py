"""Heights for the capitals' service locations (addon/AzerothGPS/Data/CityPlaces.lua).

The places are map percentages written by hand, with no height. Where a city's floors lie over
each other (Undercity's walkways over its bank, a trainer under an arch), the route needs the
floor: each place gets the height of its NPC (the nearest spawn in the CMaNGOS dump whose title
says the service: "Cooking Trainer" for a cooking trainer, "Banker" for the bank), as a 4th
value in world yards. `agps city-places` writes them into the file.
"""

from __future__ import annotations

import gzip
import math
import re
from pathlib import Path

from .hostile import DUMP, _rows
from .paths import ADDON_DIR

FILE = ADDON_DIR / "Data" / "CityPlaces.lua"
NEAR_YD = 25.0  # the NPC within this of the place (on the map)
CITIES = ("Undercity", "Orgrimmar", "Thunder Bluff", "Stormwind", "Ironforge", "Darnassus")
# the place's service -> words in its NPC's title (the rest: the service's first word, cut to its stem)
TITLES = {
    "Bank": ("banker",),
    "Inn": ("innkeeper",),
    "Auction House": ("auctioneer",),
    "Bat Handler": ("bat handler",),
    "Wind Rider Master": ("wind rider master",),
    "Gryphon Master": ("gryphon master",),
    "Hippogryph Master": ("hippogryph master",),
    "Guild Master": ("guild master",),
    "Stable Master": ("stable master",),
    "Weapon Master": ("weapon master",),
}


def service(name: str) -> str:
    """"Undercity Cooking Trainer" -> "Cooking Trainer"."""
    for c in CITIES:
        if name.startswith(c + " "):
            return name[len(c) + 1:]
    return name


def title_words(svc: str) -> tuple[str, ...]:
    if svc in TITLES:
        return TITLES[svc]
    words = svc.split()
    stem = words[0].lower()[:6]  # (Alchemy -> alchem: "Journeyman Alchemist Trainer"; Leatherworking -> leathe)
    return (stem, "trainer") if words[-1] == "Trainer" else (stem,)


RANKS = ("apprentice", "journeyman", "expert", "artisan", "master")  # (a crafting trainer's title: "Journeyman Blacksmith")


def matches(svc: str, title: str) -> bool:
    t = title.lower()
    words = title_words(svc)
    if all(w in t for w in words):
        return True
    # (a crafting trainer: its rank and craft, "Expert Tailor"; not "Tailoring Supplies")
    return words[-1] == "trainer" and words[0] in t and t.split()[0] in RANKS


def npc_spawns(data_dir: Path) -> list[tuple[int, float, float, float, str]]:
    """(map, x, y, z, title) of every NPC with a title on the continents."""
    txt = gzip.open(Path(data_dir) / DUMP, "rt", encoding="utf-8", errors="replace").read()
    titles = {r["Entry"]: r.get("SubName", "") for r in _rows(txt, "creature_template")}
    out = []
    for r in _rows(txt, "creature"):
        t = titles.get(r["id"])
        if t and r["map"] in ("0", "1"):
            out.append((int(r["map"]), float(r["position_x"]), float(r["position_y"]), float(r["position_z"]), t))
    return out


def place_height(cont: int, x: float, y: float, name: str, spawns) -> float | None:
    """The height of the place's NPC, or None when none near says its service."""
    svc = service(name)
    best = None
    for m, sx, sy, sz, t in spawns:
        if m != cont or not matches(svc, t):
            continue
        d = math.hypot(sx - x, sy - y)
        if d <= NEAR_YD and (best is None or d < best[0]):
            best = (d, sz)
    return best[1] if best else None


ENTRY = re.compile(r"\{ (-?[\d.]+), (-?[\d.]+), (\"[^\"]*\")(?:, (-?[\d.]+))? \}")


def with_heights(text: str, maps: dict, spawns) -> tuple[str, int, list[str]]:
    """CityPlaces.lua's text with each place's height (a 4th value), how many, and the places
    with none found. `maps`: uiMap -> (continent, bounds (x0, y0, x1, y1) as ns.Maps)."""
    out, n, missing = [], 0, []
    ui = None
    for line in text.splitlines():
        m = re.match(r"\s*\[(\d+)\] = \{ city", line)
        if m:
            ui = int(m.group(1))
        e = ENTRY.search(line)
        if e and ui in maps:
            u, v, qname = float(e.group(1)), float(e.group(2)), e.group(3)
            cont, b = maps[ui]
            x, y = b[2] - v / 100 * (b[2] - b[0]), b[3] - u / 100 * (b[3] - b[1])
            z = place_height(cont, x, y, qname.strip('"'), spawns)
            if z is None:
                missing.append(qname.strip('"'))
                line = line[:e.start()] + f"{{ {e.group(1)}, {e.group(2)}, {qname} }}" + line[e.end():]
            else:
                n += 1
                line = line[:e.start()] + f"{{ {e.group(1)}, {e.group(2)}, {qname}, {z:.1f} }}" + line[e.end():]
        out.append(line)
    return "\n".join(out) + "\n", n, missing

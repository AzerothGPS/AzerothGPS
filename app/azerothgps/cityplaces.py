"""Heights for the capitals' service locations (addon/AzerothGPS/Data/CityPlaces.lua).

The Horde capitals' places are map percentages written by hand; the Alliance capitals' are made
from their NPCs (`from_spawns`, `agps city-places --add`: the same services, each at its NPC, as
the hand-written ones are to within a few yards). Where a city's floors lie over
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


def map_bounds() -> dict:
    """uiMap -> (continent, bounds (x0, y0, x1, y1) as ns.Maps), from Data/Maps.lua."""
    import lupa

    lua = lupa.LuaRuntime()
    lua.execute("ns = {}")
    loader = lua.eval("function(src) return assert(load(src, '@Maps.lua')) end")
    loader((ADDON_DIR / "Data" / "Maps.lua").read_text(encoding="utf-8"))("AzerothGPS", lua.globals().ns)
    out = {}
    Maps = lua.globals().ns.Maps
    for k in Maps.keys():
        m = Maps[k]
        if m.bounds and m.continent is not None:
            b = m.bounds
            out[int(k)] = (int(m.continent), (b[1], b[2], b[3], b[4]))
    return out


def places(ui: int, maps: dict | None = None) -> list[tuple[str, float, float, float]]:
    """A city's places with their heights (CityPlaces.lua, uiMap `ui`): (name, x, y, z) world."""
    maps = maps or map_bounds()
    cont, b = maps[ui]
    out, cur = [], None
    for line in FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*\[(\d+)\] = \{ city", line)
        if m:
            cur = int(m.group(1))
        e = ENTRY.search(line)
        if e and cur == ui and e.group(4):
            u, v = float(e.group(1)), float(e.group(2))
            out.append((e.group(3).strip('"'), b[2] - v / 100 * (b[2] - b[0]), b[3] - u / 100 * (b[3] - b[1]), float(e.group(4))))
    return out


# The services a capital's guards give directions to, for a city's places made from its NPCs
# (`from_spawns`): the Horde capitals' lists were written by hand, the Alliance's are made so.
SERVICES = ("Alchemy Trainer", "Blacksmithing Trainer", "Cooking Trainer", "Enchanting Trainer", "Engineering Trainer",
            "First Aid Trainer", "Fishing Trainer", "Herbalism Trainer", "Leatherworking Trainer", "Mining Trainer",
            "Skinning Trainer", "Tailoring Trainer", "Druid Trainer", "Hunter Trainer", "Mage Trainer", "Paladin Trainer",
            "Priest Trainer", "Rogue Trainer", "Shaman Trainer", "Warlock Trainer", "Warrior Trainer", "Bank", "Inn",
            "Auction House", "Guild Master", "Stable Master", "Weapon Master", "Gryphon Master", "Hippogryph Master",
            "Wind Rider Master", "Bat Handler")
CLUSTER_YD = 40.0  # NPCs of a service this close together are one place (a trainers' hall, the bank's counter)


def from_spawns(ui: int, city: str, maps: dict, spawns) -> list[tuple[float, float, str, float]]:
    """A capital's places from its NPCs: (u, v map percent, "<city> <service>", height) for each
    service with an NPC inside the city's map. Where a service has NPCs in more than one spot,
    the spot with the most of them, and its NPC nearest their middle."""
    cont, b = maps[ui]
    inside = [(x, y, z, t) for m, x, y, z, t in spawns if m == cont and b[0] <= x <= b[2] and b[1] <= y <= b[3]]
    if not inside:
        return []
    mx = sum(s[0] for s in inside) / len(inside)
    my = sum(s[1] for s in inside) / len(inside)
    out = []
    for svc in SERVICES:
        hits = [s for s in inside if matches(svc, s[3])]
        if not hits:
            continue
        # (single-linkage clusters)
        groups: list[list] = []
        for s in hits:
            near = [g for g in groups if any(math.hypot(s[0] - o[0], s[1] - o[1]) <= CLUSTER_YD for o in g)]
            merged = [s]
            for g in near:
                merged += g
                groups.remove(g)
            groups.append(merged)
        # (the most NPCs; then the one nearer the city's middle)
        g = max(groups, key=lambda g: (len(g), -math.hypot(sum(o[0] for o in g) / len(g) - mx, sum(o[1] for o in g) / len(g) - my)))
        cx, cy = sum(o[0] for o in g) / len(g), sum(o[1] for o in g) / len(g)
        x, y, z, _t = min(g, key=lambda o: math.hypot(o[0] - cx, o[1] - cy))
        u = (b[3] - y) / (b[3] - b[1]) * 100
        v = (b[2] - x) / (b[2] - b[0]) * 100
        out.append((round(u, 1), round(v, 1), f"{city} {svc}", round(z, 1)))
    out.sort(key=lambda p: p[2])
    return out


# The capitals whose places are made from their NPCs (the Horde's are written by hand): uiMap, name.
MADE = ((1453, "Stormwind"), (1455, "Ironforge"), (1457, "Darnassus"))


SNAP_YD = 40.0  # a place off the city's walkable cells (an NPC in a small room it doesn't reach) moves this far at most


def snap(ui: int, maps: dict, row):
    """A made place (u, v, name, z) moved onto the capital's walkable cells (Data/Capitals.lua's grid:
    0 open, 3 a floor under walkable ground) when its NPC stands off them, to the nearest within
    SNAP_YD: the room's doorway, where a route can end. As it was when on them, or none is near."""
    from .roads.build import capital_cells

    u, v, name, z = row
    cont, b = maps[ui]
    x, y = b[2] - v / 100 * (b[2] - b[0]), b[3] - u / 100 * (b[3] - b[1])
    T = 1600 / 3
    for tx0, ty0, cell, rows in capital_cells(cont):
        k = T / cell
        c0 = int(math.floor(((32 - y / T) - tx0) * k))
        r0 = int(math.floor(((32 - x / T) - ty0) * k))
        if not (0 <= r0 < len(rows) and 0 <= c0 < len(rows[r0])):
            continue
        if rows[r0][c0] in (0, 3):
            return row
        reach = int(SNAP_YD / cell)
        best = None
        for r in range(max(0, r0 - reach), min(len(rows), r0 + reach + 1)):
            for c in range(max(0, c0 - reach), min(len(rows[r]), c0 + reach + 1)):
                if rows[r][c] in (0, 3):
                    d = math.hypot(r - r0, c - c0)
                    if d <= reach and (best is None or d < best[0]):
                        best = (d, r, c)
        if best:
            _, r, c = best
            X = (32 - ty0 - (r + 0.5) / k) * T
            Y = (32 - tx0 - (c + 0.5) / k) * T
            return (round((b[3] - Y) / (b[3] - b[1]) * 100, 1), round((b[2] - X) / (b[2] - b[0]) * 100, 1), name, z)
    return row


def with_made(text: str, maps: dict, spawns) -> tuple[str, list[str]]:
    """CityPlaces.lua's text with the MADE capitals' places (from_spawns) put in, replacing any
    there already; and what was written."""
    done = []
    for ui, city in MADE:
        rows = [snap(ui, maps, r) for r in from_spawns(ui, city, maps, spawns)]
        if not rows:
            continue
        block = f'  [{ui}] = {{ city = "{city}",\n' + "".join(
            f'    {{ {u}, {v}, "{n}", {z} }},\n' for u, v, n, z in rows) + "  },\n"
        pat = re.compile(r"  \[%d\] = \{ city = .*?\n  \},\n" % ui, re.S)
        if pat.search(text):
            text = pat.sub(lambda _m: block, text)
        else:
            text = text[:text.rstrip().rfind("}")] + block + "}\n"
        done.append(f"{city} ({len(rows)})")
    return text, done

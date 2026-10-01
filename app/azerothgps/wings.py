"""Dungeons and raids with wings: ways in that lead to parts of their own (asked, 2026-10-01: the
Scarlet Monastery's four, "and any dungeon/raid that does this").

Each way in is named by its wing (the server's teleport into it, matched by `WINGS`' patterns, in
order: a door of its own too, "Back Door"), and each boss belongs to its wing: by `BOSSES` where known
(the roads guessed wrong: Stratholme's halves are one city, and a gap join can tie two wings' roads),
else the wing whose way in reaches it soonest along the instance's roads. `DOORS`: another way into the
same dungeon, not a part of its own (Uldaman's back, Gnomeregan's Train Depot): named, its bosses all.
The addon draws an icon per wing on the continent, and a wing's map, boss route and usual way through
are its own (GPSFrame's G.InstanceWing)."""

from __future__ import annotations

import heapq
import math

# map id -> [(a piece of the teleport's name, the wing, the door or None)], the first that matches
WINGS = {
    189: [("Graveyard", "Graveyard", None), ("Library", "Library", None), ("Armory", "Armory", None),
          ("Cathedral", "Cathedral", None)],  # Scarlet Monastery
    429: [("East - Entering Back Door", "East", "Back Door"), ("West - Entering Side Door", "West", "Side Door"),
          ("East", "East", None), ("West", "West", None), ("North", "North", None)],  # Dire Maul
    329: [("Front", "Main Gate", None), ("Back Door", "Service Entrance", None)],  # Stratholme
    349: [("Orange", "Orange", None), ("Purple", "Purple", None)],  # Maraudon
    70: [("Entering", "Front Entrance", None), ("Exit", "Back Entrance", None)],  # Uldaman
    90: [("Entering", "Front Entrance", None), ("Train Depot", "Train Depot", None)],  # Gnomeregan
}
DOORS = {70, 90}

# map id -> {wing (or wings, a tuple: the bosses both reach): [boss names]}; the rest by the roads
BOSSES = {
    189: {"Graveyard": ["Interrogator Vishas", "Bloodmage Thalnos", "Azshir the Sleepless", "Fallen Champion", "Ironspine"],
          "Library": ["Houndmaster Loksey", "Arcanist Doan"],
          "Armory": ["Herod"],
          "Cathedral": ["Scarlet Commander Mograine", "High Inquisitor Whitemane", "High Inquisitor Fairbanks"]},
    429: {"East": ["Pusillin", "Zevrim Thornhoof", "Hydrospawn", "Lethtendris", "Alzzin the Wildshaper", "Isalien"],
          "West": ["Tendris Warpwood", "Illyanna Ravenoak", "Magister Kalendris", "Immol'thar", "Prince Tortheldrin", "Tsu'zee"],
          "North": ["Guard Mol'dar", "Stomper Kreeg", "Guard Fengus", "Guard Slip'kik", "Captain Kromcrush",
                    "Cho'Rush the Observer", "King Gordok"]},
    329: {"Main Gate": ["Skul", "Stratholme Courier", "Hearthsinger Forresten", "The Unforgiven", "Timmy the Cruel",
                        "Malor the Zealous", "Cannon Master Willey", "Archivist Galford", "Balnazzar", "Postmaster Malown",
                        "Jarien", "Sothos"],
          "Service Entrance": ["Baroness Anastari", "Nerub'enkan", "Maleki the Pallid", "Magistrate Barthilas",
                               "Ramstein the Gorger", "Baron Rivendare", "Black Guard Swordsmith"]},
    349: {"Orange": ["Noxxion", "Razorlash"], "Purple": ["Lord Vyletongue"],
          ("Orange", "Purple"): ["Celebras the Cursed", "Landslide", "Tinkerer Gizlock", "Rotgrip", "Princess Theradras"]},
}

# a way in's teleport -> its way out's, where their names don't pair up ("Uldaman Exit" is the back way in)
DOOR_OUTS = {"Uldaman Exit": "Uldaman Instance End"}

NODE_Z = 8.0  # yards: a road node this near a spot's height is on its floor (where the roads have heights)


def entrance_wing(map_id: int, label: str) -> tuple:
    """(wing, door) of the way in with teleport name `label`, or (None, None)."""
    for piece, wing, door in WINGS.get(map_id, []):
        if piece.lower() in (label or "").lower():
            return wing, door
    return None, None


def _nearest(nodes, zs, x, y, z) -> int | None:
    best = None
    for i, (nx, ny) in enumerate(nodes):
        if zs and z is not None and abs(zs[i] - z) > NODE_Z:
            continue
        d = math.hypot(nx - x, ny - y)
        if best is None or d < best[0]:
            best = (d, i)
    if best is None and zs:  # (no node on that floor: any)
        return _nearest(nodes, None, x, y, None)
    return best[1] if best else None


def _distances(n: int, edges, start: int) -> list:
    """Yards along the roads from node `start` to every node (inf where they don't reach)."""
    adj = [[] for _ in range(n)]
    for a, b, pts in edges:
        d = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(pts, pts[1:]))
        adj[a].append((b, d))
        adj[b].append((a, d))
    dist = [math.inf] * n
    dist[start] = 0.0
    heap = [(0.0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            if d + w < dist[v]:
                dist[v] = d + w
                heapq.heappush(heap, (d + w, v))
    return dist


def wings(map_id: int, entrances: list, bosses: list, nodes: list, edges: list, zs: list | None) -> tuple:
    """The instance's wings: (each way in's (wing, door), each boss's wing (by index in `bosses`: a name, or a
    list when in several; not placed: none), the wings in order), or ([], {}, []) when it has fewer than two. `entrances`: (cont, x, y, z,
    ix, iy, iz, label); `bosses`: dicts with x, y, z; `nodes` [(x, y)], `edges` [(a, b, pts)], `zs` the
    nodes' heights. A way in no pattern names takes the wing of the named one its roads reach soonest."""
    named = [entrance_wing(map_id, e[7]) for e in entrances]
    order = []
    for _p, wing, _d in WINGS.get(map_id, []):
        if wing not in order and any(w == wing for w, _ in named):
            order.append(wing)
    if len(order) < 2 or not nodes:
        return [], {}, []
    starts = [_nearest(nodes, zs, e[4], e[5], e[6]) for e in entrances]
    dists = [_distances(len(nodes), edges, s) if s is not None else None for s in starts]

    def reach(i, node):
        d = dists[i]
        return math.inf if d is None or node is None else d[node]

    # (an unnamed way in: the named one nearest along the roads, else straight)
    for i, (w, door) in enumerate(named):
        if w is None:
            cands = [(reach(j, starts[i]), math.hypot(entrances[j][4] - entrances[i][4], entrances[j][5] - entrances[i][5]), j)
                     for j, (wj, _d) in enumerate(named) if wj is not None]
            if cands:
                named[i] = (named[min(cands)[2]][0], door)
    boss_wing = {}
    if map_id in DOORS:  # (ways into the same dungeon: each its bosses all)
        return named, boss_wing, order
    known = {name: w for w, names in BOSSES.get(map_id, {}).items() for name in names}
    for k, b in enumerate(bosses):
        if b.get("x") is None:
            continue
        if b["name"] in known:
            w = known[b["name"]]
            boss_wing[k] = list(w) if isinstance(w, tuple) else w
            continue
        node = _nearest(nodes, zs, b["x"], b["y"], b.get("z"))
        cands = [(reach(i, node), math.hypot(e[4] - b["x"], e[5] - b["y"]), i) for i, e in enumerate(entrances)
                 if named[i][0] is not None]
        if cands:
            boss_wing[k] = named[min(cands)[2]][0]
    return named, boss_wing, order

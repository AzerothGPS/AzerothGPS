# Plan (in-game addon)

On 2026-09-24 the project pivoted from an external second-monitor app to a
self-contained addon. The Phase 0 findings still hold ([phase0-results.md](phase0-results.md)):
position and facing work in and out of combat, speed is secret in combat, and the
client files can be read offline.

## Principles
- The addon only displays. It never moves the character, clicks, or automates anything.
- The addon ships derived numbers only (texture FileDataIDs, coordinates, road
  polylines) and draws the game's own textures. No Blizzard files in the repo.
- The data files are regenerated from the local client with `agps gen-addon-data`
  after each client patch.
- Pure Lua logic (layout, routing, maneuvers) is unit-tested with lupa.

## Milestones

| | Scope | Done when |
|---|---|---|
| **A1 GPS frame** | Square, movable, clipped frame; minimap terrain tiles (default) or zone world-map art (fully explored); heading-up (default) or north-up; zoom with the mouse wheel; opacity; size; lock | The map matches the in-game minimap/world map and turns correctly with the character in several zones |
| **A2 Road network** | Road extraction (texture rules, raster, skeleton, graph, gap bridging, overrides); review overlays for Durotar, the Barrens, Orgrimmar, Elwynn and Westfall; export `Data/Roads.lua`; a debug toggle that draws roads in the GPS frame | You sign off on the zone overlays, and the roads line up in game |
| **A3 Destinations and routing** | Set a destination by clicking the GPS frame or the world map, `/agps way x y`, or a town/flight master list; A* in Lua with off-road legs; route line in the frame; rerouting when off route; Follow while navigating | A route from the Valley of Trials to Razor Hill follows the roads, and rerouting works |
| **A4 Turn-by-turn** | Maneuvers (slight/turn/sharp/U-turn, "toward <place>"); a panel with the next turn icon, distance, ETA and upcoming turns | The instructions match the actual turns on test routes |
| **A5 Flight paths** | Known nodes from the flight map, learned flight times, flight edges and a toggle | A long route flies when that is faster, and only via known nodes |
| **A6 Polish** | Options panel, boats and zeppelins, minimap/world-map integration, packaging for CurseForge/Wago, a checklist for the Forever launch data refresh | |

## 1.0.7: Dungeons and raids (released)

Done: 25 dungeons and raids as their own levels (floors in layers with stairs, the game's
minimap art, floor buttons), boss order and the gold "usual way", boss route and kill
tracking, the map in dungeons while the game hides the position there (probed in Ragefire
Chasm: position, facing and uiMap hidden; speed given), zones too high for the level avoided
and asked about, zeppelin and boat docks with learned timetables, faction-aware transports,
the public API (v2 for dungeon maps). The "dungeon route" (starting the boss route on
entering) is built but off the menus: it needs the position, which this client hides.


Goal: every dungeon and raid on the open continents viewable and routed like a city: its
own walk network, its bosses on the map, and a suggested boss route where killing a boss
counts as arriving at that stop.

### What it looks like to the player
- **Instances toggle** in the map menu (a quick button, grouped with the map layers):
  shows instance entrances on every map style (Terrain, World Map, No Spoiler) and, inside
  or viewing an instance, its boss icons.
- **View an instance like a city:** click an entrance icon (on the continent map, a zone
  map or the terrain view) to open the instance's map, as capital icons open cities today.
- **Instance route** (like the quest route): inside an instance, one click makes a route
  through its bosses in the suggested order, from the entrance. A stop is done when its
  boss dies (or is already dead), not when you reach its spot; skipped bosses can be
  removed like any stop. Outside, a route to an instance ends at its entrance (the
  summoning stone / portal), including the walk to it through caves (e.g. Wailing Caverns).
- **City icons on the terrain view:** cities with a map of their own (Undercity, and the
  capitals' interiors like Ironforge) get their icon on the terrain view too, at the
  entrance; clicking opens the city's map, as on the continent map.

### How it's built
1. **Feasibility first (in game, `/agps debug` inside a dungeon):**
   - whether the player's position is available inside an instance (`UnitPosition`,
     `C_Map.GetBestMapForUnit`, `C_Map.GetPlayerMapPosition`: retail and some classic
     clients hide it there);
   - which uiMaps the instance has (floors), and whether its map art draws;
   - whether `ENCOUNTER_END` / `BOSS_KILL` fire, else the combat log's `UNIT_DIED` for the
     boss's NPC.
   If the position is hidden, the instance view and boss list still work, but routing
   inside becomes "next boss" guidance without live following. Decide after the probe.
2. **Extraction (`app/azerothgps/instances.py`, reusing `walknet.py`):** each instance
   map (Map DB2 with an instance type) becomes its own routing level (like Undercity's
   10001: a pseudo-continent per instance), built from its WMO (or terrain, for the few
   outdoor ones): floors, walls, stairs/drops, roads. Entrances from the client's
   AreaTrigger/portal positions on the continent and in the instance, joined as
   transports (like the lifts). Output `Data/Instances.lua` (a new toc file: a full game
   restart).
3. **Bosses:** positions from the NPC spawn data already in use (the CMaNGOS dump, same
   license decision as the NPC paths), matched to the client's DungeonEncounter table
   for names and encounter IDs; boss icons in `Data/Instances.lua`.
4. **Suggested order:** the usual boss order per instance from public guides (facts
   only: which boss after which), reviewed by hand; the route stays on the instance's
   roads between them.
5. **Addon:** instance levels in Router/Nav (as city levels), the instance map view and
   entrance/boss icons on all map styles, the map-menu toggle, the Instance route, boss
   kill = stop done.

### Order of work
1. Probe in game (you, in any dungeon: Ragefire Chasm or the Deadmines are closest), and
   city icons on the terrain view (independent, small).
2. Research (boss order per instance) and extraction (walk networks, entrances, bosses)
   in parallel background agents, one dungeon family at a time, starting with the
   low-level five-mans (Ragefire Chasm, Wailing Caverns, the Deadmines, Shadowfang Keep,
   Blackfathom Deeps, the Stockade).
3. Addon side, then the rest of the dungeons and the raids.

## 1.0.8: More dungeons and raids

Done so far: Blackwing Lair (in through Blackrock Spire); WoW Forever's Karazhan Crypts, Demon
Fall Canyon, Scarlet Enclave, Storm Cliffs, The Tainted Scar, The Crystal Vale, Nightmare Grove,
City of Dalaran, Ruins of Lordaeron, The Hall of Thanes and Excavation Site: Wetlands with their
map, bosses (no spots) and researched entrances; entrances learned in game. Not in this client:
The Drowned City, Krol'Dok Stronghold, Alcaz Island Prison, Blackmaw Hold, Shaper's Terrace
(announced), Hyjal Summit, Barrow Deeps; Half-Pint Tavern and Manor Mistmantle are unannounced.

Also done: movement abilities in the times (Ghost Wolf, Travel Form, Cat Form with Feline
Swiftness, Aspect of the Cheetah / Pack with Pathfinding: shown beside walking when known, the
walking time while on; their speed learned when seen, the plain run speed with the Speed stat);
the walked part of the route trimmed off behind the player every 2 yd between recalculations.; the
Deeprun Tram as a ride between Stormwind and Ironforge (its ways in from the client's AreaTrigger,
its time from the cars' TransportAnimation: 130 s end to end; Alliance cities at both ends, so
the faction check leaves it to the Alliance), the route held while in its map.
Walk searches by blocks (prepared offline, as Shortest Path Forever's): 5x faster over 160 trips,
no way through known at once (was up to 1.2 s of flooding); straightening by jumps (5x); line
checks skip the overlay lookups away from cities and look each cell up once (1.8x). Left: offroad
mode's node links (up to 36k line checks on a long route after a /reload) are most of what's left.
Road display zoomed out: roads no longer vanish past the 1500-line cap (drawn roads first, only
on-screen parts, lines on a screen grid drawn once, a coarser grid when crowded, scaled with the
zoom); walls drawn before the terrain's edges.
World map: Zephras Isle (no place on the world art, nor a link in the client) as a framed inset
of its own map (G.WORLD_INSETS), clicked to open it; continents' zones light up under the mouse
(C_Map.GetMapHighlightInfoAtPosition, as the game's map).

- **Blackwing Lair:** its ghost entrance (Blackrock Mountain) and triggers inside are in the
  client, its bosses in the CMaNGOS dump; reached through Upper Blackrock Spire.
- **WoW Forever's new dungeons and raids** (Karazhan Crypts, Demon Fall Canyon, Scarlet Enclave,
  Storm Cliffs, The Tainted Scar, The Crystal Vale, Nightmare Grove, City of Dalaran, Ruins of
  Lordaeron, The Hall of Thanes, Excavation Site: Wetlands, Half-Pint Tavern, Manor Mistmantle,
  Hyjal Summit, Barrow Deeps): the client has their models and boss names (DungeonEncounter),
  not their entrances, boss spots or order (its encounter-journal tables are empty). Entrances:
  learned in game (where the player stood before the loading screen), shared with Copy map data;
  boss spots and order: public guides.
- **Zeppelin and boat timers shared** with guild and group (addon messages, opt-in): one ride
  by anyone starts everyone's countdowns.
- **The 3D dungeon check** (`agps instances --check`) for the floor layers: route with heights,
  walk over the layers' floors.
- **Boss kills:** confirm which events this client sends (the probe logs them).

- **Texture rotation (A1):** heading-up relies on `Texture:SetRotation` turning the whole
  quad. If it only rotates texture coordinates inside an axis-aligned box, fall back to
  north-up for tiles (the arrow still rotates) or find another technique.
- **Road quality (A2):** the crux, as before; handled with texture rules, overrides and review.
- **Performance:** the frame redraws at most `hz` times a second from a small texture pool.

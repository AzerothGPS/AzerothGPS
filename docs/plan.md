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

## Risks
- **Texture rotation (A1):** heading-up relies on `Texture:SetRotation` turning the whole
  quad. If it only rotates texture coordinates inside an axis-aligned box, fall back to
  north-up for tiles (the arrow still rotates) or find another technique.
- **Road quality (A2):** the crux, as before; handled with texture rules, overrides and review.
- **Performance:** the frame redraws at most `hz` times a second from a small texture pool.

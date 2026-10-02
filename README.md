<p align="center"><img src="assets/logo.png" alt="AzerothGPS" width="256"></p>

# AzerothGPS

[![Release build](https://github.com/AzerothGPS/AzerothGPS/actions/workflows/release.yml/badge.svg)](https://github.com/AzerothGPS/AzerothGPS/actions/workflows/release.yml)
[![Latest release](https://img.shields.io/github/v/release/AzerothGPS/AzerothGPS?label=release)](https://github.com/AzerothGPS/AzerothGPS/releases/latest)
[![CurseForge downloads](https://img.shields.io/curseforge/dt/1712208?label=CurseForge&logo=curseforge&color=F16436)](https://www.curseforge.com/projects/1712208)
![WoW Forever 1.60.1](https://img.shields.io/badge/WoW%20Forever-1.60.1-1f6feb)
![Interface 16001](https://img.shields.io/badge/interface-16001-555555)
![Lua 5.1](https://img.shields.io/badge/Lua-5.1-2C2D72?logo=lua&logoColor=white)
[![Last commit](https://img.shields.io/github/last-commit/AzerothGPS/AzerothGPS)](https://github.com/AzerothGPS/AzerothGPS/commits/main)

Car-GPS style navigation **inside World of Warcraft: Forever**. Routes follow the
game's roads, with turn-by-turn directions, multi-stop trips (boats and zeppelins
included), quests on the map, and TomTom `/way` import and sharing.

<p align="center">
  <img src="https://github.com/user-attachments/assets/81709111-9f3d-43d0-af64-d24932cbcadb" alt="Double-clicking Goldshire and a spot nearby, confirming, then following the route with the direction arrow" width="540">
  <br><em>Double-click to place stops, then follow the direction arrow stop by stop.</em>
</p>

| Exploring the map | Importing <code>/way</code> waypoints |
|---|---|
| <img src="https://github.com/user-attachments/assets/9a342cd0-a3ae-4a8d-939a-bb2c5a0f4850" alt="Panning, zooming and picking a spot from the world map" width="400"> | <img src="https://github.com/user-attachments/assets/3d9a2af0-0980-40d4-89c8-b3d45e432e43" alt="Pasting /way lines into the import window" width="400"> |
| Drag, zoom, or right-click out to the world map to pick a spot. | Paste TomTom lines and the route is ready, zeppelin included. |

<p align="center">
  <img src="https://github.com/user-attachments/assets/9f86bb86-8e44-48eb-9a78-725811e2667c" alt="A three-stop trip in Mulgore along the roads, with the direction arrow above the map" width="700">
  <br><em>A three-stop trip: each leg in its stop's color, the steps with times, and the direction arrow (top left). The map is enlarged here; size and opacity are adjustable.</em>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/4493cdc1-c3fe-4176-9bf4-b974e36e31b9" alt="The same spot near Razor Hill in Terrain, World Map and No Spoiler" width="700">
  <br><em>Three map styles: Terrain, World Map, and No Spoiler (only what you've explored).</em>
</p>

| Direction arrow | Quest areas |
|---|---|
| <img src="https://github.com/user-attachments/assets/e3062cea-ce82-410f-b8ef-11eb23ae4431" alt="The direction arrow above the map in Mulgore: the next turn, the stop's distance and ETA, the stops after it" width="400"> | <img src="https://github.com/user-attachments/assets/ee5e73a8-0b70-4f17-8f6a-9d57b5fa2dd2" alt="Quest area outlines with a quest tooltip" width="400"> |
| Next maneuver, the stop's distance and ETA, and the stops after it. | Quest areas outlined like on the minimap; hover for the objectives. |
| **Sharing a route** | **Drawn roads** |
| <img src="https://github.com/user-attachments/assets/134bff8b-795f-4a1a-b08a-28398172314a" alt="The waypoint window with a Mulgore route copied as /way lines" width="400"> | <img src="https://github.com/user-attachments/assets/06d4058a-a63c-4494-8c3e-200dc0befd10" alt="Road tools on near Razor Hill: a drawn road joining the road network" width="400"> |
| Copy your route as <code>/way</code> lines, or send it in game. | Draw a missing road on the map and routes use it right away. |
| **Search** | **Hearthstone in routes** |
| <img src="https://github.com/user-attachments/assets/8012fb12-c9f1-4881-9889-e6c1b6563852" alt="Searching &quot;ri&quot; on Zephras Isle, each result with its kind" width="400"> | <img src="https://github.com/user-attachments/assets/7bdb905f-ca31-4046-8f06-bf88ab0de96c" alt="In the Barrens, a route whose first step is Use your Hearthstone, in the arrow window and the route panel" width="400"> |
| Type a few letters and pick a town, zone, landmark, flight master or dock. | Hearth home when it's faster; one click on the button turns it on or off. |
| **Farming routes** | **Importing herb and ore nodes** |
| <img src="https://github.com/user-attachments/assets/09e4ea32-aa55-4921-8526-1164ee2e7709" alt="On Zephras Isle: the herb and ore buttons, Draw a Farming Area, a loop drawn round the nodes, the route through them" width="400"> | <img src="https://github.com/user-attachments/assets/3e19339d-b59e-4764-9614-1e3c22e958cc" alt="The waypoint window with Import as herb/ore nodes ticked, Durotar herbs" width="400"> |
| Draw around herb or ore nodes and the route loops through them. | Paste <code>/way</code> node lists; they show faded until you gather there. |
| **Your raid on the map** | **A bigger map** |
| <img src="https://github.com/user-attachments/assets/8f65e156-c3af-46f1-a3e1-c3755bb95991" alt="Your raid in open-world PvP, each member's class icon on the map" width="400"> | <img src="https://github.com/user-attachments/assets/e0db657e-87ab-46aa-a531-f089d7f28a24" alt="Dragging the map window's corner to resize it" width="400"> |
| Where your raid or party is, by class, in open-world PvP or anywhere. | Drag the corner to resize (Lock map size off). |
| **Dungeons** | **Zeppelins and boats** |
| <img src="https://github.com/user-attachments/assets/c697343f-1eed-45e0-8a2e-4b32cc35aeef" alt="Ragefire Chasm's map: marking where you are, the next boss" width="400"> | <img src="https://github.com/user-attachments/assets/5bff3157-49cc-464c-a0df-cab9a715145d" alt="A zeppelin tower's countdown and tooltip" width="400"> |
| A dungeon's map with its bosses in order and the usual way through; mark where you are and bosses down. | Every dock counts down to its next zeppelin or boat. |

**Get it:** download the zip from the [latest release](https://github.com/AzerothGPS/AzerothGPS/releases/latest)
and extract the `AzerothGPS` folder into `_classic_beta_\Interface\AddOns`. In game,
`/agps` opens the options and `/agps help` lists the commands.

**Documentation:** every feature, option and command is in the [wiki](https://github.com/AzerothGPS/AzerothGPS/wiki).

**Community:** questions, news and road or wall fixes on the [AzerothGPS Discord](https://discord.gg/gktYHzs2c).
Bugs and road data can also go in [GitHub issues](https://github.com/AzerothGPS/AzerothGPS/issues).

## Repository

- `addon/AzerothGPS` is the addon. It is display-only: it never moves your
  character, clicks, or automates anything. It draws the game's own textures by
  FileDataID; no Blizzard files are shipped.
- `app/` holds developer tools (Python). They read the **local** client install to
  generate the addon's data files (`addon/AzerothGPS/Data/*.lua`: texture IDs,
  map bounds, road network). Players don't need them.
- `data/` is generated scratch output and git-ignored.

## Status

Version 1.0.0. Roadmap: [docs/plan.md](docs/plan.md).

## Developer tools

`agps.cmd` runs the tools in their own environment at `%USERPROFILE%\.venvs\azerothgps`.

```
agps setup                 # first time
agps gen-addon-data        # regenerate addon/AzerothGPS/Data/*.lua after a client patch
agps install-addon         # copy the addon into _classic_beta_\Interface\AddOns
agps extract               # map art, bounds, POIs and roads into data/ (for road review)
agps roads                 # rebuild the road network after editing overrides/
agps probes                # read /agps debug results
```

Extraction needs `data/ref/listfile.csv` (the wowdev community listfile) and
`data/ref/dbd/*.dbd` (WoWDBDefs). Tests: `cd app`, then `python -m pytest`.

Docs: [plan](docs/plan.md) · [coordinates](docs/coordinates.md) · [in-game tests](docs/ingame-tests.md) · [CurseForge page](docs/curseforge-description.md)

## License

Copyright (c) 2026 AzerothGPS. All rights reserved. See [LICENSE](LICENSE).

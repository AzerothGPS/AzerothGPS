<p align="center"><img src="assets/logo.png" alt="AzerothGPS" width="256"></p>

# AzerothGPS

Car-GPS style navigation **inside World of Warcraft: Forever**. Routes follow the
game's roads, with turn-by-turn directions, multi-stop trips (boats and zeppelins
included), quests on the map, and TomTom `/way` import and sharing.

<p align="center">
  <img src="https://i.imgur.com/LnZbC2x.gif" alt="Placing stops, then following the route with the direction arrow" width="540">
  <br><em>Double-click to place stops, then follow the direction arrow stop by stop.</em>
</p>

| Exploring the map | Importing <code>/way</code> waypoints |
|---|---|
| <img src="https://i.imgur.com/pIXbXdS.gif" alt="Panning, zooming and picking a spot from the world map" width="400"> | <img src="https://i.imgur.com/SvecrT3.gif" alt="Pasting /way lines into the import window" width="400"> |
| Drag, zoom, or right-click out to the world map to pick a spot. | Paste TomTom lines and the route is ready, zeppelin included. |

<p align="center">
  <img src="https://i.imgur.com/lOUdHxl.png" alt="A three-stop route around Brill and the Undercity with the direction arrow" width="700">
  <br><em>A three-stop trip: each leg in its stop's color, the steps with times, and the direction arrow (top left). The map is enlarged here; size and opacity are adjustable.</em>
</p>

<p align="center">
  <img src="https://i.imgur.com/gqISXPx.png" alt="Terrain, World Map and No Spoiler map styles" width="700">
  <br><em>Three map styles: Terrain, World Map, and No Spoiler (only what you've explored).</em>
</p>

| Direction arrow | Quest areas |
|---|---|
| <img src="https://i.imgur.com/pCqMfOT.png" alt="The direction arrow window" width="400"> | <img src="https://i.imgur.com/NLye6Xh.png" alt="Quest area outlines with a quest tooltip" width="400"> |
| Next maneuver, the stop's distance and ETA, and the stops after it. | Quest areas outlined like on the minimap; hover for the objectives. |
| **Sharing a route** | **Drawn roads** |
| <img src="https://i.imgur.com/mUgJa9g.png" alt="The import and share window" width="400"> | <img src="https://i.imgur.com/6U6bU8C.png" alt="A drawn road joining the road network" width="400"> |
| Copy your route as <code>/way</code> lines, or send it in game. | Draw a missing road on the map and routes use it right away. |
| **Search** | **Hearthstone in routes** |
| <img src="https://i.imgur.com/Qb3HwWf.png" alt="Searching places on Zephras Isle" width="400"> | <img src="https://i.imgur.com/m1Trl0w.png" alt="A route that starts with Use your Hearthstone" width="400"> |
| Type a few letters and pick a town, zone, landmark, flight master or dock. | Hearth home when it's faster; one click on the button turns it on or off. |
| **Farming routes** | **Importing herb and ore nodes** |
| <img src="https://i.imgur.com/ABt7arU.gif" alt="Drawing a farming area and following the loop route" width="400"> | <img src="https://i.imgur.com/KXUz2RU.png" alt="The waypoint window with Import as herb/ore nodes" width="400"> |
| Draw around herb or ore nodes and the route loops through them. | Paste <code>/way</code> node lists; they show faded until you gather there. |

**Get it:** download the zip from the [latest release](https://github.com/AzerothGPS/AzerothGPS/releases/latest)
and extract the `AzerothGPS` folder into `_classic_beta_\Interface\AddOns`. In game,
`/agps` opens the options and `/agps help` lists the commands.

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

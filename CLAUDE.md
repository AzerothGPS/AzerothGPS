# AzerothGPS

A car-GPS style navigation addon for **World of Warcraft: Forever**. It draws a map around
the player with routes along the game's roads, turn-by-turn directions, multi-stop trips,
boats, zeppelins and flight paths. It's published on CurseForge as "Azeroth GPS".

## Hard rules (Blizzard ToS / UI Add-On Development Policy)

The addon is going public, so every change must keep it policy-safe:

- **Display only.** Never move the character, click, target, cast, or automate anything.
  No input automation, memory reading, packet inspection or DLL injection, and no
  libraries that do those things.
- **No Blizzard assets in the repo or in any release.** Draw the game's own textures by
  FileDataID or path at runtime. Game screenshots stay out of git
  (`docs/curseforge-images/` is ignored). Our own art in `addon/AzerothGPS/Media/` is fine.
- **`data/` is git-ignored** and holds files extracted from the local client. Never commit
  extracted Blizzard files. `addon/AzerothGPS/Data/*.lua` is generated numbers and names
  only, and that is committed.
- **Addons can't use the network.** Sharing features are opt-in and store data locally in
  SavedVariables only. Routes shared in game go through addon messages, and the receiver
  is always asked before one is used.
- **Never execute submitted or shared data** (no `loadstring` and the like on it). Parse it
  strictly as data.
- If a feature is a gray area, flag it instead of silently building it.

## What this client doesn't give addons (checked; don't retry)

- **Minimap blips:** herbs, ore and quest givers can't be listed or located. Only the
  tooltip of a blip under the mouse can be read (Layers.lua uses it).
- **NPC locations:** not in the client files and not in the API. Search covers places,
  not NPCs.
- **Quests to pick up:** `C_QuestLine.GetAvailableQuestLines` is empty here, and the world
  map doesn't show them either. The feature was removed.
- **Old globals missing or unreliable:** use `ns.SpellName` / `ns.SpellIcon` (Core.lua),
  not `GetSpellInfo`.
- **Combat hides values (secret values):** e.g. `GetUnitSpeed`, and the quest-area hit tests
  (`C_Minimap.IsInsideQuestBlob` and friends). Quest-area tracing pauses in combat; check
  results with `ns.IsSecret` before testing them.
- **Old button art is missing** (e.g. `UI-PlusButton-Up`): draw simple controls instead.

## Layout

- `addon/AzerothGPS/`: the addon itself (Lua 5.1, interface 16001). Load order is in
  `AzerothGPS.toc`.
  - `Core.lua`: settings (`ns.DEFAULTS`), SavedVariables migration, events, API probe.
  - `Geo.lua`: world coordinates and screen maths.
  - `Router.lua`: A* over the road graph, off-road legs, joins across gaps in the road
    network, background terrain searches.
  - `Passability.lua`: terrain grid and walk-around search (coroutines).
  - `Nav.lua`: stops, planning across transports, flights (including from unlearned flight
    masters of your faction) and teleports, following and
    rerouting (keeps the current route when a recalculation is clearly longer), farming
    loops, questing stops (done when their quest areas' quests are), steps text, ETAs.
  - `Turns.lua`: turn-by-turn maneuvers.
  - `Arrow.lua`: the direction arrow window.
  - `GPSFrame.lua`: the map window (layers, fade while moving, click-through, window
    frame, map menu, search, drawing a farming area).
  - `Layers.lua`: quests, quest areas, herbs and ore (gathered, hovered on the minimap,
    right-clicked without the profession, imported; unconfirmed until gathered), and city
    locations guards point out (`C_GossipInfo` points of interest, saved account-wide).
  - `Import.lua`: TomTom `/way` import, export and in-game route sharing.
  - `Taxi.lua`: known flight masters, recorded flight times, the flight being taken.
  - `Teleports.lua`: hearthstone, Astral Recall and class teleports ready right now.
  - `Record.lua`: the player's road fixes, drawn on the map with the road tools (Options >
    Road tools, or `/agps dev`: the "Road tools" toggle, `G.roadMode`: left-drag draws,
    right-drag erases (a loop: everything inside), middle-drag pans, until toggled off;
    `G.FinishRoad`). The wall tools (Options > Wall tools, `G.wallMode`, the "Wall tools"
    button) draw and erase walls the same way; "Show extracted walls" (`showWalls`). Walls (op
    "wall"/"unwall"; shipped as `ns.Walls` in Roads.lua) are handled in Passability
    (`WallLines`, `CrossesWall`, wall cells closed on the grid): nothing walks through them, and roads
    they cross are cut there (`BuildGraph`; a gate is a gap); flights ignore them. The terrain's
    too-steep edges don't cut roads (a road over one is a pass). Saved in
    `ns.db.tracks` on the player's level (`continent` 10001 in Undercity). Routes use them at
    once (`Router.WithTracks`: a drawn road's stretches along an existing road are that road,
    its ends join a road within 25 yd; an erase cuts out the road under it). Drawn roads are
    truth: `agps watch-roads` (or `agps roads`) imports them into `overrides/` on every
    /reload, and `ns.RoadTracksIn` (in Roads.lua) lists the ones the data has, which the
    addon then drops (`Record.Prune`). Drawn roads draw like any road, before and after
    they're in the data. The offline rules match the addon's
    (`graph.DRAWN`, `DRAWN_CITY`); keep them in step.
  - `Feedback.lua`: opt-in road and trip data.
  - `Options.lua`: the paged options window and the minimap button.
  - `Config.lua`: slash commands.
  - `Api.lua`: the public `AzerothGPS` table for companion addons such as
    AzerothGPS-StreetView (`docs/api.md`): geometry, the cursor's world point, overlays drawn
    on the map (`G.overlays`), and showing the road network on request (`G.roadOwners`).
  - `Bindings.xml`: the show/hide map key (loaded by the game, not listed in the toc; the
    names and `AzerothGPS_ToggleMap` are in Core.lua, the Set key button in Options.lua).
  - `Data/*.lua`: generated; don't edit by hand.
  - `Data/Cities.lua` (`app/azerothgps/cities.py`): underground cities as their own routing
    level, a pseudo-continent (Undercity: 10001) drawn in its base continent's coordinates
    (`Geo.Base`, `Geo.ToContinent`), with roads from its walkable floors, a passability
    grid, and lifts as transports. The player is on it when the game reports the city's map
    (`Nav.PlayerLevel`), except in its `upper` areas (the halls at the lifts' tops, by
    subzone name). New stops there get it (`Nav.StopLevel`, `Geo.MapCont`). Offroad goes
    off down there and back on after (`Nav.CityOffroad`, kept per character).
    The grid is each cell's top floor (heights interpolated per triangle, small floors over
    a lower one left out): walls standing on a floor close it, and so does a ledge's foot.
    Stairs between levels are found in 3D and added as roads; drops off ledges are one-way
    roads (`ns.RoadDrops`, taken when `Nav.SafeDrop()` allows). Also written: floor heights
    (`ns.CityHeights`, for "below / above you"), and the Ruins of Lordaeron up top: a grid
    laid over the continent's (`ns.CityHalls[0]`, `overlay = true`: 0 open, 2 closed, 1 the
    continent's there; `Passability.Overlay`) and roads merged into the continent's
    (`ns.RoadOverlays`; continent roads through its walls are dropped). Check changes with a
    3D walk of routes over the heights, not only the 2D grid.
  - `Data/Hostile.lua` (`app/azerothgps/hostile.py`, from the NPC data under
    `data/thirdparty` and the client's FactionTemplate): each faction's guards as circles
    (A: dangerous to Alliance players). Routes pay `Router.HOSTILE_FACTOR` per yard in the
    other faction's reach (road edges, off-road legs, node links, and the terrain search
    in `Passability.FindPath`), so they go around their towns; option "Avoid the other
    faction's towns" (`avoidHostile`).
  - `Data/Caves.lua` (`app/azerothgps/caves.py`, the WMO floor code shared with Undercity in
    `walknet.py`): caves, mines, dens and tunnels on continents 0 and 1 (minor-dungeon WMOs placed
    in the ADTs), merged into the continent's level. Each gets a grid over the continent's
    (`ns.CityHalls[cont]`, `overlay = true`, `cave = true`: 0 open, 1 the continent's, 2 closed,
    3 a floor under walkable ground; its rock under walkable ground is left to the continent's
    grid) and all of a continent's caves' roads are one `ns.RoadOverlays[cont]` entry: `joins`
    (the roads out of the mouths end on a land road; `Router.JoinOnto` splits it there), `bridge`
    (the only cave nodes gap links may use), `drops`. Only collidable faces count (MOPY flags),
    floors are those reached on foot from the ground at the mouth (the model's outdoor groups),
    the lowest per cell. A trip gets on or off a cave's roads only down in it, or on its way
    in when the other end is down in one (`Router.CaveDown`, `CaveLevel`); over a mine under
    a hill the player's level is told by `IsIndoors()` (`Nav.Indoors`), and a stop over its
    floor is taken to be down in it. Terrain walks (`FindPath`) ignore the caves' grids
    (their cells are coarser than a tunnel); `route-check` leaves out trips from or to a
    spot over a cave (its flat reference walk can't judge them).
    `agps caves` renders each one into `data/debug/caves/` with `summary.txt` (covered and
    skipped); `--write` writes the file.
  - `Data/Capitals.lua` (`app/azerothgps/capitals.py`, `CAPITALS`: each city's models (MODF
    ids), gates, check spots): capitals at ground level, whose streets are city models (no road
    textures), merged into the continent's level like the caves. Each gets a grid over the
    continent's (`ns.Terrain["capital_<name>"]`, `overlay = true`, `capital = true`: 0 open, 1
    the continent's, 2 closed) from the floors reached on foot from the ground at its gates,
    the top one per cell (bridges, ramps and tower tops over the streets); stairs and spiral
    ramps between levels are found in 3D (`walknet.build(road_pieces=True)`), and its roads are
    one `ns.RoadOverlays[cont]` entry joined onto the land's road at the gates. Floors under
    the grid's (a street under a bridge, the Cleft of Shadow under the Drag, a hall's ground
    floor) are levels of their own, laid over it like a cave's (`_under<n>` grids, `cave =
    true`, `split` = a height between the two: `Router.CaveDown` takes the player as down
    under when lower (`opts.z`, `Nav.PlayerZ`); a stop there is down, except within 8 yd of
    a flight master or dock, `capitals.up_top_spots`), with their own roads (a `cave` entry,
    no gap links). A straight line (`Passability.Overlay`) goes by the floor over them. A city
    under a mountain (Ironforge, `indoor`) is also written like a cave (its floor under walkable
    land 3, its rock there the continent's; `IsIndoors` tells). A city on its own ground
    (Thunder Bluff's mesas, Darnassus: `ground_above`) takes that ground in too; its gates'
    ways to the land's roads may not cross blocked ground (`join_blocked`), and a lift
    (`lifts`: Thunder Bluff's from Mulgore, shafts from the cmangos DB's "Mesa Elevator") is a
    road from the city's road up top down onto the land's road at its foot, its length
    counting the wait and the ride (`LIFT_SECONDS`). In a
    capital, legs off the roads are straight (no terrain walk: its grid is coarser than the
    streets and blind to levels), gap links through closed cells are shut, and offroad mode
    goes off there (`Nav.CityOffroad`); `route-check` leaves out trips from or to a capital's
    own cells (its flat walk can't judge levels and lifts). `agps capitals` renders each (floors under others
    purple, their roads cyan) into `data/debug/capitals/` with `summary.txt`; `--write` writes
    the file, `--check` routes from outside the gate to every place (CityPlaces, the check's
    own, each named area of the models) and walks the routes in 3D over the floors
    (`capitals.walk_3d`; "!" marks a jump between levels or a long last leg).
  - `Data/Instances.lua` (`app/azerothgps/instances.py`): dungeons and raids, each instance map
    (the client's Map rows with InstanceType 1 or 2) a level of its own like Undercity's:
    **level id = 20000 + its MapID** (the Deadmines, map 36: 20036), in the instance's own world
    coordinates (what the game reports inside). `ns.CityLevels[level]` has `base` = the MapID and
    `instance = true` (`Nav.InstanceLevel`: the game reporting that map as the continent puts the
    player on the level), and the usual `ns.Terrain` (0 open, 1 water to swim, 2 closed; a
    cave's compact rows), `ns.Roads` (points packed like the caves'; `Router.BuildGraph` unpacks
    them), `ns.RoadDrops` and `ns.CityHeights` (rows as runs, `runs = true`) per level. Built by
    `walknet.build` from the global WMO in the map's WDT (a WDT placement has no map offset:
    world X = -z, Y = -x) or the dungeon WMOs its NPCs stand in (ADT maps), with their terrain
    walked from the models' mouths near the NPCs (`GROUND_NEAR`); only floors reached on foot
    from the entrance or a boss are kept (`seeds`); spiral stairs are looked for further
    (`stair_max`); water deep enough to swim is a floor
    at its surface, magma and slime close what's under them. `ns.Instances[level]`: name, map,
    raid, entrances, bosses (name, NPC entry, x, y, z, `enc` = DungeonEncounter IDs, `order` /
    `optional` from `app/azerothgps/data/instance_bosses.json`). Each entrance is a portal in
    `ns.Transports` (kind "portal": continent end where the server's exit teleport puts you,
    else the client's ghost entrance `Map.Corpse`; instance end where its entering teleport puts
    you), so a trip from outside walks to the portal (into a cave or capital when it's in one),
    rides it, and goes on over the instance's roads (`Nav.Plan` takes a portal only for a trip
    from or to inside that instance: never through a dungeon's two entrances as a shortcut).
    On the map (`layerInstances`, the "Dungeons and raids" quick button): entrance icons on
    every style but the world map (one per spot on a continent's map); a click opens the
    instance's map (`G.ShowInstance`: no art here, its floors' outline from
    `G.BlockEdges` at `EDGE_SAMPLES_INSTANCE`, its roads, boss icons numbered in order, the way
    out); right-click or the way-out icon goes back to the entrance (`G.ShowEntrance`). The
    player inside one gets the same view (`G.InstanceOf`, `view.instance`). With no map art
    the frame has no background of its own: `G.DrawFloors` puts a dark one under it and fills
    the floors (the open runs `BlockEdges` also returns, `edges.fill`). Right-click in a city's
    or dungeon's map opened from its icon goes back to the view it was opened from
    (`openedFrom`, `RememberView`). **Boss route** (quick button, `/agps bosses`,
    `G.BossRoute`/`G.BossStops`): the bosses in `order`, optional and dead ones left out, kept
    in that order; a stop with `boss` (its NPC entry) is done when it dies, not on arrival
    (`Nav.BossKilled` from ENCOUNTER_END / BOSS_KILL by DungeonEncounter id or name, and the
    combat log's UNIT_DIED / PARTY_KILL by NPC entry, registered only inside an instance;
    kept per character, `BOSS_KILL_HOURS`). Entrances, bosses (the server's encounters
    and rank 3 NPCs, positions from their spawns) come from the CMaNGOS dump under
    `data/thirdparty`; the AreaTrigger and DungeonEncounter layouts this client has are in
    `app/azerothgps/extract/dbd/` (written by hand). `agps instances` renders each into
    `data/debug/instances/` with `summary.txt` (covered, skipped and why); `--write` writes the
    file; `--check` routes from the entrance to every boss and walks the routes in 3D ("!": a
    jump between levels, a long last leg, yards through closed cells).
  - `Data/CityPlaces.lua`: capitals' service locations (map %), shown once a guard in that
    city has been talked to (`Layers.RevealCity`, account-wide); a stop still comes from
    asking a guard.
  - `Media/*.tga`: our own art: `Logo` (portraits), `Device` (minimap button and the
    addon list icon), `MapMenu` (the eye button), `Dash` (dotted route lines).
- `app/`: Python developer tools (not shipped). They include a CASC/DB2 reader, road
  extraction, `gen-addon-data`, `route-check` (`routecheck.py`) and the tests.
- `overrides/`: fixes for the extracted road network. `roads_<map>.geojson` also takes
  the roads drawn in game (`agps watch-roads` / `agps roads` import them from
  SavedVariables; `roads_10001` is Undercity's, applied in `cities.py`); commit them with
  the regenerated `Data/Roads.lua`. `data/roads_<map>_base.json` is the network before the
  overrides, so re-applying them takes seconds.
- `docs/`: `plan.md` (roadmap), `ingame-tests.md`, `curseforge-description.md` (the
  CurseForge page, Markdown; images are hosted on Imgur).
- `assets/`: the logo and other source art (not shipped).
- `dist/`: release zips (git-ignored).

## Commands

The venv is at `%USERPROFILE%\.venvs\azerothgps`. Run the tools with `agps.cmd`, or with
`python -P -m azerothgps ...` using that venv's Python.

```
agps install-addon     # copy the addon into _classic_beta_\Interface\AddOns (then /reload in game)
agps gen-addon-data    # regenerate addon/AzerothGPS/Data/*.lua from the client (after a patch)
agps roads             # rebuild road networks after editing overrides/
agps probes            # read /agps debug probe results from SavedVariables
agps perf              # read /agps debug perf timings (saved on /reload)
agps feedback          # export opt-in shared roads and trips to data/feedback/
agps route-check        # routing on random trips in every zone; flags detours and cliff cuts
agps caves             # build the caves (renders + summary in data/debug/caves/; --write: Data/Caves.lua)
agps capitals          # build the capitals (renders in data/debug/capitals/; --write: Data/Capitals.lua; --check: 3D route checks)
agps instances         # build the dungeons and raids (renders in data/debug/instances/; --write: Data/Instances.lua; --check: entrance-to-boss 3D checks)
agps watch-roads       # on every /reload: roads drawn in game go into overrides/ and the data, then install
agps import-shared <file>  # roads and walls players copied from the share page ("Copy map data...") into the data
cd app && python -m pytest -q    # tests (the addon's Lua runs under lupa)
```

- Maps covered: Eastern Kingdoms (0), Kalimdor (1), Zephras Isle (2991); the list is
  `CONTINENTS` in `app/azerothgps/extract/pipeline.py`. New WoW Forever zones on their own
  map need adding there, then `agps extract` and `agps gen-addon-data`.
- WoW Forever lives at `C:\Program Files (x86)\World of Warcraft\_classic_beta_`: product
  `wow_classic_beta`, build 1.60.1.70009, interface 16001.
- `gen-addon-data` rewrites the date line in every data file. Revert the files whose only
  change is that line.

## Working on the addon

- **Test pure Lua with lupa** in `app/tests/test_addon_lua.py`. Frames aren't available
  there; keep logic in plain functions (e.g. `G.FadeTarget`, `N.KeepOld`) so it can be
  tested.
- **Lua 5.5 in the tests, 5.1 in the game:**
  - Loop variables are read-only.
  - `%d` needs integers.
  - Use `unpack or table.unpack` and `math.atan2 or math.atan`.
- **After routing or terrain changes, run `agps route-check`** (a few minutes) and expect
  0 flagged trips. Turn anything it finds into a test with the trip's coordinates.
- **Check the full test run before committing.** A new test passing isn't enough; older
  tests can break.
- **Game side:**
  - After `install-addon`, `/reload` picks up changed Lua.
  - **New files, including images, need a full game restart.**
  - Changed images usually need a restart too.
- **Use the game's newer UI templates, with fallbacks.** Old art such as
  `UI-PlusButton-Up` is missing in this client. Prefer drawing simple controls yourself,
  or use the modern templates (`PortraitFrameTemplate` etc.) wrapped in `pcall`, with a
  fallback.
- **Settings:** new ones go in `ns.DEFAULTS` (Core.lua) and on the right options page
  (Options.lua). Renamed keys get a migration in `InitDB`.
- **Performance:** routing runs while the player moves. Keep per-frame work cheap, and run
  heavy terrain searches as coroutines (`Router.Pump`).
  - `/agps debug perf`, then `/reload`, then `agps perf` gives the timings per part.
  - Route calculation is the main cost, not drawing. Don't recalculate on every finished
    search (`Nav.SearchDone` limits it to every 3 s), work out the stretches between stops
    one per call (`N.LATER_PER_CALL`), and keep terrain checks memoized (`Router`'s `SegCost`).
  - Offroad mode's straight links between road nodes (`NodeLinks`, cached) are worked out
    for `NODE_LINK_MS` per route calculation; the rest go to a background job (`LinksNow`)
    and the route is provisional (`pending`) until they're in. A long route reaches
    thousands of nodes: done at once, it froze the game for seconds.
  - A continent's road data is built in the background the first time (`Router.WarmUp`;
    Nav waits for it up to `WARM_WAIT` s). Long loops that can run inside it call
    `Breathe`. Tests set `Router.WARM = false`.
  - Drawing: at most 20 redraws a second; dotted legs are one line each with
    `Media\Dash` repeated along it (`/agps debug dashes` switches back to a line per dash).
- **Shell pitfall:** Bash heredocs and Python string literals collapse `\\` in Lua strings
  (`"Interface\\Icons\\..."`) and turn `\n` into real newlines. Edit such lines with the
  Edit tool, or write the script to a file first.

## Releases

Automated by `.github/workflows/release.yml` on a version tag:
1. Bump `## Version` in `AzerothGPS.toc` and the header in `addon/AzerothGPS/README.txt`.
2. Add a `## <version>` section at the top of `CHANGELOG.md` (Markdown): it becomes the
   release notes on GitHub and the changelog on CurseForge.
3. Commit, then tag and push the tag: `git tag v<version> && git push origin v<version>`.
   The workflow checks the toc matches the tag, builds the zip (single `AzerothGPS/`
   folder, every toc file in it), creates the GitHub release, and uploads to CurseForge
   (project 1712208, "Azeroth GPS v<version>"; `.github/scripts/curseforge.py`, secret
   `CF_API_TOKEN`, game version by name "1.60.1" or the repo variable `CF_GAME_VERSION_ID`).
   Only tag when the user asks for a release. "Run workflow" by hand is a dry run (the
   game version lookup only).
4. Before tagging, check nothing personal is in the repo (the repo is public).

## Commits

The remote is https://github.com/AzerothGPS/AzerothGPS (the only one: push nowhere else). Commit and push
completed work, with short imperative messages.

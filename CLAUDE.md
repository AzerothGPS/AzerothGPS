# AzerothGPS

A car-GPS style navigation addon for **World of Warcraft: Forever**. It draws a map around
the player with routes along the game's roads, turn-by-turn directions, multi-stop trips,
boats, zeppelins and flight paths. It's published on CurseForge as "Azeroth GPS".

## Hard rules (Blizzard ToS / UI Add-On Development Policy)

The addon is going public, so every change must keep it policy-safe:

- **Display only.** Never move the character, click, target, cast, or automate anything.
  The one exception: a secure button the player clicks themselves (`SecureActionButtonTemplate`,
  as action bars are) may use the item or spell the route's next step names (GPSFrame's use
  button: the hearthstone, a teleport). Nothing is ever used without the player's click.
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
- **Party members' positions are given** (probed grouped): `UnitPosition("party1")` returns their
  world position, and the other player needs no addon (`GPS.party.io.members`, round class icons).
- **Old button art is missing** (e.g. `UI-PlusButton-Up`): draw simple controls instead.

## Layout

- `addon/AzerothGPS/`: the addon itself (Lua 5.1, interface 16001). Load order is in
  `AzerothGPS.toc`.
  - `Core.lua`: settings (`ns.DEFAULTS`), SavedVariables migration, events, API probe.
  - `Geo.lua`: world coordinates and screen maths.
  - `Router.lua`: A* over the road graph, off-road legs, joins across gaps in the road
    network, background terrain searches.
  - `Passability.lua`: terrain grid and walk-around search (coroutines). Long walks (start and
    stop `HPA_MIN_CELLS` apart) are searched by blocks, as Shortest Path Forever does: the grid cut
    into 32 x 32-cell blocks, each with its ways through to its neighbors and the walks between
    them inside it, prepared offline (`Data/TerrainHPA.lua`, `agps terrain-hpa`,
    `app/azerothgps/hpa.py`); then only the cells across the blocks on the way (straight lines over
    open ground). No way through the blocks: nil at once (it used to flood the whole box). Blocks
    the player's own walls or erasers change, and their neighbors, are worked out in game
    (`BuildBlock`, the same rule as hpa.py's: keep them in step). The prepared data has a `stamp`
    of what it's made from (the grid, the grids laid over it, the shipped walls): `install-addon`
    prepares it again when that changed, and a test fails when it's stale.
  - `Nav.lua`: stops, planning across transports, flights (including from unlearned flight
    masters of your faction) and teleports, following and
    rerouting (keeps the current route when a recalculation is clearly longer), farming
    loops, questing stops (done when their quest areas' quests are), steps text, ETAs. Speeds
    (`N.Speeds`): the plain run speed (seen on foot, the Speed stat in it), mounts, and movement
    abilities (`N.MOVE_ABILITIES`, `N.MoveAbility`: its time beside walking; while on, it's the
    walking speed; learned per character in `moveSpeeds`). The walked part behind the player is
    trimmed off every `TRIM_MOVED_YD` between recalculations (`Follow(r, x, y, ahead)`).
  - `Turns.lua`: turn-by-turn maneuvers.
  - `Arrow.lua`: the direction arrow window.
  - `GPSFrame.lua`: the map window (layers, fade while moving, click-through, window
    frame, map menu, search, drawing a farming area).
    Inside maps (`G.FindInterior`): a model's indoor rooms only (or where the game says indoors;
    down in an underground city, any of its rooms); indoors the inside map shows at any zoom,
    outdoors up to `INTERIOR_MAX_ZOOM`. Never from Stormwind's city model (`G.NO_INSIDE_MAP`: its
    streets have art and district names too, and it looks worse than the terrain). In a city (a
    capital's own cells, down in an underground city) its inside map shows at any zoom, and the wheel
    zooms out no further than `CITY_MAX_ZOOM` (`G.cityMap`; zoomed further out on the way in, zoomed
    in to it): right-click for the land around. The title (the coordinates line's place) names the
    city there (`G.CityMapAt`: the ground's zone is the land's, Dun Morogh over Ironforge).
  - `Layers.lua`: quests, quest areas, herbs and ore (gathered, hovered on the minimap,
    right-clicked without the profession, imported; unconfirmed until gathered), and city
    locations guards point out (`C_GossipInfo` points of interest, saved account-wide).
  - `Import.lua`: TomTom `/way` import, export and in-game route sharing.
    Developer hooks for the private dev addon (`AzerothGPS_Dev`, repo AzerothGPS/AzerothGPS-Dev,
    checked out next to this one, installed with `agps install-addon --dev`, never shipped):
    `AzerothGPS_Extend(fn)` (Core.lua: fn(ns) after login), `Import.io.send` (the only way out),
    `Import.OnAddonMessage` (messages in), `Import.Offer` (the popup), `GPS.party.io.members` (party
    members' positions for the map's party dots, option `showParty`). Keep them small; if the
    dev addon needs more, add a hook here with a test rather than copying code there.
  - `Taxi.lua`: known flight masters, recorded flight times, the flight being taken. Zeppelins'
    and boats' timetables: Data/Transports.lua has each one's `cycle` (the server's, from the
    CMaNGOS dump's `transports` periods, else the path's estimate), `ride1`/`ride2`, `wait1`/`wait2`;
    the game doesn't tell addons where a transport is, so a departure is learned when the player
    rides one (`TransportTick`: near a dock, then carried off it without walking, two checks in a
    row), kept per realm in `ns.db.transports`, and `TransportTimes` gives the next arrival and
    departure at either dock. The map shows every dock with points of interest on (`G.DockTimes`:
    the countdown under the icon; double-click for a stop).
  - `Teleports.lua`: hearthstone, Astral Recall, class teleports and the engineers' teleporters
    (`T.ITEMS`, with the specialization each needs) ready right now. Each row carries its `item`
    or `spell`: when the route starts with one (`Nav.UseNow`), the directions panel shows a use
    button (`G.MakeUseButton`, `G.UpdateUseButton`): a secure button parented to UIParent (the map
    may hide in combat), set only out of combat and hidden on PLAYER_REGEN_DISABLED.
  - `Record.lua`: the player's road fixes, drawn on the map with the road tools (Options >
    Tools, or `/agps dev`: the "Road tools" toggle, `G.roadMode`: left-drag draws,
    right-drag erases (a loop: everything inside), middle-drag pans, until toggled off;
    `G.FinishRoad`). The wall tools (Options > Tools, `G.wallMode`, the "Wall tools"
    button) draw and erase walls the same way. The road tools on show the road network, the wall
    tools the walls; with the tools off, the "Show Roads and Walls" map button under Undo
    (`showMapData`, `G.ToggleMapData`: `showRoads` and `showWalls` together; also /agps roads|walls).
    Undo takes back the last road or wall change: they're one list (`ns.db.tracks`), in the order
    drawn. Walls (op
    "wall"/"unwall"; shipped as `ns.Walls` in Roads.lua) are handled in Passability
    (`WallLines`, `CrossesWall`, wall cells closed on the grid): nothing walks through them, and roads
    they cross are cut there (`BuildGraph`; a gate is a gap); flights ignore them. The terrain's
    too-steep edges don't cut roads (a road over one is a pass). Saved in
    `ns.db.tracks` on the player's level (`continent` 10001 in Undercity). While the road or wall
    tools are on, edits aren't built into the network (`Record.pending`: the map draws them over the
    roads as they were, only what's in view); turning the tools off rebuilds it once (`Record.Apply`).
    Routes use them from then (`Router.WithTracks`: a drawn road's stretches along an existing road are that road,
    its ends join a road within 25 yd; an erase cuts out the road under it). Drawn roads are
    truth: `agps watch-roads` (or `agps roads`) imports them into `overrides/` on every
    /reload, and `ns.RoadTracksIn` (in Roads.lua) lists the ones the data has, which the
    addon then drops (`Record.Prune`). Drawn roads draw like any road, before and after
    they're in the data. The offline rules match the addon's
    (`graph.DRAWN`, `DRAWN_CITY`); keep them in step.
    **Floors over floors** (Undercity's level with heights; on a continent, a cave's or a capital's
    floor under walkable ground, their grids' 3): a stroke records the player's floor (`G.EditFloor`:
    `z`, `indoors`, and `down` on a continent, only for a stroke over a capital's or cave's grid), and
    changes that floor's roads only (`Router.WithTracks`' `onFloor`: of the roads within the edit's reach
    or `FLOOR_STACK_YD` of the stroke's spot, as they were before the stroke, those about at the height
    of the one nearest the player's; on a continent `CaveFloorOK`). Split and cut roads keep their cave
    and drop marks (`roads.cave`/`roads.drop`), and a road drawn down in a cave is one of its roads.
    Walls with a floor cut only that floor's roads (`Passability.CrossesWall`/`WallHit`'s `ok`), and a
    wall eraser takes out walls drawn within `WALL_FLOOR_Z` of its height. With the tools on, the hint
    says the player's floor (`G.FloorText`, `G.FloorHere`, kept up to date by `G.RefreshFloorHint`)
    and other floors' roads and walls draw faint (`G.OtherFloor`: the graph's `otherFloors`, made in
    BuildGraph from `floorsAt` for an underground city). Offline: `roads.graph.LayerFloors`
    (`cities.py`), `capitals.drawn_fixes` (a `down` edit over a floor under the city goes on those
    roads), `caves.drawn_fixes` (a `down` edit mostly over a cave's own cells goes on its roads, in
    `build_continent`: after one, `caves --write`), `finish_continent` (a `down` erasure leaves the
    land's roads); imports and the share text carry `z`, `indoors`, `down`.
  - `Feedback.lua`: opt-in road and trip data.
  - `Options.lua`: the paged options window and the minimap button.
  - `Config.lua`: slash commands.
  - `Api.lua`: the public `AzerothGPS` table for companion addons such as
    AzerothGPS-StreetView (`docs/api.md`): geometry, the cursor's world point, overlays drawn
    on the map (`G.overlays`), showing the road network on request (`G.roadOwners`), and holding
    the map for a game on it (`G.holders`, `G.Held`: no route lines, pins, crosshair or top panel;
    double-clicks go to the holder).
  - `Bindings.xml`: the show/hide map key (loaded by the game, not listed in the toc; the
    names and `AzerothGPS_ToggleMap` are in Core.lua, the Set key button in Options.lua).
  - `Data/*.lua`: generated; don't edit by hand.
  - `Data/Cities.lua` (`app/azerothgps/cities.py`): underground cities as their own routing
    level, a pseudo-continent (Undercity: 10001) drawn in its base continent's coordinates
    (`Geo.Base`, `Geo.ToContinent`), with roads from its walkable floors, a passability
    grid, and lifts as transports. The player is on it when the game reports the city's map
    (`Nav.PlayerLevel`), except in its `upper` areas (the halls at the lifts' tops, by
    subzone name). New stops there get it (`Nav.StopLevel`, `Geo.MapCont`).
    The grid is each cell's top floor (heights interpolated per triangle, small floors over
    a lower one left out): walls standing on a floor close it, and so does a ledge's foot.
    Its roads are on every floor (floors over floors, `layers.py`, `cities.LAYERED`), from the
    faces a character collides with (the MPY2 flags; collision faces are often wound upside
    down, the drawn floors over them decoration): doorways' gaps in the floor filled
    (`fill_seams`), stairs between floors traced through the floor voxels, each city place
    (CityPlaces' heights) joined by a road over its floor (`spurs`), and roads added where the
    floors go and the roads went round (`complete`). Each node has its height (Roads' `z`, the
    game's: the model's plus `zoff`), and a road a node where its height bends: the Router takes
    the level as layered (roads only; start and stop on their floors by the player's and the
    stop's heights, `Nav.StopZ`; a lift's city end `z1`; legs off the roads dear past a few
    yards, `LAYER_LEG_FACTOR`). No drops there now. Also written: floor heights
    (`ns.CityHeights`, for "below / above you"), and the Ruins of Lordaeron up top: a grid
    laid over the continent's (`ns.CityHalls[0]`, `overlay = true`: 0 open, 2 closed, 1 the
    continent's there; `Passability.Overlay`) and roads merged into the continent's
    (`ns.RoadOverlays`; continent roads through its walls are dropped). Check changes with a
    3D walk of routes over the floors, every place to every other (not only the 2D grid).
  - `Data/Hostile.lua` (`app/azerothgps/hostile.py`, from the NPC data under
    `data/thirdparty` and the client's FactionTemplate): each faction's guards as circles
    (A: dangerous to Alliance players). Routes pay `Router.HOSTILE_FACTOR` per yard in the
    other faction's reach (road edges, off-road legs, node links, and the terrain search
    in `Passability.FindPath`), so they go around their towns; option "Avoid the other
    faction's towns" (`avoidHostile`).
  - `Data/Buildings.lua` (`app/azerothgps/buildings.py`, `agps buildings --write`; `--render X Y R` for a
    picture): the continents' buildings (models placed in the ADTs, not caves, capitals or anything
    over `MAX_SIZE_YD`) as grid cells routes don't walk through. Each model's solid faces are cut at a
    body's height over the ground (its walls and door gaps), doorways closed and the inside filled up
    to a hall's size (a fort's yard stays open), and a cell of the continent's grid blocked where that
    covers `BLOCK_SHARE` of it (and each building's best-covered cell); a cell a shipped road runs
    through stays open (so run it again after road changes). `Passability`'s `Cell` adds them
    (`ns.BuildingCells`, runs per row; `P.Buildings(g)` the set, made at first read), so legs, the
    walk search and the prepared blocks (hpa.py stamps them) all go round. No end slack over a
    building's cells (`SegmentCost`, `FindPath`) unless that end is in a building itself (a stop at
    the innkeeper); a wall eraser opens them as it opens the terrain's.
  - `Data/Zones.lua` (`addon_data.zones_lua`, from the ADTs' area ids): each continent's zone
    (uiMap) per ground chunk, run-length rows (`Router.ZoneAt`, `ZoneYards`). Zones too high
    for the character (option `avoidHighZones`, on by default: lowest level more than
    `LEVEL_RED` above theirs, `Router.RedZones`, levels from `C_Map.GetMapLevels` or
    `GPS.ZONE_LEVELS`) cost `LEVEL_FACTOR` per yard on roads (`g.zones` per edge), gap links,
    node links and legs, not in the zones the route starts and ends in; an open straight line
    through one isn't taken at once but weighed. A route to a stop in one asks first
    (`Nav.RedStops`, `GPS.ConfirmRedZone`: "route there anyway?"; `SetStops`/`AddStop` return
    false, true while asking), not for the zone the player is in.
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
    one `ns.RoadOverlays[cont]` entry joined onto the land's road at the gates (a gate whose roads the
    drawn fixes erased has none: `capitals --write` warns, and a road drawn in game through the gate is
    the way out; the merge in `Router.BuildGraph` drops the land's roads through a city's closed cells,
    but never a drawn one, source 2: Stormwind's gate road went once shipped). Those roads are its
    **streets** (`capitals.streets`): of the floors' roads (every square's middle, a jumble), the
    edges along the NPCs' walks (`patrol_points`, the path files `agps npc-paths` reads;
    `STREET_*`), the shortest ways between every two of its gates, places (CityPlaces, the check's,
    the named areas) and lifts, and the city edges the floors under others join; the rest dropped.
    The terrain's water over the city (`terrain_liquids`, MH2O) counts like the models' (no floor
    under it). The land's roads are cut where they run over a model-built capital's core
    (`roads.build.cut_capitals` / `capital_cores`, in `finish_continent`: its own cells less
    `CUT_MARGIN_YD` in from its outer edge, so the roads up to its gates stay; Stormwind, Ironforge,
    Orgrimmar, not the cities on their own ground). Roads drawn in game stay among the land's whole,
    and `capitals.drawn_fixes` puts them on the capital's roads too: a drawn road mostly over its core,
    an erasure touching it anywhere (the watcher's import alone left a city's erasures unapplied).
    After road edits: roads (`reapply_overrides`), then `capitals --write`, then `buildings
    --write`, then `terrain-hpa`. Floors under
    the grid's (a street under a bridge, the Cleft of Shadow under the Drag, a hall's ground
    floor) are levels of their own, laid over it like a cave's (`_under<n>` grids, `cave =
    true`, `split` = a height between the two: `Router.CaveDown` takes the player as down
    under when lower (`opts.z`, `Nav.PlayerZ`); a stop there is down, except within 8 yd of
    a flight master or dock, `capitals.up_top_spots`), with their own roads (a `cave` entry,
    no gap links). A straight line (`Passability.Overlay`) goes by the floor over them. A city
    under a mountain (Ironforge, `indoor`) is also written like a cave (its floor under walkable
    land 3, its rock there the continent's), and its grid has a `zsplit` (between its floor and the
    ground over it: lower, down in the city, `Router.CaveDown`; `IsIndoors` said outdoors in its halls
    and routes took the mountain over it). A city on its own ground
    (Thunder Bluff's mesas, Darnassus: `ground_above`) takes that ground in too; its gates'
    ways to the land's roads may not cross blocked ground (`join_blocked`), and a lift
    (`lifts`: Thunder Bluff's from Mulgore, shafts from the cmangos DB's "Mesa Elevator") is a
    road from the city's road up top down onto the land's road at its foot, its length
    counting the wait and the ride (`LIFT_SECONDS`). In a
    capital, legs off the roads are straight (no terrain walk: its grid is coarser than the
    streets and blind to levels), gap links through closed cells are shut, and no joining the
    roads partway (`Router`'s `JOIN_ALONG_MAX` joins skip capitals, cities and caves); `route-check` leaves out trips from or to a capital's
    own cells (its flat walk can't judge levels and lifts). `agps capitals` renders each (floors under others
    purple, their roads cyan) into `data/debug/capitals/` with `summary.txt`; `--write` writes
    the file, `--check` routes from outside the gate to every place (CityPlaces, the check's
    own, each named area of the models) and walks the routes in 3D over the floors
    (`capitals.walk_3d`; "!" marks a jump between levels or a long last leg).
  - `Data/Transit.lua` (`agps transit --write`, `instances.TRANSIT_MAPS`): maps the game puts you on
    between places (the Deeprun Tram, map 369): a level like an instance's (`instance`, `transit`: no
    entrances, bosses or roads), its models' art, so the map shows it as a dungeon's; its name in the
    title. The ride between the cities is still `Data/Transports.lua`'s tram.
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
    player inside one gets the same view (`G.InstanceOf`, `view.instance`). Its art is the
    game's own minimap images of its models (the WMO interior maps, as buildings'), written to
    the end of `Instances.lua` as `ns.WMOs` / `ns.Interiors[map id]` (`interiors.build_places`
    over the instance's models, `places_lua`): `G.LayoutInstanceArt` draws every floor (higher
    over lower), or the player's floor while they're in it (`G.FindInterior` by height). The
    frame has no background of its own: `G.DrawFloors` puts a dark one under a dungeon's map,
    and where it has no art fills its floors (the open runs `BlockEdges` also returns,
    `edges.fill`) and outlines them. Right-click in a city's
    or dungeon's map opened from its icon goes back to the view it was opened from
    (`openedFrom`, `RememberView`; kept over a /reload by `SaveView`). **Floors:** a dungeon's
    art rooms grouped by height into floors that lie over each other (`G.InstanceFloors`:
    `FLOOR_GAP`, `FLOOR_STACK`, `FLOOR_MIN_SHARE`); the mouse wheel steps them (`G.FloorWheel`:
    in = down a floor, out = up, all floors past the top; past the ends it zooms, and zooming
    back returns to where the floors were stepped); the player in it sees their floor by height
    (`G.ShownFloor`); bosses on other floors are faint. **Dungeon route** (option
    `dungeonRoute`, the map menu's toggle, `/agps dungeonroute`): entering a dungeon or raid
    (PLAYER_ENTERING_WORLD → `G.DungeonEntered`) starts its boss route when the game gives the
    position in there, leaving it ends it; while it's set in there, other routes are held off
    (`Nav.DungeonLocked`: `SetStops`/`AddStop`/`SetLoop` refuse unless `force`, the map's route
    buttons say why). **Boss route** (quick button, `/agps bosses`,
    `G.BossRoute`/`G.BossStops`): the bosses in `order`, optional and dead ones left out, kept
    in that order; a stop with `boss` (its NPC entry) is done when it dies, not on arrival
    (`Nav.BossKilled` from ENCOUNTER_END / BOSS_KILL by DungeonEncounter id or name, and the
    combat log's UNIT_DIED / PARTY_KILL by NPC entry, registered only inside an instance;
    kept per character, `BOSS_KILL_HOURS`). **The position is hidden in dungeons** (probed in
    Ragefire Chasm: `UnitPosition`, `GetPlayerFacing`, `C_Map.GetBestMapForUnit` all nil; speed
    and `GetInstanceInfo` given), so there's no dead reckoning: the map puts up the dungeon's
    map (`hiddenShown`, from `Nav.CurrentInstance`) with no arrow and no route from the player,
    and shows the run's progress: `G.NextBoss` (the first in `G.BossOrder` not dead), the
    usual way's stretches to bosses down faded and the one to the next bright (`SuggestedPath`'s
    `legs`), bosses down faint and "Defeated". **Floors over floors** (`app/azerothgps/layers.py`):
    the floors reached (walknet's bands) split into layers, each at most one floor per cell;
    roads per layer, a layer's road pieces joined over its floor, layers joined where they meet
    (and through bits too small for roads), pieces with the way in or a boss joined across the
    smallest gap (`GAP_MAX`); `ns.Roads[level].z` holds each node's height, portals' `iz`, the
    entrances' 6th value. In `Router` such a level is `layered`: roads only, the start and stop
    snapped to roads at their heights (`opts.z`/`opts.tz`, `NearestEdges(..., z)`, `LAYER_Z`), gap
    links only on one floor, straight only on one floor; routes carry `zs`, and
    `G.FloorChanges` puts stairs icons (up/down) where the route climbs a floor. **In through another dungeon** (Blackwing
    Lair, from Upper Blackrock Spire's orb): its entrance is a portal on that dungeon's level (the
    server's teleport from a trigger inside it), its icon on the continent at the client's ghost
    way in (`ghost`), and `Nav.Plan` allows the chain (a portal into a dungeon that holds the
    destination's way in). **WoW Forever's own dungeons and raids** (`instances.terrain_instances`):
    no spawns or entrances in the server data, none in the client (its encounter journal tables
    are empty), so their map only: the terrain's minimap tiles (`ns.MinimapTiles[map id]`, drawn
    by `G.LayoutMinimap`; `G.InstanceBounds` from the tiles), bosses from DungeonEncounter
    (names, IDs, order; no spots: no icons or boss route, kills counted by name, `Nav.BossKey`),
    entrances from `overrides/instance_entrances.json` (researched, and learned in game:
    `Taxi.NoteEntrance` records where the player stood before the loading screen, shared as
    "E map continent x,y" lines, `agps entrances` / `import-shared` merge them). Entrances, bosses (the server's encounters
    and rank 3 NPCs, positions from their spawns) come from the CMaNGOS dump under
    `data/thirdparty`; the AreaTrigger and DungeonEncounter layouts this client has are in
    `app/azerothgps/extract/dbd/` (written by hand). `agps instances` renders each into
    `data/debug/instances/` with `summary.txt` (covered, skipped and why); `--write` writes the
    file; `--check` routes from the entrance to every boss and walks the routes in 3D ("!": a
    jump between levels, a long last leg, yards through closed cells).
  - `Data/CityPlaces.lua`: capitals' service locations (map %), shown once a guard in that
    city has been talked to (`Layers.RevealCity`, account-wide); a stop still comes from
    asking a guard. Each has a 4th value, its NPC's height (world yards, from the CMaNGOS
    dump's spawns: `agps city-places`, `cityplaces.py`), carried to its stop (`d.z`): where
    floors lie over each other it tells the floor (Router's city floor check, `CaveDown`, the
    height hint). Undercity's heights in Cities.lua are its model's own: the game's less
    `CityLevels[10001].zoff`; the player's own height (`Nav.PlayerCityZ`) tells their floor.
  - `Media/*.tga`: our own art: the windows' corner logo, pre-scaled by `agps media`
    (`app/azerothgps/media.py`, from `assets/logo.png`), the size nearest its pixels on the screen
    shown 1:1 (Core.lua `ns.PortraitPx`): `CornerLogo<px>` (the default: on a plate cut to its outline,
    no circle, the border without the portrait's ring; dragging it moves the window) or `Portrait<px>`
    (option `roundLogo`: in the round portrait); `ns.SetLogoPortrait`, `ns.ApplyLogoLook`. `Device` (minimap button and the
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
agps route-sweep        # random trips routed as in game (background searches, moving): snapbacks, U-turns, spikes
agps trip-sweep         # random trips planned and followed with the whole addon (gameharness): flights vs walks at
                        # random levels, detours, frame budget; data/debug/trip-sweep/report.json (nightly task too)
agps buildings         # buildings as ground routes don't walk through (--write: Data/Buildings.lua; --render X Y R)
agps media             # the corner logo in sizes from assets/logo.png (Media/CornerLogo<px>.tga, Portrait<px>.tga)
agps caves             # build the caves (renders + summary in data/debug/caves/; --write: Data/Caves.lua)
agps capitals          # build the capitals (renders in data/debug/capitals/; --write: Data/Capitals.lua; --check: 3D route checks)
agps instances         # build the dungeons and raids (renders in data/debug/instances/; --write: Data/Instances.lua; --check: entrance-to-boss 3D checks)
agps watch-roads       # on every /reload: roads drawn in game go into overrides/ and the data, then install
agps terrain-hpa        # prepare the terrain's blocks for the walk search (install-addon does it when stale)
agps city-places       # the capitals' service locations' heights from their NPCs (after adding places)
agps import-shared <file>  # roads and walls players copied from the share page ("Copy map data...") into the data
cd app && python -m pytest -q    # tests (the addon's Lua runs under lupa)
```

- Maps covered: Eastern Kingdoms (0), Kalimdor (1), Zephras Isle (2991); the list is
  `CONTINENTS` in `app/azerothgps/extract/pipeline.py`. New WoW Forever zones on their own
  map need adding there, then `agps extract` and `agps gen-addon-data`.
- WoW Forever lives at `C:\Program Files (x86)\World of Warcraft\_classic_beta_`: product
  `wow_classic_beta`, build 1.60.1.70058, interface 16001.
- `gen-addon-data` rewrites the date line in every data file. Revert the files whose only
  change is that line.

## Working on the addon

- **Test pure Lua with lupa** in `app/tests/test_addon_lua.py`. Frames aren't available
  there; keep logic in plain functions (e.g. `G.FadeTarget`, `N.KeepOld`) so it can be
  tested.
- **A file-level `local` is only visible below its declaration.** A function written above
  it (e.g. a map handler calling a `local function` defined further down) reads a nil
  global instead, and fails only when called, so a load-only test won't catch it. Declare
  the local first (`local Foo` near the top, `Foo = function() ... end` later), and test the
  handler by calling it.
- **Lua 5.1's limits are tighter:** a function may use at most 60 variables from outside it
  (upvalues) and have 200 locals. `G.Init` is near the 60: group new file-level locals it uses
  into a table (like `fl`). The whole file fails to load in game otherwise (the map never
  opens), and Lua 5.5 in the tests allows 255; `test_every_addon_file_compiles_under_the_games_lua_5_1`
  compiles every file with lupa's Lua 5.1.
- **Lua 5.5 in the tests, 5.1 in the game:**
  - Loop variables are read-only.
  - `%d` needs integers.
  - Use `unpack or table.unpack` and `math.atan2 or math.atan`.
- **After routing or terrain changes, run `agps route-check`** (a few minutes) and expect
  0 flagged trips. Turn anything it finds into a test with the trip's coordinates.
- **Check the full test run before committing.** A new test passing isn't enough; older
  tests can break.
- **A bug that comes back, or a kind of bug, gets a test that fails on it**, so a later change
  can't bring it back unnoticed:
  - `test_frame_budget.py`: lag spikes. Background work must pause often (every slice under
    `FRAME_MS`), and showing the roads never builds them in the frame. Add a case for any new
    long job (a new data build, a new warm-up step).
  - `test_lua_lint.py`: the forward-reference trap (a file-level `local` used above its declaration).
  - `test_every_addon_file_compiles_under_the_games_lua_5_1`: the 60-upvalue limit.
  - `test_terrain_hpa.py`: stale prepared terrain blocks.
  - `test_road_display.py`: roads vanishing zoomed out, or while being rebuilt after an edit.
  - `test_map_redraw.py`: the map's setup and redraw, and the options window (every page), run under
    Lua 5.1 with a stand-in for the game's UI (`app/azerothgps/gameharness.py` + `wowmock.lua`: add what a new game call needs there). In the game a redraw
    failing is caught and nothing after the failing line is drawn (no route, no panel).
  - `test_lua_lint.py`'s `truncated_and_or`: `x, y = a and f()` (only f's first value).
  - Gap links between far-apart road pieces are picked from samples by place (`Bridges`,
    `BRIDGE_SAMPLE_YD`), not node number: roads edited in one city once changed a route across
    the continent (`test_offroad_joins_the_road_partway_along`).

  Check that a new test fails without the fix before trusting it.
- **Game side:**
  - After `install-addon`, `/reload` picks up changed Lua.
  - **New Lua files (in the toc) need a full game restart.** New images have loaded after a
    `/reload` (Media/CornerLogo<px>.tga, 2026-09-30): try `/reload` first.
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
  - A walk around an obstacle is searched in the background. Meanwhile a leg blocked for
    no more than `PENDING_BLOCKED_YD` counts as about straight (`PendingCost`), not the long
    way by the roads (that showed as a U-turn away from the stop), and a walk found from
    where the player just was is joined straight onto (`Reuse`, `WALK_REUSE_YD`) instead of
    searched again from each new spot.
  - Offroad mode's straight links between road nodes (`NodeLinks`, cached) are worked out
    for `NODE_LINK_MS` per route calculation; the rest go to a background job (`LinksNow`)
    and the route is provisional (`pending`) until they're in. A long route reaches
    thousands of nodes: done at once, it froze the game for seconds.
  - A continent's road data is built in the background the first time (`Router.WarmUp`;
    Nav waits for it up to `WARM_WAIT` s). Long loops that can run inside it call
    `Breathe`. Tests set `Router.WARM = false`.
  - Drawing: at most `hz` (20) redraws a second; dotted legs are one line each with
    `Media\Dash` repeated along it (`/agps debug dashes` switches back to a line per dash).
  - **Options > Performance** (for slower PCs): `hz` (map redraws per second: the biggest saving,
    about half the redraw work at 10), `rerouteSeconds` (`Nav.RerouteTiming`: a route the player
    left is worked out again at most this often; the yards moved and the finished-search
    recalculation scale with it), `stopsAhead` (stops routed and drawn ahead: only on this page),
    `gentleBackground` (`GPS.PumpBudget`: smaller background slices, `GENTLE_*`) and `arrowHz` (the
    arrow turned that often; 0: every frame). "Use Low-End Settings" (`Options.LOW_END`) and
    "Restore Defaults" set them. The page shows the addon's share of the time from `ns.PerfTotal`,
    the sum of `ns.PERF_TOP` (the timings that don't overlap): a new top-level timing goes there.
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

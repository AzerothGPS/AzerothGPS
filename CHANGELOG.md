# Changelog

Each version's section is its release notes (GitHub and CurseForge).

## 1.1.0

For WoW Forever client 1.60.1 (interface 16001). A new data file is included, so fully restart the game after updating, rather than just /reload.

### New

- **Joining the roads where they're heading:** off the road, a route now joins it where it's going (across open ground, around fences and buildings), not back at its nearest point and round. Walk off the way drawn to the road and it's worked out again from where you are, so the join point moves with you. A short walk over open ground goes straight. This replaces the experimental off-road shortcuts, and their option is gone.
- **Buildings are in the way:** routes go around buildings (Goldshire's inn, farmhouses, towers), not through them. A stop inside one, like an innkeeper, is still reached.
- **Flight paths to learn on the way:** when your walk passes a flight master of your faction you haven't learned, a brown line shows the detour to it and the steps list it where the walk passes ("Detour 388 yd to learn the flight path at Tarren Mill", or "Learn the flight path at … (on the way)"). Right-click the flight master's icon, **Remove?**, to skip it for this route.
- **Pins:** Shift + left-click on the map, **Create Pin**, then name it and pick any icon the game has (the same list a macro uses). Where floors lie over each other (a dungeon, Undercity, a cave), pick its floor too; one on another floor than the map shows is drawn faint. Double-click a pin for a stop there, like a city location; right-click it to remove it. Kept for all your characters, and shared with your map data (**Copy Map Data...**) like roads and walls. Options → Tools: **Pinning** (on by default); Options → Map: **Pins**.
- **Pick what Copy Map Data... includes:** Roads, Walls, Routes and Pins, each with how many you have, all ticked unless you untick one (in the copy window, or on the Help improve page). **Routes** are the faster trips **Share faster trips** keeps, which can now be shared this way too. Dungeon entrances you found always go along.
- While the route is being worked out, now and then it's said in Murloc (one time in twenty: Mrglglglgl), one time in five the gnome engineers are at it ("Spinning up the Route-o-Tron 3000..."), and another one in five the goblins ("Time is money, friend! Routing...").
- **New defaults:** the map is 450 wide, and in combat it stays shown, fully opaque, and clickable (Options → Opacity; your own settings stay as they are, Reset to defaults takes these).
- **Stairs in the directions:** in the capitals, Undercity and dungeons, the directions say the stairs and ramps between levels, with the turn after them: "Stairs up in 10 yd, then turn left". The bends of a spiral stair aren't called out as turns.
- **Leave a ride out of a route:** every flight, boat, zeppelin, tram and teleport a route takes has its icon where you board it. Right-click it, **Remove?**, and the route is worked out again without it, and it stays out while you follow this route (rerouting and /reload too) until you set a new one. For a flight, each flight master it flies over has its own icon, and removing one leaves out just that connection; any other flight over it can't be taken on this route either.
- **Use your hearthstone or a teleport from the directions:** when a route starts with one, a button with its icon sits in the directions panel's corner; your click uses it (nothing is ever used without it, and it hides in combat). New teleports: the engineers' **Dimensional Ripper - Everlook** and **Ultrasafe Transporter: Gadgetzan**. A hearthstone or teleport is only suggested when it saves more than 800 yd.
- **Performance options** (Options → Performance) for slower PCs, with how much of the time AzerothGPS is using shown live:
  - **Map redraws per second** (5 to 30, default 20): the biggest saving; at 10 the map needs about half the work.
  - **Work out a route you've left at most every** 2 to 10 seconds.
  - **Stops routed and drawn ahead** (1 to 8, default 3): how many stops are worked out and drawn at a time. Every stop keeps its marker and its place in the fastest order; the ones further on are listed with an estimated distance until they're routed.
  - **Gentle background work:** fewer stutters, while routes take a moment longer to appear.
  - **Turn the arrow every frame,** or 20 times a second.
  - **Use Low-End Settings** sets them all lighter at once; **Restore Defaults** puts them back.
- **Party and raid members on the map,** as round class icons in their class's color (Options → Map, Party members). They don't need AzerothGPS themselves.
- **Movement abilities in travel times:** Ghost Wolf, Travel Form, Cat Form with Feline Swiftness, and Aspect of the Cheetah or the Pack show their time beside walking, and become the walking time while on.
- **The Deeprun Tram** between Stormwind and Ironforge, for Alliance characters.
- **Undercity, floor by floor:** routes follow every floor (walkways over the bank's level, the canal walks under the bridges, the Magic Quarter's rooms), picked by your height and the stop's. Trips across the city are shorter, and no longer go through floors, over the canals' rims, or out over the Ruins' walls.
- **Cave and mine entrances on the map** (double-click one for a stop), in the map menu's new **Caves/Dungeons/Raids** group.
- **Blackwing Lair** (through Upper Blackrock Spire) and **WoW Forever's own dungeons and raids:** their maps, bosses and entrances. Entrances not known yet are learned when you go in; share them with **Copy Map Data...**.
- **Zephras Isle on the world map:** a framed picture at the top; click it to open the island. On a continent's map, the zone under the pointer lights up.
- **A route to another continent** is shown on the world map first, then the map follows you again.
- **Heading-up:** with "Turn the map with me" on, your arrow sits low on the map, so more of the way ahead shows.
- **Right-click inside a building** shows the outside view first; the next right-click, the continent's map.
- **Capitals' districts named on the map** when zoomed in, as Undercity's are: Stormwind's Trade District and Old Town, Orgrimmar's Valleys and The Drag, Ironforge's Wards, Thunder Bluff's Rises, Darnassus's Terraces.
- **City places** a guard showed you can be double-clicked into stops, and a stop down in a city takes the lift.
- **More roads** on Eastern Kingdoms, drawn in game.
- **Road and wall tools:** the road tools show the road network while they're on (the wall tools already showed the walls), and "Show extracted roads" and "Show extracted walls" are one map button now, **Show Roads and Walls**, under Undo. Undo takes back your last road or wall change, whichever came last.
- **Editing floors over floors** (Undercity, the floors under Orgrimmar's Drag and Stormwind's bridges, caves and mines): with the road or wall tools on, **Shift + mouse wheel** picks the floor you edit, from the floors where the map is centered (the game doesn't tell addons your height). The hint under the map says which ("Editing: floor 2 of 3 here", or all floors), its roads and walls draw bright and the others faint, and what you draw or erase changes that floor only. Turning the tools off goes back to all floors.
- **For other addons:** API versions 3 to 11 (HoldMap, with a map style held while it's on; icons in overlays; popup windows in AzerothGPS's style; LookAt, Follow, ShowMap, ShowWorld, ToContinent, SaveView and RestoreView, TopPanelInset). See docs/api.md.

### Changed

- **Flights at a low level:** a flight is weighed against the walk as it's actually routed, not a straight line, so a route flies when walking would go the long way round zones too high for you (e.g. from Brill into Arathi Highlands at level 14).
- With the window frame on, the place's name ("Undercity") is in its title bar, in place of "AzerothGPS"; the coordinates stay at the bottom of the map. Without the frame, both are at the bottom as before.
- The directions say what to do now, then the next turn: "Continue straight, then slight right in 13 yd" ("Slight right now" at the turn).
- Changing a route option (flight paths, the hearthstone, teleports, the zones or towns avoided) works the trip out again at once.
- "Route there anyway?" is remembered for the route, also after a /reload.
- The last stop clears as soon as you reach it.
- With a stop down in Undercity, only the city's stops keep the order you placed them; the others go in the fastest order.
- The map window sits under other windows.

### Fixed

- **Lag:**
  - the first route after a /reload, and very long walks, are worked out in the background (no freeze);
  - recalculating a route with a flight in it (up to 200 ms in game);
  - riding a zeppelin or a boat no longer works the route out again all the way;
  - the first road display after a /reload, and each road or wall edit.
- Talking to a guard in Stormwind, Ironforge or Darnassus showed only the place you asked for: now all of that city's places show (trainers, the bank, the inn, the flight master and more), as in the Horde capitals.
- **The capitals' roads are their streets:** Stormwind's (and Ironforge's, Orgrimmar's, Thunder Bluff's and Darnassus's) roads were a jumble over every floor, some running out over the water; they now follow the streets the city guards walk, with ways to every trainer, bank, inn and flight master. Undercity's are as they were.
- Stormwind's map switched between the city's own map and the terrain as you zoomed: Stormwind now keeps the terrain map. Elsewhere, a building's inside map shows only indoors (at any zoom).
- The map window's title is centered (it sat a little right of the middle).
- The logo at the top left of the map and options windows stands on its own, without the circle, and is sharp: drawn at the size your screen shows it, not shrunk by the graphics card.
- Routes out of Stormwind went straight out through the city's wall (and after a moment by the Deeprun Tram and a long walk): a road drawn in through its gate was dropped once it was in the data. Drawn roads are always kept now.
- In Ironforge, routes cut straight across the Great Forge and the Forlorn Cavern's pool instead of along its halls: the game can report its halls as outdoors, and that took you to be up on the mountain over the city. Your height tells now.
- In a city with its own inside map (Ironforge, Undercity), zooming out stops at the city's map instead of turning to the land around it; right-click for the outside. Coming into the city zoomed far out, the map zooms in to it.
- The map's title says the city you're in (Ironforge, not Dun Morogh).
- The Deeprun Tram has its map (it was blank), with its name in the title.
- A zeppelin to Zephras Isle had no line on the map (on a trip hopping two zeppelins by the isle, only one ride showed).
- **On a road, routes keep to it** unless a way across country onto another road saves a fair bit (riding Mulgore's road, the route kept swapping between the road and a shortcut over the fields).
- In the capitals, routes no longer climb onto a ledge or balcony and jump back down to a trainer under it (Ironforge's Mystic Ward and Hall of Mysteries: its Mage and Priest trainers): a city place is reached by the roads on its own floor.
- When a route starts with your hearthstone (or a teleport), the direction arrow gave the turns of the walk after it instead. It now says "Use your Hearthstone (to …)" like the route's first step, with the item's button where the arrow is: click it there too. With the map's steps collapsed, the map's button hides.
- Every popup (Create Pin, Your Map Data, the waypoint import and sharing windows) has the map window's frame, without its logo; the questions ("Route there anyway?", a route someone shares) have it without a title bar too.
- A shaman with Astral Recall ready gets it in the route rather than the hearthstone (the same trip home), so the hearthstone stays ready for later.
- In Ironforge (or any building whose outside you right-clicked to), the map stayed on the outside after making a route out of the city, or cancelling one: it's back on the city's inside map once the map follows you again.
- **Thunder Bluff's lifts:** routes into and out of the city take them (they weren't joined to Mulgore's road), and the directions say "Take the lift up" (or down), as in Undercity. By the east lifts, two of the city's ways out ran straight up and down the mesa's cliff: they're gone, so the lifts are the way.
- While riding (or walking) past ground the addon was still checking, the route vanished every few seconds behind "Working out the route...": it stays shown now while it's worked out again.
- A zeppelin's or boat's dock that was a stop lost its countdown (hidden with its icon under the stop's marker): the countdown now shows under the stop.
- A straight line over the hills could replace the roads after standing still for a while.
- A flight could stop being suggested after a stop was added elsewhere and taken back.
- Roads vanished from the map when zoomed out (road and wall tools).
- Ironforge's roads, and road tool edits there, didn't show on the city's inside map (only on the mountain above it).
- Clicking the open sea on a continent's map opened a black terrain view.

### Known limits

- Party members show where the game gives their position: not inside dungeons.
- In some dungeons with floors over floors (Blackrock Spire and Depths, Temple of Ahn'Qiraj) the gold line can still jump between floors in places.
- Zeppelin and boat countdowns start once you've ridden that one (the game doesn't tell addons where they are).

## 1.0.7

For WoW Forever client 1.60.1 (interface 16001). New data and image files are included, so fully restart the game after updating, rather than just /reload.

### New

- **Dungeons and raids:** 25 of them (from Ragefire Chasm to Naxxramas) have entrance icons on every map style (the map menu's "Dungeons and raids" group turns them on and off). Click one for its map:
  - the game's own map of it, floor by floor with the **+** and **-** buttons at the top left (the mouse wheel still zooms);
  - its bosses, numbered in the usual kill order (optional ones marked);
  - a gold line for the usual way through, boss by boss, with stairs icons where it goes up or down a floor.

  Right-click goes back to the map you came from.
- **Boss route** (map menu): a route through a dungeon's bosses in the usual order. Each stop is done when its boss dies, not when you get there, and a boss already down is left out.
- **Inside a dungeon** the game hides your position from addons, so the map shows the dungeon itself: the bosses you've killed fade, the stretch of the gold line to the next boss lights up, and the panel says which boss is next ("Next: Sneed (2 of 6)").
- **Zones too high for your level** (Options → Routing, on by default): routes go around zones whose levels are red for you, when there's another way. Routing to a stop in one, or along the only way there through one, asks first, on the map.
- **Zeppelin and boat docks** show on the map with points of interest (double-click one for a stop). After you've ridden one once, its icon counts down to its next arrival, from its timetable and when you saw it leave.
- **Boats, zeppelins, lifts and dungeon portals** are only used when your faction can take them.
- **City icons on the terrain view:** Undercity's and Ironforge's open their inside maps.
- **For other addons:** a public `AzerothGPS` API (map geometry, the point under the mouse, drawing on the map; dungeons' maps too). See docs/api.md.

### Fixed

- Long routes without flight paths froze the game for seconds (off-road shortcuts are now worked out in the background).
- A route could turn back to a road the other way (a U-turn) while the way around a rock or a steep patch was still being searched, and kept doing it as you walked.
- Right-clicking out of a city's or dungeon's map went to the wrong place.
- An error inside dungeons (a tooltip the game hides from addons).

### Known limits

- Blackwing Lair and WoW Forever's new dungeons and raids aren't in yet.
- In some dungeons with floors over floors (Blackrock Spire and Depths, Temple of Ahn'Qiraj) the gold line can still jump between floors in places.
- Zeppelin and boat countdowns start once you've ridden that one (the game doesn't tell addons where they are).

## 1.0.6

For WoW Forever client 1.60.1 (interface 16001). New data files are included, so fully restart the game after updating, rather than just /reload.

### New

- **Undercity:** routes follow the city's own floors, stairs and lifts, with "above you" and "below you" hints, and use a safe jump down a ledge when it saves time (only when your health allows it). Off-road shortcuts turn themselves off in cities and the Ruins of Lordaeron, and back on after. Its flight master, trainers and quest givers are reached down in the city, not up top.

  ![Undercity's map with its districts and places](https://i.imgur.com/AZzfqTs.png)

- **The capitals:** Orgrimmar, Ironforge, Stormwind, Thunder Bluff and Darnassus have their own streets now: routes go in through the gates and follow them to the banks, trainers, flight masters and docks. That includes the Cleft of Shadow under Orgrimmar, the halls under Ironforge's mountain, Stormwind's canal bridges, and Thunder Bluff's bridges and elevators. Off-road shortcuts turn themselves off inside.
- **Caves and mines:** 351 of them on both continents are mapped: routes go in at the mouth and follow the tunnels.
- **More roads:** many roads the map was missing (Dun Morogh, Desolace, Badlands, Winterspring and more) are part of the network now.
- **The other faction's towns:** routes keep away from their guards and go around their towns when there's a way (Options → Routing).
- **Continent map:** right-click from the terrain view goes to the continent's map, then the world map. Hover a zone for its name and level range; click a capital's icon to open the city (Ironforge and Undercity show their inside).

  ![A continent's map: hovering a zone shows its name and level range](https://i.imgur.com/HHVpQsL.png)

- **City locations:** after talking to a guard in a capital, its banks, trainers and other places show on the map. Asking a guard again routes there again, and any banker, auctioneer or trainer of the kind finishes that stop.
- **Quick buttons** are grouped (map styles; quests; herbs, ore and farming) and slide out beside their button, in the order you set in Options.

  ![Quick button groups sliding out](https://i.imgur.com/DG6utoK.gif)

- **Road tools** (Options → Road tools): draw a road the routes miss, or erase a false one (or circle an area).

  ![Road tools: circling a false road to erase it, then drawing the real one](https://i.imgur.com/WjwnjW1.gif)

- **Wall tools** (Options → Wall tools): draw walls routes can't walk through (roads crossing them are cut; leave a gap for a gate), or erase a mountain edge the map has wrong. **Show extracted walls** draws everything routes won't cross.

  ![Stormwind's roads](https://i.imgur.com/woSLg9m.png)
  ![The walls routes won't cross, over the roads](https://i.imgur.com/oH1dYxZ.png)

- **Share your fixes:** Options → Help improve → **Copy map data...**, then paste it in a [Road data issue](https://github.com/AzerothGPS/AzerothGPS/issues/new?template=road-data.yml) on GitHub.
- **Quest route:** an option to use only the quests in the zone you're in; a quest route always goes in the fastest order, in cities too.
- **Smoother directions:** short jogs in a route are straightened (not on hilly ground, where winding is the way up), and a turn that just jogs back onto the same line reads as straight on. Parts of a route on another floor are drawn faint and dotted.
- The map keeps where you panned it across a /reload, and switching map style keeps the spot you're looking at.

### Fixed

- Routes through walls, off ledges and into water in Undercity and the Ruins of Lordaeron.
- A freeze when the first route after logging in was worked out, and the road network builds several times faster.
- "Turn around" when the way on was a lift down or up.

## 1.0.5

For WoW Forever client 1.60.1 (interface 16001). A new key binding file is included, so fully restart the game after updating, rather than just /reload.

### New

- **Questing** (on by default, Options → Routing). A stop inside a quest's area is done when that quest's objectives are, not when you get there:
  - **In the stop's quest area,** the arrow window shows the objective counters. A smaller arrow still points to the stop's spot, with "In quest area" and the distance under it, and the stop after this one listed below.
  - **At the spot,** a big **!** replaces the arrow and the route waits while you quest. Leave the area early and the route leads you back.
  - **Objectives done** anywhere in the area: on to the next stop.
  - **Other quest areas** you walk through (even with no route) show their objectives in the arrow window, with a **!**.
  - **In the area of a stop further down your list?** That stop moves to the front.
- **Quest route.** The new **Sprint button** next to the Hearthstone button makes a route through your quest log: every quest's objectives and every finished quest's turn-in, in the fastest order.
  - Pick up a new quest while on a quest route and a Sprint icon pulses in the arrow window's corner. Click it to make the route again with the new quest.
- **Corpse runs.** Released as a ghost, your body (the skull marker) becomes stop 1 with a red route, ahead of any stops you had. Once you're alive, it's taken off and your route carries on.
- **Long lists.** Import up to 100 stops (a quest guide, say). With fastest order on, the whole list is ordered from where you are; the route shows the next 8 stops and brings in the next one as you arrive.
- **Show/hide key.** Set a key for the map in Options → General, or in the game's Key Bindings under AddOns ("Show/Hide AzerothGPS").
- **Reopen following me** (Options → General, off by default): with a route set, a map you hid while looking around reopens centered on you.

### Improved

- **Quest areas** are found more reliably:
  - Small areas (a few dozen yards) are found by looking closely around you.
  - Quests with no map icon on your current map are traced too.
  - Tracing waits until combat is over (the game hides the answers in combat), so areas no longer come out empty.
  - All of it works with the map closed.
- **Hidden map:** routing and the arrow keep going with the map closed. Stops placed but not confirmed are confirmed when you close it.
- **The direction arrow** is click-through while locked.
- **The route animation** frames every stop, not just the first few.

### Fixed

- The route animation could stop the map from updating after making a quest route.

## 1.0.4

For WoW Forever client 1.60.1 (interface 16001). A new texture is included, so fully restart the game after updating, rather than just /reload.

### Improved

- **Much lower CPU use.** In testing with a 5-stop off-road route and quest areas shown, AzerothGPS uses about 40% less CPU than 1.0.3, with far fewer frame hitches:
  - **Routing** no longer recalculates several times a second while you're off-road. Background terrain searches refresh the route at most every 3 seconds.
  - **Recalculations are cheaper.** Terrain checks and stop-to-stop times are remembered instead of worked out again.
  - **Multi-stop routes** work out the legs between stops one per frame, so adding stops no longer stalls the game.
  - **The map** redraws at most 20 times a second, and dotted route lines are drawn as one line per leg.
  - **The first route** after logging in builds its road data in the background (the route panel briefly says "Working out the route...") instead of freezing the game for a moment.
- **Hearthstone and teleports on any leg.** On a multi-stop trip, your Hearthstone (or Astral Recall, or a mage teleport) is now used on the leg where it saves the most time, not only from where you stand. A trip that ends near home hearths from the last stop instead of running back. Each is used once per trip.

### Fixed

- **Routes stay up to date while the map is hidden** (for example in combat). The direction arrow keeps the route's background work going.

## 1.0.3

For WoW Forever client 1.60.1 (interface 16001). New files are included, so fully restart the game after updating, rather than just /reload.

### New

- **Search.** The magnifier at the bottom-left of the map finds towns, zones, landmarks, flight masters and boat and zeppelin docks. Pick one and it becomes a stop. NPCs can't be searched: the game doesn't tell addons where they are.
- **Farming routes.** Open the round map button, choose **Draw a farming area**, and drag around the herbs or ore you want. The route loops through every known node inside, round and round.
- **Herbs and ore:**
  - **Separate layers:** Herbs and Ore are now separate map layers, and a farming area uses the ones you show.
  - **Right-click to save:** right-click a herb or ore node without the profession ("Requires Herbalism/Mining") and it's saved for your characters who have it.
  - **Import node lists:** in the waypoint window (+), choose "Import as herb/ore nodes". They show faded until you gather there.
- **Hearthstone and teleports.** When it's faster, a route can start with your Hearthstone, Astral Recall, a mage's teleport or Teleport: Moonglade. The directions say "Use your Hearthstone (to …)"; the addon never uses anything for you.
  - **Two options** under Routing: "Use hearthstone" and "Use class teleports" (both on by default).
  - **Hearthstone button** next to the round map button: one click turns the hearthstone on or off for routes (grayed when off).
  - **Knows your inn:** the hearthstone lands at your inn's building, and the exact spot is learned when you're inside it.
- **New flight masters on the way.** If a flight master of your faction you haven't learned yet has a flight to one you know, and going there is faster, the route says "Learn the flight path, then take the flight to …".
- **Zephras Isle.** WoW Forever's island has its terrain map, roads and place names, and routes take the zeppelins there from Alterac Mountains and Mulgore.
- **Click-through.** Options → Opacity: while moving and/or in combat, clicks pass through the map and the arrow to the game world (combat on by default).

### Improved

- **Off-road routes:**
  - They walk around ridges on longer trips (up to 3,000 yards) instead of making long road detours.
  - They walk off rocks you're standing on.
  - They no longer cut through cliffs from walled-in spots.
  - Checked with a new all-zones route test: 0 bad routes in 711 random trips.
- **Route options apply right away.** Turning flights, the hearthstone or teleports on or off changes the route at once, instead of keeping the old one for a while.
- **Quest areas:**
  - Much lower CPU use while moving with quest areas shown.
  - They no longer disappear for a while when an outline is updated or you cross into another zone.
- **Gathering** is recognized at every rank of Mining and Herb Gathering, so gathered nodes show up.
- **Adding a stop to a route** shows the whole route again after 5 seconds, then follows you. Drawing a farming area plays the route animation.
- **The map menu** closes after 6 idle seconds or a click on the map, and the search panel after 20 seconds.
- **Stop markers** skip the cross and skull, and start over after six.
- **Buttons:** the import + button and the back-to-you button swapped places.
- **The direction arrow** has no tooltip anymore. How it works is explained under Options → Directions.
- **Close buttons** on AzerothGPS windows work in combat.
- **The addon list** shows the AzerothGPS icon instead of a "?".

### Fixed

- **Hearthstone** wasn't suggested in routes.
- **Flights** with only one known flight master at the far end couldn't be used.

### Removed

- **Quests to pick up.** This client only shows them on its own minimap, where addons can't read them.

## 1.0.2

For WoW Forever client 1.60.1 (interface 16001). Extract the `AzerothGPS` folder into `World of Warcraft\_classic_beta_\Interface\AddOns`. New image files are included, so fully restart the game after updating (not just /reload).

### New
- **Flight paths:** routes take flights between the flight masters your character knows, including connecting flights (option "Use flight paths", on by default). Open the flight map at any flight master once so the addon learns which ones you know.
- **Flying:** while on a flight, the route stays put and nothing is recalculated. The flight's line shrinks as you fly, and the time left counts into your ETA.
- **Stop order on the way:** with "Visit stops in the fastest order", stops are reordered as you travel when another order becomes clearly faster.
- **Fade while moving:** the map can fade while you move, leaving the route, the stop markers and your arrow visible (Options → Opacity).
- **Window frame:** the map has a game-style frame with a title bar, logo and close button, and it's its own option. The map and the direction arrow have separate lock options.
- **Options:** the options window has pages like the game's settings (General, Map, Routing, Directions, Opacity, Road tools, Help improve).
- **Map menu:** one round button at the bottom-left opens the map type and the map layers.
- **Route panel:** a -/+ button collapses the steps to the trip's times. The ✕ now closes the panel without canceling the route; an option restores the old behavior.

### Improved
- **Off-road:** routes join and leave roads partway along, so they cut straight across to where the road is heading.
- **Rerouting:** routes no longer jump to a longer path for a moment near obstacles while you're still on the route.
- **Times line:** only the mount time shows while mounted, and a mount time only appears once the character has learned Riding. Flights no longer count as mounted.

### License
All rights reserved (see LICENSE.txt).

## 1.0.1

For WoW Forever client 1.60.1 (interface 16001). Extract the `AzerothGPS` folder into `World of Warcraft\_classic_beta_\Interface\AddOns`.

### New
- **Share routes.** The + button's window can copy your route as TomTom `/way` lines (paste them anywhere), or send it in game to a player or your group. Receivers need AzerothGPS and are asked before it's used. Shift+click a name in chat to fill in "Send to". Option: "Accept routes shared by players".
- **Points of interest as stops.** Double-click a flight master, town or quest icon to add it as a stop; its name is used in the directions.
- **In combat options.** Hide the map and/or the direction arrow during fights, or give each its own combat opacity (the map's follows its usual opacity by default). The arrow no longer catches clicks in combat.

### Fixed
- Clicking a point of interest replaced the whole route; it now adds a stop like a double-click, and Confirm Route starts it.
- Routes on the other side of a boat or zeppelin (and anywhere the road data had gaps) could fall back to a straight line; the pieces of the road network are now joined, so routes follow the roads.
- "Show extracted roads" is off by default for new installs.

## 1.0.0

First release of **AzerothGPS**, car-GPS style navigation for World of Warcraft (Classic / WoW Forever client, interface 16001). Display only: it never moves your character, clicks, or automates anything.

**Install:** unzip `AzerothGPS-1.0.0.zip` into `World of Warcraft\_classic_beta_\Interface\AddOns\` (so you get `AddOns\AzerothGPS\AzerothGPS.toc`), then start the game or `/reload`. `/agps` opens the options.

### Features
- **Map window:** terrain view, world map, and a No Spoiler map (only explored parts); building interiors; zoom, pan, right-click to browse Azeroth and continents; coordinates under the mouse.
- **Routing:** along the extracted road network, optional off-road shortcuts that respect mountains and cliffs, zeppelins and boats between continents; follows the route like a car GPS and reroutes when you leave it.
- **Multi-stop trips:** double-click to place stops (raid markers), fastest order option, per-stop times, add/remove stops on a live route, colour per leg.
- **Turn-by-turn:** a TomTom-style arrow with the next turn, "toward <place>", the stop's distance and ETA, and later stops when made taller.
- **TomTom compatible:** import `/way` lines (the + button), `/way` in chat, pasted lists of `/way` lines.
- **Layers:** quest objectives and turn-ins, quest areas with hover tooltips, quests to pick up, flight masters, points of interest, place names, herbs and ore you've gathered or hovered.
- **Road fixes:** record missing or false roads in game; they're used right away.

### Privacy
Nothing is sent anywhere; addons can't use the network. The optional "Help improve AzerothGPS" settings (off by default) only keep data in your saved variables on your PC.

AzerothGPS is a fan-made addon and is not affiliated with or endorsed by Blizzard Entertainment.

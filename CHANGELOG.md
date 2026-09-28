# Changelog

Each version's section is its release notes (GitHub and CurseForge).

## 1.0.6

For WoW Forever client 1.60.1 (interface 16001). New data files are included, so fully restart the game after updating, rather than just /reload.

### New

- **Undercity:** routes follow the city's own floors, stairs and lifts, with "above you" and "below you" hints, and use a safe jump down a ledge when it saves time (only when your health allows it). Off-road shortcuts turn themselves off in cities and the Ruins of Lordaeron, and back on after. Its flight master, trainers and quest givers are reached down in the city, not up top.

  ![Undercity's map with its districts and places](https://i.imgur.com/AZzfqTs.png)

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

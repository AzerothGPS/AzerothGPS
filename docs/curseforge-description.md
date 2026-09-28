# AzerothGPS

**A car-style GPS for Azeroth.** Pick where you want to go and AzerothGPS draws the way there along the world's roads and trails, with turn-by-turn directions, distances and ETAs. Multi-stop trips, flight paths, boats, zeppelins and your hearthstone are all part of the route.

![A three-stop route around Brill and the Undercity, with the direction arrow](https://i.imgur.com/lOUdHxl.png)

_A three-stop trip in Tirisfal Glades: each leg in its stop's color, the steps and times at the top, the direction arrow top left. (Enlarged for the showcase; the map's size and opacity are adjustable.)_

![Double-clicking Brill and a spot on the map, confirming, then following the route with the direction arrow](https://i.imgur.com/LnZbC2x.gif)

_Double-click where you want to go, confirm, and follow the arrow._

## Highlights

- **Real routes:** along the roads, around mountains and in through the passes, with optional off-road shortcuts.
- **Inside cities and caves:** Undercity's floors, stairs and lifts, and 351 caves and mines, entered at the mouth.
- **Keeps you out of trouble:** routes go around the other faction's towns and guards.
- **Turn-by-turn directions** in a small arrow window, with the distance and ETA to every stop.
- **Multi-stop trips** in the fastest order, including flight paths (even ones you'll learn on the way), boats, zeppelins, your hearthstone and class teleports.
- **Questing:** a one-click route through your quest log, and stops that wait while you do the quest.
- **Corpse runs:** a red route back to your body.
- **Herbs, ore and farming loops**, shared by all your characters.
- **Fix the map yourself:** draw a missing road or a wall the routes should go around, and share it.
- **TomTom `/way` import and route sharing.**
- **Display only.** It never moves your character, clicks for you or automates anything.

---

## Getting started

1. The map window shows at the bottom of the screen (`/agps show` if it's hidden).
2. **Double-click the map** to add a stop. Double-click a town, flight master or quest icon to use its name.
3. Click **Confirm Route**, or wait 5 seconds.
4. Follow the line on the map, or the direction arrow.
5. Using flight paths? Open the flight map at any flight master once, so the addon learns which ones your character knows.

![Placing two stops near the Undercity before confirming the route](https://i.imgur.com/oNhjJnz.png)

_Placed stops wait for Confirm Route (or 5 seconds)._

---

## Routing

### Roads and off-road

Routes follow the game's real roads. With **Off-road shortcuts** on (Options → Routing), they cut across open ground where that's faster, but never over cliffs: they go around the terrain and in through the way in.

![The same three-stop trip with off-road shortcuts off, following the roads](https://i.imgur.com/qbTwnQH.png)

_The trip from the top of the page with off-road off: to the nearest road, then along the roads._

![A route around a mountain ridge and in through the pass to a walled-off valley](https://i.imgur.com/IyVpGiY.png)

_In a straight line it's much closer, but cliffs close off the valley: the route leads to the pass and in from the north._

### Stops

- **Add** stops by double-clicking the map (also while a route is running), with search, or by importing `/way` lines. Up to 100 per trip.
- **Fastest order** (on by default): the stops are ordered for the quickest trip, and reordered on the way if another order becomes clearly faster. Long lists are routed 8 stops ahead; the next comes in as you arrive.
- **Remove** a stop by right-clicking its marker; **Clear Route** or `/agps clear` cancels the trip.
- **The route panel** at the top of the map lists the steps with a time for each stop. **-** collapses it to the trip's times, and its **✕** hides it (an option makes it cancel the route).

![Right-clicking a stop marker shows Remove?](https://i.imgur.com/idzgHPV.png)

### Flight paths

Routes take a flight when it's faster: "Walk to the flight master", then "Take the flight to …", with connecting flights as one step. If a flight master you haven't learned yet (your faction) is on the way, the route can go there to learn it and fly on. In the air, the route waits for you to land, and the time left counts into your ETA. Flight times start as estimates and use your own recorded times once you've flown.

![A route that walks to the Undercity flight master and flies to The Sepulcher](https://i.imgur.com/BnlilQ8.png)

![In the air: Flying to The Sepulcher, lands in 1m 25s](https://i.imgur.com/rXP7fQc.gif)

_On a flight, the line shrinks toward the landing and the time left counts down._

### Hearthstone, teleports and boats

- A trip can use your **Hearthstone**, **Astral Recall**, a **mage teleport** or **Teleport: Moonglade** when it's ready and faster, on whichever leg saves the most (once per trip). The addon knows your inn and never uses anything for you: the directions just say "Use your Hearthstone".
- **Boats and zeppelins** are part of the route, with where to board.

![A route whose first step is Use your Hearthstone (to Gallows' End Tavern)](https://i.imgur.com/m1Trl0w.png)

_Hearth home, then walk the rest._

### Cities and caves

- **Undercity** is routed on its own floors: stairs, ramps and the lifts up to the Ruins of Lordaeron, with "12 yd above you" or "below you (down a lift)" when your stop is on another floor. Safe drops off a ledge are used when they save time ("Jump down here", only when your health allows it). Off-road shortcuts turn themselves off in cities and back on after.
- **Caves and mines** (351 of them on both continents, from Fargodeep and Jasperlode to the Wailing Caverns): routes go in at the mouth and follow the tunnels.
- **City locations:** once you've asked a guard in a capital for directions, its banks, trainers and other places show on the map (for all your characters). Asking a guard again routes you there again, and any banker, auctioneer or trainer of the kind finishes that stop.

![Undercity's map with its districts and places](https://i.imgur.com/AZzfqTs.png)

### The other faction's towns

Routes keep away from the other faction's guards: around their towns and camps, and off the roads they patrol, when there's another way. A stop inside one is still reached, the shortest way in. (Options → Routing: "Avoid the other faction's towns".)

### Corpse runs

Released as a ghost? Your body (the **skull** marker) becomes stop 1 with a **red route**, ahead of any other stops. Once you're alive again your route carries on.

![As a ghost at The Sepulcher: a red route to the skull marker](https://i.imgur.com/9QiJiRw.png)

---

## The map

| Control | What it does |
|---|---|
| **Drag / mouse wheel** | Pan and zoom. The coordinates follow your pointer. |
| **Right-click** (Terrain style) | Out to the continent's map, then the world map. Hover a zone on a continent's map for its name and level range; click a capital's icon to open the city (Ironforge and Undercity show their inside). |
| **Round map button** (bottom left) | Slides out the quick buttons you keep in its menu, upward, to the right, or both. Closes after 20 seconds untouched. |
| **Quick buttons** | Search, quest route, the map styles, **Draw a farming area** (shovel), and on/off toggles for the hearthstone, off-road shortcuts, quests, quest areas, herbs, ore and city locations (grayed when off). Related ones are grouped (map styles; quests; herbs, ore and farming) and slide out beside their button. Each is always shown or in the menu, going up or to the right, or hidden, in the order you like (Options: Quick buttons). |
| **Target button** (bottom right) | Back to your position. |
| **+ button** | Import, copy or send waypoints. |

![Panning and zooming, then right-clicking out to the world map and picking a spot in Durotar](https://i.imgur.com/pIXbXdS.gif)

![The round map button's menu: map styles and map layers](https://i.imgur.com/jbtbfif.gif)

![Quick button groups sliding out: quests, herbs and ore, farming](https://i.imgur.com/DG6utoK.gif)

![A continent's map: hovering a zone shows its name and level range](https://i.imgur.com/HHVpQsL.png)

![Searching "ri" on Zephras Isle, each result with its kind](https://i.imgur.com/Qb3HwWf.png)

**Near a stop**, the map zooms in smoothly so you can see exactly where it is, and back out once you're there.

**In cities** like Undercity, the map shows the district names (Trade Quarter, Magic Quarter...) along with your quests and the city's places. Parts of a route on another floor are drawn faint and dotted.

**City locations:** ask a guard for directions (a trainer, the bank) and the spot they mark becomes a stop, with a matching icon. It's saved for all your characters and shown on the map afterwards.

**A panned map stays put** across a /reload, and switching map style keeps the spot you're looking at.

### Map styles

**Terrain** (the minimap's ground art), **World Map** (zone art) or **No Spoiler** (only what you've explored; routes still work everywhere).

![The same spot near Brill in Terrain, World Map and No Spoiler](https://i.imgur.com/gqISXPx.png)

**Zephras Isle**, WoW Forever's island, has its own terrain map and roads, and routes take the zeppelins there.

---

## The direction arrow

A small window with an arrow along your route: **green** on course, **white** for a turn coming up, **red** when the route is behind you. It shows the next turn ("Turn right in 120 yd", "Board the zeppelin to Orgrimmar"), the road you're heading toward, and the stop's distance and ETA. Make it taller to list your later stops. Locked, clicks pass through it.

![The direction arrow: next turn, the stop's distance and ETA, the stops after it](https://i.imgur.com/pCqMfOT.png)

---

## Quests

- **On the map:** your quests' objectives and turn-ins, with the quest areas outlined like on the minimap. Hover an area for its objectives.
- **Quest route:** the **Sprint button** makes a route through your quest log in one click: every quest's objectives and every finished quest's turn-in, in the fastest order. Pick up a new quest while on it and a Sprint icon pulses in the arrow window: click it to add the quest.
- **Only this zone** (Options → Routing): the quest route takes just the quests in the zone you're in. Quests in a city route to the city itself (down in Undercity, not up top).
- **Questing** (on by default): a stop inside a quest's area is done when that quest's objectives are, not when you get there.
  - In the area, the arrow window shows the objective counters; a small arrow still leads to the stop's spot. At the spot, a big **!** takes over and the route waits.
  - Leave early and the route leads you back. Done anywhere in the area: on to the next stop.
  - Walking through any quest's area (even with no route) shows its objectives. In the area of a stop further down your list, that stop moves to the front.

![Quest area outlines on the map, with the objectives on hover](https://i.imgur.com/NLye6Xh.png)

![Clicking the Sprint button: the route zooms out over every quest stop and turn-in](https://i.imgur.com/g67YfqD.gif)

![The arrow window in a quest area: objectives, a small arrow with the distance, and the next stop](https://i.imgur.com/xiarwgJ.png)

![The Sprint icon pulsing in the arrow window after picking up a new quest](https://i.imgur.com/gqC0L8e.gif)

---

## Herbs, ore and farming

- **Nodes** you gather, hover on the minimap, or right-click without the profession ("Requires Herbalism") are saved for all your characters. Show herbs, ore or both.
- **Import node lists:** in the waypoint window, tick **Import as herb/ore nodes** and paste `/way` lines with the node's name. They show faded until you gather there.
- **Farming routes:** **Draw a farming area** (the shovel quick button), drag around the nodes, and the route loops through every one inside, each stop with its herb or ore icon.

![Drawing a farming area and following the loop](https://i.imgur.com/ABt7arU.gif)

![The waypoint window with Import as herb/ore nodes](https://i.imgur.com/KXUz2RU.png)

---

## Waypoints and sharing

AzerothGPS reads the TomTom `/way` format used by guides and websites:

```
/way Elwynn Forest 43.2 65.1 First Stop (Vendor)
/way 45.0 60.2 Second Stop
```

- **Paste into chat** (one or many lines), or into the waypoint window (**+ button**). With TomTom installed, both addons get them.
- **Shift+click a map pin** someone shared in chat and it becomes a stop.
- **Copy route as /way** to post your stops anywhere.
- **Send in game** to a player (type a name, or Shift+click one in chat) or your group. They need AzerothGPS and are asked before it's used; the next 8 stops are sent.

![Pasting /way lines and getting a route with a zeppelin ride](https://i.imgur.com/SvecrT3.gif)

![The waypoint window with a route copied as /way lines](https://i.imgur.com/mUgJa9g.png)

---

## Fixing the map: roads and walls

**Road tools** (Options → Road tools, or `/agps dev`) add a **Road tools** button to the map. Click it, then:
- **Left-drag** along a trail the routes miss: routes use it right away, joined to the roads it meets (where it runs along one, it replaces that stretch).
- **Right-drag** over a "road" that isn't really there, or **circle an area** to erase every road in it.
- **Middle-drag** pans. Click the button again when you're done.

![Road tools in Duskwood: circling a false road to erase it, then drawing the real one](https://i.imgur.com/WjwnjW1.gif)

**Wall tools** (Options → Wall tools) do the same for what routes can't walk through: **left-drag** along a wall, fence or cliff the routes try to cross and they go around it like a mountain. A road crossing a wall is cut there (leave a gap for a gate); flight paths still fly over. **Right-drag** erases walls, and also opens a mountain edge the map has wrong. **Show extracted walls** draws everything routes treat as impassable in blood red: the terrain's cliffs and steep slopes, and the walls.

![Stormwind with the road network shown](https://i.imgur.com/woSLg9m.png)

![The same view with the walls routes won't cross](https://i.imgur.com/oH1dYxZ.png)

![Show extracted walls on its own](https://i.imgur.com/TTQtp1E.png)

`/agps draw undo` (or the **Undo** button) takes the last one back.

**Share them:** Options → Help improve → **Copy map data...**, then paste it in a [Road data issue](https://github.com/AzerothGPS/AzerothGPS/issues/new?template=road-data.yml) on GitHub. Roads and walls that check out go into a later version for everyone.

---

## Options

`/agps` or right-click the minimap button. Pages, like the game's own settings:

- **General:** show the map, reopen it following you, lock it, window frame, zoom in near a stop, heading-up, size, a **key to show and hide the map**, minimap button.
- **Map:** right-click world map, building interiors, and what's shown (flight masters, places, quests, quest areas, herbs, ore).
- **Quick buttons:** a table of where each quick button goes (always shown or in the menu, up or right, or hidden), and their on/off settings. The map can't be made smaller than they need.
- **Routing:** off-road shortcuts, avoiding the other faction's towns, questing and the quest route's "only this zone", flight paths, hearthstone, class teleports, fastest order (and keeping your own order in cities), the panel's ✕, `/way` and shared routes.
- **Directions:** the arrow window, its lock and background, and how it works.
- **Opacity:** map opacity, fade while moving, click-through while moving or in combat, hide or dim in combat.
- **Road tools**, **Wall tools** and **Help improve** (copy your map data to share; kept on your PC until you do).

![Clicking through the options pages](https://i.imgur.com/Jap95Dp.gif)

![Options, General: the Show/hide key set to Insert](https://i.imgur.com/JFyo73O.png)

---

## Commands

`/agps` (or `/gps`):

| Command | What it does |
|---|---|
| `/agps` | Options |
| `/agps show` / `hide` / `toggle` | Show or hide the map |
| `/agps clear` | Cancel the route |
| `/agps import` | Waypoint window |
| `/way [zone] x y [text]` | Add a stop |
| `/agps arrow on\|off` | Direction arrow |
| `/agps style minimap\|zone\|nospoiler` | Map style |
| `/agps rotate on\|off` | Heading-up or north-up |
| `/agps offroad on\|off` | Off-road shortcuts |
| `/agps quests on\|off` | Quests on the map |
| `/agps herbs\|ore\|nodes on\|off` | Herbs, ore, or both |
| `/agps lock` / `unlock` `[map\|arrow]` | Lock or unlock |
| `/agps dev` | The Road tools button on the map |
| `/agps walltools` | The Wall tools button on the map |
| `/agps walls on\|off` | Show what routes can't walk through |
| `/agps draw [undo\|list]` | Road tools on/off (left-drag draws, right-drag erases); take the last back |
| `/agps reset` | Default settings |
| `/agps help` | Every command |

---

## Privacy and fair play

- **No internet, no data collection.** Addons can't go online. The optional "Help improve" data is off by default and stays on your PC.
- **Sharing only when you choose**, and only the stops. Nothing is used until the other player accepts.
- **Display only:** no automation, memory reading or anything else against the Terms of Service. No Blizzard files are shipped; the map uses the game's own textures.

## Feedback and bugs

Found a wrong road, a bad route or a bug? Open an issue on [GitHub](https://github.com/AzerothGPS/AzerothGPS/issues) with the zone, your start and destination coordinates (shown at the bottom of the map), and a screenshot if you can. Fixed a road or a wall yourself? Share it as a [Road data issue](https://github.com/AzerothGPS/AzerothGPS/issues/new?template=road-data.yml).

_AzerothGPS is a fan-made addon and is not affiliated with or endorsed by Blizzard Entertainment. World of Warcraft and Azeroth are trademarks of Blizzard Entertainment, Inc._

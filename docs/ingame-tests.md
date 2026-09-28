# In-game test checklist

Install or refresh the addon with `agps install-addon`, then `/reload`.

## Options and minimap button

| # | Do | Expect |
|---|---|---|
| O1 | Look at the minimap edge | An AzerothGPS map button; its tooltip lists the clicks |
| O2 | Left-click it | The GPS shows and hides |
| O3 | Right-click it (or type `/agps`) | The options window opens: checkboxes, style buttons, sliders, road recording and reset. Escape closes it |
| O4 | Drag the button | It slides round the minimap and keeps its place after `/reload` |
| O5 | Esc > Options > AddOns > AzerothGPS | A page with an "Open AzerothGPS options" button |
| O6 | `/agps help` | The command list |

## A2: Road network

| # | Do | Expect |
|---|---|---|
| R1 | Options: tick **Show road network** (or `/agps roads on`) | Orange road lines over the terrain, cyan where a gap was bridged |
| R2 | Ride Orgrimmar gate > Razor Hill > Valley of Trials, and the Durotar-Barrens bridge | The lines sit on the roads you see in the terrain |
| R3 | **Draw a missing road:** `/agps dev`, click **Road tools** on the map's buttons, and left-drag from Razor Hill's road to Sen'jin Village; then `/reload` | "saved your road": drawn in the road color, joined to the road; with `agps watch-roads` running it's in the road data after the `/reload` |
| R4 | Anywhere the lines are wrong | With **Road tools** on, right-drag over them (red) |

## A1: GPS frame

| # | Do | Expect |
|---|---|---|
| G1 | Log in | A square map in the top-right showing the terrain around you, like the minimap, with an arrow in the center |
| G2 | Walk in a straight line | The map scrolls smoothly; the arrow stays centered |
| G3 | Turn in place (heading-up, the default) | The **map** turns, the arrow keeps pointing up, and the red **N** moves round the edge toward north. Terrain matches the real minimap when you turn it to match |
| G4 | `/agps rotate off` | North-up: the map is fixed, the arrow turns, and N stays at the top |
| G5 | Mouse wheel over the frame | Zooms in and out (60-2500 yd) |
| G6 | `/agps opacity 50`, `/agps size 350` | Half transparent, bigger |
| G7 | Drag the frame; `/agps lock` | Moves; stays put when locked; the position survives `/reload` |
| G8 | `/agps style zone` | Fully explored world-map art for your zone, turning the same way |
| G9 | Cross a zone border (e.g. into the Barrens) | Minimap style: seamless. Zone style: switches to the new zone's art |
| G10 | Enter a dungeon | "No map here" |

**If tiles look wrong when turning** (seams, gaps, or tiles turning the opposite way to
the map): try `/agps debug rotsign`, and tell me what you see, ideally with a screenshot.

Afterwards, `/agps debug`, then `/reload`, so the probe is saved (`agps probes` reads it).

## Map layers (Layers.lua)

1. `/reload`, then `/agps debug` and `/agps debug layers`: tells which quest APIs this client
   has (GetQuestsOnMap / GetAvailableQuestLines). Send the output.
2. Quests: with a quest in your log, its objective area ("?" circle) and turn-in show on the
   GPS; quest givers you can pick up from show a "!". Layers button (third, bottom-left):
   toggle them, and "include low-level quests".
3. If the client lacks those APIs: open the world map on the zone once; its quest pins are
   then shown on the GPS for the rest of the session.
4. Herbs/ore (character with Mining or Herbalism): gather a node, or hover a node icon on the
   game minimap; it appears on the GPS at that spot and stays (saved for all characters).
5. The game minimap stays in its corner, untouched.

## Multi-stop routes

1. Drag the map (free view), double-click a spot: a star marker appears and the button
   reads "Confirm Route (1)". Double-click more spots: circle, diamond, triangle... (up to 8).
2. Right-click a marker to remove it (the others renumber).
3. Leave the map alone for 5 s: the route starts (zoom out over all stops, then back to you).
   Or press "Confirm Route" right away. With no markers, the button routes to the crosshair.
4. The nav panel shows the next stop's marker, "1/3", its distance and ETA, and
   "All stops" walk/mount times. Reaching a stop moves on to the next.
5. Options > "Fastest order for several stops": stops are visited in the fastest order
   (markers keep their icons, so you can see the new order); ticking it with a route
   active reorders it.
6. Recenter (bottom-right arrow) throws away unconfirmed markers.

## Turn-by-turn arrow (A4: Turns.lua, Arrow.lua)

1. Set a route (e.g. Valley of Trials -> Razor Hill). A small window appears (top of the
   screen by default; drag it while the GPS is unlocked): big arrow, next instruction with
   its distance ("Turn right  120 yd", "toward Sen'jin Village"), the stop line (marker,
   name, distance, ETA, 1/N) and "Then: ...".
2. The arrow points along the route ~30 yd ahead: green when you face that way, gold for a
   turn, red when it's behind you. Turn around and watch it follow.
3. On roads, instructions come only at junctions (and very sharp bends); off-road legs give
   "Join the road" / "Leave the road" and turns; zeppelins give "Board the zeppelin to ...".
4. The window works with the GPS hidden; "Direction arrow" in the options (or
   /agps arrow on|off) turns it off.

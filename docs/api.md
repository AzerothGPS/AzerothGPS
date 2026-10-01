# Public API for companion addons

`Api.lua` publishes a global table `AzerothGPS` (version 11) so other addons, such as
AzerothGPS-StreetView, can read the map's geometry and draw on the map. It stays display
only, like the rest of AzerothGPS. Declare `## Dependencies: AzerothGPS` in your toc.

World coordinates are yards on a continent: **x points north, y points west**, in the order
`UnitPosition` returns them (see `coordinates.md`). Map offsets are UI units from the map's
center, +x right and +y up.

## Geometry

| Function | Returns |
|---|---|
| `PlayerWorld()` | x, y, continent, z; nil in instances or when the game hides it |
| `Facing()` | radians, counter-clockwise from north |
| `BaseContinent(cont)` | the continent an underground city level is drawn on |
| `ToContinent(from, x, y, to)` | (x, y) on continent `from` in continent `to`'s coordinates, by where both sit on the world map (a spot on one continent drawn over the other's world map); nil when either has no world frame. A map shown as an inset on the world map (Zephras Isle, continent 2991) lands on its inset (version 7) |
| `LocateWorld(cont, x, y)` | uiMapID, zone name, u (east), v (south) of the smallest zone there |
| `MapToWorld(uiMapID, u, v)` | x, y, continent |
| `Roads(cont)` | the shipped road network, read only (`Data/Roads.lua` format) |
| `NearestRoad(cont, x, y)` | x, y, distance, edge index of the closest road point routing uses; nil while that continent's roads are still being built in the background (a moment after a /reload) |
| `RoadEdge(cont, edge)` | that edge's table, read only; its points start at index 5 |

## The map window

| Function | Returns |
|---|---|
| `MapFrame()` | `AzerothGPSFrame` |
| `MapCanvas()` | the clipped map area |
| `MapButtonParent()` | a frame above the map for your buttons (anchor inside it) |
| `MapShown()` | whether the map is visible |
| `MapButton(name)` | the map's `"recenter"` button (Back to your position; shown only while panned away) or `"import"` button (always shown), to place your buttons around them |
| `View()` | center x, y, continent, rotation, scale (UI units per yard), half width |
| `SaveView()` | the whole map view, to put back later (version 8): following the player, or the map browsed (a continent's, the world's, a zone's, a dungeon's and its floor) with its zoom and middle, or the terrain view looked around. An opaque table |
| `RestoreView(state)` | puts back a view from `SaveView` (right-click still goes back where it did); nil, following, or no longer valid: follows the player (version 8) |
| `CursorWorld()` | x, y, continent under the mouse pointer; nil unless it's over the map. On a dungeon's map: its level as the continent, and a 4th value, z: the height there on the floor shown |
| `Instance()` | the dungeon or raid whose map is in view: level (20000 + MapID: its coordinates' "continent"), MapID, name, the floor shown (0: all, else counted from the top), how many floors; nil when none is. The game hides the player's position inside, so pick spots here by browsing its map (its entrance's icon, or it's shown while the player is in it) with the `+` / `-` floor buttons |
| `InstanceFloors(level)` | its floors, lowest first: `{ { lowest z, highest z }, ... }` |
| `WorldToMap(x, y)` | the point's offset from the map's center as drawn now |

## Drawing on the map

- `SetOverlay(name, fn)`: `fn(ctx)` runs on every redraw inside a `pcall`. `ctx.cont` is the
  continent in view and `ctx.zoom` the yards from center to edge. Draw with
  `ctx.Line(x1, y1, x2, y2, {r, g, b}, width, alpha, dotted)` and
  `ctx.Dot(x, y, {r, g, b}, size, alpha)` in world yards; `ctx.ToScreen(x, y)` converts.
  `ctx.Icon(x, y, texture, size, alpha)` (version 10) puts an icon there: a file id, a path or
  `"atlas:<name>"`, `size` UI units across.
  The lines join the map's own: clipped, rotated with the map, drawn above the route, never
  faded. Pass `nil` to remove the overlay. Errors are logged like the map's own.
- `ShowRoads(owner, on, {r, g, b})`: shows the road network in that color while any owner
  asks. The player's own road option wins.
- `HoldMap(owner, on, onDoubleClick)`: while any owner holds the map (a game on it), the
  route (still followed; the arrow window is unchanged), the stops' pins, the crosshair with
  Confirm Route and the top panel aren't shown, and a double-click on the map or one of its
  icons calls `onDoubleClick(x, y, continent)` instead of making a stop. `on = false` lets go.
- `HoldMap(owner, on, onDoubleClick, opts)` (version 9): `opts.style` draws the map in that style
  while it's held, at every zoom as for a player who picked it, whatever the player's own setting
  (which isn't changed, and is back on release): `"minimap"` (the terrain view), `"zone"` (the
  world map's art, every area shown), `"unrevealed"` (the world map's art with no area shown at
  all: the same for every character), or `"nospoiler"` (the areas this character explored).
  Holding again with another style updates it. Meanwhile the Map Style buttons and `/agps style`
  don't change it (they say the game on the map sets it). No `opts`, or no style: as before.
  An older AzerothGPS ignores the 4th argument: check `AzerothGPS.version >= 9`.
- `LookAt(cont, x, y, zoom)`: centers the map on that spot, north up, `zoom` yards from the
  middle to the edge. "Back to your position" or `Follow()` returns to the player.
- `ShowWorld()`: the world map, as right-clicking out to the top level (from the terrain view, a
  click on a continent and then on a spot comes back to the terrain view there).
- `Follow()`: back to following the player.
- `Window(name, width, height, title, strata)` (version 11): a popup window in AzerothGPS's style, the
  map window's frame without the logo (the game's metal border, title bar and close button, a dark
  inside, the title centered), movable and closed by Escape; a plain dark box with a border where the
  client lacks the template. It starts hidden; put its content from `f.top` (negative) down, and
  change the title with `f:SetWindowTitle(text)`.
- `ShowMap()`: shows the map window when the player has it hidden.
- `TopPanelInset()`: the left inset (pixels) the top panel starts at: past the window frame's
  portrait when the frame is on, else 4. Line up a panel of your own there with it.
- `OnLayout(owner, fn)`: `fn(inset)` is called when that inset changes (the window frame turned
  on or off); `fn = nil` stops.
- `Redraw()`: the map redraws on its next frame. The map skips redraws when nothing it knows
  about changed, so call this after changing what your overlay draws.

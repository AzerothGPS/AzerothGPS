# Public API for companion addons

`Api.lua` publishes a global table `AzerothGPS` (version 1) so other addons, such as
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
| `LocateWorld(cont, x, y)` | uiMapID, zone name, u (east), v (south) of the smallest zone there |
| `MapToWorld(uiMapID, u, v)` | x, y, continent |
| `Roads(cont)` | the shipped road network, read only (`Data/Roads.lua` format) |
| `NearestRoad(cont, x, y)` | x, y, distance, edge index of the closest road point routing uses |
| `RoadEdge(cont, edge)` | that edge's table, read only; its points start at index 5 |

## The map window

| Function | Returns |
|---|---|
| `MapFrame()` | `AzerothGPSFrame` |
| `MapCanvas()` | the clipped map area |
| `MapButtonParent()` | a frame above the map for your buttons (anchor inside it) |
| `MapShown()` | whether the map is visible |
| `View()` | center x, y, continent, rotation, scale (UI units per yard), half width |
| `CursorWorld()` | x, y, continent under the mouse pointer; nil unless it's over the map |
| `WorldToMap(x, y)` | the point's offset from the map's center as drawn now |

## Drawing on the map

- `SetOverlay(name, fn)`: `fn(ctx)` runs on every redraw inside a `pcall`. `ctx.cont` is the
  continent in view and `ctx.zoom` the yards from center to edge. Draw with
  `ctx.Line(x1, y1, x2, y2, {r, g, b}, width, alpha, dotted)` and
  `ctx.Dot(x, y, {r, g, b}, size, alpha)` in world yards; `ctx.ToScreen(x, y)` converts.
  The lines join the map's own: clipped, rotated with the map, drawn above the route, never
  faded. Pass `nil` to remove the overlay. Errors are logged like the map's own.
- `ShowRoads(owner, on, {r, g, b})`: shows the road network in that color while any owner
  asks. The player's own road option wins.
- `Redraw()`: the map redraws on its next frame. The map skips redraws when nothing it knows
  about changed, so call this after changing what your overlay draws.

-- Public API for companion addons (AzerothGPS-StreetView and others): read the map's
-- geometry and draw on the map. Display only, like the rest of AzerothGPS. See docs/api.md.
-- World coordinates are yards on a continent: x points north, y points west (UnitPosition's
-- order). Everything here is safe to call before the map exists; it returns nil then.
local _, ns = ...

local API = { version = 9 }
_G.AzerothGPS = API

local function GPS() return ns.GPS end

-- The player: x, y, continent, z (nil in instances or when the game hides it).
function API.PlayerWorld() return ns.Geo.PlayerWorld() end
-- Facing in radians, counter-clockwise from north (0 when unavailable).
function API.Facing() return ns.Geo.Facing() end
-- The continent an underground city level (a pseudo-continent) is drawn on; others unchanged.
function API.BaseContinent(cont) return ns.Geo.Base(cont) end
-- (x, y) on continent `from` in continent `to`'s coordinates, by where both sit on the world map
-- (to draw a spot on one continent over the other's on the world map); nil when either has none.
-- (Version 7: a map shown as an inset on the world map, Zephras Isle, lands on its inset.)
function API.ToContinent(from, x, y, to) return ns.Geo.ToContinent(from, x, y, to) end
-- (Version 8) The whole map view, to put back later (a game on the map ending): following the
-- player, or the map browsed (a continent's, the world's, a zone's, a dungeon's and its floor)
-- with its zoom and middle, or the terrain view looked around. An opaque table.
function API.SaveView()
  local G = GPS()
  if not G then return nil end
  return G.SaveView() or { follow = true }
end
-- Put back a view from SaveView; nil, following, or one no longer valid: following the player.
function API.RestoreView(state)
  local G = GPS()
  if not G then return end
  if type(state) ~= "table" or state.follow or not state.x then return G.Follow() end
  G.ApplyView(state)
end
-- The smallest zone on continent `cont` containing (x, y): uiMapID, name, u (east), v (south).
-- (not `GPS() and GPS().f()`: `and` keeps only a call's first value)
function API.LocateWorld(cont, x, y)
  if GPS() then return GPS().LocateWorld(cont, x, y) end
end
-- uiMap point (u east, v south, 0-1) -> world x, y and the map's continent.
function API.MapToWorld(mapID, u, v)
  local m = ns.Maps and ns.Maps[mapID]
  local b = m and m.bounds
  if not b then return nil end
  return b[3] - v * (b[3] - b[1]), b[4] - u * (b[4] - b[2]), m.continent
end

-- The shipped road network of `cont` (read only!): { n = { x1, y1, ... }, e = { { a, b, len,
-- source, x, y, x, y, ... }, ... } }. Data/Roads.lua has the details.
function API.Roads(cont) return ns.Roads and ns.Roads[cont] end
-- The nearest point on the road network routing uses: x, y, distance (yards), edge index.
function API.NearestRoad(cont, x, y)
  local R = ns.Router
  -- (the continent's roads not built yet, after a /reload: built in the background, nil meanwhile,
  -- rather than all at once in this frame)
  if R and R.WARM and not R.SYNC_WALKS and R.GraphReady and (not R.GraphReady(cont) or (R.Warming and R.Warming())) then
    R.WarmUp(cont, x, y)
    return nil
  end
  local n = R and R.Nearest and R.Nearest(cont, x, y)
  if not n then return nil end
  return n.px, n.py, n.dist, n.edge
end
-- That edge's points (read only!), as in API.Roads: e[5], e[6] is its first point.
function API.RoadEdge(cont, edge)
  local R = ns.Router
  local edges = R and R.Edges and R.Edges(cont)
  return edges and edges[edge]
end

-- The map window (AzerothGPSFrame), its clipped map area, and a frame above the map for
-- buttons (anchor to it; it isn't clipped).
function API.MapFrame() return _G.AzerothGPSFrame end
function API.MapCanvas() return GPS() and GPS().Canvas() end
function API.MapButtonParent() return GPS() and GPS().TopLayer() end
-- One of the map's own buttons, to place yours around it: "recenter" (Back to your
-- position: shown only while the map is panned away from you) or "import" (always shown).
function API.MapButton(name)
  local b = GPS() and GPS().mapButtons
  return b and b[name] or nil
end
function API.MapShown() return GPS() and GPS().IsVisible() or false end
-- The last drawn view: center x, y, continent, rotation (radians), scale (UI units per
-- yard), half the map's width (UI units).
function API.View()
  if not GPS() then return nil end
  return GPS().ViewState()
end
-- The world point under the mouse pointer: x, y, continent (on a dungeon's map: its level,
-- and z, the height there on the floor shown); nil unless it's over the map.
function API.CursorWorld()
  if GPS() then return GPS().CursorWorld() end
end

-- The dungeon or raid whose map is in view (browsed from its entrance's icon, or the one the
-- player is in: the game hides their position there): level (20000 + its MapID, the
-- "continent" its coordinates are in), MapID, name, the floor shown (0: all of them, else
-- counted from the top; the map's "+" / "-" buttons), how many floors. nil when none is.
function API.Instance()
  local G = GPS()
  if not (G and G.ViewInstance) then return nil end
  local lvl, floor = G.ViewInstance()
  local info = lvl and ns.Instances and ns.Instances[lvl]
  if not info then return nil end
  return lvl, info.map, info.name, floor or 0, #G.InstanceFloors(lvl)
end
-- A dungeon's floors, lowest first: { { lowest height, highest }, ... } (world z).
function API.InstanceFloors(level)
  local G = GPS()
  return G and G.InstanceFloors and G.InstanceFloors(level) or {}
end
-- A world point's offset from the map's center in UI units (+x right, +y up), as drawn now.
function API.WorldToMap(x, y)
  if not GPS() then return nil end
  local cx, cy, _, rot, s = GPS().ViewState()
  local dx, dy = ns.Geo.ScreenOffset(cx, cy, x, y)
  return ns.Geo.Rotate(dx * s, dy * s, rot)
end

-- Draw on the map: fn(ctx) runs on every redraw (in a pcall). ctx.cont is the continent in
-- view; ctx.Line(x1, y1, x2, y2, { r, g, b }, width, alpha, dotted) and
-- ctx.Dot(x, y, { r, g, b }, size, alpha) take world yards; ctx.ToScreen(x, y) gives UI units
-- from the center; ctx.zoom is yards from center to edge. fn = nil removes it.
function API.SetOverlay(name, fn)
  if not GPS() then return end
  GPS().overlays[name] = fn
  GPS().Redraw()
end
-- Show the road network (in color { r, g, b }) while `owner` wants it; on = false stops.
function API.ShowRoads(owner, on, color)
  if not GPS() then return end
  GPS().roadOwners[owner] = on and (color or { 0.25, 0.6, 1 }) or nil
  GPS().Redraw()
end
-- Hold the map for a while (a game on it): while any owner holds it, the route (still followed,
-- and the arrow window unchanged), the stops' pins, the crosshair with Confirm Route and the top
-- panel aren't shown, and a double-click on the map (or on one of its icons) calls
-- onDoubleClick(x, y, continent) instead of making a stop. on = false lets go.
-- (Version 9) `opts.style`: the map drawn in that style while held, whatever the player's own setting
-- (not changed; back on release): "minimap" (the terrain view), "zone" (the world map's art, every area
-- shown), "unrevealed" (the world map's art with no area shown: the same for every character), or
-- "nospoiler". The style buttons and /agps style don't change it meanwhile. Holding again updates it.
function API.HoldMap(owner, on, onDoubleClick, opts)
  local G = GPS()
  if not G then return end
  local style = type(opts) == "table" and G.HOLD_STYLES[opts.style] and opts.style or nil
  G.SetHolder(owner, on and { click = onDoubleClick, style = style } or nil)
end
-- Look at a spot: the map centered on (x, y) of `cont`, north up, `zoom` yards from the middle
-- to the edge. "Back to your position" (or API.Follow) returns to the player.
function API.LookAt(cont, x, y, zoom)
  if GPS() then GPS().LookAt(cont, x, y, zoom) end
end
-- The world map (both continents), as right-clicking out to the top level.
function API.ShowWorld()
  if GPS() then GPS().ShowWorld() end
end
-- Back to following the player.
function API.Follow()
  if GPS() then GPS().Follow() end
end
-- Show the map window (when the player has it hidden).
function API.ShowMap()
  if not (ns.settings and ns.settings.gps) then return end
  ns.settings.gps.shown = true
  if ns.Options and ns.Options.Apply then ns.Options.Apply() elseif GPS() then GPS().ApplySettings() end
end

-- The left inset (pixels from the map's left edge) the top panel starts at now: past the window
-- frame's portrait when the frame is on, else 4. A panel of your own there can line up with it.
function API.TopPanelInset()
  local G = GPS()
  return G and G.topInset or 4
end
-- fn(inset) is called when that inset changes (the window frame turned on or off); fn = nil stops.
function API.OnLayout(owner, fn)
  local G = GPS()
  if G then G.layoutHooks[owner] = fn end
end

-- Redraw the map on its next frame (after changing what an overlay draws).
function API.Redraw()
  if GPS() then GPS().Redraw() end
end

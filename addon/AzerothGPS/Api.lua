-- Public API for companion addons (AzerothGPS-StreetView and others): read the map's
-- geometry and draw on the map. Display only, like the rest of AzerothGPS. See docs/api.md.
-- World coordinates are yards on a continent: x points north, y points west (UnitPosition's
-- order). Everything here is safe to call before the map exists; it returns nil then.
local _, ns = ...

local API = { version = 1 }
_G.AzerothGPS = API

local function GPS() return ns.GPS end

-- The player: x, y, continent, z (nil in instances or when the game hides it).
function API.PlayerWorld() return ns.Geo.PlayerWorld() end
-- Facing in radians, counter-clockwise from north (0 when unavailable).
function API.Facing() return ns.Geo.Facing() end
-- The continent an underground city level (a pseudo-continent) is drawn on; others unchanged.
function API.BaseContinent(cont) return ns.Geo.Base(cont) end
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
-- The world point under the mouse pointer: x, y, continent; nil unless it's over the map.
function API.CursorWorld()
  if GPS() then return GPS().CursorWorld() end
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
-- Redraw the map on its next frame (after changing what an overlay draws).
function API.Redraw()
  if GPS() then GPS().Redraw() end
end

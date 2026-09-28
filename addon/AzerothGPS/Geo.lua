-- World geometry. World coordinates are yards: X points north, Y points west
-- (the order UnitPosition returns). See docs/coordinates.md.
local _, ns = ...

local Geo = {}
ns.Geo = Geo

Geo.TILE = 1600 / 3 -- yards per terrain tile; 64x64 tiles per continent

-- Player position: world X, Y, continent (instance) ID and height Z; nil in instances.
function Geo.PlayerWorld()
  local ok, x, y, z, inst = pcall(UnitPosition, "player")
  if not ok or not x or ns.IsSecret(x) or ns.IsSecret(y) then return nil end
  return x, y, inst, z or 0
end

-- Facing in radians, counter-clockwise from north (0 when unavailable).
function Geo.Facing()
  local ok, f = pcall(GetPlayerFacing)
  if ok and f and not ns.IsSecret(f) then return f end
  return 0
end

-- World (X, Y) -> fractional terrain tile (tx east, ty south).
function Geo.WorldToTile(x, y)
  return 32 - y / Geo.TILE, 32 - x / Geo.TILE
end

-- Offset of world point (x, y) from the player, in screen yards: +right = east, +up = north.
function Geo.ScreenOffset(px, py, x, y)
  return py - y, x - px
end

-- Rotate (dx, dy) counter-clockwise by angle a.
function Geo.Rotate(dx, dy, a)
  local c, s = math.cos(a), math.sin(a)
  return dx * c - dy * s, dx * s + dy * c
end

-- The world map (Azeroth) shows both continents on one image; each continent's region
-- maps to its own rectangle of it (Data/Maps.lua worldFrames).
function Geo.WorldMap()
  if Geo.worldMapID == nil then
    Geo.worldMapID = false
    for id, m in pairs(ns.Maps or {}) do
      if m.worldFrames then Geo.worldMapID = id end
    end
  end
  return Geo.worldMapID or nil
end

-- Bounds {minX, minY, maxX, maxY} of the whole world map image, expressed in continent
-- `cont`'s world coordinates (extrapolated beyond that continent).
function Geo.WorldArtBounds(cont)
  local id = Geo.WorldMap()
  local wf = id and ns.Maps[id].worldFrames[cont]
  if not wf then return nil end
  local ky = (wf[4] - wf[2]) / (wf[7] - wf[5]) -- yards of Y per unit of u (east-west)
  local kx = (wf[3] - wf[1]) / (wf[8] - wf[6]) -- yards of X per unit of v (north-south)
  local maxY = wf[4] + wf[5] * ky
  local maxX = wf[3] + wf[6] * kx
  return { maxX - kx, maxY - ky, maxX, maxY }
end

-- World position (x, y) on continent `from` -> the matching point in continent `to`'s
-- coordinates, via the world map (for drawing routes across the sea).
-- City levels (Data/Cities.lua): an underground city routes as its own level, a
-- pseudo-continent that is drawn in its base continent's coordinates.
function Geo.Base(cont)
  local l = ns.CityLevels and ns.CityLevels[cont]
  return l and l.base or cont
end

-- The continent (or city level) of uiMap `mapID`: an underground city's map gives its level.
function Geo.MapCont(mapID)
  for id, l in pairs(ns.CityLevels or {}) do
    if l.map == mapID then return id end
  end
  local m = ns.Maps and ns.Maps[mapID]
  return m and m.continent
end

function Geo.ToContinent(from, x, y, to)
  from, to = Geo.Base(from), Geo.Base(to)
  if from == to then return x, y end
  local a, b = Geo.WorldArtBounds(from), Geo.WorldArtBounds(to)
  if not a or not b then return nil end
  local u = (a[4] - y) / (a[4] - a[2])
  local v = (a[3] - x) / (a[3] - a[1])
  return b[3] - v * (b[3] - b[1]), b[4] - u * (b[4] - b[2])
end

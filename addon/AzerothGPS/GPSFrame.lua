-- The GPS frame: a square, clipped map around the player drawn from the game's
-- own textures (by FileDataID), heading-up or north-up, adjustable opacity.
local _, ns = ...
local Geo = ns.Geo

local G = {}
ns.GPS = G

local TILE = Geo.TILE
local MIN_ZOOM, MAX_ZOOM = 60, 2500
local BORDER = 3
local CHROME_TITLE = 22 -- title bar height of the game-style window frame (while unlocked)
local MAP_BUTTON = 32 -- the round map menu button (bottom-left)
local MENU_IDLE = 20 -- seconds: the map menu (and its toggles column) closes by itself
local SEARCH_IDLE = 20 -- ... and the search panel
local LASSO_COLOR = { 1, 0.82, 0 } -- a farming area being drawn
local DRAW_COLOR, ERASE_COLOR = { 0.3, 1, 0.3 }, { 1, 0.2, 0.2 } -- a road being drawn / erased
local WALL_COLOR, UNWALL_COLOR = { 0.55, 0.02, 0.02 }, { 0.6, 0.6, 0.6 } -- a wall being drawn (blood red) / erased
local CHROME_PORTRAIT_INSET = 46 -- the frame's portrait covers this much of the map's top-left

-- Texture:SetRotation turns the image counter-clockwise for positive angles.
-- If the in-game test shows tiles turning the wrong way, flip with /agps debug rotsign.
G.rotSign = 1

---------------------------------------------------------------------------
-- Layout (pure; unit-tested outside the game)
---------------------------------------------------------------------------

-- A north-aligned world rectangle [minX, maxX] x [minY, maxY] showing texture coords
-- [u0, u1] x [v0, v1] (u runs east, v runs south), cropped to the view box around
-- (cx, cy) with half-size R yards. Returns the quad for it, or nil when out of view.
-- Cropping keeps every drawn region small: the game stops drawing very large regions,
-- which blanked the map when zoomed right in.
function G.CropQuad(fid, minX, maxX, minY, maxY, u0, u1, v0, v1, cx, cy, R, rot, s, sublayer)
  local X0, X1 = math.max(minX, cx - R), math.min(maxX, cx + R)
  local Y0, Y1 = math.max(minY, cy - R), math.min(maxY, cy + R)
  if X0 >= X1 or Y0 >= Y1 then return nil end
  local du, dv = (u1 - u0) / (maxY - minY), (v1 - v0) / (maxX - minX)
  local cu0, cu1 = u0 + (maxY - Y1) * du, u0 + (maxY - Y0) * du
  local cv0, cv1 = v0 + (maxX - X1) * dv, v0 + (maxX - X0) * dv
  local dx, dy = Geo.ScreenOffset(cx, cy, (X0 + X1) / 2, (Y0 + Y1) / 2)
  dx, dy = Geo.Rotate(dx * s, dy * s, rot)
  return { fid, dx, dy, (Y1 - Y0) * s + 1, (X1 - X0) * s + 1, rot, cu0, cu1, cv0, cv1, sublayer }
end

-- Returns a list of quads { fid, x, y, w, h, rot, l, r, t, b, sublayer } in UI units,
-- relative to the frame center (+y up), for the view centered on world (px, py).
-- `rot` is the map rotation (radians, CCW); l/r/t/b are texture coords.
function G.LayoutMinimap(px, py, cont, rot, zoom, half)
  local tiles = ns.MinimapTiles and ns.MinimapTiles[cont]
  local quads = {}
  if not tiles then return quads end
  local s = half / zoom -- UI units per yard
  local R = zoom * 1.42 -- covers the view's corners at any rotation
  local ptx, pty = Geo.WorldToTile(px, py)
  local span = R / TILE + 1
  for tx = math.floor(ptx - span), math.floor(ptx + span) do
    for ty = math.floor(pty - span), math.floor(pty + span) do
      local fid = tiles[tx * 64 + ty]
      if fid then
        local maxX, maxY = (32 - ty) * TILE, (32 - tx) * TILE -- north-west corner
        local q = G.CropQuad(fid, maxX - TILE, maxX, maxY - TILE, maxY, 0, 1, 0, 1, px, py, R, rot, s, 0)
        if q then quads[#quads + 1] = q end
      end
    end
  end
  return quads
end

-- Zone map art (fully explored) for uiMap `mapID`, placed in world space.
-- Explored parts of uiMap `id`'s art, as overlay tiles like Maps.lua's ({ fileID, x, y, w,
-- h, texW, texH }), from what the game says the player has explored
-- (C_MapExplorationInfo, as the world map uses). Cached; refreshed every few seconds.
local explored = {} -- [id] = { t, tiles }
G.EXPLORED_TTL = 10
function G.ExploredOverlays(id)
  local c = explored[id]
  local now = GetTime()
  if c and now - c.t < G.EXPLORED_TTL then return c.tiles end
  local tiles = {}
  local api = C_MapExplorationInfo and C_MapExplorationInfo.GetExploredMapTextures
  for _, e in ipairs(api and api(id) or {}) do
    if not e.isShownByMouseOver and e.fileDataIDs then
      local wide = math.ceil(e.textureWidth / 256)
      local tall = math.ceil(e.textureHeight / 256)
      for j = 1, tall do
        for k = 1, wide do
          local fid = e.fileDataIDs[(j - 1) * wide + k]
          if fid then
            -- the last column/row is narrower; its file is the next power of two
            local w = k < wide and 256 or (e.textureWidth - 256 * (wide - 1))
            local h = j < tall and 256 or (e.textureHeight - 256 * (tall - 1))
            local texW, texH = 16, 16
            while texW < w do texW = texW * 2 end
            while texH < h do texH = texH * 2 end
            tiles[#tiles + 1] = { fid, e.offsetX + 256 * (k - 1), e.offsetY + 256 * (j - 1), w, h, texW, texH }
          end
        end
      end
    end
  end
  explored[id] = { t = now, tiles = tiles }
  return tiles
end

-- Map styles that draw world map art: "zone" (fully explored) and "nospoiler" (only what
-- the character has explored).
function G.IsMapStyle(style) return style == "zone" or style == "nospoiler" end

-- `noSpoiler`: only the explored overlays (what this character has discovered).
function G.LayoutZone(px, py, mapID, rot, zoom, half, bounds, noSpoiler)
  local quads = {}
  local m = ns.Maps and ns.Maps[mapID]
  while m and not m.tiles do
    mapID = m.parent
    m = ns.Maps[mapID]
  end
  local b = bounds or (m and m.bounds) -- the world map has no bounds of its own: passed in
  if not m or not b then return quads end
  local s = half / zoom
  local R = zoom * 1.42
  local minX, minY, maxX, maxY = b[1], b[2], b[3], b[4]
  local ydx = (maxX - minX) / m.artH -- world X yards per art pixel (north-south)
  local ydy = (maxY - minY) / m.artW -- world Y yards per art pixel (east-west)
  local function add(list, sublayer)
    if not list then return end
    for _, q in ipairs(list) do
      local fid, ax, ay, w, h, texW, texH = q[1], q[2], q[3], q[4], q[5], q[6], q[7]
      local qMaxX, qMaxY = maxX - ay * ydx, maxY - ax * ydy
      local c = G.CropQuad(fid, qMaxX - h * ydx, qMaxX, qMaxY - w * ydy, qMaxY, 0, w / texW, 0, h / texH,
        px, py, R, rot, s, sublayer)
      if c then quads[#quads + 1] = c end
    end
  end
  add(m.tiles, 0)
  if noSpoiler then
    add(G.ExploredOverlays(mapID), 1)
  else
    add(m.overlays, 1) -- explored areas draw over the base art
  end
  return quads
end

-- Per-continent edge bounding boxes for culling: { minX, maxX, minY, maxY, edge }.
local roadIndex = {}

-- The roads as routing sees them (shipped plus recorded; rebuilt when recordings change).
local function RoadIndex(cont)
  local edges, g
  if ns.Router then
    edges, g = ns.Router.Edges(cont)
  else
    local roads = ns.Roads and ns.Roads[cont]
    edges, g = roads and roads.e, roads
  end
  local c = roadIndex[cont]
  if c and c.g == g then return c.idx end
  local idx = {}
  if edges then
    for _, e in ipairs(edges) do
      local minX, maxX, minY, maxY = math.huge, -math.huge, math.huge, -math.huge
      for i = 5, #e, 2 do
        local x, y = e[i], e[i + 1]
        if x < minX then minX = x end
        if x > maxX then maxX = x end
        if y < minY then minY = y end
        if y > maxY then maxY = y end
      end
      idx[#idx + 1] = { minX, maxX, minY, maxY, e }
    end
  end
  roadIndex[cont] = { g = g, idx = idx }
  return idx
end

G.MAX_SEGMENTS = 1500

-- The terrain's impassable edges near a view (mountains, cliffs: Passability.At == 2), as
-- world segments { x1, y1, x2, y2, ... } (flat): the borders between blocked and open
-- samples on a grid of `step` yards (the terrain's cell, coarser zoomed out). Worked out
-- for a block around the view and kept while the view stays in it.
G.EDGE_SAMPLES = 48 -- samples across the view's half width, at least
G.EDGE_MS = 2 -- ms of a frame spent working a new outline out (the old one stays meanwhile)
local edgeCache, edgeJob = {}, nil
function G.ClearEdges() edgeCache, edgeJob = {}, nil end -- (walls or wall erasers changed)
local function EdgeWork(cont, g, P, step, x0, x1, y0, y1)
  local nx, ny = math.floor((x1 - x0) / step), math.floor((y1 - y0) / step)
  local blocked = {}
  for i = 0, nx - 1 do
    local row = {}
    local x = x0 + (i + 0.5) * step
    for j = 0, ny - 1 do row[j] = P.At(cont, x, y0 + (j + 0.5) * step) == 2 end
    blocked[i] = row
    coroutine.yield()
  end
  local segs = {}
  local function line(ax, ay, bx, by)
    segs[#segs + 1], segs[#segs + 2], segs[#segs + 3], segs[#segs + 4] = ax, ay, bx, by
  end
  -- borders across x (between rows i and i + 1), merged along y; then across y
  for i = 0, nx - 2 do
    local a, b = blocked[i], blocked[i + 1]
    local x = x0 + (i + 1) * step
    local run
    for j = 0, ny do
      local edge = j < ny and a[j] ~= b[j]
      if edge and not run then run = j
      elseif not edge and run then
        line(x, y0 + run * step, x, y0 + j * step)
        run = nil
      end
    end
  end
  for j = 0, ny - 2 do
    local y = y0 + (j + 1) * step
    local run
    for i = 0, nx do
      local edge = i < nx and blocked[i][j] ~= blocked[i][j + 1]
      if edge and not run then run = i
      elseif not edge and run then
        line(x0 + run * step, y, x0 + i * step, y)
        run = nil
      end
    end
  end
  return segs
end

function G.BlockEdges(cont, cx, cy, zoom)
  local P = ns.Passability
  local g = ns.Terrain and ns.Terrain[cont]
  if not (P and P.At and g) then return {} end
  local step = g.cell
  while step < zoom / G.EDGE_SAMPLES do step = step * 2 end
  local chunk = step * 32
  local reach = zoom * 1.4
  local x0, x1 = math.floor((cx - reach) / chunk) * chunk, math.ceil((cx + reach) / chunk) * chunk
  local y0, y1 = math.floor((cy - reach) / chunk) * chunk, math.ceil((cy + reach) / chunk) * chunk
  local key = string.format("%s:%g:%g:%g:%g:%g", tostring(cont), step, x0, x1, y0, y1)
  if edgeCache.key == key then return edgeCache.segs end
  -- (a new block: worked out a little each frame by G.PumpEdges, the last one shown meanwhile)
  if not edgeJob or edgeJob.key ~= key then
    edgeJob = { key = key, cont = cont, co = coroutine.create(EdgeWork) }
    edgeJob.args = { cont, g, P, step, x0, x1, y0, y1 }
  end
  if not debugprofilestop then G.PumpEdges() end -- (no frames to spread it over: all now)
  if edgeCache.key == key then return edgeCache.segs end
  if edgeCache.cont == cont then return edgeCache.segs or {} end
  return {}
end

-- An error in the map's work: kept (ns.db.errors, the last 20, read with `agps probes`-style
-- tools after a /reload) and said once per kind in chat.
local errorSaid = {}
function G.LogError(what, err)
  G.lastError = tostring(err)
  if ns.db then
    ns.db.errors = ns.db.errors or {}
    local list = ns.db.errors
    list[#list + 1] = { what = what, err = G.lastError, time = time and time() or 0,
      stack = debugstack and debugstack(2, 8, 0) or nil }
    while #list > 20 do table.remove(list, 1) end
  end
  if not errorSaid[what] then
    errorSaid[what] = true
    ns.Print("GPS error (" .. what .. "): " .. G.lastError)
  end
end

-- Every frame: a little more of the outline being worked out (EDGE_MS); the map redrawn
-- once it's done.
function G.PumpEdges()
  if not edgeJob then return end
  local clock = debugprofilestop
  local t0 = clock and clock()
  repeat
    local ok, res = coroutine.resume(edgeJob.co, (unpack or table.unpack)(edgeJob.args))
    if not ok then
      edgeJob = nil
      return
    end
    if coroutine.status(edgeJob.co) == "dead" then
      edgeCache.key, edgeCache.segs, edgeCache.cont = edgeJob.key, res, edgeJob.cont
      edgeJob = nil
      if G.Redraw then G.Redraw() end
      return
    end
  until clock and clock() - t0 >= G.EDGE_MS
end

-- Walls near the view (Passability.WallLines, and with `edges` the terrain's impassable
-- borders: G.BlockEdges): { x1, y1, x2, y2 } in UI units.
function G.LayoutWalls(px, py, cont, rot, zoom, half, edges)
  local segs = {}
  local P = ns.Passability
  if not (P and P.WallLines) then return segs end
  local s = half / zoom
  local reach = zoom * 1.5
  if edges then
    local e = G.BlockEdges(cont, px, py, zoom)
    for i = 1, #e - 3, 4 do
      local ax, ay, bx, by = e[i], e[i + 1], e[i + 2], e[i + 3]
      if math.abs(ax - px) <= reach or math.abs(bx - px) <= reach then
        if math.abs(ay - py) <= reach or math.abs(by - py) <= reach then
          local dx1, dy1 = Geo.ScreenOffset(px, py, ax, ay)
          dx1, dy1 = Geo.Rotate(dx1 * s, dy1 * s, rot)
          local dx2, dy2 = Geo.ScreenOffset(px, py, bx, by)
          dx2, dy2 = Geo.Rotate(dx2 * s, dy2 * s, rot)
          segs[#segs + 1] = { dx1, dy1, dx2, dy2, edge = true }
          if #segs >= G.MAX_SEGMENTS then return segs end
        end
      end
    end
  end
  for _, w in ipairs(P.WallLines(cont)) do
    local lx, ly
    for i = 1, #w - 1, 2 do
      local wx, wy = w[i], w[i + 1]
      local dx, dy = Geo.ScreenOffset(px, py, wx, wy)
      dx, dy = Geo.Rotate(dx * s, dy * s, rot)
      if lx and (math.abs(wx - px) <= reach and math.abs(wy - py) <= reach or math.abs(dx) <= half * 2) then
        segs[#segs + 1] = { lx, ly, dx, dy }
      end
      lx, ly = dx, dy
    end
  end
  return segs
end

-- Road segments near the player: list of { x1, y1, x2, y2, source } in UI units
-- relative to the frame center. source: 0 road (the player's drawn ones too), 1 bridged
-- gap, 3 a drop off a ledge.
local RECORDED = 9 -- (Router.SOURCE_RECORDED)
function G.LayoutRoads(px, py, cont, rot, zoom, half)
  local segs = {}
  local s = half / zoom
  local reach = zoom * 1.5
  local minStep = 2 / s -- skip points closer than ~2 UI units when zoomed out
  for _, b in ipairs(RoadIndex(cont)) do
    if b[2] > px - reach and b[1] < px + reach and b[4] > py - reach and b[3] < py + reach then
      local e = b[5]
      -- (drawn roads are truth: roads like any, before they're in the data too)
      local src = (e[4] == 2 or e[4] == RECORDED) and 0 or e[4]
      local lx, ly -- last emitted point (screen)
      local wx0, wy0
      local n = #e
      for i = 5, n, 2 do
        local wx, wy = e[i], e[i + 1]
        local last = i >= n - 1
        if not wx0 or last or math.abs(wx - wx0) + math.abs(wy - wy0) >= minStep then
          local dx, dy = Geo.ScreenOffset(px, py, wx, wy)
          dx, dy = Geo.Rotate(dx * s, dy * s, rot)
          if lx then
            segs[#segs + 1] = { lx, ly, dx, dy, src }
            if #segs >= G.MAX_SEGMENTS then return segs end
          end
          lx, ly, wx0, wy0 = dx, dy, wx, wy
        end
      end
    end
  end
  return segs
end

-- Interiors (WMO minimaps; see app/azerothgps/interiors.py for the conventions)

local Z_SLACK = 3 -- yards above/below a group's height range still counted as "in" it
G.INTERIOR_MAX_ZOOM = 500 -- zoomed out further than this, show the outside view instead

-- Height range of the rooms in `w` named `name` (cached): the floor the minimap names.
local function NamedBand(w, name)
  w.bands = w.bands or {}
  local b = w.bands[name]
  if b == nil then
    b = false
    for _, g in ipairs(w.groups) do
      if g.n == name then
        if not b then b = { g[3], g[6] } else b[1], b[2] = math.min(b[1], g[3]), math.max(b[2], g[6]) end
      end
    end
    w.bands[name] = b
  end
  return b or nil
end

-- Squared distance from (x, y) to a room's rectangle (0 inside).
local function RectDist2(g, x, y)
  local dx = math.max(g[1] - x, 0, x - g[4])
  local dy = math.max(g[2] - y, 0, y - g[5])
  return dx * dx + dy * dy
end

-- The building the player at world (px, py) is inside, if any: returns place, wmo and
-- the room ("group") that sets the floor to draw.
-- The client reports height as 0 and Forever says "outdoors" all through Undercity, so
-- without height the floor comes from the minimap zone text: the rooms named like it
-- (e.g. every "Trade Quarter" room) give a height band, and any indoor room containing
-- the player within that band counts, named or not (corridors are often unnamed). With
-- no containing room, the nearest named room is used. Most ordinary buildings' rooms
-- have no name, so standing outside next to one does not trigger this.
-- `cityZ`, `cityWmo`: down in an underground city, the floor's height under the player (its
-- model's own) for that model: its room found by height, like with a known z.
function G.FindInterior(px, py, pz, cont, zoneText, indoors, cityZ, cityWmo)
  local list = ns.Interiors and ns.Interiors[cont]
  if not list then return nil end
  local haveZ = pz and pz ~= 0
  local hasName = zoneText and zoneText ~= ""
  local best, bestWmo, bestGroup, bestScore
  for _, p in ipairs(list) do
    if px >= p[6] - 5 and px <= p[8] + 5 and py >= p[7] - 5 and py <= p[9] + 5 then
      local w = ns.WMOs[p[1]]
      local dx, dy = px - p[2], py - p[3]
      local c, s = math.cos(p[5]), math.sin(p[5])
      local lx, ly, lz = dx * c + dy * s, -dx * s + dy * c, (pz or 0) - p[4]
      local haveZ = haveZ
      if cityZ and p[1] == cityWmo then haveZ, lz = true, cityZ + 1 end
      local band = hasName and NamedBand(w, zoneText)
      local nearest, nearestD
      for _, g in ipairs(w.groups) do
        local named = hasName and g.n == zoneText
        local inside = lx >= g[1] and lx <= g[4] and ly >= g[2] and ly <= g[5]
        local ok
        if haveZ then
          ok = inside and lz >= g[3] - Z_SLACK and lz <= g[6] + Z_SLACK
        else
          local onFloor = band and g[6] >= band[1] - Z_SLACK and g[3] <= band[2] + Z_SLACK
          ok = inside and g["in"] and (named or indoors or onFloor)
        end
        if ok then
          local score = (g[4] - g[1]) * (g[5] - g[2]) * math.max(1, g[6] - g[3])
          if named then score = score * 1e-6 end -- prefer the named room, then the smallest
          if not bestScore or score < bestScore then best, bestWmo, bestGroup, bestScore = p, w, g, score end
        elseif named and not haveZ then
          local d = RectDist2(g, lx, ly)
          if not nearestD or d < nearestD then nearest, nearestD = g, d end
        end
      end
      if not best and nearest and nearestD < 60 * 60 then
        best, bestWmo, bestGroup, bestScore = p, w, nearest, math.huge
      end
    end
  end
  return best, bestWmo, bestGroup
end

-- Step-by-step report of the interior lookup, for /agps debug interior.
function G.DebugInterior()
  local px, py, cont, pz = Geo.PlayerWorld()
  local zt = GetMinimapZoneText and GetMinimapZoneText() or "?"
  local out = { string.format("pos %.1f, %.1f z=%s cont=%s indoors=%s zoneText=%q setting=%s",
    px or 0, py or 0, tostring(pz), tostring(cont), tostring(IsIndoors()), zt, tostring(ns.settings.gps.interiors)) }
  local list = ns.Interiors and ns.Interiors[cont]
  local function try(f, ...) local ok, v = pcall(f, ...); return ok and tostring(v) or "n/a" end
  local mapID = C_Map.GetBestMapForUnit("player")
  out[#out + 1] = string.format("outdoors=%s mounted=%s zone=%q subzone=%q real=%q map=%s(%s)",
    try(IsOutdoors), try(IsMounted), try(GetZoneText), try(GetSubZoneText), try(GetRealZoneText),
    tostring(mapID), mapID and try(function() return C_Map.GetMapInfo(mapID).name end) or "?")
  out[#out + 1] = "interior data: " .. (list and (#list .. " buildings on this continent") or "none")
  for _, p in ipairs(list or {}) do
    if px >= p[6] - 5 and px <= p[8] + 5 and py >= p[7] - 5 and py <= p[9] + 5 then
      local dx, dy = px - p[2], py - p[3]
      local c, sn = math.cos(p[5]), math.sin(p[5])
      local lx, ly = dx * c + dy * sn, -dx * sn + dy * c
      local w = ns.WMOs[p[1]]
      local inXY, named = 0, 0
      for _, g in ipairs(w.groups) do
        if lx >= g[1] and lx <= g[4] and ly >= g[2] and ly <= g[5] then
          inXY = inXY + 1
          if g.n == zt then named = named + 1 end
        end
      end
      out[#out + 1] = string.format("  wmo %d: local %.1f, %.1f; %d rooms contain it, %d named %q",
        p[1], lx, ly, inXY, named, zt)
    end
  end
  local place, _, room = G.FindInterior(px, py, pz, cont, zt, IsIndoors())
  out[#out + 1] = "result: " .. (place and (room.n .. " in wmo " .. place[1]) or "nil")
  return out
end

-- Quads for the floor of room `room` (all indoor rooms overlapping its height range),
-- centered on world (cx, cy).
-- District names inside a building (its rooms' area names, what the zone text shows:
-- "Trade Quarter", "Magic Quarter"), on the level of the room you're in: { { x, y, name } }
-- in world coordinates. Rooms of a name are grouped by nearness; each group gets a label
-- in its middle (by area) when it's big enough, and each name is shown once, on its
-- biggest group (Undercity's canals are many bits). Cached per building and level.
G.LABEL_GROUP_YD = 70 -- rooms of one name closer than this: one label
G.LABEL_MIN_AREA = 1500 -- square yards a label's rooms must cover
local interiorLabels = {}
function G.InteriorLabels(place, wmo, room)
  local key = tostring(place) .. ":" .. tostring(room and room[3] or 0)
  if interiorLabels[key] then return interiorLabels[key] end
  local zlo, zhi = room[3] - Z_SLACK, room[6] + Z_SLACK
  local clusters = {}
  for _, g in ipairs(wmo.groups) do
    if g.n and g.n ~= "" and (g == room or (g["in"] and g[6] >= zlo and g[3] <= zhi)) then
      local x, y = (g[1] + g[4]) / 2, (g[2] + g[5]) / 2
      local area = (g[4] - g[1]) * (g[5] - g[2])
      local into
      for _, c in ipairs(clusters) do
        if c.name == g.n and (c.x / c.area - x) ^ 2 + (c.y / c.area - y) ^ 2 <= G.LABEL_GROUP_YD ^ 2 then into = c break end
      end
      if into then
        into.x, into.y, into.area = into.x + x * area, into.y + y * area, into.area + area
      else
        clusters[#clusters + 1] = { name = g.n, x = x * area, y = y * area, area = area }
      end
    end
  end
  -- one label per name: on its biggest group of rooms
  local biggest = {}
  for _, cl in ipairs(clusters) do
    if cl.area >= G.LABEL_MIN_AREA and (not biggest[cl.name] or cl.area > biggest[cl.name].area) then biggest[cl.name] = cl end
  end
  local c, sn = math.cos(place[5]), math.sin(place[5])
  local out = {}
  for name, cl in pairs(biggest) do
    local lx, ly = cl.x / cl.area, cl.y / cl.area
    out[#out + 1] = { place[2] + lx * c - ly * sn, place[3] + lx * sn + ly * c, name }
  end
  table.sort(out, function(a, b) return a[3] < b[3] end)
  interiorLabels[key] = out
  return out
end

function G.LayoutInterior(cx, cy, place, wmo, room, rot, zoom, half)
  local quads = {}
  local s = half / zoom
  local theta = place[5]
  local c, sn = math.cos(theta), math.sin(theta)
  local texRot = theta + math.pi / 2 + rot -- image "right" is the building's local +x
  local reach = zoom * 1.5 + 128
  local groups = {}
  local zlo, zhi = room[3] - Z_SLACK, room[6] + Z_SLACK
  for _, g in ipairs(wmo.groups) do
    if g == room or (g["in"] and g[6] >= zlo and g[3] <= zhi) then groups[#groups + 1] = g end
  end
  table.sort(groups, function(a, b) return a[6] < b[6] end) -- higher floors drawn last
  for layer, g in ipairs(groups) do
    for _, b in ipairs(g.blocks) do
      local fid, bx, by, w, h = b[1], b[2], b[3], b[4], b[5]
      local lx = g[1] + bx * 128 + w / 4 -- block center, local yards (2 px per yard)
      local ly = g[2] + by * 128 + h / 4
      local wx = place[2] + lx * c - ly * sn
      local wy = place[3] + lx * sn + ly * c
      local dx, dy = Geo.ScreenOffset(cx, cy, wx, wy)
      if math.abs(dx) < reach and math.abs(dy) < reach then
        dx, dy = Geo.Rotate(dx * s, dy * s, rot)
        quads[#quads + 1] = { fid, dx, dy, w / 2 * s + 0.5, h / 2 * s + 0.5, texRot, 0, 1, 0, 1, math.min(layer, 7) }
      end
    end
  end
  return quads
end

-- Points of interest in view: list of { kind, sx, sy, name, x, y, extra, faction }.
-- show = { [1] = flight masters, [2] = map POIs, [3] = place labels } (booleans),
-- faction = "A"/"H"/nil; flight masters of the other faction are skipped.
G.MAX_POIS = 150
function G.LayoutPois(cx, cy, cont, rot, zoom, half, show, faction)
  local out = {}
  local list = ns.Pois and ns.Pois[cont]
  if not list then return out end
  local s = half / zoom
  local reach = zoom * 1.45
  for _, p in ipairs(list) do
    local kind = p[1]
    if show[kind] and (kind ~= 1 or not faction or string.find(p[6], faction, 1, true)) then
      local dx, dy = Geo.ScreenOffset(cx, cy, p[2], p[3])
      if math.abs(dx) < reach and math.abs(dy) < reach then
        dx, dy = Geo.Rotate(dx * s, dy * s, rot)
        if math.abs(dx) <= half and math.abs(dy) <= half then
          out[#out + 1] = { kind, dx, dy, p[4], p[2], p[3], p[5], p[6], level = kind == 1 and p[7] or nil }
          if #out >= G.MAX_POIS then break end
        end
      end
    end
  end
  return out
end

-- World point under a screen offset (dxUI, dyUI) from the center of a view centered on
-- world (cx, cy) with rotation rot and scale s.
function G.ScreenToWorld(cx, cy, dxUI, dyUI, rot, s)
  local east, north = Geo.Rotate(dxUI / s, dyUI / s, -rot)
  return cx + north, cy - east
end

-- Yards from center to edge that fit a whole uiMap (for world-map browsing).
function G.MapFitZoom(m)
  local b = m.bounds
  return math.max(b[3] - b[1], b[4] - b[2]) / 2 * 1.02
end

-- The zone (child of parentID) containing world (x, y), smallest first.
function G.ZoneAt(x, y, parentID)
  local best, bestArea
  for id, m in pairs(ns.Maps or {}) do
    if m.parent == parentID and m.tiles then
      local b = m.bounds
      if x >= b[1] and x <= b[3] and y >= b[2] and y <= b[4] then
        local area = (b[3] - b[1]) * (b[4] - b[2])
        if not bestArea or area < bestArea then best, bestArea = id, area end
      end
    end
  end
  return best
end

-- The smallest zone/city map on continent `cont` containing world (x, y), with the
-- point's map coordinates (0-1): returns uiMapID, name, mx, my.
function G.LocateWorld(cont, x, y)
  local best, bestArea
  for id, m in pairs(ns.Maps or {}) do
    local b = m.bounds
    if m.type == 3 and m.continent == cont and b and x >= b[1] and x <= b[3] and y >= b[2] and y <= b[4] then
      local area = (b[3] - b[1]) * (b[4] - b[2])
      if not bestArea or area < bestArea then best, bestArea = id, area end
    end
  end
  if not best then return nil end
  local m = ns.Maps[best]
  local b = m.bounds
  return best, m.name, (b[4] - y) / (b[4] - b[2]), (b[3] - x) / (b[3] - b[1])
end

G.MINIMAP_MAX_ZOOM = 3000 -- wider than this, the terrain view shows map art instead of tiles

-- The smallest map with art on continent `cont` that contains (cx, cy) and is at least
-- about as big as a view of `zoom` yards: a zone, else the continent, else the whole
-- world map (drawn in this continent's coordinates). Returns uiMapID, bounds.
function G.CoveringMap(cont, cx, cy, zoom)
  local best, bestArea, bestBounds
  for id, m in pairs(ns.Maps or {}) do
    local b = m.bounds
    if b and m.tiles and m.continent == cont and cx >= b[1] and cx <= b[3] and cy >= b[2] and cy <= b[4]
        and math.max(b[3] - b[1], b[4] - b[2]) / 2 >= zoom * 0.9 then
      local area = (b[3] - b[1]) * (b[4] - b[2])
      if not bestArea or area < bestArea then best, bestArea, bestBounds = id, area, b end
    end
  end
  if best then return best, bestBounds end
  local w = Geo.WorldMap()
  return w, w and Geo.WorldArtBounds(cont)
end

-- The nearest map with art, starting from uiMap `id` and walking up its parents.
function G.DisplayMap(id)
  local m = id and ns.Maps and ns.Maps[id]
  while m and not m.tiles do
    id = m.parent
    m = ns.Maps[id]
  end
  return m and id or nil
end

-- Free view: dragging the map by (dxUI, dyUI) UI units (+y up) from a view
-- centered on world (x0, y0) with rotation rot and scale s (UI units per yard).
-- The map follows the cursor, so the center moves the other way.
function G.PanCenter(x0, y0, dxUI, dyUI, rot, s)
  local east, north = Geo.Rotate(-dxUI / s, -dyUI / s, -rot)
  return x0 + north, y0 - east
end

---------------------------------------------------------------------------
-- Frame
---------------------------------------------------------------------------

local frame, canvas, lineLayer, arrow, northLabel, infoText, noMapText, recenter
local free -- nil while following the player; else the frozen view { x, y, rot }
local approachZoom, approachFor, approachSkip -- near a stop: the zoom now (animated); for which stop; skipped for (G.UpdateApproach)
local view = { x = 0, y = 0, rot = 0, s = 1 } -- last drawn view
local drag -- { cx, cy, x, y, rot, s, moved } while the left button is held on the map
local browse, browseZoom -- world-map browsing: displayed uiMap and its zoom (nil = follow the player's zone)
local browseCont, browseBounds -- continent whose coordinates the browsed map is drawn in; its bounds there
local tour -- Route Here tour: { phase, t0, from = {x, y, zoom}, to = {x, y, zoom} }
local navClosedAt -- Nav.Version() when the route panel was closed with its X
local crossH, crossV, routeBtn, navPanel, navText, stepsText
local pending = {} -- stops double-clicked in free view, not yet confirmed: { x, y, cont, icon }
local lastActivity = 0 -- GetTime() of the last click, drag or zoom on the map
local lastClick -- { t, x, y } of the last plain left click, for double-click detection
local stopPins = {}
local AUTO_CONFIRM = 5 -- seconds without map activity before pending stops start the route
local DOUBLE_CLICK = 0.4 -- seconds
local poiLayer, poiButtons, poiLabels = nil, {}, {}
-- Fading while moving (options): the map's tiles, points of interest, road and quest-area
-- lines, buttons, frame and crosshair fade; the route, the stop markers and the player arrow don't.
local tileLayer, keepLayer, topLayer -- map tiles; stop markers; buttons and text above the map
local fade = 1 -- current share of the map's opacity for the fading parts
local lastMoved = -math.huge -- GetTime() the player was last seen moving
local FADE_SECONDS = 0.4 -- time to fade out or back in
local FADE_HOLD = 1 -- seconds standing still before the map fades back in
local TAXI_ICON = {
  known = "Interface\\TaxiFrame\\UI-Taxi-Icon-Green",
  unlearned = "Interface\\TaxiFrame\\UI-Taxi-Icon-Gray",
  unknown = "Interface\\TaxiFrame\\UI-Taxi-Icon-Yellow",
}
local LABEL_MAX_ZOOM = 1200 -- place names only when zoomed in this far
local ROUTE_COLOR = 3
local pool, poolUsed = {}, 0
local lines, linesUsed = {}, 0
local dashes, dashesUsed = {}, 0 -- textured dotted lines (DASH_TEXTURE)
local ROAD_COLORS = { [0] = { 1, 0.35, 0.1 }, [1] = { 0.1, 0.9, 1 }, [2] = { 0.3, 1, 0.3 }, [3] = { 0.05, 0.28, 0.85 },
  [4] = { 0.25, 0.85, 1 }, [5] = { 0.65, 0.65, 0.7 }, [6] = { 0.45, 0.6, 1 }, [7] = { 0.55, 0.02, 0.02 } } -- 6: quest areas, 7: walls
-- Route segment kinds -> { color, width, dotted }: road, off-road, transport ride, far-side walk.
local ROUTE_STYLE = { [0] = { 3, 5, false }, [1] = { 3, 4, true }, [2] = { 4, 4, true }, [3] = { 5, 3, true } }
local DASH, GAP = 7, 5 -- off-road route legs are dotted (UI units)
-- Dotted legs as one line each, with Media\Dash repeated along it (DASH on, GAP off per
-- 32 pixels of the texture) instead of a line per dash. `/agps debug dashes` switches back
-- to a line per dash (G.dashTexture = false).
local DASH_TEXTURE = "Interface\\AddOns\\AzerothGPS\\Media\\Dash"
G.dashTexture = true
local elapsed = 0

local function S() return ns.settings.gps end

-- The continent the view shows: the browsed map's, a free view's (it may be on another
-- continent, e.g. picked from the world map), else the player's.
local function ViewCont(cont)
  return browse and browseCont or (free and free.cont) or cont
end
local fromTerrain -- world-map browsing started by right-clicking the terrain view

local function Acquire(i)
  local t = pool[i]
  if not t then
    t = tileLayer:CreateTexture(nil, "ARTWORK")
    if t.SetSnapToPixelGrid then t:SetSnapToPixelGrid(false) end
    if t.SetTexelSnappingBias then t:SetTexelSnappingBias(0) end
    pool[i] = t
  end
  return t
end

local function DrawQuads(quads)
  for i, q in ipairs(quads) do
    local t = Acquire(i)
    if t.fid ~= q[1] then
      t:SetTexture(q[1])
      t.fid = q[1]
    end
    t:ClearAllPoints()
    t:SetPoint("CENTER", canvas, "CENTER", q[2], q[3])
    t:SetSize(q[4], q[5])
    t:SetTexCoord(q[7], q[8], q[9], q[10])
    t:SetRotation(q[6] * G.rotSign)
    t:SetDrawLayer("ARTWORK", q[11])
    t:Show()
  end
  for i = #quads + 1, poolUsed do pool[i]:Hide() end
  poolUsed = #quads
end

-- Line records for the current redraw, reused from frame to frame (no garbage):
-- segPool[1..segN] = { x1, y1, x2, y2, color (index or { r, g, b }), thickness, alpha, keep }
-- (keep: part of the route, which doesn't fade while moving).
local segPool, segN = {}, 0
local function AddSeg(ax, ay, bx, by, c, w, a, keep, dotted)
  segN = segN + 1
  local sg = segPool[segN]
  if not sg then
    sg = {}
    segPool[segN] = sg
  end
  sg[1], sg[2], sg[3], sg[4], sg[5], sg[6], sg[7], sg[8], sg[9] = ax, ay, bx, by, c, w, a, keep or false, dotted or false
end

-- Color, thickness and alpha only when they changed (most lines keep theirs frame to frame).
local function Style(l, c, a, w, textured)
  if l.agpsC ~= c or l.agpsA ~= a then
    if textured then l:SetVertexColor(c[1], c[2], c[3], a) else l:SetColorTexture(c[1], c[2], c[3], a) end
    l.agpsC, l.agpsA = c, a
  end
  if l.agpsW ~= w then
    l:SetThickness(w)
    l.agpsW = w
  end
end

-- Draw segPool[1..n].
local function DrawLines(n, thickness, colors, alpha)
  local nl, nd = 0, 0
  for i = 1, n do
    local sg = segPool[i]
    local c = type(sg[5]) == "table" and sg[5] or colors[sg[5]] or colors[0] -- index or { r, g, b }
    local a = (sg[7] or alpha) * (sg[8] and 1 or fade)
    local l
    if sg[9] then
      nd = nd + 1
      l = dashes[nd]
      if not l then
        l = lineLayer:CreateLine(nil, "OVERLAY")
        l:SetTexture(DASH_TEXTURE, "REPEAT", "REPEAT")
        dashes[nd] = l
      end
      Style(l, c, a, sg[6] or thickness, true)
      local len = math.sqrt((sg[3] - sg[1]) ^ 2 + (sg[4] - sg[2]) ^ 2)
      l:SetTexCoord(0, len / (DASH + GAP), 0, 1)
    else
      nl = nl + 1
      l = lines[nl]
      if not l then
        l = lineLayer:CreateLine(nil, "OVERLAY")
        lines[nl] = l
      end
      Style(l, c, a, sg[6] or thickness, false)
    end
    l:SetStartPoint("CENTER", lineLayer, sg[1], sg[2])
    l:SetEndPoint("CENTER", lineLayer, sg[3], sg[4])
    l:Show()
  end
  for i = nl + 1, linesUsed do lines[i]:Hide() end
  for i = nd + 1, dashesUsed do dashes[i]:Hide() end
  linesUsed, dashesUsed = nl, nd
end

-- Quest area outlines: drawn once on their own layer around an anchor point (the view's
-- centre then), which just slides as the view moves: one SetPoint a frame instead of every
-- outline segment. Redrawn when the zoom, rotation, continent or outlines change, every
-- AREA_REFRESH seconds (new quests get traced), or when the view drifts far from the anchor.
local areaLayer, areaLines, areaUsed, areaState = nil, {}, 0, nil
local AREA_REFRESH = 2
local AREA_COLOR = { 0.45, 0.6, 1 } -- the minimap's quest-area blue (as ROAD_COLORS[6])

local function DrawAreas(on, viewCont, cx, cy, zoom, rot, s, half, maps)
  if not on then
    for i = 1, areaUsed do areaLines[i]:Hide() end
    areaUsed, areaState = 0, nil
    return
  end
  local st = areaState
  local mapsKey = tostring(maps[1]) .. ":" .. tostring(maps[2])
  local now = GetTime()
  local stale = not st or st.cont ~= viewCont or st.zoom ~= zoom or math.abs(st.rot - rot) > 0.0005
    or st.version ~= ns.Layers.version or st.maps ~= mapsKey or now - st.t > AREA_REFRESH
    or math.max(math.abs(cx - st.ax), math.abs(cy - st.ay)) * s > half * 0.75
  if stale then
    local t0 = ns.PerfStart and ns.PerfStart()
    st = { cont = viewCont, zoom = zoom, rot = rot, version = ns.Layers.version, maps = mapsKey, t = now, ax = cx, ay = cy }
    areaState = st
    local n = 0
    ns.Layers.EachArea(viewCont, cx, cy, zoom * 2.5, maps, function(x1, y1, x2, y2)
      local dx1, dy1 = Geo.ScreenOffset(cx, cy, x1, y1)
      local dx2, dy2 = Geo.ScreenOffset(cx, cy, x2, y2)
      local ax, ay = Geo.Rotate(dx1 * s, dy1 * s, rot)
      local bx, by = Geo.Rotate(dx2 * s, dy2 * s, rot)
      n = n + 1
      local l = areaLines[n]
      if not l then
        l = areaLayer:CreateLine(nil, "OVERLAY")
        l:SetColorTexture(AREA_COLOR[1], AREA_COLOR[2], AREA_COLOR[3], 0.9)
        l:SetThickness(3)
        areaLines[n] = l
      end
      l:SetStartPoint("CENTER", areaLayer, ax, ay)
      l:SetEndPoint("CENTER", areaLayer, bx, by)
      l:Show()
    end)
    for i = n + 1, areaUsed do areaLines[i]:Hide() end
    areaUsed = n
    if t0 then ns.PerfEnd("quest areas", t0) end
  end
  -- slide the layer: where the anchor is now, relative to the view's centre
  local dx, dy = Geo.ScreenOffset(cx, cy, st.ax, st.ay)
  local ox, oy = Geo.Rotate(dx * s, dy * s, rot)
  areaLayer:ClearAllPoints()
  areaLayer:SetPoint("CENTER", canvas, "CENTER", ox, oy)
end

-- Flight master knowledge for this character: set of known node IDs, and whether any
-- flight map has been seen (otherwise we can't tell known from unlearned).
local function TaxiKnowledge()
  local known, seen = {}, false
  local cdb = ns.CharDB()
  for _, entry in pairs(cdb.taxiNodes or {}) do
    for _, n in ipairs(entry.nodes or {}) do
      if n.state ~= nil then seen = true end
      if n.known then known[n.nodeID] = true end
    end
  end
  return known, seen
end

local function PoiButton(i)
  local b = poiButtons[i]
  if b then return b end
  b = CreateFrame("Button", nil, poiLayer)
  b:SetSize(16, 16)
  if G.clickThrough then b.agpsMouse, b.agpsWheel = true, false; b:EnableMouse(false) end
  b.icon = b:CreateTexture(nil, "ARTWORK")
  b.icon:SetAllPoints()
  b:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(self.name, 1, 1, 1)
    if self.questID and ns.Layers then
      GameTooltip:ClearLines()
      ns.Layers.AddQuestToTooltip(GameTooltip, self.questID)
    end
    if self.note then GameTooltip:AddLine(self.note, 0.7, 0.7, 0.7) end
    if self.preview then
      GameTooltip:AddLine("Ask a guard for directions to go there", 0.4, 0.8, 1)
    else
      GameTooltip:AddLine("Double-click: add as a stop", 0.4, 0.8, 1)
    end
    GameTooltip:Show()
  end)
  b:SetScript("OnLeave", GameTooltip_Hide)
  b:SetScript("OnClick", function(self)
    if self.cityMap then G.ShowCity(self.cityMap) end -- (a capital on a continent's map)
  end)
  b:SetScript("OnDoubleClick", function(self)
    if self.cityMap then return end
    if self.preview then return end -- (a city place a guard hasn't pointed out: ask one)
    G.AddStopAt(self.wx, self.wy, self.name, self.level, self.stopTex) -- like a double-click on the map, with its name and icon
  end)
  poiButtons[i] = b
  return b
end

local function DrawPois(pois, zoom)
  local known, seen = TaxiKnowledge()
  local nb, nl = 0, 0
  for _, p in ipairs(pois) do
    if p[1] == 3 then
      if zoom <= LABEL_MAX_ZOOM then
        nl = nl + 1
        local fs = poiLabels[nl]
        if not fs then
          fs = poiLayer:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
          fs:SetTextColor(1, 0.95, 0.8)
          fs:SetShadowOffset(1, -1)
          poiLabels[nl] = fs
        end
        fs:SetText(p[4])
        fs:ClearAllPoints()
        fs:SetPoint("CENTER", poiLayer, "CENTER", p[2], p[3])
        fs:Show()
      end
    else
      nb = nb + 1
      local b = PoiButton(nb)
      b.name, b.wx, b.wy = p[4], p[5], p[6]
      b.level = p.level -- (a flight master down in a city: its stop is on the city's level)
      b.preview, b.cityMap = nil, nil
      if p[1] == 5 then -- a capital on a continent's map: click for the city
        ns.SetIcon(b.icon, "atlas:poi-majorcity", "Interface\\Icons\\INV_Misc_Map02")
        b.icon:SetVertexColor(1, 1, 1)
        b.stopTex, b.questID = nil, nil
        b.note = "Click: show the city"
        b.cityMap = p.cityMap
        b:SetSize(20, 20)
      elseif p[1] == 1 then
        local state = not seen and "unknown" or (known[p[7]] and "known" or "unlearned")
        ns.SetIcon(b.icon, TAXI_ICON[state])
        b.stopTex = TAXI_ICON[state]
        b.note = state == "known" and "Flight master (known)" or state == "unlearned" and "Flight master (not learned)"
          or "Flight master (open a flight map once to see which you know)"
        b:SetSize(16, 16)
      elseif p[1] == 4 then -- map layer mark (Layers.lua)
        ns.SetIcon(b.icon, p.icon, ns.Layers and ns.Layers.ICON.objectiveFallback)
        b.icon:SetVertexColor(p.r or 1, p.g or 1, p.b or 1)
        -- its icon for a stop made from it (a file; atlas art can't show in text)
        b.stopTex = type(p.icon) == "string" and not p.icon:find("^atlas:") and p.icon or nil
        b.note = p.note
        b.questID = p.questID
        b.preview = p.preview
        b:SetSize(p.size or 14, p.size or 14)
      else
        ns.SetIcon(b.icon, "Interface\\Common\\Indicator-Yellow")
        b.stopTex = nil
        b.note = nil
        b:SetSize(12, 12)
      end
      if p[1] ~= 4 then
        b.icon:SetVertexColor(1, 1, 1)
        b.questID = nil
      end
      b:ClearAllPoints()
      b:SetPoint("CENTER", poiLayer, "CENTER", p[2], p[3])
      b:Show()
    end
  end
  for i = nb + 1, #poiButtons do poiButtons[i]:Hide() end
  for i = nl + 1, #poiLabels do poiLabels[i]:Hide() end
end

-- Marker buttons for the route's stops and the pending (not yet confirmed) ones.
local function StopPin(i)
  local b = stopPins[i]
  if b then return b end
  b = CreateFrame("Button", nil, keepLayer)
  b:SetSize(18, 18)
  b:SetFrameLevel(keepLayer:GetFrameLevel() + 2)
  b.icon = b:CreateTexture(nil, "OVERLAY")
  b.icon:SetAllPoints()
  b:RegisterForClicks("RightButtonUp")
  b:SetScript("OnClick", function(self) G.AskRemove(self) end)
  b:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(self.title, 1, 1, 1)
    GameTooltip:AddLine("Right-click: remove this stop", 0.7, 0.7, 0.7)
    GameTooltip:Show()
  end)
  b:SetScript("OnLeave", GameTooltip_Hide)
  stopPins[i] = b
  return b
end

-- Draw the pins: route stops (solid) and pending stops (lighter, removable).
local function DrawStopPins(toScreen, viewCont)
  local n = 0
  local function pin(d, title, pendingIndex, stopIndex)
    local x, y = Geo.ToContinent(d.cont, d.x, d.y, viewCont)
    if not x then return end
    local sx, sy = toScreen(x, y)
    n = n + 1
    local b = StopPin(n)
    b.icon:SetTexture(ns.Nav.StopIcon(d))
    b.icon:SetAlpha(pendingIndex and 0.75 or 1)
    b.title, b.pendingIndex, b.stopIndex = title, pendingIndex, stopIndex
    if G.clickThrough then
      b.agpsMouse = true -- restored when click-through ends
      b:EnableMouse(false)
    else
      b:EnableMouse(true)
    end
    b:ClearAllPoints()
    b:SetPoint("BOTTOM", poiLayer, "CENTER", sx, sy - 4)
    b:Show()
  end
  -- the stops routed ahead (a long list: the rest show up as they come next)
  local stops = ns.Nav.stops
  for i = 1, ns.Nav.PlannedStops() do
    local d = stops[i]
    pin(d, d.name or (#stops > 1 and ("Stop " .. i) or "Destination"), nil, i)
  end
  for i, d in ipairs(pending) do
    pin(d, "New stop " .. i .. " (not confirmed yet)", i)
  end
  for i = n + 1, #stopPins do stopPins[i]:Hide() end
end

function G.Update()
  local st = S()
  local px, py, cont, pz = Geo.PlayerWorld()
  if not px then
    DrawQuads({})
    DrawLines(0, 1, ROAD_COLORS, 1)
    noMapText:SetText("No map here")
    noMapText:Show()
    arrow:Hide()
    northLabel:Hide()
    infoText:SetText("")
    return
  end
  noMapText:Hide()
  arrow:Show()
  local pt = ns.PerfStart() -- the parts' timings (/agps debug perf)
  local facing = Geo.Facing()
  local half = canvas:GetWidth() / 2
  -- Following: centered on the player, turning with them in heading-up mode.
  -- Free view: wherever the user dragged, rotation frozen at the start of the drag.
  local cx, cy, rot = px, py, st.rotate and -facing or 0
  if free then cx, cy, rot = free.x, free.y, free.rot end
  local zoom = browseZoom or approachZoom or st.zoom
  local s = half / zoom
  view.x, view.y, view.rot, view.s = cx, cy, rot, s
  -- The continent whose coordinates this view uses (browsing may show the other one).
  local viewCont = ViewCont(cont)
  local here = viewCont == cont
  local quads
  -- Indoors inside a known building: show its interior map, like the game minimap.
  local place, wmo, room
  -- Interiors belong to the terrain view (like the game minimap), and only while zoomed in:
  -- the world map style shows the city's world map, and zooming out shows the outside.
  -- (the player's own inside map only while the view is on them: not a city opened from its
  -- icon, nor looking somewhere else)
  local onMe = not free or (not free.interior and (free.x - px) ^ 2 + (free.y - py) ^ 2 <= (zoom * 1.5) ^ 2)
  if st.interiors and not G.IsMapStyle(st.style) and not browse and here and onMe and zoom <= G.INTERIOR_MAX_ZOOM then
    local lvl = ns.Nav.PlayerLevel(cont)
    local city = ns.CityLevels and ns.CityLevels[lvl]
    local cityZ = city and ns.Nav.CityHeight(lvl, px, py)
    place, wmo, room = G.FindInterior(px, py, pz, cont, GetMinimapZoneText and GetMinimapZoneText(), IsIndoors(),
      cityZ, city and city.wmo)
    -- an underground city's model while up top (the Ruins of Lordaeron): its art there is
    -- mostly black, so the outside map until down in the city
    if place and not city then
      for _, l in pairs(ns.CityLevels or {}) do
        if l.wmo == place[1] then place, wmo, room = nil, nil, nil break end
      end
    end
  end
  -- a city inside a mountain (Ironforge) opened from its icon: its interior map while looking there
  if not place and free and free.interior and not browse and not G.IsMapStyle(st.style) and zoom <= G.INTERIOR_MAX_ZOOM then
    place, wmo, room = free.interior[1], free.interior[2], free.interior[3]
  end
  G.inside = place and ((room.n ~= "" and room.n or "?") .. " / " .. place[1]) or nil
  if place and not browse then
    quads = G.LayoutInterior(cx, cy, place, wmo, room, rot, zoom, half)
  elseif browse then
    quads = G.LayoutZone(cx, cy, browse, rot, zoom, half, browseBounds, st.style == "nospoiler")
  elseif G.IsMapStyle(st.style) or zoom > G.MINIMAP_MAX_ZOOM then
    -- The player's zone map, or a bigger map (continent, world) when zoomed out past it.
    -- (the view moved off somewhere else: the zone there, not the player's)
    local id = free and G.LocateWorld(Geo.Base(viewCont), cx, cy)
    if not id then id = here and G.DisplayMap(C_Map.GetBestMapForUnit("player")) or nil end
    local m = id and ns.Maps[id]
    local bounds = m and m.bounds
    if not bounds or math.max(bounds[3] - bounds[1], bounds[4] - bounds[2]) / 2 < zoom * 0.9 then
      id, bounds = G.CoveringMap(viewCont, cx, cy, zoom)
    end
    quads = G.LayoutZone(cx, cy, id, rot, zoom, half, bounds, st.style == "nospoiler")
  else
    quads = G.LayoutMinimap(cx, cy, viewCont, rot, zoom, half)
  end
  DrawQuads(quads)
  ns.PerfEnd("redraw: tiles", pt)
  pt = ns.PerfStart()
  segN = 0
  -- (the roads of the continent in view, the player's or another)
  if st.showRoads and not place then
    for _, sg in ipairs(G.LayoutRoads(cx, cy, here and cont or viewCont, rot, zoom, half)) do AddSeg(sg[1], sg[2], sg[3], sg[4], sg[5]) end
  end
  -- walls (blood red): with the roads shown, or the road tools on
  if st.showWalls or G.wallMode then -- (inside maps too: a city's own floors and walls)
    local wc = (here and onMe) and ns.Nav.PlayerLevel(cont) or viewCont -- (the level shown: the player's only while the view is on them)
    -- (the terrain's impassable borders thinner, drawn walls thicker)
    for _, sg in ipairs(G.LayoutWalls(cx, cy, wc, rot, zoom, half, true)) do AddSeg(sg[1], sg[2], sg[3], sg[4], 7, sg.edge and 2 or 3) end
  end
  -- Quest objective areas (Layers.lua), outlined in the minimap's blue, on their own layer.
  local layerMaps = { C_Map.GetBestMapForUnit("player"), browse }
  DrawAreas(ns.Layers and st.layerQuests and st.layerQuestAreas and not place, viewCont, cx, cy, zoom, rot, s, half, layerMaps)
  ns.PerfEnd("redraw: roads and quest areas", pt)
  pt = ns.PerfStart()
  -- Route: solid along roads, dotted for the legs to and from the road; destination pin.
  ns.Nav.Tick()
  local dest = ns.Nav.dest
  local route = ns.Nav.Route(px, py, cont)
  if route then
    -- Every part of the route, converted into this view's continent coordinates.
    local reach = half * 1.5
    local function toScreen(x, y)
      local dx, dy = Geo.ScreenOffset(cx, cy, x, y)
      return Geo.Rotate(dx * s, dy * s, rot)
    end
    -- Several stops: each leg in the color of its stop's marker (off-road and rides a
    -- darker shade of it); a single destination keeps the usual blues.
    local stops = ns.Nav.stops
    local multi = #stops > 1
    local shades = {}
    local function color(stop, kind, base)
      local d = stops[stop]
      if d and d.corpse then -- the way back to your body: red
        local c, k = ns.Nav.CORPSE_COLOR, kind == 0 and 1 or 0.75
        shades.corpse = shades.corpse or {}
        shades.corpse[k] = shades.corpse[k] or { c[1] * k, c[2] * k, c[3] * k }
        return shades.corpse[k]
      end
      if not multi then return base end
      local c = d and ns.Nav.MARKER_COLORS[d.icon or 1]
      if not c then return base end
      local k = kind == 0 and 1 or 0.7
      local key = (d.icon or 1) * 10 + (kind == 0 and 0 or 1)
      shades[key] = shades[key] or { c[1] * k, c[2] * k, c[3] * k }
      return shades[key]
    end
    local questing = ns.Nav.QuestPaused()
    -- (the level shown: the player's, or a city's opened from its icon; the route's stretches
    -- on another level (down in a city while up top, or back up) are drawn faint and dotted,
    -- not as if across what's shown)
    local shown = here and ns.Nav.PlayerLevel(cont) or viewCont
    if free and free.interior then
      for lc, l in pairs(ns.CityLevels or {}) do
        if l.wmo == free.interior[1][1] then shown = lc end
      end
    end
    ns.Nav.EachSegment(route, viewCont, function(x1, y1, x2, y2, kind, stop, partCont)
      if questing and stop == 1 then return end -- in the stop's quest area, spot reached: no way there
      local ax, ay = toScreen(x1, y1)
      local bx, by = toScreen(x2, y2)
      -- nowhere near the view: skip (no dashes, no line objects, no garbage)
      if (ax > reach and bx > reach) or (ax < -reach and bx < -reach) or (ay > reach and by > reach)
          or (ay < -reach and by < -reach) then return end
      local style = ROUTE_STYLE[kind] or ROUTE_STYLE[1]
      local col = color(stop, kind, style[1])
      if partCont and partCont ~= shown and (ns.CityLevels and (ns.CityLevels[partCont] or ns.CityLevels[shown])) then
        AddSeg(ax, ay, bx, by, col, math.max(2, style[2] - 2), 0.45, true, true) -- (another level)
      elseif not style[3] then
        AddSeg(ax, ay, bx, by, col, style[2], 1, true)
      elseif G.dashTexture then
        AddSeg(ax, ay, bx, by, col, style[2], 1, true, true)
      else
        local vx, vy = bx - ax, by - ay
        local len = math.sqrt(vx * vx + vy * vy)
        local t, n = 0, 0
        while t < len and n < 400 do
          local t2 = math.min(t + DASH, len)
          AddSeg(ax + vx * t / len, ay + vy * t / len, ax + vx * t2 / len, ay + vy * t2 / len, col, style[2], 1, true)
          t, n = t2 + GAP, n + 1
        end
      end
    end)
  end
  DrawStopPins(function(x, y)
    local dx, dy = Geo.ScreenOffset(cx, cy, x, y)
    return Geo.Rotate(dx * s, dy * s, rot)
  end, viewCont)
  -- a farming area being drawn: its outline so far
  local lasso = G.lasso
  if lasso and lasso.cont == viewCont then
    local pts, lx, ly = lasso.pts, nil, nil
    for i = 1, #pts - 1, 2 do
      local dx, dy = Geo.ScreenOffset(cx, cy, pts[i], pts[i + 1])
      local ax, ay = Geo.Rotate(dx * s, dy * s, rot)
      if lx then AddSeg(lx, ly, ax, ay, lasso.color or LASSO_COLOR, lasso.color and 3 or 2, 1, true) end
      lx, ly = ax, ay
    end
  end
  DrawLines(segN, 3, ROAD_COLORS, 0.85)
  ns.PerfEnd("redraw: route (incl. calculation)", pt)
  pt = ns.PerfStart()
  local worldView = browse and ns.Maps[browse] and ns.Maps[browse].type <= 1
  -- Map layers: quests, gathering nodes, city locations (Layers.lua), outside and inside
  local function AddMarks(pois)
    if not ns.Layers then return end
    -- (a city's own places show on its level: the player's, or the city opened from its icon)
    local level = here and ns.Nav.PlayerLevel(cont) or nil
    if free and free.interior then
      for lc, l in pairs(ns.CityLevels or {}) do
        if l.wmo == free.interior[1][1] then level = lc end
      end
    end
    for _, m in ipairs(ns.Layers.Marks(viewCont, cx, cy, zoom * 1.45, layerMaps, level)) do
      local dx, dy = Geo.ScreenOffset(cx, cy, m[1], m[2])
      dx, dy = Geo.Rotate(dx * s, dy * s, rot)
      if math.abs(dx) <= half and math.abs(dy) <= half then
        pois[#pois + 1] = { 4, dx, dy, m[4], m[1], m[2], nil, nil, icon = m[3], note = m[5], size = m[6], questID = m[10],
          r = m[7], g = m[8], b = m[9], preview = m[11] }
      end
    end
  end
  -- a stop made from a map icon (a trainer, a flight master) shows that icon: the map's
  -- own one under it isn't drawn as well
  local function DropUnderStops(pois)
    local under = {}
    for _, list in ipairs({ ns.Nav.stops, pending }) do
      for _, d in ipairs(list) do
        if d.tex then
          local x, y = Geo.ToContinent(d.cont, d.x, d.y, viewCont)
          if x then under[#under + 1] = { x, y } end
        end
      end
    end
    if not under[1] then return pois end
    local out = {}
    for _, p in ipairs(pois) do
      local drop = false
      if p[1] ~= 3 and p[5] then
        for _, u in ipairs(under) do
          if (u[1] - p[5]) ^ 2 + (u[2] - p[6]) ^ 2 <= 9 then drop = true break end
        end
      end
      if not drop then out[#out + 1] = p end
    end
    return out
  end
  if (not place or browse) and not worldView then
    local fac = ns.CharDB().faction
    fac = fac == "Horde" and "H" or fac == "Alliance" and "A" or nil
    -- (a continent's map: none of the points of interest, only once in a zone)
    local bm = browse and ns.Maps[browse]
    local pois = {}
    if not (bm and bm.type == 2) then
      pois = G.LayoutPois(cx, cy, viewCont, rot, zoom, half, { st.poiTaxi, st.poiPoi, st.poiLabels }, fac)
      AddMarks(pois)
    end
    -- a continent's map: its capitals, to click for the city
    if bm and bm.type == 2 then
      for id, m in pairs(ns.Maps) do
        if m.zoneParent and m.continent == bm.continent and m.bounds then
          local x, y = (m.bounds[1] + m.bounds[3]) / 2, (m.bounds[2] + m.bounds[4]) / 2
          local dx, dy = Geo.ScreenOffset(cx, cy, x, y)
          dx, dy = Geo.Rotate(dx * s, dy * s, rot)
          if math.abs(dx) <= half and math.abs(dy) <= half then
            pois[#pois + 1] = { 5, dx, dy, m.name, x, y, cityMap = id }
          end
        end
      end
    end
    DrawPois(DropUnderStops(pois), zoom)
  elseif place and not browse then
    -- inside a building's map (a city like Undercity): its districts' names, like the
    -- world map's, and the quests and city locations
    local pois = {}
    if st.poiLabels ~= false then
      for _, l in ipairs(G.InteriorLabels(place, wmo, room)) do
        local dx, dy = Geo.ScreenOffset(cx, cy, l[1], l[2])
        dx, dy = Geo.Rotate(dx * s, dy * s, rot)
        if math.abs(dx) <= half and math.abs(dy) <= half then
          pois[#pois + 1] = { 3, dx, dy, l[3], l[1], l[2] }
        end
      end
    end
    AddMarks(pois)
    DrawPois(DropUnderStops(pois), zoom)
  else
    DrawPois({}, zoom)
  end
  ns.PerfEnd("redraw: icons", pt)
  pt = ns.PerfStart()
  local status = ns.Nav.Status(px, py, cont)
  local steps = status and ns.Nav.StepsText(st.stepsAll and 99 or 3) or ""
  -- a walk with no other legs: its next turn and the one after (as the arrow shows them)
  if status and steps == "" and route and not route.flying and ns.Turns and not ns.Nav.questing then
    -- (worked out twice a second, not every redraw)
    local now = GetTime()
    if route ~= G.turnRoute or now - (G.turnAt or 0) > 0.5 then
      G.turnRoute, G.turnAt = route, now
      local ok, ms = pcall(function() return ns.Turns.Maneuvers(ns.Turns.Path(route), dest and dest.name or "the stop") end)
      G.turnMs = ok and ms or nil
    end
    local ms = G.turnMs
    local ok = ms ~= nil
    local m = ok and ms and ms[1]
    if m then
      steps = string.format("|cffffffff%s  %s|r", m.text, ns.Nav.FormatDistance(m.dist))
      local nxt = ms[2]
      if nxt then
        steps = steps .. string.format("\n|cffb0b0b0Then: %s in %s|r", nxt.text, ns.Nav.FormatDistance(nxt.dist - m.dist))
      end
    end
  end
  -- collapsed (the -/+ button, with steps to list): only the "All stops" / times line
  local collapsed = steps ~= "" and st.stepsCollapsed
  navText:SetText(collapsed and G.CollapsedStatus(status) or status or "")
  if collapsed then steps = "" end
  stepsText:SetText(steps)
  stepsText:SetShown(steps ~= "")
  G.stepsToggle:SetShown(status ~= nil and (steps ~= "" or collapsed))
  G.stepsToggle.label:SetText(collapsed and "+" or "-")
  -- "+" for all of them: when there are more than the few shown
  G.stepsMore:SetShown(status ~= nil and not collapsed and not st.stepsAll and #ns.Nav.Steps() > 3)
  navPanel:SetHeight(navText:GetStringHeight() + 12 + (steps ~= "" and stepsText:GetStringHeight() + 4 or 0))
  -- closed with its X: hidden until the route changes (unless the X clears the route)
  navPanel:SetShown(status ~= nil and navClosedAt ~= ns.Nav.Version())
  ns.PerfEnd("redraw: text", pt)
  -- Once the player starts moving after choosing a destination, follow them again --
  -- but not during the Route Here tour: only dragging or zooming cancels that, and it
  -- ends by zooming in on the player anyway.
  if dest and free and not browse and dest.watchX and not tour then
    local mx, my = px - dest.watchX, py - dest.watchY
    if mx * mx + my * my > 4 then
      dest.watchX = nil
      G.Follow()
    end
  end
  -- Free look: crosshair and "Route Here" at the view center.
  local showCross = free ~= nil and free.cross and not (browse and ns.Maps[browse] and ns.Maps[browse].type <= 2)
  crossH:SetShown(showCross)
  crossV:SetShown(showCross)
  routeBtn:SetShown(showCross or #pending > 0)
  -- with a route set: Clear Route (double-clicks add stops to it directly)
  routeBtn:SetText(#ns.Nav.stops > 0 and "Clear Route"
    or (#pending > 0 and ("Confirm Route (" .. #pending .. ")") or "Confirm Route"))
  if G.mapMenu and G.mapMenu:IsShown() then G.RefreshMapMenu() end

  -- Arrow at the player's real position; it points where they face on this map
  -- (always up while following in heading-up mode).
  local ax, ay = Geo.ScreenOffset(cx, cy, px, py)
  ax, ay = Geo.Rotate(ax * s, ay * s, rot)
  arrow:SetShown(here)
  arrow:ClearAllPoints()
  arrow:SetPoint("CENTER", lineLayer, "CENTER", ax, ay)
  arrow:SetRotation(facing + rot)
  -- North marker orbits the edge in heading-up mode.
  local nx, ny = Geo.Rotate(0, half - 12, rot)
  northLabel:ClearAllPoints()
  northLabel:SetPoint("CENTER", canvas, "CENTER", nx, ny)
  northLabel:Show()

  view.cont = viewCont
  G.UpdateInfo()
end

-- The coordinates line (bottom): the spot under the mouse pointer while it's over the map,
-- else the crosshair while panning, else the player. Runs ~10 times a second on its own
-- (the map redraw is skipped when nothing moves, the pointer may still).
function G.UpdateInfo()
  if not infoText then return end
  local over = canvas:IsMouseOver() and not drag
  local x, y, mark
  if over then
    local mx, my = GetCursorPosition()
    local sc = canvas:GetEffectiveScale()
    local ccx, ccy = canvas:GetCenter()
    x, y = G.ScreenToWorld(view.x, view.y, mx / sc - ccx, my / sc - ccy, view.rot, view.s)
    mark = "|cff80c0ff>|r "
  elseif free and free.cross then
    x, y, mark = view.x, view.y, "|cffffd100+|r "
  end
  if x and view.cont then
    local _, name, u, v = G.LocateWorld(view.cont, x, y)
    if name then
      infoText:SetFormattedText("%s%s  %.1f, %.1f", mark, name, u * 100, v * 100)
    else
      infoText:SetText(mark)
    end
    return
  end
  local mapID = C_Map.GetBestMapForUnit("player")
  local info = mapID and C_Map.GetMapInfo(mapID)
  local pos = mapID and C_Map.GetPlayerMapPosition(mapID, "player")
  if info and pos then
    local px, py = pos:GetXY()
    infoText:SetFormattedText("%s  %.1f, %.1f", info.name, px * 100, py * 100)
  else
    infoText:SetText(info and info.name or "")
  end
end

function G.Describe()
  if not frame then return "not created" end
  local st = S()
  return string.format("shown=%s style=%s rotate=%s zoom=%d size=%d alpha=%.2f roads=%s interior=%s quads=%d lines=%d",
    tostring(frame:IsShown()), st.style, tostring(st.rotate), st.zoom, st.size, st.alpha,
    tostring(st.showRoads), tostring(G.inside), poolUsed, linesUsed) .. (G.lastError and ("\nlast error: " .. G.lastError) or "")
end

local function SavePosition()
  local p, rel, rp, x, y = frame:GetPoint(1)
  S().point = { p, rel and rel:GetName() or "UIParent", rp, x, y }
end

function G.ApplySettings()
  local st = S()
  -- the window frame (option, locked or not); without it, an unlocked map has the Move tab
  local framed = G.chrome ~= nil and st.windowFrame ~= false
  if G.chrome then
    G.chrome:SetShown(framed)
    -- the portrait hangs over the map's top-left corner: the top panel starts right of it
    navPanel:SetPoint("TOPLEFT", framed and CHROME_PORTRAIT_INSET or 4, -4)
  end
  if G.moveTab then G.moveTab:SetShown(not st.locked and not framed) end
  frame:SetSize(st.size, st.size)
  local hidden = ns.inCombat and st.combatHideMap
  frame:SetAlpha(ns.inCombat and (st.combatAlpha or st.alpha) or st.alpha)
  if G.RefreshHearthButton then G.RefreshHearthButton() end -- the option may have changed
  frame:ClearAllPoints()
  local p = st.point
  frame:SetPoint(p[1], _G[p[2]] or UIParent, p[3], p[4], p[5])
  frame:SetMovable(not st.locked)
  frame:SetShown(st.shown and not hidden)
  elapsed = 1 -- redraw now
end

-- Fading while moving: the share of the map's opacity the fading parts should have now.
function G.FadeTarget(st, moving, mouseOver, baseAlpha)
  if not st.fadeMoving or mouseOver or not moving then return 1 end
  if not baseAlpha or baseAlpha <= 0 then return 1 end
  return math.min(1, (st.movingAlpha or 0.4) / baseAlpha)
end

local function ApplyFade()
  if not frame then return end
  tileLayer:SetAlpha(fade)
  areaLayer:SetAlpha(fade)
  poiLayer:SetAlpha(fade)
  topLayer:SetAlpha(fade)
  frame:SetBackdropColor(0.05, 0.05, 0.05, fade)
  frame:SetBackdropBorderColor(0.15, 0.15, 0.15, fade)
  if G.chrome then G.chrome:SetAlpha(fade) end
  -- the crosshair (shown while looking around, not following the player) fades too
  crossH:SetAlpha(fade)
  crossV:SetAlpha(fade)
end

local function PlayerMoving()
  if IsPlayerMoving then
    local ok, m = pcall(IsPlayerMoving)
    if ok and not ns.IsSecret(m) then return m and true or false end
  end
  local ok, speed = pcall(GetUnitSpeed, "player")
  return ok and not ns.IsSecret(speed) and speed and speed > 0 or false
end

-- Every frame: fade out while the player moves, back in a moment after they stop (or
-- right away while the mouse is over the map, to use it).
G.PlayerMoving = PlayerMoving

-- Click-through (options, Opacity page): while moving and/or in combat the map ignores the
-- mouse, so clicks go to the game world (targeting, turning the camera) instead.
G.clickThrough = false
local CLICK_HOLD = 0.3 -- seconds after stopping before the map takes clicks again

function G.ClickThroughWanted(st, moving, inCombat)
  return (st.clickThroughMoving and moving) or (st.clickThroughCombat and inCombat) and true or false
end

-- Every frame of the map (and the frames in it): stop taking the mouse, or go back to how
-- it was (remembered per frame).
local function SetMouse(f, takeMouse)
  if takeMouse then
    if f.agpsMouse ~= nil then f:EnableMouse(f.agpsMouse) end
    if f.agpsWheel ~= nil and f.EnableMouseWheel then f:EnableMouseWheel(f.agpsWheel) end
    f.agpsMouse, f.agpsWheel = nil, nil
  else
    if f.agpsMouse == nil and f.IsMouseEnabled then f.agpsMouse = f:IsMouseEnabled() end
    if f.agpsWheel == nil and f.IsMouseWheelEnabled then f.agpsWheel = f:IsMouseWheelEnabled() end
    if f.EnableMouse then f:EnableMouse(false) end
    if f.EnableMouseWheel then f:EnableMouseWheel(false) end
  end
  for _, c in ipairs({ f:GetChildren() }) do SetMouse(c, takeMouse) end
end

function G.UpdateFade(dt)
  local now = GetTime()
  if PlayerMoving() then lastMoved = now end
  local through = G.ClickThroughWanted(S(), now - lastMoved < CLICK_HOLD, ns.inCombat)
  if through ~= G.clickThrough then
    G.clickThrough = through
    if through and drag then
      drag = nil
      frame:StopMovingOrSizing()
    end
    SetMouse(frame, not through)
  end
  local target = G.FadeTarget(S(), now - lastMoved < FADE_HOLD, canvas:IsMouseOver(), frame:GetAlpha())
  if fade == target then return end
  local step = dt / FADE_SECONDS
  if fade < target then fade = math.min(target, fade + step) else fade = math.max(target, fade - step) end
  ApplyFade()
  elapsed = 1 -- redraw the lines at the new opacity
end

-- The nav panel's text when the steps are collapsed: just its last line (the whole trip's
-- walking and mounted times, "All stops: ..." or "Next 8 stops: ..."; "Arrived" and the
-- like stay as they are).
function G.CollapsedStatus(status)
  if not status then return "" end
  return status:match("\n([^\n]*)$") or status
end

-- Leave free view and follow the player again.
function G.Follow()
  G.appended = false
  fromTerrain = nil
  tour = nil
  free = nil
  pending = {}
  browse, browseZoom, browseCont, browseBounds = nil, nil, nil, nil
  if recenter then recenter:Hide() end
  elapsed = 1
end

-- From browsing a map (a world map style) to the terrain view: over the same spot, about
-- as zoomed, not back on the player.
function G.BrowseToTerrain()
  if not browse then return end
  local x, y, c, z = view.x, view.y, browseCont, browseZoom
  browse, browseZoom, browseCont, browseBounds, fromTerrain = nil, nil, nil, nil, nil
  free = { x = x, y = y, rot = 0, cross = true, cont = c }
  if z then S().zoom = math.max(MIN_ZOOM, math.min(MAX_ZOOM, z)) end
  if recenter then recenter:Show() end
  elapsed = 1
end

-- World-map browsing (zone style): show uiMap `id` whole, north-up, in free view.
-- `cont` picks the continent whose coordinates the world map is drawn in.
function G.Browse(id, cont)
  local m = ns.Maps[id]
  if not m then return end
  local b, c = m.bounds, m.continent
  if not b and m.worldFrames then
    local _, _, pc = Geo.PlayerWorld()
    c = cont or browseCont or pc or 0
    b = Geo.WorldArtBounds(c)
  end
  if not b then return end
  browse, browseCont, browseBounds = id, c, b
  browseZoom = math.max(b[3] - b[1], b[4] - b[2]) / 2 * 1.02
  free = { x = (b[1] + b[3]) / 2, y = (b[2] + b[4]) / 2, rot = 0, cross = true }
  recenter:Show()
  elapsed = 1
end

-- One level up from uiMap `id`: a capital city goes to the zone around it (zoneParent,
-- e.g. Undercity -> Tirisfal Glades), a zone to its continent, a continent to the world.
function G.UpMap(id)
  local m = ns.Maps[id]
  if not m then return nil end
  if m.zoneParent and ns.Maps[m.zoneParent] then return m.zoneParent end
  local parent = ns.Maps[m.parent]
  return parent and parent.tiles and m.parent or nil
end

-- Right-click in world-map style: up one level.
function G.ZoomOut()
  local current = browse or G.DisplayMap(C_Map.GetBestMapForUnit("player"))
  if not current or not ns.Maps[current] then return end
  if not browse then
    G.Browse(current) -- first right-click: the whole zone
  else
    local up = G.UpMap(current)
    if up then G.Browse(up, browseCont) end
  end
end

-- Left-click (no drag) on the map: open the zone (on a continent) or the continent (on
-- the world map) under the cursor.
local function OnMapClick(dxUI, dyUI)
  local m = browse and ns.Maps[browse]
  if not m or (m.type > 2 and not fromTerrain) then return end -- (a zone from the terrain view: a spot on it)
  local x, y = G.ScreenToWorld(view.x, view.y, dxUI, dyUI, view.rot, view.s)
  if m.worldFrames then
    local b = browseBounds
    local u, v = (b[4] - y) / (b[4] - b[2]), (b[3] - x) / (b[3] - b[1])
    for c, wf in pairs(m.worldFrames) do
      if u >= wf[5] and u <= wf[7] and v >= wf[6] and v <= wf[8] then
        for id, o in pairs(ns.Maps) do
          if o.type == 2 and o.continent == c and o.parent == browse then
            G.Browse(id) -- the continent (from the terrain view: then a spot on it)
            return
          end
        end
      end
    end
    return
  end
  if fromTerrain then
    -- picked a spot: back to the terrain view, centered there (free view, crosshair)
    local c = browseCont
    browse, browseZoom, browseCont, browseBounds, fromTerrain = nil, nil, nil, nil, nil
    free = { x = x, y = y, rot = 0, cross = true, cont = c }
    recenter:Show()
    elapsed = 1
    return
  end
  local zone = G.ZoneAt(x, y, browse)
  if zone then G.Browse(zone) end
end

-- Right-click in the terrain view: the world map (Azeroth) to pick a continent, then a spot
-- on it to come back to the terrain view there. Right-click again goes back up / home.
-- (The continent first, then the world map with both; left-clicks come back down: the
-- world map to a continent, a spot on the continent to the terrain view there.)
local function WorldMapID()
  for id, o in pairs(ns.Maps or {}) do
    if o.worldFrames then return id end
  end
end
-- A continent's map: the world map's child (with the zones), not the small overview some
-- continents also have (no parent, one 512 texture).
function G.ContinentMap(c)
  local best, bestKey
  for id, o in pairs(ns.Maps or {}) do
    if o.type == 2 and o.continent == c and o.bounds then
      local key = ((o.parent or 0) ~= 0 and 1e6 or 0) + (o.artW or 0)
      if not bestKey or key > bestKey or (key == bestKey and id < best) then best, bestKey = id, key end
    end
  end
  return best
end

function G.TerrainZoomOut()
  local m = browse and ns.Maps[browse]
  local _, _, cont = Geo.PlayerWorld()
  if not browse then
    fromTerrain = true
    local c = Geo.Base(ViewCont(cont))
    local id = G.ContinentMap(c)
    if id then
      G.Browse(id, c) -- this continent's map
      return
    end
    local w = WorldMapID()
    if w then G.Browse(w, ViewCont(cont)) end
  elseif m and m.worldFrames then
    G.Follow() -- from the world map: back to following the player
  elseif fromTerrain then
    local w = WorldMapID()
    if w then G.Browse(w, browseCont) else G.Follow() end
  else
    local up = G.UpMap(browse)
    if up then G.Browse(up, browseCont) else G.Follow() end
  end
end

G.CITY_WMO_YD = 300 -- a building this big at the city is the city (Ironforge, inside its mountain)
G.CITY_INDOOR_SHARE = 0.97 -- ... when about all of its rooms (by area) are indoors

-- A capital that's one huge building (a city inside a mountain): { place, wmo, room } of
-- its main hall, for its interior map; nil for a city in the open.
function G.CityInterior(id)
  local m = ns.Maps and ns.Maps[id]
  if not (m and m.bounds and m.name) then return nil end
  local b = m.bounds
  local cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
  local place, wmo, room = G.FindInterior(cx, cy, nil, m.continent, m.name, true)
  if place and math.max(place[8] - place[6], place[9] - place[7]) >= G.CITY_WMO_YD then
    -- (mostly indoors, like Ironforge: not a city in the open built as one model, like Orgrimmar)
    local indoor, all = 0, 0
    for _, g in ipairs(wmo.groups) do
      local area = (g[4] - g[1]) * (g[5] - g[2])
      all = all + area
      if g["in"] then indoor = indoor + area end
    end
    if all > 0 and indoor >= all * G.CITY_INDOOR_SHARE then return { place, wmo, room } end
  end
end

-- A capital picked on a continent's map: the terrain view over the city.
function G.ShowCity(id)
  local m = ns.Maps[id]
  if not (m and m.bounds) then return end
  local b = m.bounds
  browse, browseZoom, browseCont, browseBounds, fromTerrain = nil, nil, nil, nil, nil
  local cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
  local interior = G.CityInterior(id)
  free = { x = cx, y = cy, rot = 0, cross = true, cont = m.continent, interior = interior }
  if recenter then recenter:Show() end
  elapsed = 1
end

-- "Route Here": destination at the crosshair, then a short tour: hold 3 s, ease out to
-- show the whole route, hold 4 s, ease back in on the player and follow. Dragging the
-- map, the mouse wheel or recentering cancel it; the player moving does not.
local ROUTE_TOUR = { hold = 3, out = 1.5, show = 4, back = 1.5 }

local function Ease(t) return t < 0.5 and 2 * t * t or 1 - (-2 * t + 2) ^ 2 / 2 end

function G.CancelTour() tour = nil end

-- The view that fits the player and the destination (with the route between them).
local function Overview(px, py, cont)
  local r = ns.Nav.Route(px, py, cont) -- make sure the route exists before framing it
  local minX, maxX, minY, maxY = px, px, py, py
  if r then
    ns.Nav.EachSegment(r, cont, function(x1, y1, x2, y2)
      minX, maxX = math.min(minX, x1, x2), math.max(maxX, x1, x2)
      minY, maxY = math.min(minY, y1, y2), math.max(maxY, y1, y2)
    end)
  end
  -- every stop routed too: the legs between stops are worked out over the next frames,
  -- so right after a route is made only the first ones are drawn yet
  for i = 1, ns.Nav.PlannedStops() do
    local d = ns.Nav.stops[i]
    local x, y
    if d then x, y = Geo.ToContinent(d.cont, d.x, d.y, cont) end -- (not `d and ...`: keeps one value)
    if x and y then
      minX, maxX = math.min(minX, x), math.max(maxX, x)
      minY, maxY = math.min(minY, y), math.max(maxY, y)
    end
  end
  local half = math.max(maxX - minX, maxY - minY) / 2
  return (minX + maxX) / 2, (minY + maxY) / 2, math.max(MIN_ZOOM, half * 1.35) -- margin for rotation
end

local function TourStep(now)
  if not tour then return end
  local px, py, cont = Geo.PlayerWorld()
  if not px or not ns.Nav.dest then tour = nil return end
  local dt = now - tour.t0
  if tour.phase == "hold" and dt >= ROUTE_TOUR.hold then
    local x, y, z = Overview(px, py, cont)
    tour = { phase = "out", t0 = now, from = { free.x, free.y, browseZoom or S().zoom }, to = { x, y, z } }
  elseif tour.phase == "out" or tour.phase == "back" then
    local dur = ROUTE_TOUR[tour.phase]
    local k = Ease(math.min(1, dt / dur))
    local to = tour.to
    if tour.phase == "back" then to = { px, py, S().zoom } end -- the player may be moving
    local f = tour.from
    free.x = f[1] + (to[1] - f[1]) * k
    free.y = f[2] + (to[2] - f[2]) * k
    browseZoom = math.exp(math.log(f[3]) + (math.log(to[3]) - math.log(f[3])) * k) -- even zoom speed
    elapsed = 1
    if dt >= dur then
      if tour.phase == "out" then
        tour = { phase = "show", t0 = now }
      else
        tour = nil
        G.Follow()
      end
    end
  elseif tour.phase == "show" and dt >= ROUTE_TOUR.show then
    tour = { phase = "back", t0 = now, from = { free.x, free.y, browseZoom or S().zoom } }
  end
end

-- After setting the route: the tour. `skipHold` starts zooming out right away.
local function StartTour(px, py, cont, viewCont, skipHold)
  local dest = ns.Nav.dest
  if not dest then return end
  dest.watchX, dest.watchY = px, py -- moving ends the tour and follows the player
  browse, browseCont, browseBounds = nil, nil, nil
  pending = {}
  if viewCont == cont then
    free = { x = free.x, y = free.y, rot = free.rot } -- no crosshair once routed
  else
    -- The view is in the other continent's coordinates: go straight to the overview.
    free = { x = px, y = py, rot = 0 }
    skipHold = true
  end
  tour = { phase = "hold", t0 = GetTime() - (skipHold and ROUTE_TOUR.hold or 0) }
  elapsed = 1
end

-- Route to the crosshair (single stop).
function G.RouteHere()
  local px, py, cont = Geo.PlayerWorld()
  if not px or not free then return end
  local viewCont = ViewCont(cont)
  ns.Nav.SetDestination(free.x, free.y, viewCont)
  StartTour(px, py, cont, viewCont, false)
end

-- "Confirm Route": the double-clicked stops (in the fastest order if that option is on),
-- or the crosshair when none were placed.
function G.ConfirmRoute()
  if #pending == 0 then return G.RouteHere() end
  local px, py, cont = Geo.PlayerWorld()
  if not px or not free then return end
  local viewCont = ViewCont(cont)
  -- new stops go after the route's existing ones (clear the route first to start over)
  local stops = {}
  for _, d in ipairs(ns.Nav.stops) do stops[#stops + 1] = d end
  for _, d in ipairs(pending) do stops[#stops + 1] = d end
  ns.Nav.SetStops(stops, S().fastestOrder)
  StartTour(px, py, cont, viewCont, true)
end

-- A stop at world (x, y) in the viewed continent, named `name` in the directions (a point
-- of interest's): appended to the route when one is set, else placed for Confirm Route
-- (or the 5 s auto-confirm). Stops following the player while placing. False at the limit.
---------------------------------------------------------------------------
-- Search (the magnifier button above the map button)
---------------------------------------------------------------------------

-- Places to search: flight masters, points of interest, place names, zones and docks from
-- the addon's data. Not NPCs: the game doesn't tell addons where they are.
local searchIndex
local function SearchIndex()
  if searchIndex then return searchIndex end
  local list, seen = {}, {}
  local function add(name, sub, cont, x, y)
    if not name or name == "" or not cont then return end
    local key = name:lower() .. ":" .. cont .. ":" .. math.floor(x / 200) .. ":" .. math.floor(y / 200)
    if seen[key] then return end
    seen[key] = true
    list[#list + 1] = { name = name, lower = name:lower(), sub = sub, cont = cont, x = x, y = y }
  end
  for cont, pois in pairs(ns.Pois or {}) do
    for _, p in ipairs(pois) do
      add(p[4], p[1] == 1 and "Flight master" or p[1] == 2 and "Point of interest" or "Place", cont, p[2], p[3])
    end
  end
  for _, m in pairs(ns.Maps or {}) do
    if m.type == 3 and m.bounds and m.continent and m.continent >= 0 then
      local b = m.bounds
      add(m.name, "Zone (its middle)", m.continent, (b[1] + b[3]) / 2, (b[2] + b[4]) / 2)
    end
  end
  for _, t in ipairs(ns.Transports or {}) do
    add(t[9], t[8] .. " dock", t[1], t[2], t[3])
    add(t[10], t[8] .. " dock", t[4], t[5], t[6])
  end
  searchIndex = list
  return list
end

-- Places matching `text` (any case, 2+ letters): names starting with it first, then names
-- containing it, shorter first. At most `max` (default 8).
function G.SearchPlaces(text, max)
  local q = (text or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
  if #q < 2 then return {} end
  local starts, contains = {}, {}
  for _, e in ipairs(SearchIndex()) do
    local i = e.lower:find(q, 1, true)
    if i == 1 then
      starts[#starts + 1] = e
    elseif i then
      contains[#contains + 1] = e
    end
  end
  local function order(a, b)
    if #a.name ~= #b.name then return #a.name < #b.name end
    return a.name < b.name
  end
  table.sort(starts, order)
  table.sort(contains, order)
  local out = {}
  for _, l in ipairs({ starts, contains }) do
    for _, e in ipairs(l) do
      if #out < (max or 8) then out[#out + 1] = e end
    end
  end
  return out
end

---------------------------------------------------------------------------
-- Drawing a farming area (map menu): circle known herb/ore nodes, route a loop
---------------------------------------------------------------------------

local drawHint

-- `kind`: "farm" (a loop round nodes, the default) or "road" (a road to suggest).
function G.StartDrawing(kind)
  G.drawMode, G.lasso, G.drawKind = true, nil, kind or "farm"
  if drawHint then
    drawHint:SetText(G.drawKind == "road" and "Drag along the road  |cff9d9d9d(right-click cancels)|r"
      or G.drawKind == "erase" and "Drag over the road to take out  |cff9d9d9d(right-click cancels)|r"
      or "Drag around the nodes to farm  |cff9d9d9d(right-click cancels)|r")
    drawHint:Show()
  end
  elapsed = 1
end

function G.StopDrawing()
  G.drawMode, G.lasso = false, nil
  if drawHint then
    if G.roadMode or G.wallMode then G.RoadHint() else drawHint:Hide() end
  end
  elapsed = 1
end

-- The road tools: on until toggled off. On the map, left-drag draws a road, right-drag
-- erases one (in red), middle-drag pans.
function G.RoadHint()
  if G.wallMode then
    drawHint:SetText("|cffd02020Left-drag: draw a wall|r  ·  |cffb0b0b0Right-drag: erase walls (circle an area to erase them all)|r  ·  |cff9d9d9dMiddle-drag: pan|r")
  else
    drawHint:SetText("Left-drag: draw a road  ·  |cffff4040Right-drag: erase (circle an area to erase it all)|r  ·  |cff9d9d9dMiddle-drag: pan|r")
  end
  drawHint:Show()
end

function G.SetRoadMode(on)
  G.roadMode = on and true or false
  if G.roadMode then G.wallMode = false end -- (one set of tools at a time)
  G.lasso, drag = nil, nil
  if G.drawMode then G.drawMode = false end
  if drawHint then
    if G.roadMode or G.wallMode then G.RoadHint() else drawHint:Hide() end
  end
  if G.RefreshQuick then G.RefreshQuick() end
  elapsed = 1
end

-- The wall tools: like the road tools, for walls (what routes can't walk through): on the
-- map, left-drag draws one, right-drag erases them, middle-drag pans. On until toggled off.
function G.SetWallMode(on)
  G.wallMode = on and true or false
  if G.wallMode then G.roadMode = false end
  G.lasso, drag = nil, nil
  if G.drawMode then G.drawMode = false end
  if drawHint then
    if G.roadMode or G.wallMode then G.RoadHint() else drawHint:Hide() end
  end
  if G.RefreshQuick then G.RefreshQuick() end
  elapsed = 1
end

function G.ToggleWallMode()
  G.SetWallMode(not G.wallMode)
  ns.Print(G.wallMode and "wall tools on: left-drag draws a wall, right-drag erases walls, middle-drag pans (toggle off when done)"
    or "wall tools off")
end

function G.ToggleRoadMode()
  G.SetRoadMode(not G.roadMode)
  ns.Print(G.roadMode and "road tools on: left-drag draws a road, right-drag erases one, middle-drag pans (toggle off when done)"
    or "road tools off")
end

-- The area is drawn: a loop through the known nodes inside it (of this character's
-- gathering professions; all kinds if it has none).
function G.FinishDrawing()
  local lasso = G.lasso
  local kind = G.drawKind
  G.StopDrawing()
  if kind == "road" or kind == "erase" then return G.FinishRoad(lasso, kind == "erase") end
  if not lasso or #lasso.pts < 6 then return end
  -- the kinds shown on the map (map menu: Herbs, Ore): one, the other, or both
  local kinds = ns.Layers.VisibleKinds()
  if not kinds.herb and not kinds.ore then
    ns.Print("turn on Herbs or Ore in the map menu first: the farming area uses the nodes shown")
    return
  end
  local nodes = ns.Layers.NodesInPolygon(lasso.cont, lasso.pts, kinds)
  local px, py = Geo.PlayerWorld()
  if #nodes == 0 then
    ns.Print(string.format("no known %s in that area. Nodes show up once gathered, hovered on the minimap, right-clicked, or imported (+ button).",
      kinds.herb and kinds.ore and "herb or ore nodes" or kinds.herb and "herbs" or "ore nodes"))
    return
  elseif #nodes == 1 then
    ns.Nav.SetStops({ nodes[1] })
  else
    ns.Nav.SetLoop(nodes, px, py)
  end
  local n = #ns.Nav.stops
  ns.Print(string.format("farming route: %d node%s%s. Clear Route (or /agps clear) ends it.", n, n == 1 and "" or "s",
    n > 1 and ", round and round" or "")
    .. (#nodes > n and string.format(" (the nearest %d of %d)", n, #nodes) or ""))
  -- start it like Confirm Route: the tour over the route, then follow the player
  local _, _, cont = Geo.PlayerWorld()
  if px then
    if not free then free = { x = view.x, y = view.y, rot = view.rot, cont = view.cont } end
    StartTour(px, py, cont, ViewCont(cont), true)
  else
    G.Follow()
  end
end

-- A road drawn on the map: saved with the player's road fixes (Record.lua), so routes use
-- it at once (the stretches along an existing road are that road: Router.WithTracks); on
-- the city's own level when that's where the player is. `agps roads` takes it into the
-- road data. `erase`: a road that shouldn't be there, drawn over (a "remove" track).
-- Whether a stroke (flat points, `len` yards long) is a loop: long enough, and ending back
-- near where it started.
G.LOOP_CLOSE = 0.25 -- its ends at most this share of its length apart
function G.IsLoop(pts, len)
  local n = #pts
  if n < 8 or len < 30 then return false end
  local gap = math.sqrt((pts[n - 1] - pts[1]) ^ 2 + (pts[n] - pts[2]) ^ 2)
  return gap <= math.max(15, len * G.LOOP_CLOSE) and gap < len * 0.5
end

-- `wall`: a wall (what can't be walked through), not a road; with `erase`, walls taken out.
function G.FinishRoad(line, erase, wall)
  if not line or #line.pts < 4 then return end
  local pts, len = {}, 0
  for i = 1, #line.pts - 1, 2 do
    local x, y = line.pts[i], line.pts[i + 1]
    local n = #pts
    if n >= 2 then len = len + math.sqrt((x - pts[n - 1]) ^ 2 + (y - pts[n]) ^ 2) end
    pts[n + 1], pts[n + 2] = math.floor(x * 10 + 0.5) / 10, math.floor(y * 10 + 0.5) / 10
  end
  if len < 8 then
    ns.Print(wall and "that wall is too short (drag along it)" or "that road is too short (drag along it)")
    return
  end
  -- (down in a city: on its level only when drawn over the city, not somewhere else looked at)
  local level = ns.Nav.PlayerLevel and ns.Nav.PlayerLevel(line.cont) or line.cont
  if level ~= line.cont and not (ns.Passability and ns.Passability.InGrid and ns.Passability.InGrid(level, pts[1], pts[2])) then
    level = line.cont
  end
  local mapID = C_Map.GetBestMapForUnit("player")
  local info = mapID and C_Map.GetMapInfo(mapID)
  -- an erase drawn as a loop (ending back near its start): the roads inside it go
  local area = erase and G.IsLoop(pts, len) or nil
  local op = wall and (erase and "unwall" or "wall") or (erase and "remove" or "add")
  local i = ns.Record.Save({ op = op, drawn = true, continent = level,
    zone = info and info.name or "?", time = time(), pts = pts, area = area })
  if wall then
    ns.Print(string.format(erase and "erased the walls %s (#%d). /agps draw undo puts them back."
      or "saved your wall (#%d, %d yd): routes won't cross it now, roads included (leave a gap for a gate). /agps draw undo takes it back.",
      erase and (area and "inside that circle" or "along that stroke") or i, erase and i or math.floor(len + 0.5)))
    elapsed = 1
    return
  end
  if area then
    ns.Print(string.format("erased the roads inside that circle (#%d): routes leave them out now. /agps draw undo puts them back.", i))
    elapsed = 1
    return
  end
  ns.Print(string.format(erase and "erased that road (#%d, %d yd): routes leave it out now. /agps draw undo puts it back."
    or "saved your road (#%d, %d yd): routes use it now (joined to the roads it meets). /agps draw undo takes it back.",
    i, math.floor(len + 0.5)))
  elapsed = 1
end

function G.AddStopAt(x, y, name, stopCont, tex)
  local px, _, cont = Geo.PlayerWorld()
  if not px then return false end
  local max = ns.Nav.loop and ns.Nav.MAX_LOOP_STOPS or ns.Nav.MAX_STOPS
  if #ns.Nav.stops + #pending >= max then
    ns.Print("at most " .. max .. " stops per route")
    return false
  end
  if not free then
    free = { x = view.x, y = view.y, rot = view.rot, cross = true, cont = view.cont }
    if recenter then recenter:Show() end
  end
  tour = nil
  local sc = stopCont or ViewCont(cont)
  if ns.Nav.StopLevel then sc = ns.Nav.StopLevel(sc, x, y) end -- down in a city: on its level
  -- a place picked on the map (its icon: a guard's city location...) on a city's floors is
  -- down there, wherever the player is
  if tex and ns.Layers and ns.Layers.CityLevelAt then sc = ns.Layers.CityLevelAt(Geo.Base(sc), x, y) or sc end
  local stop = { x = x, y = y, cont = sc, name = name, icon = ns.Nav.NextMarker(ns.Nav.stops, pending), tex = tex }
  if #ns.Nav.stops > 0 then
    ns.Nav.AddStop(stop, S().fastestOrder) -- a route is set: straight onto it
    G.appended = true -- after AUTO_CONFIRM seconds of quiet: the tour, then follow again
  else
    pending[#pending + 1] = stop
  end
  lastActivity = GetTime()
  elapsed = 1
  return true
end

-- Double-click on the map: a stop at that spot (up to Nav.MAX_STOPS, one marker each).
function G.AddPending(dxUI, dyUI)
  -- (not on a city location a guard hasn't pointed out: that's asked of a guard)
  local ccx, ccy = canvas:GetCenter()
  for _, b in ipairs(poiButtons) do
    if b:IsShown() and b.preview then
      local bx, by = b:GetCenter()
      if bx and (bx - ccx - dxUI) ^ 2 + (by - ccy - dyUI) ^ 2 <= 100 then return end
    end
  end
  G.AddStopAt(G.ScreenToWorld(view.x, view.y, dxUI, dyUI, view.rot, view.s))
end

-- Right-click on a stop's marker: a small "Remove?" button next to it.
local removeAsk
function G.AskRemove(pin)
  if not removeAsk then
    removeAsk = CreateFrame("Button", nil, keepLayer, "UIPanelButtonTemplate")
    removeAsk:SetSize(76, 20)
    removeAsk:SetText("Remove?")
    removeAsk:SetFrameLevel(keepLayer:GetFrameLevel() + 6)
    removeAsk:SetScript("OnClick", function(self)
      self:Hide()
      if self.pendingIndex then
        G.RemovePending(self.pendingIndex)
      elseif self.stopIndex then
        ns.Nav.RemoveStop(self.stopIndex)
        elapsed = 1
      end
    end)
    removeAsk:SetScript("OnUpdate", function(self)
      if GetTime() - self.shownAt > 5 then self:Hide() end -- not taken up: go away
    end)
  end
  removeAsk.pendingIndex, removeAsk.stopIndex = pin.pendingIndex, pin.stopIndex
  removeAsk.shownAt = GetTime()
  removeAsk:ClearAllPoints()
  removeAsk:SetPoint("BOTTOM", pin, "TOP", 0, 2)
  removeAsk:Show()
  GameTooltip_Hide()
end

function G.RemovePending(i)
  table.remove(pending, i)
  local kept = {}
  for _, d in ipairs(pending) do
    d.icon = ns.Nav.NextMarker(ns.Nav.stops, kept)
    kept[#kept + 1] = d
  end
  lastActivity = GetTime()
  elapsed = 1
end

-- Hovering a quest area on the map shows the quest and its objectives, like the minimap.
local hoverWait, hoverKey = 0, nil
local infoWait = 0
function G.AreaTooltip(dt)
  hoverWait = hoverWait - dt
  if hoverWait > 0 then return end
  hoverWait = 0.1
  local st = S()
  local over = canvas and canvas:IsMouseOver() and not drag and ns.Layers and st.layerQuests and st.layerQuestAreas
  local owned = GameTooltip:IsShown() and GameTooltip:GetOwner() == frame
  if over and GameTooltip:IsShown() and not owned then return end -- another tooltip (an icon) has it
  local quests = {}
  if over then
    local mx, my = GetCursorPosition()
    local sc = canvas:GetEffectiveScale()
    local ccx, ccy = canvas:GetCenter()
    local x, y = G.ScreenToWorld(view.x, view.y, mx / sc - ccx, my / sc - ccy, view.rot, view.s)
    local _, _, pc = Geo.PlayerWorld()
    quests = ns.Layers.QuestsAt(browse and browseCont or pc, x, y)
  end
  if #quests == 0 then
    if owned and hoverKey then GameTooltip:Hide() end -- (only its own: the zone hover's stays)
    hoverKey = nil
    G.areaTip = false
    return
  end
  table.sort(quests)
  local key = table.concat(quests, ",")
  if owned and key == hoverKey then return end
  hoverKey = key
  G.areaTip = true
  GameTooltip:SetOwner(frame, "ANCHOR_CURSOR")
  for i, q in ipairs(quests) do
    if i > 1 then GameTooltip:AddLine(" ") end
    ns.Layers.AddQuestToTooltip(GameTooltip, q)
  end
  GameTooltip:Show()
end

function G.IsFree() return free ~= nil end

function G.Redraw() elapsed = 1 end

-- Near the next stop (option): the map zooms in smoothly for the last yards, and back out
-- once you're there (or move away, or zoom yourself). Only while following the player.
G.APPROACH_YD = 50 -- zoom in this close to the stop
G.APPROACH_LEAVE_YD = 70 -- ... and back out beyond this
G.APPROACH_ZOOM = 70 -- yards from the middle to the edge, zoomed in
G.APPROACH_SPEED = 2.5 -- how fast it eases (per second)

function G.ApproachTarget(px, py, cont)
  local st = S()
  local N = ns.Nav
  local d = N.dest
  if not st.approachZoom or not d or not px or free or browse or tour or N.arrivedAt then return nil end
  -- (on its level: not with the stop straight above or below, down a lift)
  if N.PlayerLevel(cont) ~= d.cont or d.spotReached or N.QuestPaused() or approachSkip == d then return nil end
  local dd = math.sqrt((d.x - px) ^ 2 + (d.y - py) ^ 2)
  if dd > (approachFor == d and G.APPROACH_LEAVE_YD or G.APPROACH_YD) then return nil end
  approachFor = d
  return math.min(st.zoom, G.APPROACH_ZOOM)
end

function G.UpdateApproach(dt)
  local st = S()
  local px, py, cont = Geo.PlayerWorld()
  local target = G.ApproachTarget(px, py, cont)
  if not target then approachFor = nil end
  if not target and not approachZoom then return end
  local goal = target or st.zoom
  local cur = approachZoom or st.zoom
  local nz = math.exp(math.log(cur) + (math.log(goal) - math.log(cur)) * math.min(1, dt * G.APPROACH_SPEED))
  if not target and math.abs(nz - st.zoom) < st.zoom * 0.01 then
    approachZoom = nil -- back to the zoom it had
  else
    approachZoom = nz
  end
  if math.abs(nz - cur) > 0.01 then elapsed = 1 end
end

-- A route made or changed from outside the map (quest route, a shared map pin): the
-- route tour when the map is open (closing it ends the tour and follows the player);
-- closed, just follow the player, no tour when it's opened.
function G.RouteChanged()
  local px, py, cont = Geo.PlayerWorld()
  G.Follow()
  if frame and frame:IsVisible() and px and ns.Nav.dest then
    free = { x = view.x, y = view.y, rot = view.rot, cont = view.cont }
    StartTour(px, py, cont, ViewCont(cont), true)
    elapsed = 1
  end
end

-- The quest route button: stops for the quest log's objectives and turn-ins, in the
-- fastest order, as the route.
function G.QuestRoute()
  if InCombatLockdown and InCombatLockdown() then
    ns.Print("Quest route: not in combat (the game hides quest locations then).")
    return
  end
  if not (ns.Layers and ns.Layers.QuestStops) then return end
  local onlyZone = S().questZoneOnly
  local stops, c = ns.Layers.QuestStops(onlyZone)
  if #stops == 0 then
    ns.Print(onlyZone and c.elsewhere > 0
      and string.format("Quest route: none of your quests are in this zone (%d elsewhere; Options > Routing: only this zone).", c.elsewhere)
      or "Quest route: no quest locations found in your quest log.")
    return
  end
  ns.Nav.SetStops(stops, true)
  ns.Nav.questRouteStale = nil
  G.RouteChanged()
  local msg = string.format("Quest route: %d stop%s (%d to do, %d to turn in).", #ns.Nav.stops,
    #ns.Nav.stops == 1 and "" or "s", c.todo, c.turnin)
  if (c.elsewhere or 0) > 0 then msg = msg .. string.format(" %d in other zones left out.", c.elsewhere) end
  if #c.missing > 0 then msg = msg .. " No location for: " .. table.concat(c.missing, ", ") .. "." end
  ns.Print(msg)
end

-- Background terrain searches and road data (Router.Pump), ~1 ms a frame (WARM_MS while a
-- road network is being built). Run by the map window, or by the arrow window while the map
-- is hidden (e.g. in combat). True when one finished (the route was invalidated to use it).
G.WARM_MS = 5
function G.PumpSearches()
  if not ns.Router.HasWork() then return false end
  local t0 = ns.PerfStart()
  local budget = ns.Router.Warming and ns.Router.Warming() and G.WARM_MS or 1 -- (ms of this frame)
  local done, fixed = ns.Router.Pump(debugprofilestop() + budget, debugprofilestop)
  if done then ns.Nav.SearchDone(fixed) end
  ns.PerfEnd("terrain search", t0)
  return done
end

function G.IsVisible() return frame ~= nil and frame:IsVisible() end

-- What the picture depends on, compared with the last redraw (no garbage: values are
-- kept in `sig`). Returns true when any of it changed.
local sig = {}
local REDRAW_IDLE = 1
local lastFull = 0
local function SigChanged(...)
  local changed = false
  for i = 1, select("#", ...) do
    local v = select(i, ...)
    if sig[i] ~= v then
      sig[i] = v
      changed = true
    end
  end
  return changed
end

local function ViewChanged()
  local px, py, cont = Geo.PlayerWorld()
  local st = S()
  return SigChanged(px and math.floor(px * 10) or false, py and math.floor(py * 10) or false, cont or false,
    math.floor((Geo.Facing() or 0) * 500), browseZoom or approachZoom or st.zoom, free and free.x or false, free and free.y or false,
    free and free.rot or false, browse or false, ns.Nav.route or false, #ns.Nav.stops, #pending,
    ns.Layers and ns.Layers.version or 0, st.style, canvas:GetWidth())
end

function G.SetZoom(z)
  -- zooming yourself near a stop: that zoom stays (no zooming back out for this stop)
  if approachZoom then approachSkip, approachZoom = ns.Nav.dest, nil end
  S().zoom = math.max(MIN_ZOOM, math.min(MAX_ZOOM, z))
  elapsed = 1
end

function G.Init()
  if frame then return end
  frame = CreateFrame("Frame", "AzerothGPSFrame", UIParent, "BackdropTemplate")
  frame:SetFrameStrata("MEDIUM")
  frame:SetClampedToScreen(true)
  frame:EnableMouse(true)
  -- Left-drag pans the map (free view); Shift+left-drag moves the frame.
  frame:SetScript("OnMouseDown", function(f, button)
    if removeAsk then removeAsk:Hide() end
    -- a click on the map closes the map menu and the search panel
    if G.mapMenu then G.mapMenu:Hide() end
    if G.searchPanel then G.searchPanel:Hide() end
    if (G.roadMode or G.wallMode) and not G.drawMode then
      if button == "LeftButton" or button == "RightButton" then
        local erase = button == "RightButton"
        local wall = G.wallMode
        G.lasso = { pts = {}, cont = view.cont, road = true, erase = erase, wall = wall, button = button,
          color = wall and (erase and UNWALL_COLOR or WALL_COLOR) or (erase and ERASE_COLOR or DRAW_COLOR) }
      elseif button == "MiddleButton" then
        local mx, my = GetCursorPosition()
        tour = nil
        lastActivity = GetTime()
        drag = { cx = mx, cy = my, x = view.x, y = view.y, rot = view.rot, s = view.s, moved = false, pan = true }
      end
      return
    end
    if G.drawMode then
      if button == "RightButton" then
        G.StopDrawing()
      elseif button == "LeftButton" then
        G.lasso = { pts = {}, cont = view.cont, road = G.drawKind == "road" }
      end
      return
    end
    if button == "RightButton" then
      if G.IsMapStyle(S().style) then
        G.ZoomOut()
      elseif S().terrainZoomOut ~= false then
        G.TerrainZoomOut()
      end
      return
    end
    if button ~= "LeftButton" then return end
    if IsShiftKeyDown() then
      if not S().locked then
        f:StartMoving()
        f.moving = true
      end
      return
    end
    local mx, my = GetCursorPosition()
    tour = nil
    lastActivity = GetTime()
    drag = { cx = mx, cy = my, x = view.x, y = view.y, rot = view.rot, s = view.s, moved = false }
  end)
  frame:SetScript("OnMouseUp", function(f, button)
    if (G.roadMode or G.wallMode) and not G.drawMode then
      local l = G.lasso
      if l and button == l.button then
        G.lasso = nil
        local okF, errF = pcall(G.FinishRoad, l, l.erase, l.wall)
        if not okF then G.LogError("saving a drawn road or wall", errF) end
      elseif button == "MiddleButton" then
        drag = nil
      end
      return
    end
    if G.drawMode then
      if button == "LeftButton" and G.lasso then G.FinishDrawing() end
      return
    end
    if f.moving then
      f:StopMovingOrSizing()
      f.moving = false
      SavePosition()
    end
    if button == "LeftButton" and drag and not drag.moved then
      local mx, my = GetCursorPosition()
      local sc = canvas:GetEffectiveScale()
      local ccx, ccy = canvas:GetCenter()
      local dx, dy = mx / sc - ccx, my / sc - ccy
      local now = GetTime()
      local m = browse and ns.Maps[browse]
      local worldMap = m and m.type <= 2 -- a click there opens a zone instead
      if not worldMap and lastClick and now - lastClick.t <= DOUBLE_CLICK
          and (dx - lastClick.x) ^ 2 + (dy - lastClick.y) ^ 2 <= 100 then
        lastClick = nil
        G.AddPending(dx, dy)
      else
        lastClick = { t = now, x = dx, y = dy }
        OnMapClick(dx, dy)
      end
    end
    drag = nil
  end)
  frame:EnableMouseWheel(true)
  frame:SetScript("OnMouseWheel", function(_, delta)
    tour = nil
    lastActivity = GetTime()
    local f = delta > 0 and 0.8 or 1.25
    if browseZoom then
      browseZoom = math.max(MIN_ZOOM, browseZoom * f)
      elapsed = 1
    else
      G.SetZoom(S().zoom * f)
    end
  end)
  frame:SetBackdrop({
    bgFile = "Interface\\Buttons\\WHITE8X8",
    edgeFile = "Interface\\Buttons\\WHITE8X8",
    edgeSize = BORDER,
  })
  frame:SetBackdropColor(0.05, 0.05, 0.05, 1)
  frame:SetBackdropBorderColor(0.15, 0.15, 0.15, 1)

  -- "Move" tab above the top edge while unlocked: drag it to move the frame.
  local tab = CreateFrame("Button", nil, frame, "BackdropTemplate")
  tab:SetSize(84, 18)
  tab:SetPoint("BOTTOM", frame, "TOP", 0, -1)
  tab:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
  tab:SetBackdropColor(0.12, 0.12, 0.14, 0.95)
  tab:SetBackdropBorderColor(0.3, 0.3, 0.3, 1)
  local tabText = tab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  tabText:SetPoint("CENTER")
  tabText:SetText("Move")
  tab:RegisterForDrag("LeftButton")
  tab:SetScript("OnDragStart", function() frame:StartMoving() end)
  tab:SetScript("OnDragStop", function() frame:StopMovingOrSizing(); SavePosition() end)
  tab:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText("Drag to move the GPS", 1, 1, 1)
    GameTooltip:AddLine("Lock it in the options (or /agps lock) to hide this tab.", 0.8, 0.8, 0.8, true)
    GameTooltip:Show()
  end)
  tab:SetScript("OnLeave", GameTooltip_Hide)
  G.moveTab = tab

  -- While unlocked: the game's own window frame (metal border, title bar, portrait, close
  -- button) around the map, from the client's PortraitFrameTemplate. A child of the map, so
  -- it takes the map's opacity. Only its border and title bar draw over the map; the map
  -- stays clickable (only the title bar and the close button take the mouse). If the
  -- template isn't there, the plain Move tab is used instead.
  local ok, chrome = pcall(CreateFrame, "Frame", nil, frame, "PortraitFrameTemplate")
  if ok and chrome and chrome.NineSlice then
    chrome:SetPoint("TOPLEFT", frame, "TOPLEFT", -2, CHROME_TITLE)
    chrome:SetPoint("BOTTOMRIGHT", frame, "BOTTOMRIGHT", 2, -2)
    chrome:SetFrameLevel(frame:GetFrameLevel() + 12)
    chrome:EnableMouse(false)
    if chrome.Bg then chrome.Bg:Hide() end -- the map is the window's content
    if chrome.TopTileStreaks then chrome.TopTileStreaks:Hide() end
    local strip = chrome:CreateTexture(nil, "BACKGROUND") -- behind the title only
    strip:SetPoint("TOPLEFT", 2, -2)
    strip:SetPoint("BOTTOMRIGHT", chrome, "TOPRIGHT", -2, -CHROME_TITLE)
    strip:SetColorTexture(0.06, 0.06, 0.07, 1)
    if chrome.SetTitle then chrome:SetTitle("AzerothGPS")
    elseif chrome.TitleContainer and chrome.TitleContainer.TitleText then chrome.TitleContainer.TitleText:SetText("AzerothGPS") end
    -- the AzerothGPS logo in the round portrait (top left); the map's top panel moves
    -- right of it while unlocked (ApplySettings)
    ns.SetLogoPortrait(chrome)
    if chrome.CloseButton then
      chrome.CloseButton:SetScript("OnClick", function()
        S().shown = false
        G.ApplySettings()
        ns.Print("map hidden: /agps show or the minimap button brings it back")
      end)
    end
    -- the title bar moves the map
    local grab = CreateFrame("Frame", nil, chrome)
    grab:SetPoint("TOPLEFT", 56, 0)
    grab:SetPoint("TOPRIGHT", -26, 0)
    grab:SetHeight(CHROME_TITLE)
    grab:EnableMouse(true)
    grab:RegisterForDrag("LeftButton")
    grab:SetScript("OnDragStart", function() if not S().locked then frame:StartMoving() end end)
    grab:SetScript("OnDragStop", function() frame:StopMovingOrSizing(); SavePosition() end)
    grab:SetScript("OnEnter", function(self)
      GameTooltip:SetOwner(self, "ANCHOR_TOP")
      if S().locked then
        GameTooltip:SetText("AzerothGPS", 1, 1, 1)
        GameTooltip:AddLine("Locked. Unlock the map in the options (or /agps unlock map) to move it.", 0.8, 0.8, 0.8, true)
      else
        GameTooltip:SetText("Drag to move the GPS", 1, 1, 1)
        GameTooltip:AddLine("Lock it in the options (or /agps lock map) to keep it in place.", 0.8, 0.8, 0.8, true)
      end
      GameTooltip:Show()
    end)
    grab:SetScript("OnLeave", GameTooltip_Hide)
    G.chrome = chrome
  end

  canvas = CreateFrame("Frame", nil, frame)
  canvas:SetPoint("TOPLEFT", BORDER, -BORDER)
  canvas:SetPoint("BOTTOMRIGHT", -BORDER, BORDER)
  canvas:SetClipsChildren(true)

  tileLayer = CreateFrame("Frame", nil, canvas) -- the map tiles (fade while moving)
  tileLayer:SetAllPoints(canvas)
  tileLayer:SetFrameLevel(canvas:GetFrameLevel() + 1)

  areaLayer = CreateFrame("Frame", nil, canvas) -- quest area outlines (DrawAreas), clipped
  areaLayer:SetSize(1, 1)
  areaLayer:SetFrameLevel(canvas:GetFrameLevel() + 2)

  lineLayer = CreateFrame("Frame", nil, canvas) -- roads and routes, above the tiles, still clipped
  lineLayer:SetAllPoints(canvas)
  lineLayer:SetFrameLevel(canvas:GetFrameLevel() + 2)

  poiLayer = CreateFrame("Frame", nil, canvas) -- clickable points of interest, clipped
  poiLayer:SetAllPoints(canvas)
  poiLayer:SetFrameLevel(canvas:GetFrameLevel() + 3)

  keepLayer = CreateFrame("Frame", nil, canvas) -- stop markers (don't fade), clipped
  keepLayer:SetAllPoints(canvas)
  keepLayer:SetFrameLevel(canvas:GetFrameLevel() + 4)

  local top = CreateFrame("Frame", nil, frame) -- above the map tiles
  top:SetAllPoints(canvas)
  top:SetFrameLevel(canvas:GetFrameLevel() + 5)
  topLayer = top

  arrow = lineLayer:CreateTexture(nil, "OVERLAY", nil, 7) -- clipped: may leave the view in free mode
  arrow:SetTexture("Interface\\Minimap\\MinimapArrow")
  arrow:SetSize(32, 32)
  arrow:SetPoint("CENTER")

  recenter = CreateFrame("Button", nil, top)
  recenter:SetSize(28, 28)
  recenter:SetPoint("BOTTOMRIGHT", -6, 38)
  local rbg = recenter:CreateTexture(nil, "BACKGROUND")
  rbg:SetAllPoints()
  rbg:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  local ricon = recenter:CreateTexture(nil, "ARTWORK")
  ricon:SetTexture("Interface\\Minimap\\MinimapArrow")
  ricon:SetSize(24, 24)
  ricon:SetPoint("CENTER")
  recenter:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
  recenter:SetScript("OnClick", function() G.Follow() end)
  recenter:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:SetText("Back to your position", 1, 1, 1)
    GameTooltip:Show()
  end)
  recenter:SetScript("OnLeave", GameTooltip_Hide)
  recenter:Hide()

  -- Import waypoints (TomTom /way lines): bottom-right, below the recenter button.
  local import = CreateFrame("Button", nil, top)
  import:SetSize(28, 28)
  import:SetPoint("BOTTOMRIGHT", -6, 6)
  local ibg = import:CreateTexture(nil, "BACKGROUND")
  ibg:SetAllPoints()
  ibg:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  local iicon = import:CreateTexture(nil, "ARTWORK")
  iicon:SetTexture("Interface\\Buttons\\UI-PlusButton-Up")
  iicon:SetSize(18, 18)
  iicon:SetPoint("CENTER")
  import:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
  import:SetScript("OnClick", function() ns.Import.Toggle() end)
  import:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:SetText("Import and share waypoints", 1, 1, 1)
    GameTooltip:AddLine("Paste TomTom /way lines to make them the route's stops, or copy or send your route to someone else.", nil, nil, nil, true)
    GameTooltip:Show()
  end)
  import:SetScript("OnLeave", GameTooltip_Hide)

  -- Map menu (bottom-left): a round button that opens the map type and the map layers.
  local STYLES = {
    { "minimap", "Interface\\Icons\\INV_Misc_Map02", "Terrain view", "The ground seen from above, like the minimap." },
    { "zone", "Interface\\Icons\\INV_Misc_Map05", "World map", "The world map, fully explored. Right-click to zoom out to the continent; click a zone to open it." },
    { "nospoiler", "Interface\\Icons\\INV_Misc_Map03", "No Spoiler map", "The world map as your character has explored it: undiscovered parts stay hidden. Routes still use every road." },
  }
  local mapButton = CreateFrame("Button", nil, top)
  mapButton:SetSize(MAP_BUTTON, MAP_BUTTON)
  mapButton:SetPoint("BOTTOMLEFT", 3, 3)
  local mbIcon = mapButton:CreateTexture(nil, "ARTWORK")
  mbIcon:SetAllPoints()
  mbIcon:SetTexture("Interface\\AddOns\\AzerothGPS\\Media\\MapMenu")
  local mbGlow = mapButton:CreateTexture(nil, "HIGHLIGHT")
  mbGlow:SetAllPoints()
  mbGlow:SetTexture("Interface\\AddOns\\AzerothGPS\\Media\\MapMenu")
  mbGlow:SetBlendMode("ADD")
  mbGlow:SetAlpha(0.35)

  -- The drawer's open/closed state: an invisible frame shown while it's open (its OnUpdate
  -- closes it after MENU_IDLE seconds untouched; a click on the map closes it too). What's
  -- in it are the quick buttons put "in the menu" (G.LayoutQuick).
  local menu = CreateFrame("Frame", nil, mapButton)
  menu:SetSize(1, 1)
  menu:SetPoint("CENTER")
  menu:Hide()
  if ns.Layers then ns.Layers.Init() end
  function G.RefreshMapMenu()
    if G.RefreshQuick then G.RefreshQuick() end
  end
  menu:SetScript("OnShow", function(self) self.idle = 0 end)
  menu:SetScript("OnUpdate", function(self, dt)
    if mapButton:IsMouseOver() or (G.QuickMouseOver and G.QuickMouseOver()) then
      self.idle = 0
    else
      self.idle = (self.idle or 0) + dt
      if self.idle >= MENU_IDLE then self:Hide() end
    end
  end)

  mapButton:SetScript("OnClick", function() menu:SetShown(not menu:IsShown()) end)
  mapButton:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText("Map", 1, 1, 1)
    GameTooltip:AddLine("Opens the quick buttons you keep in the menu: map styles, layers, drawing a farming area and more (Options: Quick buttons). Closes after 20 seconds untouched.", nil, nil, nil, true)
    GameTooltip:Show()
  end)
  mapButton:SetScript("OnLeave", GameTooltip_Hide)
  G.mapButton, G.mapMenu = mapButton, menu

  -- (the zone under the mouse on a continent's map, beside the cursor)
  G.zoneLabel = top:CreateFontString(nil, "OVERLAY", "GameFontHighlightLarge")
  G.zoneLabel:SetJustifyH("LEFT")
  G.zoneLabel:SetShadowColor(0, 0, 0, 1)
  G.zoneLabel:SetShadowOffset(1, -1)
  G.zoneLabel:Hide()
  drawHint = top:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  -- (as wide as the map, less a margin: longer lines wrap instead of running past its edges)
  drawHint:SetPoint("TOPLEFT", top, "TOPLEFT", 14, -46)
  drawHint:SetPoint("TOPRIGHT", top, "TOPRIGHT", -14, -46)
  drawHint:SetWordWrap(true)
  drawHint:SetJustifyH("CENTER")
  drawHint:SetText("Drag around the nodes to farm  |cff9d9d9d(right-click cancels)|r")
  -- (on a black band, a quarter opaque, so it reads over any map; shown and hidden with it)
  local hintBg = top:CreateTexture(nil, "ARTWORK")
  hintBg:SetColorTexture(0, 0, 0, 0.25)
  hintBg:SetPoint("TOPLEFT", drawHint, "TOPLEFT", -8, 4)
  hintBg:SetPoint("BOTTOMRIGHT", drawHint, "BOTTOMRIGHT", 8, -4)
  local show, hide = drawHint.Show, drawHint.Hide
  drawHint.Show = function(self) show(self); hintBg:Show() end
  drawHint.Hide = function(self) hide(self); hintBg:Hide() end
  drawHint:Hide()

  -- Search: a small round magnifier button above the map button
  local search = CreateFrame("Button", nil, top)
  search:SetSize(26, 26)
  search:SetPoint("BOTTOM", mapButton, "TOP", 0, 4)
  local sbg = search:CreateTexture(nil, "BACKGROUND")
  sbg:SetAllPoints()
  sbg:SetTexture("Interface\\AddOns\\AzerothGPS\\Media\\MapMenu") -- the same round frame
  sbg:SetVertexColor(0.35, 0.35, 0.35)
  local sicon = search:CreateTexture(nil, "ARTWORK")
  sicon:SetPoint("TOPLEFT", 6, -6)
  sicon:SetPoint("BOTTOMRIGHT", -6, 6)
  ns.SetIcon(sicon, "atlas:common-search-magnifyingglass", "Interface\\Icons\\INV_Misc_Spyglass_03")
  local shl = search:CreateTexture(nil, "HIGHLIGHT")
  shl:SetAllPoints()
  shl:SetTexture("Interface\\AddOns\\AzerothGPS\\Media\\MapMenu")
  shl:SetBlendMode("ADD")
  shl:SetAlpha(0.3)

  local panel = CreateFrame("Frame", nil, search, "BackdropTemplate")
  panel:SetFrameStrata("DIALOG")
  panel:SetSize(270, 36)
  panel:SetPoint("BOTTOMLEFT", search, "BOTTOMRIGHT", 6, 0)
  panel:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
  panel:SetBackdropColor(0.05, 0.05, 0.06, 0.95)
  panel:SetBackdropBorderColor(0.3, 0.3, 0.3, 1)
  panel:EnableMouse(true)
  panel:Hide()
  local box = CreateFrame("EditBox", nil, panel, "InputBoxTemplate")
  box:SetSize(248, 20)
  box:SetPoint("TOPLEFT", 14, -8)
  box:SetAutoFocus(false)
  box:SetMaxLetters(40)
  local rows, results = {}, {}
  local function Pick(e)
    if not e then return end
    panel:Hide()
    local _, _, cont = Geo.PlayerWorld()
    if e.cont == ViewCont(cont) then -- show it: the view moves there
      free = { x = e.x, y = e.y, rot = view.rot, cross = true, cont = e.cont }
      recenter:Show()
    end
    G.AddStopAt(e.x, e.y, e.name, e.cont)
    ns.Print(string.format("stop: %s (%s)", e.name, e.sub))
  end
  local function Refresh()
    results = G.SearchPlaces(box:GetText(), 8)
    for i, e in ipairs(results) do
      local r = rows[i]
      if not r then
        r = CreateFrame("Button", nil, panel)
        r:SetSize(248, 18)
        r:SetPoint("TOPLEFT", 12, -32 - (i - 1) * 18)
        local hl = r:CreateTexture(nil, "HIGHLIGHT")
        hl:SetAllPoints()
        hl:SetColorTexture(1, 1, 1, 0.1)
        r.text = r:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
        r.text:SetPoint("LEFT", 4, 0)
        r.text:SetPoint("RIGHT", -4, 0)
        r.text:SetJustifyH("LEFT")
        r.text:SetWordWrap(false)
        r:SetScript("OnClick", function(self) Pick(self.entry) end)
        rows[i] = r
      end
      r.entry = e
      r.text:SetText(string.format("%s  |cff9d9d9d%s|r", e.name, e.sub))
      r:Show()
    end
    for i = #results + 1, #rows do rows[i]:Hide() end
    local extra = (#results == 0 and #(box:GetText() or "") >= 2) and 18 or 0
    panel:SetHeight(36 + #results * 18 + extra)
    panel.none:SetShown(extra > 0)
  end
  panel.none = panel:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  panel.none:SetPoint("TOPLEFT", 16, -34)
  panel.none:SetText("No places by that name (NPCs can't be searched)")
  panel.none:Hide()
  box:SetScript("OnTextChanged", function()
    panel.idle = 0 -- typing keeps it open
    Refresh()
  end)
  -- closes by itself after SEARCH_IDLE seconds without typing or the mouse over it
  panel:SetScript("OnShow", function(self) self.idle = 0 end)
  panel:SetScript("OnUpdate", function(self, dt)
    if self:IsMouseOver() or search:IsMouseOver() then
      self.idle = 0
    else
      self.idle = (self.idle or 0) + dt
      if self.idle >= SEARCH_IDLE then
        box:ClearFocus()
        self:Hide()
      end
    end
  end)
  box:SetScript("OnEnterPressed", function() Pick(results[1]) end)
  box:SetScript("OnEscapePressed", function() panel:Hide() end)
  search:SetScript("OnClick", function()
    panel:SetShown(not panel:IsShown())
    if panel:IsShown() then
      box:SetText("")
      Refresh()
      box:SetFocus()
    end
  end)
  search:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText("Search places", 1, 1, 1)
    GameTooltip:AddLine("Type 2+ letters, then pick a place to add it as a stop (Enter takes the first).", nil, nil, nil, true)
    GameTooltip:AddLine("Finds: towns and places, zones, landmarks, flight masters, and boat and zeppelin docks, on every continent.", 0.8, 0.8, 0.8, true)
    GameTooltip:AddLine("Not NPCs: the game doesn't tell addons where NPCs are. A zone's result is the middle of the zone.", 0.8, 0.8, 0.8, true)
    GameTooltip:Show()
  end)
  search:SetScript("OnLeave", GameTooltip_Hide)
  G.searchButton, G.searchPanel = search, panel

  -- A small round button like the map button: an icon in the same frame. Returns it and
  -- its icon texture.
  local function RoundButton(size, iconPath)
    local b = CreateFrame("Button", nil, top)
    b:SetSize(size, size)
    local bg = b:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetTexture("Interface\\AddOns\\AzerothGPS\\Media\\MapMenu") -- the same round frame
    bg:SetVertexColor(0.35, 0.35, 0.35)
    local icon = b:CreateTexture(nil, "ARTWORK")
    icon:SetPoint("TOPLEFT", 5, -5)
    icon:SetPoint("BOTTOMRIGHT", -5, 5)
    ns.SetIcon(icon, iconPath, "Interface\\Icons\\INV_Misc_QuestionMark")
    local mask = b:CreateMaskTexture()
    mask:SetAllPoints(icon)
    mask:SetTexture("Interface\\CharacterFrame\\TempPortraitAlphaMask", "CLAMPTOBLACKADDITIVE", "CLAMPTOBLACKADDITIVE")
    icon:AddMaskTexture(mask)
    local hl = b:CreateTexture(nil, "HIGHLIGHT")
    hl:SetAllPoints()
    hl:SetTexture("Interface\\AddOns\\AzerothGPS\\Media\\MapMenu")
    hl:SetBlendMode("ADD")
    hl:SetAlpha(0.3)
    b:SetScript("OnLeave", GameTooltip_Hide)
    return b, icon
  end

  -- Quest route: stops for the quest log, fastest order.
  local qr = RoundButton(26, "Interface\\Icons\\Ability_Rogue_Sprint")
  qr:SetScript("OnClick", function() G.QuestRoute() end)
  qr:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText("Quest route", 1, 1, 1)
    GameTooltip:AddLine("A route through your quest log: where each quest's objectives are, and where finished quests are turned in, in the fastest order. Replaces the current route.", nil, nil, nil, true)
    GameTooltip:Show()
  end)

  -- The quick buttons. Each goes on the bar (always shown, along the bottom from the map
  -- button), in the menu (a column going up from the map button, shown with its menu) or
  -- nowhere: gps.quick[id] = G.QUICK_PLACES (Options: Quick buttons). What
  -- doesn't fit on the bar at the map's size goes in the menu.
  local QUICK = {
    { id = "search", button = search, label = "Search places" },
    { id = "questRoute", button = qr, label = "Quest route" },
    { id = "hearth", key = "useHearthstone", icon = "Interface\\Icons\\INV_Misc_Rune_01", label = "Use hearthstone",
      tip = "A route may start with your Hearthstone when it's ready and faster.", route = true, defaultOn = true },
    { id = "offroad", key = "offroad", icon = "Interface\\Icons\\INV_Boots_05", label = "Off-road shortcuts",
      tip = "Routes cut across open ground where that's faster. Off: they follow the roads.", route = true },
    { id = "quests", key = "layerQuests", icon = ns.Layers and ns.Layers.ICON and ns.Layers.ICON.objective, label = "Quests",
      tip = "Your quests' objectives and turn-ins on the map." },
    { id = "questAreas", key = "layerQuestAreas", icon = ns.Layers and ns.Layers.ICON and ns.Layers.ICON.objective,
      label = "Quest areas", tip = "The quests' areas outlined on the map, like on the minimap.", needs = "layerQuests",
      tint = { 0.45, 0.6, 1 } },
    { id = "herbs", key = "layerHerbs", icon = "Interface\\Icons\\INV_Misc_Herb_07", label = "Herbs", tip = "Herb nodes you know." },
    { id = "ore", key = "layerOre", icon = "Interface\\Icons\\INV_Ore_Copper_01", label = "Ore", tip = "Ore nodes you know." },
    { id = "city", key = "layerCity", icon = "Interface\\Icons\\INV_Helmet_03", label = "City locations",
      tip = "Places guards pointed out to you (trainers, bank, ...), for all your characters.", defaultOn = true },
    { id = "roadTools", icon = "Interface\\Icons\\INV_Misc_Note_02", label = "Road tools", dev = true,
      tip = "Click to turn on, click again when done. On the map: left-drag along a road the routes miss to add it (joined to the roads it meets; where it runs along one, that road stays), right-drag over a road that isn't there to erase it (red), middle-drag to pan. Routes use your changes at once. (Shown with the road tools option, or /agps dev)",
      isOn = function() return G.roadMode end,
      action = function()
        if G.mapMenu then G.mapMenu:Hide() end
        G.ToggleRoadMode()
      end },
    { id = "wallTools", icon = "Interface\\Icons\\Ability_Warrior_ShieldWall", label = "Wall tools", wallDev = true,
      tip = "Click to turn on, click again when done. On the map: left-drag along a wall, fence or cliff edge the routes try to walk through (blood red): routes go around it like a mountain, and roads it crosses are cut there (leave a gap for a gate; flight paths still cross it). Right-drag over walls to erase them (circle an area for all in it), middle-drag to pan. (Shown with the wall tools option)",
      isOn = function() return G.wallMode end,
      action = function()
        if G.mapMenu then G.mapMenu:Hide() end
        G.ToggleWallMode()
      end },
    { id = "roadUndo", icon = "Interface\\Icons\\INV_Misc_PocketWatch_01", label = "Undo", dev = true, wallDev = true,
      tip = "Takes back your last drawn or erased road or wall (until it's in the data). (Shown with the road or wall tools)",
      action = function()
        if G.mapMenu then G.mapMenu:Hide() end
        ns.Record.Undo()
      end },
    { id = "farm", icon = "Interface\\Icons\\INV_Misc_Shovel_01", label = "Draw a farming area",
      tip = "Drag a loop around nodes on the map: the route visits every known node inside that's shown (herbs, ore or both), round and round (the nearest 60 at most). Right-click cancels.",
      action = function()
        G.mapMenu:Hide()
        G.StartDrawing()
      end },
  }
  -- the map styles: one at a time
  for i, sd in ipairs(STYLES) do
    table.insert(QUICK, 2 + i, { id = "style_" .. sd[1], style = sd[1], icon = sd[2], label = sd[3], tip = sd[4] })
  end
  G.QUICK = QUICK
  -- Where each goes: always shown or in the menu, going up or right from the map button,
  -- or hidden. (The defaults fit a 400 map: 2 going right, 9 going up.)
  G.QUICK_PLACES = { "barUp", "barRight", "menuUp", "menuRight", "hidden" }
  G.QUICK_DEFAULT = { search = "menuUp", questRoute = "barRight", hearth = "barRight", offroad = "hidden",
    city = "hidden", styles = "menuUp", gather = "menuUp", questsG = "menuUp", roadTools = "barUp", roadUndo = "barUp", wallTools = "barUp" }
  -- Groups: one button in the bar or menu; clicked, its buttons slide out beside it (to the
  -- right from a column going up, upward from a row going right).
  G.QUICK_GROUPS = {
    { id = "styles", label = "Map style", members = { "style_minimap", "style_zone", "style_nospoiler" },
      tip = "The map's look: click to choose." },
    { id = "questsG", label = "Quests", members = { "quests", "questAreas" }, tip = "Quests and quest areas on the map." },
    { id = "gather", label = "Herbs, ore and farming", members = { "herbs", "ore", "farm" },
      tip = "Herb and ore nodes on the map, and drawing a farming area." },
  }
  G.GROUP_IDLE = 8 -- seconds an opened group stays open with the mouse away
  G.DRAWER_SECONDS = 0.22 -- the menu column slides open and shut like a drawer
  G.QUICK_STEP_BAR, G.QUICK_STEP_MENU = 30, 28

  function G.QuickPlace(id)
    local q = S().quick
    local v = q and q[id]
    if not v and G.groupOf then -- a group: where its first member was put before groups
      local grp = G.groupOf[id]
      if grp then v = q and q[grp.members[1].id] end
    end
    v = v or G.QUICK_DEFAULT[id] or "menuUp"
    -- (an earlier version's "bar" / "menu", with the menu opening one way)
    local right = S().drawerDir == "right"
    if v == "bar" then v = right and "barUp" or "barRight" end
    if v == "menu" then v = right and "menuRight" or "menuUp" end
    return v
  end
  function G.QuickOn(t)
    if t.isOn then return t.isOn() and true or false end
    if t.style then return S().style == t.style end
    if t.action then return true end
    local v = S()[t.key]
    if t.defaultOn then return v ~= false end
    return v and true or false
  end
  -- How many fit: on the bar (up to the middle, clear of Clear Route and the coordinates)
  -- and in the menu column (up to the route panel).
  -- How many fit going up (to below the route panel) and going right (to short of the
  -- bottom middle: Clear Route and the coordinates) at `size` (default: the map as it is).
  function G.QuickCapacity(size)
    local w, h = top:GetWidth(), top:GetHeight()
    if size then w, h = size, size end
    if not w or w < 50 then w, h = S().size or 400, S().size or 400 end -- (not laid out yet)
    local up = math.max(0, math.floor((h - (MAP_BUTTON + 7) - 100) / G.QUICK_STEP_MENU))
    local right = math.max(0, math.floor((w / 2 - 80 - (MAP_BUTTON + 7)) / G.QUICK_STEP_BAR))
    return up, right
  end
  -- How many go up and right, always shown and in the menu together (`change`: { id,
  -- place } to try one).
  function G.QuickCounts(change)
    local up, right = 0, 0
    for _, t in ipairs(G.QuickSlots()) do
      local where = (change and change[1] == t.id) and change[2] or G.QuickPlace(t.id)
      if where == "barUp" or where == "menuUp" then up = up + 1 end
      if where == "barRight" or where == "menuRight" then right = right + 1 end
    end
    return up, right
  end
  function G.QuickFits(change, size)
    local up, right = G.QuickCounts(change)
    local cu, cr = G.QuickCapacity(size)
    return up <= cu and right <= cr
  end
  -- The smallest map size that holds them all (in steps of 10, up to 800).
  function G.QuickMinSize(change)
    for size = 120, 800, 10 do
      if G.QuickFits(change, size) then return size end
    end
    return 800
  end
  -- A map size to use for `v`: not smaller than the quick buttons need (and say why).
  local toldAt = -100
  function G.ClampSize(v, quiet)
    local min = G.QuickMinSize()
    if v < min then
      if not quiet and GetTime() - toldAt > 3 then
        toldAt = GetTime()
        ns.Print(string.format("The map can't be smaller than %d with your quick buttons. Move some to the menu or hide them (Options: Quick buttons) to make it smaller.", min))
      end
      return min
    end
    return v
  end

  for _, t in ipairs(QUICK) do
    if t.key or t.style or t.action then
      local b, icon = RoundButton(26, t.icon)
      t.button, t.iconTex = b, icon
      b:SetScript("OnClick", function(self)
        if t.action then
          t.action()
          if t.isOn and (GameTooltip:GetOwner() == self) then self:GetScript("OnEnter")(self) end
          return
        end
        if t.style then
          S().style = t.style
          if not G.IsMapStyle(t.style) and browse then G.BrowseToTerrain() end
          G.RefreshQuick()
          if G.mapMenu then G.mapMenu.idle = 0 end
          elapsed = 1
          return
        end
        if t.needs and not S()[t.needs] then return end
        S()[t.key] = not G.QuickOn(t)
        if t.key == "offroad" then ns.Nav.OffroadSetByPlayer() end
        if t.route then
          if ns.Teleports then ns.Teleports.Changed() end
          ns.Nav.Invalidate(true, true)
        end
        G.RefreshQuick()
        if G.mapMenu then G.mapMenu.idle = 0 end -- (a click keeps the menu open)
        if ns.Options and ns.Options.Refresh then ns.Options.Refresh() end
        elapsed = 1
        if (GameTooltip:GetOwner() == self) then self:GetScript("OnEnter")(self) end
      end)
      b:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        local on = G.QuickOn(t)
        if t.isOn then
          GameTooltip:SetText(t.label .. ": " .. (on and "|cff40ff40on|r" or "|cff9d9d9doff|r"), 1, 1, 1)
        elseif t.action then
          GameTooltip:SetText(t.label, 1, 1, 1)
        elseif t.style then
          GameTooltip:SetText(t.label .. (on and ": |cff40ff40showing|r" or ""), 1, 1, 1)
        else
          GameTooltip:SetText(t.label .. ": " .. (on and "|cff40ff40on|r" or "|cff9d9d9doff|r"), 1, 1, 1)
        end
        GameTooltip:AddLine(t.tip, nil, nil, nil, true)
        if t.needs and not S()[t.needs] then GameTooltip:AddLine("Turn Quests on first.", 1, 0.5, 0.5) end
        GameTooltip:Show()
      end)
    end
  end

  -- The slots: a button on its own, or a group's one button. G.QuickSlots() in the order
  -- set in the options (gps.quickOrder: slot ids), the rest after in the built-in order.
  local byId, SLOTS, openGroup, groupIdle = {}, {}, nil, 0
  for _, t in ipairs(QUICK) do byId[t.id] = t end
  G.groupOf = {}
  local memberOf = {}
  for _, grp in ipairs(G.QUICK_GROUPS) do
    local slot = { id = grp.id, label = grp.label, tip = grp.tip, members = {}, group = true }
    for _, mid in ipairs(grp.members) do
      local m = byId[mid]
      if m then
        slot.members[#slot.members + 1] = m
        memberOf[mid] = slot
      end
    end
    slot.icon = slot.members[1] and slot.members[1].icon
    local b, icon = RoundButton(26, slot.icon)
    slot.button, slot.iconTex = b, icon
    b:SetScript("OnClick", function() G.ToggleGroup(slot) end)
    b:SetScript("OnEnter", function(self)
      GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
      GameTooltip:SetText(slot.label, 1, 1, 1)
      GameTooltip:AddLine(slot.tip, nil, nil, nil, true)
      local names = {}
      for _, m in ipairs(slot.members) do names[#names + 1] = m.label end
      GameTooltip:AddLine("Click for: " .. table.concat(names, ", "), 0.8, 0.8, 0.8, true)
      GameTooltip:Show()
    end)
    G.groupOf[grp.id] = slot
  end
  for _, t in ipairs(QUICK) do
    local grp = memberOf[t.id]
    if not grp then
      SLOTS[#SLOTS + 1] = t
    elseif not grp.added then
      grp.added = true
      SLOTS[#SLOTS + 1] = grp
    end
  end
  function G.QuickSlots()
    local rank, base = {}, {}
    for i, id in ipairs(S().quickOrder or {}) do rank[id] = i end
    local out = {}
    for i, t in ipairs(SLOTS) do
      -- (the road tools: /agps dev; the wall tools: their option; Undo with either)
      local shown = (not t.dev and not t.wallDev) or (t.dev and S().devTools) or (t.wallDev and S().wallTools)
      if shown then out[#out + 1] = t end
      base[t.id] = i
    end
    -- (the wall tools right above the road tools, and Undo above both)
    local function key(t)
      if t.id == "roadUndo" and base.roadTools then return (rank.roadTools or 1000 + base.roadTools) + 0.7 end
      if t.id == "wallTools" and base.roadTools then return (rank.roadTools or 1000 + base.roadTools) + 0.5 end
      return rank[t.id] or 1000 + base[t.id]
    end
    table.sort(out, function(a, b) return key(a) < key(b) end)
    return out
  end
  -- Move a slot `delta` places in the order (the options' ^ / v).
  function G.MoveSlot(id, delta)
    local ids = {}
    for i, t in ipairs(G.QuickSlots()) do ids[i] = t.id end
    for i, sid in ipairs(ids) do
      if sid == id then
        local j = i + delta
        if j >= 1 and j <= #ids then ids[i], ids[j] = ids[j], ids[i] end
        break
      end
    end
    S().quickOrder = ids
    G.LayoutQuick()
  end

  -- A group's buttons out beside its button (or back in).
  local function PlaceGroup()
    if openGroup and not openGroup.button:IsShown() then openGroup = nil end
    for _, grp in pairs(G.groupOf) do
      local open = grp == openGroup
      local up = grp.where == "barUp" or grp.where == "menuUp"
      for j, m in ipairs(grp.members) do
        m.button:ClearAllPoints()
        if open then
          if up then
            m.button:SetPoint("LEFT", grp.button, "RIGHT", 4 + (j - 1) * G.QUICK_STEP_BAR, 0)
          else
            m.button:SetPoint("BOTTOM", grp.button, "TOP", 0, 4 + (j - 1) * G.QUICK_STEP_MENU)
          end
          m.button:SetAlpha(1)
          m.button:SetFrameLevel(grp.button:GetFrameLevel() + 2)
          m.button:Show()
        else
          m.button:Hide()
        end
      end
    end
  end
  function G.ToggleGroup(slot)
    openGroup = openGroup ~= slot and slot or nil
    groupIdle = 0
    if G.mapMenu then G.mapMenu.idle = 0 end
    PlaceGroup()
  end
  local groupDriver = CreateFrame("Frame", nil, top)
  groupDriver:SetScript("OnUpdate", function(_, dt)
    if not openGroup then return end
    local over = openGroup.button:IsMouseOver()
    for _, m in ipairs(openGroup.members) do over = over or (m.button:IsShown() and m.button:IsMouseOver()) end
    groupIdle = over and 0 or groupIdle + dt
    if over and G.mapMenu then G.mapMenu.idle = 0 end
    if groupIdle >= G.GROUP_IDLE or not openGroup.button:IsShown() then
      openGroup = nil
      PlaceGroup()
    end
  end)

  -- on/off look of the toggles (a group's: its active map style, or lit when any is on)
  function G.RefreshQuick()
    for _, t in ipairs(QUICK) do
      if t.iconTex then
        local on = G.QuickOn(t) and (not t.needs or S()[t.needs])
        t.iconTex:SetDesaturated(not on)
        t.iconTex:SetAlpha(on and 1 or 0.45)
        if t.tint and on then t.iconTex:SetVertexColor(t.tint[1], t.tint[2], t.tint[3]) else t.iconTex:SetVertexColor(1, 1, 1) end
      end
    end
    for _, grp in pairs(G.groupOf or {}) do
      local any, icon = false, grp.icon
      for _, m in ipairs(grp.members) do
        if m.style then
          if G.QuickOn(m) then icon, any = m.icon, true end
        elseif m.key and G.QuickOn(m) and (not m.needs or S()[m.needs]) then
          any = true
        end
      end
      ns.SetIcon(grp.iconTex, icon, "Interface\\Icons\\INV_Misc_QuestionMark")
      grp.iconTex:SetDesaturated(not any)
      grp.iconTex:SetAlpha(any and 1 or 0.6)
    end
  end

  -- The menu column opens like a drawer: the buttons slide up out of the map button (and
  -- fade in), and back into it when it closes. drawer: 0 shut .. 1 open.
  local drawer, drawerTarget, colList = 0, 0, {}
  local menuUp, menuRight, pinnedUp, pinnedRight = {}, {}, 0, 0
  local function PlaceColumn()
    local e = drawer * drawer * (3 - 2 * drawer) -- eased
    local function place(list, pinned, up)
      for j, b in ipairs(list) do
        if drawer <= 0 then
          b:Hide()
        else
          local k = pinned + (j - 1) * e -- slides out from just past the always-shown ones
          b:ClearAllPoints()
          if up then
            b:SetPoint("BOTTOM", mapButton, "TOP", 0, 4 + k * G.QUICK_STEP_MENU)
          else
            b:SetPoint("LEFT", mapButton, "RIGHT", 4 + k * G.QUICK_STEP_BAR, 0)
          end
          b:SetAlpha(math.min(1, e * 1.5))
          b:Show()
        end
      end
    end
    place(menuUp, pinnedUp, true)
    place(menuRight, pinnedRight, false)
  end
  local driver = CreateFrame("Frame", nil, top)
  driver:SetScript("OnUpdate", function(_, dt)
    if drawer == drawerTarget then return end
    local step = dt / G.DRAWER_SECONDS
    if drawerTarget > drawer then drawer = math.min(drawerTarget, drawer + step) else drawer = math.max(drawerTarget, drawer - step) end
    PlaceColumn()
  end)

  -- Place the buttons: the bar, and the column (the drawer) while the menu is open.
  function G.LayoutQuick()
    local capUp, capRight = G.QuickCapacity()
    local lists = { barUp = {}, barRight = {}, menuUp = {}, menuRight = {} }
    for _, t in ipairs(QUICK) do t.button:Hide() end
    for _, t in ipairs(G.QuickSlots()) do
      local where = G.QuickPlace(t.id)
      t.where = where
      if lists[where] then lists[where][#lists[where] + 1] = t end
      t.button:Hide()
    end
    -- always shown first (next to the map button); what doesn't fit isn't shown
    local function pin(list, up, cap)
      local n = 0
      for i, t in ipairs(list) do
        if i <= cap then
          t.button:ClearAllPoints()
          if up then
            t.button:SetPoint("BOTTOM", mapButton, "TOP", 0, 4 + (i - 1) * G.QUICK_STEP_MENU)
          else
            t.button:SetPoint("LEFT", mapButton, "RIGHT", 4 + (i - 1) * G.QUICK_STEP_BAR, 0)
          end
          t.button:SetAlpha(1)
          t.button:Show()
          n = i
        end
      end
      return n
    end
    pinnedUp = pin(lists.barUp, true, capUp)
    pinnedRight = pin(lists.barRight, false, capRight)
    menuUp, menuRight, colList = {}, {}, {}
    for i, t in ipairs(lists.menuUp) do
      if pinnedUp + i <= capUp then menuUp[#menuUp + 1] = t.button colList[#colList + 1] = t.button end
    end
    for i, t in ipairs(lists.menuRight) do
      if pinnedRight + i <= capRight then menuRight[#menuRight + 1] = t.button colList[#colList + 1] = t.button end
    end
    drawerTarget = menu:IsShown() and 1 or 0
    PlaceColumn()
    PlaceGroup()
    -- the search box: upward from the bar, to the right from the column
    panel:ClearAllPoints()
    local across = QUICK[1].where == "barRight" or QUICK[1].where == "menuRight" -- going right: open above
    if across then
      panel:SetPoint("BOTTOMLEFT", search, "TOPLEFT", 0, 4)
    else
      panel:SetPoint("BOTTOMLEFT", search, "BOTTOMRIGHT", 6, 0)
    end
    if not search:IsShown() then panel:Hide() end
    G.RefreshQuick()
  end
  function G.QuickMouseOver()
    if drawer <= 0 then return false end
    for _, b in ipairs(colList) do
      if b:IsShown() and b:IsMouseOver() then return true end
    end
    for _, m in ipairs(openGroup and openGroup.members or {}) do
      if m.button:IsShown() and m.button:IsMouseOver() then return true end
    end
    return false
  end
  menu:HookScript("OnShow", G.LayoutQuick)
  menu:HookScript("OnHide", G.LayoutQuick)
  top:HookScript("OnSizeChanged", G.LayoutQuick)
  G.RefreshHearthButton = G.LayoutQuick -- (ApplySettings calls this)
  G.RefreshTray = G.RefreshQuick
  G.LayoutQuick()

  -- Free look: crosshair and Route Here.
  crossH = lineLayer:CreateTexture(nil, "OVERLAY", nil, 6)
  crossH:SetColorTexture(1, 1, 1, 0.85)
  crossH:SetSize(18, 2)
  crossH:SetPoint("CENTER")
  crossV = lineLayer:CreateTexture(nil, "OVERLAY", nil, 6)
  crossV:SetColorTexture(1, 1, 1, 0.85)
  crossV:SetSize(2, 18)
  crossV:SetPoint("CENTER")
  routeBtn = CreateFrame("Button", nil, top, "UIPanelButtonTemplate")
  routeBtn:SetSize(128, 22)
  routeBtn:SetPoint("BOTTOM", 0, 22)
  routeBtn:SetText("Confirm Route")
  routeBtn:SetScript("OnClick", function()
    if #ns.Nav.stops > 0 then
      ns.Nav.Clear()
      elapsed = 1
    else
      G.ConfirmRoute()
    end
  end)
  routeBtn:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    if #ns.Nav.stops > 0 then
      GameTooltip:SetText("Clear Route", 1, 1, 1)
      GameTooltip:AddLine("Removes the route and all its stops. To add a stop instead, double-click the map; right-click a stop's marker to remove just that one.", nil, nil, nil, true)
    else
      GameTooltip:SetText("Confirm Route", 1, 1, 1)
      GameTooltip:AddLine("Routes to the crosshair, or through the stops you double-clicked (each gets its own marker). With stops placed, the route also starts by itself after 5 seconds without touching the map.", nil, nil, nil, true)
    end
    GameTooltip:Show()
  end)
  routeBtn:SetScript("OnLeave", GameTooltip_Hide)

  -- Navigation panel (top): distance and ETAs; click the X to cancel the route.
  navPanel = CreateFrame("Frame", nil, top, "BackdropTemplate")
  navPanel:SetPoint("TOPLEFT", 4, -4)
  navPanel:SetPoint("TOPRIGHT", -4, -4)
  navPanel:SetHeight(36)
  navPanel:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8" })
  navPanel:SetBackdropColor(0, 0, 0, 0.7)
  navText = navPanel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  navText:SetPoint("TOPLEFT", 6, -6)
  navText:SetPoint("TOPRIGHT", -40, -6)
  navText:SetJustifyH("LEFT")
  -- The route's steps (several stops, zeppelins, boats): the first three, then "... more".
  stepsText = navPanel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  stepsText:SetPoint("TOPLEFT", navText, "BOTTOMLEFT", 0, -4)
  stepsText:SetPoint("RIGHT", -6, 0)
  stepsText:SetJustifyH("LEFT")
  stepsText:SetSpacing(2)
  local cancel = CreateFrame("Button", nil, navPanel, "UIPanelCloseButton")
  cancel:SetSize(22, 22)
  cancel:SetPoint("TOPRIGHT", 0, -1)
  -- X: closes this panel, the route goes on (option: clears the route instead)
  cancel:SetScript("OnClick", function()
    if S().navCloseClears then
      ns.Nav.Clear()
    else
      navClosedAt = ns.Nav.Version()
    end
    elapsed = 1
  end)
  cancel:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    if S().navCloseClears then
      GameTooltip:SetText("Cancel the route", 1, 1, 1)
    else
      GameTooltip:SetText("Close", 1, 1, 1)
      GameTooltip:AddLine("Hides this panel; the route goes on. It comes back when the route changes. To cancel the route: Clear Route, or /agps clear.", nil, nil, nil, true)
    end
    GameTooltip:Show()
  end)
  cancel:SetScript("OnLeave", GameTooltip_Hide)
  -- collapse / expand the steps: "-" hides them (then "+" brings them back), and "+" beside
  -- it shows all of them, not just the next few
  -- (drawn here: small gold-edged boxes, not game art that may be missing)
  local function SmallBox(anchor, text)
    local b = CreateFrame("Button", nil, navPanel)
    b:SetSize(16, 16)
    b:SetPoint("RIGHT", anchor, "LEFT", -2, 0)
    local edge = b:CreateTexture(nil, "BACKGROUND")
    edge:SetAllPoints()
    edge:SetColorTexture(1, 0.82, 0, 0.6)
    local fill = b:CreateTexture(nil, "BORDER")
    fill:SetPoint("TOPLEFT", 1, -1)
    fill:SetPoint("BOTTOMRIGHT", -1, 1)
    fill:SetColorTexture(0.12, 0.07, 0.03, 1)
    local hover = b:CreateTexture(nil, "HIGHLIGHT")
    hover:SetAllPoints(fill)
    hover:SetColorTexture(1, 1, 1, 0.15)
    b.label = b:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    b.label:SetPoint("CENTER", 0, 1)
    b.label:SetText(text)
    b:SetScript("OnLeave", GameTooltip_Hide)
    b:Hide()
    return b
  end
  local toggle = SmallBox(cancel, "-")
  toggle:SetScript("OnClick", function()
    local st = S()
    if st.stepsCollapsed then st.stepsCollapsed = false -- "+": back to the next few
    elseif st.stepsAll then st.stepsAll = false -- all of them: back to the next few
    else st.stepsCollapsed = true end
    elapsed = 1
  end)
  toggle:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    local st = S()
    GameTooltip:SetText(st.stepsCollapsed and "Show the steps" or st.stepsAll and "Show fewer steps" or "Hide the steps", 1, 1, 1)
    GameTooltip:Show()
  end)
  G.stepsToggle = toggle
  local more = SmallBox(toggle, "+")
  more:SetScript("OnClick", function()
    S().stepsAll, S().stepsCollapsed = true, false
    elapsed = 1
  end)
  more:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText("Show all the steps", 1, 1, 1)
    GameTooltip:Show()
  end)
  G.stepsMore = more
  navPanel:Hide()

  northLabel = top:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  northLabel:SetText("N")
  northLabel:SetTextColor(1, 0.3, 0.3)

  infoText = top:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  infoText:SetPoint("BOTTOM", 0, 4)
  infoText:SetShadowOffset(1, -1)

  noMapText = top:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  noMapText:SetPoint("CENTER")

  -- Hidden (closed, a key, combat) with stops placed but not confirmed yet: they become the
  -- route now (the 5 s auto-confirm runs only while the map shows), so the direction arrow
  -- leads there in the background. Placing ends; the map follows the player again.
  frame:HookScript("OnHide", function()
    if #pending > 0 then
      local stops = {}
      for _, d in ipairs(ns.Nav.stops) do stops[#stops + 1] = d end
      for _, d in ipairs(pending) do stops[#stops + 1] = d end
      ns.Nav.SetStops(stops, S().fastestOrder)
    end
    -- (option) with a route, a map looked around in reopens following the player too
    local reopenFollow = S().reopenFollow and ns.Nav.dest and (free or browse)
    if #pending > 0 or G.appended or tour or reopenFollow then G.Follow() end
  end)

  frame:SetScript("OnUpdate", function(_, dt)
    if tour then
      -- (an error in the tour ends it, rather than failing every frame)
      local ok, err = pcall(TourStep, GetTime())
      if not ok then
        tour = nil
        G.lastError = tostring(err)
        G.Follow()
      end
    end
    -- background terrain searches for the route: ~1 ms a frame
    if G.PumpSearches() then elapsed = 1 end
    G.UpdateApproach(dt)
    local ft = ns.PerfStart()
    G.AreaTooltip(dt)
    G.UpdateFade(dt)
    ns.PerfEnd("every frame: fade, tooltip", ft)
    infoWait = infoWait - dt
    if infoWait <= 0 then
      infoWait = 0.1
      G.UpdateInfo()
    end
    if #pending > 0 or G.appended then
      local mx, my = GetCursorPosition()
      if (mx ~= G.lastMouseX or my ~= G.lastMouseY) and frame:IsMouseOver() then lastActivity = GetTime() end
      G.lastMouseX, G.lastMouseY = mx, my
      if not drag and GetTime() - lastActivity >= AUTO_CONFIRM then
        if #pending > 0 then
          G.ConfirmRoute()
        else
          -- stops added to the route: show the whole route, then follow the player again
          G.appended = false
          local px, py, cont = Geo.PlayerWorld()
          if px and ns.Nav.dest and free then StartTour(px, py, cont, ViewCont(cont), true) else G.Follow() end
        end
      end
    end
    local okH, errH = pcall(G.UpdateZoneHover)
    if not okH then G.LogError("zone hover", errH) end
    local okE, errE = pcall(G.PumpEdges) -- (the walls' outline, worked out in the background)
    if not okE then G.LogError("wall outline", errE) end
    if G.lasso then -- drawing a farming area: add the cursor's spot as it moves
      local mx, my = GetCursorPosition()
      local sc = canvas:GetEffectiveScale()
      local ccx, ccy = canvas:GetCenter()
      local dx, dy = mx / sc - ccx, my / sc - ccy
      local l = G.lasso
      if not l.sx or (dx - l.sx) ^ 2 + (dy - l.sy) ^ 2 >= 36 then
        local x, y = G.ScreenToWorld(view.x, view.y, dx, dy, view.rot, view.s)
        l.pts[#l.pts + 1], l.pts[#l.pts + 2] = x, y
        l.sx, l.sy = dx, dy
        elapsed = 1
      end
    end
    if drag then
      local mx, my = GetCursorPosition()
      local sc = frame:GetEffectiveScale()
      local dx, dy = (mx - drag.cx) / sc, (my - drag.cy) / sc
      if drag.moved or dx * dx + dy * dy > 9 then -- ignore clicks and tiny jitters
        drag.moved = true
        local x, y = G.PanCenter(drag.x, drag.y, dx, dy, drag.rot, drag.s)
        free = { x = x, y = y, rot = drag.rot, cross = true, cont = view.cont, interior = free and free.interior }
        recenter:Show()
        elapsed = 1 -- redraw this frame
      end
    end
    local forced = elapsed >= 1 -- G.Redraw / settings / dragging / tour set elapsed = 1
    elapsed = elapsed + dt
    if elapsed < 1 / S().hz then return end
    elapsed = 0
    -- Nothing changed (standing still, same view, same route): skip, but still redraw at
    -- least every REDRAW_IDLE seconds (ETAs, timers, refreshed layers).
    local now = GetTime()
    if not ViewChanged() and not forced and now - lastFull < REDRAW_IDLE then return end
    lastFull = now
    local t0 = ns.PerfStart()
    local ok, err = pcall(G.Update)
    ns.PerfEnd("redraw", t0)
    if not ok then G.LogError("redraw", err) end
  end)
  G.ApplySettings()
  -- a /reload keeps the view where it was panned to (saved as the UI goes)
  local saver = CreateFrame("Frame")
  saver:RegisterEvent("PLAYER_LOGOUT")
  saver:SetScript("OnEvent", function() ns.db.mapView = G.SaveView() end)
  G.RestoreView(ns.db.mapView)
  ns.db.mapView = nil
end

G.VIEW_KEEP = 600 -- seconds: a saved view older than this (a later login) isn't restored

-- Zone level ranges (the classic zones) when the game doesn't say (C_Map.GetMapLevels).
G.ZONE_LEVELS = {
  ["Elwynn Forest"] = { 1, 10 }, ["Dun Morogh"] = { 1, 10 }, ["Tirisfal Glades"] = { 1, 10 },
  ["Durotar"] = { 1, 10 }, ["Mulgore"] = { 1, 10 }, ["Teldrassil"] = { 1, 10 },
  ["Westfall"] = { 10, 20 }, ["Loch Modan"] = { 10, 20 }, ["Silverpine Forest"] = { 10, 20 },
  ["Darkshore"] = { 10, 20 }, ["The Barrens"] = { 10, 25 }, ["Redridge Mountains"] = { 15, 25 },
  ["Stonetalon Mountains"] = { 15, 27 }, ["Ashenvale"] = { 18, 30 }, ["Duskwood"] = { 18, 30 },
  ["Wetlands"] = { 20, 30 }, ["Hillsbrad Foothills"] = { 20, 30 }, ["Thousand Needles"] = { 25, 35 },
  ["Alterac Mountains"] = { 30, 40 }, ["Arathi Highlands"] = { 30, 40 }, ["Desolace"] = { 30, 40 },
  ["Stranglethorn Vale"] = { 30, 45 }, ["Dustwallow Marsh"] = { 35, 45 }, ["Badlands"] = { 35, 45 },
  ["Swamp of Sorrows"] = { 35, 45 }, ["Feralas"] = { 40, 50 }, ["The Hinterlands"] = { 40, 50 },
  ["Tanaris"] = { 40, 50 }, ["Searing Gorge"] = { 43, 50 }, ["Azshara"] = { 45, 55 },
  ["Blasted Lands"] = { 45, 55 }, ["Un'Goro Crater"] = { 48, 55 }, ["Felwood"] = { 48, 55 },
  ["Burning Steppes"] = { 50, 58 }, ["Western Plaguelands"] = { 51, 58 }, ["Eastern Plaguelands"] = { 53, 60 },
  ["Winterspring"] = { 55, 60 }, ["Deadwind Pass"] = { 55, 60 }, ["Moonglade"] = { 55, 60 },
  ["Silithus"] = { 55, 60 },
}

-- A zone's levels: min, max (nil if unknown).
function G.ZoneLevels(id, name)
  if C_Map and C_Map.GetMapLevels then
    local ok, lo, hi = pcall(C_Map.GetMapLevels, id)
    if ok and lo and hi and lo > 0 and hi > 0 then return lo, hi end
  end
  local l = name and G.ZONE_LEVELS[name]
  if l then return l[1], l[2] end
end

-- The zone's name and levels for the hover: name, "Level 10-20" (or nil), color (by the
-- player's level: red far below it, orange below, yellow in it, green above, gray far above).
function G.ZoneHoverText(id, name, playerLevel)
  local lo, hi = G.ZoneLevels(id, name)
  if not lo then return name end
  local pl = playerLevel or 1
  local r, g, b
  if pl < lo - 4 then r, g, b = 1, 0.1, 0.1
  elseif pl < lo then r, g, b = 1, 0.5, 0.25
  elseif pl <= hi then r, g, b = 1, 1, 0
  elseif pl <= hi + 5 then r, g, b = 0.25, 0.75, 0.25
  else r, g, b = 0.6, 0.6, 0.6 end
  return name, lo == hi and ("Level " .. lo) or ("Level " .. lo .. "-" .. hi), r, g, b
end

-- On a continent's map: the zone under the mouse, and its levels, as text beside the cursor.
local hoverZone, hoverAt = nil, 0
function G.UpdateZoneHover()
  local label = G.zoneLabel
  if not label then return end
  local m = browse and ns.Maps and ns.Maps[browse]
  local over = m and m.type == 2 and frame:IsMouseOver() and not drag and not G.lasso
  if not over then
    if hoverZone then label:Hide() end
    hoverZone = nil
    return
  end
  local mx, my = GetCursorPosition()
  local sc = canvas:GetEffectiveScale()
  local ccx, ccy = canvas:GetCenter()
  local dx, dy = mx / sc - ccx, my / sc - ccy
  label:ClearAllPoints()
  label:SetPoint("BOTTOMLEFT", canvas, "CENTER", dx + 16, dy + 2)
  local now = GetTime()
  if now - hoverAt < 0.1 then return end
  hoverAt = now
  local x, y = G.ScreenToWorld(view.x, view.y, dx, dy, view.rot, view.s)
  local id, name
  local b = browseBounds
  if b and C_Map and C_Map.GetMapInfoAtPosition then
    local ok, info = pcall(C_Map.GetMapInfoAtPosition, browse, (b[4] - y) / (b[4] - b[2]), (b[3] - x) / (b[3] - b[1]))
    if ok and info and info.mapType == 3 then id, name = info.mapID, info.name end
  end
  if not id then id, name = G.LocateWorld(browseCont or m.continent, x, y) end
  if id == hoverZone then return end
  hoverZone = id
  if not id then
    label:Hide()
    return
  end
  local zn, lv, r, g, bl = G.ZoneHoverText(id, name, UnitLevel and UnitLevel("player"))
  label:SetText(lv and string.format("%s\n|cff%02x%02x%02x%s|r", zn, math.floor(r * 255), math.floor(g * 255), math.floor(bl * 255), lv) or zn)
  label:Show()
end

-- The panned view (nil while following the player), to come back to after a /reload.
function G.SaveView()
  if not free then return nil end
  return { x = free.x, y = free.y, rot = free.rot, cross = free.cross, cont = free.cont,
    browse = browse, browseZoom = browseZoom, browseCont = browseCont, fromTerrain = fromTerrain,
    who = UnitGUID and UnitGUID("player"), t = time() }
end

function G.RestoreView(v)
  if not (v and v.x and v.y) then return end
  if v.who ~= (UnitGUID and UnitGUID("player")) or not v.t or math.abs(time() - v.t) > G.VIEW_KEEP then return end
  if v.browse and ns.Maps and ns.Maps[v.browse] then
    G.Browse(v.browse, v.browseCont)
    browseZoom = v.browseZoom or browseZoom
    fromTerrain = v.fromTerrain
  else
    browse, browseZoom, browseCont, browseBounds = nil, nil, nil, nil
  end
  free = { x = v.x, y = v.y, rot = v.rot or 0, cross = v.cross, cont = v.cont }
  if recenter then recenter:Show() end
  elapsed = 1
end

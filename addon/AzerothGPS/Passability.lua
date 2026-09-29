-- Terrain passability for offroad routing (data: Data/Terrain.lua).
-- Cells are 0 open, 1 water (swimmable, slower), 2 blocked (too steep / off the map).
local _, ns = ...

local P = {}
ns.Passability = P

P.SWIM_COST = 1.5 -- swimming is about 2/3 of run speed
local TILE = 1600 / 3
local QUADS = 128 -- terrain quads per tile edge

local ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
local INDEX = {}
for i = 1, #ALPHABET do INDEX[ALPHABET:byte(i)] = i - 1 end
local SHORT = 21

local cache = {} -- [grid][row] = { end1, v1, end2, v2, ... }

-- Decode one run-length encoded row (see encode_row in app/azerothgps/roads/terrain.py;
-- `short`: the longest short run, SHORT unless the grid says (a cave's: 15); `long`: the
-- digits of a long run's length, 3 unless the grid says (a cave's: 2)).
local function DecodeRow(text, short, long)
  short = short or SHORT
  local runs, pos, i, n = {}, 0, 1, #text
  while i <= n do
    local b = text:byte(i)
    local v, len
    if b == 95 then -- "_": long run
      v = text:byte(i + 1) - 48
      if long == 2 then
        len = INDEX[text:byte(i + 2)] * 64 + INDEX[text:byte(i + 3)]
        i = i + 4
      else
        len = INDEX[text:byte(i + 2)] * 4096 + INDEX[text:byte(i + 3)] * 64 + INDEX[text:byte(i + 4)]
        i = i + 5
      end
    else
      local k = INDEX[b]
      v = math.floor(k / short)
      len = k % short + 1
      i = i + 1
    end
    pos = pos + len
    runs[#runs + 1] = pos
    runs[#runs + 1] = v
  end
  return runs
end
P.DecodeRow = DecodeRow

-- A grid's rows: a list, or one string of them split by "/" (a cave's), split the first time.
local function Rows(g)
  local rows = g.rows
  if type(rows) == "string" then
    local list = {}
    for r in rows:gmatch("[^/]+") do list[#list + 1] = r end
    g.rows = list
    rows = list
  end
  return rows
end
P.Rows = Rows

-- Walls drawn with the road tools (Shift+left-drag) or shipped (ns.Walls): what a player
-- can't walk through (a town's wall, a fence), like a mountain. Their cells on each grid are
-- closed (wallCells[grid][row * 65536 + col]) and legs crossing them blocked (P.CrossesWall).
-- Built again when the drawn ones change (P.RefreshWalls: Record.Changed).
local wallCells, wallSegs, wallsBuilt = {}, {}, false
-- Blocked ground a wall eraser went over (a mountain's edge the grid has wrong): open
-- (openCells[grid][row * 65536 + col]). Drawn walls still close their cells.
local openCells = {}
P.OPEN_YD = 6 -- an erase stroke opens the blocked ground this close to it
P.WALL_UNDER_YD = 12 -- an erase stroke takes out the walls this close to it
P.WALL_BUCKET = 64

-- Cell value at (row, col) of grid g (2 outside the grid, and on a wall).
local function Cell(g, row, col)
  if row < 1 or row > g.h or col < 1 or col > g.w then return 2 end
  local wc = wallCells[g]
  if wc and wc[row * 65536 + col] then return 2 end
  local oc = openCells[g]
  if oc and oc[row * 65536 + col] then return 0 end
  local rc = cache[g]
  if not rc then
    rc = {}
    cache[g] = rc
  end
  local runs = rc[row]
  if not runs then
    runs = DecodeRow(Rows(g)[row], g.short, g.long)
    rc[row] = runs
  end
  -- binary search for the run containing col
  local lo, hi = 1, #runs / 2
  while lo < hi do
    local mid = math.floor((lo + hi) / 2)
    if runs[mid * 2 - 1] < col then lo = mid + 1 else hi = mid end
  end
  return runs[lo * 2]
end

-- Grid cell (col, row) of world (x, y), and a cell's center back in world coordinates.
local function ToCell(g, x, y)
  local k = TILE / g.cell
  return math.floor(((32 - y / TILE) - g.tx0) * k) + 1, math.floor(((32 - x / TILE) - g.ty0) * k) + 1
end

local function CellCentre(g, col, row)
  local k = TILE / g.cell
  return (32 - g.ty0 - (row - 0.5) / k) * TILE, (32 - g.tx0 - (col - 0.5) / k) * TILE
end

local function InLoop(poly, x, y)
  local inside, n = false, #poly / 2
  local jx, jy = poly[2 * n - 1], poly[2 * n]
  for i = 1, n do
    local ix, iy = poly[2 * i - 1], poly[2 * i]
    if (iy > y) ~= (jy > y) and x < (jx - ix) * (y - iy) / (jy - iy) + ix then inside = not inside end
    jx, jy = ix, iy
  end
  return inside
end

local function NearLine(line, x, y, r)
  local r2 = r * r
  for k = 1, #line - 3, 2 do
    local ax, ay, bx, by = line[k], line[k + 1], line[k + 2], line[k + 3]
    local vx, vy = bx - ax, by - ay
    local L2 = vx * vx + vy * vy
    local t = L2 > 0 and math.max(0, math.min(1, ((x - ax) * vx + (y - ay) * vy) / L2)) or 0
    if (ax + vx * t - x) ^ 2 + (ay + vy * t - y) ^ 2 <= r2 then return true end
  end
  return false
end

-- The walls on `cont`: the shipped ones, then the player's drawn ones in order (an erase
-- stroke, "unwall", takes out the walls near it, or inside it when drawn as a loop). Each a
-- flat point list.
function P.WallLines(cont)
  local out = {}
  for _, w in ipairs(ns.Walls and ns.Walls[cont] or {}) do out[#out + 1] = w end
  local shipped = ns.RoadTracksIn or {}
  for _, t in ipairs(ns.db and ns.db.tracks or {}) do
    if t.continent == cont and t.pts and #t.pts >= 4 and not shipped[t.time or -1] then
      if t.op == "wall" then
        out[#out + 1] = t.pts
      elseif t.op == "unwall" then
        local kept = {}
        for _, w in ipairs(out) do
          local under = false
          for i = 1, #w - 1, 2 do
            local x, y = w[i], w[i + 1]
            if (t.area and InLoop(t.pts, x, y)) or (not t.area and NearLine(t.pts, x, y, P.WALL_UNDER_YD)) then
              under = true
              break
            end
          end
          if not under then kept[#kept + 1] = w end
        end
        out = kept
      end
    end
  end
  return out
end

-- The wall erasers on `cont` (they open blocked ground too): shipped (ns.WallOpens) and the
-- player's not yet in the data. { { pts, area }, ... }
function P.OpenAreas(cont)
  local out = {}
  for _, o in ipairs(ns.WallOpens and ns.WallOpens[cont] or {}) do out[#out + 1] = o end
  local shipped = ns.RoadTracksIn or {}
  for _, t in ipairs(ns.db and ns.db.tracks or {}) do
    if t.continent == cont and t.op == "unwall" and t.pts and #t.pts >= 4 and not shipped[t.time or -1] then
      out[#out + 1] = { pts = t.pts, area = t.area }
    end
  end
  return out
end

-- Every continent (and city level) with walls or wall erasers, shipped or drawn.
local function WallConts()
  local set = {}
  for c in pairs(ns.Walls or {}) do set[c] = true end
  for c in pairs(ns.WallOpens or {}) do set[c] = true end
  for _, t in ipairs(ns.db and ns.db.tracks or {}) do
    if t.op == "wall" or t.op == "unwall" then set[t.continent] = true end
  end
  return set
end

-- A continent's wall cells, segments and opened cells from these walls and wall erasers.
local function WallGrid(g, lines, opens)
  local cells, segs, open = {}, {}, {}
  local B = P.WALL_BUCKET
  for _, w in ipairs(lines) do
    for k = 1, #w - 3, 2 do
      local ax, ay, bx, by = w[k], w[k + 1], w[k + 2], w[k + 3]
      -- its cells, every third of a cell along it (so none it crosses is skipped)
      if g then
        local len = math.sqrt((bx - ax) ^ 2 + (by - ay) ^ 2)
        local n = math.max(1, math.ceil(len / (g.cell / 3)))
        for i = 0, n do
          local c, r = ToCell(g, ax + (bx - ax) * i / n, ay + (by - ay) * i / n)
          cells[r * 65536 + c] = true
        end
      end
      local seg = { ax, ay, bx, by }
      for kx = math.floor(math.min(ax, bx) / B), math.floor(math.max(ax, bx) / B) do
        for ky = math.floor(math.min(ay, by) / B), math.floor(math.max(ay, by) / B) do
          local key = kx * 65536 + ky
          segs[key] = segs[key] or {}
          local list = segs[key]
          list[#list + 1] = seg
        end
      end
    end
  end
  -- the ground the erasers went over: open (inside a loop; along a stroke, OPEN_YD either side)
  if g then
    for _, o in ipairs(opens) do
      local pts = o.pts
      local x0, x1, y0, y1 = math.huge, -math.huge, math.huge, -math.huge
      for i = 1, #pts - 1, 2 do
        x0, x1 = math.min(x0, pts[i]), math.max(x1, pts[i])
        y0, y1 = math.min(y0, pts[i + 1]), math.max(y1, pts[i + 1])
      end
      local pad = o.area and 0 or P.OPEN_YD + g.cell
      local cA, rA = ToCell(g, x1 + pad, y1 + pad)
      local cB, rB = ToCell(g, x0 - pad, y0 - pad)
      for r = math.min(rA, rB), math.max(rA, rB) do
        for c = math.min(cA, cB), math.max(cA, cB) do
          local x, y = CellCentre(g, c, r)
          if (o.area and InLoop(pts, x, y)) or (not o.area and NearLine(pts, x, y, P.OPEN_YD + g.cell / 2)) then
            open[r * 65536 + c] = true
          end
        end
      end
    end
  end
  return cells, segs, open
end

-- Whether the player has walls or wall erasers on `cont` not in the data yet.
local function Drawn(cont)
  local shipped = ns.RoadTracksIn or {}
  for _, t in ipairs(ns.db and ns.db.tracks or {}) do
    if t.continent == cont and (t.op == "wall" or t.op == "unwall") and not shipped[t.time or -1] then return true end
  end
  return false
end

local hpaBlocks, hpaDirty = {}, {} -- (the search by blocks, below: blocks decoded, and those worked out here)

-- Build the walls' cells and segments again (after drawing or erasing one).
function P.RefreshWalls()
  wallCells, wallSegs, openCells = {}, {}, {}
  wallsBuilt = true
  hpaBlocks, hpaDirty = {}, {}
  for cont in pairs(WallConts()) do
    local g = ns.Terrain and ns.Terrain[cont]
    local cells, segs, open = WallGrid(g, P.WallLines(cont), P.OpenAreas(cont))
    if g then wallCells[g] = cells end
    wallSegs[cont] = segs
    if g and next(open) then openCells[g] = open end
    -- (the player's own, not in the data yet: the blocks they change, and their neighbors,
    -- are worked out here; the prepared ones have the shipped walls)
    local H = g and ns.TerrainHPA and ns.TerrainHPA[cont]
    if H and Drawn(cont) then
      local sc, _, so = WallGrid(g, ns.Walls and ns.Walls[cont] or {}, ns.WallOpens and ns.WallOpens[cont] or {})
      local d = {}
      local function mark(key)
        local r, c = math.floor(key / 65536), key % 65536
        local br, bc = math.floor((r - 1) / H.K), math.floor((c - 1) / H.K)
        for _, o in ipairs({ { 0, 0 }, { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }) do
          local nr, nc = br + o[1], bc + o[2]
          if nr >= 0 and nr < H.ny and nc >= 0 and nc < H.nx then d[nr * H.nx + nc] = true end
        end
      end
      for k in pairs(cells) do if not sc[k] then mark(k) end end
      for k in pairs(sc) do if not cells[k] then mark(k) end end
      for k in pairs(open) do if not so[k] then mark(k) end end
      for k in pairs(so) do if not open[k] then mark(k) end end
      if next(d) then hpaDirty[cont] = d end
    end
  end
end
local function EnsureWalls() if not wallsBuilt then P.RefreshWalls() end end

local function Orient(ax, ay, bx, by, cx, cy)
  local v = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
  return v > 1e-9 and 1 or v < -1e-9 and -1 or 0
end

-- Where along the leg (x1, y1)-(x2, y2) it first meets a wall: 0..1, or nil.
function P.WallHit(cont, x1, y1, x2, y2)
  EnsureWalls()
  local segs = wallSegs[cont]
  if not segs then return nil end
  local B = P.WALL_BUCKET
  local best
  local seen = {}
  local dx, dy = x2 - x1, y2 - y1
  for kx = math.floor(math.min(x1, x2) / B), math.floor(math.max(x1, x2) / B) do
    for ky = math.floor(math.min(y1, y2) / B), math.floor(math.max(y1, y2) / B) do
      for _, s in ipairs(segs[kx * 65536 + ky] or {}) do
        if not seen[s] then
          seen[s] = true
          local ex, ey = s[3] - s[1], s[4] - s[2]
          local den = dx * ey - dy * ex
          if math.abs(den) > 1e-9 then
            local t = ((s[1] - x1) * ey - (s[2] - y1) * ex) / den
            local u = ((s[1] - x1) * dy - (s[2] - y1) * dx) / den
            if t > 1e-9 and t <= 1 and u >= 0 and u <= 1 and (not best or t < best) then best = t end -- (at its end too: a crossing right on a point)
          end
        end
      end
    end
  end
  return best
end

-- Whether world (x, y) is inside grid `key`'s rectangle (a city level's: over the city).
-- The world extent of grid `key` (a continent's, a city's or an instance's): x0, x1, y0, y1.
function P.GridBounds(key)
  local g = ns.Terrain and ns.Terrain[key]
  if not (g and g.w and g.h) then return nil end
  local x1, y1 = (32 - g.ty0) * TILE, (32 - g.tx0) * TILE -- (its north-west corner: rows run south, columns east)
  return x1 - g.h * g.cell, x1, y1 - g.w * g.cell, y1
end

function P.InGrid(key, x, y)
  local g = ns.Terrain and ns.Terrain[key]
  if not g then return false end
  local c, r = ToCell(g, x, y)
  return r >= 1 and r <= g.h and c >= 1 and c <= g.w
end

-- Whether `cont` has any walls.
function P.HasWalls(cont)
  EnsureWalls()
  return wallSegs[cont] ~= nil and next(wallSegs[cont]) ~= nil
end

-- Whether the leg (x1, y1)-(x2, y2) crosses a wall.
function P.CrossesWall(cont, x1, y1, x2, y2)
  EnsureWalls()
  local segs = wallSegs[cont]
  if not segs then return false end
  local B = P.WALL_BUCKET
  local seen = {}
  for kx = math.floor(math.min(x1, x2) / B), math.floor(math.max(x1, x2) / B) do
    for ky = math.floor(math.min(y1, y2) / B), math.floor(math.max(y1, y2) / B) do
      for _, s in ipairs(segs[kx * 65536 + ky] or {}) do
        if not seen[s] then
          seen[s] = true
          local o1, o2 = Orient(x1, y1, x2, y2, s[1], s[2]), Orient(x1, y1, x2, y2, s[3], s[4])
          local o3, o4 = Orient(s[1], s[2], s[3], s[4], x1, y1), Orient(s[1], s[2], s[3], s[4], x2, y2)
          if o1 ~= o2 and o3 ~= o4 and o1 ~= 0 and o2 ~= 0 then return true end
        end
      end
    end
  end
  return false
end

-- Grids laid over a continent's (a city's ruins up top, the caves: ns.CityHalls[cont]), by
-- area: { keys = the list indexed, n = its length, b = { [bucket] = { grid, ... } } }. Built
-- again when the list changes.
local OV_BUCKET = 256
local ovIndex = {}
local function OverlayIndex(cont)
  local keys = ns.CityHalls and ns.CityHalls[cont]
  if not keys then return nil end
  local ix = ovIndex[cont]
  if ix and ix.keys == keys and ix.n == #keys then return ix end
  ix = { keys = keys, n = #keys, b = {} }
  for _, key in ipairs(keys) do
    local o = ns.Terrain and ns.Terrain[key]
    if o and o.overlay then
      local x1, y1 = (32 - o.ty0) * TILE, (32 - o.tx0) * TILE -- (its north-west corner: rows run south, columns east)
      local x0, y0 = x1 - o.h * o.cell, y1 - o.w * o.cell
      for bx = math.floor(x0 / OV_BUCKET), math.floor(x1 / OV_BUCKET) do
        for by = math.floor(y0 / OV_BUCKET), math.floor(y1 / OV_BUCKET) do
          local k = bx * 65536 + by
          local list = ix.b[k]
          if not list then
            list = {}
            ix.b[k] = list
          end
          list[#list + 1] = o
        end
      end
    end
  end
  ovIndex[cont] = ix
  return ix
end

-- A grid laid over a continent's (a city's ruins up top, a cave: ns.CityHalls[cont]): its
-- own value at (x, y) and the grid, or nil where none has one (1: the continent's grid).
-- A cave's (Data/Caves.lua) are 0 open, 2 closed, 3 its floor under walkable ground (open,
-- up top or down below; its rock there is the continent's grid, 1).
-- (`floors`: past a capital's floors under others (`split`), to the grid of the floor over them.)
local function OverlayRaw(cont, x, y, floors)
  local ix = OverlayIndex(cont)
  if not ix then return nil end
  local list = ix.b[math.floor(x / OV_BUCKET) * 65536 + math.floor(y / OV_BUCKET)]
  if not list then return nil end
  for _, o in ipairs(list) do
    local col, row = ToCell(o, x, y)
    if row >= 1 and row <= o.h and col >= 1 and col <= o.w then
      local v = Cell(o, row, col)
      if v ~= 1 and not (floors and o.split) then return v, o end
    end
  end
  return nil
end
P.OverlayRaw = OverlayRaw

-- An overlay's value at (x, y) (0 open, 2 closed), or nil where the continent's grid holds.
-- (A capital's floor under another: the one over it, which a straight line there stays on.)
local function Overlay(cont, x, y)
  local v = OverlayRaw(cont, x, y, true)
  if v == 3 then return 0 end
  if v == 2 then -- (closed there, unless a wall eraser opened it)
    local g = ns.Terrain and ns.Terrain[cont]
    local oc = g and openCells[g]
    if oc then
      local c, r = ToCell(g, x, y)
      if oc[r * 65536 + c] then return 0 end
    end
  end
  return v
end
P.Overlay = Overlay

-- Whether any overlay grid lies near the leg (x1, y1)-(x2, y2) (its buckets): its cells are
-- finer than the continent's, so a leg there is checked every OVERLAY_STEP yards.
P.OVERLAY_STEP = 0.75
local function OverlayNear(cont, x1, y1, x2, y2)
  local ix = OverlayIndex(cont)
  if not ix then return false end
  for bx = math.floor(math.min(x1, x2) / OV_BUCKET), math.floor(math.max(x1, x2) / OV_BUCKET) do
    for by = math.floor(math.min(y1, y2) / OV_BUCKET), math.floor(math.max(y1, y2) / OV_BUCKET) do
      if ix.b[bx * 65536 + by] then return true end
    end
  end
  return false
end
P.OverlayNear = OverlayNear

-- Cell value at world (x, y) on continent `cont` (2 outside the grid).
function P.At(cont, x, y)
  EnsureWalls()
  local ov = Overlay(cont, x, y)
  if ov then return ov end
  local g = ns.Terrain and ns.Terrain[cont]
  if not g then return 0 end -- no data: treat as open
  local col, row = ToCell(g, x, y)
  return Cell(g, row, col)
end

-- Cost (yards, water weighted) of walking straight from (x1, y1) to (x2, y2), or nil when
-- the line crosses blocked terrain. Blocked cells within END_SLACK of either end are
-- ignored: the player (or the road) is evidently standing there.
P.END_SLACK = 12
-- A start inside "blocked" terrain (the player is standing there, so it's walkable: the
-- slope data is too strict on rocky ground) may cross this much of it to open ground; a
-- stop placed inside it, STOP_SLACK. Ends on open ground keep END_SLACK.
P.START_SLACK = 60
P.STOP_SLACK = 40
-- (A grid with its own `slack`, a city's: its blocked cells are walls and ledges, so only
-- that much, or up to CITY_INSIDE_SLACK from a start or stop inside them.)
P.CITY_INSIDE_SLACK = 0 -- (Router starts and stops from the nearest open floor instead)

function P.SegmentCost(cont, x1, y1, x2, y2, endSlack)
  if P.CrossesWall(cont, x1, y1, x2, y2) then return nil end -- (a wall: never, not even near its ends)
  local g = ns.Terrain and ns.Terrain[cont]
  local dx, dy = x2 - x1, y2 - y1
  local len = math.sqrt(dx * dx + dy * dy)
  if not g then return len end
  local step = g.cell / 3 -- fine enough not to skip across the corner of a blocked cell
  local near = OverlayNear(cont, x1, y1, x2, y2)
  if near then step = math.min(step, P.OVERLAY_STEP) end -- (nor an overlay's)
  local n = math.max(1, math.ceil(len / step))
  local water = 0
  local yards = endSlack or P.END_SLACK
  if g.slack then yards = endSlack and math.min(endSlack, math.max(g.slack, P.CITY_INSIDE_SLACK)) or g.slack end
  local slack = len > 0 and yards / len or 1
  -- (no grid laid over the continent near the line: its own cells only; and a cell's value is
  -- looked up once, not for each of the samples in it)
  local k = TILE / g.cell
  local lastRow, lastCol, lastV
  for i = 0, n do
    local t = i / n
    local x, y = x1 + dx * t, y1 + dy * t
    local ov = near and Overlay(cont, x, y) or nil
    if ov == 2 and t > 0 and t < 1 then return nil end -- (a city's ruins: its walls are real, no slack)
    local v = ov
    if not v then -- (the continent's own grid: the overlay was just asked)
      local col = math.floor(((32 - y / TILE) - g.tx0) * k) + 1
      local row = math.floor(((32 - x / TILE) - g.ty0) * k) + 1
      if row == lastRow and col == lastCol then
        v = lastV
      else
        v = Cell(g, row, col)
        lastRow, lastCol, lastV = row, col, v
      end
    end
    if v == 2 and t > slack and t < 1 - slack then return nil end
    if v == 1 then water = water + 1 end
  end
  return len + len * (water / (n + 1)) * (P.SWIM_COST - 1)
end

-- Binary heap keyed on f.
local function Push(h, node, f)
  h[#h + 1] = { node, f }
  local i = #h
  while i > 1 do
    local p = math.floor(i / 2)
    if h[p][2] <= h[i][2] then break end
    h[p], h[i] = h[i], h[p]
    i = p
  end
end

local function Pop(h)
  local top = h[1]
  local last = table.remove(h)
  if #h > 0 then
    h[1] = last
    local i = 1
    while true do
      local l, r, m = i * 2, i * 2 + 1, i
      if h[l] and h[l][2] < h[m][2] then m = l end
      if h[r] and h[r][2] < h[m][2] then m = r end
      if m == i then break end
      h[m], h[i] = h[i], h[m]
      i = m
    end
  end
  return top
end

P.PATH_PAD = 50 -- cells searched around the two points' bounding box
P.PATH_MAX_CELLS = 520 * 520
-- Cells expanded before giving up (the search runs in the background in slices, so this
-- only bounds how long a hopeless search, e.g. walled in by a town's terrain, keeps going).
P.PATH_MAX_EXPANSIONS = 80000
P.PATH_YIELD_EVERY = 50 -- cells expanded between pauses when run in the background

local SQ2 = math.sqrt(2)

-- The cost rule's value of a continent grid's cell: its own (walls and erased ground in), or,
-- under a capital's or the ruins' grid (not a cave's), that one's at the cell's middle.
local function BaseValue(g, cont, hasOverlay, c, r)
  local v = Cell(g, r, c)
  if hasOverlay then
    local cx, cy = CellCentre(g, c, r)
    local ov, o = OverlayRaw(cont, cx, cy, true)
    if ov and not o.cave then v = ov end
  end
  return v
end

-- A row of `cont`'s grid as those values, one digit a cell (for the offline prep, hpa.py).
function P.BaseRow(cont, r)
  local g = ns.Terrain[cont]
  local hasOverlay = ns.CityHalls and ns.CityHalls[cont] and true
  local t = {}
  for c = 1, g.w do t[c] = BaseValue(g, cont, hasOverlay, c, r) end
  return table.concat(t)
end

-- Cheapest walks over cells from (c0, r0): { [r * 65536 + c] = cost } and where each came
-- from. `step(c, r)`: the multiplier for stepping into a cell, nil where it can't go (a
-- diagonal step needs both cells beside it open). `back`: walks to (c0, r0) instead (each
-- entry's `came` is the next cell toward it).
local function Spread(step, c0, r0, back, pause)
  local start = r0 * 65536 + c0
  local dist, came, done, open = { [start] = 0 }, {}, {}, {}
  Push(open, start, 0)
  while #open > 0 do
    local n = Pop(open)[1]
    if not done[n] then
      done[n] = true
      if pause then pause() end
      local r, c = math.floor(n / 65536), n % 65536
      local here = back and (step(c, r) or 1) -- (walking back: stepping into this cell)
      for dr = -1, 1 do
        for dc = -1, 1 do
          if dr ~= 0 or dc ~= 0 then
            local m = step(c + dc, r + dr)
            if m and (dr == 0 or dc == 0 or (step(c + dc, r) and step(c, r + dr))) then
              local k = (r + dr) * 65536 + c + dc
              local d = dist[n] + (back and here or m) * ((dr ~= 0 and dc ~= 0) and SQ2 or 1)
              if not done[k] and (dist[k] == nil or d < dist[k]) then
                dist[k], came[k] = d, n
                Push(open, k, d)
              end
            end
          end
        end
      end
    end
  end
  return dist, came
end

-- A* over cells from (c1, r1) to (c2, r2): the cells { {c, r}, ... }, or nil.
local function CellPath(step, c1, r1, c2, r2, pause, limit)
  local start, goal = r1 * 65536 + c1, r2 * 65536 + c2
  local gs, came, closed, open = { [start] = 0 }, {}, {}, {}
  Push(open, start, 0)
  local expanded = 0
  while #open > 0 do
    local n = Pop(open)[1]
    if n == goal then break end
    if not closed[n] then
      closed[n] = true
      expanded = expanded + 1
      if limit and expanded > limit then return nil end
      if pause then pause() end
      local r, c = math.floor(n / 65536), n % 65536
      for dr = -1, 1 do
        for dc = -1, 1 do
          if dr ~= 0 or dc ~= 0 then
            local m = step(c + dc, r + dr)
            if m and (dr == 0 or dc == 0 or (step(c + dc, r) and step(c, r + dr))) then
              local k = (r + dr) * 65536 + c + dc
              local ng = gs[n] + m * ((dr ~= 0 and dc ~= 0) and SQ2 or 1)
              if not closed[k] and (gs[k] == nil or ng < gs[k]) then
                gs[k], came[k] = ng, n
                Push(open, k, ng + math.sqrt((c + dc - c2) ^ 2 + (r + dr - r2) ^ 2))
              end
            end
          end
        end
      end
    end
  end
  if not gs[goal] then return nil end
  local cells, cur = {}, goal
  while cur do
    table.insert(cells, 1, { cur % 65536, math.floor(cur / 65536) })
    cur = came[cur]
  end
  return cells
end

-- The cells on the line from (c1, r1) to (c2, r2) when every one of them is plain open ground
-- (a step of 1: no water, no guards' reach), with the walk's cost over cells (the 8-way
-- distance, what a search would find there); else nil. Open ground needs no search.
local function LineCells(step, c1, r1, c2, r2)
  local dc, dr = c2 - c1, r2 - r1
  local n = math.max(math.abs(dc), math.abs(dr))
  local cells = { { c1, r1 } }
  local pc, pr = c1, r1
  for i = 1, n do
    local c, r = c1 + math.floor(dc * i / n + 0.5), r1 + math.floor(dr * i / n + 0.5)
    if step(c, r) ~= 1 then return nil end
    if c ~= pc and r ~= pr and not (step(c, pr) == 1 and step(pc, r) == 1) then return nil end
    cells[#cells + 1] = { c, r }
    pc, pr = c, r
  end
  local a, b = math.abs(dc), math.abs(dr)
  return cells, math.max(a, b) + (SQ2 - 1) * math.min(a, b)
end

-- Searching by blocks (hierarchical A*, as Shortest Path Forever does): a continent's grid cut
-- into blocks of K x K cells (Data/TerrainHPA.lua, prepared offline by `agps terrain-hpa`,
-- app/azerothgps/hpa.py): each block's ways through to its neighbors (along each border, one
-- per opening, or one at each end of a wide one) and the walks between them inside it. A long
-- walk is searched over those (a few hundred nodes, not tens of thousands of cells), then only
-- the cells across the blocks it goes through; walled in, that's known at once. The blocks the
-- player's own walls or wall erasers change (and their neighbors) are worked out here instead.
P.HPA_MIN_CELLS = 40 -- start and stop at least this many cells apart (either way): by blocks
P.HPA_RUN_SPLIT = 8 -- (hpa.RUN_SPLIT) an opening this wide gets a way through at each end, else one in its middle

local function Two(s, i) return INDEX[s:byte(i)] * 64 + INDEX[s:byte(i + 1)] end

-- A block's ways through: { n, r = {}, c = {} (their cells), cost = {} (n x n: walking
-- between two inside the block, false: no way), at = { [cell in the block] = way } }.
local function DecodeBlock(H, b)
  local bl = { n = 0, r = {}, c = {}, cost = {}, at = {} }
  local s = H.c[b]
  if not s then return bl end
  local K = H.K
  local r0, c0 = math.floor(b / H.nx) * K, (b % H.nx) * K
  local n, p = Two(s, 1), 3
  for i = 1, n do
    local l = Two(s, p)
    p = p + 2
    bl.r[i], bl.c[i], bl.at[l] = r0 + math.floor(l / K) + 1, c0 + l % K + 1, i
  end
  for i = 1, n - 1 do
    for j = i + 1, n do
      local v = Two(s, p)
      p = p + 2
      local d = v < 4095 and v / 4 or false
      bl.cost[(i - 1) * n + j], bl.cost[(j - 1) * n + i] = d, d
    end
  end
  bl.n = n
  return bl
end

-- The same worked out from the grid as it is now (the player's walls in), as hpa.py does.
local function BuildBlock(g, cont, H, b)
  local K = H.K
  local br, bc = math.floor(b / H.nx), b % H.nx
  local r0, c0 = br * K, bc * K
  local hasOverlay = ns.CityHalls and ns.CityHalls[cont] and true
  local vals = {}
  local function V(c, r)
    if r < 1 or r > g.h or c < 1 or c > g.w then return 2 end
    local k = r * 65536 + c
    local v = vals[k]
    if not v then
      v = BaseValue(g, cont, hasOverlay, c, r)
      vals[k] = v
    end
    return v
  end
  local set = {}
  local function runs(ok, at)
    local s
    for k = 0, K do
      local o = k < K and ok(k)
      if o and not s then s = k end
      if not o and s then
        local e = k - 1
        if e - s + 1 >= P.HPA_RUN_SPLIT then
          set[at(s)], set[at(e)] = true, true
        else
          set[at(math.floor((s + e) / 2))] = true
        end
        s = nil
      end
    end
  end
  if bc > 0 then runs(function(k) return V(c0 + 1, r0 + k + 1) ~= 2 and V(c0, r0 + k + 1) ~= 2 end, function(k) return k * K end) end
  if bc < H.nx - 1 then
    runs(function(k) return V(c0 + K, r0 + k + 1) ~= 2 and V(c0 + K + 1, r0 + k + 1) ~= 2 end, function(k) return k * K + K - 1 end)
  end
  if br > 0 then runs(function(k) return V(c0 + k + 1, r0 + 1) ~= 2 and V(c0 + k + 1, r0) ~= 2 end, function(k) return k end) end
  if br < H.ny - 1 then
    runs(function(k) return V(c0 + k + 1, r0 + K) ~= 2 and V(c0 + k + 1, r0 + K + 1) ~= 2 end, function(k) return (K - 1) * K + k end)
  end
  local list = {}
  for l in pairs(set) do list[#list + 1] = l end
  table.sort(list)
  local bl = { n = #list, r = {}, c = {}, cost = {}, at = {} }
  for i, l in ipairs(list) do
    bl.r[i], bl.c[i], bl.at[l] = r0 + math.floor(l / K) + 1, c0 + l % K + 1, i
  end
  local function step(c, r)
    if c <= c0 or c > c0 + K or r <= r0 or r > r0 + K then return nil end
    local v = V(c, r)
    if v == 2 then return nil end
    return v == 1 and P.SWIM_COST or 1
  end
  for i = 1, bl.n do
    local dist = Spread(step, bl.c[i], bl.r[i])
    for j = 1, bl.n do
      if j ~= i then bl.cost[(i - 1) * bl.n + j] = dist[bl.r[j] * 65536 + bl.c[j]] or false end
    end
  end
  return bl
end

-- The walk's cells by blocks: { {c, r}, ... }; or nil and "none" (no way through the blocks
-- over the search box), or nil and "cells" (search it cell by cell after all).
local function ByBlocks(g, H, cont, c1, r1, c2, r2, step, box, hostile, pause)
  local K, nx, ny = H.K, H.nx, H.ny
  local function BlockOf(c, r) return math.floor((r - 1) / K) * nx + math.floor((c - 1) / K) end
  local blocks = hpaBlocks[cont]
  if not blocks then
    blocks = {}
    hpaBlocks[cont] = blocks
  end
  local dirty = hpaDirty[cont]
  local function Block(b)
    local bl = blocks[b]
    if not bl then
      bl = (dirty and dirty[b]) and BuildBlock(g, cont, H, b) or DecodeBlock(H, b)
      blocks[b] = bl
    end
    return bl
  end
  -- (only the blocks over the search box, as the cell search keeps to the box)
  local bc0, bc1 = math.max(0, math.floor((box[1] - 1) / K)), math.min(nx - 1, math.floor((box[2] - 1) / K))
  local br0, br1 = math.max(0, math.floor((box[3] - 1) / K)), math.min(ny - 1, math.floor((box[4] - 1) / K))
  local function Within(b) -- a block's cells only
    local r0, c0 = math.floor(b / nx) * K, (b % nx) * K
    return function(c, r)
      if c <= c0 or c > c0 + K or r <= r0 or r > r0 + K then return nil end
      return step(c, r)
    end
  end
  local bs, bg = BlockOf(c1, r1), BlockOf(c2, r2)
  if bs == bg then return nil, "cells" end
  -- the start's and the stop's walks to their blocks' ways through: straight over open ground,
  -- else searched over the block's cells
  local S, Gb = Block(bs), Block(bg)
  local function Reach(bl, b, c0, r0, back)
    local dist, lines = {}, {}
    for i = 1, bl.n do
      local cells, d = LineCells(Within(b), c0, r0, bl.c[i], bl.r[i])
      if not cells then return Spread(Within(b), c0, r0, back, pause) end
      local k = bl.r[i] * 65536 + bl.c[i]
      dist[k], lines[k] = d, cells
    end
    return dist, nil, lines
  end
  local sdist, scame, slines = Reach(S, bs, c1, r1, false)
  local gdist, gcame, glines = Reach(Gb, bg, c2, r2, true)
  local HF = ns.Router and ns.Router.HOSTILE_FACTOR or 1
  local function h(r, c) return math.sqrt((c - c2) ^ 2 + (r - r2) ^ 2) end
  local gs, came, closed, open = {}, {}, {}, {}
  for i = 1, S.n do
    local d = sdist[S.r[i] * 65536 + S.c[i]]
    if d then
      local k = bs * 4096 + i
      gs[k], came[k] = d, false
      Push(open, k, d + h(S.r[i], S.c[i]))
    end
  end
  if not next(gs) then return nil, "cells" end -- (walled in within its block: the cells decide)
  local reached = false
  for i = 1, Gb.n do
    if gdist[Gb.r[i] * 65536 + Gb.c[i]] then reached = true break end
  end
  if not reached then return nil, "cells" end
  local best, bestK
  local expanded = 0
  local DIRS = { { 1, 0 }, { -1, 0 }, { 0, 1 }, { 0, -1 } }
  while #open > 0 do
    local top = Pop(open)
    local k = top[1]
    if best and top[2] >= best then break end
    if not closed[k] then
      closed[k] = true
      expanded = expanded + 1
      if expanded > P.PATH_MAX_EXPANSIONS then return nil, "none" end
      if pause then pause() end
      local b, i = math.floor(k / 4096), k % 4096
      local bl = Block(b)
      local r, c = bl.r[i], bl.c[i]
      local gk = gs[k]
      if b == bg then -- (the stop's block: on to the stop)
        local d = gdist[r * 65536 + c]
        if d and (not best or gk + d < best) then best, bestK = gk + d, k end
      end
      -- across the block to its other ways through (the other faction's guards: about)
      local n = bl.n
      for j = 1, n do
        local d = j ~= i and bl.cost[(i - 1) * n + j]
        if d then
          if HF ~= 1 then -- (the share of five points along the way that are in their reach)
            local cj, rj, inside = bl.c[j], bl.r[j], 0
            for q = 0, 4 do
              if hostile(math.floor(c + (cj - c) * q / 4 + 0.5), math.floor(r + (rj - r) * q / 4 + 0.5)) then inside = inside + 1 end
            end
            d = d * (1 + inside / 5 * (HF - 1))
          end
          local kj = b * 4096 + j
          local ng = gk + d
          if not closed[kj] and (gs[kj] == nil or ng < gs[kj]) then
            gs[kj], came[kj] = ng, k
            Push(open, kj, ng + h(bl.r[j], bl.c[j]))
          end
        end
      end
      -- over the border to the neighbor's way through beside it
      for _, o in ipairs(DIRS) do
        local nc, nr = c + o[1], r + o[2]
        if nc >= 1 and nc <= g.w and nr >= 1 and nr <= g.h then
          local nb = BlockOf(nc, nr)
          local nbr, nbc = math.floor(nb / nx), nb % nx
          if nb ~= b and nbc >= bc0 and nbc <= bc1 and nbr >= br0 and nbr <= br1 then
            local m = step(nc, nr)
            local j = m and Block(nb).at[((nr - 1) % K) * K + (nc - 1) % K]
            if j then
              local kj = nb * 4096 + j
              local ng = gk + m
              if not closed[kj] and (gs[kj] == nil or ng < gs[kj]) then
                gs[kj], came[kj] = ng, k
                Push(open, kj, ng + h(nr, nc))
              end
            end
          end
        end
      end
    end
  end
  if not best then return nil, "none" end
  -- the ways through, in order, then their cells
  local chain, k = {}, bestK
  while k do
    table.insert(chain, 1, k)
    k = came[k]
  end
  local cells = {}
  local function At(key) local bl = Block(math.floor(key / 4096)) local i = key % 4096 return bl.c[i], bl.r[i] end
  local fc, fr = At(chain[1])
  if slines then
    for _, cell in ipairs(slines[fr * 65536 + fc]) do cells[#cells + 1] = cell end
  else
    local seq, cur = {}, fr * 65536 + fc
    while cur do
      table.insert(seq, 1, cur)
      cur = scame[cur]
    end
    for _, n in ipairs(seq) do cells[#cells + 1] = { n % 65536, math.floor(n / 65536) } end
  end
  for q = 2, #chain do
    local ac, ar = At(chain[q - 1])
    local bc, br = At(chain[q])
    if math.floor(chain[q - 1] / 4096) == math.floor(chain[q] / 4096) then
      local within = Within(math.floor(chain[q] / 4096))
      local path = LineCells(within, ac, ar, bc, br) or CellPath(within, ac, ar, bc, br, pause)
      if not path then return nil, "cells" end
      for m = 2, #path do cells[#cells + 1] = path[m] end
    else
      cells[#cells + 1] = { bc, br }
    end
  end
  local lc, lr = At(chain[#chain])
  if glines then
    local line = glines[lr * 65536 + lc] -- (from the stop: walked backward)
    for m = #line - 1, 1, -1 do cells[#cells + 1] = line[m] end
  else
    local cur = gcame[lr * 65536 + lc]
    while cur do
      cells[#cells + 1] = { cur % 65536, math.floor(cur / 65536) }
      cur = gcame[cur]
    end
  end
  return cells
end

-- Walkable path from (x1, y1) to (x2, y2) over the grid (8-connected A*, by blocks when far,
-- then straightened with line of sight): cost, { x1, y1, ..., x2, y2 }; nil when there is
-- none nearby.
function P.FindPath(cont, x1, y1, x2, y2)
  EnsureWalls()
  local g = ns.Terrain and ns.Terrain[cont]
  if not g then return nil end
  local c1, r1 = ToCell(g, x1, y1)
  local c2, r2 = ToCell(g, x2, y2)
  local pad = P.PATH_PAD
  local cmin, cmax = math.min(c1, c2) - pad, math.max(c1, c2) + pad
  local rmin, rmax = math.min(r1, r2) - pad, math.max(r1, r2) + pad
  if (cmax - cmin + 1) * (rmax - rmin + 1) > P.PATH_MAX_CELLS then return nil end
  local function slack(yd) -- (squared cells; a city's none means none: its walls are real)
    if g.slack and yd <= 0 then return -1 end
    return (yd / g.cell + 1) ^ 2
  end
  local function yards(inside, far)
    if g.slack then return inside and math.max(g.slack, P.CITY_INSIDE_SLACK) or g.slack end
    return inside and far or P.END_SLACK
  end
  local slack1 = slack(yards(Cell(g, r1, c1) == 2, P.START_SLACK))
  local slack2 = slack(yards(Cell(g, r2, c2) == 2, P.STOP_SLACK))
  local hasOverlay = ns.CityHalls and ns.CityHalls[cont] and true
  -- (the other faction's guards: their reach costs Router.HOSTILE_FACTOR a step)
  local Rt = ns.Router
  local side = Rt and Rt.HostileSide and Rt.HostileSide()
  local hostileCell = {}
  local function hostile(c, r)
    if not side then return false end
    local k = r * 65536 + c
    local h = hostileCell[k]
    if h == nil then
      local hx, hy = CellCentre(g, c, r)
      h = Rt.HostileAt(cont, hx, hy, side)
      hostileCell[k] = h
    end
    return h
  end
  local wc = wallCells[g]
  local function cost0(c, r)
    if wc and wc[r * 65536 + c] then return nil end -- (a wall: not even near the ends)
    local v = Cell(g, r, c)
    if g.overlay and v == 1 then return nil end -- (an overlay grid: not its own there)
    if hasOverlay then -- (the continent's grid: a ruins' own grid over it where it has one)
      -- (not a cave's: its tunnels are narrower than these cells, and its roads lead through
      -- it; a cell's middle on its floor would open a hillside's blocked cell)
      local cx, cy = CellCentre(g, c, r)
      local ov, o = OverlayRaw(cont, cx, cy, true)
      if ov and not o.cave then v = ov end
    end
    if v == 2 then
      if (c - c1) ^ 2 + (r - r1) ^ 2 > slack1 and (c - c2) ^ 2 + (r - r2) ^ 2 > slack2 then return nil end
      return 1
    end
    return v == 1 and P.SWIM_COST or 1
  end
  local memo = {}
  local function step(c, r) -- step multiplier into (c, r), or nil where it can't go
    local k = r * 65536 + c
    local m = memo[k]
    if m == nil then
      m = cost0(c, r) or false
      if m and hostile(c, r) then m = m * Rt.HOSTILE_FACTOR end
      memo[k] = m
    end
    return m or nil
  end
  -- Run as a background job (a coroutine, see Router.Pump): hand control back every so
  -- often so no single frame pays for the whole search.
  local co, isMain = coroutine.running()
  local canYield = co ~= nil and not isMain
  local count = 0
  local pause = canYield and function()
    count = count + 1
    if count % P.PATH_YIELD_EVERY == 0 then coroutine.yield() end
  end or nil
  local cells, how
  local H = ns.TerrainHPA and ns.TerrainHPA[cont]
  if H and not g.slack and H.w == g.w and H.h == g.h
      and (math.abs(c1 - c2) >= P.HPA_MIN_CELLS or math.abs(r1 - r2) >= P.HPA_MIN_CELLS) then
    cells, how = ByBlocks(g, H, cont, c1, r1, c2, r2, step, { cmin, cmax, rmin, rmax }, hostile, pause)
    if how == "none" then return nil end
  end
  if not cells then
    local function inBox(c, r)
      if c < cmin or c > cmax or r < rmin or r > rmax then return nil end
      return step(c, r)
    end
    cells = CellPath(inBox, c1, r1, c2, r2, pause, P.PATH_MAX_EXPANSIONS)
    if not cells then return nil end
  end
  local pts = {}
  for i, n in ipairs(cells) do
    local x, y = CellCentre(g, n[1], n[2])
    if i == 1 then x, y = x1, y1 elseif i == #cells then x, y = x2, y2 end
    pts[#pts + 1] = { x, y }
  end
  -- straighten: from each kept point, go as far along the path as is still in sight (and
  -- not back into the other faction's guards' reach where the path went round it)
  -- (the path's yards in their reach so far, from its start: a shortcut may not add any)
  local hostileSoFar = { 0 }
  for k = 2, #pts do
    local inside = hostile(cells[k][1], cells[k][2])
    local d = math.sqrt((pts[k][1] - pts[k - 1][1]) ^ 2 + (pts[k][2] - pts[k - 1][2]) ^ 2)
    hostileSoFar[k] = hostileSoFar[k - 1] + (inside and d or 0)
  end
  local function shortcut(i, j)
    if not P.SegmentCost(cont, pts[i][1], pts[i][2], pts[j][1], pts[j][2], 0) then return false end
    if side then
      local h = Rt.HostileYards(cont, pts[i][1], pts[i][2], pts[j][1], pts[j][2], side)
      if h > hostileSoFar[j] - hostileSoFar[i] + g.cell then return false end
    end
    return true
  end
  local out, total, i = { x1, y1 }, 0, 1
  local checks = 0
  local function sees(j)
    checks = checks + 1
    if canYield and checks % 6 == 0 then coroutine.yield() end
    return shortcut(i, j)
  end
  while i < #pts do
    -- the farthest point still in sight: jumping ahead twice as far each time, then halving
    -- back between the last one seen and the first one not (a line check each, not one per point)
    local j, far, jump = i + 1, nil, 1
    while j < #pts do
      local k = math.min(#pts, j + jump)
      if sees(k) then
        j, jump = k, jump * 2
      else
        far = k
        break
      end
    end
    while far and far - j > 1 do
      local mid = math.floor((j + far) / 2)
      if sees(mid) then j = mid else far = mid end
    end
    local a, b = pts[i], pts[j]
    total = total + (P.SegmentCost(cont, a[1], a[2], b[1], b[2]) or math.sqrt((b[1] - a[1]) ^ 2 + (b[2] - a[2]) ^ 2))
    out[#out + 1], out[#out + 2] = b[1], b[2]
    i = j
  end
  return total, out
end

function P.ClearCache()
  cache, ovIndex, hpaBlocks = {}, {}, {}
end

-- Whether (x, y) is hilly ground (Data/Terrain.lua's ns.Hills: open, but a climb): a route
-- winding there may be taking the slope the easy way.
function P.Hilly(cont, x, y)
  local g = ns.Hills and ns.Hills[cont]
  if not g then return false end
  local c, r = ToCell(g, x, y)
  if r < 1 or r > g.h or c < 1 or c > g.w then return false end
  return Cell(g, r, c) == 1
end

-- Whether the path (flat points, from index i to j) or the straight line between its ends
-- is on hilly ground anywhere (checked every `step` yards).
function P.HillyAlong(cont, pts, i, j, step)
  if not (ns.Hills and ns.Hills[cont]) then return false end
  step = step or 10
  local function line(x1, y1, x2, y2)
    local n = math.max(1, math.ceil(math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2) / step))
    for k = 0, n do
      if P.Hilly(cont, x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n) then return true end
    end
    return false
  end
  for m = i, j - 1 do
    if line(pts[2 * m - 1], pts[2 * m], pts[2 * m + 1], pts[2 * m + 2]) then return true end
  end
  return line(pts[2 * i - 1], pts[2 * i], pts[2 * j - 1], pts[2 * j])
end

-- Whether (x, y) is open ground on `cont`'s grid (false without a grid).
function P.IsOpen(cont, x, y)
  EnsureWalls()
  local ov = Overlay(cont, x, y)
  if ov then return ov == 0 end
  local g = ns.Terrain and ns.Terrain[cont]
  if not g then return false end
  local c, r = ToCell(g, x, y)
  local v = Cell(g, r, c)
  if g.overlay then return v == 0 end -- (an overlay's own: 1 is the continent's, not it)
  return v ~= 2
end

-- Decode the terrain rows within `yd` of (x, y) ahead of time (Router.WarmUp, run as a
-- background job: it pauses every few rows).
function P.WarmRows(cont, x, y, yd)
  local g = ns.Terrain and ns.Terrain[cont]
  if not g then return end
  local _, r1 = ToCell(g, x - yd, y - yd)
  local _, r2 = ToCell(g, x + yd, y + yd)
  local rc = cache[g]
  if not rc then
    rc = {}
    cache[g] = rc
  end
  local co, main = coroutine.running()
  local canYield = co ~= nil and not main
  local n = 0
  for row = math.max(1, math.min(r1, r2)), math.min(g.h, math.max(r1, r2)) do
    if not rc[row] and Rows(g)[row] then
      rc[row] = DecodeRow(Rows(g)[row], g.short, g.long)
      n = n + 1
      if canYield and n % 6 == 0 then coroutine.yield() end
    end
  end
end

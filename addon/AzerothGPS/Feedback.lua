-- Opt-in feedback for improving the road network (both off by default):
--  * shareRoads: roads the player draws or erases (Record.lua) are kept for sharing.
--  * shareTrips: when the player reaches a stop clearly faster than the addon estimated,
--    the way they went (a GPS trace) is kept: it likely found a road or shortcut the
--    network doesn't know.
-- Addons can't send anything over the network: this only stores the data in the saved
-- variables (AzerothGPSDB.feedback, account-wide, no character or realm names). Sharing it
-- is a separate step outside the game (`agps feedback` exports it for upload).
local _, ns = ...
local Geo = ns.Geo

local F = {}
ns.Feedback = F

F.FASTER = 0.85 -- kept when the trip took at most this share of the estimate
F.MIN_SECONDS = 20 -- shorter trips say nothing useful
F.STEP_YD = 10 -- trace point spacing
F.MAX_POINTS = 3000 -- per trip
F.MAX_TRIPS, F.MAX_ROADS = 100, 200 -- oldest dropped beyond these

local trip -- the leg being traced: { dest, t0, cont, estimate, mounted, pts }

local function S() return ns.settings.gps end

local function Store()
  local db = ns.db
  db.feedback = db.feedback or {}
  db.feedback.roads = db.feedback.roads or {}
  db.feedback.trips = db.feedback.trips or {}
  return db.feedback
end

local function Build()
  local v, b = GetBuildInfo()
  return tostring(v) .. "." .. tostring(b)
end

local function Push(list, item, max)
  list[#list + 1] = item
  while #list > max do table.remove(list, 1) end
end

local function Round(v) return math.floor(v * 10 + 0.5) / 10 end

-- Record.lua saved a drawn (or erased) road.
function F.RoadRecorded(track)
  if not S().shareRoads then return end
  local pts = {}
  for i, v in ipairs(track.pts) do pts[i] = v end
  Push(Store().roads, { op = track.op, continent = track.continent, zone = track.zone, pts = pts,
    time = track.time, area = track.area, z = track.z, indoors = track.indoors, down = track.down, build = Build(),
    addon = ns.VERSION }, F.MAX_ROADS)
end

-- ... and took one back: not shared either.
function F.RoadRemoved(track)
  local roads = ns.db.feedback and ns.db.feedback.roads
  if not roads then return end
  for i = #roads, 1, -1 do
    if roads[i].time == track.time and roads[i].continent == track.continent then table.remove(roads, i) end
  end
end

-- Nav reached stop `d` (before moving on to the next one).
function F.Arrived(d)
  local t = trip
  trip = nil
  if not t or t.dest ~= d or not S().shareTrips then return end
  local actual = GetTime() - t.t0
  if actual < F.MIN_SECONDS or actual > t.estimate * F.FASTER or #t.pts < 10 then return end
  local x, y, cont = Geo.PlayerWorld()
  if x then t.pts[#t.pts + 1], t.pts[#t.pts + 2] = Round(x), Round(y) end
  Push(Store().trips, {
    continent = t.cont, from = { t.pts[1], t.pts[2] }, to = { Round(d.x), Round(d.y), d.cont },
    estimate = math.floor(t.estimate + 0.5), actual = math.floor(actual + 0.5), mounted = t.mounted,
    pts = t.pts, time = time(), build = Build(), addon = ns.VERSION,
  }, F.MAX_TRIPS)
end

-- Once a second: start tracing a leg when a route is set, add points as the player moves.
local function Tick()
  if not S().shareTrips then
    trip = nil
    return
  end
  local N = ns.Nav
  local d, r = N.dest, N.route
  local px, py, cont = Geo.PlayerWorld()
  local away = (UnitOnTaxi and UnitOnTaxi("player")) or (UnitIsDeadOrGhost and UnitIsDeadOrGhost("player"))
  if not d or not r or not px or away then
    trip = nil
    return
  end
  if not trip or trip.dest ~= d then
    -- a new leg: remember what the addon predicted for it
    local _, walk, mount, mounted = N.Speeds()
    local speed = mounted and mount or walk
    trip = { dest = d, t0 = GetTime(), cont = cont, estimate = r.walkYards / speed + (r.rideSeconds or 0),
      mounted = mounted, pts = { Round(px), Round(py) } }
    return
  end
  if cont ~= trip.cont then
    trip = nil -- changed continent (a ride): not comparable
    return
  end
  local pts = trip.pts
  local n = #pts
  if (px - pts[n - 1]) ^ 2 + (py - pts[n]) ^ 2 >= F.STEP_YD * F.STEP_YD and n < F.MAX_POINTS * 2 then
    pts[n + 1], pts[n + 2] = Round(px), Round(py)
  end
end

function F.Init()
  if F.ticker then return end
  F.ticker = C_Timer.NewTicker(1, Tick)
end

-- The player's map data as text to copy and send ("Copy Map Data..."): a header line, then a line each.
-- The kinds the player picked (F.KINDS, the copy window's and the Help improve page's checkboxes, all on
-- by default) and the dungeons' ways in they learned:
--   roads:  R <add|remove|area> <continent> <time> [z=..] [indoors=1|0] [down=1] <x,y> <x,y> ...
--   walls:  R <wall|unwall|unwallarea> ... (as roads)
--   routes: T <continent> <time> <estimate s> <actual s> <mounted 1|0> to=<x>,<y>,<continent> <x,y> ...
--           (the faster trips "Share faster trips" kept, their traces simplified: TRIP_SIMPLIFY_YD)
--   pins:   P add|remove ... (Pins.ShareLines)
--   E <map id> <continent> <x,y> (a dungeon's way in; always)
-- Drawn roads both kept for sharing and not in the road data yet, each once. (`agps import-shared` reads
-- it back.) Positions and the player's pin names only: no character or realm names.
F.TEXT_HEADER = "AzerothGPS roads 1"
F.KINDS = {
  { kind = "roads", key = "copyRoads", label = "Roads", tip = "Roads you drew or erased with the road tools." },
  { kind = "walls", key = "copyWalls", label = "Walls", tip = "Walls you drew or erased with the wall tools." },
  { kind = "routes", key = "copyRoutes", label = "Routes",
    tip = "The ways you went when you reached a stop clearly faster than estimated (kept with Share faster trips on)." },
  { kind = "pins", key = "copyPins", label = "Pins", tip = "Your pins, and the shared ones you removed." },
}
F.TRIP_SIMPLIFY_YD = 4 -- a trip's trace: points within this of the line the others make are left out
function F.Included(kind)
  local st = ns.settings and ns.settings.gps
  for _, k in ipairs(F.KINDS) do
    if k.kind == kind then return not st or st[k.key] ~= false end
  end
  return true
end

-- A trace (flat x, y, ...) with the points within `tol` yards of the line through the others left out
-- (Douglas-Peucker): its first and last kept.
function F.Simplify(pts, tol)
  local n = #pts / 2
  if n <= 2 then return pts end
  local keep = { [1] = true, [n] = true }
  local stack = { { 1, n } }
  while #stack > 0 do
    local seg = table.remove(stack)
    local a, b = seg[1], seg[2]
    local ax, ay, bx, by = pts[2 * a - 1], pts[2 * a], pts[2 * b - 1], pts[2 * b]
    local vx, vy = bx - ax, by - ay
    local L2 = vx * vx + vy * vy
    local worst, wi = -1, nil
    for i = a + 1, b - 1 do
      local px, py = pts[2 * i - 1], pts[2 * i]
      local t = L2 > 0 and math.max(0, math.min(1, ((px - ax) * vx + (py - ay) * vy) / L2)) or 0
      local d = (ax + vx * t - px) ^ 2 + (ay + vy * t - py) ^ 2
      if d > worst then worst, wi = d, i end
    end
    if wi and worst > tol * tol then
      keep[wi] = true
      stack[#stack + 1] = { a, wi }
      stack[#stack + 1] = { wi, b }
    end
  end
  local out = {}
  for i = 1, n do
    if keep[i] then out[#out + 1], out[#out + 2] = pts[2 * i - 1], pts[2 * i] end
  end
  return out
end

-- Every kind's lines (whether picked or not): { roads, walls, routes, pins, entrances }.
function F.Lines()
  local out = { roads = {}, walls = {}, routes = {}, pins = {}, entrances = {} }
  local seen = {}
  local shipped = ns.RoadTracksIn or {}
  local function add(t)
    local key = tostring(t.continent) .. ":" .. tostring(t.time)
    -- (not what the data has already: nothing to share there)
    if seen[key] or not t.pts or #t.pts < 4 or shipped[t.time or -1] then return end
    seen[key] = true
    local op = t.op == "remove" and (t.area and "area" or "remove")
      or t.op == "wall" and "wall" or t.op == "unwall" and (t.area and "unwallarea" or "unwall") or "add"
    local line = { "R", op, tostring(t.continent or 0), tostring(t.time or 0) }
    -- (its floor, where floors lie over each other: "z=<height>", "indoors=1|0", "down=1")
    if t.z then line[#line + 1] = string.format("z=%.1f", t.z) end
    if t.indoors ~= nil then line[#line + 1] = t.indoors and "indoors=1" or "indoors=0" end
    if t.down then line[#line + 1] = "down=1" end
    for i = 1, #t.pts - 1, 2 do line[#line + 1] = string.format("%.1f,%.1f", t.pts[i], t.pts[i + 1]) end
    local list = (t.op == "wall" or t.op == "unwall") and out.walls or out.roads
    list[#list + 1] = table.concat(line, " ")
  end
  for _, t in ipairs(ns.db and ns.db.tracks or {}) do add(t) end
  for _, t in ipairs(ns.db and ns.db.feedback and ns.db.feedback.roads or {}) do add(t) end
  for _, t in ipairs(ns.db and ns.db.feedback and ns.db.feedback.trips or {}) do
    if t.pts and #t.pts >= 4 and t.to then
      local line = { "T", tostring(t.continent or 0), tostring(t.time or 0), tostring(t.estimate or 0),
        tostring(t.actual or 0), t.mounted and "1" or "0",
        string.format("to=%.1f,%.1f,%s", t.to[1] or 0, t.to[2] or 0, tostring(t.to[3] or t.continent or 0)) }
      local pts = F.Simplify(t.pts, F.TRIP_SIMPLIFY_YD)
      for i = 1, #pts - 1, 2 do line[#line + 1] = string.format("%.0f,%.0f", pts[i], pts[i + 1]) end
      out.routes[#out.routes + 1] = table.concat(line, " ")
    end
  end
  for _, l in ipairs(ns.Pins and ns.db and ns.Pins.ShareLines() or {}) do out.pins[#out.pins + 1] = l end
  -- dungeons' ways in learned (Taxi.NoteEntrance), those the data doesn't have yet
  for mapID, list in pairs(ns.db and ns.db.entrances or {}) do
    local known = F.KnownEntrances(mapID)
    for _, e in ipairs(list) do
      local have = false
      for _, k in ipairs(known) do
        if k[1] == e[1] and math.sqrt((k[2] - e[2]) ^ 2 + (k[3] - e[3]) ^ 2) <= 40 then have = true end
      end
      if not have then out.entrances[#out.entrances + 1] = string.format("E %d %d %.1f,%.1f", mapID, e[1], e[2], e[3]) end
    end
  end
  return out
end

-- Faster trips and dungeons' ways in someone shared, taken in (the dev tools' import of a Copy Map Data
-- text): trips with the ones kept here (by continent and time, each once; `agps feedback` exports them),
-- ways in with the ones learned (Taxi.NoteEntrance's, `agps entrances` / the road watcher take them).
-- trips: { continent, time, estimate, actual, mounted, to = { x, y, cont }, pts }; entrances: { map,
-- level, x, y }. Returns how many of each were new.
function F.AddShared(trips, entrances)
  local nt, ne = 0, 0
  local fb = Store()
  local have = {}
  for _, t in ipairs(fb.trips) do have[tostring(t.continent) .. ":" .. tostring(t.time)] = true end
  for _, t in ipairs(trips or {}) do
    local key = tostring(t.continent) .. ":" .. tostring(t.time)
    if not have[key] and t.pts and #t.pts >= 4 then
      have[key] = true
      Push(fb.trips, { continent = t.continent, time = t.time, estimate = t.estimate, actual = t.actual,
        mounted = t.mounted, from = { t.pts[1], t.pts[2] }, to = t.to, pts = t.pts, shared = true }, F.MAX_TRIPS)
      nt = nt + 1
    end
  end
  ns.db.entrances = ns.db.entrances or {}
  for _, e in ipairs(entrances or {}) do
    local list = ns.db.entrances[e.map] or {}
    ns.db.entrances[e.map] = list
    local near = false
    for _, k in ipairs(list) do
      if k[1] == e.level and math.sqrt((k[2] - e.x) ^ 2 + (k[3] - e.y) ^ 2) <= 40 then near = true end
    end
    for _, k in ipairs(F.KnownEntrances(e.map)) do
      if k[1] == e.level and math.sqrt((k[2] - e.x) ^ 2 + (k[3] - e.y) ^ 2) <= 40 then near = true end
    end
    if not near then
      list[#list + 1] = { e.level, e.x, e.y }
      ne = ne + 1
    end
  end
  return nt, ne
end

-- How many lines of each kind there are to share (picked or not): { roads = n, ... }.
function F.KindCounts()
  local counts = {}
  for kind, list in pairs(F.Lines()) do counts[kind] = #list end
  return counts
end

-- The text to copy: the kinds picked; and how many lines it has (the header aside).
function F.RoadsText()
  local all = F.Lines()
  local lines = {}
  for _, k in ipairs(F.KINDS) do
    if F.Included(k.kind) then
      for _, l in ipairs(all[k.kind]) do lines[#lines + 1] = l end
    end
  end
  for _, l in ipairs(all.entrances) do lines[#lines + 1] = l end
  if #lines == 0 then return "", 0 end
  local v, b = "", ""
  if GetBuildInfo then v, b = GetBuildInfo() end
  table.insert(lines, 1, string.format("%s (addon %s, game %s.%s)", F.TEXT_HEADER, tostring(ns.VERSION or "?"), tostring(v), tostring(b)))
  return table.concat(lines, "\n"), #lines - 1
end

-- The ways in the data has for dungeon map `mapID`: { { cont, x, y }, ... } (its entrances on a
-- continent, and a ghost spot).
function F.KnownEntrances(mapID)
  local out = {}
  local info = ns.Instances and ns.Instances[20000 + mapID]
  for _, e in ipairs(info and info.entrances or {}) do out[#out + 1] = e end
  if info and info.ghost then out[#out + 1] = info.ghost end
  return out
end

-- The drawn roads and walls waiting (not yet in the data): roads, walls (erasers of each count
-- with them).
function F.DrawnCounts()
  local roads, walls = 0, 0
  local shipped = ns.RoadTracksIn or {}
  for _, t in ipairs(ns.db and ns.db.tracks or {}) do
    if not shipped[t.time or -1] then
      if t.op == "wall" or t.op == "unwall" then walls = walls + 1 else roads = roads + 1 end
    end
  end
  return roads, walls
end

-- For the options: how much is waiting to be shared.
function F.Counts()
  local fb = ns.db and ns.db.feedback
  local shipped = ns.RoadTracksIn or {}
  local roads = 0
  for _, t in ipairs(fb and fb.roads or {}) do
    if not shipped[t.time or -1] then roads = roads + 1 end
  end
  return roads, fb and fb.trips and #fb.trips or 0
end

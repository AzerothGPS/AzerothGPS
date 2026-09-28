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
    time = track.time, area = track.area, build = Build(), addon = ns.VERSION }, F.MAX_ROADS)
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
    offroad = t.offroad, pts = t.pts, time = time(), build = Build(), addon = ns.VERSION,
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
      mounted = mounted, offroad = S().offroad, pts = { Round(px), Round(py) } }
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

-- The player's drawn and erased roads as text to copy and send (the share page's "Copy
-- road data"): a header line, then a road per line:
--   R <op add|remove|area> <continent> <time> <x,y> <x,y> ...
-- Both the roads kept for sharing and the ones not in the road data yet, each once.
-- (`agps import-shared` reads it back.) Numbers only: no character or realm names.
F.TEXT_HEADER = "AzerothGPS roads 1"
function F.RoadsText()
  local seen, lines = {}, {}
  local function add(t)
    local key = tostring(t.continent) .. ":" .. tostring(t.time)
    if seen[key] or not t.pts or #t.pts < 4 then return end
    seen[key] = true
    local op = t.op == "remove" and (t.area and "area" or "remove") or "add"
    local out = { "R", op, tostring(t.continent or 0), tostring(t.time or 0) }
    for i = 1, #t.pts - 1, 2 do out[#out + 1] = string.format("%.1f,%.1f", t.pts[i], t.pts[i + 1]) end
    lines[#lines + 1] = table.concat(out, " ")
  end
  for _, t in ipairs(ns.db and ns.db.tracks or {}) do add(t) end
  for _, t in ipairs(ns.db and ns.db.feedback and ns.db.feedback.roads or {}) do add(t) end
  if #lines == 0 then return "", 0 end
  local v, b = "", ""
  if GetBuildInfo then v, b = GetBuildInfo() end
  table.insert(lines, 1, string.format("%s (addon %s, game %s.%s)", F.TEXT_HEADER, tostring(ns.VERSION or "?"), tostring(v), tostring(b)))
  return table.concat(lines, "\n"), #lines - 1
end

-- For the options: how much is waiting to be shared.
function F.Counts()
  local fb = ns.db and ns.db.feedback
  return fb and fb.roads and #fb.roads or 0, fb and fb.trips and #fb.trips or 0
end

-- Navigation state: stops, current route (via Router), distance and ETAs.
local _, ns = ...
local Geo = ns.Geo
local unpack = unpack or table.unpack

local N = {}
ns.Nav = N

local DEFAULT_RUN = 7 -- yd/s, normal run speed
local ARRIVED_YD = 10
local REROUTE_SECONDS = 2 -- at most this often while moving (option rerouteSeconds, Performance)
local REROUTE_MOVED_YD = 15 -- ...and only after moving this far (scaled with it)
local REROUTE_STALE = 30 -- standing still: refresh this often anyway
local OFF_ROUTE_YD = 30 -- further than this from the route: recalculate it
-- A terrain search from the player's position finished: the route is recalculated to use
-- it, but at most this often: each recalculation starts searches from the new position,
-- and recalculating on each of those would loop (a recalculation a few times a second).
local SEARCH_RECALC_SECONDS = 3 -- (scaled with rerouteSeconds too)
-- How often a route off the player's way is recalculated (Options > Performance): seconds, and the
-- yards moved and seconds between recalculations for finished searches, scaled with it.
function N.RerouteTiming()
  local st = ns.settings and ns.settings.gps
  local secs = math.max(REROUTE_SECONDS, st and st.rerouteSeconds or REROUTE_SECONDS)
  local k = secs / REROUTE_SECONDS
  return secs, REROUTE_MOVED_YD * k, SEARCH_RECALC_SECONDS * k
end
local searchDirty, searchRecalcAt = false, -math.huge
local FOLLOW_MAX_AGE = 20 -- following the route: recalculate this often anyway
-- The walked part behind the player is trimmed off as they go (every TRIM_MOVED_YD), apart
-- from recalculations (at most every REROUTE_SECONDS and REROUTE_MOVED_YD): the route shrinks
-- behind them smoothly instead of in jumps. Only the next TRIM_AHEAD_YD of it is searched.
N.TRIM_MOVED_YD = 2
N.TRAM_MAP = 369 -- the Deeprun Tram's own map (Data/Transports.lua: its ride)
N.TRIM_AHEAD_YD = 120
-- A recalculation that comes out clearly longer while the player is still on the current
-- route (e.g. a terrain search near an obstacle hasn't finished yet) keeps the current
-- route: while the new one is provisional, or for up to KEEP_SECONDS if it's final.
local LONGER_SHARE, LONGER_YD = 1.1, 30 -- "clearly longer": more than 10% and 30 yd
local KEEP_SECONDS = 20

N.stops = {} -- { { x, y, cont, name, icon }, ... } in visiting order
N.dest = nil -- the next stop (N.stops[1])
N.route = nil -- Router result from the player's position at routeX/routeY
N.arrivedAt = nil
N.MAX_STOPS = 100 -- a trip's stops (imported lists, /way, placed)
N.PLAN_AHEAD = 8 -- stops routed and drawn ahead at most (option stopsAhead, default 3); the next comes in as each is reached
N.MAX_LOOP_STOPS = 60 -- a farming loop (nodes circled on the map)
N.LOOP_AHEAD = 4 -- a loop routes this many stops ahead (it goes round and round)
N.loop = false -- the stops are a loop: reaching one moves it to the end
N.ICON = "Interface\\TargetingFrame\\UI-RaidTargetingIcon_%d"
-- Marker for the k-th stop placed (raid icon numbers): square, star, triangle, diamond,
-- moon, circle. Cross and skull aren't used: after the six, the markers start over.
N.MARKER_ORDER = { 6, 1, 4, 3, 5, 2 }
function N.MarkerFor(k) return N.MARKER_ORDER[(k - 1) % #N.MARKER_ORDER + 1] end

-- The first marker (in MARKER_ORDER) that none of the given stop lists uses yet.
function N.NextMarker(...)
  local used = {}
  for _, list in ipairs({ ... }) do
    for _, d in ipairs(list) do if d.icon then used[d.icon] = true end end
  end
  local count = 0
  for _, list in ipairs({ ... }) do count = count + #list end
  if count < #N.MARKER_ORDER then
    for _, m in ipairs(N.MARKER_ORDER) do
      if not used[m] then return m end
    end
  end
  return N.MarkerFor(count + 1) -- all six in use: start over
end
-- Route color per marker (star, circle, diamond, triangle, moon, square, cross, skull),
-- for trips with several stops: each leg in the color of the stop it leads to.
N.MARKER_COLORS = {
  { 1, 0.85, 0.1 }, { 1, 0.5, 0.05 }, { 0.75, 0.3, 1 }, { 0.25, 0.85, 0.25 },
  { 0.65, 0.8, 1 }, { 0.15, 0.5, 1 }, { 1, 0.2, 0.15 }, { 0.92, 0.92, 0.92 },
}
local version = 0 -- bumped when the stops change (cache key for the stretches between stops)

local function Copy(d)
  return { x = d.x, y = d.y, cont = d.cont, name = d.name, icon = d.icon, corpse = d.corpse, questRoute = d.questRoute,
    tex = d.tex, boss = d.boss, enc = d.enc, z = d.z }
end

-- The stops are saved per character, so /reload and relogging keep the route.
local function Save()
  local cdb = ns.CharDB and ns.db and ns.CharDB()
  if not cdb then return end
  local list = {}
  for i, d in ipairs(N.stops) do list[i] = Copy(d) end
  cdb.stops = #list > 0 and list or nil
  cdb.loop = (N.loop and #list > 1) or nil
  cdb.dest = nil -- older single-destination save
  -- (the zones too high the player said yes to for this route: not asked again after a /reload)
  local ok = {}
  for z in pairs(N.redOk or {}) do ok[#ok + 1] = z end
  cdb.redOk = (#list > 0 and #ok > 0) and ok or nil
  local skip = {}
  for node in pairs(N.skipLearn or {}) do skip[#skip + 1] = node end
  cdb.skipLearn = (#list > 0 and #skip > 0) and skip or nil
  local rides = {}
  for key in pairs(N.skipRides or {}) do rides[#rides + 1] = key end
  cdb.skipRides = (#list > 0 and #rides > 0) and rides or nil
end
N.SaveStops = Save

local function Changed()
  N.dest = N.stops[1]
  N.route, N.arrivedAt = nil, nil
  version = version + 1
  Save()
end

-- A route through `stops` ({ x, y, cont, name?, icon? } each) in the given order, or in
-- the fastest order from the player's position when `fastest` is set.
-- Stops down in a city stay in the order they were placed (option, on by default): the
-- way through a city from one to the next is what the player means.
-- Whether stop `d` keeps the place it was given (option cityKeepOrder): down in a city, placed
-- by hand (the quest route button's stops are always put in the fastest order, in cities too).
function N.CityKept(d)
  local gps = ns.settings and ns.settings.gps
  if not gps or gps.cityKeepOrder == false or not ns.CityLevels then return false end
  return d.cont and ns.CityLevels[d.cont] and not d.questRoute and true or false
end

-- The stops aren't reordered at all: every one down in a city, in the order placed. With some
-- outside the city, the fastest order, the city's still in their order among themselves
-- (N.OrderStops): how you go round a city is up to you, not where the rest of the trip goes.
function N.KeepCityOrder()
  if #N.stops == 0 then return false end
  for _, d in ipairs(N.stops) do
    if not N.CityKept(d) then return false end
  end
  return true
end

-- In a dungeon or raid with the dungeon route on (option `dungeonRoute`) and its boss route
-- set: other routes wait (the quest route, stops added on the map, shared routes) until it's
-- done or turned off. `force`: the boss route itself.
function N.DungeonLocked()
  local gps = ns.settings and ns.settings.gps
  if not gps or gps.dungeonRoute == false then return false end
  local lvl = N.CurrentInstance and N.CurrentInstance()
  if not lvl then return false end
  for _, d in ipairs(N.stops) do
    if d.boss and d.cont == lvl then return true end
  end
  return false
end

local lockSaidAt = -100
function N.SayLocked()
  local now = GetTime and GetTime() or 0
  if now - lockSaidAt < 5 then return end
  lockSaidAt = now
  ns.Print("In a dungeon the dungeon route is on: other routes wait until its bosses are down. Turn it off in the map menu (Dungeon route) or with /agps dungeonroute.")
end

local function Locked(force)
  if force or not N.DungeonLocked() then return false end
  N.SayLocked()
  return true
end

-- Stops in zones too high for the player (red on the map; option avoidHighZones): { { zone
-- name, lowest level, highest }, ... } (each zone once), or nil. Not the zone the player is in.
function N.RedStops(list)
  local R = ns.Router
  local red = R and R.RedZones and R.RedZones()
  if not red then return nil end
  local px, py, pc = Geo.PlayerWorld()
  local here = px and R.ZoneAt(Geo.Base(pc), px, py)
  local out, seen = {}, {}
  for _, d in ipairs(list) do
    local z = d.x and R.ZoneAt(Geo.Base(d.cont), d.x, d.y)
    if z and red[z] and z ~= here and not seen[z] then
      seen[z] = true
      local lo, hi = R.ZoneLevels(z)
      local m = ns.Maps and ns.Maps[z]
      out[#out + 1] = { m and m.name or "?", lo, hi, z = z }
    end
  end
  return out[1] and out or nil
end

-- A route to stops in a zone too high for the player: asked first (GPSFrame's popup), and
-- `again` (setting them, confirmed) run on yes. True while asking.
local function AskRed(list, again)
  local zones = N.RedStops(list)
  if not zones or not (ns.GPS and ns.GPS.ConfirmRedZone) then return false end
  return ns.GPS.ConfirmRedZone(zones, list, function()
    for _, z in ipairs(zones) do N.redOk[z.z] = true end -- (asked: not again for passing through)
    again()
  end)
end

-- A route walking through a zone too high for the player (the way round there isn't, for
-- their faction): asked once per zone per route, like a stop in one. Rides (boats, flights)
-- over one don't count, nor the zones the route starts and ends in.
N.RED_ROUTE_YD = 60 -- walked this far in one: asked
N.redOk = {} -- zones the player said yes to, for this route
function N.RedOnRoute(r, px, py, cont)
  local R = ns.Router
  local red = R and R.RedZones and R.RedZones()
  if not (red and r and r.parts) then return nil end
  local exempt = { [R.ZoneAt(Geo.Base(cont), px, py)] = true }
  for _, d in ipairs(N.stops) do exempt[R.ZoneAt(Geo.Base(d.cont), d.x, d.y)] = true end
  local yards = {}
  for _, part in ipairs(r.parts) do
    local c, pts = Geo.Base(part.cont), part.pts
    for i = 1, #pts - 3, 2 do
      if part.kinds[(i + 1) / 2] ~= N.KIND_TRANSPORT then
        for z, yd in pairs(R.ZoneYards(c, pts[i], pts[i + 1], pts[i + 2], pts[i + 3])) do
          if red[z] and not exempt[z] and not N.redOk[z] then yards[z] = (yards[z] or 0) + yd end
        end
      end
    end
  end
  local out = {}
  for z, yd in pairs(yards) do
    if yd >= N.RED_ROUTE_YD then
      local lo, hi = R.ZoneLevels(z)
      local m = ns.Maps and ns.Maps[z]
      out[#out + 1] = { m and m.name or "?", lo, hi, z = z, yards = yd }
    end
  end
  table.sort(out, function(a, b) return a.yards > b.yards end)
  return out[1] and out or nil
end

function N.SetStops(stops, fastest, force)
  if Locked(force) then return false end
  if force ~= "red" then N.redOk, N.skipLearn = {}, {} N.ClearSkippedRides() end -- (a new route: its zones asked about again, its detours and rides back)
  -- ("red": asked and confirmed; true: the dungeon route, its own)
  if not force and AskRed(stops, function() N.SetStops(stops, fastest, "red") end) then return false, true end
  N.stops, N.loop = {}, false
  for i, d in ipairs(stops) do
    if i > N.MAX_STOPS then break end
    local c = Copy(d)
    c.icon = c.icon or N.MarkerFor(i)
    N.stops[#N.stops + 1] = c
  end
  Changed()
  if fastest and #N.stops > 1 and not N.KeepCityOrder() then N.OrderStops() end
  return true
end

-- Add a stop at the end of the route (then reorder if `fastest`).
function N.AddStop(d, fastest, force)
  if Locked(force) then return false end
  if not force and AskRed({ d }, function() N.AddStop(d, fastest, "red") end) then return false, true end
  if #N.stops >= (N.loop and N.MAX_LOOP_STOPS or N.MAX_STOPS) then return false end
  local c = Copy(d)
  c.icon = c.icon or N.NextMarker(N.stops)
  N.stops[#N.stops + 1] = c
  Changed()
  if fastest and not N.loop and #N.stops > 1 and not N.KeepCityOrder() then N.OrderStops() end
  return true
end

-- Order for a loop through points { x, y } starting nearest (px, py): nearest-next, then
-- 2-opt on the closed loop (straight distances: the points are close together, one area).
function N.LoopOrder(pts, px, py)
  local n = #pts
  if n < 2 then return { 1 } end
  local function d(a, b) return math.sqrt((a.x - b.x) ^ 2 + (a.y - b.y) ^ 2) end
  local used, order = {}, {}
  local cur = { x = px, y = py }
  for k = 1, n do
    local best, bd
    for i = 1, n do
      if not used[i] then
        local di = d(cur, pts[i])
        if not bd or di < bd then best, bd = i, di end
      end
    end
    used[best], order[k], cur = true, best, pts[best]
  end
  local function len(o)
    local t = 0
    for k = 1, n do t = t + d(pts[o[k]], pts[o[k % n + 1]]) end
    return t
  end
  local improved, bestLen, rounds = true, len(order), 0
  while improved and rounds < 50 do
    improved, rounds = false, rounds + 1
    for a = 1, n - 1 do
      for b = a + 1, n do
        local o = {}
        for k = 1, n do o[k] = order[k] end
        for k = 0, math.floor((b - a) / 2) do o[a + k], o[b - k] = o[b - k], o[a + k] end
        local l = len(o)
        if l < bestLen - 1e-6 then order, bestLen, improved = o, l, true end
      end
    end
  end
  return order
end

-- A farming loop through `nodes` ({ x, y, cont, name }): visited round and round, each
-- reached one moving to the end. Starts at the node nearest the player.
function N.SetLoop(nodes, px, py)
  if Locked() then return false end
  local order = N.LoopOrder(nodes, px or nodes[1].x, py or nodes[1].y)
  N.stops = {}
  for k, i in ipairs(order) do
    if k > N.MAX_LOOP_STOPS then break end
    local c = Copy(nodes[i])
    c.icon = N.MarkerFor(k)
    N.stops[k] = c
  end
  N.loop = #N.stops > 1
  Changed()
end

-- How many stops the route is worked out through (and drawn): a few ahead. A long list
-- (an imported guide) is routed PLAN_AHEAD stops at a time; reaching one brings in the next.
function N.PlannedStops()
  if N.loop then return math.min(#N.stops, 1 + N.LOOP_AHEAD) end
  local st = ns.settings and ns.settings.gps
  local ahead = math.max(1, math.min(N.PLAN_AHEAD, math.floor(tonumber(st and st.stopsAhead) or 3)))
  return math.min(#N.stops, ahead)
end

-- A stop's icon: its own (a city location's, say), else its marker.
function N.StopIcon(d)
  return d.tex or N.ICON:format(d.icon or 1)
end

-- Whether the route is a quest route (the Sprint button): a stop made for a quest is left.
function N.OnQuestRoute()
  for _, d in ipairs(N.stops) do
    if d.questRoute then return true end
  end
  return false
end

-- Remove stop i from the route (the route is recomputed).
function N.RemoveStop(i)
  if not N.stops[i] then return end
  table.remove(N.stops, i)
  Changed()
end

function N.SetDestination(x, y, cont, name)
  return N.SetStops({ { x = x, y = y, cont = cont, name = name, icon = 1 } })
end

-- Changes whenever the stops do (a new route, a stop added, removed or reached).
function N.Version() return version end

function N.Clear()
  N.stops, N.loop = {}, false
  N.redOk, N.skipLearn = {}, {}
  N.ClearSkippedRides()
  Changed()
end

-- Called at login: bring back the saved stops.
function N.Restore()
  local cdb = ns.CharDB()
  local list = cdb.stops or (cdb.dest and { cdb.dest }) or {}
  N.stops = {}
  for _, d in ipairs(list) do
    if d.x and d.y and d.cont then N.stops[#N.stops + 1] = Copy(d) end
  end
  N.loop = cdb.loop and #N.stops > 1 or false
  N.redOk = {}
  for _, z in ipairs(#N.stops > 0 and cdb.redOk or {}) do N.redOk[z] = true end
  N.skipLearn = {}
  for _, node in ipairs(#N.stops > 0 and cdb.skipLearn or {}) do N.skipLearn[node] = true end
  N.skipRides = {}
  for _, key in ipairs(#N.stops > 0 and cdb.skipRides or {}) do N.skipRides[key] = true end
  if next(N.skipRides) then N.FlightsChanged() end
  N.dest = N.stops[1]
  N.route, N.arrivedAt = nil, nil
  version = version + 1
end

---------------------------------------------------------------------------
-- Planning across transports (zeppelins, boats)
---------------------------------------------------------------------------

N.KIND_TRANSPORT, N.KIND_PLANNED = 2, 3 -- route segment kinds beyond Router's road/offroad
N.WALK_FACTOR = 1.35 -- straight-line yards -> expected route yards, for planning only
N.DOCK_YD = 40 -- "at the dock" radius

-- Planning a walk from (x1, y1) to (x2, y2) on `cont`: its straight yards, plus what the router
-- charges for the yards in zones too high for the player (Router.LEVEL_FACTOR each: the way round
-- them, or through at a cost), but in the zones in `exempt` (the trip's own ends: where the player
-- starts and the stop is; not a dock walked past, which would let the walk through the zone it's
-- in). Else a flight over them lost to a walk that looked short in a straight line.
-- (Sampled every PLAN_ZONE_STEP yards; the yards in each zone between docks and flight masters
-- remembered, `keep`.)
N.PLAN_ZONE_STEP = 64
local planYards = { red = nil } -- [key] = { [zone] = yards }, for the zones too high now (`red`)
function N.PlanYards(cont, x1, y1, x2, y2, keep, exempt)
  local d = math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2)
  local R = ns.Router
  local red = R and R.RedZones and R.RedZones()
  if not red or not (ns.Zones and ns.Zones[Geo.Base(cont)]) then return d end
  if planYards.red ~= red then planYards = { red = red } end
  local key = keep and string.format("%d:%.0f:%.0f:%.0f:%.0f", cont, x1, y1, x2, y2)
  local zy = key and planYards[key]
  if not zy then
    zy = {}
    local c = Geo.Base(cont)
    local n = math.max(1, math.ceil(d / N.PLAN_ZONE_STEP))
    for k = 0, n - 1 do
      local t = (k + 0.5) / n
      local z = R.ZoneAt(c, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
      if red[z] then zy[z] = (zy[z] or 0) + d / n end
    end
    if key then planYards[key] = zy end
  end
  local extra = 0
  for z, yd in pairs(zy) do
    if not (exempt and exempt[z]) then extra = extra + yd end
  end
  return d + extra * (R.LEVEL_FACTOR - 1)
end

---------------------------------------------------------------------------
-- Flight paths (Data/Flights.lua) between the flight masters this character knows
---------------------------------------------------------------------------

N.FLIGHT_SPEED = 32 -- yd/s along the flight path
N.FLIGHT_OVERHEAD = 15 -- s: talking to the flight master, taking off and landing

local flightCache -- { key, masters = { [node] = { cont, x, y, name } }, trips = { [from] = { [to] = row } } }

-- Flight masters (Data/Pois.lua kind 1): { [nodeID] = { cont, x, y, name, faction } }; cont
-- is the city level for one down in a city (Undercity's: p[7]).
local function Masters()
  local m = {}
  for cont, list in pairs(ns.Pois or {}) do
    for _, p in ipairs(list) do
      if p[1] == 1 then
        local lvl = p[7] and ns.CityLevels and ns.CityLevels[p[7]] and p[7] -- (with the city's data)
        m[p[5]] = { lvl or cont, p[2], p[3], p[4], p[6] }
      end
    end
  end
  return m
end

-- The flight master nodes this character knows (seen on a flight map: Taxi.lua).
function N.KnownFlightNodes()
  local known, n = {}, 0
  local cdb = ns.CharDB and ns.CharDB()
  for _, entry in pairs(cdb and cdb.taxiNodes or {}) do
    for _, node in ipairs(entry.nodes or {}) do
      if node.known and node.nodeID and not known[node.nodeID] then
        known[node.nodeID] = true
        n = n + 1
      end
    end
  end
  return known, n
end

-- Rides the player left out of this route (right-click "Remove?" on a ride's pin: GPSFrame): not taken
-- again on it, rerouting or after a /reload (saved with the stops); a new route clears it. A flight's is
-- one connection between two flight masters (either way: "h:a:b"), so every flight over it goes too; a
-- boat's, a zeppelin's, the tram's, its row's; a teleport's, its item or spell.
N.skipRides = {}
local function HopKey(a, b)
  a, b = tostring(a), tostring(b)
  if b < a then a, b = b, a end
  return "h:" .. a .. ":" .. b
end
-- The key ride row `t` is left out by (`hop`: a flight's k-th connection, from its k-th flight master).
function N.RideKey(t, hop)
  if hop and t.hops and t.hops[hop + 1] then return HopKey(t.hops[hop], t.hops[hop + 1]) end
  if t.use then return "u:" .. (t.item and ("i" .. t.item) or ("s" .. tostring(t.spell or t[8]))) end
  if t.from and t.to then return "f:" .. tostring(t.from) .. ">" .. tostring(t.to) end
  return string.format("t:%s:%.0f,%.0f>%.0f,%.0f", tostring(t[8]), t[2], t[3], t[5], t[6])
end
function N.SkipRide(t, hop)
  N.skipRides[N.RideKey(t, hop)] = true
  N.FlightsChanged() -- (the flights over a connection left out: worked out again without it)
  N.SaveStops()
end
function N.ClearSkippedRides()
  if next(N.skipRides or {}) then N.FlightsChanged() end
  N.skipRides = {}
end

-- Recompute the flights on the next plan (a flight map was opened, the option changed).
function N.FlightsChanged()
  flightCache = nil
  N.Invalidate(true, true) -- (also forgets the stop-to-stop times)
end

-- A route option the player changed (flight paths, the hearthstone, class teleports, the zones
-- and towns avoided): the whole trip worked out again at once, not compared with the one shown
-- (a longer one isn't held back), the stops put in the fastest order again under it (the order
-- was chosen with the old one: a flight since turned off), and the map redrawn now.
function N.OptionsChanged()
  flightCache = nil
  if ns.Teleports and ns.Teleports.Changed then ns.Teleports.Changed() end
  N.Invalidate(true, true)
  local st = ns.settings and ns.settings.gps
  if st and st.fastestOrder and #N.stops > 1 and not N.loop and not N.KeepCityOrder() then N.OrderStops() end
  if ns.GPS and ns.GPS.Redraw then ns.GPS.Redraw() end
end

-- The character's faction as in Data/Pois.lua ("A" / "H"), or nil when unknown.
local function Faction()
  local f = ns.CharDB and ns.CharDB().faction
  return f == "Alliance" and "A" or f == "Horde" and "H" or nil
end
N.Faction = Faction

-- Whether transport row t (a boat, a zeppelin, a lift, a dungeon's portal) is one the player's
-- faction can take: not with either end among the other faction's guards (Data/Hostile.lua:
-- within DOCK_GUARDS_YD of them; the ship waits off the quay). Worked out once per faction.
N.DOCK_GUARDS_YD = 100
local usable = {}
function N.TransportUsable(t)
  local side = Faction()
  local R = ns.Router
  if not (side and R and R.HostileAt and ns.Hostile) then return true end
  usable[side] = usable[side] or {}
  local v = usable[side][t]
  if v == nil then
    local function guarded(c, x, y)
      for a = 0, 15 do
        for k = 0, 3 do
          local r = N.DOCK_GUARDS_YD * k / 3
          if R.HostileAt(c, x + math.cos(a * math.pi / 8) * r, y + math.sin(a * math.pi / 8) * r, side) then return true end
        end
      end
      return false
    end
    v = not (guarded(t[1], t[2], t[3]) or guarded(t[4], t[5], t[6]))
    usable[side][t] = v
  end
  return v
end

-- Every trip between two known flight masters, connecting through known ones like the
-- game does: rows in the transports' format { c, x1, y1, c, x2, y2, seconds, "flight",
-- fromName, toName, "flight master", pts = { x, y, ... } via the connecting stops }.
-- Seconds: learned ones (Taxi.lua records each flight taken) or the path length.
-- Also trips from flight masters of the character's faction not learned yet but with a
-- direct flight to a known one: talking to one learns it, and the flight leaves from there
-- (rows marked learn = true). Flights only ever land at known ones.
local function Flights()
  if ns.settings and ns.settings.gps.useFlights == false or not ns.Flights then return nil end
  if N.corpse then return nil end -- a ghost can't take a flight
  local known, count = N.KnownFlightNodes()
  if count < 1 then return nil end
  local fac = Faction()
  local key = count .. (fac or "")
  if flightCache and flightCache.key == key then return flightCache end
  local masters = Masters()
  local adj, fresh = {}, {}
  for _, f in ipairs(ns.Flights) do
    local a, b = f[1], f[2]
    local ma, mb = masters[a], masters[b]
    if ma and mb and known[b] then
      if known[a] then
        adj[a] = adj[a] or {}
        adj[a][#adj[a] + 1] = { b, f[3] }
      elseif fac and ma[5] and string.find(ma[5], fac, 1, true) then
        fresh[a] = fresh[a] or {}
        fresh[a][#fresh[a] + 1] = { b, f[3] }
      end
    end
  end
  local learned = ns.CharDB and ns.CharDB().flights or {}
  local trips = {}
  local starts = {}
  for from in pairs(adj) do starts[from] = adj[from] end
  for from, edges in pairs(fresh) do starts[from] = edges end
  for from, first in pairs(starts) do
    -- shortest flight (yards) to every other known master
    local dist, prev, done = { [from] = 0 }, {}, {}
    while true do
      local u, best
      for v, dv in pairs(dist) do
        if not done[v] and (not best or dv < best) then u, best = v, dv end
      end
      if not u then break end
      done[u] = true
      for _, e in ipairs(u == from and first or adj[u] or {}) do
        local v, nd = e[1], best + e[2]
        if not N.skipRides[HopKey(u, v)] and (not dist[v] or nd < dist[v]) then dist[v], prev[v] = nd, u end
      end
    end
    trips[from] = {}
    for to, yards in pairs(dist) do
      if to ~= from then
        local a, b = masters[from], masters[to]
        local pts, cur, stops = {}, to, {}
        while cur do
          table.insert(stops, 1, cur)
          cur = prev[cur]
        end
        for _, s in ipairs(stops) do
          pts[#pts + 1], pts[#pts + 2] = masters[s][2], masters[s][3]
        end
        local took = learned[a[4] .. " > " .. b[4]]
        local secs = took and took.seconds or yards / N.FLIGHT_SPEED + N.FLIGHT_OVERHEAD
        trips[from][to] = { a[1], a[2], a[3], b[1], b[2], b[3], secs, "flight", a[4], b[4],
          fresh[from] and "new flight master" or "flight master", pts = pts, learn = fresh[from] and true or nil,
          from = from, to = to, hops = stops }
      end
    end
  end
  -- every landing is a place on the map too, with flights on from there or not
  local lands = {}
  for _, to in pairs(trips) do
    for node in pairs(to) do lands[node] = true end
  end
  for node in pairs(lands) do trips[node] = trips[node] or {} end
  flightCache = { key = key, masters = masters, trips = trips }
  return flightCache
end

-- The rides route `r` takes that the player can leave out of it (right-click on their pins: GPSFrame),
-- each once: { cont, x, y, title, kind, ride = row, hop = k, dock = { transport, side } } where it's
-- boarded: a flight's at each flight master it flies on from (a connection each), a teleport's where it
-- lands; none for the flight being flown or a dungeon's way in.
N.RIDE_NAMES = { zeppelin = "Zeppelin", boat = "Boat", tram = "Deeprun Tram", lift = "Lift" }
local rowIndex = setmetatable({}, { __mode = "k" }) -- [transport row] = its index in ns.Transports
function N.RidePins(r)
  local out, seen = {}, {}
  if not r then return out end
  local masters = flightCache and flightCache.masters
  local function add(p)
    local key = N.RideKey(p.ride, p.hop)
    if seen[key] then return end
    seen[key] = true
    out[#out + 1] = p
  end
  local function legs(list)
    for _, leg in ipairs(list or {}) do
      local t = leg.ride
      if t and not t.flying and t[8] ~= "portal" then
        if t.hops then
          for k = 1, #t.hops - 1 do
            local a, b = masters and masters[t.hops[k]], masters and masters[t.hops[k + 1]]
            if a and b then
              add({ cont = a[1], x = a[2], y = a[3], kind = "flight", ride = t, hop = k,
                title = "Flight: " .. tostring(a[4]) .. " to " .. tostring(b[4]) })
            end
          end
        elseif t.use then
          add({ cont = t[4], x = t[5], y = t[6], kind = "teleport", ride = t,
            title = tostring(t[8]):gsub("^%l", string.upper) .. " to " .. tostring(t[10] ~= "" and t[10] or "?") })
        elseif t[8] ~= "flight" then
          local back = leg.from == 2
          if not next(rowIndex) then
            for i, row in ipairs(ns.Transports or {}) do rowIndex[row] = i end
          end
          local i = rowIndex[t]
          add({ cont = back and t[4] or t[1], x = back and t[5] or t[2], y = back and t[6] or t[3], kind = t[8], ride = t,
            title = (N.RIDE_NAMES[t[8]] or "Ride") .. " to " .. tostring(back and t[9] or t[10]),
            dock = i and { i, back and 2 or 1 } or nil })
        end
      end
    end
  end
  local stretches = r.stretches
  legs(r.legs)
  for i = 2, stretches and N.PlannedStops() or 0 do
    if stretches[i] then legs(stretches[i].legs) end
  end
  return out
end

-- Fastest sequence of legs from (px, py) on `cont` to stop d (default: the next stop),
-- walking, taking transports (Data/Transports.lua) and flights between known flight
-- masters. Legs: { walk = true, cont, x1, y1, x2, y2 } or { ride = row, from = 1|2 }
-- (a transport row, or a flight row in the same format; from = which end we board at).
-- `teleports`: rows (Teleports.lua) usable right away from (px, py): hearthstone, etc.
-- `direct`: seconds the walk straight from (px, py) to the stop takes at least (routed: see Stretch).
function N.Plan(cont, px, py, speed, d, teleports, direct)
  d = d or N.dest
  local nodes = { { cont, px, py }, { d.cont, d.x, d.y } }
  for _, row in ipairs(teleports or {}) do
    nodes[#nodes + 1] = { row[4], row[5], row[6], tp = row }
  end
  -- (a dungeon's way in only for a trip from or to inside it, never through one as a shortcut;
  -- and the dungeon one is entered from, Blackrock Spire's for Blackwing Lair)
  local inside = { [cont] = true, [d.cont] = true }
  for _ = 1, 2 do
    for _, t in ipairs(ns.Transports or {}) do
      if t[8] == "portal" and inside[t[4]] and ns.CityLevels and ns.CityLevels[t[1]] then inside[t[1]] = true end
    end
  end
  for i, t in ipairs(ns.Transports or {}) do
    if (t[8] ~= "portal" or inside[t[4]]) and N.TransportUsable(t) then
      nodes[#nodes + 1] = { t[1], t[2], t[3], t = i, side = 1 }
      nodes[#nodes + 1] = { t[4], t[5], t[6], t = i, side = 2 }
    end
  end
  local fl = Flights()
  if fl then
    for node in pairs(fl.trips) do
      local m = fl.masters[node]
      nodes[#nodes + 1] = { m[1], m[2], m[3], fm = node }
    end
  end
  -- (the trip's own ends: zones too high there are where the player is and the stop is)
  local Rt = ns.Router
  local exempt = Rt and Rt.ZoneAt and { [Rt.ZoneAt(Geo.Base(cont), px, py)] = true, [Rt.ZoneAt(Geo.Base(d.cont), d.x, d.y)] = true }
  local dist, prev, rode, done = { [1] = 0 }, {}, {}, {}
  local breathe = ns.Router and ns.Router.Breathe
  local expanded = 0
  while true do
    local u, best
    for i in pairs(dist) do
      if not done[i] and (not best or dist[i] < best) then u, best = i, dist[i] end
    end
    if not u or u == 2 then break end
    done[u] = true
    expanded = expanded + 1
    if breathe then breathe(expanded, 1) end -- (in a background job: a pause after each place: each weighs them all)
    local a = nodes[u]
    for v, b in ipairs(nodes) do
      if not done[v] then
        local cost, ride
        -- (with `direct` set, the way with a ride is wanted: no walk on from a place walked to, which
        -- would only be the walk there in two, a flight master walked past)
        if a[1] == b[1] and not (direct and u ~= 1 and not rode[u]) then -- (zones too high on the way: as the router weighs them)
          cost = N.PlanYards(a[1], a[2], a[3], b[2], b[3], u ~= 1 and v ~= 2, exempt) * N.WALK_FACTOR / speed
          if u == 1 and v == 2 and direct then cost = math.max(cost, direct) end
        end
        if a.t and b.t == a.t and a.side ~= b.side and not N.skipRides[N.RideKey(ns.Transports[a.t])] then
          local secs = ns.Transports[a.t][7]
          if not cost or secs < cost then cost, ride = secs, { ns.Transports[a.t], a.side } end
        end
        if u == 1 and b.tp and not N.skipRides[N.RideKey(b.tp)] and (not cost or b.tp[7] < cost) then -- a teleport, from where we stand
          cost, ride = b.tp[7], { b.tp, 1 }
        end
        if a.fm and b.fm then
          local row = fl.trips[a.fm][b.fm]
          if row and not N.skipRides[N.RideKey(row)] and (not cost or row[7] < cost) then cost, ride = row[7], { row, 1 } end
        end
        if cost and (not dist[v] or dist[u] + cost < dist[v]) then
          dist[v], prev[v], rode[v] = dist[u] + cost, u, ride
        end
      end
    end
  end
  if not dist[2] then return nil end
  local path, cur = {}, 2
  while cur do
    table.insert(path, 1, cur)
    cur = prev[cur]
  end
  local legs = {}
  for i = 2, #path do
    local a, b = nodes[path[i - 1]], nodes[path[i]]
    local r = rode[path[i]]
    local last = legs[#legs]
    if r then
      legs[#legs + 1] = { ride = r[1], from = r[2] }
    elseif last and last.walk and last.cont == a[1] then
      -- (a dock or flight master only walked past: one walk, the router's own way; routed in
      -- two, each would be free in the zone of the point between, one too high for the player)
      last.x2, last.y2 = b[2], b[3]
    else
      legs[#legs + 1] = { walk = true, cont = a[1], x1 = a[2], y1 = a[3], x2 = b[2], y2 = b[3] }
    end
  end
  return legs, dist[2]
end

-- For a bug report (/agps debug): how the trip to the next stop is planned from here, and why:
-- the character's level and the zones too high for it, the flight masters known, the plan and
-- its time, the planned walk straight there, and the route as it stands.
function N.DescribePlan()
  local d = N.stops[1]
  if not d then return "no stop" end
  local px, py, cont = Geo.PlayerWorld()
  if not px then return "no position" end
  cont = N.PlayerLevel(cont)
  local _, walk = N.Speeds()
  local R = ns.Router
  local red = R and R.RedZones and R.RedZones()
  local names = {}
  for z in pairs(red or {}) do names[#names + 1] = ns.Maps and ns.Maps[z] and ns.Maps[z].name or tostring(z) end
  table.sort(names)
  local _, known = N.KnownFlightNodes()
  local legs, secs = N.Plan(cont, px, py, walk, d)
  local steps = {}
  for _, l in ipairs(legs or {}) do
    steps[#steps + 1] = l.ride and ("ride " .. tostring(l.ride[10] or l.ride[8]) .. string.format(" %.0fs", l.ride[7] or 0))
      or string.format("walk %.0f yd", math.sqrt((l.x2 - l.x1) ^ 2 + (l.y2 - l.y1) ^ 2))
  end
  local direct
  if Geo.Base(d.cont) == Geo.Base(cont) and R and R.ZoneAt then
    local exempt = { [R.ZoneAt(Geo.Base(cont), px, py)] = true, [R.ZoneAt(Geo.Base(d.cont), d.x, d.y)] = true }
    direct = N.PlanYards(cont, px, py, d.x, d.y, false, exempt) * N.WALK_FACTOR / walk
  end
  local lvl = UnitLevel and UnitLevel("player")
  local st = ns.settings and ns.settings.gps or {}
  local r = N.route
  return string.format("from (%d, %.0f, %.0f) to (%s, %.0f, %.0f) level=%s walk=%.1f avoidHigh=%s useFlights=%s "
    .. "flight masters known=%s | too high: %s | plan %.0fs: %s | walk straight there %.0fs | route %s yd, rides %s s | %s",
    cont, px, py, tostring(d.cont), d.x, d.y, tostring(lvl), walk, tostring(st.avoidHighZones ~= false),
    tostring(st.useFlights ~= false), tostring(known), table.concat(names, ", "), secs or -1, table.concat(steps, " > "),
    direct or -1, r and string.format("%.0f", r.totalYards or 0) or "none", r and string.format("%.0f", r.totalRide or 0) or "-",
    N.lastRideCheck or "no ride check")
end

-- One stretch of the route, from (sx, sy) on `cont` to stop `d`: every walking leg routed
-- over its own continent's roads, transport rides as straight dotted lines.
-- { parts = { { cont, pts, kinds }, ... }, legs, first = yards before any ride,
--   walk = walking yards, ride = seconds on transports, road = yards on roads }
-- opts.transient: (sx, sy) is the player's position (see Router's Walk).
-- Whether the player is indoors (a building, a cave: IsIndoors), or nil when unknown: over a
-- cave under walkable ground, whether they're up top or down in it (Router.CaveLevel).
function N.Indoors()
  if not IsIndoors then return nil end
  local ok, v = pcall(IsIndoors)
  if not ok or (ns.IsSecret and ns.IsSecret(v)) then return nil end
  return v and true or false
end

-- The player's height (world z), or nil when unknown: under a capital's floor, whether they're
-- up on it or down under it (Router.CaveDown).
function N.PlayerZ()
  local x, _, _, z = Geo.PlayerWorld()
  if not x or not z or z == 0 then return nil end
  return z
end

-- A walking leg's options: `base` with the heights it starts and ends at, when known (a
-- dungeon's floors over floors: Router takes the roads on those floors).
local function LegOpts(base, z, tz)
  if not z and not tz then return base end
  local o = {}
  for k, v in pairs(base) do o[k] = v end
  o.z, o.tz = z or base.z, tz
  return o
end

-- `sz`: the height the stretch starts at, when known (a stop's).
-- A walk planned the whole way (from the straight line) against the best way with a ride (a
-- flight, a boat), both as routed: the straight line's yards say little round a lake or over
-- mountains, and through zones too high for the player they count many times over (for either:
-- a walk from a flight master too). The walks are routed and weighed as planning does (the zones
-- too high on them, but the trip's own ends), the rides at their times. (Reported: level 14 from
-- Brill into Arathi Highlands: planned on foot over Lordamere Lake and Alterac, the walk went round
-- by Silverpine, 7.6k yd, past the Sepulcher's flight master, the flight there from Undercity not
-- taken.) Worked out once per stop from about here (RIDE_CHECK_YD), remembered.
N.RIDE_CHECK_MIN_YD = 800 -- (shorter walks: not worth a second look)
N.RIDE_CHECK_YD = 200
local rideCheck = {} -- [key] = whether the way with a ride won
local rideLast = {} -- [stop] = the last answer for it (from wherever: used while this square's is worked out)
-- Seconds for a walk along `pts` as planning weighs it: the zones too high for the player (but
-- `exempt`) counted extra (PlanYards), and water at swimming's cost (Passability's: across the sea
-- to an island isn't a walk to take over the boat).
local function Weighed(cont, pts, walk, exempt, blocked)
  local P = ns.Passability
  -- (yards straight over ground the terrain blocks, `blocked`: at the router's own cost for them,
  -- not ruled out: a bridge the terrain doesn't know, Thandol Span, was one on both ways)
  local yards = (blocked or 0) * ((ns.Router and ns.Router.BLOCKED_PENALTY or 12) - 1)
  for i = 1, #pts - 3, 2 do
    local x1, y1, x2, y2 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
    yards = yards + N.PlanYards(cont, x1, y1, x2, y2, false, exempt)
    local c = P and P.SegmentCost and P.SegmentCost(cont, x1, y1, x2, y2, 0)
    if c then yards = yards + math.max(0, c - math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2)) end
  end
  return yards / walk
end
N.WeighedWalk = Weighed -- (the trip sweep's checks weigh as this does)

-- A routed walk that isn't one: no way there found on foot (a line across). (Yards over blocked
-- ground are weighed, Weighed's `blocked`: the sea to an island costs a lot, a bridge a little.)
local function Unwalkable(r)
  return r.unconnected
end
N.Unwalkable = Unwalkable
-- Walks between fixed points (a lift to a flight master, a landing to the stop: not from the
-- player) routed once and kept: rerouting as the player moves redoes only the walk from them
-- (a long walk after a flight, routed again on every recalculation, was a lag spike each time).
-- Forgotten with the route's other cached parts (Invalidate), and never a provisional one.
N.LEG_MEMO_MAX = 64
local legMemo, legMemoN = {}, 0
local function LegRoute(cont, x1, y1, x2, y2, o, fixed)
  if not fixed then return ns.Router.Route(cont, x1, y1, x2, y2, o) end
  local key = string.format("%d:%.1f:%.1f:%.1f:%.1f:%s:%s:%s", cont, x1, y1, x2, y2, tostring(o.z), tostring(o.tz),
    tostring(o.offroad))
  local r = legMemo[key]
  if r then return r end
  r = ns.Router.Route(cont, x1, y1, x2, y2, o)
  if not r.pending then
    if legMemoN >= N.LEG_MEMO_MAX then legMemo, legMemoN = {}, 0 end
    legMemo[key], legMemoN = r, legMemoN + 1
  end
  return r
end

-- Each walking leg of `legs` routed (a list by leg index), with the heights they start and end
-- at (a ride's ends: into a dungeon, down a lift; the stop's).
local function EndZ(t, e) return e == 1 and t.z1 or e == 2 and t.iz or nil end
local function WalkRoutes(legs, sx, sy, d, opts, sz)
  local out, legZ = {}, sz
  for li, leg in ipairs(legs) do
    if leg.ride then
      legZ = EndZ(leg.ride, leg.from == 1 and 2 or 1)
    else
      local toStop = leg.x2 == d.x and leg.y2 == d.y
      local nxt = legs[li + 1]
      local endZ = toStop and N.StopZ(d) or (nxt and nxt.ride and EndZ(nxt.ride, nxt.from)) or nil
      local fromPlayer = opts.transient and leg.x1 == sx and leg.y1 == sy
      out[li] = LegRoute(leg.cont, leg.x1, leg.y1, leg.x2, leg.y2, LegOpts(fromPlayer and opts or opts.fixed, legZ, endZ),
        not fromPlayer)
      legZ = toStop and endZ or nil
    end
  end
  return out
end

-- The walk the whole way against the best way with a ride, from about (sx, sy): { won, final },
-- with both walks routed from the spot rounded to RIDE_CHECK_ROUND (searches between fixed points,
-- remembered: a comparison from about here comes out the same, and final once they're done).
N.RIDE_CHECK_ROUND = 50
local function CompareRide(cont, sx, sy, d, walk, tps, opts, sz)
  local q = N.RIDE_CHECK_ROUND
  local qx, qy = math.floor(sx / q + 0.5) * q, math.floor(sy / q + 0.5) * q
  local legs = N.Plan(cont, qx, qy, walk, d, tps, math.huge)
  local fixed = { fixed = opts.fixed }
  local lr = LegRoute(cont, qx, qy, d.x, d.y, LegOpts(opts.fixed, sz, N.StopZ(d)), true)
  if not (legs and lr and lr.pts and lr.length and lr.length >= N.RIDE_CHECK_MIN_YD) then return { won = false, final = true } end
  local routes = WalkRoutes(legs, qx, qy, d, fixed, sz)
  local Rt = ns.Router
  local exempt = Rt and Rt.ZoneAt and { [Rt.ZoneAt(Geo.Base(cont), sx, sy)] = true, [Rt.ZoneAt(Geo.Base(d.cont), d.x, d.y)] = true }
  local secs, pending = 0, lr.pending
  for li, leg in ipairs(legs) do
    if leg.ride then
      secs = secs + (leg.ride[7] or 0)
    elseif routes[li] then
      secs = secs + (Unwalkable(routes[li]) and math.huge or Weighed(leg.cont, routes[li].pts, walk, exempt, routes[li].blocked))
      pending = pending or routes[li].pending
    end
  end
  local walkSecs = Unwalkable(lr) and math.huge or Weighed(cont, lr.pts, walk, exempt, lr.blocked)
  local won = secs < walkSecs or (secs == math.huge and walkSecs == math.huge) -- (neither: the plan's ride)
  N.lastRideCheck = string.format("walk routed %.0fs (%.0f yd) vs with rides %.0fs: %s%s", walkSecs, lr.length, secs,
    won and "rides" or "walk", pending and " (provisional, not remembered)" or "")
  return { won = won, final = not pending }
end

-- The walk planned the whole way, or the best way with a ride: its legs and their routes, or nil
-- (the walk). Compared in the background (Router.Background: a long walk and the ride's walks
-- routed in full were a tenth of a second and more in one frame, on every recalculation while the
-- searches were still running); meanwhile the plan's walk, and the route worked out again once the
-- comparison says ride. Remembered once final (not on provisional routes: a straight line while a
-- terrain search runs makes the walk look short).
local function RideInstead(cont, sx, sy, d, walk, tps, opts, sz)
  local legs = N.Plan(cont, sx, sy, walk, d, tps, math.huge)
  local rides = false
  for _, leg in ipairs(legs or {}) do rides = rides or leg.ride ~= nil end
  if not rides then return nil end
  local lvl = UnitLevel and UnitLevel("player")
  local key = string.format("%d:%d:%d:%s:%.0f:%.0f:%s", cont, math.floor(sx / N.RIDE_CHECK_YD), math.floor(sy / N.RIDE_CHECK_YD),
    tostring(d.cont), d.x, d.y, tostring(lvl))
  -- (meanwhile, crossing into another RIDE_CHECK_YD square: the last answer for this stop, not the
  -- plan's walk: that walked the whole way routed in the frame, then the ride again once compared)
  local stopKey = string.format("%s:%.0f:%.0f:%s", tostring(d.cont), d.x, d.y, tostring(lvl))
  local won = rideCheck[key]
  if won == nil then
    ns.Router.Background("ride:" .. key, function()
      return CompareRide(cont, sx, sy, d, walk, tps, opts, sz)
    end, function(res)
      if not res then return end
      -- (the answer for now, provisional or not; remembered for this square only once final:
      -- else asked again on the next recalculation)
      local before = rideLast[stopKey] or false
      rideLast[stopKey] = res.won
      if res.final then rideCheck[key] = res.won end
      if res.won ~= before then N.Invalidate(false) end -- (the other way: the route worked out again)
    end)
    won = rideCheck[key]
    if won == nil then won = rideLast[stopKey] end
  else
    N.lastRideCheck = (N.lastRideCheck or "") .. " [remembered]"
  end
  if not won then return nil, nil, won end
  return legs, WalkRoutes(legs, sx, sy, d, opts, sz), true
end

local function Stretch(cont, sx, sy, d, walk, opts, sz)
  -- from the player's position: the teleports ready now may start the trip
  local tps = opts.teleports -- the teleports this stretch may start with (AssignTeleports)
  local legs = N.Plan(cont, sx, sy, walk, d, tps)
  if not legs then return nil end
  local routes
  -- (walk vs ride, both routed: when the plan walks all the way, and when it rides, not a teleport,
  -- on this continent: its straight lines can pick a ride that's slower, a walk round to a flight
  -- master far off; reported, Winterspring to Aldrassil at level 14)
  local rides = false
  for _, leg in ipairs(legs) do rides = rides or (leg.ride ~= nil and not leg.ride.use) end
  if ((#legs == 1 and legs[1].walk) or rides) and legs[1].cont == cont and d.cont == cont
      and math.sqrt((d.x - sx) ^ 2 + (d.y - sy) ^ 2) >= N.RIDE_CHECK_MIN_YD / N.WALK_FACTOR then
    local ride, rideRoutes, won = RideInstead(cont, sx, sy, d, walk, tps, opts, sz)
    if ride then
      legs, routes = ride, rideRoutes
    elseif won == false and rides then -- (walking all the way wins)
      legs = { { walk = true, cont = cont, x1 = sx, y1 = sy, x2 = d.x, y2 = d.y } }
    end
  end
  routes = routes or WalkRoutes(legs, sx, sy, d, opts, sz)
  -- (a walk with no way there, the Router's `noWay`: a line through a wall or over blocked ground with
  -- no roads or walk round: none, "No way there found", rather than that line drawn; a broken road
  -- network drew one over the mountains from Ironforge, 2026-10-01)
  for li, leg in ipairs(legs) do
    if not leg.ride and routes[li] and routes[li].noWay then return nil end
  end
  local st = { parts = {}, legs = legs, first = 0, walk = 0, ride = 0, road = 0 }
  local rode = false
  for li, leg in ipairs(legs) do
    if leg.ride then
      local t = leg.ride
      local c1, x1, y1, c2, x2, y2 = t[1], t[2], t[3], t[4], t[5], t[6]
      if leg.from == 2 then c1, x1, y1, c2, x2, y2 = t[4], t[5], t[6], t[1], t[2], t[3] end
      local bx, by = Geo.IntoAny(c2, x2, y2, c1) -- (onto an isle shown as an inset too: Zephras Isle's)
      if t.use then -- a teleport: nothing to draw
      elseif t.pts then -- a flight: through its connecting stops (one continent)
        local kinds = {}
        for k = 1, #t.pts / 2 - 1 do kinds[k] = N.KIND_TRANSPORT end
        -- (in the air over the continent: not on a city's level, from its flight master down in
        -- it, Undercity's; the map doesn't draw what's down in a city while the player is up top)
        st.parts[#st.parts + 1] = { cont = Geo.Base(c1), pts = t.pts, kinds = kinds }
      elseif bx then
        st.parts[#st.parts + 1] = { cont = Geo.Base(c1) == Geo.Base(c2) and c1 or Geo.Base(c1), pts = { x1, y1, bx, by },
          kinds = { N.KIND_TRANSPORT } }
      end
      st.ride = st.ride + t[7]
      rode = true
    else
      local lr = routes[li]
      st.parts[#st.parts + 1] = { cont = leg.cont, pts = lr.pts, kinds = lr.kinds, zs = lr.zs, leg = leg,
        blocked = lr.blocked, unconnected = lr.unconnected }
      st.walk, st.road = st.walk + lr.length, st.road + lr.road
      if lr.pending then st.pending = true end
      leg.yards = lr.length
      if not rode then st.first = st.first + lr.length end
    end
  end
  return st
end

local later = {} -- the stretches between stops don't depend on the player: cached
local pairCosts, pairCount = {}, 0 -- OrderStops: planned seconds between two stops
N.ORDER_WALK_YD = 1200 -- OrderStops: stops closer than this are just walked (no plan needed)
local kept -- the last route, kept through Invalidate to compare a recalculation with

-- Following the route like a car GPS: while the player stays near the first part (the
-- walk from them), trim what's behind them and count the distances down, without
-- recalculating anything. False when they're off the route (then it's recalculated).
N.JOIN_REPICK_YD = 10 -- off the walk to the road by this much: it's worked out again
local function Follow(r, px, py, ahead)
  local full = r.fullFirst
  if not full then return false end
  local pts, kinds, cum = full.pts, full.kinds, r.cum
  local best, bi, bt
  local upTo = ahead and (r.consumed or 0) + ahead
  for i = r.followIdx, #pts / 2 - 1 do
    if upTo and cum[i] > upTo then break end -- (trimming only: the stretch just ahead)
    local ax, ay, bx, by = pts[2 * i - 1], pts[2 * i], pts[2 * i + 1], pts[2 * i + 2]
    local vx, vy = bx - ax, by - ay
    local L2 = vx * vx + vy * vy
    local t = 0
    if L2 > 0 then t = math.max(0, math.min(1, ((px - ax) * vx + (py - ay) * vy) / L2)) end
    local dx, dy = ax + vx * t - px, ay + vy * t - py
    local d2 = dx * dx + dy * dy
    if not best or d2 < best then best, bi, bt = d2, i, t end
  end
  if not best or best > OFF_ROUTE_YD * OFF_ROUTE_YD then return false end
  -- still walking to the road and off that walk: worked out again from here, joining the road
  -- where it's heading from where the player is now (a nearer point on it may be better)
  if best > N.JOIN_REPICK_YD * N.JOIN_REPICK_YD then
    local R = ns.Router
    local toRoad, road = true, false
    for i = 1, #kinds do
      if i <= bi and kinds[i] ~= R.KIND_OFFROAD then toRoad = false break end
      if i > bi and kinds[i] == R.KIND_ROAD then road = true break end
    end
    if toRoad and road then return false end
  end
  local ax, ay, bx, by = pts[2 * bi - 1], pts[2 * bi], pts[2 * bi + 1], pts[2 * bi + 2]
  local qx, qy = ax + (bx - ax) * bt, ay + (by - ay) * bt
  local consumed = cum[bi] + (cum[bi + 1] - cum[bi]) * bt
  local np, nk = { qx, qy }, {}
  for i = bi, #pts / 2 - 1 do
    np[#np + 1], np[#np + 2] = pts[2 * i + 1], pts[2 * i + 2]
    nk[#nk + 1] = kinds[i]
  end
  local nz -- (a dungeon's floors: the points' heights, trimmed alike)
  local zs = full.zs
  if zs and zs[bi] and zs[bi + 1] then
    nz = { zs[bi] + (zs[bi + 1] - zs[bi]) * bt }
    for i = bi, #pts / 2 - 1 do nz[#nz + 1] = zs[i + 1] end
  end
  local trimmed = { cont = full.cont, pts = np, kinds = nk, stop = full.stop, zs = nz, leg = full.leg }
  r.parts[1], r.pts, r.kinds = trimmed, np, nk
  r.followIdx, r.consumed = bi, consumed
  local b = r.base
  r.length = math.max(0, b.length - consumed)
  r.walkYards = math.max(0, b.walkYards - consumed)
  r.totalYards = math.max(0, b.totalYards - consumed)
  return true
end

-- On a flight: the route is the flight to where it lands, then on from there. Nothing is
-- recalculated until landing; the flight's line shrinks from the player to the landing and
-- its time counts down. Taxi.lua knows where the flight lands (the flight master picked).
local flyingRest -- { key, st }: the route on from the landing, worked out once per flight

local function MasterNamed(name)
  if not name then return nil end
  for node, m in pairs(Masters()) do
    if m[4] == name then return m, node end
  end
end

-- The flight's seconds from boarding to landing: learned, or the flight network's estimate.
local function FlightSeconds(from, to)
  local cdb = ns.CharDB and ns.CharDB()
  local took = from and to and cdb and cdb.flights and cdb.flights[from .. " > " .. to]
  if took then return took.seconds end
  local _, a = MasterNamed(from)
  local _, b = MasterNamed(to)
  local fl = a and b and Flights()
  local row = fl and fl.trips[a] and fl.trips[a][b]
  return row and row[7] - N.FLIGHT_OVERHEAD
end

function N.FlyingRoute(px, py, cont, walk, offroad, f)
  local L = MasterNamed(f.to)
  if not L or L[1] ~= cont then return nil end
  local d = N.dest
  local key = version .. ":" .. f.to .. ":" .. tostring(offroad)
  if not flyingRest or flyingRest.key ~= key then
    local fixed = { offroad = offroad }
    local rest = Stretch(L[1], L[2], L[3], d, walk, { offroad = offroad, fixed = fixed })
    -- the stops after this one, as usual
    local laterSt = {}
    for i = 2, N.PlannedStops() do
      local a = N.stops[i - 1]
      laterSt[i] = Stretch(a.cont, a.x, a.y, N.stops[i], walk, { offroad = offroad, fixed = fixed }, N.StopZ(a)) or false
    end
    flyingRest = { key = key, st = rest, later = laterSt }
  end
  local rest = flyingRest.st
  if not rest then return nil end
  -- time left in the air: the planned flight time counting down, at least the straight
  -- distance left at flight speed
  local left = math.sqrt((L[2] - px) ^ 2 + (L[3] - py) ^ 2)
  local secs = left / N.FLIGHT_SPEED
  local total = FlightSeconds(f.from, f.to)
  if total then secs = math.max(secs, total - (GetTime() - f.start)) end
  local row = { cont, px, py, L[1], L[2], L[3], secs, "flight", f.from or "?", f.to, "flight master", flying = true }
  local flight = { cont = cont, pts = { px, py, L[2], L[3] }, kinds = { N.KIND_TRANSPORT }, stop = 1 }
  local parts = { flight }
  for _, p in ipairs(rest.parts) do
    p.stop = 1
    parts[#parts + 1] = p
  end
  local legs = { { ride = row, from = 1 } }
  for _, leg in ipairs(rest.legs) do legs[#legs + 1] = leg end
  local first = { parts = parts, legs = legs, first = 0, walk = rest.walk, ride = secs + rest.ride, road = rest.road }
  local stretches = { first }
  local yards, ride = rest.walk, secs + rest.ride
  for i = 2, N.PlannedStops() do
    local st = flyingRest.later[i]
    stretches[i] = st
    if st then
      for _, p in ipairs(st.parts) do
        p.stop = i
        parts[#parts + 1] = p
      end
      yards, ride = yards + st.walk, ride + st.ride
    end
  end
  return {
    pts = flight.pts, kinds = flight.kinds, road = rest.road, length = 0,
    walkYards = rest.walk, rideSeconds = secs + rest.ride, extraSeconds = secs + rest.ride,
    totalYards = yards, totalRide = ride, parts = parts, legs = legs, stretches = stretches,
    flying = { to = f.to, seconds = secs }, version = version, offroad = offroad, cont = cont,
  }
end

-- The stretches between stops are worked out a few per call (N.LATER_PER_CALL), the rest on
-- the next frames: a new route with many stops doesn't stall one frame. Until then the
-- route shows the ones done (and after Invalidate, the previous ones: later.done is reset,
-- the stretches themselves stay until replaced).
N.LATER_PER_CALL = 1

local function LaterMissing()
  if not later.key then return false end
  for i = 2, N.PlannedStops() do
    if not later.done or not later.done[i] then return true end
  end
  return false
end

-- Teleports (hearthstone, Astral Recall, mage teleports) ready now, from (x, y), limited
-- to the names in `only` ({ [name] = true }).
local function TeleportsFrom(cont, x, y, only)
  local out = {}
  if not only or not ns.Teleports then return out end
  for _, row in ipairs(ns.Teleports.Available(cont, x, y)) do
    if only[row[8]] then out[#out + 1] = row end
  end
  return out
end

-- The teleport the fastest plan from (x, y) to stop d starts with, and the seconds it
-- saves over the plan without teleports; nil when none helps.
local function TeleportGain(cont, x, y, d, walk, tps)
  if not tps or not tps[1] then return nil end
  local legs, with = N.Plan(cont, x, y, walk, d, tps)
  for _, leg in ipairs(legs or {}) do
    if leg.ride and leg.ride.use then
      local _, without = N.Plan(cont, x, y, walk, d)
      return leg.ride[8], (without or math.huge) - with
    end
  end
end

-- Each teleport is used once per trip, on the stretch where it saves the most: from the
-- player to the next stop, or from one stop to the next (e.g. hearthing from the last
-- stop but one when the trip ends near home). The gains between stops are worked out once
-- per route (and when the teleports ready change); the player's stretch every
-- recalculation. Sets later.tp[i] (the teleport stretch i may use; the stretch is redone
-- when that changes) and returns the teleports for the player's stretch.
-- (only when it saves more than TELEPORT_MIN_YD of walking: a hearthstone's hour-long cooldown
-- isn't worth a few hundred yards)
N.TELEPORT_MIN_YD = 800
local function AssignTeleports(cont, px, py, d, walk)
  local T = ns.Teleports
  if not T or N.loop or N.corpse then return nil end
  local tps = T.Available(cont, px, py)
  local names = {}
  for _, row in ipairs(tps) do names[#names + 1] = row[8] end
  local sig = table.concat(names, "|")
  if later.tpSig ~= sig then
    later.tpSig, later.gains = sig, {}
    for i = 2, sig ~= "" and N.PlannedStops() or 1 do
      local a = N.stops[i - 1]
      local name, gain = TeleportGain(a.cont, a.x, a.y, N.stops[i], walk, T.Available(a.cont, a.x, a.y))
      later.gains[i] = name and { name, gain } or false
    end
  end
  local best = {} -- [name] = { stretch, seconds saved }
  local n1, g1 = TeleportGain(cont, px, py, d, walk, tps)
  local minGain = N.TELEPORT_MIN_YD / walk
  if n1 and g1 > minGain then best[n1] = { 1, g1 } end
  for i = 2, N.PlannedStops() do
    local g = later.gains[i]
    if g and g[2] > minGain and (not best[g[1]] or g[2] > best[g[1]][2]) then best[g[1]] = { i, g[2] } end
  end
  later.tp = later.tp or {}
  for i = 2, N.PlannedStops() do
    local want
    for name, b in pairs(best) do
      if b[1] == i then want = name end
    end
    if later.tp[i] ~= want then
      later.tp[i] = want
      if later.done then later.done[i] = nil end
    end
  end
  local out = {}
  for _, row in ipairs(tps) do
    if best[row[8]] and best[row[8]][1] == 1 then out[#out + 1] = row end
  end
  return out
end

-- Work out up to `budget` stretches between stops still to do (in order).
local function FillLater(walk, offroad, budget)
  later.done = later.done or {}
  for i = 2, N.PlannedStops() do
    if budget <= 0 then break end
    if not later.done[i] then
      local a = N.stops[i - 1]
      local opts = { offroad = offroad }
      opts.fixed = { offroad = offroad }
      if later.tp and later.tp[i] then opts.teleports = TeleportsFrom(a.cont, a.x, a.y, { [later.tp[i]] = true }) end
      later[i] = Stretch(a.cont, a.x, a.y, N.stops[i], walk, opts, N.StopZ(a)) or false
      later.done[i] = true
      budget = budget - 1
    end
  end
end

-- The route from the player's stretch (`first`, worked out at (px, py)) and the stretches
-- between stops worked out so far.
local function Assemble(first, px, py, cont, walk, offroad)
  local parts, stretches = {}, { first }
  for i = 2, N.PlannedStops() do stretches[i] = later[i] end
  -- each part knows which stop it leads to (drawn in that stop's marker color)
  for _, p in ipairs(first.parts) do
    p.stop = 1
    parts[#parts + 1] = p
  end
  local yards, ride = first.walk, first.ride
  for i = 2, N.PlannedStops() do
    local st = later[i]
    if st then
      for _, p in ipairs(st.parts) do
        p.stop = i
        parts[#parts + 1] = p
      end
      yards, ride = yards + st.walk, ride + st.ride
    end
  end
  local p1 = first.parts[1]
  local r = {
    pts = p1 and p1.pts or { px, py }, kinds = p1 and p1.kinds or {}, road = first.road,
    length = first.first, walkYards = first.walk, rideSeconds = first.ride,
    extraSeconds = first.ride + (first.walk - first.first) / walk,
    totalYards = yards, totalRide = ride, parts = parts, legs = first.legs, stretches = stretches,
  }
  -- for following: the first part (the walk from the player) and its running lengths
  r.version, r.offroad, r.cont, r.pending, r.firstStretch = version, offroad, cont, first.pending, first
  r.base = { length = r.length, walkYards = r.walkYards, totalYards = r.totalYards }
  r.followIdx, r.consumed = 1, 0
  if p1 and first.legs[1] and first.legs[1].walk then
    r.fullFirst = p1
    local cum, pts = { 0 }, p1.pts
    for i = 2, #pts / 2 do
      cum[i] = cum[i - 1] + math.sqrt((pts[2 * i - 1] - pts[2 * i - 3]) ^ 2 + (pts[2 * i] - pts[2 * i - 2]) ^ 2)
    end
    r.cum = cum
  end
  return r
end

-- Current route from (px, py) through every stop, recomputed every few seconds or after
-- moving a bit. route.parts = { { cont, pts, kinds }, ... } in each part's own continent
-- coordinates (drawing converts them via the world map); route.pts/kinds are the first
-- part (from the player). To the next stop: route.length = yards before any transport,
-- route.walkYards, route.rideSeconds; to the last stop: route.totalYards, route.totalRide.
-- The level the player routes on: an underground city's (the game says we're on its map)
-- or the continent. Checked every half second.
local levelAt, levelCache = -math.huge, nil

-- The underground city the player is down in right now (its level id), or nil; false when
-- the game doesn't say where the player is (loading).
function N.CityHere()
  local map = C_Map and C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
  if not map then return false end
  for id, l in pairs(ns.CityLevels or {}) do
    if l.map == map then
      -- (the halls at the lifts' tops report the city's map too, but they're up top)
      local sub = GetSubZoneText and GetSubZoneText()
      local mini = GetMinimapZoneText and GetMinimapZoneText()
      local up = l.upper and ((sub and l.upper[sub]) or (mini and l.upper[mini]))
      if not up then return id end
    end
  end
  return nil
end

-- Boss kills (a dungeon's boss route: a boss's stop is done when it dies, not when you get
-- there). Kept per character for the instance they're in: { level, at = time(), npcs = { [npc]
-- = true } }, started over in another instance or BOSS_KILL_HOURS after the last kill.
N.BOSS_KILL_HOURS = 3
N.BOSS_NEAR_YD = 40 -- this close to a boss's stop: "Defeat <boss>"

local function Kills()
  local cdb = ns.CharDB and ns.db and ns.CharDB()
  if not cdb then
    N.kills = N.kills or {}
    return N.kills
  end
  cdb.bossKills = cdb.bossKills or {}
  return cdb.bossKills
end

-- The instance level the player is in (GetInstanceInfo's map), or nil.
function N.CurrentInstance()
  if not GetInstanceInfo then return nil end
  local ok, _, kind, _, _, _, _, _, mapID = pcall(GetInstanceInfo)
  if not ok or (kind ~= "party" and kind ~= "raid") then return nil end
  return N.InstanceLevel(mapID)
end

-- A boss's key in the kills: its NPC entry, or its name (WoW Forever's own dungeons: no entry).
function N.BossKey(b) return (b[2] and b[2] ~= 0) and b[2] or b[1] end

-- The bosses of instance level `lvl` matching a kill: by NPC entry, DungeonEncounter id or
-- name. Returns how many were marked dead.
function N.BossKilled(lvl, npc, encounter, name)
  local info = lvl and ns.Instances and ns.Instances[lvl]
  if not info then return 0 end
  local k = Kills()
  local now = time and time() or 0
  if k.level ~= lvl or (k.at and now - k.at > N.BOSS_KILL_HOURS * 3600) then
    k.level, k.npcs = lvl, {}
  end
  k.at = now
  local n = 0
  for _, b in ipairs(info.bosses or {}) do
    local hit = (npc and b[2] == npc) or (name and b[1] == name)
    for _, e in ipairs(encounter and b.enc or {}) do
      if e == encounter then hit = true end
    end
    local key = N.BossKey(b)
    if hit and not k.npcs[key] then
      k.npcs[key] = true
      n = n + 1
    end
  end
  return n
end

-- Whether boss stop `d` ({ cont = its level, boss = its NPC entry }) is dead.
function N.BossDead(d)
  local k = Kills()
  if not (d.boss and k.level == d.cont and k.npcs) then return false end
  if k.at and (time and time() or 0) - k.at > N.BOSS_KILL_HOURS * 3600 then return false end
  return k.npcs[d.boss] == true
end

-- A creature's NPC entry from its GUID ("Creature-0-server-instance-zone-npc-spawn").
function N.NpcOf(guid)
  if type(guid) ~= "string" then return nil end
  local kind, npc = guid:match("^(%a+)%-%d+%-%d+%-%d+%-%d+%-(%d+)%-")
  if kind ~= "Creature" and kind ~= "Vehicle" then return nil end
  return tonumber(npc)
end

-- The level of an instance map (Data/Instances.lua: LEVEL_BASE + its MapID, base = the map),
-- or nil: in a dungeon, the game reports its map as the player's continent.
local instanceOf
function N.InstanceLevel(cont)
  if not instanceOf then
    instanceOf = {}
    for id, l in pairs(ns.CityLevels or {}) do
      if l.instance then instanceOf[l.base] = id end
    end
  end
  return cont and instanceOf[cont]
end

function N.PlayerLevel(cont)
  if not ns.CityLevels or not cont then return cont end
  local inst = N.InstanceLevel(cont)
  if inst then return inst end
  local now = GetTime()
  if now - levelAt > 0.5 then
    levelAt, levelCache = now, N.CityHere() or nil
  end
  if levelCache and (levelCache == cont or ns.CityLevels[levelCache].base == cont) then return levelCache end
  return cont
end

-- The level of a new stop at (x, y) on `cont`: the city's when the player is down in it and
-- the spot is on its floors, else the continent. (Its floors: a height there, not only open
-- cells: a trainer at a ledge's edge or in a booth is a yard from closed ones.)
function N.StopLevel(cont, x, y)
  local lvl = N.PlayerLevel(cont)
  if lvl == cont then return cont end
  local P = ns.Passability
  if (P and P.IsOpen and P.IsOpen(lvl, x, y)) or (N.CityHeight and N.CityHeight(lvl, x, y)) then return lvl end
  return cont
end

local Apply, Rejoin
-- The route from (px, py) worked out: the stretch to the next stop and those after it (a few more
-- each call), assembled; nil when there's no way.
local function Compute(px, py, cont, d, offroad)
  local _, walk = N.Speeds()
  local key = version .. ":" .. tostring(offroad)
  if later.key ~= key then later = { key = key, done = {} } end
  local tps = AssignTeleports(cont, px, py, d, walk)
  if ns.Router.Breathe then ns.Router.Breathe(1, 1) end -- (in a background job: a pause between the parts)
  local t1 = ns.PerfStart and ns.PerfStart()
  local first = Stretch(cont, px, py, d, walk, { offroad = offroad, transient = true, fixed = { offroad = offroad },
    teleports = tps, indoors = N.Indoors(), z = N.PlayerZ() })
  if t1 then ns.PerfEnd("route calculation: next stop", t1) end
  if not first then return nil end
  if ns.Router.Breathe then ns.Router.Breathe(1, 1) end
  local t2 = ns.PerfStart and ns.PerfStart()
  FillLater(walk, offroad, N.LATER_PER_CALL)
  if t2 then ns.PerfEnd("route calculation: later stops", t2) end
  return Assemble(first, px, py, cont, walk, offroad)
end

-- `new` (worked out at (px, py)) as the route; but `old`, when the player is still on it and `new`
-- is clearly longer (KeepOld).
function Apply(new, old, px, py, cont, offroad, now, trim)
  local _, walk = N.Speeds()
  if old and new and old ~= new and N.KeepOld(old, new, walk, now) and Follow(old, px, py) then
    old.keptSince = old.keptSince or now
    new = old
  elseif new then
    new.keptSince = nil
    if trim then Follow(new, px, py) end -- (worked out a moment ago, in the background: from where the player is now)
  end
  N.route, kept = new, new
  N.warming = nil
  N.routeX, N.routeY, N.routeTime, N.routeOffroad, N.routeCont = px, py, now, offroad, cont
  N.trimX, N.trimY = px, py
  N.CheckRedRoute(px, py, cont, now)
  return new
end

-- Off a long walk from the player: back onto it a little ahead of the nearest point (REJOIN_AHEAD_YD),
-- a short way routed from the player, the rest of the walk and the route after it as they were.
-- nil when it doesn't fit (too far off, a city's floors, near the walk's end).
N.REJOIN_MIN_YD = 1500 -- a walk from the player this long left: rejoined, worked out again in the background
N.REJOIN_MAX_OFF_YD = 250
N.REJOIN_AHEAD_YD = 60
function Rejoin(old, px, py, cont, offroad)
  local full, f0 = old.fullFirst, old.firstStretch
  if not (full and f0 and old.cum) or full.zs or Geo.Base(full.cont) ~= Geo.Base(cont) then return nil end
  local pts, cum = full.pts, old.cum
  local best, bi, bt
  for i = old.followIdx or 1, #pts / 2 - 1 do
    local ax, ay, bx, by = pts[2 * i - 1], pts[2 * i], pts[2 * i + 1], pts[2 * i + 2]
    local vx, vy = bx - ax, by - ay
    local L2 = vx * vx + vy * vy
    local t = L2 > 0 and math.max(0, math.min(1, ((px - ax) * vx + (py - ay) * vy) / L2)) or 0
    local d2 = (ax + vx * t - px) ^ 2 + (ay + vy * t - py) ^ 2
    if not best or d2 < best then best, bi, bt = d2, i, t end
  end
  if not best or best > N.REJOIN_MAX_OFF_YD ^ 2 then return nil end
  local total = cum[#cum]
  local along = cum[bi] + (cum[bi + 1] - cum[bi]) * bt + N.REJOIN_AHEAD_YD
  if along >= total - N.REJOIN_AHEAD_YD then return nil end
  local j = bi
  while cum[j + 1] < along do j = j + 1 end
  local f = (along - cum[j]) / math.max(cum[j + 1] - cum[j], 1e-6)
  local tx, ty = pts[2 * j - 1] + (pts[2 * j + 1] - pts[2 * j - 1]) * f, pts[2 * j] + (pts[2 * j + 2] - pts[2 * j]) * f
  local lr = ns.Router.Route(full.cont, px, py, tx, ty, { offroad = offroad, transient = true })
  if not lr or Unwalkable(lr) then return nil end
  local np, nk = {}, {}
  for k = 1, #lr.pts do np[k] = lr.pts[k] end
  for k = 1, #lr.kinds do nk[k] = lr.kinds[k] end
  nk[#nk + 1] = full.kinds[j] -- (on from the way back on along the walk)
  for k = j + 1, #pts / 2 do
    np[#np + 1], np[#np + 2] = pts[2 * k - 1], pts[2 * k]
    if k < #pts / 2 then nk[#nk + 1] = full.kinds[k] end
  end
  local newLen = lr.length + (total - along)
  local legs, l1 = {}, {}
  for k, v in pairs(f0.legs[1]) do l1[k] = v end
  l1.yards = newLen
  for k, leg in ipairs(f0.legs) do legs[k] = k == 1 and l1 or leg end
  local part = { cont = full.cont, pts = np, kinds = nk, leg = l1, stop = full.stop }
  local parts = { part }
  for k = 2, #f0.parts do parts[k] = f0.parts[k] end
  local first = { parts = parts, legs = legs, first = f0.first - total + newLen, walk = f0.walk - total + newLen,
    ride = f0.ride, road = f0.road, pending = lr.pending or f0.pending }
  local _, walk = N.Speeds()
  return Assemble(first, px, py, cont, walk, offroad)
end

-- In a city, the floor under the player changing height at a stroke (jumped down, or
-- back up top): worked out again from there (a drop may be the way again).
N.FLOOR_JUMP = 5
N.FLOOR_JUMP_EVERY = 4 -- seconds, at most (walking along a ledge's foot flickers)
local lastFloor, floorJumpAt = nil, -math.huge
function N.Route(px, py, cont)
  cont = N.PlayerLevel(cont)
  N.playerX, N.playerY = px, py
  local d = N.dest
  if not d then return nil end
  if ns.CityLevels and ns.CityLevels[cont] and px and N.CityHeight then
    -- (the player's own height when the game gives it: the floor's under them can be a walkway
    -- over their head, and they didn't jump up to it)
    local h = N.PlayerCityZ(cont) or N.CityHeight(cont, px, py)
    if h and lastFloor and math.abs(h - lastFloor) >= N.FLOOR_JUMP and GetTime() - floorJumpAt >= N.FLOOR_JUMP_EVERY then
      floorJumpAt = GetTime()
      kept = nil
      N.Invalidate(false) -- (just the way to the next stop)
    end
    lastFloor = h or lastFloor
  else
    lastFloor = nil
  end
  if N.QuestPaused() then return N.route end -- in the stop's quest area, spot reached: waits
  local now = GetTime()
  local r = N.route
  -- (roads always: the route joins them where they're heading, from wherever the player is;
  -- Router's JOIN_ALONG. The offroad option is gone from 1.0.8.)
  local offroad = false
  -- on a flight: the flight, then on from where it lands; no rerouting until then
  local f = ns.Taxi and ns.Taxi.Current and ns.Taxi.Current()
  if f then
    if f.to then
      local _, walkSpeed = N.Speeds()
      local fr = N.FlyingRoute(px, py, cont, walkSpeed, offroad, f)
      if fr then
        N.route, kept = fr, fr
        N.routeX, N.routeY, N.routeTime, N.routeOffroad, N.routeCont = px, py, now, offroad, cont
        return fr
      end
    end
    if r then return r end -- flying somewhere we can't tell (e.g. after a reload): keep the route
  end
  -- in the Deeprun Tram (its own map): the route kept as it is until out at the other end
  if cont == N.TRAM_MAP then return r end
  -- on a boat or a zeppelin (Taxi.Riding): the route as it is, not worked out again until off it
  if ns.Taxi and ns.Taxi.Riding and ns.Taxi.Riding() then return r or kept end
  if r and r.flying then r, kept = nil, nil end -- just landed: work the route out afresh
  -- the continent's road data is still being built in the background (a moment)
  -- (and the levels the stops are on: a city's, down a lift)
  if not r and ns.Router.WarmUp then
    local busy = ns.Router.WarmUp(cont, px, py)
    for _, s in ipairs(N.stops) do
      if s.cont and s.cont ~= cont then busy = ns.Router.WarmUp(s.cont, s.x, s.y) or busy end
    end
    -- (and the underground cities on this continent: a route through one's flight master or
    -- lift, Undercity's, built its roads in the frame, a third of a second and more)
    for lvl, l in pairs(ns.CityLevels or {}) do
      if not l.instance and lvl ~= cont and Geo.Base(lvl) == Geo.Base(cont) then
        busy = ns.Router.WarmUp(lvl, px, py) or busy
      end
    end
    if busy then
      N.warming = true
      return nil
    end
  end
  N.warming = nil
  local moved = r and ((px - N.routeX) ^ 2 + (py - N.routeY) ^ 2) or math.huge
  -- stretches between stops still to work out: one more now, same route from the player
  if r and not r.flying and r.firstStretch and r.version == version and r.offroad == offroad
      and later.key == version .. ":" .. tostring(offroad) and LaterMissing() then
    local _, walk = N.Speeds()
    local t0 = ns.PerfStart and ns.PerfStart()
    FillLater(walk, offroad, N.LATER_PER_CALL)
    local nr = Assemble(r.firstStretch, N.routeX, N.routeY, cont, walk, offroad)
    nr.keptSince = r.keptSince
    Follow(nr, px, py)
    N.route, kept, r = nr, nr, nr
    if t0 then ns.PerfEnd("route calculation: stops", t0) end
  end
  local rerouteSecs, rerouteYd, searchSecs = N.RerouteTiming()
  if searchDirty and r and now - searchRecalcAt >= searchSecs then
    r, N.route = nil, nil
    moved = math.huge
    searchDirty, searchRecalcAt = false, now
  end
  local age = r and now - N.routeTime or math.huge
  local same = r and N.routeOffroad == offroad and N.routeCont == cont
  if same and age < REROUTE_STALE and (age < rerouteSecs or moved <= rerouteYd ^ 2) then
    -- (not recalculated yet: the walked part behind the player trimmed off meanwhile)
    local tx, ty = N.trimX or N.routeX, N.trimY or N.routeY
    if age < FOLLOW_MAX_AGE and (px - tx) ^ 2 + (py - ty) ^ 2 >= N.TRIM_MOVED_YD ^ 2
        and Follow(r, px, py, N.TRIM_AHEAD_YD) then
      N.trimX, N.trimY = px, py
    end
    return r
  end
  -- moving along the route: just follow it (no recalculation)
  if same and age < FOLLOW_MAX_AGE and Follow(r, px, py) then
    N.routeX, N.routeY, N.trimX, N.trimY = px, py, px, py
    return r
  end
  -- the route so far, to compare with (also after Invalidate)
  local old = r or kept
  if old and not (old.version == version and old.offroad == offroad and old.cont == cont) then old = nil end
  -- Worked out in the background (Router.Background: its searches pause, no frame waits on them):
  -- the first route (nothing to show yet: "Working out the route..."), and a route whose walk from
  -- the player is long, `old` shown meanwhile (off it: rejoined, a short way back onto it ahead).
  -- Else, a short walk, at once. (A long walk worked out again in the frame on every reroute, and
  -- the first route after a /reload, were a tenth of a second and more in one frame.)
  local long = old and old.fullFirst and old.cum and (old.cum[#old.cum] - (old.consumed or 0)) >= N.REJOIN_MIN_YD
  if ns.Router.WARM and not ns.Router.SYNC_WALKS and (not old or long) then -- (as in game; tests: at once)
    if old and not Follow(old, px, py) then
      local rj = Rejoin(old, px, py, cont, offroad)
      if rj then Apply(rj, nil, px, py, cont, offroad, now) end
    elseif old and N.route == nil then
      -- (still on it, the route dropped for a finished search's recalculation: shown meanwhile, not
      -- "Working out the route..." with no route every few seconds while riding past searched ground)
      N.route = old
    end
    ns.Router.Background("route:" .. version .. ":" .. tostring(offroad), function()
      return Compute(px, py, cont, d, offroad)
    end, function(res)
      -- (still this route's stops: in, unless the one shown is clearly shorter; from where the
      -- player is now)
      if not res or res.version ~= version then return end
      local cur = N.route or kept
      if cur and not (cur.version == version and cur.cont == res.cont) then cur = nil end
      Apply(res, cur, N.playerX or px, N.playerY or py, res.cont, offroad, GetTime(), true)
    end)
    -- (queued now, or already: what's shown meanwhile, never worked out in the frame as well)
    N.warming = N.route == nil or nil
    return N.route
  end
  local t0 = ns.PerfStart and ns.PerfStart()
  local new = Compute(px, py, cont, d, offroad)
  if t0 then ns.PerfEnd("route calculation", t0) end
  return Apply(new, old, px, py, cont, offroad, now)
end

-- Once a route is worked out (settled, or 3 s on): walking through a zone too high for the
-- player asks first (GPSFrame's ConfirmRedRoute); no clears the route.
local redChecked, redSeenAt = nil, nil
function N.CheckRedRoute(px, py, cont, now)
  local r = N.route
  local d = N.dest
  if not r or not d or d.corpse or redChecked == version then return end
  if redSeenAt == nil or redSeenAt[1] ~= version then redSeenAt = { version, now } end
  if r.pending and now - redSeenAt[2] < 3 then return end
  redChecked = version
  local zones = N.RedOnRoute(r, px, py, cont)
  if not (zones and ns.GPS and ns.GPS.ConfirmRedRoute) then return end
  ns.GPS.ConfirmRedRoute(zones, function()
    for _, z in ipairs(zones) do N.redOk[z.z] = true end
    N.SaveStops()
  end, function()
    N.Clear()
  end)
end

-- Keep route `old` instead of the recalculated `new`? When `new` is clearly longer (the
-- whole trip, rides counted at walking speed) and either still provisional or `old` hasn't
-- been kept for KEEP_SECONDS yet. (The caller also checks the player is still on `old`.)
-- A provisional route (a terrain search still running: straight across meanwhile) never
-- stays over a worked-out one, nor replaces one: standing still, the refresh's search made
-- a straight line over the hills each time and kept it, shorter than the roads.
function N.KeepOld(old, new, walk, now)
  if old.pending and not new.pending then return false end
  if new.pending and not old.pending then return true end
  local function cost(r) return (r.totalYards or 0) + (r.totalRide or 0) * walk end
  if cost(new) <= cost(old) * LONGER_SHARE + LONGER_YD then return false end
  return new.pending or now - (old.keptSince or now) < KEEP_SECONDS
end

-- Background terrain searches finished (GPSFrame pumps them): `fixed` when one was for a
-- leg between fixed points (the stops), else they were from the player's position.
function N.SearchDone(fixed)
  if fixed then
    N.Invalidate(true)
  else
    searchDirty = true -- see SEARCH_RECALC_SECONDS
  end
end

-- Recompute the route on the next request (e.g. a background terrain search finished);
-- `all`: the legs between stops too (otherwise only the way from the player).
-- `fresh`: something the player changed (an option): the new route applies right away,
-- without comparing it with the current one (see KeepOld).
function N.Invalidate(all, fresh)
  N.route = nil -- (kept stays, to compare the recalculation with)
  if all ~= false then later.done = {} end -- redone a few a frame; shown until replaced
  if fresh then pairCosts, pairCount = {}, 0 end
  if fresh then kept, rideCheck, rideLast = nil, {}, {} end
  if all ~= false then legMemo, legMemoN = {}, 0 end
end

-- Reorder the stops into the fastest order from (px, py) (default: the player's
-- position), by planned travel time (transports included): every order for up to 7
-- stops, nearest-first improved by 2-opt beyond that. `onlyIfFaster`: keep the current
-- order unless the best one is clearly faster (REORDER_GAIN). Returns whether it changed.
N.REORDER_GAIN_SECONDS, N.REORDER_GAIN_SHARE = 15, 0.10
function N.OrderStops(px, py, cont, onlyIfFaster)
  local n = #N.stops
  if n < 2 then return false end
  if N.stops[1].corpse then return false end -- your body stays first (corpse run)
  if not px then px, py, cont = Geo.PlayerWorld() end
  cont = N.PlayerLevel(cont)
  if not px then return end
  local _, walk = N.Speeds()
  local pts = { { x = px, y = py, cont = cont } }
  for i, d in ipairs(N.stops) do pts[i + 1] = d end
  local cost = {}
  for i = 1, n + 1 do
    cost[i] = {}
    for j = 2, n + 1 do
      local secs = 0
      if i ~= j then
        local a, b = pts[i], pts[j]
        local d = a.cont == b.cont and math.sqrt((a.x - b.x) ^ 2 + (a.y - b.y) ^ 2)
        if d and d <= N.ORDER_WALK_YD then
          secs = d * N.WALK_FACTOR / walk -- close by: walked (what the plan would say)
        else
          -- between two stops the time doesn't change: remembered (not from the player)
          local key = i > 1 and string.format("%d:%.0f:%.0f>%d:%.0f:%.0f@%.2f", a.cont, a.x, a.y, b.cont, b.x, b.y, walk)
          secs = key and pairCosts[key]
          if not secs then
            secs = select(2, N.Plan(a.cont, a.x, a.y, walk, b)) or math.huge
            if key then
              if pairCount > 20000 then pairCosts, pairCount = {}, 0 end
              pairCosts[key], pairCount = secs, pairCount + 1
            end
          end
        end
      end
      cost[i][j] = secs
    end
  end
  local function total(order)
    local t, prev = 0, 1
    for _, j in ipairs(order) do t, prev = t + cost[prev][j], j end
    return t
  end
  -- (stops down in a city keep their order among themselves: N.KeepCityOrder)
  local kept, keptList = {}, {}
  for j = 2, n + 1 do
    if N.CityKept(pts[j]) then
      kept[j] = true
      keptList[#keptList + 1] = j
    end
  end
  local function inTurn(j, used) -- (a kept stop only after the kept ones placed before it)
    if not kept[j] then return true end
    for _, e in ipairs(keptList) do
      if e == j then return true end
      if not used[e] then return false end
    end
    return true
  end
  local best, bestT
  if n <= 7 then
    local order, used = {}, {}
    local function perm(k)
      if k > n then
        local t = total(order)
        if not bestT or t < bestT then best, bestT = { unpack(order) }, t end
        return
      end
      for j = 2, n + 1 do
        if not used[j] and inTurn(j, used) then
          used[j], order[k] = true, j
          perm(k + 1)
          used[j] = false
        end
      end
    end
    perm(1)
  else
    best = {}
    local used, prev = {}, 1
    for k = 1, n do
      local pick
      for j = 2, n + 1 do
        if not used[j] and (not pick or cost[prev][j] < cost[prev][pick]) then pick = j end
      end
      used[pick], best[k], prev = true, pick, pick
    end
    -- 2-opt: reverse a run of stops where that shortens the trip. Times one way and back
    -- are about the same, so each try costs just the two ends (averaged both ways).
    local function S(i, j)
      if not j then return 0 end -- after the last stop: nothing
      if i == 1 then return cost[1][j] end -- from the player
      return (cost[i][j] + cost[j][i]) / 2
    end
    local improved, passes = true, 0
    while improved and passes < 50 do
      improved, passes = false, passes + 1
      for a = 1, n - 1 do
        for b = a + 1, n do
          local before = a > 1 and best[a - 1] or 1
          local after = best[b + 1]
          local delta = S(before, best[b]) + S(best[a], after) - S(before, best[a]) - S(best[b], after)
          if delta < -1e-6 then
            for k = 0, math.floor((b - a) / 2) do best[a + k], best[b - k] = best[b - k], best[a + k] end
            improved = true
          end
        end
      end
    end
    -- (the stops down in a city back in their order, in the places they got)
    local k = 0
    for i, j in ipairs(best) do
      if kept[j] then
        k = k + 1
        best[i] = keptList[k]
      end
    end
    bestT = total(best)
  end
  local same = true
  for k, j in ipairs(best) do if j ~= k + 1 then same = false end end
  if same then return false end
  if onlyIfFaster then
    local current = {}
    for k = 1, n do current[k] = k + 1 end
    local now = total(current)
    if bestT > now - math.max(N.REORDER_GAIN_SECONDS, now * N.REORDER_GAIN_SHARE) then return false end
  end
  local ordered = {}
  for k, j in ipairs(best) do ordered[k] = pts[j] end
  N.stops = ordered
  Changed()
  return true
end

-- While traveling with several stops (fastest order on): every REORDER_EVERY seconds, and
-- after moving a bit, visit the stops in a new order if that has become clearly faster
-- (e.g. heading for stop 2 first). Not while flying.
local REORDER_EVERY, REORDER_MOVED_YD = 8, 30
local reorderAt, reorderX, reorderY = 0, nil, nil
function N.MaybeReorder(px, py, cont)
  if N.loop or #N.stops < 2 or not (ns.settings and ns.settings.gps.fastestOrder) or N.KeepCityOrder() then return false end
  -- a long list (an imported guide) was put in order once, from where it was imported:
  -- redoing that on the way would be a long pause for little gain
  if #N.stops > N.PLAN_AHEAD then return false end
  if ns.Taxi and ns.Taxi.Current and ns.Taxi.Current() then return false end
  local now = GetTime()
  if now - reorderAt < REORDER_EVERY then return false end
  if reorderX and (px - reorderX) ^ 2 + (py - reorderY) ^ 2 < REORDER_MOVED_YD ^ 2 then return false end
  reorderAt, reorderX, reorderY = now, px, py
  return N.OrderStops(px, py, cont, true)
end

-- The route's points converted into continent `view`'s coordinates:
-- calls fn(x1, y1, x2, y2, kind, stop) per segment (stop: index of the stop that part of
-- the route leads to). Returns the last point (the destination).
function N.EachSegment(route, view, fn)
  local lx, ly
  for _, part in ipairs(route.parts or {}) do
    local px, py
    for i = 1, #part.pts, 2 do
      local x, y = Geo.ToContinent(part.cont, part.pts[i], part.pts[i + 1], view)
      if not x then break end
      if px then fn(px, py, x, y, part.kinds[(i - 1) / 2], part.stop, part.cont) end
      px, py = x, y
    end
    lx, ly = px or lx, py or ly
  end
  return lx, ly
end

-- The next transport on the route: row, boarding side, and whether the player is at its dock.
local function NextRide(route, px, py)
  if not route or not route.legs then return nil end
  for i, leg in ipairs(route.legs) do
    if leg.ride then
      local t, from = leg.ride, leg.from
      local bx, by = from == 1 and t[2] or t[5], from == 1 and t[3] or t[6]
      local atDock = i <= 2 and math.sqrt((px - bx) ^ 2 + (py - by) ^ 2) <= N.DOCK_YD
      return t, from, atDock
    end
  end
end

-- The teleport to use now: the route's first step (the hearthstone, a teleport, an engineer's
-- teleporter), from where the player stands; else nil. What GPSFrame's use button uses.
function N.UseNow()
  local r = N.route
  local leg = r and not r.flying and r.legs and r.legs[1]
  if leg and leg.ride and leg.ride.use and (leg.ride.item or leg.ride.spell) then return leg.ride end
end

---------------------------------------------------------------------------
-- Speeds
---------------------------------------------------------------------------

local lastRun = DEFAULT_RUN -- the plain run speed: on foot, no speed ability on (items and the Speed stat in it)
local plainSeen -- (lastRun was seen, not guessed)

-- Movement abilities (not items): the spell, the share of the run speed it adds, talents adding
-- more (their spells by rank, `per` rank), and whether it only works outdoors. A known one's
-- time is shown beside walking; while it's on, it's the walking speed. Its speed is learned
-- the first time it's seen on (the server's own numbers), else estimated from these.
N.MOVE_ABILITIES = {
  { spell = 783, add = 0.40, outdoors = true },   -- Travel Form (druid)
  { spell = 2645, add = 0.40, outdoors = true },  -- Ghost Wolf (shaman)
  { spell = 768, add = 0, talent = { 17002, 24866 }, per = 0.15, outdoors = true }, -- Cat Form, with Feline Swiftness
  { spell = 5118, add = 0.30, talent = { 19559, 19560 }, per = 0.03 },  -- Aspect of the Cheetah (Pathfinding)
  { spell = 13159, add = 0.30, talent = { 19559, 19560 }, per = 0.03 }, -- Aspect of the Pack (Pathfinding)
}

local function Known(spell)
  if IsPlayerSpell then
    local ok, v = pcall(IsPlayerSpell, spell)
    if ok and v then return true end
  end
  if IsSpellKnown then
    local ok, v = pcall(IsSpellKnown, spell)
    if ok and v then return true end
  end
  return false
end

-- A talent's rank: its rank spells known, else found by name in the talent tabs.
local function TalentRank(ids)
  for rank = #ids, 1, -1 do
    if Known(ids[rank]) then return rank end
  end
  local want = ns.SpellName and ns.SpellName(ids[1])
  if not (want and GetNumTalentTabs and GetNumTalents and GetTalentInfo) then return 0 end
  local ok, rank = pcall(function()
    for tab = 1, GetNumTalentTabs() do
      for i = 1, GetNumTalents(tab) do
        local name, _, _, _, r = GetTalentInfo(tab, i)
        if name == want then return r or 0 end
      end
    end
    return 0
  end)
  return ok and rank or 0
end

-- Whether a spell's aura (or shapeshift form) is on the player.
local function AuraOn(spell)
  local ok, on = pcall(function()
    if C_UnitAuras and C_UnitAuras.GetPlayerAuraBySpellID then
      local a = C_UnitAuras.GetPlayerAuraBySpellID(spell)
      if a then return true end
    end
    if GetNumShapeshiftForms and GetShapeshiftFormInfo then
      for i = 1, GetNumShapeshiftForms() do
        local _, active, _, id = GetShapeshiftFormInfo(i)
        if active and id == spell then return true end
      end
    end
    if UnitBuff then
      for i = 1, 40 do
        local name, _, _, _, _, _, _, _, _, id = UnitBuff("player", i)
        if not name then break end
        if id == spell then return true end
      end
    end
    return false
  end)
  return ok and on == true
end

-- The movement ability to show: the one on, else the fastest known. { spell, name, icon,
-- speed, active } or nil. Checked at most every half second (the auras) and 10 s (the
-- spells and talents known).
local abilities, abilitiesAt, abilityNow, abilityAt
local function AbilitySpeed(a, cdb)
  local learned = cdb and cdb.moveSpeeds and cdb.moveSpeeds[a.spell]
  if learned then return learned end
  return lastRun * (1 + a.add + (a.rank or 0) * (a.per or 0))
end
function N.MoveAbility()
  local now = GetTime()
  if not abilities or now - abilitiesAt >= 10 then
    abilities, abilitiesAt = {}, now
    for _, a in ipairs(N.MOVE_ABILITIES) do
      if Known(a.spell) then
        local rank = a.talent and TalentRank(a.talent) or 0
        if a.add + rank * (a.per or 0) > 0 then
          abilities[#abilities + 1] = { spell = a.spell, add = a.add, per = a.per, rank = rank, outdoors = a.outdoors }
        end
      end
    end
    abilityAt = nil
  end
  if #abilities == 0 then return nil end
  if abilityNow and abilityAt and now - abilityAt < 0.5 then return abilityNow end
  local cdb = ns.CharDB and ns.CharDB()
  local best, on
  for _, a in ipairs(abilities) do
    a.speed = AbilitySpeed(a, cdb)
    if AuraOn(a.spell) then on = a end
    if not best or a.speed > best.speed then best = a end
  end
  local a = on or best
  if not a.name then
    local name = ns.SpellName and ns.SpellName(a.spell) or "Ability"
    a.name = name:gsub("^Aspect of the ", "")
    a.icon = ns.SpellIcon and ns.SpellIcon(a.spell)
  end
  a.active = on ~= nil
  abilityNow, abilityAt = a, now
  return a
end

-- "Ghost Wolf" with its icon, for the times line.
function N.AbilityLabel(a)
  return a.icon and string.format("|T%s:12|t %s", a.icon, a.name) or a.name
end

-- Riding skill rank (0 if not learned). Classic keeps riding as a skill line.
local riding, ridingAt -- cached: Speeds() runs every redraw
function N.RidingRank()
  local now = GetTime()
  if riding and now - ridingAt < 10 then return riding end
  local ok, rank = pcall(function()
    for i = 1, GetNumSkillLines() do
      local name, isHeader, _, skillRank = GetSkillLineInfo(i)
      if not isHeader and name == (RIDING or "Riding") then return skillRank end
    end
    return 0
  end)
  riding, ridingAt = ok and rank or 0, now
  return riding
end

-- current speed, walking (run) speed, mounted speed or nil if the player can't ride, mounted?,
-- and the movement ability (N.MoveAbility) or nil. The walking speed is the plain run speed
-- (the Speed stat and items in it), or the ability's while it's on.
-- GetUnitSpeed is secret in combat; the last values seen are used then.
function N.Speeds()
  local cur, run
  local ok, a, b = pcall(GetUnitSpeed, "player")
  if ok and a and not ns.IsSecret(a) then cur, run = a, b end
  -- a flight counts as mounted to the game: not here (and its speed isn't a mount's)
  local onTaxi = UnitOnTaxi and UnitOnTaxi("player") or false
  local mounted = not onTaxi and IsMounted and IsMounted() or false
  local cdb = ns.CharDB and ns.CharDB()
  local ability = N.MoveAbility()
  if run and run > 0 and not onTaxi and not mounted then
    if ability and ability.active then
      -- (its speed as the server has it, kept per character)
      if cdb and run > lastRun + 0.2 then
        cdb.moveSpeeds = cdb.moveSpeeds or {}
        cdb.moveSpeeds[ability.spell] = run
      end
    else
      lastRun, plainSeen = run, true
    end
  end
  if not plainSeen and GetSpeed then
    -- (not seen on foot yet: the base run speed and the Speed stat, a percentage)
    local sok, pct = pcall(GetSpeed)
    if sok and type(pct) == "number" and not ns.IsSecret(pct) and pct >= 0 and pct < 100 then
      lastRun = DEFAULT_RUN * (1 + pct / 100)
    end
  end
  if ability then ability.speed = AbilitySpeed(ability, cdb) end
  -- a mounted time only for characters that have learned to ride
  local rank = N.RidingRank()
  if mounted then rank = math.max(rank, 75) end -- on a mount (the skill list may be collapsed)
  local mount
  if rank >= 75 then
    if mounted and cur and cur > lastRun + 0.5 and cur <= lastRun * 3 then
      if cdb then cdb.mountSpeed = cur end -- includes riding skill, items and buffs
    end
    if mounted and cur and cur > 0 then
      mount = cur
    elseif cdb and cdb.mountSpeed and cdb.mountSpeed <= lastRun * 3 then
      mount = cdb.mountSpeed
    else
      mount = lastRun * (rank >= 150 and 2.0 or 1.6)
    end
  end
  local walk = (ability and ability.active and not mounted) and ability.speed or lastRun
  return cur, walk, mount, mounted and mount ~= nil, ability
end

---------------------------------------------------------------------------
-- Formatting and status
---------------------------------------------------------------------------

function N.FormatTime(seconds)
  if not seconds or seconds ~= seconds or seconds == math.huge then return "--" end
  seconds = math.floor(seconds + 0.5)
  local h, m, s = math.floor(seconds / 3600), math.floor(seconds % 3600 / 60), seconds % 60
  if h > 0 then return string.format("%dh %02dm %02ds", h, m, s) end
  if m > 0 then return string.format("%dm %02ds", m, s) end
  return string.format("%ds", s)
end

function N.FormatDistance(yd)
  if yd >= 1000 then return string.format("%.1fk yd", yd / 1000) end
  return string.format("%d yd", math.floor(yd + 0.5))
end

N.STEP_MIN_YD = 15 -- shorter walks (e.g. already at the dock) aren't listed as steps

-- How a stop is named in the steps: its marker and name.
local function StopLabel(i, d, count)
  local icon = string.format("|T%s:12|t ", N.StopIcon(d))
  if d.name then return icon .. d.name end
  if count > 1 then return icon .. "stop " .. i end
  return icon .. "your destination"
end

-- The route as a list of steps (strings), from where the player is: walks to docks and
-- stops, rides on zeppelins and boats. Uses the last computed route (N.Route).
function N.Steps()
  local r = N.route
  if not r or not r.stretches then return {} end
  local steps = {}
  local count = #N.stops
  -- time for each stretch (from the previous stop, or from the player for the first):
  -- walking at mount speed while mounted, else run speed, plus transport rides
  local _, walk, mount, mounted = N.Speeds()
  local speed = mounted and mount or walk
  local learn = N.LearnOnRoute(r) or {}
  -- (a walk passing flight masters to learn: split where it passes each, the detour between;
  -- `yards` the walk's still to go: returns what's left after the detours)
  -- (a detour where the walk ends, the stop or a dock: after the walk's step, `after`)
  local function Detour(h)
    if h.off < N.LEARN_BY_YD then -- (right by the way)
      steps[#steps + 1] = string.format("|cffc08040Learn the flight path at %s (on the way)|r", h.name)
    else
      steps[#steps + 1] = string.format("|cffc08040Detour %s to learn the flight path at %s|r", N.FormatDistance(h.off), h.name)
    end
  end
  local function Detours(leg, yards)
    local walked, after = 0, {}
    for _, h in ipairs(learn) do
      if h.leg == leg and h.along >= walked then
        if h.along > yards - N.STEP_MIN_YD then
          after[#after + 1] = h
        else
          if h.along - walked >= N.STEP_MIN_YD then steps[#steps + 1] = "Walk " .. N.FormatDistance(h.along - walked) end
          Detour(h)
          walked = h.along
        end
      end
    end
    return yards - walked, after
  end
  for i, st in ipairs(r.stretches) do
    local d = N.stops[i]
    if st and d then
      local legs = st.legs
      local done = i == 1 and (r.consumed or 0) or 0 -- already walked (following the route)
      local took = string.format("  |cffffd100%s|r", N.FormatTime(math.max(0, st.walk - done) / speed + st.ride))
      for k, leg in ipairs(legs) do
        if leg.ride then
          local t, from = leg.ride, leg.from
          steps[#steps + 1] = t.flying and string.format("Flying to %s", t[10])
            or t.use and string.format("Use %s (to %s)", t[8], t[10])
            or t.learn and string.format("Learn the flight path, then take the flight to %s", t[10])
            or string.format("Take the %s to %s", t[8], from == 1 and t[10] or t[9])
        elseif (leg.yards or 0) - (k == 1 and done or 0) >= N.STEP_MIN_YD or k == #legs then
          local nxt = legs[k + 1]
          local left, after = Detours(leg, math.max(0, (leg.yards or 0) - (k == 1 and done or 0)))
          local dist = N.FormatDistance(left)
          if nxt and nxt.ride then
            local t = nxt.ride
            steps[#steps + 1] = string.format("Walk %s to the %s (%s)", dist, t[11] or t[8], nxt.from == 1 and t[9] or t[10])
          else
            steps[#steps + 1] = string.format("Walk %s to %s", dist, StopLabel(i, d, count))
              .. (count > 1 and took or "")
          end
          for _, h in ipairs(after) do Detour(h) end
        end
      end
    end
  end
  -- the stops after those routed (the option: stops routed and drawn ahead): listed too, not worked
  -- out yet (about: the straight line from the one before, as planning counts it)
  local planned = N.PlannedStops()
  local prev = N.stops[planned]
  for i = planned + 1, #N.stops do
    local d = N.stops[i]
    local far = prev and Geo.Base(prev.cont) == Geo.Base(d.cont)
      and math.sqrt((d.x - prev.x) ^ 2 + (d.y - prev.y) ^ 2) * N.WALK_FACTOR
    steps[#steps + 1] = string.format("|cff9d9d9d%s to %s (not routed yet)|r",
      far and ("About " .. N.FormatDistance(far)) or "Then", StopLabel(i, d, count))
    prev = d
  end
  return steps
end

-- Steps text for the nav panel: the first `shown` steps numbered, then "... N more".
-- Empty when the trip is a single walk.
function N.StepsText(shown)
  if N.questing then return "" end
  local steps = N.Steps()
  if #steps < 2 then return "" end
  shown = shown or 3
  local lines = {}
  for i = 1, math.min(shown, #steps) do
    lines[i] = string.format("%s%d. %s|r", i == 1 and "|cffffffff" or "|cffb0b0b0", i, steps[i])
  end
  if #steps > shown then
    lines[#lines + 1] = string.format("|cff808080... %d more step%s|r", #steps - shown, #steps - shown > 1 and "s" or "")
  end
  return table.concat(lines, "\n")
end

---------------------------------------------------------------------------
-- Corpse run: released as a ghost, your body becomes stop 1 (the skull marker, a red
-- route), ahead of whatever stops there are, whether there was a route or not. It stays
-- first: no reordering moves it. Alive again, it's taken off and the route goes on.
---------------------------------------------------------------------------

N.CORPSE_CHECK = 1 -- seconds between checks
N.CORPSE_ICON = 8 -- the skull
N.CORPSE_COLOR = { 1, 0.12, 0.08 }
local corpseCheckAt = -math.huge

-- Where your body is: cont, x, y (world), or nil. Asked on the map you're on, then on the
-- continents (the body can be in the next zone from the graveyard).
local function CorpseSpot()
  local D = C_DeathInfo
  if not (D and D.GetCorpseMapPosition) then return nil end
  local maps = {}
  local here = C_Map and C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
  if here then maps[1] = here end
  for id, m in pairs(ns.Maps or {}) do
    if m.type == 2 then maps[#maps + 1] = id end
  end
  for _, id in ipairs(maps) do
    local m = ns.Maps and ns.Maps[id]
    local pos = m and m.bounds and D.GetCorpseMapPosition(id)
    if pos and not (ns.IsSecret and ns.IsSecret(pos)) then
      local u, v
      if pos.GetXY then u, v = pos:GetXY() else u, v = pos.x, pos.y end
      if u and v and (u > 0 or v > 0) and u <= 1 and v <= 1 then
        local b = m.bounds
        return Geo.MapCont(id), b[3] - v * (b[3] - b[1]), b[4] - u * (b[4] - b[2])
      end
    end
  end
end

function N.DeathCheck()
  local now = GetTime()
  if now - corpseCheckAt < N.CORPSE_CHECK then return end
  corpseCheckAt = now
  local ghost = UnitIsGhost and UnitIsGhost("player")
  if ns.IsSecret and ns.IsSecret(ghost) then return end
  local body
  if ghost then
    local cont, x, y = CorpseSpot()
    if cont then body = { x = x, y = y, cont = cont, name = "Your body", icon = N.CORPSE_ICON, corpse = true } end
  end
  local d = N.stops[1]
  if body and d and d.corpse and d.cont == body.cont and math.abs(d.x - body.x) < 1 and math.abs(d.y - body.y) < 1 then
    N.corpse = true
    return -- already first
  end
  -- take off any body stop (alive again, or it moved), then put it first
  local changed = false
  for i = #N.stops, 1, -1 do
    if N.stops[i].corpse then
      table.remove(N.stops, i)
      changed = true
    end
  end
  if body then
    table.insert(N.stops, 1, body)
    changed = true
  end
  N.corpse = body ~= nil or nil
  if changed then Changed() end
end

---------------------------------------------------------------------------
-- Questing (option, on by default): a stop inside the area of quests in the log (as the
-- map outlines them, overlapping ones too) is done when those quests' objectives are, not
-- when you get there. In one of those areas (N.questing = the quests there) the directions
-- show the objectives, and the arrow still leads to the stop's spot until you've been
-- there (d.spotReached); after that the route waits while you're in the area
-- (N.QuestPaused). Leave before they're done and the route leads back. Then on to the
-- next stop.
---------------------------------------------------------------------------

N.QUEST_CHECK = 0.5 -- seconds between checks
-- The stop's quests done while you're in their area (or after being at its spot): the stop
-- is done. Done outside the area: it's a plain stop again, reached by going there.
local questCheckAt, questCheckVersion = -math.huge, nil

local function QuestActive(id)
  local Q = C_QuestLog
  if not Q then return false end
  local secret = ns.IsSecret or function() return false end
  local complete = Q.IsComplete and Q.IsComplete(id)
  if complete and not secret(complete) then return false end
  local on = Q.IsOnQuest and Q.IsOnQuest(id)
  if Q.IsOnQuest and not secret(on) and not on then return false end -- abandoned or turned in
  return true -- (hidden in combat: still open, until known otherwise)
end

local function QuestingOn()
  return ns.settings and ns.settings.gps.questing ~= false and not N.loop and not N.corpse and ns.Layers
    and ns.Layers.QuestsAt
end

-- The stop's quests still to do, sorted. Remembers every quest whose area holds the stop
-- (d.quests): a quest finished drops out of the areas, but still counts as the stop's.
local function StopQuests(d)
  for _, id in ipairs(ns.Layers.QuestsAt(d.cont, d.x, d.y)) do
    d.quests = d.quests or {}
    d.quests[id] = true
  end
  local open = {}
  for id in pairs(d.quests or {}) do
    if QuestActive(id) then open[#open + 1] = id end
  end
  table.sort(open)
  return open
end

-- Every QUEST_CHECK seconds (Status): the next stop's quests, and whether the player is in
-- one of their areas. Sets N.questing, and d.questDone once its quests are all done.
function N.QuestCheck(px, py, cont)
  local d = N.dest
  if not QuestingOn() then
    N.questing, N.areaQuests = nil, nil
    return
  end
  local now = GetTime()
  if now - questCheckAt < N.QUEST_CHECK and questCheckVersion == version then return end
  questCheckAt, questCheckVersion = now, version
  local L = ns.Layers
  -- keep the areas around the player traced, even with the quest areas layer off
  if L.EachArea and C_Map and C_Map.GetBestMapForUnit then
    L.EachArea(cont, px, py, 0, { C_Map.GetBestMapForUnit("player") }, function() end)
  end
  -- the open quests whose areas the player is in (on the way anywhere: N.areaQuests)
  local at = L.QuestsAt(cont, px, py)
  if not d then -- no route: just the areas you're in (the arrow window shows them)
    N.questing, N.areaQuests = nil, at[1] and at or nil
    return
  end
  -- in the quest area of a later stop: that stop first (already here: faster to do it now)
  local destHere = false
  for _, id in ipairs(L.AreaContains and at or {}) do
    if L.AreaContains(id, d.cont, d.x, d.y) then destHere = true end
  end
  if at[1] and #N.stops > 1 and L.AreaContains and not destHere then
    for i = 2, #N.stops do
      local s = N.stops[i]
      local hit = false
      for _, id in ipairs(at) do
        if L.AreaContains(id, s.cont, s.x, s.y) then
          s.quests = s.quests or {}
          s.quests[id] = true
          hit = true
        end
      end
      if hit and not s.questDone then
        table.insert(N.stops, 1, table.remove(N.stops, i))
        Changed()
        d = N.dest
        questCheckVersion = version
        break
      end
    end
  end
  local open = StopQuests(d)
  if d.quests and #open == 0 then
    -- all done: in the quest's area (or been at the spot), this stop is reached
    -- (CheckArrival moves on); outside it, it's reached by going there, like any stop
    local inArea = N.questing ~= nil -- in the area at the last check
    for id in pairs(d.quests) do
      if L.AreaContains and L.AreaContains(id, cont, px, py) then inArea = true end
    end
    if inArea or d.spotReached then d.questDone = true end
    N.questing = nil
    N.areaQuests = at[1] and at or nil
    return
  end
  local here, inside, stopQuest = {}, {}, {}
  for _, id in ipairs(at) do inside[id] = true end
  for _, id in ipairs(open) do
    stopQuest[id] = true
    if inside[id] then here[#here + 1] = id end
  end
  local was = N.questing
  N.questing = here[1] and here or nil
  if was and not N.questing then N.route = nil end -- left the area: the route leads back
  -- other quest areas the player is in (not the stop's): shown with the directions
  local other = {}
  for _, id in ipairs(at) do
    if not stopQuest[id] then other[#other + 1] = id end
  end
  N.areaQuests = other[1] and other or nil
end

-- In the stop's quest area, and its spot already reached: the route waits, no arrow.
function N.QuestPaused()
  return N.questing ~= nil and N.dest ~= nil and N.dest.spotReached == true
end

-- The quests being done here (default: the stop's, N.questing), for the directions:
-- { { text, r, g, b }, ... } (titles in gold, objectives white, finished ones gray).
function N.QuestLines(ids)
  local out = {}
  for _, id in ipairs(ids or N.questing or {}) do
    local title, objectives = ns.Layers.QuestObjectives(id)
    out[#out + 1] = { title or ("Quest " .. id), 1, 0.82, 0 }
    for _, o in ipairs(objectives) do
      if o.finished then out[#out + 1] = { o.text, 0.55, 0.55, 0.55 } else out[#out + 1] = { o.text, 1, 1, 1 } end
    end
  end
  return out
end

-- Reaching a stop that isn't the last one moves on to the next stop; reaching the last
-- one marks the trip as arrived (cleared a few seconds later by Tick). A questing stop
-- (see above) is reached when its quests are done, not by getting there.
local function CheckArrival(px, py, cont)
  local d = N.dest
  while d do
    if d.corpse then return false end -- at your body: it stays until you're alive (DeathCheck)
    local at = cont == d.cont and math.sqrt((d.x - px) ^ 2 + (d.y - py) ^ 2) <= ARRIVED_YD
    if not d.questDone and at and QuestingOn() and d.quests and StopQuests(d)[1] then
      d.spotReached = true -- at the spot, its quests still open: stay (see QuestCheck)
      at = false
    end
    if d.boss then -- a boss: done when it dies (wherever you are), not by getting there
      at = false
      if not d.bossDone and N.BossDead(d) then d.bossDone = true end
    end
    if not (d.questDone or d.served or d.bossDone or at) then break end
    if ns.Feedback and not N.arrivedAt then ns.Feedback.Arrived(d) end
    if N.loop and #N.stops > 1 then
      -- a loop: this stop goes to the end, on to the next one
      table.insert(N.stops, table.remove(N.stops, 1))
      Changed()
      return false
    end
    if #N.stops <= 1 then
      -- (the last one: the route goes at once; "Arrived" stays up a few seconds, N.Tick. Kept
      -- as the stop until then, running on out of its circle brought the route to it back.)
      N.Clear()
      N.arrivedAt = GetTime()
      return true
    end
    table.remove(N.stops, 1)
    Changed()
    d = N.dest
  end
  return false
end

-- "Working out the route...", and now and then said another way (asked, 2026-10-01): in Murloc one time
-- in twenty, gnome engineers at it one in five, goblin engineers another one in five (N.WORKING_FLAVORS:
-- each its share of the times and its lines). Picked once each time a
-- route is being worked out (not every redraw: it would flicker), until there's a route. N.FUN = false:
-- always the plain one (the tests).
N.WORKING_TEXT = "Working out the route..."
N.WORKING_FLAVORS = {
  { share = 0.05, lines = { "Mrglglglgl... mrrgll mrgl...", "Aaaaaughibbrgubugbugrguburgle!",
    "Mmmrrglllm... rrrgle mrgl?", "Mrrrggk! Mglrmglmglmgl..." } },
  { share = 0.2, lines = { "Recalibrating the gyro-o-matic...", "Consulting the Tinker Town schematics...",
    "Spinning up the Route-o-Tron 3000...", "Oiling the cogs of the navigation engine..." } },
  { share = 0.2, lines = { "Time is money, friend! Routing...", "Charging extra for the shortcut..." } },
}
N.Random = math.random
local working -- (the text picked while the route is being worked out)
function N.WorkingText()
  if not working then
    working = N.WORKING_TEXT
    if N.FUN ~= false then
      local roll, at = N.Random(), 0
      for _, f in ipairs(N.WORKING_FLAVORS) do
        at = at + f.share
        if roll < at then
          working = f.lines[N.Random(#f.lines)]
          break
        end
      end
    end
  end
  return working
end

-- Text for the nav panel, or nil when there is no destination.
function N.Status(px, py, cont)
  cont = N.PlayerLevel(cont)
  N.DeathCheck()
  if not N.dest then
    N.QuestCheck(px, py, cont) -- (no route: the quest areas you're in, for the arrow window)
    if N.arrivedAt then return "|cff40ff40Arrived|r" end -- (the last stop just reached)
    return nil
  end
  N.QuestCheck(px, py, cont)
  if CheckArrival(px, py, cont) then return "|cff40ff40Arrived|r" end
  if N.questing then
    -- in the stop's quest area: the objectives instead of directions (and the way to the
    -- spot, until it's reached)
    if not N.QuestPaused() then N.Route(px, py, cont) end
    local lines = { "|cffffd100In the quest area|r" }
    local ql = N.QuestLines()
    for _, l in ipairs(N.areaQuests and N.QuestLines(N.areaQuests) or {}) do ql[#ql + 1] = l end
    for _, l in ipairs(ql) do
      lines[#lines + 1] = string.format("|cff%02x%02x%02x%s|r", math.floor(l[2] * 255), math.floor(l[3] * 255), math.floor(l[4] * 255), l[1])
    end
    return table.concat(lines, "\n")
  end
  N.MaybeReorder(px, py, cont)
  local d = N.dest
  local r = N.Route(px, py, cont)
  if not r then return N.warming and N.WorkingText() or "No way there found" end
  working = nil -- (the next time: picked again)
  local cur, walk, mount, mounted, ability = N.Speeds()
  local head = N.FormatDistance(r.length)
  local multi = #N.stops > 1
  if multi then head = string.format("|T%s:14|t 1/%d  %s", N.StopIcon(d), #N.stops, head) end
  local t, from, atDock = NextRide(r, px, py)
  if r.flying then
    head = string.format("|cffffd100Flying to %s|r  lands in %s", r.flying.to, N.FormatTime(r.flying.seconds))
  elseif t then
    local to = from == 1 and t[10] or t[9]
    if t.use then
      head = string.format("|cffffd100Use %s|r (to %s)", t[8], to)
    elseif atDock and t.learn then
      head = string.format("|cffffd100Learn the flight path, then fly to %s|r", to)
    elseif atDock then
      head = string.format("|cffffd100Board the %s to %s|r", t[8], to)
    else
      head = head .. string.format("  to the %s (then to %s)", t[11] or t[8], to)
    end
  end
  if cur and cur > 0.5 and not r.flying then head = head .. "   |cffffffffETA " .. N.FormatTime(r.walkYards / cur + r.rideSeconds) .. "|r" end
  -- walking and mounted times: to the stop, or for the whole trip with several stops
  local yards, ride, line = r.walkYards, r.rideSeconds, ""
  if multi then
    yards, ride = r.totalYards, r.totalRide
    local planned = N.PlannedStops()
    line = (planned < #N.stops and not N.loop) and string.format("Next %d stops: ", planned) or "All stops: "
  end
  -- mounted: just the mounted time; on foot: walking (or the movement ability while it's on),
  -- the ability's time when one is known, and mounted if the character can ride
  if mount and mounted then
    line = line .. "Mount " .. N.FormatTime(yards / mount + ride)
  else
    local on = ability and ability.active
    line = line .. (on and N.AbilityLabel(ability) or "Walk") .. " " .. N.FormatTime(yards / walk + ride)
    if ability and not on then
      line = line .. "    " .. N.AbilityLabel(ability) .. " " .. N.FormatTime(yards / ability.speed + ride)
    end
    if mount then line = line .. "    Mount " .. N.FormatTime(yards / mount + ride) end
  end
  -- in another quest's area on the way: its objectives first (the times line stays last:
  -- the collapsed panel shows just that)
  if N.areaQuests then
    local q = { "|cffffd100! In a quest area|r" }
    for _, l in ipairs(N.QuestLines(N.areaQuests)) do
      q[#q + 1] = string.format("|cff%02x%02x%02x%s|r", math.floor(l[2] * 255), math.floor(l[3] * 255), math.floor(l[4] * 255), l[1])
    end
    head = table.concat(q, "\n") .. "\n" .. head
  end
  local hint = N.HeightText(px, py, cont)
  if hint then head = head .. "\n" .. hint end
  if d.boss and cont == d.cont and math.sqrt((d.x - px) ^ 2 + (d.y - py) ^ 2) <= N.BOSS_NEAR_YD then
    head = string.format("|cffffd100Defeat %s|r\n", d.name or "the boss") .. head
  end
  return head .. "\n" .. line
end

-- The flight masters of the player's faction they haven't learned, by the route's walks still ahead
-- (within LEARN_NEAR_YD), in the order the route passes them: a list of { name, off = yards from the
-- route, leg = the walk passing it, along = yards along that walk (its part) to where it passes,
-- cont, x, y = the flight master, rx, ry = the nearest point of the route }, or nil. Each a detour:
-- a brown line on the map from the route to it and its pin (GPSFrame), and a step where that walk
-- passes it (Steps: the walk split there); the route itself isn't changed. Learned on the way, the next trips may fly from it (Taxi.lua sees it on the flight map:
-- the route is worked out again). Only once a flight map has been seen (else what's known isn't),
-- and not with flights turned off.
N.LEARN_NEAR_YD = 450 -- (Tarren Mill from the walk into Arathi: 390 yd off it)
N.LEARN_BY_YD = 40 -- ... this close: "on the way", not a detour
local mastersList
-- Flight masters whose detour the player removed (right-click on its pin: GPSFrame): not suggested
-- again on this route, rerouting or after a /reload (saved with the stops); a new route clears it.
N.skipLearn = {}
function N.SkipLearn(node)
  N.skipLearn[node] = true
  if N.route then N.route.learnAt = nil end
  N.SaveStops()
end
function N.LearnOnRoute(r)
  local st = ns.settings and ns.settings.gps
  if not (r and r.parts) or r.flying or (st and st.useFlights == false) or N.corpse then return nil end
  local fac = Faction()
  local known, count = N.KnownFlightNodes()
  if not fac or count < 1 then return nil end
  local at = math.floor((r.consumed or 0) / 50)
  if r.learnAt == at then return r.learnHint or nil end
  if not mastersList then
    mastersList = {}
    for node, m in pairs(Masters()) do mastersList[#mastersList + 1] = { node, m } end
  end
  local cands = {}
  for _, e in ipairs(mastersList) do
    local m = e[2]
    -- (not the game's obsolete ones: "zzOLD..." names in its data)
    if not known[e[1]] and not N.skipLearn[e[1]] and m[5] and string.find(m[5], fac, 1, true)
        and not (m[4] or ""):find("^zz") then cands[#cands + 1] = e end
  end
  -- (each flight master: the nearest point of the route's walks to it, if within reach)
  local best = {}
  local near2 = N.LEARN_NEAR_YD * N.LEARN_NEAR_YD
  for pi, part in ipairs(r.parts) do
    local c, pts, kinds = Geo.Base(part.cont), part.pts, part.kinds
    local acc = 0
    for i = 1, #pts - 3, 2 do
      local ax, ay, bx, by = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
      local vx, vy = bx - ax, by - ay
      local L2 = vx * vx + vy * vy
      if kinds[(i + 1) / 2] ~= N.KIND_TRANSPORT then
        for _, e in ipairs(cands) do
          local m = e[2]
          if Geo.Base(m[1]) == c then
            local t = L2 > 0 and math.max(0, math.min(1, ((m[2] - ax) * vx + (m[3] - ay) * vy) / L2)) or 0
            local d2 = (ax + vx * t - m[2]) ^ 2 + (ay + vy * t - m[3]) ^ 2
            local b = best[e[1]]
            if d2 <= near2 and (not b or d2 < b.d2) then
              best[e[1]] = { name = (m[4]:match("^([^,]+)") or m[4]), full = m[4], off = math.sqrt(d2), d2 = d2, node = e[1],
                leg = part.leg, cont = c, x = m[2], y = m[3], rx = ax + vx * t, ry = ay + vy * t,
                part = pi, along = acc + math.sqrt(L2) * t }
            end
          end
        end
      end
      acc = acc + math.sqrt(L2)
    end
  end
  -- (not one the route takes a flight from: learned there, "Learn the flight path, then...")
  local from = {}
  for _, leg in ipairs(r.legs or {}) do
    if leg.ride and leg.ride.pts then from[leg.ride[leg.from == 2 and 10 or 9] or ""] = true end
  end
  -- (in the order the route passes them)
  local list = {}
  for _, b in pairs(best) do
    if not from[b.full] then list[#list + 1] = b end
  end
  table.sort(list, function(a, b) return a.part < b.part or (a.part == b.part and a.along < b.along) end)
  r.learnAt, r.learnHint = at, list[1] and list or false
  return list[1] and list or nil
end

-- Called every redraw: "Arrived" goes a few seconds after reaching the last stop (the route
-- went at once).
N.ARRIVED_SHOWN = 5
function N.Tick()
  if N.arrivedAt and GetTime() - N.arrivedAt > N.ARRIVED_SHOWN then N.arrivedAt = nil end
end

-- Heights in an underground city: its floors' height at (x, y) on `level` (the model's
-- own, relative), or nil.
local HTILE = 1600 / 3
local RUN = {} -- (a run's length character: ALPHABET, 1 to 64)
do
  local chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
  for i = 1, #chars do RUN[chars:byte(i)] = i end
end
function N.CityHeight(level, x, y)
  local h, g = ns.CityHeights and ns.CityHeights[level], ns.Terrain and ns.Terrain[level]
  if not (h and g and x) then return nil end
  local k = HTILE / g.cell
  local col = math.floor(((32 - y / HTILE) - g.tx0) * k) + 1
  local row = math.floor(((32 - x / HTILE) - g.ty0) * k) + 1
  local s = h.rows[row]
  if s and h.runs then
    -- (an instance's rows, Data/Instances.lua: runs of a height character and its length;
    -- a row is spelled out the first time it's read)
    h.plain = h.plain or {}
    if not h.plain[row] then
      local out = {}
      for i = 1, #s - 1, 2 do out[#out + 1] = s:sub(i, i):rep(RUN[s:byte(i + 1)] or 1) end
      s = table.concat(out)
      h.rows[row], h.plain[row] = s, true
    end
  end
  local b = s and s:byte(col)
  if not b or b == 46 then return nil end -- (".": no floor)
  if b > 92 then b = b - 1 end -- (the backslash isn't used)
  return (b - 48) * h.step + h.z0
end

-- A stop's height, the game's: its own (a city place's, a boss's), or down in an underground
-- city, the floor's under it (the most common near it: N.CityFloor); nil when unknown.
function N.StopZ(d)
  if d.z then return d.z end
  local l = ns.CityLevels and ns.CityLevels[d.cont]
  local h = l and l.zoff and N.CityFloor(d.cont, d.x, d.y)
  return h and h + l.zoff or nil
end

-- The player's height in an underground city's own terms (its heights are the model's: the
-- game's height less the level's zoff), or nil when unknown.
function N.PlayerCityZ(level)
  local l = ns.CityLevels and ns.CityLevels[level]
  local z = l and l.zoff and N.PlayerZ()
  return z and z - l.zoff or nil
end

-- The floor a stop is on: the most common floor height within a few yards (a marker can
-- sit on a sliver of another floor, under or beside a counter).
N.FLOOR_AROUND_YD = 4
function N.CityFloor(level, x, y)
  local count, best, bestN = {}, nil, 0
  local r = N.FLOOR_AROUND_YD
  for dx = -r, r, 2 do
    for dy = -r, r, 2 do
      local h = N.CityHeight(level, x + dx, y + dy)
      if h then
        count[h] = (count[h] or 0) + 1
        if count[h] > bestN then best, bestN = h, count[h] end
      end
    end
  end
  return best
end

-- Where the stop is against the player, up or down: "down" / "up" and yards (nil when on
-- another level: down or up a lift), or nil when it's about level with them.
N.HEIGHT_HINT_YD = 6
function N.HeightHint(px, py, cont)
  local d = N.dest
  if not (d and px and ns.CityLevels) then return nil end
  -- (what's walked to now: the next stop, or where the next ride (a flight, a lift) is boarded)
  local tc, tx, ty = d.cont, d.x, d.y
  local legs = N.route and N.route.legs
  if legs and legs[1] and legs[1].walk and legs[2] and legs[2].ride then
    local t, from = legs[2].ride, legs[2].from
    tc, tx, ty = from == 1 and t[1] or t[4], from == 1 and t[2] or t[5], from == 1 and t[3] or t[6]
  end
  local lvl = N.PlayerLevel(cont)
  if Geo.Base(tc) ~= Geo.Base(lvl) then return nil end
  if tc ~= lvl then
    if ns.CityLevels[tc] then return "down" end
    if ns.CityLevels[lvl] then return "up" end
    return nil
  end
  if not ns.CityLevels[lvl] then return nil end
  -- (the player's own height, and the stop's when it has one: not the top floor over them)
  local zoff = ns.CityLevels[lvl].zoff
  local zs = (tx == d.x and ty == d.y and d.z and zoff) and d.z - zoff or N.CityFloor(lvl, tx, ty)
  local zp = N.PlayerCityZ(lvl) or N.CityHeight(lvl, px, py)
  if not (zs and zp) or math.abs(zs - zp) < N.HEIGHT_HINT_YD then return nil end
  return zs < zp and "down" or "up", math.abs(zs - zp)
end

function N.HeightText(px, py, cont)
  local way, yd = N.HeightHint(px, py, cont)
  if not way then return nil end
  local color = way == "down" and "|cff80c0ff" or "|cffffc080"
  if not yd then return color .. (way == "down" and "Below you (down a lift)" or "Above you (up a lift)") .. "|r" end
  return string.format("%s%s you, %d yd %s|r", color, way == "down" and "Below" or "Above", math.floor(yd + 0.5), way)
end

-- A stop that's a service (a guard's "Bank", "Auction House", a trainer...) is reached when
-- its window opens near it: any of the bankers, not only the spot the guard marked.
-- (event -> words in the stop's name)
N.SERVICES = {
  BANKFRAME_OPENED = { "bank" },
  AUCTION_HOUSE_SHOW = { "auction" },
  MAIL_SHOW = { "mailbox" },
  TAXIMAP_OPENED = { "flight master", "bat handler", "wind rider", "gryphon", "hippogryph" },
  TRAINER_SHOW = { "trainer" },
  MERCHANT_SHOW = { "vendor", "merchant", "supplies", "goods" },
}
N.SERVICE_YD = 60
function N.OnService(event, px, py, cont)
  local words, d = N.SERVICES[event], N.dest
  if not (words and d and d.name and px) or d.corpse then return false end
  if Geo.Base(d.cont) ~= Geo.Base(cont) or (d.x - px) ^ 2 + (d.y - py) ^ 2 > N.SERVICE_YD ^ 2 then return false end
  local name = d.name:lower()
  for _, w in ipairs(words) do
    if name:find(w, 1, true) then
      d.served = true
      return true
    end
  end
  return false
end

-- The highest drop off a ledge the player survives with health to spare: falls up to
-- FALL_FREE yards cost nothing, then about FALL_PER_YD of their health each yard. A ghost
-- takes no fall damage; in combat (health hidden) only the free ones.
N.FALL_FREE = 14
N.FALL_PER_YD = 0.02
N.FALL_KEEP = 0.3 -- of their health left after the fall, at least
function N.SafeDrop()
  if UnitIsGhost and UnitIsGhost("player") then return math.huge end
  local h = UnitHealth and UnitHealth("player")
  local m = UnitHealthMax and UnitHealthMax("player")
  if not h or not m or (ns.IsSecret and (ns.IsSecret(h) or ns.IsSecret(m))) or m <= 0 then return N.FALL_FREE end
  return N.FALL_FREE + math.max(0, h / m - N.FALL_KEEP) / N.FALL_PER_YD
end

do -- a service's window opening (see N.SERVICES)
  local ok, f = pcall(CreateFrame, "Frame")
  if ok and f then
    for e in pairs(N.SERVICES) do pcall(f.RegisterEvent, f, e) end
    f:SetScript("OnEvent", function(_, e)
      local px, py, cont = Geo.PlayerWorld()
      if N.OnService(e, px, py, cont) and ns.GPS and ns.GPS.Redraw then ns.GPS.Redraw() end
    end)
  end
end

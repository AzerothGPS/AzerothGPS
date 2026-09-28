-- Navigation state: stops, current route (via Router), distance and ETAs.
local _, ns = ...
local Geo = ns.Geo
local unpack = unpack or table.unpack

local N = {}
ns.Nav = N

local DEFAULT_RUN = 7 -- yd/s, normal run speed
local ARRIVED_YD = 10
local REROUTE_SECONDS = 2 -- at most this often while moving
local REROUTE_MOVED_YD = 15 -- ...and only after moving this far
local REROUTE_STALE = 30 -- standing still: refresh this often anyway
local OFF_ROUTE_YD = 30 -- further than this from the route: recalculate it
-- A terrain search from the player's position finished: the route is recalculated to use
-- it, but at most this often: each recalculation starts searches from the new position,
-- and recalculating on each of those would loop (a recalculation a few times a second).
local SEARCH_RECALC_SECONDS = 3
local searchDirty, searchRecalcAt = false, -math.huge
local FOLLOW_MAX_AGE = 20 -- following the route: recalculate this often anyway
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
N.PLAN_AHEAD = 8 -- stops routed and drawn ahead; the next comes in as each is reached
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
    tex = d.tex }
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
end

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
function N.KeepCityOrder()
  local gps = ns.settings and ns.settings.gps
  if not gps or gps.cityKeepOrder == false or not ns.CityLevels then return false end
  -- (the quest route button's stops are always put in the fastest order, in cities too)
  for _, s in ipairs(N.stops) do
    if s.cont and ns.CityLevels[s.cont] and not s.questRoute then return true end
  end
  return false
end

function N.SetStops(stops, fastest)
  N.stops, N.loop = {}, false
  for i, d in ipairs(stops) do
    if i > N.MAX_STOPS then break end
    local c = Copy(d)
    c.icon = c.icon or N.MarkerFor(i)
    N.stops[#N.stops + 1] = c
  end
  Changed()
  if fastest and #N.stops > 1 and not N.KeepCityOrder() then N.OrderStops() end
end

-- Add a stop at the end of the route (then reorder if `fastest`).
function N.AddStop(d, fastest)
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
  return math.min(#N.stops, N.PLAN_AHEAD)
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
  N.SetStops({ { x = x, y = y, cont = cont, name = name, icon = 1 } })
end

-- Changes whenever the stops do (a new route, a stop added, removed or reached).
function N.Version() return version end

function N.Clear()
  N.stops, N.loop = {}, false
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

-- Recompute the flights on the next plan (a flight map was opened, the option changed).
function N.FlightsChanged()
  flightCache = nil
  N.Invalidate(true, true) -- (also forgets the stop-to-stop times)
end

-- The character's faction as in Data/Pois.lua ("A" / "H"), or nil when unknown.
local function Faction()
  local f = ns.CharDB and ns.CharDB().faction
  return f == "Alliance" and "A" or f == "Horde" and "H" or nil
end
N.Faction = Faction

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
        if not dist[v] or nd < dist[v] then dist[v], prev[v] = nd, u end
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
          fresh[from] and "new flight master" or "flight master", pts = pts, learn = fresh[from] and true or nil }
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

-- Fastest sequence of legs from (px, py) on `cont` to stop d (default: the next stop),
-- walking, taking transports (Data/Transports.lua) and flights between known flight
-- masters. Legs: { walk = true, cont, x1, y1, x2, y2 } or { ride = row, from = 1|2 }
-- (a transport row, or a flight row in the same format; from = which end we board at).
-- `teleports`: rows (Teleports.lua) usable right away from (px, py): hearthstone, etc.
function N.Plan(cont, px, py, speed, d, teleports)
  d = d or N.dest
  local nodes = { { cont, px, py }, { d.cont, d.x, d.y } }
  for _, row in ipairs(teleports or {}) do
    nodes[#nodes + 1] = { row[4], row[5], row[6], tp = row }
  end
  for i, t in ipairs(ns.Transports or {}) do
    nodes[#nodes + 1] = { t[1], t[2], t[3], t = i, side = 1 }
    nodes[#nodes + 1] = { t[4], t[5], t[6], t = i, side = 2 }
  end
  local fl = Flights()
  if fl then
    for node in pairs(fl.trips) do
      local m = fl.masters[node]
      nodes[#nodes + 1] = { m[1], m[2], m[3], fm = node }
    end
  end
  local dist, prev, rode, done = { [1] = 0 }, {}, {}, {}
  while true do
    local u, best
    for i in pairs(dist) do
      if not done[i] and (not best or dist[i] < best) then u, best = i, dist[i] end
    end
    if not u or u == 2 then break end
    done[u] = true
    local a = nodes[u]
    for v, b in ipairs(nodes) do
      if not done[v] then
        local cost, ride
        if a[1] == b[1] then
          cost = math.sqrt((a[2] - b[2]) ^ 2 + (a[3] - b[3]) ^ 2) * N.WALK_FACTOR / speed
        end
        if a.t and b.t == a.t and a.side ~= b.side then
          local secs = ns.Transports[a.t][7]
          if not cost or secs < cost then cost, ride = secs, { ns.Transports[a.t], a.side } end
        end
        if u == 1 and b.tp and (not cost or b.tp[7] < cost) then -- a teleport, from where we stand
          cost, ride = b.tp[7], { b.tp, 1 }
        end
        if a.fm and b.fm then
          local row = fl.trips[a.fm][b.fm]
          if row and (not cost or row[7] < cost) then cost, ride = row[7], { row, 1 } end
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
    if r then
      legs[#legs + 1] = { ride = r[1], from = r[2] }
    else
      legs[#legs + 1] = { walk = true, cont = a[1], x1 = a[2], y1 = a[3], x2 = b[2], y2 = b[3] }
    end
  end
  return legs, dist[2]
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

local function Stretch(cont, sx, sy, d, walk, opts)
  -- from the player's position: the teleports ready now may start the trip
  local tps = opts.teleports -- the teleports this stretch may start with (AssignTeleports)
  local legs = N.Plan(cont, sx, sy, walk, d, tps)
  if not legs then return nil end
  local st = { parts = {}, legs = legs, first = 0, walk = 0, ride = 0, road = 0 }
  local rode = false
  for _, leg in ipairs(legs) do
    if leg.ride then
      local t = leg.ride
      local c1, x1, y1, c2, x2, y2 = t[1], t[2], t[3], t[4], t[5], t[6]
      if leg.from == 2 then c1, x1, y1, c2, x2, y2 = t[4], t[5], t[6], t[1], t[2], t[3] end
      local bx, by = Geo.ToContinent(c2, x2, y2, c1)
      if t.use then -- a teleport: nothing to draw
      elseif t.pts then -- a flight: through its connecting stops (one continent)
        local kinds = {}
        for k = 1, #t.pts / 2 - 1 do kinds[k] = N.KIND_TRANSPORT end
        st.parts[#st.parts + 1] = { cont = c1, pts = t.pts, kinds = kinds }
      elseif bx then
        st.parts[#st.parts + 1] = { cont = c1, pts = { x1, y1, bx, by }, kinds = { N.KIND_TRANSPORT } }
      end
      st.ride = st.ride + t[7]
      rode = true
    else
      local lr = ns.Router.Route(leg.cont, leg.x1, leg.y1, leg.x2, leg.y2,
        (opts.transient and leg.x1 == sx and leg.y1 == sy) and opts or opts.fixed)
      st.parts[#st.parts + 1] = { cont = leg.cont, pts = lr.pts, kinds = lr.kinds }
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
local function Follow(r, px, py)
  local full = r.fullFirst
  if not full then return false end
  local pts, kinds, cum = full.pts, full.kinds, r.cum
  local best, bi, bt
  for i = r.followIdx, #pts / 2 - 1 do
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
  local ax, ay, bx, by = pts[2 * bi - 1], pts[2 * bi], pts[2 * bi + 1], pts[2 * bi + 2]
  local qx, qy = ax + (bx - ax) * bt, ay + (by - ay) * bt
  local consumed = cum[bi] + (cum[bi + 1] - cum[bi]) * bt
  local np, nk = { qx, qy }, {}
  for i = bi, #pts / 2 - 1 do
    np[#np + 1], np[#np + 2] = pts[2 * i + 1], pts[2 * i + 2]
    nk[#nk + 1] = kinds[i]
  end
  local trimmed = { cont = full.cont, pts = np, kinds = nk, stop = full.stop }
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
      laterSt[i] = Stretch(a.cont, a.x, a.y, N.stops[i], walk, { offroad = offroad, fixed = fixed }) or false
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
  if n1 and g1 > 0 then best[n1] = { 1, g1 } end
  for i = 2, N.PlannedStops() do
    local g = later.gains[i]
    if g and g[2] > 0 and (not best[g[1]] or g[2] > best[g[1]][2]) then best[g[1]] = { i, g[2] } end
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
      later[i] = Stretch(a.cont, a.x, a.y, N.stops[i], walk, opts) or false
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

function N.PlayerLevel(cont)
  if not ns.CityLevels or not cont then return cont end
  local now = GetTime()
  if now - levelAt > 0.5 then
    levelAt, levelCache = now, N.CityHere() or nil
  end
  if levelCache and (levelCache == cont or ns.CityLevels[levelCache].base == cont) then return levelCache end
  return cont
end

-- The level of a new stop at (x, y) on `cont`: the city's when the player is down in it and
-- the spot is on its floors, else the continent.
function N.StopLevel(cont, x, y)
  local lvl = N.PlayerLevel(cont)
  if lvl ~= cont and ns.Passability and ns.Passability.IsOpen and ns.Passability.IsOpen(lvl, x, y) then return lvl end
  return cont
end

-- In a city, the floor under the player changing height at a stroke (jumped down, or
-- back up top): worked out again from there (a drop may be the way again).
N.FLOOR_JUMP = 5
N.FLOOR_JUMP_EVERY = 4 -- seconds, at most (walking along a ledge's foot flickers)
local lastFloor, floorJumpAt = nil, -math.huge
function N.Route(px, py, cont)
  cont = N.PlayerLevel(cont)
  local d = N.dest
  if not d then return nil end
  if ns.CityLevels and ns.CityLevels[cont] and px and N.CityHeight then
    local h = N.CityHeight(cont, px, py)
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
  local offroad = ns.settings and ns.settings.gps.offroad or false
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
  if r and r.flying then r, kept = nil, nil end -- just landed: work the route out afresh
  -- the continent's road data is still being built in the background (a moment)
  -- (and the levels the stops are on: a city's, down a lift)
  if not r and ns.Router.WarmUp then
    local busy = ns.Router.WarmUp(cont, px, py)
    for _, s in ipairs(N.stops) do
      if s.cont and s.cont ~= cont then busy = ns.Router.WarmUp(s.cont, s.x, s.y) or busy end
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
  if searchDirty and r and now - searchRecalcAt >= SEARCH_RECALC_SECONDS then
    r, N.route = nil, nil
    moved = math.huge
    searchDirty, searchRecalcAt = false, now
  end
  local age = r and now - N.routeTime or math.huge
  local same = r and N.routeOffroad == offroad and N.routeCont == cont
  if same and age < REROUTE_STALE and (age < REROUTE_SECONDS or moved <= REROUTE_MOVED_YD ^ 2) then
    return r
  end
  -- moving along the route: just follow it (no recalculation)
  if same and age < FOLLOW_MAX_AGE and Follow(r, px, py) then
    N.routeX, N.routeY = px, py
    return r
  end
  -- the route so far, to compare with (also after Invalidate)
  local old = r or kept
  if old and not (old.version == version and old.offroad == offroad and old.cont == cont) then old = nil end
  local _, walk = N.Speeds()
  local t0 = ns.PerfStart and ns.PerfStart()
  local key = version .. ":" .. tostring(offroad)
  if later.key ~= key then later = { key = key, done = {} } end
  local tps = AssignTeleports(cont, px, py, d, walk)
  local t1 = ns.PerfStart and ns.PerfStart()
  local first = Stretch(cont, px, py, d, walk, { offroad = offroad, transient = true, fixed = { offroad = offroad },
    teleports = tps, indoors = N.Indoors() })
  if t1 then ns.PerfEnd("route calculation: next stop", t1) end
  N.route = nil
  if first then
    local t2 = ns.PerfStart and ns.PerfStart()
    FillLater(walk, offroad, N.LATER_PER_CALL)
    if t2 then ns.PerfEnd("route calculation: later stops", t2) end
    N.route = Assemble(first, px, py, cont, walk, offroad)
  end
  -- still on the current route and the new one is clearly longer: keep the current one
  if old and N.route and old ~= N.route and N.KeepOld(old, N.route, walk, now) and Follow(old, px, py) then
    old.keptSince = old.keptSince or now
    N.route = old
  elseif N.route then
    N.route.keptSince = nil
  end
  kept = N.route
  N.routeX, N.routeY, N.routeTime, N.routeOffroad, N.routeCont = px, py, now, offroad, cont
  if t0 then ns.PerfEnd("route calculation", t0) end
  return N.route
end

-- Keep route `old` instead of the recalculated `new`? When `new` is clearly longer (the
-- whole trip, rides counted at walking speed) and either still provisional or `old` hasn't
-- been kept for KEEP_SECONDS yet. (The caller also checks the player is still on `old`.)
function N.KeepOld(old, new, walk, now)
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
  if fresh then kept = nil end
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
        if not used[j] then
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

---------------------------------------------------------------------------
-- Speeds
---------------------------------------------------------------------------

local lastRun = DEFAULT_RUN

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

-- current speed, walking (run) speed, mounted speed or nil if the player can't ride, mounted?
-- GetUnitSpeed is secret in combat; the last values seen are used then.
function N.Speeds()
  local cur, run
  local ok, a, b = pcall(GetUnitSpeed, "player")
  if ok and a and not ns.IsSecret(a) then cur, run = a, b end
  if run and run > 0 then lastRun = run end
  -- a flight counts as mounted to the game: not here (and its speed isn't a mount's)
  local onTaxi = UnitOnTaxi and UnitOnTaxi("player") or false
  local mounted = not onTaxi and IsMounted and IsMounted() or false
  local cdb = ns.CharDB and ns.CharDB()
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
  return cur, lastRun, mount, mounted and mount ~= nil
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
          local dist = N.FormatDistance(math.max(0, (leg.yards or 0) - (k == 1 and done or 0)))
          if nxt and nxt.ride then
            local t = nxt.ride
            steps[#steps + 1] = string.format("Walk %s to the %s (%s)", dist, t[11] or t[8], nxt.from == 1 and t[9] or t[10])
          else
            steps[#steps + 1] = string.format("Walk %s to %s", dist, StopLabel(i, d, count))
              .. (count > 1 and took or "")
          end
        end
      end
    end
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
    if not (d.questDone or d.served or at) then break end
    if ns.Feedback and not N.arrivedAt then ns.Feedback.Arrived(d) end
    if N.loop and #N.stops > 1 then
      -- a loop: this stop goes to the end, on to the next one
      table.insert(N.stops, table.remove(N.stops, 1))
      Changed()
      return false
    end
    if #N.stops <= 1 then
      N.arrivedAt = N.arrivedAt or GetTime()
      return true
    end
    table.remove(N.stops, 1)
    Changed()
    d = N.dest
  end
  return false
end

-- Text for the nav panel, or nil when there is no destination.
function N.Status(px, py, cont)
  cont = N.PlayerLevel(cont)
  N.DeathCheck()
  if not N.dest then
    N.QuestCheck(px, py, cont) -- (no route: the quest areas you're in, for the arrow window)
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
  if not r then return N.warming and "Working out the route..." or "No way there found" end
  local cur, walk, mount, mounted = N.Speeds()
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
  -- mounted: just the mounted time; on foot: walking, and mounted if the character can ride
  if mount and mounted then
    line = line .. "Mount " .. N.FormatTime(yards / mount + ride)
  else
    line = line .. "Walk " .. N.FormatTime(yards / walk + ride)
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
  return head .. "\n" .. line
end

-- Called every redraw: clears the destination a few seconds after arriving.
function N.Tick()
  if N.arrivedAt and GetTime() - N.arrivedAt > 5 then N.Clear() end
end

-- Heights in an underground city: its floors' height at (x, y) on `level` (the model's
-- own, relative), or nil.
local HTILE = 1600 / 3
function N.CityHeight(level, x, y)
  local h, g = ns.CityHeights and ns.CityHeights[level], ns.Terrain and ns.Terrain[level]
  if not (h and g and x) then return nil end
  local k = HTILE / g.cell
  local col = math.floor(((32 - y / HTILE) - g.tx0) * k) + 1
  local row = math.floor(((32 - x / HTILE) - g.ty0) * k) + 1
  local s = h.rows[row]
  local b = s and s:byte(col)
  if not b or b == 46 then return nil end -- (".": no floor)
  return (b - 48) * h.step + h.z0
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
  local lvl = N.PlayerLevel(cont)
  if Geo.Base(d.cont) ~= Geo.Base(lvl) then return nil end
  if d.cont ~= lvl then
    if ns.CityLevels[d.cont] then return "down" end
    if ns.CityLevels[lvl] then return "up" end
    return nil
  end
  if not ns.CityLevels[lvl] then return nil end
  local zs, zp = N.CityFloor(lvl, d.x, d.y), N.CityHeight(lvl, px, py)
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

-- Offroad shortcuts go off down in an underground city (there's no way through its walls
-- but its streets), and back on after, unless the player set them while there. Kept per
-- character, so a reload or logging in there picks up where it was.
local function OffroadChanged(text)
  if UIErrorsFrame and UIErrorsFrame.AddMessage then UIErrorsFrame:AddMessage(text, 1, 0.82, 0) end
  if ns.Print then ns.Print(text) end
  if ns.Teleports and ns.Teleports.Changed then ns.Teleports.Changed() end
  N.Invalidate(true, true)
  if ns.GPS and ns.GPS.RefreshQuick then ns.GPS.RefreshQuick() end
  if ns.Options and ns.Options.Refresh then ns.Options.Refresh() end
end

-- The player set offroad themselves: while in a city, left as they set it after.
function N.OffroadSetByPlayer()
  local st = ns.CharDB and ns.CharDB().cityOffroad
  if st then st.touched = true end
end

function N.CityOffroad()
  local gps = ns.settings and ns.settings.gps
  if not gps or not ns.CharDB or not ns.CityLevels then return end
  local city = N.CityHere()
  if city == false then return end -- (loading: wait until the game says where we are)
  -- (up top in its ruins too: the game reports the city's map there)
  if not city then
    local map = C_Map and C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
    for id, l in pairs(ns.CityLevels) do
      if map and l.map == map then city = id end
    end
  end
  local cdb = ns.CharDB()
  local st = cdb.cityOffroad
  if city then
    local name = ns.CityLevels[city].name or "the city"
    if not st then
      cdb.cityOffroad = { was = gps.offroad and true or false, name = name }
      if gps.offroad then
        gps.offroad = false
        OffroadChanged("Offroad mode off in " .. name .. ": routes keep to its streets. It comes back on when you leave.")
      end
    elseif gps.offroad then
      st.touched = true -- the player turned it back on here: theirs from now on
    end
  elseif st then
    cdb.cityOffroad = nil
    if st.was and not st.touched and not gps.offroad then
      gps.offroad = true
      OffroadChanged("Offroad mode back on (left " .. (st.name or "the city") .. ").")
    end
  end
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

do -- (checked when the zone or subzone changes, and after loading in)
  local ok, f = pcall(CreateFrame, "Frame")
  if ok and f then
    for _, e in ipairs({ "ZONE_CHANGED", "ZONE_CHANGED_INDOORS", "ZONE_CHANGED_NEW_AREA", "PLAYER_ENTERING_WORLD" }) do
      pcall(f.RegisterEvent, f, e)
    end
    f:SetScript("OnEvent", function(_, e)
      local wait = e == "PLAYER_ENTERING_WORLD" and 2 or 0.2
      if C_Timer then C_Timer.After(wait, N.CityOffroad) else N.CityOffroad() end
    end)
  end
end

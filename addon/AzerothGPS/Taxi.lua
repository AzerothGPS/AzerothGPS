-- Taxi: records known flight masters and learned flight durations into
-- SavedVariables. Read-only observation; never selects or takes a flight.
local _, ns = ...

local T = {}
ns.Taxi = T

local pending -- { fromNode, toNode, toName } set when a flight is chosen
local flightStart

local function KnownState(state)
  -- Enum.FlightPathState: 0 Current, 1 Reachable, 2 Unreachable
  return state == 0 or state == 1
end

local function StoreNodes(mapID, nodes, source)
  if not nodes then return 0 end
  local cdb = ns.CharDB()
  local out = {}
  for _, n in ipairs(nodes) do
    out[#out + 1] = {
      nodeID = n.nodeID,
      name = n.name,
      x = n.position and n.position.x,
      y = n.position and n.position.y,
      state = n.state,
      known = KnownState(n.state),
      slotIndex = n.slotIndex,
    }
  end
  cdb.taxiNodes[mapID] = { time = time(), source = source, nodes = out }
  if ns.Nav and ns.Nav.FlightsChanged then ns.Nav.FlightsChanged() end -- routes may fly now
  return #out
end

local function CurrentNode()
  for i = 1, NumTaxiNodes() do
    if TaxiNodeGetType(i) == "CURRENT" then return i end
  end
end

local function OnTaxiMapOpened()
  local mapID = GetTaxiMapID and GetTaxiMapID()
  if not mapID then return end
  local n = StoreNodes(mapID, C_TaxiMap.GetAllTaxiNodes(mapID), "taximap")
  ns.Print(("recorded %d flight nodes for map %d"):format(n, mapID))
end

function T.OnLogin()
  -- If the API exposes known nodes without visiting a flight master, keep
  -- a fresh copy from login. Phase 0 probe reports whether this works.
  for _, mapID in ipairs({ 1414, 1415 }) do
    pcall(function()
      StoreNodes(mapID, C_TaxiMap.GetTaxiNodesForMap(mapID), "login")
    end)
  end
end

-- Remember which node the player picked (hook only observes the call).
if TakeTaxiNode then
  hooksecurefunc("TakeTaxiNode", function(slot)
    pcall(function()
      local from = CurrentNode()
      pending = {
        from = from and TaxiNodeName(from),
        to = TaxiNodeName(slot),
      }
    end)
  end)
end

-- The flight the player is on: { from, to (flight master names, as the flight map shows
-- them), start (GetTime) }, or nil when not flying. `to` is unknown when the flight was
-- picked before this session (e.g. a /reload in the air).
local OnTaxiChanged
function T.Current()
  local on = UnitOnTaxi and UnitOnTaxi("player")
  if not on then
    if flightStart and OnTaxiChanged then pcall(OnTaxiChanged) end -- (landed: its time recorded)
    return nil
  end
  -- (taken off: the clock starts now if the control events didn't start it. This client doesn't fire
  -- them for flights, so the start was "now" at every redraw and the countdown sat at the whole flight's
  -- time, reported 2026-10-01; and no flight's time was ever learned)
  if not flightStart then flightStart = GetTime() end
  return { from = pending and pending.from, to = pending and pending.to, start = flightStart }
end

OnTaxiChanged = function()
  local onTaxi = UnitOnTaxi("player")
  if onTaxi and not flightStart then
    flightStart = GetTime()
  elseif not onTaxi and flightStart then
    local secs = GetTime() - flightStart
    flightStart = nil
    if pending and pending.from and pending.to and secs > 5 then
      local flights = ns.CharDB().flights
      local key = pending.from .. " > " .. pending.to
      local f = flights[key] or { from = pending.from, to = pending.to, seconds = 0, samples = 0 }
      f.seconds = (f.seconds * f.samples + secs) / (f.samples + 1)
      f.samples = f.samples + 1
      flights[key] = f
      ns.Print(("flight %s took %.0fs"):format(key, secs))
    end
    pending = nil
  end
end

local ev = CreateFrame("Frame")
ev:RegisterEvent("TAXIMAP_OPENED")
ev:RegisterEvent("PLAYER_CONTROL_LOST")
ev:RegisterEvent("PLAYER_CONTROL_GAINED")
ev:SetScript("OnEvent", function(_, event)
  if event == "TAXIMAP_OPENED" then
    pcall(OnTaxiMapOpened)
  else
    -- Taxi state flips around control lost/gained; check shortly after.
    C_Timer.After(0.5, function() pcall(OnTaxiChanged) end)
  end
end)

---------------------------------------------------------------------------
-- Zeppelins and boats: their timetables (Data/Transports.lua: cycle, ride1 / ride2, wait1 /
-- wait2) and when one was seen leaving a dock (the player aboard it: standing still, carried
-- away from the dock), for the next arrivals and departures at both its docks. The game
-- doesn't tell addons where a transport is; the server keeps its own time, so it's learned
-- per realm, and an old sighting (a server restart since) may be off.
---------------------------------------------------------------------------
T.DOCK_YD = 45 -- this close to a dock: waiting there (or aboard, docked)
T.RIDE_YD = 60 -- carried this far from it without walking: it left
T.CARRY_YD = 1.5 -- moved this far between checks without walking: carried
T.CYCLE_SHARPEN = 0.02 -- a second departure sharpens the cycle only this close to the data's (a server restart
-- between the two shifted the timetable, and up to 10% let it bend the cycle: the timer drifted off, 2026-10-02)
T.RIDE_LOG_MAX = 20

-- What the ride detector saw (ns.db.rideLog, the last RIDE_LOG_MAX): each departure learned, and each time the
-- player left a dock's reach without one ("rode it and the timer didn't fix itself", 2026-10-02).
function T.LogRide(text)
  if not ns.db then return end
  ns.db.rideLog = ns.db.rideLog or {}
  local log = ns.db.rideLog
  log[#log + 1] = (date and date("%m-%d %H:%M:%S ") or "") .. text
  while #log > T.RIDE_LOG_MAX do table.remove(log, 1) end
end

local function Realm() return (GetRealmName and GetRealmName()) or "?" end
local function RowKey(t) return (t[9] or "?") .. " | " .. (t[10] or "?") end

-- The sightings: { [realm] = { [row key] = { side, at (server time, seconds), cycle? } } }.
function T.Sightings()
  if not ns.db then return {} end
  ns.db.transports = ns.db.transports or {}
  local r = Realm()
  ns.db.transports[r] = ns.db.transports[r] or {}
  return ns.db.transports[r]
end

-- The dock (transport index, side 1 or 2) within DOCK_YD of (x, y) on `cont`, nearest.
function T.DockAt(cont, x, y)
  local best, bi, bs
  for i, t in ipairs(ns.Transports or {}) do
    for side = 1, 2 do
      local c, dx, dy = t[side == 1 and 1 or 4], t[side == 1 and 2 or 5], t[side == 1 and 3 or 6]
      if c == cont then
        local d = math.sqrt((dx - x) ^ 2 + (dy - y) ^ 2)
        if d <= T.DOCK_YD and (not best or d < best) then best, bi, bs = d, i, side end
      end
    end
  end
  return bi, bs
end

-- A departure seen: transport i left dock `side` at server time `at`. A second one from the
-- same dock sharpens the cycle (the server's may run a little off the data's).
function T.Departed(i, side, at)
  local t = ns.Transports and ns.Transports[i]
  if not t then return end
  local seen = T.Sightings()
  local key = RowKey(t)
  local old = seen[key]
  local cycle = old and old.cycle
  if old and old.side == side and t.cycle then
    local n = math.floor((at - old.at) / t.cycle + 0.5)
    if n >= 1 and n <= 40 then
      local c = (at - old.at) / n
      if math.abs(c - t.cycle) < t.cycle * T.CYCLE_SHARPEN then cycle = c end
    end
  end
  seen[key] = { side = side, at = at, cycle = cycle }
  T.LogRide(string.format("departed %s side %d at %.0f (was %s; cycle %s)", key, side, at,
    old and tostring(old.at) or "unknown", cycle and string.format("%.1f", cycle) or "data's"))
end

-- Called every half second: near a dock, then carried away from it (not walking): it left.
local near -- { i, side, x, y, since }
local last -- { x, y, cont }
local carried -- (server time the carrying began)
local streak, streakAt = 0, nil -- (checks in a row carried: one alone may be the last step walked)
-- Riding a boat, a zeppelin or the tram right now, anywhere on the way (not only by a dock): not
-- walking, and carried CARRY_YD and more between checks, two in a row (T.Riding). The route isn't
-- worked out again meanwhile (Nav.Route), as on a flight: at a ride's speed every check was off it.
local rideStreak = 0
function T.Riding() return rideStreak >= 2 end
function T.TransportTick(now, serverNow, px, py, cont, speed)
  if not px then
    last = nil
    rideStreak = 0
    return
  end
  local walking = speed == nil or speed > 0.1
  local carriedNow = not walking and last and last.cont == cont
    and math.sqrt((px - last.x) ^ 2 + (py - last.y) ^ 2) >= T.CARRY_YD
  rideStreak = carriedNow and rideStreak + 1 or 0
  local i, side = T.DockAt(cont, px, py)
  -- (out of a zeppelin's or boat's reach with no departure seen: what the detector saw, for the log)
  if near and not i and not near.left and not carried and near.cont == cont then -- (carried: it departs below)
    local t = ns.Transports[near.i]
    local d = near.x and math.sqrt((px - near.x) ^ 2 + (py - near.y) ^ 2) or 0
    if d >= T.RIDE_YD and t and (t[8] == "zeppelin" or t[8] == "boat") then
      near.left = true
      T.LogRide(string.format("left %s side %d, no departure seen (speed %s, carried %s, streak %d)", RowKey(t),
        near.side, tostring(speed), tostring(carried), streak))
    end
  end
  if i then
    near = { i = i, side = side, since = near and near.i == i and near.side == side and near.since or now, cont = cont }
    local t = ns.Transports[i]
    near.x, near.y = t[side == 1 and 2 or 5], t[side == 1 and 3 or 6]
  end
  local moved = last and last.cont == cont and math.sqrt((px - last.x) ^ 2 + (py - last.y) ^ 2) or 0
  if near and not walking and moved >= T.CARRY_YD then
    streak = streak + 1
    if streak == 1 then streakAt = serverNow end
    if streak >= 2 then carried = carried or streakAt end
  else
    streak = 0
    if walking then carried = nil end
  end
  if near and near.cont == cont and carried then
    local d = math.sqrt((px - near.x) ^ 2 + (py - near.y) ^ 2)
    if d >= T.RIDE_YD then
      T.Departed(near.i, near.side, carried)
      near, carried = nil, nil
    end
  end
  if near and not i and now - near.since > 600 then near = nil end
  last = { x = px, y = py, cont = cont }
end

-- The next arrival at and departure from dock `side` of transport i: seconds from `serverNow`
-- (arrival, departure), and how long ago it was learned; nil when never seen.
function T.TransportTimes(i, side, serverNow)
  local t = ns.Transports and ns.Transports[i]
  local s = t and T.Sightings()[RowKey(t)]
  if not (s and t.cycle and t.ride1) then return nil end
  local P = s.cycle or t.cycle
  local ride = s.side == 1 and t.ride1 or t.ride2
  local waitOther = s.side == 1 and t.wait2 or t.wait1
  local waitHere = side == 1 and t.wait1 or t.wait2
  local dep0 = side == s.side and s.at or s.at + ride + waitOther
  local arr0 = dep0 - waitHere
  local function nextAfter(t0) return t0 + math.ceil((serverNow - t0) / P) * P - serverNow end
  return nextAfter(arr0), nextAfter(dep0), serverNow - s.at
end

---------------------------------------------------------------------------
-- Dungeon and raid entrances, learned: where the player stood (outside) just before the
-- loading screen into one. Kept account-wide (ns.db.entrances[map id] = { { cont, x, y, n } }),
-- shared with "Copy map data" (Feedback.RoadsText) for the data (WoW Forever's own dungeons
-- have none in the client or the server data).
---------------------------------------------------------------------------
T.ENTRANCE_FRESH = 120 -- seconds: the last spot outside this recent counts
T.ENTRANCE_SAME_YD = 40 -- one within this of a known one is the same way in
local outside -- { cont, x, y, at }

function T.NoteOutside(now, px, py, cont)
  if px and cont and not (ns.CityLevels and ns.CityLevels[cont]) and cont < 20000 then
    local inInstance = ns.Nav and ns.Nav.CurrentInstance and ns.Nav.CurrentInstance()
    if not inInstance then outside = { cont, px, py, at = now } end
  end
end

-- Just into a dungeon or raid (its map id): its way in is where the player last stood outside.
function T.NoteEntrance(mapID, now)
  if not (mapID and outside and ns.db) or now - outside.at > T.ENTRANCE_FRESH then return false end
  ns.db.entrances = ns.db.entrances or {}
  local list = ns.db.entrances[mapID] or {}
  ns.db.entrances[mapID] = list
  for _, e in ipairs(list) do
    if e[1] == outside[1] and math.sqrt((e[2] - outside[2]) ^ 2 + (e[3] - outside[3]) ^ 2) <= T.ENTRANCE_SAME_YD then
      e.n = (e.n or 1) + 1
      return true
    end
  end
  list[#list + 1] = { outside[1], outside[2], outside[3], n = 1 }
  return true
end

-- A dungeon with wings (Data/Instances.lua's `wings`: the Scarlet Monastery's, Dire Maul's): the wing the
-- player went in by, the way in nearest where they last stood outside (noted on entering, as T.NoteEntrance;
-- kept per character, over a /reload in there). Its map, boss route and usual way are that wing's.
function T.NoteWing(mapID, now)
  if not (mapID and outside) or now - outside.at > T.ENTRANCE_FRESH then return nil end
  local lvl = ns.Nav and ns.Nav.InstanceLevel and ns.Nav.InstanceLevel(mapID)
  local info = lvl and ns.Instances and ns.Instances[lvl]
  if not (info and info.wings) then return nil end
  local best, bd
  for _, e in ipairs(info.entrances or {}) do
    if e[7] and ns.Geo.Base(e[1]) == ns.Geo.Base(outside[1]) then
      local d = (e[2] - outside[2]) ^ 2 + (e[3] - outside[3]) ^ 2
      if not bd or d < bd then best, bd = e[7], d end
    end
  end
  local cdb = ns.CharDB and ns.CharDB()
  if cdb then cdb.enteredWing = best and { level = lvl, wing = best } or nil end
  return best
end

-- The wing of dungeon level `lvl` the player went in by (T.NoteWing), or nil.
function T.EnteredWing(lvl)
  local cdb = ns.CharDB and ns.CharDB()
  local w = cdb and cdb.enteredWing
  return w and w.level == lvl and w.wing or nil
end

do
  local function tick()
    local ok, px, py, _, cont = pcall(UnitPosition, "player")
    if not ok or (ns.IsSecret and (ns.IsSecret(px) or ns.IsSecret(py))) then return end
    local sok, speed = pcall(GetUnitSpeed, "player")
    if not sok or (ns.IsSecret and ns.IsSecret(speed)) then speed = nil end
    pcall(T.TransportTick, GetTime(), GetServerTime and GetServerTime() or time(), px, py, cont, speed)
    pcall(T.NoteOutside, GetTime(), px, py, cont)
  end
  if C_Timer and C_Timer.NewTicker then C_Timer.NewTicker(0.5, tick) end
end

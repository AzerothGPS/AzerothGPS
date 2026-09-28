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
function T.Current()
  if not (UnitOnTaxi and UnitOnTaxi("player")) then return nil end
  return { from = pending and pending.from, to = pending and pending.to, start = flightStart or GetTime() }
end

local function OnTaxiChanged()
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

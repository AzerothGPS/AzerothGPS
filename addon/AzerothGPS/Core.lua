-- AzerothGPS core: saved variables, settings, events, API probe.
local addonName, ns = ...

ns.DEFAULTS = {
  gps = {
    -- map window
    shown = true,
    size = 450, -- frame edge in UI units (asked, 2026-10-01: 450 by default)
    alpha = 1, -- whole-frame opacity
    stepsCollapsed = true, -- the map's top panel: only the whole trip's times (the -/+ button)
    stepsAll = false, -- the map's top panel: all the steps, not just the next few (its + button)
    fadeMoving = true, -- fade the map while moving (not the route, stops or player arrow)
    movingAlpha = 1, -- ... to this opacity
    locked = false, -- the map; unlocked: drag the window frame's title bar (or the Move tab) to move it
    windowFrame = true, -- the game-style window frame around the map (title bar, logo, close)
    arrowLocked = true, -- the direction arrow; unlocked: drag to move, corner to resize
    point = { "BOTTOM", "UIParent", "BOTTOM", 495, 191 },
    hz = 20, -- redraws per second (at most; skipped when nothing changed; Options > Performance)
    -- performance (Options > Performance; its "Use Low-End Settings" sets these lighter)
    arrowHz = 0, -- the direction arrow turned this many times a second (0: every frame)
    rerouteSeconds = 2, -- a route the player left is worked out again at most this often
    gentleBackground = false, -- background searches in smaller slices of each frame (GPS.PumpBudget)
    -- map
    style = "minimap", -- "minimap" (terrain tiles), "zone" (world map art) or "nospoiler" (explored parts only)
    rotate = false, -- heading-up; false = north-up
    zoom = 524.288, -- yards from center to edge
    interiors = true, -- switch to building interior maps indoors (cities, inns, caves)
    terrainZoomOut = true, -- terrain view: right-click opens the world map to pick a place
    showRoads = false, -- draw the road network the routes use (drawn roads too)
    -- show on the map
    poiTaxi = true, -- flight masters
    showParty = true, -- party and raid members on the map (GPS.DrawParty)
    poiPoi = true, -- the world map's points of interest
    poiLabels = true, -- place names (when zoomed in)
    layerQuests = true, -- your quests' objectives and turn-ins
    layerQuestAreas = true, -- ... and their objective areas, outlined
    layerHerbs = true, -- herbs you've gathered, hovered on the minimap, right-clicked or imported
    layerOre = true, -- ... and ore
    layerCity = true, -- city locations guards pointed out (trainers, bank, ...)
    layerInstances = true, -- dungeon and raid entrances (click one for its map, with its bosses)
    layerCaves = true, -- cave and mine entrances (double-click one for a stop)
    approachZoom = true, -- zoom in near the next stop, back out once there
    -- routing
    navCloseClears = true, -- the X on the map's route panel cancels the route (else just closes the panel)
    reopenFollow = false, -- hidden while looking around the map (a route set): reopens on the player
    questing = true, -- a stop in a quest area is done when the quest's objectives are
    questZoneOnly = false, -- the quest route: only the quests in the zone you're in
    avoidHighZones = true, -- routes keep out of zones too high for the character (red on the map), if there's a way round
    dungeonRoute = true, -- entering a dungeon or raid starts its boss route (other routes held off while on)
    useHearthstone = true, -- start a route with the hearthstone (or Astral Recall) when faster
    useTeleports = true, -- ... or a class teleport (mage teleports, Teleport: Moonglade)
    useFlights = true, -- take flights between the flight masters this character knows
    fastestOrder = true, -- routes with several stops: visit them in the fastest order
    stopsAhead = 3, -- stops routed and drawn on the map at a time (1 to Nav.PLAN_AHEAD); the next come in as they're reached
    avoidHostile = true, -- routes keep away from the other faction's guards (their towns)
    cityKeepOrder = true, -- ... except stops down in a city: in the order placed
    acceptWay = true, -- TomTom /way commands (typed or pasted in chat) add route stops
    acceptMapPins = true, -- a map pin link ("[Map Pin Location]") clicked in chat adds a stop there
    acceptShared = true, -- routes other players send (asked before use)
    -- directions
    arrow = true, -- turn-by-turn direction arrow window (TomTom style)
    arrowPoint = { "CENTER", "UIParent", "CENTER", 15, 267 },
    arrowSize = { 289, 97 }, -- taller: the later stops are listed too
    arrowBg = 0, -- background opacity of the arrow window
    -- click-through: the map and the arrow ignore the mouse (clicks go to the game world)
    clickThroughMoving = false, -- while moving
    clickThroughCombat = false, -- in combat (off by default: asked, 2026-10-01)
    -- in combat
    combatHideMap = false, -- hide the map (nothing to click by mistake; off by default, asked 2026-10-01)
    combatHideArrow = false, -- hide the direction arrow
    combatAlpha = 1, -- map opacity in combat (unset: the map's usual opacity)
    arrowCombatAlpha = 1, -- arrow opacity in combat
    -- help improve AzerothGPS (opt-in: off unless the player turns them on)
    devTools = false, -- the road tools on the map's buttons (Draw a road, Erase a road)
    wallTools = false, -- the wall tools on the map's buttons
    pinning = true, -- Shift + left-click on the map: "Create Pin" (Pins.lua)
    showCustomPins = true, -- the pins on the map (the player's and the shared ones)
    showWalls = false, -- draw the walls routes don't walk through (blood red)
    -- what "Copy Map Data..." puts in the text (Feedback.KINDS)
    copyRoads = true, copyWalls = true, copyRoutes = true, copyPins = true,
  },
  minimap = { hide = false, angle = 128 }, -- minimap button (degrees around the minimap)
  combatProbe = false,
}

local function Print(...)
  if DEFAULT_CHAT_FRAME then
    DEFAULT_CHAT_FRAME:AddMessage("|cff33ccffAzerothGPS|r " .. strjoin(" ", tostringall(...)))
  end
end
ns.Print = Print

-- True if v is one of Midnight's "secret" values (unusable in math).
local function IsSecret(v)
  return issecretvalue ~= nil and v ~= nil and issecretvalue(v) or false
end
ns.IsSecret = IsSecret

-- Key binding (Bindings.xml): shows or hides the map. Names for the game's Key Bindings.
BINDING_HEADER_AZEROTHGPS = "AzerothGPS"
BINDING_NAME_AZEROTHGPS_TOGGLE = "Show/Hide AzerothGPS"
function AzerothGPS_ToggleMap()
  if not ns.settings then return end
  ns.settings.gps.shown = not ns.settings.gps.shown
  if ns.Options and ns.Options.Apply then ns.Options.Apply() end
end

-- Timing of the addon's work (redraw and its parts, routing, layers), for /agps debug perf:
-- ns.perf[name] = { last, max, n, slow, total } in milliseconds, since ns.perfSince.
-- Names with ": " are parts of the one before (e.g. "redraw: tiles" is inside "redraw").
ns.perf = {}
ns.perfSince = GetTime and GetTime() or 0
function ns.PerfStart() return debugprofilestop and debugprofilestop() end
-- The timings that don't overlap (the others are parts of these): their sum is all the addon's work
-- (Options > Performance shows it as a share of the time).
ns.PERF_TOP = { "redraw", "arrow window", "every frame: fade, tooltip", "terrain search", "quest area tracing" }
function ns.PerfTotal()
  local sum = 0
  for _, k in ipairs(ns.PERF_TOP) do
    local p = ns.perf[k]
    if p then sum = sum + p.total end
  end
  return sum
end
function ns.PerfEnd(name, t0)
  if not t0 then return end
  local ms = debugprofilestop() - t0
  local p = ns.perf[name]
  if not p then
    p = { last = 0, max = 0, n = 0, slow = 0, total = 0 }
    ns.perf[name] = p
  end
  p.last, p.max, p.n, p.total = ms, math.max(p.max, ms), p.n + 1, p.total + ms
  if ms > 16 then p.slow = p.slow + 1 end -- longer than a 60 fps frame
end
-- The report since the last one (then starts over): chat lines, and a snapshot saved in
-- AzerothGPSDB.perf (written to disk on /reload or logout; read with `agps perf`).
function ns.PerfReport()
  local now = GetTime()
  local span = math.max(0.001, now - (ns.perfSince or now))
  local names = {}
  for k in pairs(ns.perf) do names[#names + 1] = k end
  table.sort(names)
  local out, rows = {}, {}
  out[1] = string.format("over %.0f s (10 ms/s = 1%% of a CPU core):", span)
  for _, k in ipairs(names) do
    local p = ns.perf[k]
    out[#out + 1] = string.format("%s: %.2f ms/s, avg %.2f ms, max %.1f ms, %.1f runs/s, %d over 16 ms",
      k, p.total / span, p.total / p.n, p.max, p.n / span, p.slow)
    rows[#rows + 1] = { name = k, total = p.total, n = p.n, max = p.max, slow = p.slow }
  end
  if ns.db and #rows > 0 then
    ns.db.perf = ns.db.perf or {}
    local snaps = ns.db.perf
    local st = ns.settings and ns.settings.gps or {}
    snaps[#snaps + 1] = {
      time = time(), span = span, rows = rows, fps = GetFramerate and GetFramerate() or 0,
      version = C_AddOns and C_AddOns.GetAddOnMetadata and C_AddOns.GetAddOnMetadata(addonName, "Version") or nil,
      settings = { hz = st.hz, style = st.style, rotate = st.rotate, size = st.size,
        quests = st.layerQuests, questAreas = st.layerQuestAreas, herbs = st.layerHerbs, ore = st.layerOre,
        roads = st.showRoads, fade = st.fadeMoving, stops = ns.Nav and #ns.Nav.stops or 0 },
    }
    while #snaps > 10 do table.remove(snaps, 1) end
    out[#out + 1] = "saved: /reload, then run `agps perf` on your PC"
  end
  ns.perf, ns.perfSince = {}, now
  return #rows > 0 and out or { "nothing measured yet" }
end

-- (Never pass a filter mode above "LINEAR" to SetTexture or SetAtlas: client 1.60.1.70124 asserts
-- `flags.m_filter <= GxTex_Linear` and crashes; "TRILINEAR" did, 2026-10-01. wowmock.lua refuses it.)

-- Set a texture from a file path/ID, or from a UI atlas written "atlas:<name>" (falling back
-- to `fallback` if the client doesn't know the atlas).
function ns.SetIcon(tex, icon, fallback)
  local atlas = type(icon) == "string" and icon:match("^atlas:(.+)$")
  if atlas then
    if tex.SetAtlas and C_Texture and C_Texture.GetAtlasInfo and C_Texture.GetAtlasInfo(atlas) then
      tex:SetAtlas(atlas)
      return
    end
    icon = fallback
  end
  tex:SetTexCoord(0, 1, 0, 1) -- undo a previous atlas's coordinates
  tex:SetTexture(icon)
end

-- The character's name, or nil while the game hasn't given it yet: right after logging in (a new
-- character's first login above all) UnitName says "Unknown", and everything was saved under
-- "<realm>-Unknown" (seen 2026-10-01 on the private server: flight paths and faction filed there).
local function PlayerName()
  local n = UnitName and UnitName("player")
  if not n or n == "" or n == "Unknown" or n == UNKNOWNOBJECT then return nil end
  return n
end
ns.PlayerName = PlayerName

function ns.CharKey()
  return (GetRealmName() or "?") .. "-" .. (PlayerName() or "Unknown")
end

-- This character's saved table. Until the name is known, a stand-in for this session ("<realm>-Unknown");
-- once it is, what was put there meanwhile moves into the character's own (anything it hasn't got yet).
local pendingKey
function ns.CharDB()
  local db = AzerothGPSDB
  local key = ns.CharKey()
  if PlayerName() then
    if pendingKey and pendingKey ~= key then
      local tmp = db.chars[pendingKey]
      db.chars[pendingKey] = nil
      local own = db.chars[key] or {}
      for k, v in pairs(tmp or {}) do
        if own[k] == nil or (type(v) == "table" and type(own[k]) == "table" and next(own[k]) == nil) then own[k] = v end
      end
      db.chars[key] = own
      if db.lastChar == pendingKey then db.lastChar = key end
    end
    pendingKey = nil
  elseif not pendingKey then
    pendingKey = key
    db.chars[key] = nil -- (a stand-in left by an earlier session: whose it was can't be told)
  end
  db.chars[key] = db.chars[key] or { taxiNodes = {}, flights = {} }
  return db.chars[key]
end

-- Copy missing defaults into t (recursing into sub-tables).
local function Merge(t, defaults)
  for k, v in pairs(defaults) do
    if t[k] == nil then
      t[k] = type(v) == "table" and CopyTable(v) or v
    elseif type(v) == "table" and type(t[k]) == "table" and k ~= "point" and k ~= "arrowPoint" and k ~= "arrowSize" then
      Merge(t[k], v)
    end
  end
end

local function InitDB()
  AzerothGPSDB = AzerothGPSDB or {}
  local db = AzerothGPSDB
  db.version = 2
  db.settings = db.settings or {}
  -- an early build's single "hide in combat" and fixed 100% combat map opacity
  local gps = db.settings.gps
  if gps and gps.combatHide ~= nil then
    gps.combatHideMap, gps.combatHideArrow, gps.combatHide = gps.combatHide, gps.combatHide, nil
    if gps.combatAlpha == 1 then gps.combatAlpha = nil end
  end
  if gps and gps.frameAlways ~= nil then gps.frameAlways = nil end -- replaced by windowFrame
  if gps and gps.roundLogo ~= nil then gps.roundLogo = nil end -- (the round portrait option: removed, 2026-10-01)
  -- (Share drawn roads and walls, Share faster trips: removed, 2026-10-01; drawn roads are kept anyway,
  -- faster trips always, and Copy Map Data's checkboxes say what's shared)
  if gps then gps.shareRoads, gps.shareTrips = nil, nil end
  if gps then gps.layerAvailable, gps.layerLowLevel = nil, nil end -- quests to pick up: removed
  if gps and gps.hz == 30 then gps.hz = nil end -- the old default: now 20 (less CPU)
  if gps and gps.layerNodes ~= nil then -- split into Herbs and Ore
    gps.layerHerbs, gps.layerOre, gps.layerNodes = gps.layerNodes, gps.layerNodes, nil
  end
  -- (the offroad option, gone in 1.0.8: the roads are joined where they're heading instead)
  if gps then gps.offroad = nil end
  db.offroadOff108, db.offroadNote = nil, nil
  Merge(db.settings, ns.DEFAULTS)
  db.chars = db.chars or {}
  -- (stand-ins saved before the character's name was known, by older versions: whose can't be told)
  for key in pairs(db.chars) do
    if type(key) == "string" and key:find("%-Unknown$") then db.chars[key] = nil end
  end
  db.probes = db.probes or {}
  ns.db = db
  ns.settings = db.settings
end

-- Describe a value for the probe log, including secret-ness.
local function Describe(v)
  if IsSecret(v) then return "<secret>" end
  if v == nil then return "nil" end
  if type(v) == "number" then return string.format("%.6g", v) end
  return tostring(v)
end

-- API probe: prints to chat and appends to AzerothGPSDB.probes (read with `agps probes`).
-- Boss kills, for 1.0.7's instance routes: which of these events this client fires, and
-- with what (ns.db.encounterLog, the last 20; shown by /agps debug).
do
  local f = CreateFrame and CreateFrame("Frame")
  if f then
    for _, ev in ipairs({ "ENCOUNTER_START", "ENCOUNTER_END", "BOSS_KILL", "PLAYER_ENTERING_WORLD" }) do
      pcall(f.RegisterEvent, f, ev)
    end
    -- (the combat log only in a dungeon or raid: a boss's death there, for its route's stop)
    local combatLog = false
    f:SetScript("OnEvent", function(_, ev, ...)
      if not ns.db then return end
      local N = ns.Nav
      if ev == "PLAYER_ENTERING_WORLD" then
        local inside = N and N.CurrentInstance and N.CurrentInstance() ~= nil
        if inside ~= combatLog then
          combatLog = inside
          pcall(inside and f.RegisterEvent or f.UnregisterEvent, f, "COMBAT_LOG_EVENT_UNFILTERED")
        end
        -- (into a dungeon: its way in is where the player last stood outside, Taxi.NoteEntrance)
        if inside and ns.Taxi and ns.Taxi.NoteEntrance and GetInstanceInfo then
          local ok, _, _, _, _, _, _, _, mapID = pcall(GetInstanceInfo)
          if ok then
            pcall(ns.Taxi.NoteWing, mapID, GetTime()) -- (the wing gone in by: its map and boss route)
            pcall(ns.Taxi.NoteEntrance, mapID, GetTime())
          end
        end
        -- (after a /reload or logging in: the continent's roads and terrain prepared in the
        -- background now, not in the frame of the first route or the first showing of the roads)
        if C_Timer and C_Timer.After and ns.Router and ns.Router.WarmUp then
          C_Timer.After(2, function()
            local x, y, c = ns.Geo.PlayerWorld()
            if not x then return end
            pcall(ns.Router.WarmUp, c, x, y)
            local lvl = ns.Nav and ns.Nav.PlayerLevel and ns.Nav.PlayerLevel(c)
            if lvl and lvl ~= c then pcall(ns.Router.WarmUp, lvl, x, y) end
          end)
        end
        -- (in or out of a dungeon: its boss route started or ended, once the position settles)
        if ns.GPS and ns.GPS.DungeonEntered then
          if C_Timer and C_Timer.After then C_Timer.After(1.5, ns.GPS.DungeonEntered) else ns.GPS.DungeonEntered() end
        end
        return
      end
      if ev == "COMBAT_LOG_EVENT_UNFILTERED" then
        if not (CombatLogGetCurrentEventInfo and N) then return end
        local ok, _, sub, _, _, _, _, _, guid = pcall(CombatLogGetCurrentEventInfo)
        if ok and (sub == "UNIT_DIED" or sub == "PARTY_KILL") and not ns.IsSecret(guid) then
          local npc = N.NpcOf(guid)
          if npc and N.BossKilled(N.CurrentInstance(), npc) > 0 and ns.GPS and ns.GPS.Redraw then ns.GPS.Redraw() end
        end
        return
      end
      if N and N.BossKilled and (ev == "BOSS_KILL" or (ev == "ENCOUNTER_END" and select(5, ...) == 1)) then
        local id, name = ...
        if not ns.IsSecret(id) and N.BossKilled(N.CurrentInstance(), nil, id, name) > 0 and ns.GPS and ns.GPS.Redraw then ns.GPS.Redraw() end
      end
      ns.db.encounterLog = ns.db.encounterLog or {}
      local args = {}
      for i = 1, select("#", ...) do args[#args + 1] = tostring((select(i, ...))) end
      local log = ns.db.encounterLog
      log[#log + 1] = date("%H:%M:%S") .. " " .. ev .. " " .. table.concat(args, ",")
      while #log > 20 do table.remove(log, 1) end
    end)
  end
end

function ns.RunProbe(reason)
  local rec = { time = time(), reason = reason or "manual", results = {} }
  local lines = {}
  local function add(name, fn)
    local res = { pcall(fn) }
    local ok = table.remove(res, 1)
    local desc
    if not ok then
      desc = "ERROR: " .. tostring(res[1])
    else
      local parts = {}
      for i = 1, math.max(#res, 1) do parts[#parts + 1] = Describe(res[i]) end
      desc = table.concat(parts, ", ")
    end
    rec.results[#rec.results + 1] = { name = name, ok = ok, value = desc }
    lines[#lines + 1] = name .. " = " .. desc
  end

  add("GetBuildInfo", function() return GetBuildInfo() end)
  add("InCombatLockdown", function() return InCombatLockdown() end)
  local mapID
  add("C_Map.GetBestMapForUnit", function() mapID = C_Map.GetBestMapForUnit("player"); return mapID end)
  add("C_Map.GetPlayerMapPosition", function()
    local pos = C_Map.GetPlayerMapPosition(mapID, "player")
    if not pos then return nil end
    return pos:GetXY()
  end)
  add("GetPlayerFacing", function() return GetPlayerFacing() end)
  add("GetUnitSpeed", function() return GetUnitSpeed("player") end)
  add("UnitPosition", function() return UnitPosition("player") end)
  add("IsInInstance", function() return IsInInstance() end)
  -- (instances, for 1.0.7: what the game gives inside one)
  add("GetInstanceInfo", function() return GetInstanceInfo() end)
  add("map info", function()
    local i = mapID and C_Map.GetMapInfo(mapID)
    return i and i.name, i and i.mapType, i and i.parentMapID
  end)
  add("map floors", function()
    local g = mapID and C_Map.GetMapGroupID and C_Map.GetMapGroupID(mapID)
    local out = {}
    for _, m in ipairs(g and C_Map.GetMapGroupMembersInfo(g) or {}) do out[#out + 1] = m.mapID .. " " .. tostring(m.name) end
    return g, table.concat(out, "; ")
  end)
  add("map art", function() return mapID and C_Map.GetMapArtID and C_Map.GetMapArtID(mapID) end)
  add("boss events seen", function()
    local out = {}
    for _, e in ipairs(ns.db and ns.db.encounterLog or {}) do out[#out + 1] = e end
    return table.concat(out, " | ")
  end)
  add("GPS.state", function() return ns.GPS and ns.GPS.Describe() end)
  add("Layers.state", function() return ns.Layers and ns.Layers.Describe() end)
  add("Arrow.state", function() return ns.Arrow and ns.Arrow.Describe() end)
  add("Teleports.state", function() return ns.Teleports and ns.Teleports.Describe() end)
  add("Nav.plan", function() return ns.Nav and ns.Nav.DescribePlan() end)
  -- (party and raid members' positions: what the game gives an addon for them, for showing them on
  -- the map; by unit, not name: no other player's name in the saved probes)
  add("party positions", function()
    local units = {}
    if IsInRaid and IsInRaid() then
      for i = 1, 40 do units[#units + 1] = "raid" .. i end
    else
      for i = 1, 4 do units[#units + 1] = "party" .. i end
    end
    local function show(v, fmt)
      if v == nil then return "nil" end
      if ns.IsSecret and ns.IsSecret(v) then return "secret" end
      local ok, t = pcall(string.format, fmt, v)
      return ok and t or "?"
    end
    local out = {}
    -- (the group as the game tells it, and which member units exist: "none" while grouped would
    -- mean party1-4 aren't how this client names them)
    local exists = {}
    for _, u in ipairs({ "party1", "party2", "party3", "party4", "raid1", "raid2", "raid3" }) do
      local ok, e = pcall(UnitExists or error, u)
      if ok and e and not (ns.IsSecret and ns.IsSecret(e)) then exists[#exists + 1] = u end
    end
    local function call(f)
      local ok, v = pcall(f or error)
      return ok and tostring(v) or "error"
    end
    out[1] = string.format("group: IsInGroup=%s IsInRaid=%s members=%s units=%s", call(IsInGroup), call(IsInRaid),
      call(GetNumGroupMembers), #exists > 0 and table.concat(exists, ",") or "none")
    out[2] = string.format("class art: atlas classicon-mage=%s CLASS_ICON_TCOORDS=%s",
      tostring(C_Texture and C_Texture.GetAtlasInfo and C_Texture.GetAtlasInfo("classicon-mage") ~= nil or false),
      tostring(CLASS_ICON_TCOORDS ~= nil))
    for _, u in ipairs(units) do
      if UnitExists and UnitExists(u) and not (UnitIsUnit and UnitIsUnit(u, "player")) then
        local okp, x, y, _, inst = pcall(UnitPosition, u)
        local okm, map = pcall(C_Map.GetBestMapForUnit, u)
        local mx, my, mapErr
        if okm and map then
          local ok2, pos = pcall(C_Map.GetPlayerMapPosition, map, u)
          if ok2 and pos then mx, my = pos:GetXY() elseif not ok2 then mapErr = true end
        end
        out[#out + 1] = string.format("%s: UnitPosition=%s map=%s mapPos=%s connected=%s",
          u, okp and (show(x, "%.0f") .. "," .. show(y, "%.0f") .. " inst=" .. tostring(inst)) or "error",
          okm and show(map, "%d") or "error", mapErr and "error" or (show(mx, "%.3f") .. "," .. show(my, "%.3f")),
          tostring(UnitIsConnected and UnitIsConnected(u)))
      end
    end
    return table.concat(out, " | ")
  end)
  add("start errors", function() return table.concat(ns.initErrors or {}, " | ") end)
  add("C_Minimap", function()
    local names = {}
    for k in pairs(C_Minimap or {}) do names[#names + 1] = k end
    table.sort(names)
    return table.concat(names, " ")
  end)
  add("C_QuestLog", function()
    local names = {}
    for k in pairs(C_QuestLog or {}) do names[#names + 1] = k end
    table.sort(names)
    return table.concat(names, " ")
  end)
  -- The widget the world map draws quest objective areas with: does it exist, and can it
  -- tell which quest area a point is in (so the area's outline could be traced)?
  add("QuestPOIFrame", function()
    local ok, f = pcall(CreateFrame, "QuestPOIFrame", nil, UIParent)
    if not ok or not f then return "not available: " .. tostring(f) end
    f:Hide()
    local names = {}
    local idx = getmetatable(f) and getmetatable(f).__index
    for k in pairs(type(idx) == "table" and idx or {}) do
      if type(k) == "string" and (k:find("Quest") or k:find("Blob") or k:find("POI") or k:find("Mouse")
          or k:find("Draw") or k:find("Map") or k:find("Tooltip") or k:find("Alpha")) then
        names[#names + 1] = k
      end
    end
    table.sort(names)
    return table.concat(names, " ")
  end)
  add("C_MapExplorationInfo.GetExploredMapTextures(player map)", function()
    local list = C_MapExplorationInfo.GetExploredMapTextures(mapID) or {}
    local n = 0
    for _, e in ipairs(list) do n = n + #(e.fileDataIDs or {}) end
    return #list .. " explored areas, " .. n .. " textures"
  end)
  add("C_QuestLine", function()
    local names = {}
    for k in pairs(C_QuestLine or {}) do names[#names + 1] = k end
    table.sort(names)
    return table.concat(names, " ")
  end)
  add("GetQuestsOnMap(player map)", function()
    local out = {}
    for _, q in ipairs(C_QuestLog.GetQuestsOnMap(mapID) or {}) do
      out[#out + 1] = string.format("%s@%.3f,%.3f", tostring(q.questID), q.x or -1, q.y or -1)
    end
    return table.concat(out, " ")
  end)
  add("GetAvailableQuestLines(player map)", function()
    C_QuestLine.RequestQuestLinesForMap(mapID)
    local out = {}
    for _, q in ipairs(C_QuestLine.GetAvailableQuestLines(mapID) or {}) do
      out[#out + 1] = string.format("%s@%.3f,%.3f%s", tostring(q.questName), q.x or -1, q.y or -1, q.isHidden and "(hidden)" or "")
    end
    return table.concat(out, " ")
  end)

  local probes = ns.db.probes
  probes[#probes + 1] = rec
  while #probes > 50 do table.remove(probes, 1) end
  Print("probe (" .. rec.reason .. "):")
  for _, l in ipairs(lines) do Print("  " .. l) end
end

-- Developer hook: `AzerothGPS_Extend(fn)` runs fn(ns), the addon's own tables, for the private dev
-- addon (AzerothGPS_Dev, in the private AzerothGPS-Dev repo: never shipped). It plugs in at
-- PLAYER_LOGIN, after every part has started. Nothing in AzerothGPS calls it.
local extenders = {}
function AzerothGPS_Extend(fn)
  if type(fn) ~= "function" then return end
  if ns.started then
    local ok, err = pcall(fn, ns)
    if not ok and ns.Print then ns.Print("an extension failed: " .. tostring(err)) end
  else
    extenders[#extenders + 1] = fn
  end
end

local ev = CreateFrame("Frame")
ev:RegisterEvent("ADDON_LOADED")
ev:RegisterEvent("PLAYER_LOGIN")
ev:RegisterEvent("PLAYER_REGEN_DISABLED")
ev:RegisterEvent("PLAYER_REGEN_ENABLED")
pcall(ev.RegisterEvent, ev, "UI_SCALE_CHANGED")
pcall(ev.RegisterEvent, ev, "DISPLAY_SIZE_CHANGED")

-- A spell's name and icon, whichever API this client has (C_Spell in newer clients,
-- GetSpellInfo / GetSpellTexture in older ones).
function ns.SpellName(id)
  if C_Spell and C_Spell.GetSpellName then
    local ok, name = pcall(C_Spell.GetSpellName, id)
    if ok and name then return name end
  end
  if GetSpellInfo then
    local ok, name = pcall(GetSpellInfo, id)
    if ok then return name end
  end
  return nil
end

function ns.SpellIcon(id)
  if C_Spell and C_Spell.GetSpellTexture then
    local ok, icon = pcall(C_Spell.GetSpellTexture, id)
    if ok and icon then return icon end
  end
  if GetSpellTexture then
    local ok, icon = pcall(GetSpellTexture, id)
    if ok then return icon end
  end
  return nil
end

-- The windows' corner logo (the map's and the options' PortraitFrameTemplate), pre-scaled
-- (`agps media`, app/azerothgps/media.py): the size nearest the pixels it covers on this screen, shown
-- 1:1 (one picture shrunk by the graphics card looked soft). Fitted again when the window shows and
-- when the UI's scale or the screen changes. Without the circle (the round portrait's option was
-- removed, 2026-10-01): the logo on a plate of the title bar's brown cut to its outline
-- (Media/CornerLogo<px>.tga), the window's border without the portrait's ring
-- ("ButtonFrameTemplateNoPortrait"), in the top-left corner half above the title bar, over every part
-- of the window's frame; dragging it moves the window as the title bar does.
ns.PORTRAIT_PX = { 48, 56, 64, 72, 80, 96, 112, 128, 144, 160, 176, 192, 208, 224, 256, 288 } -- (media.py's)
ns.CORNER_LOGO_UNITS = 62 -- (the portrait's size)
ns.TITLE_MID = 11 -- the title bar's middle, under the window's top (its TitleContainer: 1 down, 20 high)
local MEDIA = "Interface\\AddOns\\AzerothGPS\\Media\\"
local windows = {} -- { chrome, portrait, move = fn(starting), plate }
-- Screen pixels per UI unit at effective scale `effScale` (a frame's GetEffectiveScale()).
function ns.PixelsPerUnit(effScale)
  local ppu = 1
  if GetPhysicalScreenSize then
    local ok, _, h = pcall(GetPhysicalScreenSize)
    if ok and h and h > 0 then ppu = h / 768 * (effScale or 1) end
  end
  return ppu
end
-- The pre-scaled size for `units` UI units at effective scale `effScale`, and the screen pixels per unit.
function ns.PortraitPx(units, effScale)
  local ppu = ns.PixelsPerUnit(effScale)
  local want, px = units * ppu, ns.PORTRAIT_PX[1]
  for _, s in ipairs(ns.PORTRAIT_PX) do
    if math.abs(s - want) < math.abs(px - want) then px = s end
  end
  return px, ppu
end
local function Show1to1(tex, file, px)
  local pot = 1
  while pot < px do pot = pot * 2 end
  tex:SetTexture(MEDIA .. file .. px)
  tex:SetTexCoord(0, px / pot, 0, px / pot)
  if tex.SetSnapToPixelGrid then tex:SetSnapToPixelGrid(true) end
end
-- The plate logo's picture and place on window `w` (its size: exactly the picture's pixels).
local function FitCorner(w)
  local px, ppu = ns.PortraitPx(ns.CORNER_LOGO_UNITS, w.chrome:GetEffectiveScale())
  Show1to1(w.plate.tex, "CornerLogo", px)
  local size = px / ppu
  w.plate:SetSize(size, size)
  w.plate:ClearAllPoints()
  w.plate:SetPoint("CENTER", w.chrome, "TOPLEFT", size * 0.42, -ns.TITLE_MID)
  return px
end
-- The highest frame level among `f` and everything under it (the window's border, title bar and close
-- button are frames of their own), but `skip`.
local function TopLevel(f, skip, best)
  best = math.max(best or 0, f:GetFrameLevel())
  for _, c in ipairs({ f:GetChildren() }) do
    if c ~= skip then best = TopLevel(c, skip, best) end
  end
  return best
end
local function Fit(w)
  if w.plate then FitCorner(w) end
end
function ns.FitPortraits()
  for _, w in ipairs(windows) do Fit(w) end
end
-- Each window's logo: the plate without the circle, the border without the portrait's ring.
function ns.ApplyLogoLook()
  for _, w in ipairs(windows) do
    local c = w.chrome
    if c.SetBorder then pcall(c.SetBorder, c, "ButtonFrameTemplateNoPortrait") end
    w.portrait:SetShown(false)
    do
      if not w.plate then
        local plate = CreateFrame("Frame", nil, c)
        plate.tex = plate:CreateTexture(nil, "ARTWORK")
        plate.tex:SetAllPoints()
        plate:EnableMouse(true)
        plate:RegisterForDrag("LeftButton")
        plate:SetScript("OnDragStart", function() if w.move then w.move(true) end end)
        plate:SetScript("OnDragStop", function() if w.move then w.move(false) end end)
        w.plate = plate
      end
      w.plate:SetFrameStrata(c:GetFrameStrata()) -- (over the title bar: above every part of the frame)
      w.plate:SetFrameLevel(math.min(9000, TopLevel(c, w.plate) + 5))
      w.plate:Show()
    end
    Fit(w)
  end
end
-- `f`'s logo (a PortraitFrameTemplate window); `move(starting)` moves the window (dragging the plate
-- logo). `file`: another picture in its round portrait, as it is. Returns its record ({ chrome,
-- portrait, move, plate }).
function ns.SetLogoPortrait(f, file, move)
  local p = f.GetPortrait and f:GetPortrait() or (f.PortraitContainer and f.PortraitContainer.portrait)
  if not p then return end
  if file then
    p:SetTexture(MEDIA .. file)
    return
  end
  local w = { chrome = f, portrait = p, move = move }
  windows[#windows + 1] = w
  if f.HookScript then f:HookScript("OnShow", function() Fit(w) end) end
  ns.ApplyLogoLook()
  return w
end

-- Popup windows (asked, 2026-10-01: every popup in the map window's art style, without its logo): the
-- client's PortraitFrameTemplate (metal border, title bar, close button) with the border that has no
-- portrait, a dark inside like the map window's title strip, the title centered; a plain dark box with a
-- border and a close button if the template isn't there. Every popup AzerothGPS makes uses it (a test
-- checks: test_every_popup_window_is_made_with_ns_window), and its companions through API.Window.
-- Dragged anywhere to move, kept on the screen, closed by its button or Escape (a plain Hide: works in
-- combat). Returns the frame: its content goes from `f.top` (negative) down; f:SetWindowTitle(text).
-- `opts`: { parent (default the screen), noTitle (no title bar or close button: a question's, ns.Ask; the
-- border without the title band), fixed (not dragged) }.
ns.WINDOW_BG = { 0.06, 0.06, 0.07, 0.97 }
ns.WINDOW_TITLE_MARGIN = 24 -- (as the map window's: GPSFrame's TITLE_MARGIN)
ns.WINDOW_PLAIN_BORDER = "SimplePanelTemplate" -- (the client's metal border without a title band)
function ns.Window(name, w, h, title, strata, opts)
  opts = opts or {}
  local f = CreateFrame("Frame", name, opts.parent or UIParent, BackdropTemplateMixin and "BackdropTemplate" or nil)
  f:SetSize(w, h)
  f:SetPoint("CENTER")
  f:SetFrameStrata(strata or "DIALOG")
  f:SetToplevel(true)
  f:SetClampedToScreen(true)
  f:EnableMouse(true)
  if not opts.fixed then
    f:SetMovable(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", function(self) self:StartMoving() end)
    f:SetScript("OnDragStop", function(self) self:StopMovingOrSizing() end)
  end
  if name and UISpecialFrames then table.insert(UISpecialFrames, name) end -- (Escape closes it)
  local c = ns.WINDOW_BG
  local bg = f:CreateTexture(nil, "BACKGROUND")
  bg:SetPoint("TOPLEFT", 3, -3)
  bg:SetPoint("BOTTOMRIGHT", -3, 3)
  bg:SetColorTexture(c[1], c[2], c[3], c[4])
  f.bg = bg
  local ok, chrome = pcall(CreateFrame, "Frame", nil, f, "PortraitFrameTemplate")
  if ok and chrome and chrome.NineSlice then
    chrome:SetAllPoints()
    chrome:SetFrameLevel(f:GetFrameLevel()) -- (under the window's own controls)
    chrome:EnableMouse(false)
    if chrome.Bg then chrome.Bg:Hide() end
    if chrome.TopTileStreaks then chrome.TopTileStreaks:Hide() end
    local function Border(layout)
      if chrome.SetBorder then return (pcall(chrome.SetBorder, chrome, layout)) end
      if NineSliceUtil and NineSliceUtil.ApplyLayoutByName then
        return (pcall(NineSliceUtil.ApplyLayoutByName, chrome.NineSlice, layout))
      end
      return false
    end
    -- (no title bar: the plain metal border, else the usual one with its title band empty)
    if not (opts.noTitle and Border(ns.WINDOW_PLAIN_BORDER)) then Border("ButtonFrameTemplateNoPortrait") end
    if chrome.PortraitContainer then chrome.PortraitContainer:Hide() end
    if chrome.portrait then chrome.portrait:Hide() end
    local tc = chrome.TitleContainer
    if tc and tc.ClearAllPoints and tc.GetPoint then -- (centered on the window, as the map window's)
      local _, _, _, _, y = tc:GetPoint(1)
      tc:ClearAllPoints()
      tc:SetPoint("TOPLEFT", chrome, "TOPLEFT", ns.WINDOW_TITLE_MARGIN, y or -1)
      tc:SetPoint("TOPRIGHT", chrome, "TOPRIGHT", -ns.WINDOW_TITLE_MARGIN, y or -1)
    end
    if chrome.CloseButton then chrome.CloseButton:SetScript("OnClick", function() f:Hide() end) end
    if opts.noTitle then
      if tc then tc:Hide() end
      if chrome.CloseButton then chrome.CloseButton:Hide() end
    end
    function f.SetWindowTitle(_, text)
      if chrome.SetTitle then chrome:SetTitle(text)
      elseif tc and tc.TitleText then tc.TitleText:SetText(text) end
    end
    f.chrome, f.top = chrome, opts.noTitle and -14 or -30
  else
    if f.SetBackdrop then
      f:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
      f:SetBackdropColor(c[1], c[2], c[3], c[4])
      f:SetBackdropBorderColor(0.3, 0.3, 0.3, 1)
    end
    local t = f:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    t:SetPoint("TOP", 0, -8)
    function f.SetWindowTitle(_, text) t:SetText(text) end
    if not opts.noTitle then
      local close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
      close:SetPoint("TOPRIGHT", 2, 2)
      close:SetScript("OnClick", function() f:Hide() end)
    end
    f.top = opts.noTitle and -12 or -28
  end
  f:SetWindowTitle(title or "")
  f:Hide()
  return f
end

-- A question with two answers, in AzerothGPS's popup without a title bar (asked, 2026-10-01): the text,
-- then `yes` and `no` buttons; onYes / onNo on the answer (onNo also when it times out, `opts.timeout`
-- seconds, or Escape hides it). One window per `name` (made the first time), shown again for the next
-- question; `opts.parent` and `opts.place(f)` put it somewhere else than the screen's middle. Returns it.
local asks = {}
function ns.Ask(name, text, yes, no, onYes, onNo, opts)
  opts = opts or {}
  local f = asks[name]
  if not f then
    f = ns.Window(opts.parent and nil or name, 300, 120, nil, opts.strata, { parent = opts.parent, noTitle = true,
      fixed = opts.parent ~= nil })
    f.text = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    f.text:SetPoint("TOPLEFT", 16, f.top - 4)
    f.text:SetPoint("TOPRIGHT", -16, f.top - 4)
    f.text:SetJustifyH("LEFT")
    local function Btn(x)
      local ok, b = pcall(CreateFrame, "Button", nil, f, "UIPanelButtonTemplate")
      if not ok then b = CreateFrame("Button", nil, f) end
      b:SetSize(110, 22)
      b:SetPoint("BOTTOM", f, "BOTTOM", x, 14)
      return b
    end
    f.yes, f.no = Btn(-60), Btn(60)
    f.yes:SetScript("OnClick", function()
      f.answered = true
      f:Hide()
      if f.onYes then f.onYes() end
    end)
    f.no:SetScript("OnClick", function()
      f.answered = true
      f:Hide()
      if f.onNo then f.onNo() end
    end)
    -- (not answered: Escape, or the time out, counts as no)
    f:SetScript("OnHide", function()
      if not f.answered and f.onNo then f.onNo() end
      f.answered = true
    end)
    f:SetScript("OnUpdate", function(self)
      if self.until_ and GetTime() > self.until_ then self:Hide() end
    end)
    asks[name] = f
  end
  f.answered = true
  f:Hide() -- (the last question, unanswered: let go without its no)
  f.answered = false
  f.onYes, f.onNo = onYes, onNo
  f.yes:SetText(yes or YES or "Yes")
  f.no:SetText(no or NO or "No")
  f.text:SetText(text)
  f:SetHeight(f.text:GetStringHeight() + 22 - f.top + 34)
  f.until_ = opts.timeout and GetTime() + opts.timeout or nil
  f:ClearAllPoints()
  if opts.place then opts.place(f) else f:SetPoint("CENTER", 0, 120) end
  if opts.level then f:SetFrameLevel(opts.level) end
  f:Show()
  f:Raise()
  return f
end

-- In combat: the map and arrow switch to their combat opacity, or hide (options).
ns.inCombat = false
local function CombatChanged(inCombat)
  ns.inCombat = inCombat
  if ns.GPS and ns.GPS.ApplySettings then pcall(ns.GPS.ApplySettings) end
  if ns.Arrow and ns.Arrow.Apply then pcall(ns.Arrow.Apply) end
end
ev:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" and arg1 == addonName then
    InitDB()
  elseif event == "PLAYER_LOGIN" then
    local meta = (C_AddOns and C_AddOns.GetAddOnMetadata) or GetAddOnMetadata
    ns.VERSION = meta and meta(addonName, "Version") or "?"
    ns.db.lastChar = ns.CharKey()
    ns.CharDB().faction = UnitFactionGroup("player") -- "Horde" / "Alliance"
    -- each part starts on its own: one failing doesn't stop the others (and says why)
    ns.initErrors = {}
    local function Start(name, fn)
      if not fn then return end
      local ok, err = pcall(fn)
      if not ok then
        ns.initErrors[#ns.initErrors + 1] = name .. ": " .. tostring(err)
        Print("|cffff6060" .. name .. " failed to start:|r " .. tostring(err))
      end
    end
    Start("flight paths", ns.Taxi and ns.Taxi.OnLogin)
    Start("route", ns.Nav and ns.Nav.Restore)
    Start("map", ns.GPS and ns.GPS.Init)
    Start("direction arrow", ns.Arrow and ns.Arrow.Init)
    Start("waypoint import", ns.Import and ns.Import.Init)
    Start("teleports", ns.Teleports and ns.Teleports.Init)
    Start("feedback", ns.Feedback and ns.Feedback.Init)
    Start("drawn roads", ns.Record and ns.Record.Prune)
    Start("pins", ns.Pins and ns.Pins.Init)
    Start("options", ns.Options and ns.Options.Init)
    if InCombatLockdown() then CombatChanged(true) end -- logged in (or reloaded) mid-fight
    ns.started = true
    for _, fn in ipairs(extenders) do Start("extension", function() fn(ns) end) end
    extenders = {}
    Print("loaded. /agps for options, /agps help for commands.")
  elseif event == "PLAYER_REGEN_DISABLED" then
    CombatChanged(true)
    if ns.settings and ns.settings.combatProbe then
      C_Timer.After(1, function()
        if InCombatLockdown() then ns.RunProbe("combat") end
      end)
    end
  elseif event == "PLAYER_REGEN_ENABLED" then
    CombatChanged(false)
  elseif event == "UI_SCALE_CHANGED" or event == "DISPLAY_SIZE_CHANGED" then
    ns.FitPortraits() -- (the portraits' pixels changed)
  end
end)

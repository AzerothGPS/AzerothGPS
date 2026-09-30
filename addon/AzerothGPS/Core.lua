-- AzerothGPS core: saved variables, settings, events, API probe.
local addonName, ns = ...

ns.DEFAULTS = {
  gps = {
    -- map window
    shown = true,
    size = 400, -- frame edge in UI units
    alpha = 1, -- whole-frame opacity
    stepsCollapsed = true, -- the map's top panel: only the whole trip's times (the -/+ button)
    stepsAll = false, -- the map's top panel: all the steps, not just the next few (its + button)
    fadeMoving = true, -- fade the map while moving (not the route, stops or player arrow)
    movingAlpha = 1, -- ... to this opacity
    locked = false, -- the map; unlocked: drag the window frame's title bar (or the Move tab) to move it
    windowFrame = true, -- the game-style window frame around the map (title bar, logo, close)
    arrowLocked = true, -- the direction arrow; unlocked: drag to move, corner to resize
    point = { "BOTTOM", "UIParent", "BOTTOM", 495, 191 },
    hz = 20, -- redraws per second (at most; skipped when nothing changed)
    -- map
    style = "minimap", -- "minimap" (terrain tiles), "zone" (world map art) or "nospoiler" (explored parts only)
    rotate = false, -- heading-up; false = north-up
    zoom = 524.288, -- yards from center to edge
    interiors = true, -- switch to building interior maps indoors (cities, inns, caves)
    terrainZoomOut = true, -- terrain view: right-click opens the world map to pick a place
    showRoads = false, -- draw the road network the routes use (drawn roads too)
    -- show on the map
    poiTaxi = true, -- flight masters
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
    avoidHostile = true, -- routes keep away from the other faction's guards (their towns)
    cityKeepOrder = true, -- ... except stops down in a city: in the order placed
    acceptWay = true, -- TomTom /way commands (typed or pasted in chat) add route stops
    acceptShared = true, -- routes other players send (asked before use)
    -- directions
    arrow = true, -- turn-by-turn direction arrow window (TomTom style)
    arrowPoint = { "CENTER", "UIParent", "CENTER", 15, 267 },
    arrowSize = { 289, 97 }, -- taller: the later stops are listed too
    arrowBg = 0, -- background opacity of the arrow window
    -- click-through: the map and the arrow ignore the mouse (clicks go to the game world)
    clickThroughMoving = false, -- while moving
    clickThroughCombat = true, -- in combat
    -- in combat
    combatHideMap = true, -- hide the map (nothing to click by mistake)
    combatHideArrow = false, -- hide the direction arrow
    combatAlpha = 0.8, -- map opacity in combat (unset: the map's usual opacity)
    arrowCombatAlpha = 1, -- arrow opacity in combat
    -- help improve AzerothGPS (opt-in: off unless the player turns them on)
    shareRoads = false, -- keep the roads the player draws or erases for sharing
    devTools = false, -- the road tools on the map's buttons (Draw a road, Erase a road)
    wallTools = false, -- the wall tools on the map's buttons
    showWalls = false, -- draw the walls routes don't walk through (blood red)
    shareTrips = false, -- keep traces of trips clearly faster than estimated
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

function ns.CharKey()
  return (GetRealmName() or "?") .. "-" .. (UnitName("player") or "?")
end

function ns.CharDB()
  local db = AzerothGPSDB
  local key = ns.CharKey()
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
          if ok then pcall(ns.Taxi.NoteEntrance, mapID, GetTime()) end
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

local ev = CreateFrame("Frame")
ev:RegisterEvent("ADDON_LOADED")
ev:RegisterEvent("PLAYER_LOGIN")
ev:RegisterEvent("PLAYER_REGEN_DISABLED")
ev:RegisterEvent("PLAYER_REGEN_ENABLED")

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

-- The AzerothGPS logo in the round portrait of a frame made from the game's
-- PortraitFrameTemplate (the map, the options window). `file`: another image in Media.
function ns.SetLogoPortrait(f, file)
  local logo = "Interface\\AddOns\\AzerothGPS\\Media\\" .. (file or "Logo")
  local p = f.GetPortrait and f:GetPortrait() or (f.PortraitContainer and f.PortraitContainer.portrait)
  if p then p:SetTexture(logo) end
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
    Start("options", ns.Options and ns.Options.Init)
    if InCombatLockdown() then CombatChanged(true) end -- logged in (or reloaded) mid-fight
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
  end
end)

-- Teleports the route may start with (option "Use hearthstone and teleports"): the
-- Hearthstone, Astral Recall, the mage's own teleports and Teleport: Moonglade, when the
-- character has them ready right now. Read-only: the addon never casts or uses anything;
-- the directions just say "Use your Hearthstone".
local _, ns = ...
local Geo = ns.Geo

local T = {}
ns.Teleports = T

T.CAST_SECONDS = 25 -- casting (10 s) plus the loading screen, roughly
local HEARTHSTONE_ITEM, RUNE_OF_TELEPORTATION = 6948, 17031
local HEARTHSTONE_SPELL, ASTRAL_RECALL = 8690, 556

-- Where each teleport lands (world yards, approximate): { spell, cont, x, y, name, needsRune }
T.SPELLS = {
  { 3567, 1, 1469.9, -4221.5, "Orgrimmar", true }, -- Teleport: Orgrimmar
  { 3563, 0, 1773.5, 61.1, "Undercity", true }, -- Teleport: Undercity
  { 3566, 1, -965.0, 283.4, "Thunder Bluff", true }, -- Teleport: Thunder Bluff
  { 3561, 0, -9003.5, 869.0, "Stormwind", true }, -- Teleport: Stormwind
  { 3562, 0, -4613.6, -915.4, "Ironforge", true }, -- Teleport: Ironforge
  { 3565, 1, 9660.8, 2513.6, "Darnassus", true }, -- Teleport: Darnassus
  { 18960, 1, 7980.0, -2501.0, "Moonglade", false }, -- Teleport: Moonglade (druid)
}

local function S() return ns.settings and ns.settings.gps end

local function Ready(start, duration)
  return start == 0 or (duration or 0) <= 1.5 or (start + duration - GetTime()) <= 0
end

-- Items: C_Item in newer clients, the old globals in older ones.
local function ItemCount(item)
  local get = (C_Item and C_Item.GetItemCount) or GetItemCount
  if not get then return 0 end
  local ok, n = pcall(get, item)
  return ok and n or 0
end

local function ItemReady(item)
  if ItemCount(item) == 0 then return false end
  local get = (C_Container and C_Container.GetItemCooldown) or (C_Item and C_Item.GetItemCooldown) or GetItemCooldown
  if not get then return true end
  local ok, start, duration = pcall(get, item)
  if ok and type(start) == "table" then return Ready(start.startTime or 0, start.duration) end
  return not ok or Ready(start or 0, duration)
end

local function SpellKnown(spell)
  if IsPlayerSpell then return IsPlayerSpell(spell) end
  return IsSpellKnown and IsSpellKnown(spell) or false
end

local function SpellReady(spell)
  local get = (C_Spell and C_Spell.GetSpellCooldown) or GetSpellCooldown
  if not get then return true end
  local ok, a, b = pcall(get, spell)
  if not ok then return true end
  if type(a) == "table" then return Ready(a.startTime or 0, a.duration) end
  return Ready(a or 0, b)
end

-- The hearthstone's destination: the spot recorded after the last hearth (exact), else
-- the town of the inn (GetBindLocation) found among the place names.
function T.Home()
  local cdb = ns.CharDB and ns.CharDB()
  local bind = GetBindLocation and GetBindLocation()
  local rec = cdb and cdb.bind
  if rec and rec.name == bind then return rec end
  if not bind or bind == "" then return nil end
  -- the inn's building (bind locations are often an inn's own name), then a place name
  -- (towns, villages), then any point of interest, then a zone or city map's middle
  local spot = ns.AreaSpots and ns.AreaSpots[bind]
  if spot then return { cont = spot[1], x = spot[2], y = spot[3], name = bind } end
  for _, kind in ipairs({ 3, 2, 1 }) do
    for cont, list in pairs(ns.Pois or {}) do
      for _, p in ipairs(list) do
        if p[1] == kind and (p[4] == bind or (kind == 1 and p[4]:find(bind, 1, true) == 1)) then
          return { cont = cont, x = p[2], y = p[3], name = bind }
        end
      end
    end
  end
  for id, m in pairs(ns.Maps or {}) do
    if m.name == bind and m.bounds and m.continent and m.continent >= 0 then
      local b = m.bounds
      return { cont = Geo.MapCont(id), x = (b[1] + b[3]) / 2, y = (b[2] + b[4]) / 2, name = bind }
    end
  end
  return nil
end

-- A teleport as a transport row (Nav's format, used from where the player stands):
-- { cont, x, y, cont2, x2, y2, seconds, what, "", to, what, use = true }.
local function Row(what, cont, px, py, dest)
  return { cont, px, py, dest.cont, dest.x, dest.y, T.CAST_SECONDS, what, "", dest.name, what, use = true }
end

local cache, cacheAt = nil, -100

-- What's ready now, from (px, py) on `cont`. Cached for a few seconds (bags and cooldowns
-- don't change often; a teleport used goes on cooldown and drops out).
function T.Available(cont, px, py)
  local st = S()
  local hearth = not st or st.useHearthstone ~= false
  local teleports = not st or st.useTeleports ~= false
  if not hearth and not teleports then return {} end
  local now = GetTime()
  if not cache or now - cacheAt > 3 then
    cacheAt = now
    cache = {}
    local home = hearth and T.Home()
    if home then
      if ItemReady(HEARTHSTONE_ITEM) then cache[#cache + 1] = { "your Hearthstone", home } end
      if SpellKnown(ASTRAL_RECALL) and SpellReady(ASTRAL_RECALL) then cache[#cache + 1] = { "Astral Recall", home } end
    end
    local rune = ItemCount(RUNE_OF_TELEPORTATION) > 0
    for _, s in ipairs(teleports and T.SPELLS or {}) do
      if SpellKnown(s[1]) and (rune or not s[6]) and SpellReady(s[1]) then
        local name = ns.SpellName(s[1]) or ("Teleport: " .. s[5])
        cache[#cache + 1] = { name, { cont = s[2], x = s[3], y = s[4], name = s[5] } }
      end
    end
  end
  local out = {}
  for _, c in ipairs(cache) do out[#out + 1] = Row(c[1], cont, px, py, c[2]) end
  return out
end

function T.Changed() cache = nil end

-- In the inn you're bound to: remember exactly where it is.
function T.LearnHome()
  local bind = GetBindLocation and GetBindLocation()
  local sub = GetSubZoneText and GetSubZoneText()
  if not bind or bind == "" or sub ~= bind then return end
  local x, y, cont = Geo.PlayerWorld()
  local cdb = ns.CharDB and ns.CharDB()
  if not x or not cdb then return end
  local b = cdb.bind
  if b and b.name == bind and b.cont == cont and (b.x - x) ^ 2 + (b.y - y) ^ 2 < 900 then return end
  cdb.bind = { cont = cont, x = x, y = y, name = bind }
  cache = nil
  if ns.Nav then ns.Nav.Invalidate(true, true) end
end

-- For /agps debug: what the addon sees.
function T.Describe()
  local home = T.Home()
  local list = {}
  local x, y, cont = Geo.PlayerWorld()
  if x then
    for _, r in ipairs(T.Available(cont, x, y)) do list[#list + 1] = r[8] .. " -> " .. r[10] end
  end
  return string.format("bind=%s home=%s hearthstones=%d ready=%s available: %s",
    tostring(GetBindLocation and GetBindLocation()), home and string.format("%s (%d, %.0f, %.0f)", home.name, home.cont, home.x, home.y) or "unknown",
    ItemCount(HEARTHSTONE_ITEM), tostring(ItemReady(HEARTHSTONE_ITEM)), #list > 0 and table.concat(list, ", ") or "none")
end

-- After a hearth: remember exactly where it lands (for the next route).
function T.Init()
  local ev = CreateFrame("Frame")
  ev:RegisterEvent("UNIT_SPELLCAST_SUCCEEDED")
  ev:RegisterEvent("BAG_UPDATE_COOLDOWN")
  ev:RegisterEvent("SPELLS_CHANGED")
  -- standing in the inn you're bound to (or binding there): that's exactly home
  ev:RegisterEvent("ZONE_CHANGED")
  ev:RegisterEvent("ZONE_CHANGED_INDOORS")
  ev:RegisterEvent("PLAYER_ENTERING_WORLD")
  ev:RegisterEvent("HEARTHSTONE_BOUND")
  ev:SetScript("OnEvent", function(_, event, unit, _, spell)
    cache = nil
    if event ~= "UNIT_SPELLCAST_SUCCEEDED" then
      C_Timer.After(1, T.LearnHome)
      return
    end
    if event == "UNIT_SPELLCAST_SUCCEEDED" and unit == "player" and (spell == HEARTHSTONE_SPELL or spell == ASTRAL_RECALL) then
      C_Timer.After(4, function()
        local x, y, cont = Geo.PlayerWorld()
        local cdb = ns.CharDB and ns.CharDB()
        if x and cdb then cdb.bind = { cont = cont, x = x, y = y, name = GetBindLocation and GetBindLocation() } end
        if ns.Nav then ns.Nav.Invalidate(true) end
      end)
    end
  end)
end

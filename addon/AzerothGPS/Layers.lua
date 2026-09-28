-- Map layers on the GPS, from what the game tells addons (display only):
--  * Quests: objectives and turn-ins of your quests (C_QuestLog.GetQuestsOnMap). Clients
--    without that API: the quest pins the world map showed when you opened it. (Quests to
--    pick up aren't shown: this client only draws them on its own minimap, where addons
--    can't read them.)
--  * Gathering nodes (like GatherMate): herbs and ore you gathered, plus nodes you hover on
--    the minimap (its tooltip names them; the cursor gives the spot). The game doesn't give
--    addons the minimap's icons themselves, so nodes are only known once seen this way.
--    Saved account-wide; shown only for professions the character has.
local _, ns = ...
local Geo = ns.Geo

local L = {}
ns.Layers = L
L.version = 0 -- bumped when there's something new to draw (the GPS redraws on change)

L.QUEST_TTL = 5 -- seconds a map's quest list is reused
L.NODE_MERGE_YD = 20 -- the same node seen again within this distance is the same node
L.MAX_MARKS = 120
-- Minimap width in yards per zoom level (index 1 = zoom 0), outdoors and indoors.
L.MINIMAP_OUTDOOR = { 1400 / 3, 400, 1000 / 3, 800 / 3, 200, 400 / 3 }
L.MINIMAP_INDOOR = { 300, 240, 180, 120, 80, 50 }

L.ICON = {
  objective = "atlas:SideInProgressQuestIcon", -- the world map's in-progress quest (circle, three dots)
  objectiveFallback = "Interface\\RaidFrame\\ReadyCheck-Waiting",
  turnin = "Interface\\GossipFrame\\ActiveQuestIcon",
  available = "Interface\\GossipFrame\\AvailableQuestIcon",
}

-- Node names (enUS) the minimap tooltip can show; anything gathered is learned as well.
L.KNOWN_NODES = {
  ore = { "Copper Vein", "Tin Vein", "Silver Vein", "Iron Deposit", "Gold Vein", "Mithril Deposit",
    "Truesilver Deposit", "Small Thorium Vein", "Rich Thorium Vein", "Dark Iron Deposit",
    "Incendicite Mineral Vein", "Lesser Bloodstone Deposit", "Indurium Mineral Vein",
    "Ooze Covered Silver Vein", "Ooze Covered Gold Vein", "Ooze Covered Truesilver Deposit",
    "Ooze Covered Mithril Deposit", "Ooze Covered Thorium Vein", "Ooze Covered Rich Thorium Vein" },
  herb = { "Peacebloom", "Silverleaf", "Earthroot", "Mageroyal", "Briarthorn", "Stranglekelp",
    "Bruiseweed", "Wild Steelbloom", "Grave Moss", "Kingsblood", "Liferoot", "Fadeleaf", "Goldthorn",
    "Khadgar's Whisker", "Wintersbite", "Firebloom", "Purple Lotus", "Arthas' Tears", "Sungrass",
    "Blindweed", "Ghost Mushroom", "Gromsblood", "Golden Sansam", "Dreamfoil", "Mountain Silversage",
    "Plaguebloom", "Icecap", "Black Lotus" },
}
local function SpellName(id) return ns.SpellName and ns.SpellName(id) end -- Core.lua
local function SpellIcon(id) return ns.SpellIcon and ns.SpellIcon(id) end
L.GATHER_SPELLS = { ore = 2575, herb = 2366 } -- Mining, Herb Gathering (apprentice)
-- every rank's gathering spell (a higher rank casts a different spell ID)
L.GATHER_IDS = {
  [2575] = "ore", [2576] = "ore", [3564] = "ore", [10248] = "ore", [29354] = "ore", [50310] = "ore",
  [2366] = "herb", [2368] = "herb", [3570] = "herb", [11993] = "herb", [28695] = "herb", [50300] = "herb",
}
L.PROFESSION = { ore = "Mining", herb = "Herbalism" } -- skill line names (enUS; localized below)

local nodeKind = {} -- node name -> "ore" / "herb"
for kind, names in pairs(L.KNOWN_NODES) do
  for _, n in ipairs(names) do nodeKind[n] = kind end
end

---------------------------------------------------------------------------
-- Coordinates
---------------------------------------------------------------------------

-- World position (continent x, y) of a normalized position on uiMap `mapID`.
function L.MapToWorld(mapID, u, v)
  local m = ns.Maps and ns.Maps[mapID]
  local b = m and m.bounds
  if not b or not u or not v then return nil end
  return b[3] - v * (b[3] - b[1]), b[4] - u * (b[4] - b[2]), Geo.MapCont(mapID)
end

-- World offset of a point `dx`, `dy` UI units right/up of the minimap center: minimap
-- `width` UI units showing `yards` yards; `facing` when the minimap turns with the player.
function L.MinimapOffset(dx, dy, width, yards, facing)
  local k = yards / width
  dx, dy = dx * k, dy * k
  local f = facing or 0
  -- forward = (cos f, sin f) in (X north, Y west); right = (sin f, -cos f)
  return dy * math.cos(f) + dx * math.sin(f), dy * math.sin(f) - dx * math.cos(f)
end

---------------------------------------------------------------------------
-- Gathering nodes
---------------------------------------------------------------------------

local function DB()
  local db = ns.db
  if not db then return nil end
  db.nodes = db.nodes or {}
  return db.nodes
end

-- Nodes: { x, y, name, kind, times seen, unconfirmed? } per continent. Imported nodes are
-- unconfirmed (drawn faded) until the player gathers there.

-- A node's kind from its name: a known node name, else a word in it ("... Vein", "herb").
function L.NodeKind(name)
  if not name then return nil end
  if nodeKind[name] then return nodeKind[name] end
  local n = name:lower()
  if n:find("vein") or n:find("deposit") or n:find("ore") or n:find("mining") then return "ore" end
  if n:find("herb") or n:find("bloom") or n:find("weed") or n:find("leaf") or n:find("root")
    or n:find("thorn") or n:find("moss") or n:find("lotus") or n:find("flower") then return "herb" end
  return nil
end

-- Add a node sighting (merging with one already known nearby). Returns true if new.
-- `imported`: from a list, not seen here yet (unconfirmed until gathered).
function L.AddNode(cont, x, y, name, kind, imported)
  local db = DB()
  if not db or not cont or not name then return false end
  kind = kind or L.NodeKind(name)
  if not kind then return false end
  if not imported then nodeKind[name] = kind end
  local list = db[cont]
  if not list then
    list = {}
    db[cont] = list
  end
  local r2 = L.NODE_MERGE_YD * L.NODE_MERGE_YD
  for _, n in ipairs(list) do
    -- the same node: the same name nearby (or an imported one of the same kind)
    if (n[3] == name or (n[6] and n[4] == kind)) and (n[1] - x) ^ 2 + (n[2] - y) ^ 2 <= r2 then
      if not imported then
        n[5] = (n[5] or 1) + 1
        if n[6] then n[3], n[6] = name, nil end -- gathered here: confirmed
      end
      return false
    end
  end
  list[#list + 1] = { math.floor(x * 10 + 0.5) / 10, math.floor(y * 10 + 0.5) / 10, name, kind, 1, imported or nil }
  return true
end

-- Import nodes from text: lines like TomTom's "/way Elwynn Forest 43.2 65.1 Copper Vein"
-- (see Import.lua). The name says what it is ("Copper Vein", "Peacebloom", or any name
-- with "ore" or "herb" in it). Returns added, skipped (already known), errors.
function L.ImportNodes(text)
  local stops, errors = ns.Import.Parse(text, C_Map and C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player"))
  local added, skipped = 0, 0
  for _, d in ipairs(stops) do
    local kind = L.NodeKind(d.name)
    if not kind then
      errors[#errors + 1] = string.format("'%s': not a herb or ore name", d.name or "?")
    elseif L.AddNode(d.cont, d.x, d.y, d.name, kind, true) then
      added = added + 1
    else
      skipped = skipped + 1
    end
  end
  return added, skipped, errors
end

-- Is world (x, y) inside the polygon { x1, y1, x2, y2, ... } (even-odd rule)?
function L.InPolygon(x, y, poly)
  local inside, n = false, #poly / 2
  local j = n
  for i = 1, n do
    local xi, yi, xj, yj = poly[2 * i - 1], poly[2 * i], poly[2 * j - 1], poly[2 * j]
    if (yi > y) ~= (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi then inside = not inside end
    j = i
  end
  return inside
end

-- The known nodes inside a drawn area on continent `cont`, of the kinds in `kinds`
-- ({ ore = true, herb = true }; nil: all): { { x, y, cont, name }, ... }.
function L.NodesInPolygon(cont, poly, kinds)
  local out = {}
  local db = DB()
  for _, n in ipairs(db and db[cont] or {}) do
    if (not kinds or kinds[n[4]]) and L.InPolygon(n[1], n[2], poly) then
      out[#out + 1] = { x = n[1], y = n[2], cont = cont, name = n[3], tex = L.NodeIcon(n[4]) }
    end
  end
  return out
end

-- Profession skill lines the character has (by kind).
local profCache, profAt = nil, -100
local function Professions()
  if profCache and GetTime() - profAt < 10 then return profCache end
  local have = {}
  profCache, profAt = have, GetTime()
  pcall(function()
    local want = {}
    for kind, spell in pairs(L.GATHER_SPELLS) do
      want[L.PROFESSION[kind]] = kind
      local sname = SpellName(spell)
      if sname then want[sname] = kind end -- e.g. localized "Mining"
    end
    for i = 1, GetNumSkillLines() do
      local name, isHeader = GetSkillLineInfo(i)
      if not isHeader and want[name] then have[want[name]] = true end
    end
  end)
  return have
end
L.Professions = Professions

-- The node kinds shown on the map (the Herbs and Ore layers), which a farming area uses too.
function L.VisibleKinds(st)
  st = st or ns.settings.gps
  return { herb = st.layerHerbs ~= false, ore = st.layerOre ~= false }
end

---------------------------------------------------------------------------
-- Quests
---------------------------------------------------------------------------

local questCache = {} -- [mapID] = { t, marks }
local seenPins = {} -- [mapID] = { { kind, u, v, name }, ... } from the world map, this session

local function QuestTitle(id)
  local Q = C_QuestLog
  if Q.GetTitleForQuestID then return Q.GetTitleForQuestID(id) end
  if Q.GetQuestInfo then return Q.GetQuestInfo(id) end
end

-- Quest marks on uiMap `mapID`: { { x, y, cont, kind, name }, ... }
local function QuestMarks(mapID, st)
  local c = questCache[mapID]
  local now = GetTime()
  if c and now - c.t < L.QUEST_TTL then return c.marks end
  local marks = {}
  local function add(u, v, kind, name, questID)
    local x, y, cont = L.MapToWorld(mapID, u, v)
    if x then marks[#marks + 1] = { x, y, cont, kind, name, questID } end
  end
  local direct = false
  local Q = C_QuestLog
  if Q and Q.GetQuestsOnMap then
    direct = true
    for _, q in ipairs(Q.GetQuestsOnMap(mapID) or {}) do
      local complete = Q.IsComplete and Q.IsComplete(q.questID)
      add(q.x, q.y, complete and "turnin" or "objective", QuestTitle(q.questID), q.questID)
    end
  end
  if not direct then
    for _, p in ipairs(seenPins[mapID] or {}) do add(p[2], p[3], p[1], p[4]) end
  end
  questCache[mapID] = { t = now, marks = marks }
  return marks
end

-- Fallback for clients without the quest APIs: remember the quest pins the world map
-- shows (read-only), per map, for this session.
local function ScrapeWorldMap()
  local wm = WorldMapFrame
  if not (wm and wm.EnumerateAllPins and wm.GetMapID) then return end
  local mapID = wm:GetMapID()
  if not mapID then return end
  local list = {}
  for pin in wm:EnumerateAllPins() do
    local tmpl = pin.pinTemplate or ""
    if tmpl:find("Quest") and pin.GetPosition then
      local u, v = pin:GetPosition()
      if u and v then
        if not tmpl:find("Offer") then -- your quests only
          list[#list + 1] = { pin.isComplete and "turnin" or "objective", u, v, pin.questID and QuestTitle(pin.questID) or nil }
        end
      end
    end
  end
  seenPins[mapID] = list
  questCache[mapID] = nil
  L.lastTemplates = L.lastTemplates or {}
  for pin in wm:EnumerateAllPins() do L.lastTemplates[pin.pinTemplate or "?"] = true end
end

---------------------------------------------------------------------------
-- Quest objective areas (the shapes the minimap and world map outline)
---------------------------------------------------------------------------
-- The game gives no outline data, but it can say whether a point on a map is inside a
-- quest's area (C_Minimap.IsInsideQuestBlob, or the world map's QuestPOIFrame widget).
-- Each area is traced once in the background: a coarse grid over the zone finds it, a
-- finer grid over its box gives the shape, marching squares turn that into an outline.
-- Cached per quest until its objectives change.

L.AREA_COARSE = 72 -- samples across the whole zone (finding the areas)
L.AREA_PAD = 2 -- coarse cells added around what was found, for the fine pass
L.AREA_STEP_YD = 5 -- fine sampling step
L.AREA_FINE_MIN, L.AREA_FINE_MAX = 40, 200 -- fine samples per side
L.AREA_SMOOTH = 2 -- rounds of corner cutting on the traced outline
L.AREA_SIMPLIFY = 0.35 -- grid cells: points closer than this to the line are dropped
L.AREA_BUDGET_MS = 2 -- tracing time per frame

-- Outline of a sampled shape: inside(i, j) for i = 0..nu-1, j = 0..nv-1 (outside the grid
-- counts as outside). Returns segments { i1, j1, i2, j2, ... } in grid units (edge midpoints).
function L.Outline(inside, nu, nv)
  local out = {}
  local function at(i, j)
    if i < 0 or j < 0 or i >= nu or j >= nv then return false end
    return inside(i, j) and true or false
  end
  for i = -1, nu - 1 do
    for j = -1, nv - 1 do
      -- corners a (i, j), b (i+1, j), c (i+1, j+1), d (i, j+1); crossing points on the
      -- edges whose two corners differ, in order ab, bc, cd, da
      local a, b, c, d = at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1)
      local pts = {}
      if a ~= b then pts[#pts + 1] = { i + 0.5, j } end
      if b ~= c then pts[#pts + 1] = { i + 1, j + 0.5 } end
      if c ~= d then pts[#pts + 1] = { i + 0.5, j + 1 } end
      if d ~= a then pts[#pts + 1] = { i, j + 0.5 } end
      for k = 1, #pts - 1, 2 do
        local p, q = pts[k], pts[k + 1]
        out[#out + 1], out[#out + 2], out[#out + 3], out[#out + 4] = p[1], p[2], q[1], q[2]
      end
    end
  end
  return out
end

-- Douglas-Peucker: the points of polyline `pts` needed to stay within `eps` of it.
local function Simplify(pts, eps)
  local n = #pts
  if n < 3 then return pts end
  local keep = { [1] = true, [n] = true }
  local stack = { { 1, n } }
  while #stack > 0 do
    local seg = table.remove(stack)
    local i0, i1 = seg[1], seg[2]
    local a, b = pts[i0], pts[i1]
    local vx, vy = b[1] - a[1], b[2] - a[2]
    local L2 = vx * vx + vy * vy
    local best, bi = -1, nil
    for i = i0 + 1, i1 - 1 do
      local p = pts[i]
      local d
      if L2 == 0 then
        d = (p[1] - a[1]) ^ 2 + (p[2] - a[2]) ^ 2
      else
        local cross = (p[1] - a[1]) * vy - (p[2] - a[2]) * vx
        d = cross * cross / L2
      end
      if d > best then best, bi = d, i end
    end
    if bi and best > eps * eps then
      keep[bi] = true
      stack[#stack + 1] = { i0, bi }
      stack[#stack + 1] = { bi, i1 }
    end
  end
  local out = {}
  for i = 1, n do if keep[i] then out[#out + 1] = pts[i] end end
  return out
end

-- Join outline segments into loops and round them off (Chaikin corner cutting, `rounds`
-- times), so a grid-traced outline doesn't look like stairs. Returns segments again.
function L.Smooth(segs, rounds)
  local function key(x, y) return string.format("%.3f,%.3f", x, y) end
  local nbr, pos = {}, {}
  for k = 1, #segs - 3, 4 do
    local a, b = key(segs[k], segs[k + 1]), key(segs[k + 2], segs[k + 3])
    pos[a], pos[b] = { segs[k], segs[k + 1] }, { segs[k + 2], segs[k + 3] }
    nbr[a] = nbr[a] or {}
    nbr[b] = nbr[b] or {}
    table.insert(nbr[a], b)
    table.insert(nbr[b], a)
  end
  local used, out = {}, {}
  local function edgeKey(a, b) return a < b and (a .. "|" .. b) or (b .. "|" .. a) end
  for start in pairs(nbr) do
    for _, first in ipairs(nbr[start]) do
      if not used[edgeKey(start, first)] then
        -- walk a loop (or an open chain) from start
        local chain, prev, cur = { pos[start] }, start, first
        used[edgeKey(start, first)] = true
        local closed = false
        while true do
          chain[#chain + 1] = pos[cur]
          if cur == start then
            closed = true
            break
          end
          local nxt
          for _, n in ipairs(nbr[cur]) do
            if not used[edgeKey(cur, n)] then nxt = n break end
          end
          if not nxt then break end
          used[edgeKey(cur, nxt)] = true
          prev, cur = cur, nxt
        end
        local pts = chain
        if closed then table.remove(pts) end -- last == first
        for _ = 1, rounds do
          local n = #pts
          if n < 3 then break end
          local nxtPts = {}
          local last = closed and n or n - 1
          if not closed then nxtPts[1] = pts[1] end
          for i = 1, last do
            local p, q = pts[i], pts[i % n + 1]
            nxtPts[#nxtPts + 1] = { 0.75 * p[1] + 0.25 * q[1], 0.75 * p[2] + 0.25 * q[2] }
            nxtPts[#nxtPts + 1] = { 0.25 * p[1] + 0.75 * q[1], 0.25 * p[2] + 0.75 * q[2] }
          end
          if not closed then nxtPts[#nxtPts + 1] = pts[n] end
          pts = nxtPts
        end
        -- drop points that barely bend the line (keeps drawing cheap)
        if closed and #pts > 3 then pts[#pts + 1] = pts[1] end -- simplify as an open chain
        pts = Simplify(pts, L.AREA_SIMPLIFY)
        if closed and #pts > 3 then table.remove(pts) end
        local n = #pts
        for i = 1, closed and n or n - 1 do
          local p, q = pts[i], pts[i % n + 1]
          out[#out + 1], out[#out + 2], out[#out + 3], out[#out + 4] = p[1], p[2], q[1], q[2]
        end
      end
    end
  end
  return out
end

local poiFrame
local function POIHit(mapID, questID, u, v)
  if not poiFrame then
    poiFrame = CreateFrame("QuestPOIFrame", nil, UIParent)
    poiFrame:SetSize(2048, 2048) -- the shape may be rasterised at the frame's size
    poiFrame:SetPoint("CENTER")
    poiFrame:SetAlpha(0)
    if poiFrame.SetFillAlpha then poiFrame:SetFillAlpha(0) end
    if poiFrame.SetBorderAlpha then poiFrame:SetBorderAlpha(0) end
    poiFrame:EnableMouse(false)
  end
  if poiFrame.map ~= mapID then
    poiFrame:SetMapID(mapID)
    poiFrame.map, poiFrame.drawn = mapID, nil
  end
  if poiFrame.drawn ~= questID then
    poiFrame:DrawNone()
    poiFrame:DrawBlob(questID, true)
    poiFrame.drawn = questID
  end
  local r = poiFrame:UpdateMouseOverTooltip(u, v)
  return r == questID or r == true
end

-- Ways to ask "is (u, v) on map `mapID` inside quest `q`'s area?"; the first that answers
-- sensibly (inside at a quest's map icon, outside far away) is used.
local HITTERS = {
  { "IsInsideQuestBlob(q, u, v)", function(m, q, u, v) return C_Minimap.IsInsideQuestBlob(q, u, v) end },
  { "IsInsideQuestBlob(q, x, y)", function(m, q, u, v)
    local x, y = L.MapToWorld(m, u, v)
    return x and C_Minimap.IsInsideQuestBlob(q, x, y)
  end },
  { "QuestPOIFrame", POIHit },
}
local hitter -- chosen HITTERS entry (retried every 30 s until one works)
L.hitterName = nil

local function Hit(h, m, q, u, v)
  local ok, r = pcall(h[2], m, q, u, v)
  if ok and ns.IsSecret and ns.IsSecret(r) then return false end -- hidden (in combat)
  return ok and r and true or false
end

-- In combat the game hides what the hit tests return (secret values): every spot would
-- read as outside, and areas traced then would come out empty. Tracing (and choosing the
-- hit test) waits until combat ends; areas already traced keep working (QuestsAt uses the
-- outlines, not the game).
local function InCombat()
  return InCombatLockdown and InCombatLockdown() or false
end

-- The game only loads quest area shapes for "the map the quest POIs are for" (what the
-- world map last showed). Tracing points it at the job's map (not while the world map is
-- open on another map) and puts it back when the queue is done: switching it is not cheap,
-- so it happens once per job, not every frame.
local poiPrev -- the map to restore, while switched
local function UsePOIMap(mapID)
  local Q = C_QuestLog
  if not (Q.SetMapForQuestPOIs and Q.GetMapForQuestPOIs) then return true end
  local cur = Q.GetMapForQuestPOIs()
  if cur == mapID then return true end
  if WorldMapFrame and WorldMapFrame:IsShown() then return false end -- don't fight the open map
  if poiPrev == nil then poiPrev = cur or false end
  Q.SetMapForQuestPOIs(mapID)
  return true
end

local function RestorePOIMap()
  if poiPrev ~= nil then
    if poiPrev and C_QuestLog.SetMapForQuestPOIs then C_QuestLog.SetMapForQuestPOIs(poiPrev) end
    poiPrev = nil
  end
end

local function WithPOIMap(mapID, fn, ...)
  UsePOIMap(mapID)
  local ok, a, b = pcall(fn, ...)
  RestorePOIMap()
  if not ok then error(a, 0) end
  return a, b
end

-- The quests in the log (not headers): { questID, ... }.
function L.LogQuests()
  local Q, out = C_QuestLog, {}
  if not (Q and Q.GetNumQuestLogEntries and Q.GetInfo) then return out end
  for i = 1, (Q.GetNumQuestLogEntries()) or 0 do
    local info = Q.GetInfo(i)
    if info and not info.isHeader and info.questID and info.questID > 0 then out[#out + 1] = info.questID end
  end
  return out
end

-- A way that answers sensibly: inside somewhere on the map for one of the quests (at its
-- icon, or anywhere on a rough grid: an icon needn't be inside its area), and outside at
-- the far corner from there. L.hitterNote says what was tried (for /agps debug).
L.HITTER_GRID = 16
L.HITTER_QUESTS = 8
-- Stops for the quest log (the quest route button): each open quest's objective spot and
-- each finished quest's turn-in, from the maps' quest pins (the map you're on first, then
-- every zone), else the quest's next waypoint. Returns stops { x, y, cont, name } and
-- { todo = n, turnin = n, missing = { title, ... } }.
function L.QuestStops()
  local Q = C_QuestLog
  local out, placed = {}, {}
  local counts = { todo = 0, turnin = 0, missing = {} }
  if not Q then return out, counts end
  local wanted = {}
  for _, id in ipairs(L.LogQuests()) do wanted[id] = true end
  local function secret(v) return ns.IsSecret and ns.IsSecret(v) end
  -- (the city levels' own maps: a pin there is down in the city)
  local cityMap = {}
  for lc, l in pairs(ns.CityLevels or {}) do if l.map then cityMap[l.map] = lc end end
  local function add(id, mapID, u, v)
    local x, y, cont = L.MapToWorld(mapID, u, v)
    if not x or secret(x) then return end
    if cityMap[mapID] and L.CityLevelAt(cont, x, y) == cityMap[mapID] then cont = cityMap[mapID] end
    local complete = Q.IsComplete and Q.IsComplete(id)
    if secret(complete) then complete = false end
    local title = QuestTitle(id) or ("Quest " .. id)
    out[#out + 1] = { x = x, y = y, cont = cont, name = complete and ("Turn in: " .. title) or title, questRoute = true }
    placed[id] = true
    if complete then counts.turnin = counts.turnin + 1 else counts.todo = counts.todo + 1 end
  end
  local maps = {}
  local here = C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
  for id, m in pairs(ns.Maps or {}) do
    if m.type == 3 and m.bounds and id ~= here then maps[#maps + 1] = id end
  end
  -- (the map you're on first, then cities' own maps: a quest in a city is found there
  -- before on the zone around it, which can't tell the city from the ground above it)
  table.sort(maps, function(a, b)
    local ca, cb = cityMap[a] and 0 or 1, cityMap[b] and 0 or 1
    if ca ~= cb then return ca < cb end
    return a < b
  end)
  if here and ns.Maps and ns.Maps[here] then table.insert(maps, 1, here) end
  if Q.GetQuestsOnMap then
    for _, mapID in ipairs(maps) do
      UsePOIMap(mapID)
      for _, q in ipairs(Q.GetQuestsOnMap(mapID) or {}) do
        if wanted[q.questID] and not placed[q.questID] and q.x and not secret(q.x) then add(q.questID, mapID, q.x, q.y) end
      end
    end
    RestorePOIMap()
  end
  for _, id in ipairs(L.LogQuests()) do
    if not placed[id] and Q.GetNextWaypoint then
      local mapID, u, v = Q.GetNextWaypoint(id)
      if mapID and u and v and ns.Maps and ns.Maps[mapID] then add(id, mapID, u, v) end
    end
    if not placed[id] then counts.missing[#counts.missing + 1] = QuestTitle(id) or ("Quest " .. id) end
  end
  return out, counts
end

local function ChooseHitter(mapID, quests)
  return WithPOIMap(mapID, function()
    local G = L.HITTER_GRID
    for _, h in ipairs(HITTERS) do
      for n, q in ipairs(quests) do
        if n > L.HITTER_QUESTS then break end
        local spots = {}
        if q.x then spots[1] = { q.x, q.y } end
        for k = 0, G * G - 1 do spots[#spots + 1] = { (k % G + 0.5) / G, (math.floor(k / G) + 0.5) / G } end
        for _, sp in ipairs(spots) do
          local u, v = sp[1], sp[2]
          if Hit(h, mapID, q.questID, u, v) then
            if not Hit(h, mapID, q.questID, u > 0.5 and 0.01 or 0.99, v > 0.5 and 0.01 or 0.99) then
              L.hitterName = h[1]
              L.hitterNote = string.format("chosen on map %d with quest %d", mapID, q.questID)
              return h
            end
            break -- inside everywhere: not a real answer, next quest
          end
        end
      end
    end
    L.hitterNote = string.format("none answered on map %d (%d quests, %s)", mapID, #quests,
      InCombat() and "in combat" or "out of combat")
  end)
end

L.AREA_VERSION = 3 -- bump to retrace cached areas after changing the tracer
-- Small areas (a circle of a few dozen yards) can fall between the coarse samples: then
-- the ground around the quest's map icon and around the player is sampled closely, and a
-- quest with no area found is looked for again around the player every AREA_EMPTY_RETRY s.
L.AREA_LOCAL_CELLS = 3 -- coarse cells each way around the icon / the player
L.AREA_LOCAL_SUB = 5 -- samples per coarse cell there
L.AREA_EMPTY_RETRY = 60

-- The player's spot on uiMap `mapID` (u, v in 0..1), or nil when not on it.
local function PlayerUV(mapID)
  local pos = C_Map.GetPlayerMapPosition and C_Map.GetPlayerMapPosition(mapID, "player")
  if not pos then return nil end
  local u, v
  if pos.GetXY then u, v = pos:GetXY() else u, v = pos.x, pos.y end
  if u and v and u > 0 and u < 1 and v > 0 and v < 1 then return u, v end
end
L.PlayerUV = PlayerUV
local areas = {} -- ["map:quest"] = { sig, cont, segs = { x1, y1, x2, y2, ... } world } (segs nil while tracing)
local jobs = {} -- queue of { key, map, quest, sig, phase, ... }

local function ObjectivesSig(questID)
  local parts = { L.AREA_VERSION }
  local list = C_QuestLog.GetQuestObjectives and C_QuestLog.GetQuestObjectives(questID)
  for _, o in ipairs(list or {}) do parts[#parts + 1] = o.finished and "1" or "0" end
  return table.concat(parts)
end

-- One step of the current tracing job, within the time budget. Returns true while busy.
local function TraceStep(deadline, now)
  local job = jobs[1]
  if not job then return false end
  local h = hitter
  local function done(segs, cont)
    -- bounding box, so areas out of view are skipped without looking at their segments
    local bb
    for k = 1, #segs - 1, 2 do
      local x, y = segs[k], segs[k + 1]
      if not bb then bb = { x, y, x, y } else
        bb[1], bb[2], bb[3], bb[4] = math.min(bb[1], x), math.min(bb[2], y), math.max(bb[3], x), math.max(bb[4], y)
      end
    end
    areas[job.key] = { sig = job.sig, cont = cont, segs = segs, bbox = bb, emptyAt = #segs == 0 and GetTime() or nil }
    L.version = L.version + 1 -- something new to draw
    table.remove(jobs, 1)
  end
  -- the fine grid: the found box plus a margin, sampled every AREA_STEP_YD
  local function Fine()
    local N = L.AREA_COARSE
    local P = L.AREA_PAD
    job.fu0, job.fu1 = math.max(0, (job.u0 - P) / N), math.min(1, (job.u1 + 1 + P) / N)
    job.fv0, job.fv1 = math.max(0, (job.v0 - P) / N), math.min(1, (job.v1 + 1 + P) / N)
    local b = ns.Maps[job.map].bounds
    local function count(span, yards)
      return math.max(L.AREA_FINE_MIN, math.min(L.AREA_FINE_MAX, math.ceil(span * yards / L.AREA_STEP_YD)))
    end
    job.mu = count(job.fu1 - job.fu0, b[4] - b[2]) -- u runs east-west (world Y)
    job.mv = count(job.fv1 - job.fv0, b[3] - b[1]) -- v runs north-south (world X)
    job.phase, job.k, job.grid = "fine", 0, {}
  end
  -- close look around the icon and the player (small areas the coarse pass stepped over)
  if job.phase == "local" then
    local N = L.AREA_COARSE
    local M = 2 * L.AREA_LOCAL_CELLS * L.AREA_LOCAL_SUB
    if not job.centers then
      job.centers = {}
      if job.px and not job.nearPlayerOnly then job.centers[#job.centers + 1] = { job.px, job.py } end
      local pu, pv = PlayerUV(job.map)
      if pu then job.centers[#job.centers + 1] = { pu, pv } end
      job.k = 0
    end
    while job.k < #job.centers * M * M do
      local c = job.centers[math.floor(job.k / (M * M)) + 1]
      local r = job.k % (M * M)
      local u = c[1] + ((r % M + 0.5) / M * 2 - 1) * L.AREA_LOCAL_CELLS / N
      local v = c[2] + ((math.floor(r / M) + 0.5) / M * 2 - 1) * L.AREA_LOCAL_CELLS / N
      job.k = job.k + 1
      if u > 0 and u < 1 and v > 0 and v < 1 and Hit(h, job.map, job.quest, u, v) then
        local ci, cj = math.floor(u * N), math.floor(v * N)
        job.u0, job.u1, job.v0, job.v1 = ci, ci, cj, cj
        Fine()
        return true
      end
      if now() > deadline then return true end
    end
    done({}, nil)
    return true
  end
  if job.phase == "coarse" then
    local N = L.AREA_COARSE
    while job.k < N * N do
      local i, j = job.k % N, math.floor(job.k / N)
      if Hit(h, job.map, job.quest, (i + 0.5) / N, (j + 0.5) / N) then
        job.u0, job.u1 = math.min(job.u0 or i, i), math.max(job.u1 or i, i)
        job.v0, job.v1 = math.min(job.v0 or j, j), math.max(job.v1 or j, j)
      end
      job.k = job.k + 1
      if now() > deadline then return true end
    end
    if not job.u0 then
      -- too small for the coarse grid? look closely around the quest's icon and the player
      if job.px and Hit(h, job.map, job.quest, job.px, job.py) then
        local ci, cj = math.floor(job.px * N), math.floor(job.py * N)
        job.u0, job.u1, job.v0, job.v1 = ci, ci, cj, cj
      else
        job.phase = "local"
        return true
      end
    end
    Fine()
    return true
  end
  local MU, MV = job.mu, job.mv
  local du, dv = (job.fu1 - job.fu0) / MU, (job.fv1 - job.fv0) / MV
  while job.k < MU * MV do
    local i, j = job.k % MU, math.floor(job.k / MU)
    job.grid[job.k] = Hit(h, job.map, job.quest, job.fu0 + (i + 0.5) * du, job.fv0 + (j + 0.5) * dv)
    job.k = job.k + 1
    if now() > deadline then return true end
  end
  local g = job.grid
  local raw = L.Smooth(L.Outline(function(i, j) return g[j * MU + i] end, MU, MV), L.AREA_SMOOTH)
  local segs, cont = {}, nil
  for k = 1, #raw, 2 do
    local x, y, c = L.MapToWorld(job.map, job.fu0 + (raw[k] + 0.5) * du, job.fv0 + (raw[k + 1] + 0.5) * dv)
    segs[k], segs[k + 1], cont = x, y, c
  end
  done(segs, cont)
  return true
end

-- Finish every queued trace now (tests, /agps debug).
function L.TraceAll()
  if not hitter then return end
  while jobs[1] do
    UsePOIMap(jobs[1].map)
    TraceStep(math.huge, function() return 0 end)
  end
  RestorePOIMap()
end

-- Called every frame (Init): trace in the background, a couple of milliseconds a frame.
local function OnUpdate()
  if not hitter or not jobs[1] then
    RestorePOIMap()
    return
  end
  if InCombat() then return end -- see InCombat
  if not UsePOIMap(jobs[1].map) then return end -- wait until the world map closes
  local now = debugprofilestop
  local t0 = now()
  local deadline = t0 + L.AREA_BUDGET_MS
  while jobs[1] and now() < deadline do
    local map = jobs[1].map
    TraceStep(deadline, now)
    if jobs[1] and jobs[1].map ~= map and not UsePOIMap(jobs[1].map) then break end
  end
  if ns.PerfEnd then ns.PerfEnd("quest area tracing", t0) end
end

-- Whether (x, y) is inside a traced outline (flat segments x1, y1, x2, y2, ...): even-odd
-- rule, counting the outline's crossings of a ray going +Y from the point.
function L.InsideOutline(segs, x, y)
  local inside = false
  for k = 1, #segs - 3, 4 do
    local x1, y1, x2, y2 = segs[k], segs[k + 1], segs[k + 2], segs[k + 3]
    if (x1 > x) ~= (x2 > x) then
      local yc = y1 + (x - x1) / (x2 - x1) * (y2 - y1)
      if yc > y then inside = not inside end
    end
  end
  return inside
end

-- Whether quest `questID`'s traced area contains (x, y) on continent `cont`.
function L.AreaContains(questID, cont, x, y)
  local a = areas["q:" .. questID]
  if not (a and a.segs and a.cont and #a.segs > 0) then return false end
  local qx, qy = Geo.ToContinent(cont, x, y, a.cont)
  return qx ~= nil and L.InsideOutline(a.segs, qx, qy)
end

-- Quests whose traced area contains (x, y) on continent `cont` (the maps' areas as
-- drawn): { questID, ... }. Uses the outlines, so it costs no game calls.
function L.QuestsAt(cont, x, y)
  local out, seen = {}, {}
  for key, a in pairs(areas) do
    if a.segs and a.cont and #a.segs > 0 then
      local qx, qy = Geo.ToContinent(cont, x, y, a.cont)
      local questID = tonumber(key:match(":(%d+)$"))
      local Q = C_QuestLog
      local active = questID and not (Q.IsComplete and Q.IsComplete(questID))
        and not (Q.IsOnQuest and not Q.IsOnQuest(questID)) -- finished or abandoned: not drawn either
      if qx and active and not seen[questID] and L.InsideOutline(a.segs, qx, qy) then
        seen[questID] = true
        out[#out + 1] = questID
      end
    end
  end
  return out
end

-- A quest's title and objectives: title, { { text, finished }, ... } (text as the quest
-- log shows it, e.g. "Vile Familiar slain: 3/8").
function L.QuestObjectives(questID)
  local out = {}
  local list = C_QuestLog.GetQuestObjectives and C_QuestLog.GetQuestObjectives(questID)
  for _, o in ipairs(list or {}) do
    if o.text and o.text ~= "" then out[#out + 1] = { text = o.text, finished = o.finished and true or false } end
  end
  return QuestTitle(questID), out
end

-- Add a quest to a tooltip like the minimap does: title, then its objectives.
function L.AddQuestToTooltip(tip, questID)
  tip:AddLine(QuestTitle(questID) or ("Quest " .. questID), 1, 0.82, 0)
  local list = C_QuestLog.GetQuestObjectives and C_QuestLog.GetQuestObjectives(questID)
  for _, o in ipairs(list or {}) do
    if o.text and o.text ~= "" then
      if o.finished then tip:AddLine("- " .. o.text, 0.5, 0.5, 0.5) else tip:AddLine("- " .. o.text, 1, 1, 1) end
    end
  end
end

L.AREA_LIST_TTL = 2 -- seconds
local areaLists = {} -- [mapID] = { t, quests } (cleared on quest log changes)

-- Quest area outlines near (cx, cy) on `cont`: flat { x1, y1, x2, y2, ... } in `cont`
-- coordinates. Starts tracing areas not known yet.
function L.Areas(cont, cx, cy, reach, mapIDs)
  local out = {}
  L.EachArea(cont, cx, cy, reach, mapIDs, function(x1, y1, x2, y2)
    out[#out + 1], out[#out + 2], out[#out + 3], out[#out + 4] = x1, y1, x2, y2
  end)
  return out
end

-- Same, calling fn(x1, y1, x2, y2) per outline segment (no tables: called every redraw).
function L.EachArea(cont, cx, cy, reach, mapIDs, fn)
  local Q = C_QuestLog
  if not (Q and Q.GetQuestsOnMap) then return end
  local seenMap = {}
  for _, mapID in ipairs(mapIDs) do
    if mapID and not seenMap[mapID] and ns.Maps and ns.Maps[mapID] then
      seenMap[mapID] = true
      -- the map's open quests and their objective state, refreshed every AREA_LIST_TTL
      local c = areaLists[mapID]
      if not c or GetTime() - c.t > L.AREA_LIST_TTL then
        c = { t = GetTime(), quests = {} }
        local listed = {}
        for _, q in ipairs(Q.GetQuestsOnMap(mapID) or {}) do
          listed[q.questID] = true
          if not (Q.IsComplete and Q.IsComplete(q.questID)) then
            q.sig = ObjectivesSig(q.questID)
            c.quests[#c.quests + 1] = q
          end
        end
        -- the log's other open quests too: an area can be on this map without the quest's
        -- icon being here (e.g. "enter the Dead Fields"); no icon, so they're looked for
        -- over the whole map, then closely around the player
        for _, id in ipairs(L.LogQuests()) do
          if not listed[id] and not (Q.IsComplete and Q.IsComplete(id)) then
            c.quests[#c.quests + 1] = { questID = id, sig = ObjectivesSig(id) }
          end
        end
        areaLists[mapID] = c
      end
      local quests = c.quests
      if not hitter and #quests > 0 and GetTime() - (L.hitterTried or -100) > 30 and not InCombat() then
        L.hitterTried = GetTime()
        hitter = ChooseHitter(mapID, quests)
      end
      if hitter then
        for _, q in ipairs(quests) do
          -- per quest, not per map: outlines are in world coordinates, so one traced on
          -- another map (the zone, a city) is drawn right away here too
          local key = "q:" .. q.questID
          local sig = q.sig
          local a = areas[key]
          local retry = a and a.emptyAt and not a.tracing and GetTime() - a.emptyAt > L.AREA_EMPTY_RETRY
          if retry then
            -- none found yet: look again around where the player is now (close look only)
            a.tracing = true
            jobs[#jobs + 1] = { key = key, map = mapID, quest = q.questID, sig = sig, phase = "local", k = 0,
              nearPlayerOnly = true }
          elseif not a or a.sig ~= sig then
            if not (a and a.tracing) then
              -- re-traced in the background: the old outline stays drawn until then (all of it,
              -- its bounding box too, or it wouldn't be drawn at all)
              areas[key] = { sig = sig, tracing = true, segs = a and a.segs, cont = a and a.cont, bbox = a and a.bbox }
              jobs[#jobs + 1] = { key = key, map = mapID, quest = q.questID, sig = sig, phase = "coarse", k = 0,
                px = q.x, py = q.y }
            end
          end
          a = areas[key]
          local segs, bb = a and a.segs, a and a.bbox
          if segs and a.cont and bb then
            if a.cont == cont then
              -- the usual case: no conversion; skip the whole area when it's out of view
              if bb[3] >= cx - reach and bb[1] <= cx + reach and bb[4] >= cy - reach and bb[2] <= cy + reach then
                for k = 1, #segs - 3, 4 do
                  local x1, y1 = segs[k], segs[k + 1]
                  if math.abs(x1 - cx) <= reach and math.abs(y1 - cy) <= reach then
                    fn(x1, y1, segs[k + 2], segs[k + 3])
                  end
                end
              end
            else
              for k = 1, #segs - 3, 4 do
                local x1, y1 = Geo.ToContinent(a.cont, segs[k], segs[k + 1], cont)
                local x2, y2 = Geo.ToContinent(a.cont, segs[k + 2], segs[k + 3], cont)
                if x1 and x2 and math.abs(x1 - cx) <= reach and math.abs(y1 - cy) <= reach then fn(x1, y1, x2, y2) end
              end
            end
          end
        end
      end
    end
  end
end

---------------------------------------------------------------------------
-- What to draw
---------------------------------------------------------------------------

local nodeIcons = {} -- kind -> gathering spell icon

-- A node kind's icon (the gathering spell's), or nil.
function L.NodeIcon(kind)
  local icon = nodeIcons[kind]
  if icon == nil then
    icon = SpellIcon(L.GATHER_SPELLS[kind]) or false
    nodeIcons[kind] = icon
  end
  return icon or nil
end

-- Marks near (cx, cy) on continent `cont`, within `reach` yards: { { x, y, icon, name, note,
-- size, r, g, b }, ... } in `cont` coordinates. mapIDs: uiMaps to ask for quests.
-- `level`: the player's level when the view is theirs (a city's own places, down in it,
-- show only while on that city's level).
function L.Marks(cont, cx, cy, reach, mapIDs, level)
  local st = ns.settings.gps
  local out = {}
  local function near(x, y) return math.abs(x - cx) <= reach and math.abs(y - cy) <= reach end
  local function put(x, y, icon, name, note, size, r, g, b, questID, preview)
    if #out < L.MAX_MARKS and near(x, y) then
      out[#out + 1] = { x, y, icon, name, note, size, r, g, b, questID, preview }
    end
  end
  if st.layerQuests then
    local seen = {}
    for _, id in ipairs(mapIDs) do
      if id and not seen[id] then
        seen[id] = true
        for _, m in ipairs(QuestMarks(id, st)) do
          local x, y = Geo.ToContinent(m[3], m[1], m[2], cont)
          local kind = m[4]
          if x then
            if kind == "objective" and st.layerQuests then
              put(x, y, L.ICON.objective, m[5] or "Quest objective", "Quest objective", 16, nil, nil, nil, m[6])
            elseif kind == "turnin" and st.layerQuests then
              put(x, y, L.ICON.turnin, m[5] or "Quest", "Ready to turn in", 16, nil, nil, nil, m[6])
            end
          end
        end
      end
    end
  end
  -- (city locations on the terrain view only, not on the world map styles)
  if st.layerCity and not (ns.GPS and ns.GPS.IsMapStyle and ns.GPS.IsMapStyle(st.style)) then
    -- (and those down in its underground cities, saved on their levels, drawn here too)
    local saved = {}
    for lc, list in pairs(L.CityDB()) do
      if lc == cont or (lc == level and Geo.Base(lc) == cont) then
        for _, c in ipairs(list) do
          put(c[1], c[2], c[4] or L.CITY_DEFAULT_ICON, c[3], "City location (a guard pointed it out)", 16)
          saved[#saved + 1] = c
        end
      end
    end
    -- a city's other places, once a guard there has been talked to (not a stop until a
    -- guard is asked for it)
    for _, p in ipairs(L.RevealedPlaces(cont)) do
      local dup = p.cont ~= cont and p.cont ~= level -- (down in a city, the player elsewhere)
      for _, c in ipairs(saved) do
        if c[3] == p[3] or (c[1] - p[1]) ^ 2 + (c[2] - p[2]) ^ 2 <= L.CITY_SAME_YD ^ 2 then dup = true break end
      end
      if not dup then
        put(p[1], p[2], L.CityIcon(p[3]) or L.CITY_DEFAULT_ICON, p[3], "City location", 16, nil, nil, nil, nil, true)
      end
    end
  end
  local kinds = L.VisibleKinds(st)
  if kinds.herb or kinds.ore then
    local db = DB()
    for _, n in ipairs(db and db[cont] or {}) do
      if kinds[n[4]] then
        local icon = nodeIcons[n[4]]
        if icon == nil then
          icon = SpellIcon(L.GATHER_SPELLS[n[4]]) or false
          nodeIcons[n[4]] = icon
        end
        local note = n[4] == "ore" and "Mining node" or "Herb"
        if n[6] then
          put(n[1], n[2], icon or "Interface\\Icons\\INV_Misc_QuestionMark", n[3],
            note .. " (imported, not confirmed yet: gather it to confirm)", 12, 0.55, 0.55, 0.55)
        else
          put(n[1], n[2], icon or "Interface\\Icons\\INV_Misc_QuestionMark", n[3], note, 14)
        end
      end
    end
  end
  return out
end

---------------------------------------------------------------------------
-- City locations: what a guard points out when asked for directions ("Alchemy
-- Trainer", "Bank"): the game marks it on the map (a gossip point of interest). Each is
-- saved for all characters, drawn with a matching icon (layerCity), and made a stop.
---------------------------------------------------------------------------

L.CITY_DEFAULT_ICON = "Interface\\Icons\\INV_Misc_Map_01"
L.CITY_ICONS = { -- words in the name -> icon (the first that matches)
  { "alchem", "Interface\\Icons\\Trade_Alchemy" },
  { "blacksmith", "Interface\\Icons\\Trade_BlackSmithing" },
  { "cook", "Interface\\Icons\\INV_Misc_Food_15" },
  { "enchant", "Interface\\Icons\\Trade_Engraving" },
  { "engineer", "Interface\\Icons\\Trade_Engineering" },
  { "first aid", "Interface\\Icons\\Spell_Holy_SealOfSacrifice" },
  { "fish", "Interface\\Icons\\Trade_Fishing" },
  { "herbalis", "Interface\\Icons\\Trade_Herbalism" },
  { "leatherwork", "Interface\\Icons\\Trade_LeatherWorking" },
  { "mining", "Interface\\Icons\\Trade_Mining" },
  { "skinning", "Interface\\Icons\\INV_Misc_Pelt_Wolf_01" },
  { "tailor", "Interface\\Icons\\Trade_Tailoring" },
  { "bank", "Interface\\Icons\\INV_Misc_Bag_10_Blue" },
  { "auction", "Interface\\Icons\\INV_Misc_Coin_02" },
  { "mail", "Interface\\Icons\\INV_Letter_15" },
  { "inn", "Interface\\Icons\\INV_Drink_05" },
  { "flight", "Interface\\Icons\\Ability_Mount_Wyvern_01" },
  { "gryphon", "Interface\\Icons\\Ability_Mount_Wyvern_01" },
  { "wind rider", "Interface\\Icons\\Ability_Mount_Wyvern_01" },
  { "bat handler", "Interface\\Icons\\Ability_Mount_Wyvern_01" },
  { "hippogryph", "Interface\\Icons\\Ability_Mount_Wyvern_01" },
  { "stable", "Interface\\Icons\\Ability_Hunter_BeastTaming" },
  { "weapon", "Interface\\Icons\\INV_Sword_04" },
  { "battlemaster", "Interface\\Icons\\INV_Misc_Rune_07" },
  { "warrior", "Interface\\Icons\\INV_Sword_27" },
  { "paladin", "Interface\\Icons\\Spell_Holy_HolyBolt" },
  { "hunter", "Interface\\Icons\\INV_Weapon_Bow_07" },
  { "rogue", "Interface\\Icons\\INV_ThrowingKnife_04" },
  { "priest", "Interface\\Icons\\INV_Staff_30" },
  { "shaman", "Interface\\Icons\\Spell_Nature_BloodLust" },
  { "mage", "Interface\\Icons\\INV_Staff_13" },
  { "warlock", "Interface\\Icons\\Spell_Shadow_DeathCoil" },
  { "druid", "Interface\\Icons\\Ability_Druid_Maul" },
}
L.CITY_SAME_YD = 15 -- the same place again (same name, this close): updated, not added

function L.CityIcon(name)
  local n = (name or ""):lower()
  for _, e in ipairs(L.CITY_ICONS) do
    if n:find(e[1], 1, true) then return e[2] end
  end
  return L.CITY_DEFAULT_ICON
end

-- Saved city locations, for all characters: [cont] = { { x, y, name, icon }, ... }.
-- A city's places (Data/CityPlaces.lua) show once any character has talked to a guard in
-- that city (saved for the account). { {x, y, name}, ... } on `cont` (or its city levels).
local placeCache = {}
function L.RevealedPlaces(cont)
  local db = ns.db
  local out = {}
  if not (db and db.cityRevealed and ns.CityPlaces) then return out end
  for ui in pairs(db.cityRevealed) do
    local list = placeCache[ui]
    if list == nil then
      list = {}
      local c = ns.CityPlaces[ui]
      for _, p in ipairs(c or {}) do
        local x, y, pc = L.MapToWorld(ui, p[1] / 100, p[2] / 100)
        if x then
          pc = L.CityLevelAt(pc, x, y) or pc
          list[#list + 1] = { x, y, p[3], cont = pc }
        end
      end
      placeCache[ui] = list
    end
    for _, p in ipairs(list) do
      if p.cont == cont or Geo.Base(p.cont) == cont then out[#out + 1] = p end
    end
  end
  return out
end

-- The city (Data/CityPlaces.lua uiMap) the player is in: their map or one it's inside.
function L.CityHere()
  local id = C_Map and C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
  for _ = 1, 4 do
    if not id then return nil end
    if ns.CityPlaces and ns.CityPlaces[id] then return id end
    local m = ns.Maps and ns.Maps[id]
    id = m and m.parent
  end
  return nil
end

-- Talked to a guard here: this city's places show from now on.
function L.RevealCity()
  local ui = L.CityHere()
  local db = ns.db
  if not (ui and db) then return end
  db.cityRevealed = db.cityRevealed or {}
  if not db.cityRevealed[ui] then
    db.cityRevealed[ui] = true
    L.version = L.version + 1
  end
end

-- A guard's directions menu: it offers the bank, and the inn or the auction house.
function L.IsGuardMenu(options)
  local bank, other = false, false
  for _, o in ipairs(options or {}) do
    local t = (o.name or ""):lower()
    if t:find("bank", 1, true) then bank = true end
    if t:find("inn", 1, true) or t:find("auction", 1, true) then other = true end
  end
  return bank and other
end

-- The underground city level a place on `cont` is down in (on its floors), or nil. A guard
-- may mark it on the continent's map (asked up top, say), but city places are down there.
function L.CityLevelAt(cont, x, y)
  -- (any floor of its there: a trainer's booth or a counter is blocked, but down there)
  local P, N = ns.Passability, ns.Nav
  for id, l in pairs(ns.CityLevels or {}) do
    if l.base == cont and ((N and N.CityHeight and N.CityHeight(id, x, y)) or (P and P.IsOpen(id, x, y))) then return id end
  end
  return nil
end

local cityDbChecked
function L.CityDB()
  local db = ns.db
  if not db then return {} end
  db.cityPois = db.cityPois or {}
  if not cityDbChecked and ns.CityLevels then
    -- (saved on the continent before its cities had levels: moved down to theirs)
    cityDbChecked = true
    for cont, list in pairs(db.cityPois) do
      if not ns.CityLevels[cont] then
        for i = #list, 1, -1 do
          local c = list[i]
          local lvl = L.CityLevelAt(cont, c[1], c[2])
          if lvl then
            table.remove(list, i)
            db.cityPois[lvl] = db.cityPois[lvl] or {}
            table.insert(db.cityPois[lvl], c)
          end
        end
      end
    end
  end
  return db.cityPois
end

-- Save a city location (or update it: the same name close by). Returns the entry.
function L.AddCityPoi(cont, x, y, name, icon)
  local db = L.CityDB()
  db[cont] = db[cont] or {}
  for _, c in ipairs(db[cont]) do
    if c[3] == name and (c[1] - x) ^ 2 + (c[2] - y) ^ 2 <= L.CITY_SAME_YD ^ 2 then
      c[1], c[2], c[4] = x, y, icon
      return c
    end
  end
  local c = { x, y, name, icon }
  db[cont][#db[cont] + 1] = c
  L.version = L.version + 1
  return c
end

local lastGossipPoi, lastGossipAt -- "name:x:y" of the last one made a stop, and when (the event repeats)
L.GOSSIP_REPEAT_SECONDS = 3

-- A guard marked something on the map: save it, and make it a stop (again too, when asked
-- again for a place already known: `asked`, the player picked the guard's answer).
function L.OnGossipPoi(asked)
  local G = C_GossipInfo
  if not (G and G.GetPoiForUiMapID and G.GetPoiInfo and C_Map and C_Map.GetBestMapForUnit) then return end
  local mapID = C_Map.GetBestMapForUnit("player")
  local maps = { mapID }
  local info, onMap
  for _, id in ipairs(maps) do
    local poi = id and G.GetPoiForUiMapID(id)
    if poi and not (ns.IsSecret and ns.IsSecret(poi)) then
      info, onMap = G.GetPoiInfo(id, poi), id
      if info then break end
    end
  end
  if not (info and info.position and info.name) then return end
  local u, v
  if info.position.GetXY then u, v = info.position:GetXY() else u, v = info.position.x, info.position.y end
  local x, y, cont = L.MapToWorld(onMap, u, v)
  if not x then return end
  cont = L.CityLevelAt(cont, x, y) or cont
  local icon = L.CityIcon(info.name)
  L.AddCityPoi(cont, x, y, info.name, icon)
  local key = string.format("%s:%.0f:%.0f", info.name, x, y)
  local now = GetTime()
  if key == lastGossipPoi and now - (lastGossipAt or 0) < L.GOSSIP_REPEAT_SECONDS then return end
  if key == lastGossipPoi and not asked then return end -- (the same marker, not asked for again)
  lastGossipPoi, lastGossipAt = key, now
  -- as a stop (unless it's one already)
  for _, d in ipairs(ns.Nav and ns.Nav.stops or {}) do
    if d.name == info.name and d.cont == cont and (d.x - x) ^ 2 + (d.y - y) ^ 2 <= L.CITY_SAME_YD ^ 2 then return end
  end
  if ns.Import and ns.Import.AddMapPin then
    ns.Import.AddMapPin({ cont = cont, x = x, y = y, name = info.name, tex = icon })
  end
end

---------------------------------------------------------------------------
-- Events: gathering, minimap tooltips, world map
---------------------------------------------------------------------------

local pendingCast -- { guid, name, kind, x, y, cont }

-- Gathering from a spell cast on a target: by the spell (any rank, or its name matching
-- Mining / Herb Gathering), or by the target being a known node name.
function L.GatherKind(spellID, target)
  if L.GATHER_IDS[spellID] then return L.GATHER_IDS[spellID] end
  local name = spellID and SpellName(spellID)
  if name then
    for kind, id in pairs(L.GATHER_SPELLS) do
      if name == SpellName(id) then return kind end
    end
  end
  return target and nodeKind[target] or nil
end
local GatherKind = L.GatherKind

-- Whether the minimap is in its indoor (smaller) scale: each mode keeps its zoom in its own
-- CVar and the active one follows Minimap:GetZoom().
local indoorsAt, indoorsCached = -100, false
local function MinimapIndoors()
  if GetTime() - indoorsAt < 5 then return indoorsCached end
  indoorsAt = GetTime()
  local z = Minimap:GetZoom()
  if GetCVar("minimapZoom") == GetCVar("minimapInsideZoom") then
    Minimap:SetZoom(z < 2 and z + 1 or z - 1)
    indoorsCached = tonumber(GetCVar("minimapZoom")) ~= Minimap:GetZoom()
    Minimap:SetZoom(z)
  else
    indoorsCached = tonumber(GetCVar("minimapZoom")) ~= z
  end
  return indoorsCached
end

-- The minimap's tooltip names what's under the cursor: remember gathering nodes there.
-- The last thing in the world the mouse was over (not a unit), from the tooltip: its name.
local worldName, worldAt = nil, -100

function L.NoteWorldObject(name, now) worldName, worldAt = name, now end

-- Right-clicking a herb or ore without the profession: the game says "Requires Herbalism"
-- (or Mining). The node is right next to the player then: save it (account-wide) for a
-- character that has the profession. Its name comes from the tooltip just shown.
function L.OnGatherError(message, now, px, py, cont)
  if not message or not worldName or now - worldAt > 3 or not px then return false end
  local kind
  for k, prof in pairs(L.PROFESSION) do
    local local_name = SpellName(L.GATHER_SPELLS[k])
    if message:find(prof, 1, true) or (local_name and message:find(local_name, 1, true)) then kind = k end
  end
  if not kind then return false end
  local added = L.AddNode(cont, px, py, worldName, kind)
  if added and ns.Print then ns.Print(string.format("saved %s on the map for later (all your characters)", worldName)) end
  return added
end

local function OnTooltip(tip)
  if tip:GetOwner() ~= Minimap then
    -- the world: remember what's under the mouse (for OnGatherError); units don't count
    if tip.GetUnit and tip:GetUnit() then return end
    local fs = _G[tip:GetName() .. "TextLeft1"]
    local text = fs and fs:GetText()
    if text and text ~= "" then L.NoteWorldObject(strtrim(text), GetTime()) end
    return
  end
  local px, py, cont = Geo.PlayerWorld()
  if not px then return end
  local names = {}
  for i = 1, tip:NumLines() do
    local fs = _G[tip:GetName() .. "TextLeft" .. i]
    local text = fs and fs:GetText()
    if text then
      for line in text:gmatch("[^\n]+") do
        local name = line:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("|T.-|t", "")
        name = strtrim(name)
        if nodeKind[name] then names[#names + 1] = name end
      end
    end
  end
  if #names == 0 then return end
  local mx, my = Minimap:GetCenter()
  local cx, cy = GetCursorPosition()
  local sc = Minimap:GetEffectiveScale()
  local sizes = MinimapIndoors() and L.MINIMAP_INDOOR or L.MINIMAP_OUTDOOR
  local yards = sizes[Minimap:GetZoom() + 1]
  local facing = GetCVar("rotateMinimap") == "1" and Geo.Facing() or 0
  local ox, oy = L.MinimapOffset(cx / sc - mx, cy / sc - my, Minimap:GetWidth(), yards, facing)
  for _, name in ipairs(names) do L.AddNode(cont, px + ox, py + oy, name) end
end

function L.Init()
  if L.frame then return end
  local f = CreateFrame("Frame")
  L.frame = f
  f:RegisterEvent("UNIT_SPELLCAST_SENT")
  f:RegisterEvent("UNIT_SPELLCAST_SUCCEEDED")
  f:RegisterEvent("QUEST_LOG_UPDATE")
  f:RegisterEvent("QUEST_ACCEPTED")
  pcall(f.RegisterEvent, f, "DYNAMIC_GOSSIP_POI_UPDATED") -- a guard's directions
  -- Asked again for a place the guard already marked: the marker doesn't change, so no
  -- event. A pick that ends the talk (the answer: no more choices, or the window closes)
  -- checks the marker again.
  -- (only with those who have given directions: "Undercity Guardian" and the like)
  local pickedAt = -math.huge
  local guides = {} -- NPC names that marked a place
  if hooksecurefunc and C_GossipInfo then
    for _, fn in ipairs({ "SelectOption", "SelectOptionByIndex" }) do
      if C_GossipInfo[fn] then
        hooksecurefunc(C_GossipInfo, fn, function()
          local npc = UnitName("npc")
          pickedAt = npc and guides[npc] and GetTime() or -math.huge
        end)
      end
    end
  end
  pcall(f.RegisterEvent, f, "GOSSIP_SHOW")
  pcall(f.RegisterEvent, f, "GOSSIP_CLOSED")
  L.gossipPicked = function(event)
    if GetTime() - pickedAt > 2 then return end
    if event == "GOSSIP_SHOW" then
      local opts = C_GossipInfo.GetOptions and C_GossipInfo.GetOptions()
      if opts and #opts > 0 then return end -- (a list of places: not the answer yet)
    end
    pickedAt = -math.huge
    C_Timer.After(0.3, function() L.OnGossipPoi(true) end)
  end
  f:RegisterEvent("UI_ERROR_MESSAGE")
  f:SetScript("OnUpdate", OnUpdate)
  f:SetScript("OnEvent", function(_, event, unit, a, b, c)
    if event == "QUEST_LOG_UPDATE" then
      questCache = {}
      areaLists = {}
    elseif event == "DYNAMIC_GOSSIP_POI_UPDATED" then
      local npc = UnitName("npc")
      if npc then guides[npc] = true end
      L.RevealCity()
      L.OnGossipPoi()
    elseif event == "GOSSIP_SHOW" or event == "GOSSIP_CLOSED" then
      if event == "GOSSIP_SHOW" and C_GossipInfo and C_GossipInfo.GetOptions then
        local ok, opts = pcall(C_GossipInfo.GetOptions)
        if ok and L.IsGuardMenu(opts) then L.RevealCity() end
      end
      L.gossipPicked(event)
    elseif event == "QUEST_ACCEPTED" then
      -- on a quest route: it doesn't have the new quest yet
      questCache, areaLists = {}, {}
      if ns.Nav and ns.Nav.OnQuestRoute and ns.Nav.OnQuestRoute() then
        ns.Nav.questRouteStale = true -- (the arrow window shows the Sprint icon until rebuilt)
        local msg = "New quest: click the quest route button (Sprint) again to add it to your route."
        ns.Print(msg)
      end
    elseif event == "UI_ERROR_MESSAGE" then -- (errorType, message)
      local px, py, cont = Geo.PlayerWorld()
      L.OnGatherError(a, GetTime(), px, py, cont)
    elseif unit ~= "player" then
      return
    elseif event == "UNIT_SPELLCAST_SENT" then
      -- unit, target name, castGUID, spellID
      local kind = GatherKind(c, a)
      local px, py, cont = Geo.PlayerWorld()
      pendingCast = kind and px and a and a ~= "" and { guid = b, name = a, kind = kind, x = px, y = py, cont = cont } or nil
    elseif event == "UNIT_SPELLCAST_SUCCEEDED" and pendingCast and a == pendingCast.guid then
      local p = pendingCast
      pendingCast = nil
      L.AddNode(p.cont, p.x, p.y, p.name, p.kind)
    end
  end)
  GameTooltip:HookScript("OnShow", OnTooltip)
  -- moving across blips changes the tooltip's text without showing it again
  local since = 0
  GameTooltip:HookScript("OnUpdate", function(tip, dt)
    since = since + dt
    if since >= 0.25 then
      since = 0
      OnTooltip(tip)
    end
  end)
  if WorldMapFrame then
    WorldMapFrame:HookScript("OnShow", function() C_Timer.After(0.2, ScrapeWorldMap) end)
    if WorldMapFrame.OnMapChanged then
      hooksecurefunc(WorldMapFrame, "OnMapChanged", function() C_Timer.After(0.2, ScrapeWorldMap) end)
    end
  end
end

-- For /agps debug layers.
function L.Describe()
  local Q, QL = C_QuestLog, C_QuestLine
  local db = DB() or {}
  local n = 0
  for _, list in pairs(db) do n = n + #list end
  local tmpl = {}
  for t in pairs(L.lastTemplates or {}) do tmpl[#tmpl + 1] = t end
  table.sort(tmpl)
  local prof = {}
  for k in pairs(Professions()) do prof[#prof + 1] = k end
  local nAreas = 0
  for _, a in pairs(areas) do if a.segs and #a.segs > 0 then nAreas = nAreas + 1 end end
  local nEmpty, nTracing = 0, 0
  for _, a in pairs(areas) do
    if a.tracing then nTracing = nTracing + 1 elseif a.segs and #a.segs == 0 then nEmpty = nEmpty + 1 end
  end
  local job = jobs[1]
  local here = C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
  local list = here and areaLists[here]
  return string.format("areas: hit test=%s (%s, tried %s s ago) traced=%d empty=%d tracing=%d queued=%d%s"
      .. " combat=%s map=%s quests listed=%d log=%d | ",
    tostring(L.hitterName), tostring(L.hitterNote), L.hitterTried and string.format("%.0f", GetTime() - L.hitterTried) or "never",
    nAreas, nEmpty, nTracing, #jobs,
    job and string.format(" (first: quest %d map %d %s %d)", job.quest, job.map, job.phase, job.k or 0) or "",
    tostring(InCombat()), tostring(here), list and #list.quests or -1, #L.LogQuests())
    .. string.format("GetQuestsOnMap=%s GetAvailableQuestLines=%s IsQuestTrivial=%s nodes=%d professions=%s worldmap pins=%s",
    tostring(Q and Q.GetQuestsOnMap ~= nil), tostring(QL and QL.GetAvailableQuestLines ~= nil),
    tostring(Q and Q.IsQuestTrivial ~= nil), n, table.concat(prof, ","), table.concat(tmpl, ","))
end


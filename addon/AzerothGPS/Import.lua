-- Import waypoints written for TomTom ("/way Elwynn Forest 43.2 65.1 First Stop"), as
-- route stops: a window opened from the GPS's "+" button, and /way itself when TomTom
-- isn't installed. The parsing is pure Lua (unit-tested).
local _, ns = ...
local Geo = ns.Geo

local I = {}
ns.Import = I

local function Trim(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end

-- A number token ("43.2", "43.2,", ",65.1"): the number, or nil.
local function Num(tok)
  if not tok then return nil end
  tok = tok:gsub("^,", ""):gsub(",$", "")
  if not tok:match("^%-?%d+%.?%d*$") then return nil end
  return tonumber(tok)
end

-- The uiMap named `name` (any case; a unique beginning of a name also works, e.g.
-- "elwynn"). Several maps can share a name: the one with art and bounds, most detailed.
function I.FindMap(name)
  local want = Trim(name):lower()
  if want == "" then return nil end
  local exact, prefix = {}, {}
  for id, m in pairs(ns.Maps or {}) do
    if m.bounds and m.name then
      local n = m.name:lower()
      if n == want then exact[#exact + 1] = id
      elseif n:sub(1, #want) == want then prefix[#prefix + 1] = id end
    end
  end
  local function best(list)
    table.sort(list, function(a, b)
      local ma, mb = ns.Maps[a], ns.Maps[b]
      if (ma.tiles ~= nil) ~= (mb.tiles ~= nil) then return ma.tiles ~= nil end
      if (ma.type or 0) ~= (mb.type or 0) then return (ma.type or 0) > (mb.type or 0) end
      return a < b
    end)
    return list[1]
  end
  if #exact > 0 then return best(exact) end
  -- a beginning that names one place only
  local names = {}
  for _, id in ipairs(prefix) do names[ns.Maps[id].name] = true end
  local count = 0
  for _ in pairs(names) do count = count + 1 end
  if count == 1 then return best(prefix) end
  return nil
end

-- One line: { mapID, x, y (0-100), name } or nil, error message.
-- Accepts "/way [zone] x y [text]", "/way #mapID x y [text]", with or without "/way".
function I.ParseLine(line, currentMap)
  local s = Trim(line or "")
  s = s:gsub("^/[tT]?[wW][aA][yY]%s*", "")
  if s == "" then return nil end
  local toks = {}
  for t in s:gmatch("%S+") do toks[#toks + 1] = t end
  -- the coordinates: the first two numbers in a row
  local at
  for i = 1, #toks - 1 do
    if Num(toks[i]) and Num(toks[i + 1]) then
      at = i
      break
    end
  end
  if not at then return nil, "no coordinates" end
  local x, y = Num(toks[at]), Num(toks[at + 1])
  local zone = Trim(table.concat(toks, " ", 1, at - 1)):gsub(",$", "")
  local text = Trim(table.concat(toks, " ", at + 2))
  local mapID
  if zone == "" then
    mapID = currentMap
    if not mapID then return nil, "no zone, and your current zone is unknown" end
  elseif zone:match("^#%d+$") then
    mapID = tonumber(zone:sub(2))
  else
    mapID = I.FindMap(zone)
    if not mapID then return nil, string.format("unknown zone '%s'", zone) end
  end
  if x < 0 or x > 100 or y < 0 or y > 100 then return nil, "coordinates must be 0-100" end
  return { mapID = mapID, x = x, y = y, name = text ~= "" and text or nil }
end

-- A waypoint as a stop: { x, y, cont, name } in world coordinates, or nil, error.
function I.ToStop(w)
  local m = ns.Maps and ns.Maps[w.mapID]
  local b = m and m.bounds
  if not b then return nil, "no map data for that zone" end
  local u, v = w.x / 100, w.y / 100
  local name = w.name or string.format("%s %.1f, %.1f", m.name or "?", w.x, w.y)
  return { x = b[3] - v * (b[3] - b[1]), y = b[4] - u * (b[4] - b[2]), cont = Geo.MapCont(w.mapID), name = name }
end

-- All lines: stops, and { "Line n: error", ... } for the ones that couldn't be read.
function I.Parse(text, currentMap)
  local stops, errors, n = {}, {}, 0
  for line in (text or ""):gmatch("[^\r\n]+") do
    n = n + 1
    local w, err = I.ParseLine(line, currentMap)
    local stop
    if w then stop, err = I.ToStop(w) end
    if stop then
      stops[#stops + 1] = stop
    elseif err then
      errors[#errors + 1] = string.format("Line %d: %s", n, err)
    end
  end
  return stops, errors
end

-- A map pin link from chat ("worldmap:<uiMapID>:<x>:<y>", x and y in 1/10000 of the
-- map): { cont, x, y, name } in world coordinates, or nil.
function I.ParseMapPin(link)
  local mapID, u, v = link:match("^worldmap:(%d+):(%d+):(%d+)")
  mapID, u, v = tonumber(mapID), tonumber(u), tonumber(v)
  local m = mapID and ns.Maps and ns.Maps[mapID]
  local b = m and m.bounds
  if not (b and u and v) then return nil end
  u, v = u / 10000, v / 10000
  if u < 0 or u > 1 or v < 0 or v > 1 then return nil end
  return { cont = Geo.MapCont(mapID), x = b[3] - v * (b[3] - b[1]), y = b[4] - u * (b[4] - b[2]),
    name = string.format("Map pin (%s %.1f, %.1f)", m.name or "?", u * 100, v * 100) }
end

-- The chat box being typed in, or nil.
function I.ChatBox()
  local box = (ChatEdit_GetActiveWindow and ChatEdit_GetActiveWindow())
    or (ChatFrameUtil and ChatFrameUtil.GetActiveWindow and ChatFrameUtil.GetActiveWindow())
  return box or nil
end

-- The map pin (asked 2026-10-01: as the game's world map does it): one diamond on the map, the game's own
-- waypoint (C_Map's user waypoint) where the client has one. Ctrl + left-click on the map puts it there,
-- Shift + left-click on it links it in chat, Ctrl + left-click on it takes it away. Not a custom pin: never
-- in the shared map data. Kept per character (cdb.mapPin: { cont, x, y }, world), so it lasts over reloads
-- and logouts, and put back as the game's waypoint at login when the game has none. The game's waypoint
-- set or cleared elsewhere (its world map, a link clicked) moves the pin with it.
local syncing -- (our own change of the game's waypoint: not taken back in from its event)

function I.MapPin()
  local cdb = ns.db and ns.CharDB and ns.CharDB()
  return cdb and cdb.mapPin or nil
end

local function Redraw()
  if ns.GPS and ns.GPS.Redraw then ns.GPS.Redraw() end
end

-- The spot as the game's map point: uiMapID, x, y (0-1), on a zone's (or city's) map; not in a dungeon's.
local function MapPoint(cont, x, y)
  local G = ns.GPS
  if not (cont and cont < 20000 and G and G.LocateWorld) then return nil end
  local mapID, _, u, v = G.LocateWorld(Geo.Base(cont), x, y)
  return mapID, u, v
end

function I.SetMapPin(cont, x, y)
  if not (cont and cont < 20000) then return false end
  ns.CharDB().mapPin = { cont = Geo.Base(cont), x = x, y = y }
  local mapID, u, v = MapPoint(cont, x, y)
  if mapID and C_Map and C_Map.SetUserWaypoint and UiMapPoint then
    syncing = true
    pcall(C_Map.SetUserWaypoint, UiMapPoint.CreateFromCoordinates(mapID, u, v))
    syncing = false
  end
  Redraw()
  return true
end

function I.ClearMapPin()
  ns.CharDB().mapPin = nil
  if C_Map and C_Map.ClearUserWaypoint then
    syncing = true
    pcall(C_Map.ClearUserWaypoint)
    syncing = false
  end
  Redraw()
end

-- The pin's chat link ("[Map Pin Location]"): the game's for its waypoint, else made the same way.
function I.MapPinLink()
  local p = I.MapPin()
  if not p then return nil end
  if C_Map and C_Map.HasUserWaypoint and C_Map.GetUserWaypointHyperlink then
    local ok, has = pcall(C_Map.HasUserWaypoint)
    if ok and has then
      local okL, link = pcall(C_Map.GetUserWaypointHyperlink)
      if okL and link then return link end
    end
  end
  local mapID, u, v = MapPoint(p.cont, p.x, p.y)
  if not mapID then return nil end
  return string.format("|cffffff00|Hworldmap:%d:%d:%d|h[Map Pin Location]|h|r", mapID,
    math.floor(u * 10000 + 0.5), math.floor(v * 10000 + 0.5))
end

-- Shift + left-click on the pin: its link in the chat box being typed in, else a chat box opened with it.
function I.LinkMapPin()
  local link = I.MapPinLink()
  if not link then return false end
  if I.ChatBox() then
    if ChatFrameUtil and ChatFrameUtil.InsertLink then
      ChatFrameUtil.InsertLink(link)
    elseif ChatEdit_InsertLink then
      ChatEdit_InsertLink(link)
    else
      I.ChatBox():Insert(link)
    end
  elseif ChatFrameUtil and ChatFrameUtil.OpenChat then
    ChatFrameUtil.OpenChat(link)
  elseif ChatFrame_OpenChat then
    ChatFrame_OpenChat(link)
  else
    return false
  end
  return true
end

-- The game's waypoint changed (USER_WAYPOINT_UPDATED): the pin follows it.
function I.OnUserWaypoint()
  if syncing or not (C_Map and C_Map.HasUserWaypoint and ns.db) then return end
  local cdb = ns.CharDB()
  local ok, has = pcall(C_Map.HasUserWaypoint)
  if not ok then return end
  if has then
    local okW, wp = pcall(C_Map.GetUserWaypoint)
    local pos = okW and wp and wp.position
    local x, y, cont
    if pos and ns.Layers and ns.Layers.MapToWorld then x, y, cont = ns.Layers.MapToWorld(wp.uiMapID, pos.x, pos.y) end
    if x and cont then cdb.mapPin = { cont = Geo.Base(cont), x = x, y = y } end
  else
    cdb.mapPin = nil
  end
  Redraw()
end

-- At login: the saved pin back as the game's waypoint, when the game has none.
function I.RestoreMapPin()
  local p = I.MapPin()
  if not (p and C_Map and C_Map.HasUserWaypoint) then return end
  local ok, has = pcall(C_Map.HasUserWaypoint)
  if ok and not has then I.SetMapPin(p.cont, p.x, p.y) end
end

-- A map pin link clicked in chat (hooked on SetItemRef): a stop there (option acceptMapPins; asked
-- 2026-10-01: a plain click, it used to take Shift), but not a Shift-click with a chat box open, which is
-- the game's "put it in the chat". Whether `link` was a map pin.
function I.OnMapPinLink(link)
  local pin = type(link) == "string" and I.ParseMapPin(link)
  if not pin then return false end
  local relink = IsModifiedClick and IsModifiedClick("CHATLINK") and I.ChatBox()
  local st = ns.settings and ns.settings.gps
  if not relink and not (st and st.acceptMapPins == false) then I.AddMapPin(pin) end
  return true
end

-- A shared map pin as a stop: added to the route (or a new route), with the route tour on
-- an open map (see GPS.RouteChanged).
function I.AddMapPin(pin)
  local N = ns.Nav
  local stop = { cont = pin.cont, x = pin.x, y = pin.y, name = pin.name, tex = pin.tex, z = pin.z }
  if #N.stops > 0 then
    local ok, asked = N.AddStop(stop, ns.settings and ns.settings.gps.fastestOrder)
    if not ok then
      if not asked then ns.Print(string.format("Map pin: the route is full (%d stops at most).", N.MAX_STOPS)) end
      return
    end
  elseif N.SetStops({ stop }) == false then
    return -- (held off, or asked first: a zone too high for the character)
  end
  ns.Print(pin.name .. " added to your route.")
  if ns.GPS and ns.GPS.RouteChanged then ns.GPS.RouteChanged() end
end

-- Make them the route (or add them to it). Returns how many stops were set.
function I.Apply(stops, add)
  local N = ns.Nav
  local list = {}
  if add then
    for _, d in ipairs(N.stops) do list[#list + 1] = d end
  end
  local max = N.MAX_STOPS
  for _, d in ipairs(stops) do
    if #list >= max then break end
    d.icon = N.NextMarker(list)
    list[#list + 1] = d
  end
  N.SetStops(list, ns.settings and ns.settings.gps.fastestOrder)
  return #list
end

---------------------------------------------------------------------------
-- Export and share
---------------------------------------------------------------------------

-- A stop as a TomTom line, "/way Durotar 52.3 41.8 Razor Hill": the zone by name, or as
-- "#mapID" when that name would pick another map. nil when no zone map covers it.
function I.WayLine(d)
  local id, name, mx, my = ns.GPS.LocateWorld(Geo.Base(d.cont), d.x, d.y) -- (a city level: its continent's maps)
  if not id then return nil end
  local zone = I.FindMap(name) == id and name or ("#" .. id)
  local line = string.format("/way %s %.1f %.1f", zone, mx * 100, my * 100)
  if d.name then line = line .. " " .. d.name:gsub("[\r\n]", " ") end
  return line
end

-- The stops as /way lines (one per line), and how many couldn't be written.
function I.ExportText(stops)
  local lines, skipped = {}, 0
  for _, d in ipairs(stops) do
    local line = I.WayLine(d)
    if line then lines[#lines + 1] = line else skipped = skipped + 1 end
  end
  return table.concat(lines, "\n"), skipped
end

-- In game, to other AzerothGPS users, as a link (asked 2026-10-02: like a map pin's, so nothing pops up
-- unasked and nobody's navigation is interrupted). Sharing puts a short line in your chat box,
-- "[AzerothGPS Route 1a2b3c: 3 stops]", sent when you press Enter: plain text for players without
-- AzerothGPS, a link for those with it. Clicking the link asks you for the route (an addon whisper,
-- "?\tid"), and only then are its stops sent, to that player alone: one addon message per stop,
-- "version \t id \t i \t n \t cont \t x \t y \t name". Stops nobody asked for are ignored, and nothing
-- is used until they accept.
I.PREFIX = "AzerothGPS"
I.SHARE_TIMEOUT = 30 -- seconds to wait for a route's remaining stops
I.ASK_TIMEOUT = 30 -- seconds a clicked link's route is waited for
I.POSTED_MAX = 5 -- routes linked lately that are still answered for
I.POSTED_TTL = 3600 -- (an hour each)
I.ANSWER_GAP = 5 -- seconds before the same player gets the same route again
local SHARE_VERSION = "1"
-- Stops sent in game (the next ones): addon messages are rate limited, and the other
-- player's popup lists them all. Copy as /way has no limit.
I.MAX_SHARE = 8

function I.ShareMessages(stops, id)
  local msgs, n = {}, math.min(#stops, I.MAX_SHARE)
  for i = 1, n do
    local d = stops[i]
    local name = (d.name or ""):gsub("[\t\r\n|]", " "):sub(1, 120)
    msgs[i] = string.format("%s\t%s\t%d\t%d\t%d\t%.1f\t%.1f\t%s", SHARE_VERSION, id, i, n, d.cont, d.x, d.y, name)
  end
  return msgs
end

local function KnownContinent(cont)
  if ns.CityLevels and ns.CityLevels[cont] then return true end -- (an underground city's level)
  for _, m in pairs(ns.Maps or {}) do
    if m.type == 2 and m.continent == cont then return true end
  end
  return false
end

local incoming = {} -- [sender] = { id, n, got, stops, t }

-- One received message: the whole route ({ stops }) once all its stops are in, else nil.
-- Anything malformed is ignored.
function I.Receive(text, sender, now)
  local v, id, i, n, cont, x, y, name =
    (text or ""):match("^(%d+)\t(%w+)\t(%d+)\t(%d+)\t(%-?%d+)\t(%-?[%d%.]+)\t(%-?[%d%.]+)\t(.*)$")
  if v ~= SHARE_VERSION then return nil end
  i, n, cont, x, y = tonumber(i), tonumber(n), tonumber(cont), tonumber(x), tonumber(y)
  if not (i and n and cont and x and y) or n < 1 or n > I.MAX_SHARE or i < 1 or i > n
      or math.abs(x) > 30000 or math.abs(y) > 30000 or not KnownContinent(cont) then
    return nil
  end
  local r = incoming[sender]
  if not r or r.id ~= id or r.n ~= n or now - r.t > I.SHARE_TIMEOUT then
    r = { id = id, n = n, got = 0, stops = {}, t = now }
    incoming[sender] = r
  end
  if not r.stops[i] then r.got = r.got + 1 end
  r.stops[i] = { x = x, y = y, cont = cont, name = name ~= "" and name or nil }
  r.t = now
  if r.got < n then return nil end
  incoming[sender] = nil
  return r.stops
end

-- The one way out to other players: `I.io.send(prefix, msg, channel, target)`, the game's addon
-- message. (A developer hook: the private dev addon, AzerothGPS_Dev, swaps it to test sharing
-- without anything going over the network; see AzerothGPS_Extend in Core.lua.)
I.io = {}
function I.io.send(prefix, msg, channel, target)
  local send = C_ChatInfo and C_ChatInfo.SendAddonMessage or SendAddonMessage
  return send(prefix, msg, channel, target)
end

-- The chat box opened with `text` for `channel` ("WHISPER" to `target`, "PARTY", "RAID"; nil: the chat box
-- being typed in, else a new one), for the player to send. Nothing is sent here. Whether a box took it.
local function InsertInChat(text)
  local box = I.ChatBox()
  if box then
    if ChatFrameUtil and ChatFrameUtil.InsertLink then
      ChatFrameUtil.InsertLink(text)
    elseif ChatEdit_InsertLink then
      ChatEdit_InsertLink(text)
    else
      box:Insert(text)
    end
    return true
  end
  local open = ChatFrameUtil and ChatFrameUtil.OpenChat or ChatFrame_OpenChat
  if not open then return false end
  open(text)
  return true
end

function I.io.chat(text, channel, target)
  local slash
  if channel == "WHISPER" and target then
    slash = (SLASH_WHISPER1 or "/w") .. " " .. target .. " "
  elseif channel == "PARTY" then
    slash = (SLASH_PARTY1 or "/p") .. " "
  elseif channel == "RAID" then
    slash = (SLASH_RAID1 or "/raid") .. " "
  end
  if not slash then return InsertInChat(text) end
  local open = ChatFrameUtil and ChatFrameUtil.OpenChat or ChatFrame_OpenChat
  if not open then return false end
  open(slash .. text) -- (as the game's own "Whisper" does: the box parses the slash command)
  return true
end

-- A route's line in chat: "[AzerothGPS Route 1a2b3c: 3 stops]" (I.LinkifyRoutes makes it a link).
function I.RouteTag(id, n)
  return string.format("[AzerothGPS Route %s: %d stop%s]", id, n, n == 1 and "" or "s")
end
local TAG_PATTERN = "%[AzerothGPS Route (%x+): (%d+) stops?%]"

local posted, postedOrder = {}, {} -- [id] = { msgs, t }: the routes you linked lately, as they were then
I.posted = posted

function I.Post(id, msgs, now)
  posted[id] = { msgs = msgs, t = now or GetTime() }
  postedOrder[#postedOrder + 1] = id
  while #postedOrder > I.POSTED_MAX do posted[table.remove(postedOrder, 1)] = nil end
end

-- Link the route in chat: channel "WHISPER" (to `target`), "PARTY" or "RAID", or nil (the chat box
-- being typed in). Nothing is sent: the chat box opens with the link, for you to send. Returns the
-- number of stops it carries and its id, or nil and why not.
function I.Send(channel, target)
  local stops = ns.Nav.stops
  if #stops == 0 then return nil, "No route to share." end
  local id = string.format("%x", math.random(0x100000, 0xFFFFFF))
  local msgs = I.ShareMessages(stops, id)
  if not I.io.chat(I.RouteTag(id, #msgs), channel, target) then return nil, "Couldn't open a chat box." end
  I.Post(id, msgs)
  return #msgs, id
end

function I.AcceptShared()
  return not ns.settings or ns.settings.gps.acceptShared ~= false
end

-- A player's name to compare by: without the realm, lower case.
local function Who(name)
  return ((name or ""):match("^[^-]*")):lower()
end

local function IsMe(name)
  local me = UnitName and UnitName("player")
  return me ~= nil and Who(name) == Who(me)
end

local answered = {} -- [who \t id] = when

-- Someone clicked your route's link and asks for it: its stops, to them only (a route you linked in
-- the last hour; once in ANSWER_GAP seconds each). How many messages went.
function I.Answer(sender, id, now)
  local p = posted[id]
  if not p or now - p.t > I.POSTED_TTL then return 0 end
  local key = Who(sender) .. "\t" .. id
  if answered[key] and now - answered[key] < I.ANSWER_GAP then return 0 end
  answered[key] = now
  for _, m in ipairs(p.msgs) do I.io.send(I.PREFIX, m, "WHISPER", sender) end
  return #p.msgs
end

local askedFor = {} -- [who] = { id, t }: the route last asked for from each player (its link clicked)

-- A route `sender`'s stops are taken in for (I.Expect: the dev addon's fake players answer through it).
function I.Expect(sender, id, now)
  askedFor[Who(sender)] = { id = id, t = now or GetTime() }
end

function I.Request(sender, id)
  I.Expect(sender, id)
  I.io.send(I.PREFIX, "?\t" .. id, "WHISPER", sender)
  local name = Ambiguate and Ambiguate(sender, "none") or sender
  if C_Timer and C_Timer.After then
    C_Timer.After(I.ASK_TIMEOUT, function()
      local a = askedFor[Who(sender)]
      if a and a.id == id then
        askedFor[Who(sender)] = nil
        ns.Print(string.format("No route from %s: the link may be over an hour old, or they're offline.", name))
      end
    end)
  end
  ns.Print(string.format("Asking %s for the route...", name))
end

-- "[AzerothGPS Route id: n stops]" in a chat line from `author`: a link that asks them for it.
function I.LinkifyRoutes(msg, author)
  if type(msg) ~= "string" or not msg:find("[AzerothGPS Route ", 1, true) or not I.AcceptShared() then return msg end
  author = (author or ""):gsub("[:|]", "")
  if author == "" then return msg end
  return (msg:gsub(TAG_PATTERN, function(id, n)
    return string.format("|cff33ff99|Haddon:AzerothGPS:route:%s:%s|h[AzerothGPS Route: %s stop%s]|h|r",
      id, author, n, n == "1" and "" or "s")
  end))
end

-- A route link clicked (I.LinkifyRoutes): its author is asked for it. Whether `link` was one.
function I.OnRouteLink(link)
  if type(link) ~= "string" then return false end
  local id, who = link:match("^addon:AzerothGPS:route:(%x+):(.+)$")
  if not id then return false end
  if IsMe(who) then
    ns.Print("That's your route's link: AzerothGPS users who click it are sent your route.")
  elseif not I.AcceptShared() then
    ns.Print("Routes from other players are turned off (AzerothGPS options: Accept routes shared by players).")
  else
    I.Request(who, id)
  end
  return true
end

-- A route you asked for (its link clicked): ask before using it. (I.Offer: the dev addon's checks swap
-- it to see what would be offered without the popup.)
function I.Offer(sender, stops)
  local who = Ambiguate and Ambiguate(sender, "none") or sender
  local names = {}
  for i, d in ipairs(stops) do names[i] = string.format("%d. %s", i, d.name or ("stop " .. i)) end
  -- (AzerothGPS's popup without a title bar, ns.Ask; gone unanswered after a minute)
  I.offered = { stops = stops, who = who }
  I.offerBox = ns.Ask("AzerothGPSSharedRoute",
    string.format("%s's route (AzerothGPS):\n\n%s\n\nUse it as your route?", who, table.concat(names, "\n")),
    "Use Route", "Ignore", function()
      local n = I.Apply(stops, false)
      ns.Print(string.format("route from %s: %d stop%s", who, n, n > 1 and "s" or ""))
      if ns.GPS then
        ns.GPS.Follow()
        ns.GPS.Redraw()
      end
    end, nil, { timeout = 60 })
end

local SHARE_CHANNELS = { WHISPER = true, PARTY = true, RAID = true, INSTANCE_CHAT = true }

-- The chat a route's line becomes a link in.
I.LINK_EVENTS = { "CHAT_MSG_WHISPER", "CHAT_MSG_WHISPER_INFORM", "CHAT_MSG_PARTY", "CHAT_MSG_PARTY_LEADER",
  "CHAT_MSG_RAID", "CHAT_MSG_RAID_LEADER", "CHAT_MSG_RAID_WARNING", "CHAT_MSG_INSTANCE_CHAT",
  "CHAT_MSG_INSTANCE_CHAT_LEADER", "CHAT_MSG_GUILD", "CHAT_MSG_OFFICER", "CHAT_MSG_SAY", "CHAT_MSG_YELL",
  "CHAT_MSG_CHANNEL" }

-- An addon message received (CHAT_MSG_ADDON): someone asking for a route you linked (answered), or a
-- stop of a route you asked for, offered once all its stops are in; any other route is ignored.
-- (I.OnAddonMessage: the dev addon feeds it fake players' messages.)
function I.OnAddonMessage(prefix, text, channel, sender)
  if prefix ~= I.PREFIX or not SHARE_CHANNELS[channel] or type(text) ~= "string" or IsMe(sender) then return end
  local now = GetTime()
  local want = text:match("^%?\t(%x+)$")
  if want then
    if channel == "WHISPER" then I.Answer(sender, want, now) end
    return
  end
  if not I.AcceptShared() then return end
  local a = askedFor[Who(sender)]
  if not (a and text:match("^%d+\t(%w+)\t") == a.id and now - a.t <= I.ASK_TIMEOUT) then return end
  local stops = I.Receive(text, sender, now)
  if stops then
    askedFor[Who(sender)] = nil
    I.Offer(sender, stops)
  end
end

---------------------------------------------------------------------------
-- Window
---------------------------------------------------------------------------

local win

local function Build()
  -- the map window's frame without the logo, as every popup (ns.Window)
  local f = ns.Window("AzerothGPSImport", 480, 372, "Import and Share Waypoints")
  local TOP = -f.top -- where the content starts, below the title
  local hint = f:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  hint:SetPoint("TOPLEFT", 12, -TOP)
  hint:SetText("Paste TomTom lines, one per stop:  /way Elwynn Forest 43.2 65.1 First Stop")

  local scroll = CreateFrame("ScrollFrame", "AzerothGPSImportScroll", f, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", 12, -(TOP + 16))
  scroll:SetPoint("BOTTOMRIGHT", -32, 132)
  local bg = f:CreateTexture(nil, "BACKGROUND", nil, 1)
  bg:SetPoint("TOPLEFT", scroll, -4, 4)
  bg:SetPoint("BOTTOMRIGHT", scroll, 4, -4)
  bg:SetColorTexture(0, 0, 0, 0.5)
  local edit = CreateFrame("EditBox", nil, scroll)
  edit:SetMultiLine(true)
  edit:SetAutoFocus(false)
  edit:SetFontObject(ChatFontNormal)
  edit:SetWidth(420)
  edit:SetScript("OnEscapePressed", function() f:Hide() end)
  scroll:SetScrollChild(edit)
  scroll:SetScript("OnMouseDown", function() edit:SetFocus() end)
  f.edit = edit

  local status = f:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  status:SetPoint("BOTTOMLEFT", 12, 100)
  status:SetPoint("RIGHT", -12, 0)
  status:SetJustifyH("LEFT")
  status:SetWordWrap(true)
  f.status = status

  -- Share the current route: as /way text to copy anywhere, or sent in game.
  local copy = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  copy:SetSize(150, 22)
  copy:SetPoint("BOTTOMLEFT", 12, 68)
  copy:SetText("Copy Route as /way")
  copy:SetScript("OnClick", function()
    local text, skipped = I.ExportText(ns.Nav.stops)
    if text == "" then
      status:SetText("|cffff6060No route to copy.|r Set one first (double-click the map).")
      return
    end
    edit:SetText(text)
    edit:SetFocus()
    edit:HighlightText()
    status:SetText("Selected above: press Ctrl+C, then paste it anywhere (Discord, a guide, chat). "
      .. "AzerothGPS and TomTom users can paste it to get the same stops."
      .. (skipped > 0 and string.format(" |cffff6060%d stop%s outside any zone left out.|r", skipped, skipped > 1 and "s" or "") or ""))
  end)
  copy:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText("Copy Route as /way", 1, 1, 1)
    GameTooltip:AddLine("Writes your route's stops as TomTom /way lines in the box, selected for copying.", nil, nil, nil, true)
    GameTooltip:Show()
  end)
  copy:SetScript("OnLeave", GameTooltip_Hide)

  local sendLabel = f:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  sendLabel:SetPoint("LEFT", copy, "RIGHT", 12, 0)
  sendLabel:SetText("Link To")
  local who = CreateFrame("EditBox", nil, f, "InputBoxTemplate")
  who:SetSize(100, 20)
  who:SetPoint("LEFT", sendLabel, "RIGHT", 10, 0)
  who:SetAutoFocus(false)
  who:SetMaxLetters(60)
  who:SetScript("OnEscapePressed", function() f:Hide() end)
  f.who = who
  who:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText("Link To", 1, 1, 1)
    GameTooltip:AddLine("A player's name (Name or Name-Realm). Shift+click a name in chat to fill it in, or target the player before opening this window.", nil, nil, nil, true)
    GameTooltip:Show()
  end)
  who:SetScript("OnLeave", GameTooltip_Hide)
  local function Sent(n, err, to)
    if n then
      local more = #ns.Nav.stops > n and string.format(" (the next %d; use Copy route as /way for all %d)", n, #ns.Nav.stops) or ""
      status:SetText(string.format("A link to your route (%d stop%s%s) is in the chat box to %s: press Enter to send it. "
        .. "AzerothGPS users click it to get the route; others only see the short line.", n, n > 1 and "s" or "", more, to))
    else
      status:SetText("|cffff6060" .. err .. "|r")
    end
  end
  local whisper = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  whisper:SetSize(70, 22)
  whisper:SetPoint("LEFT", who, "RIGHT", 6, 0)
  whisper:SetText("Player")
  whisper:SetScript("OnClick", function()
    local name = Trim(who:GetText() or "")
    if name == "" then
      status:SetText("|cffff6060Type a player's name|r (or target them first).")
      return
    end
    local n, err = I.Send("WHISPER", name)
    Sent(n, err, name)
  end)
  local group = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  group:SetSize(64, 22)
  group:SetPoint("LEFT", whisper, "RIGHT", 4, 0)
  group:SetText("Group")
  group:SetScript("OnClick", function()
    local channel = IsInRaid and IsInRaid() and "RAID" or (IsInGroup and IsInGroup() and "PARTY")
    if not channel then
      status:SetText("|cffff6060You're not in a group.|r")
      return
    end
    local n, err = I.Send(channel, nil)
    Sent(n, err, channel == "RAID" and "your raid" or "your party")
  end)
  for _, b in ipairs({ whisper, group }) do
    b:SetScript("OnEnter", function(self)
      GameTooltip:SetOwner(self, "ANCHOR_TOP")
      GameTooltip:SetText(self == whisper and "Link to a player" or "Link to your group", 1, 1, 1)
      GameTooltip:AddLine("Puts a link to your route in the chat box (a whisper, or party or raid chat) for you to send. "
        .. "AzerothGPS users who click it get your route's stops, and are asked before it replaces theirs. Nothing is sent until you press Enter.", nil, nil, nil, true)
      GameTooltip:Show()
    end)
    b:SetScript("OnLeave", GameTooltip_Hide)
  end

  local add = CreateFrame("CheckButton", nil, f, "UICheckButtonTemplate")
  add:SetSize(22, 22)
  add:SetPoint("BOTTOMLEFT", 10, 38)
  local addText = add:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  addText:SetPoint("LEFT", add, "RIGHT", 2, 0)
  addText:SetText("Add to the current route")
  f.add = add
  -- or: the lines are herb and ore nodes for the map (unconfirmed until gathered)
  local asNodes = CreateFrame("CheckButton", nil, f, "UICheckButtonTemplate")
  asNodes:SetSize(22, 22)
  asNodes:SetPoint("LEFT", addText, "RIGHT", 16, 0)
  local nodesText = asNodes:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  nodesText:SetPoint("LEFT", asNodes, "RIGHT", 2, 0)
  nodesText:SetText("Import as herb/ore nodes")
  asNodes:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_TOP")
    GameTooltip:SetText("Import as herb/ore nodes", 1, 1, 1)
    GameTooltip:AddLine("Each line is a gathering node for the map instead of a stop, e.g. /way Elwynn Forest 43.2 65.1 Copper Vein. The name must say what it is (a herb or ore name). They show faded until you gather there. Circle them with \"Draw a farming area\" (map menu) to route through them.", nil, nil, nil, true)
    GameTooltip:Show()
  end)
  asNodes:SetScript("OnLeave", GameTooltip_Hide)
  f.asNodes = asNodes

  local go = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  go:SetSize(90, 22)
  go:SetPoint("BOTTOMRIGHT", -12, 10)
  go:SetText("Import")
  go:SetScript("OnClick", function()
    if asNodes:GetChecked() and ns.Layers then
      local added, skipped, errs = ns.Layers.ImportNodes(edit:GetText())
      local msg = string.format("Nodes: %d added%s.", added, skipped > 0 and string.format(", %d already known", skipped) or "")
      if #errs > 0 then msg = msg .. " Skipped: " .. table.concat(errs, "; ") end
      ns.Print(msg)
      status:SetText(msg)
      if ns.GPS then ns.GPS.Redraw() end
      return
    end
    local stops, errors = I.Parse(edit:GetText(), C_Map.GetBestMapForUnit("player"))
    if #stops == 0 then
      status:SetText("|cffff6060Nothing to import.|r " .. table.concat(errors, "; "))
      return
    end
    local wanted = #stops + (add:GetChecked() and #ns.Nav.stops or 0)
    local n = I.Apply(stops, add:GetChecked())
    local msg = string.format("Route: %d stop%s.", n, n > 1 and "s" or "")
    if wanted > n then msg = msg .. string.format(" Only %d fit (%d stops at most).", n, ns.Nav.MAX_STOPS) end
    if #errors > 0 then msg = msg .. " Skipped: " .. table.concat(errors, "; ") end
    ns.Print(msg)
    if #errors == 0 and wanted <= n then
      f:Hide()
    else
      status:SetText(msg)
    end
    if ns.GPS then
      ns.GPS.Follow()
      ns.GPS.Redraw()
    end
  end)
  local cancel = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
  cancel:SetSize(90, 22)
  cancel:SetPoint("RIGHT", go, "LEFT", -6, 0)
  cancel:SetText("Cancel")
  cancel:SetScript("OnClick", function() f:Hide() end)

  f:SetScript("OnShow", function()
    status:SetText("|cff9d9d9dTip: Shift+click a player's name in chat to put it in \"Link to\".|r")
    add:SetChecked(false)
    add:SetEnabled(#ns.Nav.stops > 0)
    -- your target, if it's another player, is the default recipient
    if UnitIsPlayer("target") and not UnitIsUnit("target", "player") then
      local name, realm = UnitName("target")
      f.who:SetText(realm and realm ~= "" and (name .. "-" .. realm) or name)
    end
    edit:SetFocus()
  end)
  f:Hide()
  return f
end

function I.Toggle()
  win = win or Build()
  win:SetShown(not win:IsShown())
end

-- Text with one or more "/way ..." commands (typed, or several lines pasted into the chat
-- box, possibly run together on one line): each one's waypoint. Returns stops, errors.
function I.ParseWays(text, currentMap)
  -- every "/way" or "/tway" starts a new waypoint
  local lines = (text or ""):gsub("/[tT]?[wW][aA][yY]%s", "\n")
  return I.Parse(lines, currentMap)
end

function I.Enabled()
  return not ns.settings or ns.settings.gps.acceptWay ~= false
end

-- Add the waypoints in `text` to the route; tell the player what happened.
function I.AddWays(text)
  if not I.Enabled() then return end
  local stops, errors = I.ParseWays(text, C_Map.GetBestMapForUnit("player"))
  for _, e in ipairs(errors) do ns.Print("/way: " .. e) end
  if #stops == 0 then
    if #errors == 0 then ns.Print("/way: usage: /way [zone] x y [description]") end
    return
  end
  local before = #ns.Nav.stops
  local n = I.Apply(stops, true)
  local added = n - before
  if added < #stops then ns.Print(string.format("/way: only %d stops fit (%d at most)", added, ns.Nav.MAX_STOPS)) end
  if added == 1 then
    ns.Print(string.format("stop %d: %s", n, stops[1].name))
  elseif added > 1 then
    ns.Print(string.format("%d stops added to the route (%d in all)", added, n))
  end
  if ns.GPS then ns.GPS.Redraw() end
end

-- "/way ..." typed in chat (our own command when TomTom isn't installed).
function I.SlashWay(msg)
  if not I.Enabled() then
    ns.Print("/way is turned off (AzerothGPS options: Accept TomTom /way commands)")
    return
  end
  I.AddWays("/way " .. (msg or ""))
end

-- Several /way lines pasted into a chat box at once: take them all right away (the chat box
-- would only run the first) and empty the box.
local function OnChatText(box, userInput)
  if not userInput or not I.Enabled() then return end
  local text = box:GetText() or ""
  local _, count = text:gsub("/[tT]?[wW][aA][yY]%s", "")
  if count < 2 then return end
  box:SetText("")
  I.AddWays(text)
  if ChatEdit_DeactivateChat then pcall(ChatEdit_DeactivateChat, box) else box:ClearFocus() end
end

function I.Init()
  local loaded = C_AddOns and C_AddOns.IsAddOnLoaded and C_AddOns.IsAddOnLoaded("TomTom")
    or IsAddOnLoaded and IsAddOnLoaded("TomTom")
  -- whoever owns /way already (TomTom): also add its waypoints to our route
  local owner
  for key in pairs(SlashCmdList) do
    for i = 1, 9 do
      local cmd = _G["SLASH_" .. key .. i]
      if not cmd then break end
      if cmd:lower() == "/way" then owner = key end
    end
  end
  if owner then
    hooksecurefunc(SlashCmdList, owner, function(msg) if I.Enabled() then I.AddWays("/way " .. (msg or "")) end end)
  elseif not loaded then
    SLASH_AZEROTHGPSWAY1 = "/way"
    SLASH_AZEROTHGPSWAY2 = "/tway"
    SlashCmdList.AZEROTHGPSWAY = I.SlashWay
  end
  -- pasted lines in any chat box
  for i = 1, (NUM_CHAT_WINDOWS or 10) do
    local box = _G["ChatFrame" .. i .. "EditBox"]
    if box then box:HookScript("OnTextChanged", OnChatText) end
  end
  -- route lines in chat as links (I.LinkifyRoutes); a click on one asks its author for the route (the game
  -- hands "addon:" links to EventRegistry's "SetItemRef"; SetItemRef's hook as well: one ask per click)
  local addFilter = ChatFrameUtil and ChatFrameUtil.AddMessageEventFilter or ChatFrame_AddMessageEventFilter
  if addFilter then
    local function Filter(_, event, msg, author, ...)
      if event == "CHAT_MSG_WHISPER_INFORM" or event == "CHAT_MSG_BN_WHISPER_INFORM" then author = UnitName("player") end
      local out = I.LinkifyRoutes(msg, author)
      if out ~= msg then return false, out, author, ... end
    end
    for _, e in ipairs(I.LINK_EVENTS) do addFilter(e, Filter) end
  end
  local lastLink, lastAt
  local function RouteClick(link)
    if type(link) ~= "string" or not link:find("^addon:AzerothGPS:route:") then return false end
    if link == lastLink and GetTime() - lastAt < 0.5 then return true end
    lastLink, lastAt = link, GetTime()
    return I.OnRouteLink(link)
  end
  if EventRegistry and EventRegistry.RegisterCallback then
    EventRegistry:RegisterCallback("SetItemRef", function(_, link) RouteClick(link) end, I)
  end
  hooksecurefunc("SetItemRef", function(link)
    if RouteClick(link) then return end
    -- a click on a map pin someone shared in chat: it becomes a stop
    if I.OnMapPinLink(link) then return end
    if type(link) ~= "string" or not IsModifiedClick("CHATLINK") then return end
    -- Shift+click on a player's name in chat, with this window open: fills in "Link to"
    if not win or not win:IsShown() then return end
    local name = link:match("^player:([^:]+)")
    if name and name ~= "" then
      win.who:SetText(name)
      win.who:SetCursorPosition(0)
    end
  end)
  -- the map pin: put back as the game's waypoint, then following the game's (I.MapPin)
  local function Waypoints()
    pcall(I.RestoreMapPin)
    local wf = CreateFrame("Frame")
    if pcall(wf.RegisterEvent, wf, "USER_WAYPOINT_UPDATED") then
      wf:SetScript("OnEvent", function() pcall(I.OnUserWaypoint) end)
    end
  end
  if C_Timer and C_Timer.After then C_Timer.After(3, Waypoints) else Waypoints() end
  -- routes shared by other players
  local register = C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix or RegisterAddonMessagePrefix
  if register then
    register(I.PREFIX)
    local ev = CreateFrame("Frame")
    ev:RegisterEvent("CHAT_MSG_ADDON")
    ev:SetScript("OnEvent", function(_, _, prefix, text, channel, sender) I.OnAddonMessage(prefix, text, channel, sender) end)
  end
end

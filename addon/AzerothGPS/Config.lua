-- Slash commands: /agps (alias /gps)
local _, ns = ...

local HELP = {
  "/agps                    (options window; also right-click the minimap button)",
  "/agps show | hide | toggle",
  "/agps opacity <0-100>",
  "/agps size <px>          (frame edge, default 260)",
  "/agps zoom <yards>       (center to edge; or mouse wheel over the frame)",
  "/agps rotate on|off      (heading-up / north-up)",
  "/agps style minimap|zone|nospoiler (terrain / world map / explored parts only)",
  "/agps clear              (cancel the route)",
  "/agps offroad on|off     (straight across open ground; roads only where needed)",
  "/agps arrow on|off       (turn-by-turn direction arrow window)",
  "/agps import             (paste TomTom /way lines as stops; copy or send your route)",
  "/way [zone] x y [text]   (add a stop; several pasted lines = several stops; with TomTom too)",
  "/agps poi taxi|poi|labels on|off (points of interest on the map)",
  "/agps quests on|off      (your quests' objectives and turn-ins)",
  "/agps bosses             (in a dungeon or with its map open: a route through its bosses)",
  "/agps instances on|off   (dungeon and raid entrances on the map)",
  "/agps caves on|off       (cave and mine entrances on the map)",
  "/agps herbs on|off | ore on|off | nodes on|off  (herbs, ore, or both on the map)",
  "/agps lock | unlock [map|arrow]  (both, or just one; unlocked they can be moved)",
  "/agps reset              (restore default position and settings)",
  "/agps roads on|off       (show the extracted road network)",
  "/agps dev                 (the Road Tools button on the map)",
  "/agps walltools           (the Wall Tools button on the map)",
  "/agps walls on|off        (show the walls routes go around)",
  "/agps draw [undo|list|delete <n>]  (road tools on/off: left-drag draws, right-drag erases, middle-drag pans)",
  "/agps minimap on|off     (minimap button)",
  "/agps debug              (API probe; see `agps probes`)",
}

local function OnOff(v, cur)
  if v == "on" then return true elseif v == "off" then return false end
  return not cur
end

local function Status()
  ns.Print(ns.GPS.Describe())
end

SLASH_AZEROTHGPS1 = "/agps"
SLASH_AZEROTHGPS2 = "/gps"
SlashCmdList.AZEROTHGPS = function(msg)
  local gps = ns.settings.gps
  local a, b = strsplit(" ", strtrim((msg or ""):lower()))
  local n = tonumber(b)
  if a == "" or a == "options" or a == "config" then
    ns.Options.Toggle()
    return
  elseif a == "show" or a == "hide" or a == "toggle" then
    gps.shown = (a == "show") or (a == "toggle" and not gps.shown)
  elseif a == "opacity" and n then
    gps.alpha = math.max(0.05, math.min(1, n / 100))
  elseif a == "size" and n then
    gps.size = math.max(120, math.min(800, math.floor(n)))
    if ns.GPS.ClampSize then gps.size = ns.GPS.ClampSize(gps.size) end -- room for the quick buttons
  elseif a == "zoom" and n then
    ns.GPS.SetZoom(n)
  elseif a == "rotate" then
    gps.rotate = OnOff(b, gps.rotate)
  elseif a == "style" and (b == "minimap" or b == "zone" or b == "nospoiler") then
    gps.style = b
  elseif a == "lock" or a == "unlock" then
    -- both, or just "map" / "arrow"
    local lock = a == "lock"
    if b ~= "arrow" then gps.locked = lock end
    if b ~= "map" then gps.arrowLocked = lock end
  elseif a == "minimap" then
    ns.settings.minimap.hide = not OnOff(b, not ns.settings.minimap.hide)
  elseif a == "import" then
    ns.Import.Toggle()
    return
  elseif a == "arrow" then
    gps.arrow = OnOff(b, gps.arrow)
  elseif a == "offroad" then
    gps.offroad = OnOff(b, gps.offroad)
  elseif a == "poi" then
    local key = ({ taxi = "poiTaxi", poi = "poiPoi", labels = "poiLabels" })[b]
    if key then gps[key] = OnOff(select(3, strsplit(" ", msg:lower())), gps[key]) end
  elseif a == "clear" then
    ns.Nav.Clear()
  elseif a == "quests" then
    gps.layerQuests = OnOff(b, gps.layerQuests)
  elseif a == "nodes" then
    local on = OnOff(b, gps.layerHerbs or gps.layerOre)
    gps.layerHerbs, gps.layerOre = on, on
  elseif a == "herbs" then
    gps.layerHerbs = OnOff(b, gps.layerHerbs)
  elseif a == "ore" then
    gps.layerOre = OnOff(b, gps.layerOre)
  elseif a == "bosses" then
    ns.GPS.BossRoute()
    return
  elseif a == "dungeonroute" then
    ns.GPS.SetDungeonRoute(b == "on" or (b ~= "off" and gps.dungeonRoute == false))
    return
  elseif a == "instances" then
    gps.layerInstances = OnOff(b, gps.layerInstances ~= false)
  elseif a == "caves" then
    gps.layerCaves = OnOff(b, gps.layerCaves ~= false)
  elseif a == "roads" then
    gps.showRoads = OnOff(b, gps.showRoads)
  elseif a == "walls" then
    gps.showWalls = OnOff(b, gps.showWalls)
  elseif a == "walltools" then
    gps.wallTools = not gps.wallTools
    ns.Print("the Wall Tools button on the map: " .. (gps.wallTools and "shown" or "hidden"))
    if not gps.wallTools and ns.GPS.wallMode then ns.GPS.SetWallMode(false) end
    if ns.GPS.LayoutQuick then ns.GPS.LayoutQuick() end
    return
  elseif a == "dev" then
    gps.devTools = not gps.devTools
    ns.Print("the Road Tools button on the map: " .. (gps.devTools and "shown" or "hidden"))
    if not gps.devTools and ns.GPS.roadMode then ns.GPS.SetRoadMode(false) end
    if ns.GPS.LayoutQuick then ns.GPS.LayoutQuick() end
    return
  elseif a == "draw" then
    if b == "undo" then
      ns.Record.Undo()
    elseif b == "list" then
      ns.Record.List()
    elseif b == "delete" then
      ns.Record.Delete(tonumber(select(3, strsplit(" ", msg))))
    else
      ns.GPS.ToggleRoadMode()
    end
    return
  elseif a == "reset" then
    ns.settings.gps = CopyTable(ns.DEFAULTS.gps)
  elseif a == "debug" then
    if b == "interior" then
      for _, l in ipairs(ns.GPS.DebugInterior()) do ns.Print(l) end
    elseif b == "perf" then
      for _, l in ipairs(ns.PerfReport()) do ns.Print(l) end
    elseif b == "dashes" then
      ns.GPS.dashTexture = not ns.GPS.dashTexture
      ns.Print("dotted route lines: " .. (ns.GPS.dashTexture and "textured (one line per leg)" or "a line per dash"))
      ns.GPS.Redraw()
    elseif b == "layers" then
      ns.Print(ns.Layers.Describe())
    elseif b == "rotsign" then
      ns.GPS.rotSign = -ns.GPS.rotSign
      ns.Print("tile rotation sign now " .. ns.GPS.rotSign)
    else
      ns.RunProbe("manual")
    end
    return
  elseif a == "status" then
    Status()
    return
  else
    for _, l in ipairs(HELP) do ns.Print(l) end
    return
  end
  ns.Options.Apply()
  Status()
end

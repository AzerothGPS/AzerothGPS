-- A stand-in for the game's UI for tests that run the addon's frames (test_map_redraw.py): every
-- frame, texture and font string is a widget taking any call. Setters do nothing (or remember what
-- a getter gives back), getters give numbers, strings or other widgets as the game's would.
-- Enough to run the map's setup and redraw; not a check of how anything looks.

AGPS_WIDGETS = {}
local M = {}
local WMT
local numeric = {
  GetWidth = 400, GetHeight = 400, GetEffectiveScale = 1, GetScale = 1, GetStringHeight = 12,
  GetStringWidth = 40, GetUnboundedStringWidth = 40, GetAlpha = 1, GetEffectiveAlpha = 1,
  GetFrameLevel = 5, GetLeft = 100, GetRight = 500, GetTop = 500, GetBottom = 100, GetNumPoints = 1,
  GetLineHeight = 12, GetValue = 0, GetID = 0, GetNumChildren = 0, GetVerticalScroll = 0,
  GetHorizontalScroll = 0, GetTextWidth = 40, GetTextHeight = 12, GetNumLines = 0, GetSpacing = 0,
  GetDrawLayer = 0, GetThickness = 2, GetVerticalScrollRange = 0, GetMaxLetters = 0, GetNumLetters = 0,
  GetCursorPosition = 0, GetDuration = 0, GetProgress = 0, GetElapsed = 0, GetOrder = 1, GetSmoothing = 0,
}

function NewWidget(kind, name, parent)
  local w = setmetatable({ _kind = kind or "Frame", _scripts = {}, _shown = true, _attr = {}, _events = {},
    _parent = parent, _name = name, _text = "" }, WMT)
  AGPS_WIDGETS[#AGPS_WIDGETS + 1] = w
  if name then _G[name] = w end
  return w
end

M.SetScript = function(s, n, f) s._scripts[n] = f end
M.GetScript = function(s, n) return s._scripts[n] end
M.HookScript = function(s, n, f)
  local o = s._scripts[n]
  s._scripts[n] = function(...)
    if o then o(...) end
    return f(...)
  end
end
M.HasScript = function() return true end
M.Show = function(s) s._shown = true end
M.Hide = function(s) s._shown = false end
M.SetShown = function(s, v) s._shown = v and true or false end
M.IsShown = function(s) return s._shown end
M.IsVisible = function(s) return s._shown end
M.RegisterEvent = function(s, e) s._events[e] = true end
M.RegisterUnitEvent = M.RegisterEvent
M.UnregisterEvent = function(s, e) s._events[e] = nil end
M.UnregisterAllEvents = function(s) s._events = {} end
M.IsEventRegistered = function(s, e) return s._events[e] or false end
M.SetText = function(s, t) s._text = t end
M.GetText = function(s) return s._text end
M.SetFormattedText = function(s, f, ...) s._text = string.format(f, ...) end
M.SetAttribute = function(s, k, v) s._attr[k] = v end
M.GetAttribute = function(s, k) return s._attr[k] end
M.GetParent = function(s) return s._parent or UIParent end
M.SetParent = function(s, p) s._parent = p end
M.GetName = function(s) return s._name end
M.GetObjectType = function(s) return s._kind end
M.IsObjectType = function(s, k) return s._kind == k end
M.GetCenter = function() return 300, 300 end
M.GetPoint = function() return "CENTER", nil, "CENTER", 0, 0 end
M.GetSize = function() return 400, 400 end
M.GetRect = function() return 100, 100, 400, 400 end
M.GetFrameStrata = function() return "MEDIUM" end
M.GetChecked = function(s) return s._checked or false end
M.SetChecked = function(s, v) s._checked = v end
-- The client asserts `flags.m_filter <= GxTex_Linear` and crashes on any filter mode above LINEAR
-- ("TRILINEAR" did, 1.60.1.70124, 2026-10-01): the stand-in fails the same way.
local function FilterOK(filter)
  if filter ~= nil and filter ~= "LINEAR" and filter ~= "NEAREST" then
    error("ASSERT(flags.m_filter <= GxTex_Linear): filter mode " .. tostring(filter) .. " crashes the client", 3)
  end
end
M.SetSize = function(s, w, h) s._w, s._h = w, h end -- (recorded; GetSize stays the stand-in's)
M.SetPoint = function(s, ...) s._pt = { ... } end -- (the last one)
M.SetTexture = function(s, t, _, _, filter) FilterOK(filter) s._tex, s._filter = t, filter end
M.SetAtlas = function(s, a, _, filter) FilterOK(filter) s._atlas, s._filter = a, filter end
M.GetTexture = function(s) return s._tex end
M.AddMaskTexture = function(s, m) s._masks = s._masks or {} s._masks[#s._masks + 1] = m end
M.SetColorTexture = function(s, r, g, b) s._tex = string.format("color:%.2f,%.2f,%.2f", r, g, b) end
M.GetFont = function() return "Fonts\\FRIZQT__.TTF", 12, "" end
M.GetTextColor = function() return 1, 1, 1, 1 end
M.GetVertexColor = function() return 1, 1, 1, 1 end
M.GetTexCoord = function() return 0, 0, 0, 1, 1, 0, 1, 1 end
M.GetStartPoint = function() return "CENTER", nil, 0, 0 end
M.GetEndPoint = function() return "CENTER", nil, 0, 0 end
M.GetMinMaxValues = function() return 0, 1 end
M.GetHitRectInsets = function() return 0, 0, 0, 0 end
M.GetClampRectInsets = function() return 0, 0, 0, 0 end
M.GetChildren = function() end
M.GetRegions = function() end
M.GetAnimationGroups = function() end
M.GetBackdropColor = function() return 0, 0, 0, 0 end
M.GetBackdropBorderColor = function() return 0, 0, 0, 0 end
M.GetBackdrop = function() return nil end
M.GetOwner = function(s) return s._owner end
M.SetOwner = function(s, o) s._owner = o end
M.GetUnit = function() return nil end
M.GetSpell = function() return nil end
M.GetItem = function() return nil end
M.NumLines = function() return 0 end
M.GetCursorPosition = function() return 0 end
M.GetJustifyH = function() return "LEFT" end
M.GetButtonState = function() return "NORMAL" end

local VERB = { "Set", "Get", "Is", "Can", "Create", "Enable", "Disable", "Register", "Unregister", "Show", "Hide",
  "Clear", "Start", "Stop", "Play", "Pause", "Raise", "Lower", "Add", "Remove", "Hook", "Lock", "Unlock", "Click",
  "Update", "Refresh", "Apply", "Scroll", "Adjust", "Reset", "Toggle", "Highlight", "Unhighlight", "Finish",
  "Restart", "Flash", "Stretch", "Fade", "Append", "Insert", "Execute", "Enable", "Has", "Num", "Wrap", "Intersects",
  "Rotate", "Load", "Save", "Cancel", "Run", "Fire" }

WMT = { __index = function(_, k)
  local m = M[k]
  if m then return m end
  if type(k) ~= "string" then return nil end
  local n = numeric[k]
  if n then return function() return n end end
  if k:match("^Create") then return function(s, ...) return NewWidget(k:sub(7), nil, s) end end
  if k:match("^Get") then return function(s) return NewWidget("child", nil, s) end end
  if k:match("^Is") or k:match("^Can") or k:match("^Has") then return function() return false end end
  for _, v in ipairs(VERB) do
    if k:sub(1, #v) == v then return function() end end
  end
  return nil -- (a field: the template's parts, the addon's own)
end }

function CreateFrame(kind, name, parent, template)
  local w = NewWidget(kind, name, parent)
  -- (a template's parts the addon reaches for)
  if template and template:find("ScrollFrame") then w.ScrollBar = NewWidget("Slider", nil, w) end
  return w
end
M.SetScrollChild = function(s, c) s._child = c end
M.GetScrollChild = function(s) return s._child end

-- Every script of `event` on every frame registered for it.
function AGPS_FIRE(event, ...)
  for _, w in ipairs(AGPS_WIDGETS) do
    if w._events[event] and w._scripts.OnEvent then w._scripts.OnEvent(w, event, ...) end
  end
end

UIParent = NewWidget("Frame", "UIParent")
WorldFrame = NewWidget("Frame", "WorldFrame")
Minimap = NewWidget("Minimap", "Minimap")
WorldMapFrame = NewWidget("Frame", "WorldMapFrame")
GameTooltip = NewWidget("GameTooltip", "GameTooltip")
UIErrorsFrame = NewWidget("MessageFrame", "UIErrorsFrame")
DEFAULT_CHAT_FRAME = NewWidget("ScrollingMessageFrame", "DEFAULT_CHAT_FRAME")
GameTooltip_Hide = function() end
UISpecialFrames = {}
SlashCmdList = {}
StaticPopupDialogs = {}
StaticPopup_Show = function() end
YES, NO, OKAY, CANCEL = "Yes", "No", "Okay", "Cancel"

AGPS_T = 100
GetTime = function() return AGPS_T end
debugprofilestop = function() return os.clock() * 1000 end
C_Timer = { After = function() end,
  NewTicker = function() return { Cancel = function() end } end,
  NewTimer = function() return { Cancel = function() end } end }
GetCursorPosition = function() return 0, 0 end
InCombatLockdown = function() return false end
IsShiftKeyDown = function() return false end
IsControlKeyDown = function() return false end
IsAltKeyDown = function() return false end
IsMouseButtonDown = function() return false end
GetFramerate = function() return 60 end
GetLocale = function() return "enUS" end
GetBuildInfo = function() return "1.60.1", "70124", "Sep 1 2026", 16001 end
GetRealmName = function() return "Realm" end
UnitName = function() return "Tester" end
UnitGUID = function() return "Player-1-00000001" end
UnitFactionGroup = function() return "Horde" end
UnitRace = function() return "Undead", "Scourge" end
UnitClass = function() return "Mage", "MAGE" end
UnitLevel = function() return AGPS_LEVEL or 14 end
UnitHealth = function() return 100 end
UnitHealthMax = function() return 100 end
UnitIsDeadOrGhost = function() return false end
UnitIsGhost = function() return false end
UnitOnTaxi = function() return false end
UnitAffectingCombat = function() return false end
UnitBuff = function() return nil end
UnitAura = function() return nil end
AGPS_POS = { 2254.0, 293.0, 0 } -- world x, y, continent (Brill)
UnitPosition = function() return AGPS_POS[1], AGPS_POS[2], AGPS_POS[4] or 0, AGPS_POS[3] end -- (4: the height, when set)
GetPlayerFacing = function() return 0 end
GetUnitSpeed = function() return 0, 7, 7, 4.7 end
IsMounted = function() return false end
IsFlying = function() return false end
IsSwimming = function() return false end
IsIndoors = function() return false end
IsResting = function() return false end
IsInInstance = function() return false, "none" end
GetInstanceInfo = function() return "Eastern Kingdoms", "none", 0, "", 5, 0, false, 0, 0 end
GetZoneText = function() return "Tirisfal Glades" end
GetRealZoneText = GetZoneText
GetSubZoneText = function() return "Brill" end
GetMinimapZoneText = function() return "Brill" end
GetBindLocation = function() return "Gallows' End Tavern" end
GetItemCount = function() return 0 end
GetItemCooldown = function() return 0, 0, 1 end
GetItemInfo = function() return nil end
GetItemIcon = function() return 134400 end
GetSpellCooldown = function() return 0, 0, 1 end
IsPlayerSpell = function() return false end
IsSpellKnown = function() return false end
GetSpellTexture = function() return 134400 end
GetNumSkillLines = function() return 0 end
PlaySound = function() end
PlaySoundFile = function() end
hooksecurefunc = function() end
SetOverrideBindingClick = function() end
ClearOverrideBindings = function() end
GetBindingKey = function() return nil end
SetBinding = function() end
SaveBindings = function() end
GetCurrentBindingSet = function() return 1 end
issecretvalue = nil
securecall = function(f, ...) return f(...) end
GetAddOnMetadata = function() return "1.0.8" end
C_AddOns = { GetAddOnMetadata = GetAddOnMetadata, IsAddOnLoaded = function() return false end }
IsAddOnLoaded = function() return false end
C_ChatInfo = { RegisterAddonMessagePrefix = function() return true end, SendAddonMessage = function() end }
RegisterAddonMessagePrefix = C_ChatInfo.RegisterAddonMessagePrefix
C_Container = { GetItemCooldown = function() return 0, 0, 1 end }
C_Spell = nil
C_TaxiMap = { GetAllTaxiNodes = function() return {} end, GetTaxiNodesForMap = function() return {} end }
NumTaxiNodes = function() return 0 end
C_QuestLog = { GetNumQuestLogEntries = function() return 0 end, GetInfo = function() return nil end,
  GetQuestsOnMap = function() return {} end, GetQuestObjectives = function() return {} end,
  IsComplete = function() return false end, GetLogIndexForQuestID = function() return nil end }
GetNumQuestLogEntries = function() return 0 end
C_QuestLine = { RequestQuestLinesForMap = function() end, GetAvailableQuestLines = function() return {} end }
C_Minimap = { IsInsideQuestBlob = function() return false end }
C_GossipInfo = { GetPoiForUiMapID = function() return nil end }
C_DeathInfo = { GetCorpseMapPosition = function() return nil end }
C_MapExplorationInfo = { GetExploredMapTextures = function() return {} end }
Enum = setmetatable({}, { __index = function() return setmetatable({}, { __index = function() return 0 end }) end })

-- The map API: the player in Tirisfal Glades, the continent's map for world coordinates.
C_Map = {
  GetBestMapForUnit = function() return AGPS_MAP or 1420 end,
  GetPlayerMapPosition = function() return { GetXY = function() return 0.6, 0.5 end } end,
  GetMapInfo = function(id)
    local m = AGPS_NS and AGPS_NS.Maps and AGPS_NS.Maps[id]
    return m and { mapID = id, name = m.name, mapType = m.type, parentMapID = m.parent } or nil
  end,
  GetMapLevels = function() return nil end,
  GetMapArtID = function() return nil end,
  GetMapGroupID = function() return nil end,
  GetMapChildrenInfo = function() return {} end,
  GetMapArtLayers = function() return {} end,
  GetMapArtLayerTextures = function() return {} end,
  GetMapInfoAtPosition = function() return nil end,
  GetWorldPosFromMapPos = function() return nil end,
  GetMapWorldSize = function() return 0, 0 end,
}

CopyTable = function(t)
  local o = {}
  for k, v in pairs(t) do o[k] = type(v) == "table" and CopyTable(v) or v end
  return o
end
tostringall = function(...)
  local out = {}
  for i = 1, select("#", ...) do out[i] = tostring((select(i, ...))) end
  return unpack(out, 1, select("#", ...))
end
-- (the icons a macro can have: the game fills the table it's given with file ids)
GetMacroIcons = function(t) for i = 1, 30 do t[#t + 1] = 136000 + i end end
GetMacroItemIcons = function(t) for i = 1, 25 do t[#t + 1] = 133000 + i end end

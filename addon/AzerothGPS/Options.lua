-- Options window, minimap button, and the entry in the game's AddOns options.
local _, ns = ...

local O = {}
ns.Options = O

local window
local controls = {} -- refresh functions, run when the window opens or settings change

local function GPS() return ns.settings.gps end

local function Apply()
  ns.GPS.ApplySettings()
  if ns.Arrow then ns.Arrow.Apply() end
  if O.button then O.UpdateButton() end
  for _, refresh in ipairs(controls) do refresh() end
end
O.Apply = Apply
-- refresh the window's controls (a setting changed elsewhere, e.g. a quick button)
function O.Refresh()
  for _, refresh in ipairs(controls) do refresh() end
end

---------------------------------------------------------------------------
-- Widgets (built from basic textures so they work on any client version)
---------------------------------------------------------------------------

local function Checkbox(parent, label, tooltip, get, set)
  local cb = CreateFrame("CheckButton", nil, parent, "UICheckButtonTemplate")
  cb:SetSize(24, 24)
  local text = cb:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  text:SetPoint("LEFT", cb, "RIGHT", 2, 0)
  text:SetText(label)
  cb:SetScript("OnClick", function(self)
    set(self:GetChecked() and true or false)
    Apply()
  end)
  if tooltip then
    cb:SetScript("OnEnter", function(self)
      GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
      GameTooltip:SetText(label, 1, 1, 1)
      GameTooltip:AddLine(tooltip, nil, nil, nil, true)
      GameTooltip:Show()
    end)
    cb:SetScript("OnLeave", GameTooltip_Hide)
  end
  controls[#controls + 1] = function() cb:SetChecked(get()) end
  return cb
end

-- The key that shows and hides the map (Bindings.xml): click, then press a key (with
-- Shift/Ctrl/Alt if wanted); Escape cancels, right-click clears it. Saved like any other
-- key binding (also in the game's Key Bindings, under AddOns). Not in combat: the game
-- doesn't allow changing key bindings then.
O.BINDING = "AZEROTHGPS_TOGGLE"
local MODIFIER_KEYS = { LSHIFT = true, RSHIFT = true, LCTRL = true, RCTRL = true, LALT = true, RALT = true,
  LMETA = true, RMETA = true, UNKNOWN = true }

local function SaveKeys()
  if SaveBindings then SaveBindings(GetCurrentBindingSet and GetCurrentBindingSet() or 1) end
end

local function KeyBind(parent, label)
  local holder = CreateFrame("Frame", nil, parent)
  holder:SetSize(360, 26)
  local text = holder:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  text:SetPoint("LEFT", 4, 0)
  text:SetText(label)
  local b = CreateFrame("Button", nil, holder, "UIPanelButtonTemplate")
  b:SetSize(130, 22)
  b:SetPoint("LEFT", text, "RIGHT", 10, 0)
  local msg = holder:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  msg:SetPoint("LEFT", b, "RIGHT", 8, 0)
  local waiting = false
  local function Refresh()
    local key = GetBindingKey and GetBindingKey(O.BINDING)
    b:SetText(waiting and "Press a key..." or (key and (GetBindingText and GetBindingText(key) or key) or "Not bound"))
  end
  local function Stop()
    waiting = false
    b:EnableKeyboard(false)
    Refresh()
  end
  b:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  b:SetScript("OnClick", function(_, button)
    msg:SetText("")
    if InCombatLockdown and InCombatLockdown() then
      msg:SetText("|cffff6060Not in combat.|r")
      return
    end
    if button == "RightButton" then
      local key = GetBindingKey and GetBindingKey(O.BINDING)
      while key do
        SetBinding(key)
        key = GetBindingKey(O.BINDING)
      end
      SaveKeys()
      Stop()
      return
    end
    waiting = not waiting
    b:EnableKeyboard(waiting)
    Refresh()
  end)
  b:SetScript("OnKeyDown", function(self, key)
    if not waiting then return end
    if key == "ESCAPE" then Stop() return end
    if MODIFIER_KEYS[key] then return end -- wait for the key itself
    if InCombatLockdown and InCombatLockdown() then Stop() return end
    local full = (IsAltKeyDown() and "ALT-" or "") .. (IsControlKeyDown() and "CTRL-" or "")
      .. (IsShiftKeyDown() and "SHIFT-" or "") .. key
    local before = GetBindingAction and GetBindingAction(full)
    local old = GetBindingKey and GetBindingKey(O.BINDING)
    while old do -- one key for it
      SetBinding(old)
      old = GetBindingKey(O.BINDING)
    end
    if SetBinding(full, O.BINDING) then
      SaveKeys()
      if before and before ~= "" and before ~= O.BINDING then
        msg:SetText("Was: " .. (GetBindingName and GetBindingName(before) or before))
      end
    else
      msg:SetText("|cffff6060That key can't be used.|r")
    end
    Stop()
  end)
  b:SetScript("OnHide", function() if waiting then Stop() end end)
  -- setting OnKeyDown turns keyboard capture on: off until it's waiting for a key, or
  -- the character can't be moved while this page shows
  b:EnableKeyboard(false)
  b:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText(label, 1, 1, 1)
    GameTooltip:AddLine("Click, then press a key (Shift, Ctrl or Alt with it if you like). The same key shows and hides the map. Escape cancels, right-click clears it. Also in the game's Key Bindings, under AddOns.", nil, nil, nil, true)
    GameTooltip:Show()
  end)
  b:SetScript("OnLeave", GameTooltip_Hide)
  controls[#controls + 1] = Refresh
  return holder
end

-- `enabled` (optional): a function; the slider is grayed out while it returns false.
local function Slider(parent, label, minV, maxV, step, fmt, get, set, enabled)
  local holder = CreateFrame("Frame", nil, parent)
  holder:SetSize(260, 40)
  local title = holder:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  title:SetPoint("TOPLEFT")
  title:SetText(label)
  local value = holder:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  value:SetPoint("TOPRIGHT")

  local s = CreateFrame("Slider", nil, holder, "BackdropTemplate")
  s:SetOrientation("HORIZONTAL")
  s:SetPoint("TOPLEFT", 0, -16)
  s:SetPoint("TOPRIGHT", 0, -16)
  s:SetHeight(16)
  s:SetBackdrop({
    bgFile = "Interface\\Buttons\\UI-SliderBar-Background",
    edgeFile = "Interface\\Buttons\\UI-SliderBar-Border",
    tile = true, tileSize = 8, edgeSize = 8,
    insets = { left = 3, right = 3, top = 6, bottom = 6 },
  })
  s:SetThumbTexture("Interface\\Buttons\\UI-SliderBar-Button-Horizontal")
  s:SetMinMaxValues(minV, maxV)
  s:SetValueStep(step)
  s:SetObeyStepOnDrag(true)
  local updating = false
  s:SetScript("OnValueChanged", function(_, v)
    value:SetText(fmt:format(v))
    if updating then return end
    set(v)
    Apply() -- other controls may follow this one (e.g. combat opacity follows opacity)
  end)
  s:EnableMouseWheel(true)
  s:SetScript("OnMouseWheel", function(self, d)
    if self:IsEnabled() then self:SetValue(self:GetValue() + d * step) end
  end)
  controls[#controls + 1] = function()
    updating = true
    s:SetValue(get())
    value:SetText(fmt:format(get()))
    updating = false
    local on = not enabled or enabled()
    if on then s:Enable() else s:Disable() end
    s:SetAlpha(on and 1 or 0.4)
    title:SetFontObject(on and "GameFontNormalSmall" or "GameFontDisableSmall")
    value:SetFontObject(on and "GameFontHighlightSmall" or "GameFontDisableSmall")
  end
  return holder
end

local function Button(parent, label, width, onClick)
  local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
  b:SetSize(width, 22)
  b:SetText(label)
  b:SetScript("OnClick", function() onClick(); Apply() end)
  return b
end

---------------------------------------------------------------------------
-- Window
---------------------------------------------------------------------------

-- "How to share": what's kept, where, and how to send it (a GitHub issue with the road
-- data pasted in, `agps import-shared --github` reads them; or the AzerothGPS Discord).
O.SHARE_URL = "https://github.com/AzerothGPS/AzerothGPS/issues/new?template=road-data.yml"
O.DISCORD_URL = "https://discord.gg/gktYHzs2c"
O.SHARE_INFO = {
  "|cffffd100What is kept|r",
  "Roads and walls you draw or erase with the road tools (and, if you turn it on, the way you went when you reached a stop clearly faster than estimated). Positions only: no character or realm names.",
  " ",
  "|cffffd100Where it is kept|r",
  "On your PC, in this addon's saved variables (WTF\\Account\\<account>\\SavedVariables\\AzerothGPS.lua). Addons can't send anything from the game.",
  " ",
  "|cffffd100How to share your roads and walls|r",
  "1. Type |cffffd100/reload|r (it saves all your edits, so every one is copied), then click |cffffd100Copy Map Data...|r and press |cffffd100Ctrl+C|r.",
  "2. Paste it in either place (click an address below, Ctrl+C, and open it in your browser):",
  "    |cffffd100GitHub|r: the first address opens a new \"Road data\" issue.",
  "    |cffffd100Discord|r: the second is the AzerothGPS Discord.",
  "3. Name the zone and say what you fixed.",
  " ",
  "Roads and walls that check out are added in a later version, for everyone.",
}

local shareInfo
-- Your drawn roads as text, selected, to copy (Ctrl+C) and send.
local roadsCopy
local function ShowRoadsText()
  local text, n = ns.Feedback.RoadsText()
  if n == 0 then
    ns.Print("no drawn or erased roads to share yet (Road Tools: left-drag draws, right-drag erases)")
    return
  end
  if not roadsCopy then
    local f = CreateFrame("Frame", "AzerothGPSRoadsCopy", UIParent, "BackdropTemplate")
    f:SetSize(460, 320)
    f:SetPoint("CENTER")
    f:SetFrameStrata("FULLSCREEN_DIALOG")
    f:SetToplevel(true)
    f:SetClampedToScreen(true)
    f:EnableMouse(true)
    f:SetMovable(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
    f:SetBackdropColor(0.06, 0.06, 0.07, 1) -- (solid: nothing behind shows through)
    f:SetBackdropBorderColor(0.3, 0.3, 0.3, 1)
    tinsert(UISpecialFrames, "AzerothGPSRoadsCopy")
    local title = f:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
    title:SetPoint("TOP", 0, -12)
    title:SetText("Your map data")
    local close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
    close:SetScript("OnClick", function() f:Hide() end)
    close:SetPoint("TOPRIGHT", 2, 2)
    local hint = f:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
    hint:SetPoint("TOPLEFT", 14, -38)
    hint:SetPoint("RIGHT", -14, 0)
    hint:SetJustifyH("LEFT")
    f.hint = hint
    local scroll = CreateFrame("ScrollFrame", "AzerothGPSRoadsCopyScroll", f, "UIPanelScrollFrameTemplate")
    scroll:SetPoint("TOPLEFT", 14, -64)
    scroll:SetPoint("BOTTOMRIGHT", -34, 14)
    local bg = f:CreateTexture(nil, "BACKGROUND", nil, 1)
    bg:SetPoint("TOPLEFT", scroll, -4, 4)
    bg:SetPoint("BOTTOMRIGHT", scroll, 4, -4)
    bg:SetColorTexture(0, 0, 0, 1)
    local edit = CreateFrame("EditBox", nil, scroll)
    edit:SetMultiLine(true)
    edit:SetAutoFocus(false)
    edit:SetFontObject(ChatFontNormal)
    edit:SetWidth(400)
    edit:SetScript("OnEscapePressed", function() f:Hide() end)
    -- (read only: typing puts the text back; a click selects it all again)
    edit:SetScript("OnTextChanged", function(self, user)
      if user then
        self:SetText(f.text or "")
        self:HighlightText()
      end
    end)
    edit:SetScript("OnMouseUp", function(self) self:HighlightText() end)
    scroll:SetScrollChild(edit)
    scroll:SetScript("OnMouseDown", function() edit:SetFocus() end)
    f.edit = edit
    roadsCopy = f
  end
  if shareInfo then shareInfo:Hide() end -- (one window at a time: it was on top of this one)
  roadsCopy.text = text
  roadsCopy.hint:SetText(string.format("%d change%s you drew (roads, walls, erasures). Press |cffffd100Ctrl+C|r to copy (it's all selected), then paste it in a \"Road data\" GitHub issue or on the AzerothGPS Discord (see How to share). Missing an edit? Type |cffffd100/reload|r and copy again.",
    n, n == 1 and "" or "s"))
  roadsCopy.edit:SetText(text)
  roadsCopy:Show()
  roadsCopy:Raise()
  roadsCopy.edit:SetFocus()
  roadsCopy.edit:HighlightText()
end
O.ShowRoadsText = ShowRoadsText

local function ShowShareInfo()
  if not shareInfo then
    local f = CreateFrame("Frame", "AzerothGPSShareInfo", UIParent, "BackdropTemplate")
    f:SetSize(380, 260)
    f:SetPoint("CENTER")
    f:SetFrameStrata("FULLSCREEN_DIALOG")
    f:SetClampedToScreen(true)
    f:EnableMouse(true)
    f:SetMovable(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
    f:SetBackdropColor(0.06, 0.06, 0.07, 1)
    f:SetBackdropBorderColor(0.3, 0.3, 0.3, 1)
    tinsert(UISpecialFrames, "AzerothGPSShareInfo")
    local title = f:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
    title:SetPoint("TOP", 0, -12)
    title:SetText("Sharing road and trip data")
    local close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
    close:SetScript("OnClick", function() f:Hide() end) -- works in combat too
    close:SetPoint("TOPRIGHT", 2, 2)
    local text = f:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
    text:SetPoint("TOPLEFT", 16, -42)
    text:SetPoint("RIGHT", -16, 0)
    text:SetJustifyH("LEFT")
    text:SetSpacing(2)
    f.text = text
    -- the addresses, to copy (the game can't open links): selected when clicked, not editable
    local function Address(value, below, gap)
      local url = CreateFrame("EditBox", nil, f, "InputBoxTemplate")
      url:SetHeight(20)
      url:SetPoint("TOPLEFT", below, "BOTTOMLEFT", gap, -8)
      url:SetPoint("RIGHT", -16, 0)
      url:SetAutoFocus(false)
      url:SetScript("OnEditFocusGained", function(self) self:HighlightText() end)
      url:SetScript("OnMouseUp", function(self) self:HighlightText() end)
      url:SetScript("OnTextChanged", function(self, user)
        if user then
          self:SetText(value)
          self:HighlightText()
        end
      end)
      url:SetScript("OnEscapePressed", function() f:Hide() end)
      return url
    end
    f.url = Address(O.SHARE_URL, text, 6)
    f.discord = Address(O.DISCORD_URL, f.url, 0)
    local copy = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
    copy:SetSize(150, 22)
    copy:SetPoint("TOPLEFT", f.discord, "BOTTOMLEFT", -6, -8)
    copy:SetText("Copy Map Data...")
    copy:SetScript("OnClick", function() O.ShowRoadsText() end)
    shareInfo = f
  end
  shareInfo.text:SetText(table.concat(O.SHARE_INFO, "\n"))
  shareInfo.url:SetText(O.SHARE_URL)
  shareInfo.url:SetCursorPosition(0)
  shareInfo.discord:SetText(O.DISCORD_URL)
  shareInfo.discord:SetCursorPosition(0)
  shareInfo:SetHeight(shareInfo.text:GetStringHeight() + 64 + 92)
  shareInfo:Show()
end
O.ShowShareInfo = ShowShareInfo

-- Stops routed ahead (the Performance page): the trip worked out again with it.
function O.SetStopsAhead(v)
  GPS().stopsAhead = v
  ns.Nav.Invalidate(true)
  if ns.GPS and ns.GPS.Redraw then ns.GPS.Redraw() end
end

-- Options > Performance. "Use Low-End Settings" sets these; "Restore Defaults" puts them back.
O.PERF_KEYS = { "hz", "rerouteSeconds", "stopsAhead", "gentleBackground", "arrowHz" }
O.LOW_END = { hz = 10, rerouteSeconds = 6, stopsAhead = 1, gentleBackground = true, arrowHz = 20 }
local function SetPerf(values)
  local before = GPS().stopsAhead
  for _, k in ipairs(O.PERF_KEYS) do GPS()[k] = values[k] end
  if GPS().stopsAhead ~= before then O.SetStopsAhead(GPS().stopsAhead) end
end
function O.UseLowEnd() SetPerf(O.LOW_END) end
function O.PerfDefaults() SetPerf(ns.DEFAULTS.gps) end
function O.IsLowEnd()
  for _, k in ipairs(O.PERF_KEYS) do
    if GPS()[k] ~= O.LOW_END[k] then return false end
  end
  return true
end
-- The addon's share of the time, from its work (ms) over `secs` seconds of play.
function O.UsageText(ms, secs)
  if not ms or not secs or secs <= 0 then return "AzerothGPS's work: measuring..." end
  local perSec = math.max(0, ms / secs)
  return string.format("AzerothGPS's work: %.1f ms a second, %.1f%% of the time", perSec, perSec / 10)
end

-- The options window, laid out like the game's Settings: categories on the left, one page
-- of settings at a time on the right. New settings go on the page they belong to (or a new
-- page: one more entry in the list).
local PAGE_W, LIST_W = 440, 150
local currentPage = 1

local function BuildWindow()
  local ok, f = pcall(CreateFrame, "Frame", "AzerothGPSOptions", UIParent, "PortraitFrameTemplate")
  local framed = ok and f and f.NineSlice
  if framed then
    -- the game's metal window frame, the AzerothGPS logo in its round portrait
    if f.SetTitle then f:SetTitle("AzerothGPS Options")
    elseif f.TitleContainer and f.TitleContainer.TitleText then f.TitleContainer.TitleText:SetText("AzerothGPS Options") end
    ns.SetLogoPortrait(f)
    -- close with a plain Hide: the template's own close goes through the game's panel
    -- manager, which can refuse during combat
    if f.CloseButton then f.CloseButton:SetScript("OnClick", function() f:Hide() end) end
  else
    f = CreateFrame("Frame", "AzerothGPSOptions", UIParent, "BackdropTemplate")
    f:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
    f:SetBackdropColor(0.06, 0.06, 0.07, 0.95)
    f:SetBackdropBorderColor(0.3, 0.3, 0.3, 1)
    local title = f:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
    title:SetPoint("TOP", 0, -8)
    title:SetText("AzerothGPS Options")
    local close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
    close:SetScript("OnClick", function() f:Hide() end) -- works in combat too
    close:SetPoint("TOPRIGHT", 2, 2)
  end
  f:SetSize(LIST_W + PAGE_W + 36, 560)
  f:SetPoint("CENTER")
  f:SetFrameStrata("DIALOG")
  f:SetClampedToScreen(true)
  f:SetMovable(true)
  f:EnableMouse(true)
  f:RegisterForDrag("LeftButton")
  f:SetScript("OnDragStart", f.StartMoving)
  f:SetScript("OnDragStop", f.StopMovingOrSizing)
  tinsert(UISpecialFrames, "AzerothGPSOptions") -- Escape closes it

  -- category list (left) and page area (right)
  local list = CreateFrame("Frame", nil, f, "BackdropTemplate")
  list:SetPoint("TOPLEFT", 10, framed and -62 or -30) -- below the portrait
  list:SetPoint("BOTTOMLEFT", 10, 44)
  list:SetWidth(LIST_W)
  list:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8" })
  list:SetBackdropColor(0, 0, 0, 0.35)
  local area = CreateFrame("Frame", nil, f, "BackdropTemplate")
  area:SetPoint("TOPLEFT", LIST_W + 18, -30)
  area:SetPoint("BOTTOMRIGHT", -10, 44)
  area:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8" })
  area:SetBackdropColor(0, 0, 0, 0.2)

  local pages, tabs = {}, {}
  local function ShowPage(n)
    currentPage = n
    for i, pg in ipairs(pages) do
      pg:SetShown(i == n)
      if i == n and pg.ScrollBar then -- a scroll bar only when the page is longer than the window
        local child = pg:GetScrollChild()
        pg.ScrollBar:SetShown(child and child:GetHeight() > pg:GetHeight() + 1)
        if not pg.ScrollBar:IsShown() then pg:SetVerticalScroll(0) end
      end
    end
    for i, t in ipairs(tabs) do
      t.selected:SetShown(i == n)
      t.text:SetFontObject(i == n and "GameFontHighlight" or "GameFontNormal")
    end
  end

  -- A page: its category button, and a layout that fills it top to bottom.
  local page, col
  -- (the page before gets its height, for scrolling)
  local function FinishPage()
    if page and col then page:SetHeight(math.max(10, -col.y + 16)) end
  end
  local function Page(name)
    FinishPage()
    local sf = CreateFrame("ScrollFrame", nil, area, "UIPanelScrollFrameTemplate")
    sf:SetPoint("TOPLEFT", area, "TOPLEFT", 0, -2)
    sf:SetPoint("BOTTOMRIGHT", area, "BOTTOMRIGHT", -26, 4)
    sf:Hide()
    page = CreateFrame("Frame", nil, sf)
    page:SetSize(PAGE_W - 26, 10)
    sf:SetScrollChild(page)
    local n = #pages + 1
    pages[n] = sf
    local t = CreateFrame("Button", nil, list)
    t:SetSize(LIST_W - 8, 24)
    t:SetPoint("TOPLEFT", 4, -6 - (n - 1) * 26)
    t.selected = t:CreateTexture(nil, "BACKGROUND")
    t.selected:SetAllPoints()
    t.selected:SetColorTexture(1, 0.82, 0, 0.18)
    local hl = t:CreateTexture(nil, "HIGHLIGHT")
    hl:SetAllPoints()
    hl:SetColorTexture(1, 1, 1, 0.08)
    t.text = t:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    t.text:SetPoint("LEFT", 10, 0)
    t.text:SetText(name)
    t:SetScript("OnClick", function() ShowPage(n) end)
    tabs[n] = t
    local title = page:CreateFontString(nil, "ARTWORK", "GameFontHighlightLarge")
    title:SetPoint("TOPLEFT", 16, -12)
    title:SetText(name)
    col = { x = 16, y = -44 }
  end
  local function place(w, h, indent)
    w:SetPoint("TOPLEFT", col.x + (indent or 0), col.y)
    col.y = col.y - (h or 26)
  end
  local function header(text, note)
    if col.y < -44 then col.y = col.y - 10 end -- space above a new section
    local fs = page:CreateFontString(nil, "ARTWORK", "GameFontNormal")
    fs:SetText(text)
    place(fs, 18)
    local line = page:CreateTexture(nil, "ARTWORK")
    line:SetColorTexture(1, 0.82, 0, 0.25)
    line:SetHeight(1)
    line:SetPoint("TOPLEFT", fs, "BOTTOMLEFT", 0, -2)
    line:SetWidth(PAGE_W - 40)
    if note then
      local nt = page:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
      nt:SetText(note)
      place(nt, 16, 4)
    end
    col.y = col.y - 2
  end
  local function note(text)
    local nt = page:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
    nt:SetWidth(PAGE_W - 48)
    nt:SetJustifyH("LEFT")
    nt:SetText(text)
    place(nt, nt:GetStringHeight() + 8, 4)
  end
  local function check(label, tip, get, set)
    place(Checkbox(page, label, tip, get, set))
  end
  local function slider(...)
    place(Slider(page, ...), 44)
  end

  ---------------------------------------------------------------- General
  Page("General")
  header("Map window")
  check("Show the map", "The GPS map window. Also: left-click the minimap button, a key (at the end of this section), or /agps toggle.",
    function() return GPS().shown end, function(v) GPS().shown = v end)
  check("Lock map position", "Locks the map in place. Unlocked: drag the window frame's title bar (or the Move tab without the frame, or Shift+drag the map) to move it.",
    function() return GPS().locked end, function(v) GPS().locked = v end)
  check("Window frame", "The game-style window frame around the map: title bar, logo and close button. Off: just the map.",
    function() return GPS().windowFrame ~= false end, function(v) GPS().windowFrame = v end)
  check("Reopen following me", "With a route set: if you hid the map while looking around it (dragged or zoomed out to the world map), it opens again centered on you, following your position. Off: it opens where you left it (the button at the bottom right brings it back to you).",
    function() return GPS().reopenFollow end, function(v) GPS().reopenFollow = v end)
  check("Zoom in near a stop", "Within 50 yards of your next stop, the map zooms in smoothly so you can see exactly where it is, and back out to your zoom once you're there. Zooming yourself keeps your zoom for that stop.",
    function() return GPS().approachZoom ~= false end, function(v) GPS().approachZoom = v end)
  check("Turn the map with me", "On: the map turns so that where you face is up (heading-up). Off: north stays up and the arrow turns.",
    function() return GPS().rotate end, function(v) GPS().rotate = v end)
  local sizeWarn
  slider("Size", 120, 800, 10, "%d", function() return GPS().size end, function(v)
    local nv = ns.GPS.ClampSize and ns.GPS.ClampSize(v, true) or v -- not too small for the quick buttons
    GPS().size = nv
    if nv > v then
      sizeWarn:SetText(string.format("|cffff4040Can't be smaller than %d with your quick buttons: move some to the menu or hide them (Quick buttons page).|r", nv))
      local shown = sizeWarn:GetText()
      C_Timer.After(6, function() if sizeWarn:GetText() == shown then sizeWarn:SetText("") end end)
    end
  end)
  sizeWarn = page:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  sizeWarn:SetWidth(PAGE_W - 60)
  sizeWarn:SetJustifyH("LEFT")
  place(sizeWarn, 26, 4)
  place(KeyBind(page, "Show/hide key"))
  note("Click the button, then press the key you want (with Shift, Ctrl or Alt if you like). Pressing it shows the map, and pressing it again hides it. Escape cancels, right-click the button to clear the key. It's also in the game's Key Bindings, under AddOns: \"Show/Hide AzerothGPS\". Keys can't be changed in combat.")
  header("Minimap")
  check("Minimap button", "The AzerothGPS button on the game's minimap. Without it, /agps opens this window.",
    function() return not ns.settings.minimap.hide end, function(v) ns.settings.minimap.hide = not v end)

  ---------------------------------------------------------------- Performance
  Page("Performance")
  header("Lighter settings", "For a slower PC: the same routes, worked out and drawn less often.")
  -- the addon's work over the last few seconds, while this page is open
  local usage = page:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
  place(usage, 20, 4)
  local ticker = CreateFrame("Frame", nil, page)
  local lastMs, lastT, wait = nil, nil, 0
  ticker:SetScript("OnShow", function() lastMs, lastT, wait = nil, nil, 0 usage:SetText(O.UsageText()) end)
  ticker:SetScript("OnUpdate", function(_, dt)
    wait = wait - dt
    if wait > 0 then return end
    wait = 2
    local ms, t = ns.PerfTotal(), GetTime()
    if lastMs and ms >= lastMs then usage:SetText(O.UsageText(ms - lastMs, t - lastT)) end
    lastMs, lastT = ms, t
  end)
  local lowBtn = Button(page, "Use Low-End Settings", 170, O.UseLowEnd)
  place(lowBtn, 30, 4)
  local defBtn = Button(page, "Restore Defaults", 140, O.PerfDefaults)
  defBtn:SetPoint("LEFT", lowBtn, "RIGHT", 6, 0)
  controls[#controls + 1] = function() lowBtn:SetEnabled(not O.IsLowEnd()) end
  header("Map")
  slider("Map redraws per second", 5, 30, 1, "%d", function() return GPS().hz or 20 end, function(v) GPS().hz = v end)
  note("The setting that saves the most: at 10 the map needs about half the work it does at 20, and still follows you smoothly. Standing still, it only redraws when something changes.")
  header("Routes")
  slider("Work out a route you've left at most every", 2, 10, 1, "%d s", function() return GPS().rerouteSeconds or 2 end,
    function(v) GPS().rerouteSeconds = v end)
  note("Off the route (fighting, gathering, or going your own way), it's worked out again from where you are. Less often is less work; the route catches up with you a little later.")
  slider("Stops routed and drawn ahead", 1, 8, 1, "%d", function() return GPS().stopsAhead or 3 end, O.SetStopsAhead)
  note("How many of the route's stops are worked out and drawn at a time; the next come in as you reach them. Every stop is still in the fastest order and on the map, and the ones further on are listed with an estimated distance until they're routed.")
  check("Gentle background work", "Walks around obstacles and the road data (after a /reload) are worked out in smaller slices of each frame: fewer stutters on a slow PC. The first route after a /reload, and walks off the roads, take a little longer to appear.",
    function() return GPS().gentleBackground end, function(v) GPS().gentleBackground = v end)
  header("Direction arrow")
  check("Turn the arrow every frame", "On: the arrow turns with every frame, as smoothly as the game runs. Off: 20 times a second, less work at high frame rates.",
    function() return (GPS().arrowHz or 0) == 0 end, function(v) GPS().arrowHz = v and 0 or 20 end)
  header("Other settings to improve performance")
  note("Fewer icons on the map (Map > Show on the map, or the round button at the map's bottom-left): herbs, ore, quests and points of interest; quest areas' outlines off; and a smaller map.")

  ---------------------------------------------------------------- Opacity
  Page("Opacity")
  header("Map")
  slider("Map opacity", 5, 100, 5, "%d%%",
    function() return math.floor(GPS().alpha * 100 + 0.5) end, function(v) GPS().alpha = v / 100 end)
  check("Fade the map while moving", "While you move, the map fades to the opacity below, leaving the route, the stop markers and your arrow as they are. It comes back a moment after you stop, or right away when you point at the map.",
    function() return GPS().fadeMoving end, function(v) GPS().fadeMoving = v end)
  slider("Map opacity while moving", 0, 100, 5, "%d%%",
    function() return math.floor((GPS().movingAlpha or 0.4) * 100 + 0.5) end, function(v) GPS().movingAlpha = v / 100 end,
    function() return GPS().fadeMoving end)
  header("Click-through", "Clicks go to the game world (targeting, the camera), not the map or arrow.")
  check("Click-through while moving", "While you move, the map and the direction arrow ignore the mouse, so a click there targets or turns the camera instead. They take clicks again a moment after you stop.",
    function() return GPS().clickThroughMoving end, function(v) GPS().clickThroughMoving = v end)
  check("Click-through in combat", "In combat, the map and the direction arrow ignore the mouse, so a click there targets or turns the camera instead.",
    function() return GPS().clickThroughCombat end, function(v) GPS().clickThroughCombat = v end)
  header("In combat")
  check("Hide the map", "Hidden while you're in combat, so nothing on it gets clicked by mistake mid-fight. It comes back when combat ends.",
    function() return GPS().combatHideMap end, function(v) GPS().combatHideMap = v end)
  slider("Map opacity in combat", 0, 100, 5, "%d%%",
    function() return math.floor((GPS().combatAlpha or GPS().alpha) * 100 + 0.5) end, function(v) GPS().combatAlpha = v / 100 end,
    function() return not GPS().combatHideMap end)
  check("Hide the direction arrow", "Hidden while you're in combat. It comes back when combat ends.",
    function() return GPS().combatHideArrow end, function(v) GPS().combatHideArrow = v end)
  slider("Arrow opacity in combat", 0, 100, 5, "%d%%",
    function() return math.floor((GPS().arrowCombatAlpha or 1) * 100 + 0.5) end, function(v) GPS().arrowCombatAlpha = v / 100 end,
    function() return not GPS().combatHideArrow end)

  ---------------------------------------------------------------- Routing
  Page("Routing")
  header("Routes")
  check("Avoid zones too high for your level", "Routes go around zones whose levels are red for your character (their lowest level more than 4 above yours) when there's another way, like the other faction's towns. The zones you start and end in don't count.",
    function() return GPS().avoidHighZones ~= false end, function(v) GPS().avoidHighZones = v ns.Nav.OptionsChanged() end)
  check("Use flight paths", "Routes take flights (connecting ones too) between the flight masters this character knows, when that's faster. The addon learns which ones you know from the flight map: open it once at any flight master.",
    function() return GPS().useFlights ~= false end, function(v)
      GPS().useFlights = v
      ns.Nav.OptionsChanged()
    end)
  check("Questing", "A stop inside a quest's area (the blue outlines, for quests in your log) is done when that quest's objectives are, not when you get there. In the area, the route waits and the arrow shows a ! and the objective counters. Leave before they're done and the route leads back; then it goes on to the next stop.",
    function() return GPS().questing ~= false end, function(v)
      GPS().questing = v
      ns.Nav.Invalidate(true, true)
    end)
  check("Quest route: only this zone", "The Quest Route button takes only the quests whose objective or turn-in is in the zone you're in (a city counts as its zone). Off: every quest in your log, anywhere.",
    function() return GPS().questZoneOnly end, function(v) GPS().questZoneOnly = v end)
  check("Use hearthstone", "Routes may start with your Hearthstone (or a shaman's Astral Recall) when it's in your bags, off cooldown, and faster. Home is your inn's town; the exact spot is learned after your first hearth. The directions say when; click the button beside them to use it.",
    function() return GPS().useHearthstone ~= false end, function(v)
      GPS().useHearthstone = v
      ns.Nav.OptionsChanged()
    end)
  check("Use class teleports and teleport items", "Routes may start with a mage's teleport (with a Rune of Teleportation), Teleport: Moonglade, or an engineer's Dimensional Ripper - Everlook or Ultrasafe Transporter: Gadgetzan (with the specialization it needs) when it's known or in your bags, off cooldown, and faster. Click the button beside the directions to use it.",
    function() return GPS().useTeleports ~= false end, function(v)
      GPS().useTeleports = v
      ns.Nav.OptionsChanged()
    end)
  check("Avoid the other faction's towns", "Routes keep away from the other faction's guards (their towns and camps, and where their guards patrol), going around when there's a way. A stop inside one is still reached, the shortest way in.",
    function() return GPS().avoidHostile ~= false end, function(v)
      GPS().avoidHostile = v
      ns.Nav.OptionsChanged()
    end)
  check("Visit stops in the fastest order", "Routes with several stops visit them in the fastest order instead of the order you placed them. (Double-click the map to place stops.)",
    function() return GPS().fastestOrder end, function(v)
      GPS().fastestOrder = v
      if v and #ns.Nav.stops > 1 and not ns.Nav.KeepCityOrder() then ns.Nav.OrderStops() end
    end)
  place(Checkbox(page, "Except in cities", "Stops down in a city (Undercity) are visited in the order you placed them among themselves: how you want to go around a city is up to you. Stops outside the city still go in the fastest order. (A quest route is always put in the fastest order.)",
    function() return GPS().cityKeepOrder ~= false end, function(v) GPS().cityKeepOrder = v end), 26, 20)
  check("X on the route panel cancels the route", "The X at the top right of the map's route panel (the steps) cancels the whole route. Off: it only closes the panel until the route changes, and the route goes on.",
    function() return GPS().navCloseClears end, function(v) GPS().navCloseClears = v end)
  header("Waypoints and sharing")
  check("Accept TomTom /way commands", "/way lines typed or pasted in chat add stops to the route (several pasted lines at once become several stops). With TomTom installed, its waypoint is set too.",
    function() return GPS().acceptWay ~= false end, function(v) GPS().acceptWay = v end)
  check("Accept routes shared by players", "Other AzerothGPS users can send you their route (Import and share waypoints window). You're always asked before it replaces yours.",
    function() return GPS().acceptShared ~= false end, function(v) GPS().acceptShared = v end)
  place(Button(page, "Import / share waypoints...", 200, function() ns.Import.Toggle() end), 30, 4)

  ---------------------------------------------------------------- Directions
  Page("Directions")
  header("Direction arrow")
  check("Show direction arrow", "A small window (TomTom style) with an arrow along the route, the next turn (\"Turn left 120 yd, toward Razor Hill\"), the stop's distance and ETA, and the stops after it when made taller.",
    function() return GPS().arrow end, function(v) GPS().arrow = v end)
  check("Lock arrow position", "Locks the direction arrow in place. Unlocked: drag it to move it and its corner to resize it (taller lists the later stops). With no route it shows a placeholder while unlocked, so you can place it. Locked, clicks pass through it to the game world.",
    function() return GPS().arrowLocked end, function(v) GPS().arrowLocked = v end)
  slider("Arrow background", 0, 100, 5, "%d%%",
    function() return math.floor((GPS().arrowBg or 0.55) * 100 + 0.5) end, function(v) GPS().arrowBg = v / 100 end)
  header("How it works")
  note("The arrow points along the route: |cff73ff73green|r straight ahead, |cffffffffwhite|r for a turn coming up, |cffff7359red|r when the route is behind you. On a flight it shows where you land and when.")
  note("Its lines: the next turn and its distance, the road or place you're heading toward, the stop with its distance and ETA, then the turn after that.")
  note("To move it, untick Lock arrow position, then drag it; drag its bottom-right corner to resize it. Made taller, it lists the later stops too. Unlocked with no route, it shows a placeholder so you can place it.")
  note("In a quest's area it shows a ! and the quest's objectives. A small Sprint icon pulsing in its top-right corner means you picked up a quest after making your quest route: click it (or the quest route button on the map) to make the route again with it.")

  ---------------------------------------------------------------- Map
  Page("Map")
  header("Map", "Map style and layers: the round button at the map's bottom-left.")
  check("Right-click opens the world map", "In the terrain view, right-click shows Azeroth: click a continent, then a spot on it, to come back to the terrain view there. Right-click again goes back.",
    function() return GPS().terrainZoomOut ~= false end, function(v) GPS().terrainZoomOut = v end)
  check("Building interiors", "Inside buildings and caves (e.g. Undercity), the terrain view shows the building's own map, like the minimap.",
    function() return GPS().interiors end, function(v) GPS().interiors = v end)
  header("Show on the map", "Double-click one to add it as a stop.")
  check("Flight masters", "Green: known. Gray: not learned. Yellow: open a flight map once so the addon can tell.",
    function() return GPS().poiTaxi end, function(v) GPS().poiTaxi = v end)
  check("Points of interest", "Places marked on the world map.",
    function() return GPS().poiPoi end, function(v) GPS().poiPoi = v end)
  check("Place names", "Town and area names, when zoomed in.",
    function() return GPS().poiLabels end, function(v) GPS().poiLabels = v end)
  check("Quests", "Your quests' objectives and turn-ins.",
    function() return GPS().layerQuests end, function(v) GPS().layerQuests = v end)
  check("Party members", "Your party's or raid's members, as round icons of their class in their class's color (their name when you point at one), where the game gives their position. They don't need AzerothGPS themselves.",
    function() return GPS().showParty ~= false end, function(v) GPS().showParty = v end)
  check("Quest areas", "Outlines of your quests' objective areas, like on the minimap. Hover one to see the quest's objectives.",
    function() return GPS().layerQuestAreas end, function(v) GPS().layerQuestAreas = v end)
  check("Herbs", "Herbs you've gathered, hovered on the game minimap, right-clicked (without Herbalism) or imported. Saved for all your characters. A farming area (map menu) uses the kinds shown.",
    function() return GPS().layerHerbs ~= false end, function(v) GPS().layerHerbs = v end)
  check("Ore", "Mining nodes you've gathered, hovered on the game minimap, right-clicked (without Mining) or imported. Saved for all your characters. A farming area (map menu) uses the kinds shown.",
    function() return GPS().layerOre ~= false end, function(v) GPS().layerOre = v end)
  check("Dungeons and raids", "Their entrances, on every map style. Click one for its map, with its bosses in the usual order; right-click goes back out.",
    function() return GPS().layerInstances ~= false end, function(v) GPS().layerInstances = v end)
  check("Cave entrances", "The ways into caves and mines (not on a continent's map). Double-click one for a stop there.",
    function() return GPS().layerCaves ~= false end, function(v) GPS().layerCaves = v end)

  ---------------------------------------------------------------- Quick buttons
  Page("Quick buttons")
  header("Where each one goes")
  note("Always shown: next to the map button, going up or to the right. In the menu: slides out past those when you click the map button (it closes after 20 seconds untouched). Hidden: not on the map (the setting still works). A group (map style, quests, herbs and ore) is one button: click it and its buttons slide out beside it. ^ and v set the order.")
  local fit = page:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  fit:SetWidth(PAGE_W - 60)
  fit:SetJustifyH("LEFT")
  place(fit, 18, 4)
  local qwarn = page:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
  qwarn:SetWidth(PAGE_W - 60)
  qwarn:SetJustifyH("LEFT")
  place(qwarn, 28, 4)
  controls[#controls + 1] = function()
    local up, right = 0, 0
    if ns.GPS.QuickCapacity then up, right = ns.GPS.QuickCapacity() end
    fit:SetText(string.format("At the map's size: %d fit going up and %d going right (always shown and in the menu together).", up, right))
  end
  local function Warn(text)
    qwarn:SetText(text and ("|cffff4040" .. text .. "|r") or "")
    if text then
      local shown = qwarn:GetText()
      C_Timer.After(8, function() if qwarn:GetText() == shown then qwarn:SetText("") end end)
    end
  end
  -- the columns: place, x, heading
  local COLS = { { "barUp", 168 }, { "barRight", 204 }, { "menuUp", 252 }, { "menuRight", 288 }, { "hidden", 336 } }
  local ON_X = 380
  local heads = CreateFrame("Frame", nil, page)
  heads:SetSize(PAGE_W - 40, 30)
  local function Head(text, x, y, w)
    local fs = heads:CreateFontString(nil, "ARTWORK", "GameFontNormalSmall")
    fs:SetPoint("TOP", heads, "TOPLEFT", x, y)
    if w then fs:SetWidth(w) end
    fs:SetText(text)
  end
  Head("Always shown", 186 + 12, 0, 90)
  Head("In the menu", 270 + 12, 0, 90)
  Head("Up", 168 + 12, -14)
  Head("Right", 204 + 12, -14)
  Head("Up", 252 + 12, -14)
  Head("Right", 288 + 12, -14)
  Head("Hidden", 336 + 12, -14)
  Head("On", ON_X + 12, -14)
  place(heads, 32)
  -- one row per button or group, in their order (^ / v move one)
  local rowsTop, rowsX, rowById = col.y, col.x, {}
  local function OrderRows()
    for i, t in ipairs(ns.GPS.QuickSlots and ns.GPS.QuickSlots() or {}) do
      local row = rowById[t.id]
      if row then
        row:ClearAllPoints()
        row:SetPoint("TOPLEFT", rowsX, rowsTop - (i - 1) * 24)
      end
    end
  end
  local function Arrow(row, text, x, id, delta, tip)
    local b = CreateFrame("Button", nil, row)
    b:SetSize(14, 16)
    b:SetPoint("LEFT", row, "LEFT", x, 0)
    local fill = b:CreateTexture(nil, "BACKGROUND")
    fill:SetAllPoints()
    fill:SetColorTexture(0.3, 0.25, 0.1, 0.8)
    local hl = b:CreateTexture(nil, "HIGHLIGHT")
    hl:SetAllPoints()
    hl:SetColorTexture(1, 1, 1, 0.2)
    local fs = b:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    fs:SetPoint("CENTER", 0, 0)
    fs:SetText(text)
    b:SetScript("OnClick", function()
      ns.GPS.MoveSlot(id, delta)
      OrderRows()
    end)
    b:SetScript("OnEnter", function(self)
      GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
      GameTooltip:SetText(tip, 1, 1, 1)
      GameTooltip:Show()
    end)
    b:SetScript("OnLeave", GameTooltip_Hide)
  end
  local slots = ns.GPS.QuickSlots and ns.GPS.QuickSlots() or {}
  for _, t in ipairs(slots) do
    local row = CreateFrame("Frame", nil, page)
    row:SetSize(PAGE_W - 40, 24)
    rowById[t.id] = row
    Arrow(row, "^", 0, t.id, -1, "Earlier (nearer the map button)")
    Arrow(row, "v", 16, t.id, 1, "Later (further from the map button)")
    local icon = row:CreateTexture(nil, "ARTWORK")
    icon:SetSize(18, 18)
    icon:SetPoint("LEFT", 34, 0)
    if t.icon then
      ns.SetIcon(icon, t.icon, "Interface\\Icons\\INV_Misc_QuestionMark")
    elseif t.id == "search" then
      ns.SetIcon(icon, "atlas:common-search-magnifyingglass", "Interface\\Icons\\INV_Misc_Spyglass_03")
    else
      icon:SetTexture("Interface\\Icons\\Ability_Rogue_Sprint")
    end
    local label = row:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
    label:SetPoint("LEFT", icon, "RIGHT", 4, 0)
    label:SetWidth(108)
    label:SetJustifyH("LEFT")
    label:SetText(t.label)
    if t.group then
      row:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetText(t.label, 1, 1, 1)
        local names = {}
        for _, m in ipairs(t.members) do names[#names + 1] = m.label end
        GameTooltip:AddLine("A group: " .. table.concat(names, ", ") .. ".", nil, nil, nil, true)
        GameTooltip:Show()
      end)
      row:SetScript("OnLeave", GameTooltip_Hide)
    end
    local boxes = {}
    for _, c in ipairs(COLS) do
      local cb = CreateFrame("CheckButton", nil, row, "UICheckButtonTemplate")
      cb:SetSize(22, 22)
      cb:SetPoint("LEFT", row, "LEFT", c[2] + 1, 0)
      cb:SetScript("OnClick", function()
        local q = GPS().quick or {}
        GPS().quick = q
        if not ns.GPS.QuickFits({ t.id, c[1] }) then
          Warn(string.format("No room for %s there at this map size (it would need %d). Make the map bigger (General: Size), or move or hide another one.",
            t.label, ns.GPS.QuickMinSize({ t.id, c[1] })))
        else
          Warn(nil)
          q[t.id] = c[1]
        end
        Apply()
      end)
      boxes[c[1]] = cb
    end
    local on
    if t.key then
      on = CreateFrame("CheckButton", nil, row, "UICheckButtonTemplate")
      on:SetSize(22, 22)
      on:SetPoint("LEFT", row, "LEFT", ON_X + 1, 0)
      on:SetScript("OnClick", function(self)
        GPS()[t.key] = self:GetChecked() and true or false
        if t.route then ns.Nav.OptionsChanged() end
        Apply()
      end)
      on:SetScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetText(t.label, 1, 1, 1)
        GameTooltip:AddLine(t.tip, nil, nil, nil, true)
        GameTooltip:Show()
      end)
      on:SetScript("OnLeave", GameTooltip_Hide)
    end
    controls[#controls + 1] = function()
      local where = ns.GPS.QuickPlace(t.id)
      for id, cb in pairs(boxes) do cb:SetChecked(id == where) end
      if on then
        on:SetChecked(ns.GPS.QuickOn(t))
        on:SetEnabled(not t.needs or GPS()[t.needs] and true or false)
      end
    end
  end
  col.y = col.y - #slots * 24
  controls[#controls + 1] = OrderRows

  ---------------------------------------------------------------- Tools
  Page("Tools")
  note("For fixing the map's data: roads the routes miss or that aren't there, and walls they walk through. Each set of tools shows its data while it's on; with them off, the |cffffd100Show Roads and Walls|r button under Undo on the map shows both (or /agps roads on, /agps walls on).")
  header("Roads", "The road network the routes use.")
  note("With the road tools on, on the map: left-drag along a road the routes miss, right-drag over a \"road\" that isn't there (red), middle-drag to pan. Routes use it right away. A drawn road joins the roads it meets; where it runs along one, that road stays.")
  check("Road tools button on the map", "Adds a Road Tools toggle to the map's buttons (the up column). Also /agps dev.",
    function() return GPS().devTools end, function(v)
      GPS().devTools = v
      if not v and ns.GPS.roadMode then ns.GPS.SetRoadMode(false) end
      if ns.GPS.LayoutQuick then ns.GPS.LayoutQuick() end
    end)
  place(Button(page, "Road Tools On/Off", 150, function() ns.GPS.ToggleRoadMode() end), 28, 4)
  header("Walls", "What routes can't walk through: a town's wall, a fence, a cliff edge.")
  note("With the wall tools on, on the map: left-drag along a wall the routes try to walk through, right-drag over a wall that isn't there, or a mountain edge that's really walkable (circle an area to open all of it), middle-drag to pan. Routes go around your walls right away, like a mountain, and a road a wall crosses is cut there: leave a gap for a gate. Flight paths still cross them. Shown in blood red: the edges of mountains and cliffs too steep to climb (the terrain data), buildings, and the walls drawn in (thicker).")
  check("Wall tools button on the map", "Adds a Wall Tools toggle to the map's buttons (the up column).",
    function() return GPS().wallTools end, function(v)
      GPS().wallTools = v
      if not v and ns.GPS.wallMode then ns.GPS.SetWallMode(false) end
      if ns.GPS.LayoutQuick then ns.GPS.LayoutQuick() end
    end)
  place(Button(page, "Wall Tools On/Off", 150, function() ns.GPS.ToggleWallMode() end), 28, 4)
  header("Your changes", "Roads and walls you draw or erase, in the order drawn.")
  local undoBtn = Button(page, "Take Back the Last", 150, function() ns.Record.Undo() end)
  local listBtn = Button(page, "List Your Changes", 150, function() ns.Record.List() end)
  place(undoBtn, 28, 4)
  listBtn:SetPoint("LEFT", undoBtn, "RIGHT", 6, 0)
  controls[#controls + 1] = function()
    local any = ns.db and ns.db.tracks and #ns.db.tracks > 0
    undoBtn:SetEnabled(any and true or false)
  end

  ---------------------------------------------------------------- Help improve
  Page("Help improve")
  header("Help improve AzerothGPS", "Kept on your PC only; sharing it is a separate step.")
  check("Share drawn roads and walls", "Roads and walls you draw or erase are kept for a future road-network update. Addons can't send anything from the game: the data waits in your saved variables until it's uploaded outside the game.",
    function() return GPS().shareRoads end, function(v) GPS().shareRoads = v end)
  check("Share faster trips", "When you reach a stop clearly faster than the estimate (85% of it or less), the way you went is kept (a trace of positions, the estimate and your time), so shortcuts and missing roads can be added. No character or realm names. Kept on your PC until uploaded outside the game.",
    function() return GPS().shareTrips end, function(v) GPS().shareTrips = v end)
  local counts = page:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  place(counts, 18, 4)
  local howBtn = Button(page, "How to share...", 150, ShowShareInfo)
  place(howBtn, 28, 4)
  local copyBtn = Button(page, "Copy Map Data...", 150, ShowRoadsText)
  copyBtn:SetPoint("LEFT", howBtn, "RIGHT", 6, 0)
  note("Type |cffffd100/reload|r before |cffffd100Copy Map Data...|r: it saves all your road and wall edits, so every one of them is in the copy.")
  controls[#controls + 1] = function()
    local _, t = ns.Feedback.Counts()
    local r, w = ns.Feedback.DrawnCounts()
    counts:SetText(string.format("Waiting to be shared: %d road%s, %d wall%s, %d trip%s", r, r == 1 and "" or "s",
      w, w == 1 and "" or "s", t, t == 1 and "" or "s"))
  end

  FinishPage()

  -- footer
  local reset = Button(f, "Reset to defaults", 160, function()
    ns.settings.gps = CopyTable(ns.DEFAULTS.gps)
  end)
  reset:SetPoint("BOTTOMRIGHT", -12, 12)
  local version = f:CreateFontString(nil, "ARTWORK", "GameFontDisableSmall")
  version:SetPoint("BOTTOMLEFT", 14, 18)
  version:SetText("AzerothGPS " .. (ns.VERSION or ""))

  f:SetScript("OnShow", function()
    for _, refresh in ipairs(controls) do refresh() end
    ShowPage(currentPage)
  end)
  ShowPage(currentPage)
  f:Hide()
  return f
end

function O.Toggle()
  window = window or BuildWindow()
  window:SetShown(not window:IsShown())
end

function O.Show()
  window = window or BuildWindow()
  window:Show()
end

---------------------------------------------------------------------------
-- Minimap button
---------------------------------------------------------------------------

local function PlaceButton()
  local a = math.rad(ns.settings.minimap.angle)
  local r = (Minimap:GetWidth() / 2) + 5
  O.button:ClearAllPoints()
  O.button:SetPoint("CENTER", Minimap, "CENTER", math.cos(a) * r, math.sin(a) * r)
end

function O.UpdateButton()
  O.button:SetShown(not ns.settings.minimap.hide)
  PlaceButton()
end

local function BuildButton()
  local b = CreateFrame("Button", "AzerothGPSMinimapButton", Minimap)
  b:SetSize(31, 31)
  b:SetFrameStrata("MEDIUM")
  b:SetFrameLevel(8)
  b:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  b:RegisterForDrag("LeftButton")
  b:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")

  local bg = b:CreateTexture(nil, "BACKGROUND")
  bg:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  bg:SetSize(20, 20)
  bg:SetPoint("CENTER")
  local icon = b:CreateTexture(nil, "ARTWORK")
  icon:SetTexture("Interface\\AddOns\\AzerothGPS\\Media\\Device") -- the device from the logo
  icon:SetSize(20, 20)
  icon:SetPoint("CENTER")
  local border = b:CreateTexture(nil, "OVERLAY")
  border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
  border:SetSize(52, 52)
  border:SetPoint("TOPLEFT")

  b:SetScript("OnClick", function(_, mouse)
    if mouse == "RightButton" then
      O.Toggle()
    else
      GPS().shown = not GPS().shown
      Apply()
    end
  end)
  b:SetScript("OnDragStart", function(self)
    self:SetScript("OnUpdate", function()
      local mx, my = Minimap:GetCenter()
      local cx, cy = GetCursorPosition()
      local scale = Minimap:GetEffectiveScale()
      ns.settings.minimap.angle = math.deg(math.atan2(cy / scale - my, cx / scale - mx))
      PlaceButton()
    end)
  end)
  b:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
  b:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:SetText("AzerothGPS", 1, 1, 1)
    GameTooltip:AddLine("Left-click: show/hide the GPS", nil, nil, nil)
    GameTooltip:AddLine("Right-click: options", nil, nil, nil)
    GameTooltip:AddLine("Drag: move this button", nil, nil, nil)
    GameTooltip:Show()
  end)
  b:SetScript("OnLeave", GameTooltip_Hide)
  return b
end

---------------------------------------------------------------------------
-- Game options (Esc > Options > AddOns)
---------------------------------------------------------------------------

local function RegisterGameOptions()
  if not (Settings and Settings.RegisterCanvasLayoutCategory and Settings.RegisterAddOnCategory) then return end
  local panel = CreateFrame("Frame")
  panel.name = "AzerothGPS"
  local t = panel:CreateFontString(nil, "ARTWORK", "GameFontNormalLarge")
  t:SetPoint("TOPLEFT", 16, -16)
  t:SetText("AzerothGPS")
  local d = panel:CreateFontString(nil, "ARTWORK", "GameFontHighlight")
  d:SetPoint("TOPLEFT", t, "BOTTOMLEFT", 0, -8)
  d:SetText("Car-GPS style map and navigation. Settings are in the AzerothGPS window.")
  local open = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
  open:SetSize(200, 24)
  open:SetPoint("TOPLEFT", d, "BOTTOMLEFT", 0, -12)
  open:SetText("Open AzerothGPS options")
  open:SetScript("OnClick", function()
    if SettingsPanel and SettingsPanel:IsShown() then HideUIPanel(SettingsPanel) end
    O.Show()
  end)
  local category = Settings.RegisterCanvasLayoutCategory(panel, "AzerothGPS")
  Settings.RegisterAddOnCategory(category)
end

function O.Init()
  O.button = BuildButton()
  O.UpdateButton()
  pcall(RegisterGameOptions)
end

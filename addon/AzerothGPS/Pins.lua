-- Pins: places the player marks on the map. With pinning on (Options > Tools, `pinning`, on by default),
-- Shift + left-click on the map asks "Create Pin" (GPSFrame's G.AskCreatePin); then a name, an icon from
-- the game's icons (the ones a macro can have) and, where floors lie over each other, the floor (a
-- dungeon's floors, Undercity's, the floor under a cave's or capital's ground: GPSFrame's G.PinFloors).
-- Shown on the map (Options > Map, `showCustomPins`) like a city location: double-click for a stop there
-- (with its height: its floor), right-click to remove it.
-- Kept account-wide (ns.db.pins) and shared with the map data like roads and walls ("Copy Map Data...":
-- the "P" lines, Feedback.RoadsText): `agps import-shared` and the road watcher put them in
-- overrides/pins.json and Data/Pins.lua (ns.SharedPins, shown to everyone; ns.PinsIn, their times: the
-- player's own copies of those are dropped at login).
local _, ns = ...

local P = {}
ns.Pins = P

P.NAME_MAX = 40 -- letters
P.DEFAULT_ICON = "Interface\\Icons\\INV_Misc_QuestionMark"
P.COLS, P.ROWS, P.CELL = 10, 6, 34 -- the icon grid: columns, rows shown, pixels a cell
-- (if the game gives no icon list: a few of its own)
P.FALLBACK_ICONS = { "INV_Misc_QuestionMark", "INV_Misc_Map02", "INV_Misc_Bag_08", "INV_Misc_Coin_01",
  "INV_Misc_Herb_07", "INV_Ore_Copper_01", "INV_Pick_02", "INV_Sword_04", "INV_Shield_06", "INV_Helmet_03",
  "INV_Misc_Bone_HumanSkull_01", "INV_Misc_Note_02", "INV_Misc_Spyglass_02", "INV_Misc_Rune_01",
  "INV_Misc_PocketWatch_01", "Ability_Warrior_ShieldWall", "Ability_DualWield" }

function P.Own()
  ns.db.pins = ns.db.pins or {}
  return ns.db.pins
end

-- A pin's icon as a texture: a file id, a path, or an icon's name (under Interface\Icons).
function P.IconTexture(icon)
  if type(icon) == "number" then return icon end
  if type(icon) ~= "string" or icon == "" then return P.DEFAULT_ICON end
  if icon:find("[\\/]") then return icon end
  return "Interface\\Icons\\" .. icon
end

-- A name as kept and shared: one line, no escape codes ("|"), "Pin" when empty.
function P.CleanName(s)
  s = tostring(s or "")
  s = s:gsub("|", ""):gsub("%c", " "):gsub("^%s+", ""):gsub("%s+$", "")
  if s == "" then s = "Pin" end
  if #s > P.NAME_MAX * 4 then s = s:sub(1, P.NAME_MAX * 4) end
  return s
end

-- Every pin to show: the player's own and the shared ones (Data/Pins.lua) they haven't removed. Each:
-- { level, x, y, z, down, icon, name, time, shipped }.
function P.All()
  local out = {}
  for _, p in ipairs(P.Own()) do out[#out + 1] = p end
  local gone = ns.db.pinsRemoved or {}
  for _, p in ipairs(ns.SharedPins or {}) do
    if not gone[p.time] then out[#out + 1] = p end
  end
  return out
end

-- A new pin { level, x, y, z, down, icon, name }: kept, and returned. Its time is its id (one no other
-- pin has, the shared ones' included).
function P.Add(pin)
  local t = time and time() or 0
  local used = {}
  for _, p in ipairs(P.All()) do
    if p.time then used[p.time] = true end
  end
  for k in pairs(ns.PinsIn or {}) do used[k] = true end
  while used[t] do t = t + 1 end
  local p = { level = pin.level, x = pin.x, y = pin.y, z = pin.z, down = pin.down, icon = pin.icon or P.DEFAULT_ICON,
    name = P.CleanName(pin.name), time = t }
  local own = P.Own()
  own[#own + 1] = p
  P.Changed()
  return p
end

-- Take pin `p` off the map: the player's own is gone; a shared one is hidden here, and its removal
-- shared with the map data. (Its time is kept as removed either way: one of the player's the road
-- watcher put in the data since login is shared by then; P.Prune forgets the rest at the next login.)
function P.Remove(p)
  if p.time then
    ns.db.pinsRemoved = ns.db.pinsRemoved or {}
    ns.db.pinsRemoved[p.time] = true
  end
  local own = P.Own()
  for i = #own, 1, -1 do
    if own[i] == p then table.remove(own, i) end
  end
  P.Changed()
end

function P.Changed()
  if ns.GPS and ns.GPS.Redraw then ns.GPS.Redraw() end
end

-- At login: the player's pins the data has now are dropped (its copy shows), and the removals of shared
-- pins the data no longer has are forgotten.
function P.Prune()
  local shipped = ns.PinsIn or {}
  local own = P.Own()
  for i = #own, 1, -1 do
    if own[i].time and shipped[own[i].time] then table.remove(own, i) end
  end
  local gone = ns.db.pinsRemoved
  if gone then
    for t in pairs(gone) do
      if not shipped[t] then gone[t] = nil end
    end
  end
end
P.Init = P.Prune

-- The pins to share ("Copy Map Data...", Feedback.RoadsText): the player's not in the data yet, and the
-- shared ones they removed. `agps import-shared` reads them back:
--   P add <level> <time> <x,y> [z=<height>] [down=1|0] icon=<file id or path> name=<the rest of the line>
--   P remove <time>
function P.ShareLines()
  local lines = {}
  local shipped = ns.PinsIn or {}
  for _, p in ipairs(P.Own()) do
    if p.time and p.x and p.y and not shipped[p.time] then
      local out = { "P", "add", tostring(p.level or 0), tostring(p.time), string.format("%.1f,%.1f", p.x, p.y) }
      if p.z then out[#out + 1] = string.format("z=%.1f", p.z) end
      if p.down ~= nil then out[#out + 1] = p.down and "down=1" or "down=0" end
      out[#out + 1] = "icon=" .. (tostring(p.icon or P.DEFAULT_ICON):gsub("%s", ""))
      out[#out + 1] = "name=" .. P.CleanName(p.name)
      lines[#lines + 1] = table.concat(out, " ")
    end
  end
  local gone = {}
  for t in pairs(ns.db.pinsRemoved or {}) do
    if shipped[t] then gone[#gone + 1] = t end
  end
  table.sort(gone)
  for _, t in ipairs(gone) do lines[#lines + 1] = "P remove " .. t end
  return lines
end

-- The icons to pick from: the game's list for macros (file ids, or names), worked out once.
local icons
function P.Icons()
  if icons then return icons end
  icons = {}
  local seen = {}
  local function take(fn)
    if type(fn) ~= "function" then return end
    local list = {}
    local ok, r = pcall(fn, list)
    if ok and type(r) == "table" and r ~= list then list = r end -- (a client that returns it instead)
    for _, v in ipairs(list) do
      if v and not seen[v] then
        seen[v] = true
        icons[#icons + 1] = v
      end
    end
  end
  take(GetLooseMacroIcons)
  take(GetLooseMacroItemIcons)
  take(GetMacroIcons)
  take(GetMacroItemIcons)
  if #icons == 0 then
    for _, n in ipairs(P.FALLBACK_ICONS) do icons[#icons + 1] = n end
  end
  return icons
end

-- The dialog: a name, the icon grid (scrolled with the mouse wheel or the bar beside it), the floor.
local dlg
P.selected, P.top = 1, 0 -- the icon picked (kept for the next pin), the grid's first row
local function Button(parent, text, w)
  local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
  b:SetSize(w, 22)
  b:SetText(text)
  return b
end
local function Dialog()
  if dlg then return dlg end
  local f = CreateFrame("Frame", "AzerothGPSPinDialog", UIParent, BackdropTemplateMixin and "BackdropTemplate" or nil)
  f:SetSize(P.COLS * P.CELL + 64, P.ROWS * P.CELL + 168)
  f:SetPoint("CENTER")
  f:SetFrameStrata("DIALOG")
  f:SetToplevel(true)
  f:SetClampedToScreen(true)
  f:EnableMouse(true)
  f:SetMovable(true)
  f:RegisterForDrag("LeftButton")
  f:SetScript("OnDragStart", function(self) self:StartMoving() end)
  f:SetScript("OnDragStop", function(self) self:StopMovingOrSizing() end)
  if f.SetBackdrop then
    f:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8", edgeFile = "Interface\\Buttons\\WHITE8X8", edgeSize = 1 })
    f:SetBackdropColor(0.06, 0.06, 0.06, 0.96)
    f:SetBackdropBorderColor(0.4, 0.4, 0.4, 1)
  end
  if UISpecialFrames then table.insert(UISpecialFrames, "AzerothGPSPinDialog") end -- (Escape closes it)
  f:Hide()

  local title = f:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
  title:SetPoint("TOP", 0, -12)
  title:SetText("Create Pin")

  local label = f:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  label:SetPoint("TOPLEFT", 20, -48)
  label:SetText("Name")
  local name = CreateFrame("EditBox", nil, f, "InputBoxTemplate")
  name:SetSize(220, 20)
  name:SetPoint("LEFT", label, "RIGHT", 12, 0)
  name:SetAutoFocus(false)
  name:SetMaxLetters(P.NAME_MAX)
  name:SetScript("OnEnterPressed", function() P.Confirm() end)
  name:SetScript("OnEscapePressed", function() f:Hide() end)
  f.name = name
  local preview = f:CreateTexture(nil, "ARTWORK")
  preview:SetSize(36, 36)
  preview:SetPoint("TOPRIGHT", -24, -38)
  f.preview = preview

  local pick = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  pick:SetPoint("TOPLEFT", 20, -80)
  pick:SetText("Choose an icon:")
  local grid = CreateFrame("Frame", nil, f)
  grid:SetSize(P.COLS * P.CELL, P.ROWS * P.CELL)
  grid:SetPoint("TOPLEFT", 20, -96)
  grid:EnableMouseWheel(true)
  grid:SetScript("OnMouseWheel", function(_, delta) P.Scroll(delta > 0 and -1 or 1) end)
  local sel = grid:CreateTexture(nil, "BACKGROUND")
  sel:SetSize(P.CELL, P.CELL)
  sel:SetColorTexture(1, 0.82, 0, 0.75)
  f.sel = sel
  f.cells = {}
  for r = 1, P.ROWS do
    for c = 1, P.COLS do
      local b = CreateFrame("Button", nil, grid)
      b:SetSize(P.CELL - 4, P.CELL - 4)
      b:SetPoint("TOPLEFT", (c - 1) * P.CELL + 2, -((r - 1) * P.CELL + 2))
      b.icon = b:CreateTexture(nil, "ARTWORK")
      b.icon:SetAllPoints()
      local hl = b:CreateTexture(nil, "HIGHLIGHT")
      hl:SetAllPoints()
      hl:SetColorTexture(1, 1, 1, 0.25)
      b:SetScript("OnClick", function(self)
        P.selected = self.index
        P.Refresh()
      end)
      b:SetScript("OnDoubleClick", function(self)
        P.selected = self.index
        P.Confirm()
      end)
      f.cells[#f.cells + 1] = b
    end
  end
  local bar = CreateFrame("Slider", nil, f)
  bar:SetOrientation("VERTICAL")
  bar:SetSize(14, P.ROWS * P.CELL)
  bar:SetPoint("TOPLEFT", grid, "TOPRIGHT", 6, 0)
  local barBg = bar:CreateTexture(nil, "BACKGROUND")
  barBg:SetAllPoints()
  barBg:SetColorTexture(0.15, 0.15, 0.15, 0.9)
  local thumb = bar:CreateTexture(nil, "OVERLAY")
  thumb:SetColorTexture(0.7, 0.7, 0.7, 1)
  thumb:SetSize(14, 28)
  bar:SetThumbTexture(thumb)
  bar:SetValueStep(1)
  if bar.SetObeyStepOnDrag then bar:SetObeyStepOnDrag(true) end
  bar:SetScript("OnValueChanged", function(_, v)
    if P.syncing then return end
    P.top = math.floor(v + 0.5)
    P.Refresh()
  end)
  f.bar = bar
  local count = f:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  count:SetPoint("TOPLEFT", grid, "BOTTOMLEFT", 0, -4)
  f.count = count

  -- the floor, where floors lie over each other there
  local floorText = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  floorText:SetPoint("BOTTOMLEFT", 20, 50)
  f.floorText = floorText
  local nextF = Button(f, ">", 26)
  nextF:SetPoint("BOTTOMRIGHT", -20, 46)
  nextF:SetScript("OnClick", function() P.StepFloor(1) end)
  local prevF = Button(f, "<", 26)
  prevF:SetPoint("RIGHT", nextF, "LEFT", -4, 0)
  prevF:SetScript("OnClick", function() P.StepFloor(-1) end)
  f.floorButtons = { prevF, nextF }

  local ok = Button(f, "Create Pin", 110)
  ok:SetPoint("BOTTOMRIGHT", -20, 14)
  ok:SetScript("OnClick", function() P.Confirm() end)
  local cancel = Button(f, "Cancel", 90)
  cancel:SetPoint("RIGHT", ok, "LEFT", -8, 0)
  cancel:SetScript("OnClick", function() f:Hide() end)
  f.ok = ok
  dlg = f
  return f
end

-- Scroll the icon grid `rows` rows (down: positive).
function P.Scroll(rows)
  P.top = (P.top or 0) + rows
  P.Refresh()
end

-- Step the pin's floor: through the floors there, and "every floor" past either end.
function P.StepFloor(d)
  local e = P.editing
  if not e or #e.floors == 0 then return end
  e.floor = (e.floor + d) % (#e.floors + 1)
  P.Refresh()
end

-- The floor's line in the dialog.
function P.FloorLine(e)
  local fl = e and e.floors[e.floor]
  return "Floor: " .. (fl and fl.label or "every floor here")
end

function P.Refresh()
  local f = dlg
  if not f then return end
  local list = P.Icons()
  local rows = math.ceil(#list / P.COLS)
  local maxTop = math.max(0, rows - P.ROWS)
  P.top = math.max(0, math.min(P.top or 0, maxTop))
  P.selected = math.max(1, math.min(P.selected or 1, #list))
  f.sel:Hide()
  for i, b in ipairs(f.cells) do
    local k = P.top * P.COLS + i
    local icon = list[k]
    b.index = k
    if icon then
      b.icon:SetTexture(P.IconTexture(icon))
      b:Show()
      if k == P.selected then
        f.sel:ClearAllPoints()
        f.sel:SetPoint("CENTER", b, "CENTER")
        f.sel:Show()
      end
    else
      b:Hide()
    end
  end
  f.preview:SetTexture(P.IconTexture(list[P.selected]))
  local first = P.top * P.COLS + 1
  f.count:SetText(string.format("Icons %d-%d of %d (mouse wheel scrolls)", math.min(first, #list),
    math.min(first + P.COLS * P.ROWS - 1, #list), #list))
  P.syncing = true
  f.bar:SetMinMaxValues(0, maxTop)
  f.bar:SetValue(P.top)
  P.syncing = false
  local e = P.editing
  local floors = e and #e.floors > 0
  f.floorText:SetShown(floors and true or false)
  for _, b in ipairs(f.floorButtons) do b:SetShown(floors and true or false) end
  if floors then f.floorText:SetText(P.FloorLine(e)) end
end

-- Open the dialog for a pin at `spot`: { level, x, y, floors = { { label, z, down }, ... } (bottom up),
-- pick = the floor picked (0: every floor) }.
function P.OpenEditor(spot)
  local f = Dialog()
  P.editing = { level = spot.level, x = spot.x, y = spot.y, floors = spot.floors or {}, floor = spot.pick or 0 }
  f.name:SetText("")
  P.top = math.floor(((P.selected or 1) - 1) / P.COLS) -- (the icon picked last in view)
  P.Refresh()
  f:Show()
  f.name:SetFocus()
end

-- "Create Pin" in the dialog: the pin, with the name, icon and floor picked.
function P.Confirm()
  local e = P.editing
  if not (e and dlg) then return nil end
  local fl = e.floors[e.floor]
  local p = P.Add({ level = e.level, x = e.x, y = e.y, z = fl and fl.z or nil, down = fl and fl.down,
    icon = P.Icons()[P.selected] or P.DEFAULT_ICON, name = dlg.name:GetText() })
  P.editing = nil
  dlg.name:ClearFocus()
  dlg:Hide()
  if ns.Print then ns.Print("pinned " .. p.name .. " (double-click it for a stop, right-click to remove it)") end
  return p
end

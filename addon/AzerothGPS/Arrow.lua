-- The direction arrow (TomTom style): a small movable window with a big arrow along the
-- route, the next maneuver ("Turn left in 120 yd", "toward Razor Hill"), the stop it
-- leads to with its distance and ETA, and the maneuver after. Toggle: gps.arrow.
local _, ns = ...
local Geo = ns.Geo

local A = {}
ns.Arrow = A

local ARROW_ATLAS = "ui-hud-minimap-arrow-questtracking-2x"
local ARROW_FILE = "Interface\\Minimap\\MinimapArrow"
local TEXT_EVERY = 0.25 -- seconds between text updates (the arrow itself turns every frame)

local frame, arrow, slot, bang, dist, line1, line2, line3, line4, grip, stale
-- the route's first step a hearthstone or teleport: its icon where the arrow is, glowing (pulsing like
-- the quest route's remake button), and over it its button, clear (GPSFrame's NewUseButton: a click uses it)
local useBtn, useIcon, useGlow
local SPRINT_ICON = "Interface\\Icons\\Ability_Rogue_Sprint" -- the quest route button's
local QUEST_ICON = "Interface\\GossipFrame\\AvailableQuestIcon" -- the "!" in a quest area
local rows = {} -- the later stops, as many as fit the window's height
local ROW_H = 14
local path, maneuvers, textWait = nil, nil, 0
local jumpIcon

local function S() return ns.settings.gps end
-- opacity: full, or the combat setting in combat
local function Alpha()
  return ns.inCombat and (S().arrowCombatAlpha or 1) or 1
end

local function SavePosition()
  local p, rel, rp, x, y = frame:GetPoint(1)
  S().arrowPoint = { p, rel and rel:GetName() or "UIParent", rp, x, y }
end

local function StopLabel(d, count)
  local icon = string.format("|T%s:14|t ", ns.Nav.StopIcon(d))
  if d.name then return icon .. d.name end
  return icon .. (count > 1 and "stop 1" or "destination")
end

-- The texts: next maneuver, toward, stop line, then.
-- Make room for `want` rows under the directions: the window grows down past its saved
-- size while needed (quest objectives), and goes back to it after. Kept in place by its
-- top left corner meanwhile.
local function FitRows(want)
  local base = (S().arrowSize or { 250, 86 })[2]
  local top, lb = frame:GetTop(), line4:GetBottom()
  if not top or not lb then return end
  local h = want > 0 and math.max(base, (top - lb) + 8 + want * ROW_H) or base
  if math.abs(frame:GetHeight() - h) < 0.5 then return end
  local p = frame:GetPoint(1)
  if p ~= "TOPLEFT" then
    local left = frame:GetLeft()
    frame:ClearAllPoints()
    frame:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", left, top)
  end
  frame:SetHeight(h)
end

local RenderLines -- (below)

-- In the stop's quest area (Nav's questing): a "!" and the objectives, one per line. Until
-- the stop's spot is reached the arrow still leads there (the "!" small beside it, the
-- distance small under it); after that just a big "!".
local function QuestText(px, py, cont)
  local N = ns.Nav
  local paused, r, d = N.QuestPaused(), N.route, N.dest
  local lines = N.QuestLines()
  for _, l in ipairs(N.areaQuests and N.QuestLines(N.areaQuests) or {}) do lines[#lines + 1] = l end
  -- where to after this: the next stop, with its distance from this one
  local nxt, st = N.stops[2], r and r.stretches and r.stretches[2]
  if nxt then
    local label = string.format("|T%s:12|t %s", N.StopIcon(nxt), nxt.name or "stop 2")
    lines[#lines + 1] = { string.format("Then: %s%s", st and ("|cffffffff" .. N.FormatDistance(st.walk) .. "|r  ") or "", label),
      0.75, 0.75, 0.75 }
  end
  bang:ClearAllPoints()
  bang:Show()
  if paused or not r or r.flying then
    path, maneuvers = nil, nil
    arrow:Hide()
    dist:Hide()
    bang:SetSize(40, 40)
    bang:SetPoint("CENTER", arrow, "CENTER")
  else
    -- still leading to the spot: a smaller, fainter arrow (a little higher), "In quest
    -- area" and the yards to the spot under it; the "!" goes by the quest's title instead
    path = ns.Turns.Path(r)
    arrow:Show()
    arrow:SetSize(29, 29)
    arrow:SetAlpha(0.5)
    arrow:ClearAllPoints()
    arrow:SetPoint("CENTER", slot, "CENTER", 0, 10)
    dist:SetText("|cffbfbfbfIn quest area|r\n" .. N.FormatDistance(r.walkYards))
    dist:Show()
    bang:Hide()
    if lines[1] then lines[1][1] = "|T" .. QUEST_ICON .. ":14|t " .. lines[1][1] end
  end
  return RenderLines(lines)
end

-- Lines { { text, r, g, b }, ... } into the four text lines, then rows below (the window
-- grows to fit them).
function RenderLines(lines)
  local fixed = { line1, line2, line3, line4 }
  for i, fs in ipairs(fixed) do
    local l = lines[i]
    fs:SetText(l and string.format("|cff%02x%02x%02x%s|r", math.floor(l[2] * 255), math.floor(l[3] * 255), math.floor(l[4] * 255), l[1]) or "")
  end
  FitRows(math.max(0, #lines - 4))
  local lb, fb = line4:GetBottom(), frame:GetBottom()
  local fit = (lb and fb) and math.max(0, math.floor((lb - fb - 6) / ROW_H)) or 0
  local n = 0
  for i = 5, #lines do
    if n >= fit then break end
    local row = rows[n + 1]
    if not row then
      row = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
      row:SetPoint("TOPLEFT", line4, "BOTTOMLEFT", 0, -4 - n * ROW_H)
      row:SetPoint("RIGHT", -18, 0)
      row:SetJustifyH("LEFT")
      row:SetWordWrap(false)
      rows[n + 1] = row
    end
    n = n + 1
    local l = lines[i]
    row:SetText(string.format("|cff%02x%02x%02x%s|r", math.floor(l[2] * 255), math.floor(l[3] * 255), math.floor(l[4] * 255), l[1]))
    row:Show()
  end
  for k = n + 1, #rows do rows[k]:Hide() end
  return true
end

-- (the arrow's use button, in the arrow's place: anchored to the window itself, as the map's to its panel,
-- not to the texture there: in the game it wasn't over the icon to click, 2026-10-01)
A.USE_PX = 28
local function PlaceUse(b)
  b:SetSize(A.USE_PX, A.USE_PX)
  b:SetPoint("CENTER", frame, "LEFT", 8 + 29, 0) -- (the slot's middle: 8 in, 58 wide)
end
local function SetUse(t)
  local G = ns.GPS
  if useBtn and G and G.SetUseButton then G.SetUseButton(useBtn, t, PlaceUse) end
end
A.SetUse = SetUse

local function UpdateText(px, py, cont)
  local N = ns.Nav
  ns.Nav.Status(px, py, cont) -- keeps the route current and advances stops, even with the GPS hidden
  -- the route starting with a hearthstone or teleport from here (its step 1): said as that, with its
  -- button where the arrow is (asked, 2026-10-01: the turns of the walk after it were shown instead,
  -- out of step with the steps), the walk after it next
  local use = N.route and N.dest and not N.route.flying and not (N.questing and N.dest) and N.UseNow and N.UseNow() or nil
  SetUse(use)
  if not use then
    useIcon:Hide()
    useGlow:Hide()
  end
  if N.questing and N.dest then return QuestText(px, py, cont) end
  arrow:SetSize(58, 58)
  arrow:SetAlpha(1)
  arrow:ClearAllPoints()
  arrow:SetPoint("CENTER", slot, "CENTER")
  arrow:Show()
  useIcon:Hide()
  useGlow:Hide()
  bang:Hide()
  dist:Hide()
  local r, d = N.route, N.dest
  if r and N.RedAsking and N.RedAsking() then r = nil end -- (asked "keep this route?": not followed yet)
  if not d and N.areaQuests then
    -- no route, in a quest's area: its objectives, with a big "!"
    path, maneuvers = nil, nil
    arrow:Hide()
    bang:ClearAllPoints()
    bang:SetSize(40, 40)
    bang:SetPoint("CENTER", arrow, "CENTER")
    bang:Show()
    return RenderLines(N.QuestLines(N.areaQuests))
  end
  if not r or not d then
    path, maneuvers = nil, nil
    return false
  end
  if r.flying or use then -- in the air: where it lands and when; turns resume after landing (or the teleport)
    path, maneuvers = nil, {}
  else
    path = ns.Turns.Path(r)
    maneuvers = ns.Turns.Maneuvers(path, StopLabel(d, #N.stops))
  end
  local m = maneuvers[1]
  if N.areaQuests and not r.flying then
    -- in a quest's area on the way (not the stop's): its objectives first with a small
    -- "!" by the arrow, then the next turn and the stop, the arrow still leading on
    bang:ClearAllPoints()
    bang:SetSize(22, 22)
    bang:SetPoint("CENTER", arrow, "TOPRIGHT", -4, -4)
    bang:Show()
    local cur, walk, mount, mounted = N.Speeds()
    local speed = (cur and cur > 0.5) and cur or (mounted and mount or walk)
    local lines = N.QuestLines(N.areaQuests)
    if m then lines[#lines + 1] = { string.format("%s  |cffffffff%s|r", m.text, N.FormatDistance(m.dist)), 1, 0.82, 0 } end
    lines[#lines + 1] = { string.format("%s  |cffffffff%s|r  |cffffd100%s|r", StopLabel(d, #N.stops),
      N.FormatDistance(r.walkYards), N.FormatTime(r.walkYards / speed + r.rideSeconds)), 1, 1, 1 }
    return RenderLines(lines)
  end
  if r.flying then
    line1:SetText(string.format("%s %s", r.flying.verb or "Flying to", r.flying.to))
    line2:SetText((r.flying.when or "lands in") .. " " .. N.FormatTime(r.flying.seconds))
    arrow:SetRotation(0)
    arrow:SetVertexColor(0.6, 0.8, 1)
  elseif use then
    line1:SetText("Use " .. tostring(use[8]))
    line2:SetText(use[10] and use[10] ~= "" and ("to " .. use[10]) or "")
    arrow:Hide() -- (its icon there instead, glowing: click it)
    useIcon:SetTexture(ns.GPS and ns.GPS.UseTexture and ns.GPS.UseTexture(use) or 134400)
    useIcon:Show()
    useGlow:Show()
  elseif m then
    -- what to do now, then the maneuver: "Continue straight, then slight right in 13 yd" (shorter when
    -- the window is too narrow for it on one line)
    local function yd(v) return "|cffffffff" .. N.FormatDistance(v) .. "|r" end
    line1:SetText(ns.Turns.NowText(m, yd))
    if line1:GetStringWidth() > line1:GetWidth() + 1 then line1:SetText(ns.Turns.NowText(m, yd, true)) end
    -- (and the stop's height against yours, in a city: "Below you, 12 yd down")
    local hint = N.HeightText(px, py, cont)
    local toward = m.toward and ("toward " .. m.toward) or ""
    line2:SetText(hint and (toward ~= "" and toward .. "  " .. hint or hint) or toward)
  else
    line1:SetText("")
    line2:SetText("")
  end
  -- the stop: its marker and name, distance and ETA
  local cur, walk, mount, mounted = N.Speeds()
  local speed = (cur and cur > 0.5 and not r.flying) and cur or (mounted and mount or walk)
  local eta = N.FormatTime(r.walkYards / speed + r.rideSeconds)
  line3:SetText(string.format("%s  |cffffffff%s|r  |cffffd100%s|r%s", StopLabel(d, #N.stops),
    N.FormatDistance(r.walkYards), eta, #N.stops > 1 and string.format("  |cff9d9d9d(1/%d)|r", #N.stops) or ""))
  local nxt = maneuvers[2]
  line4:SetText(nxt and string.format("Then: %s in %s", nxt.text, N.FormatDistance(nxt.dist - (m and m.dist or 0))) or "")
  if use then -- (then the steps' second: the walk from where it lands)
    local steps = N.Steps()
    line4:SetText(steps[2] and ("Then: " .. steps[2]) or "")
  end
  -- the later stops, each with its distance and time from the stop before it
  local questLines = {}
  FitRows(0)
  local lb, fb = line4:GetBottom(), frame:GetBottom()
  local fit = (lb and fb) and math.max(0, math.floor((lb - fb - 6) / ROW_H)) or 0
  local n, count = 0, #N.stops
  local function Row()
    local row = rows[n + 1]
    if not row then
      row = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
      row:SetPoint("TOPLEFT", line4, "BOTTOMLEFT", 0, -4 - n * ROW_H)
      row:SetPoint("RIGHT", -18, 0)
      row:SetJustifyH("LEFT")
      row:SetWordWrap(false)
      rows[n + 1] = row
    end
    n = n + 1
    row:Show()
    return row
  end
  for _, l in ipairs(questLines) do
    if n >= fit then break end
    Row():SetText(string.format("|cff%02x%02x%02x%s|r", math.floor(l[2] * 255), math.floor(l[3] * 255), math.floor(l[4] * 255), l[1]))
  end
  for i = 2, count do
    if n >= fit then break end
    local row = rows[n + 1]
    if not row then
      row = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
      row:SetPoint("TOPLEFT", line4, "BOTTOMLEFT", 0, -4 - n * ROW_H)
      row:SetPoint("RIGHT", -18, 0)
      row:SetJustifyH("LEFT")
      row:SetWordWrap(false)
      rows[n + 1] = row
    end
    n = n + 1
    if n == fit and count - i > 0 then
      row:SetText(string.format("|cff9d9d9d... %d more stop%s|r", count - i + 1, count - i + 1 > 1 and "s" or ""))
    else
      local d, st = N.stops[i], r.stretches and r.stretches[i]
      local label = string.format("|T%s:12|t %s", N.StopIcon(d), d.name or ("stop " .. i))
      if st then
        row:SetText(string.format("%d. %s  |cffffffff%s|r  |cffffd100%s|r", i, label, N.FormatDistance(st.walk),
          N.FormatTime(st.walk / speed + st.ride)))
      else
        row:SetText(string.format("%d. %s", i, label))
      end
    end
    row:Show()
  end
  for k = n + 1, #rows do rows[k]:Hide() end
  return true
end

local function Update(dt)
  local px, py, cont = Geo.PlayerWorld()
  -- a quest picked up since the quest route was made: the Sprint icon pulses in the corner
  local N = ns.Nav
  if N.questRouteStale and not N.OnQuestRoute() then N.questRouteStale = nil end
  if N.questRouteStale then
    stale:SetAlpha(0.55 + 0.45 * math.sin(GetTime() * 4))
    stale:Show()
  else
    stale:Hide()
  end
  if useIcon:IsShown() then -- (the hearthstone's icon in the arrow's place: glowing, as the remake button pulses)
    local a = 0.55 + 0.45 * math.sin(GetTime() * 4)
    useIcon:SetAlpha(0.75 + 0.25 * a)
    useGlow:SetAlpha(a)
  end
  textWait = textWait - dt
  if textWait <= 0 then
    textWait = TEXT_EVERY
    -- no route: invisible and click-through (kept shown so this keeps checking)
    local active = px and UpdateText(px, py, cont)
    -- no route: hidden and click-through, except while unlocked (to place and size it)
    local placing = not active and not S().arrowLocked
    if placing then
      line1:SetText("|cff9d9d9dNo route|r")
      line2:SetText("Set one on the map: double-click a spot, or pan and Confirm Route.")
      line3:SetText("|cff9d9d9dDrag to move, corner to resize. Shown like this while unlocked.|r")
      line4:SetText("")
      for _, row in ipairs(rows) do row:Hide() end
      arrow:SetRotation(0)
      arrow:SetVertexColor(0.5, 0.5, 0.5)
    end
    local show = active or placing
    frame:SetAlpha(show and Alpha() or 0)
    -- click-through (options): in combat, and/or while moving
    local st = S()
    local moving = ns.GPS and ns.GPS.PlayerMoving and ns.GPS.PlayerMoving()
    -- locked: always click-through (nothing to click on it then; unlocked it's dragged)
    local through = st.arrowLocked or (st.clickThroughCombat and ns.inCombat) or (st.clickThroughMoving and moving)
    frame:EnableMouse(show and not through)
    grip:SetShown(show and not S().arrowLocked)
    if not active then return end
  end
  if not px or not path then return end
  local tx, ty = ns.Turns.Target(path)
  if not tx then return end
  local rel = ns.Turns.RelativeAngle(px, py, Geo.Facing(), tx, ty)
  arrow:SetRotation(rel)
  -- green when heading the right way, gold for a turn, red when it's behind you
  local a = math.abs(rel)
  if a < math.rad(20) then arrow:SetVertexColor(0.45, 1, 0.45)
  elseif a < math.rad(100) then arrow:SetVertexColor(1, 1, 1)
  else arrow:SetVertexColor(1, 0.45, 0.35) end
  -- orange at a drop off a ledge coming up: jump down there
  local m1 = maneuvers and maneuvers[1]
  if m1 and m1.kind == "drop" and m1.dist <= 12 then arrow:SetVertexColor(1, 0.55, 0.1) end
  local jump = m1 and m1.kind == "drop" and m1.dist <= 15
  jumpIcon:SetShown(jump and true or false)
  if jump then jumpIcon:SetAlpha(0.55 + 0.45 * math.sin(GetTime() * 7)) end
end

-- Errors are reported once (else the window would just stay invisible).
local sinceUpdate = 0
local function OnUpdate(_, dt)
  -- the map window runs the route's background searches; while it's hidden, this does
  if ns.GPS and ns.GPS.IsVisible and not ns.GPS.IsVisible() then
    ns.GPS.PumpSearches()
    ns.Nav.Tick() -- (the map's redraw does this while it shows: clears an arrived trip)
  end
  -- (Options > Performance: the arrow turned at most arrowHz times a second; 0: every frame)
  sinceUpdate = sinceUpdate + dt
  local hz = S().arrowHz or 0
  if hz > 0 and sinceUpdate < 1 / hz then return end
  dt, sinceUpdate = sinceUpdate, 0
  local t0 = ns.PerfStart and ns.PerfStart()
  local ok, err = pcall(Update, dt)
  if t0 then ns.PerfEnd("arrow window", t0) end
  if not ok then
    A.lastError = tostring(err)
    if not A.errorShown then
      A.errorShown = true
      ns.Print("direction arrow error: " .. A.lastError)
    end
  end
end

function A.Describe()
  if not frame then return "not created" end
  return string.format("shown=%s visible=%s alpha=%.2f route=%s size=%.0fx%.0f%s", tostring(frame:IsShown()),
    tostring(frame:IsVisible()), frame:GetAlpha(), tostring(ns.Nav.route ~= nil), frame:GetWidth(), frame:GetHeight(),
    A.lastError and (" error: " .. A.lastError) or "")
end

function A.Apply()
  if not frame then return end
  local st = S()
  local p = st.arrowPoint
  frame:ClearAllPoints()
  frame:SetPoint(p[1], _G[p[2]] or UIParent, p[3], p[4], p[5])
  frame:SetMovable(not st.arrowLocked)
  frame:SetResizable(not st.arrowLocked)
  local size = st.arrowSize or { 250, 86 }
  frame:SetSize(size[1], size[2])
  frame:SetBackdropColor(0, 0, 0, st.arrowBg or 0.55)
  grip:SetShown(not st.arrowLocked)
  frame:SetShown(st.arrow and not (ns.inCombat and st.combatHideArrow))
  textWait = 0 -- refresh now
end

function A.Init()
  if frame then return end
  frame = CreateFrame("Frame", "AzerothGPSArrow", UIParent, "BackdropTemplate")
  frame:SetSize(250, 86)
  if frame.SetResizeBounds then frame:SetResizeBounds(190, 70, 700, 600)
  elseif frame.SetMinResize then frame:SetMinResize(190, 70) end
  frame:SetFrameStrata("MEDIUM")
  frame:SetClampedToScreen(true)
  frame:EnableMouse(true)
  frame:RegisterForDrag("LeftButton")
  frame:SetScript("OnDragStart", function(f) if not S().arrowLocked then f:StartMoving() end end)
  frame:SetScript("OnDragStop", function(f)
    f:StopMovingOrSizing()
    SavePosition()
  end)
  frame:SetBackdrop({ bgFile = "Interface\\Buttons\\WHITE8X8" })
  frame:SetBackdropColor(0, 0, 0, 0.55)

  -- resize grip (bottom-right), while the arrow is unlocked
  -- the quest route is missing a new quest (see Update): click it to remake the route. Its
  -- own button, so it takes clicks even while the window is click-through (locked)
  stale = CreateFrame("Button", nil, frame)
  stale:SetSize(18, 18)
  stale:SetPoint("TOPRIGHT", -3, -3)
  stale:SetFrameLevel(frame:GetFrameLevel() + 5)
  local sicon = stale:CreateTexture(nil, "ARTWORK")
  sicon:SetAllPoints()
  sicon:SetTexture(SPRINT_ICON)
  sicon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
  local shl = stale:CreateTexture(nil, "HIGHLIGHT")
  shl:SetAllPoints()
  shl:SetColorTexture(1, 1, 1, 0.25)
  stale:SetScript("OnClick", function()
    if ns.GPS and ns.GPS.QuestRoute then ns.GPS.QuestRoute() end
  end)
  stale:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_LEFT")
    GameTooltip:SetText("Quest Route", 1, 1, 1)
    GameTooltip:AddLine("You picked up a quest since this quest route was made. Click to make it again with the new quest.", nil, nil, nil, true)
    GameTooltip:Show()
  end)
  stale:SetScript("OnLeave", GameTooltip_Hide)
  stale:Hide()

  grip = CreateFrame("Button", nil, frame)
  grip:SetSize(14, 14)
  grip:SetPoint("BOTTOMRIGHT", -2, 2)
  grip:SetNormalTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Up")
  grip:SetHighlightTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Highlight")
  grip:SetPushedTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Down")
  grip:SetScript("OnMouseDown", function() if not S().arrowLocked then frame:StartSizing("BOTTOMRIGHT") end end)
  grip:SetScript("OnMouseUp", function()
    frame:StopMovingOrSizing()
    S().arrowSize = { math.floor(frame:GetWidth() + 0.5), math.floor(frame:GetHeight() + 0.5) }
    SavePosition()
    textWait = 0 -- relist the stops for the new size
  end)

  arrow = frame:CreateTexture(nil, "ARTWORK")
  arrow:SetSize(58, 58)
  -- a drop off a ledge coming up: a flashing jump icon by the arrow
  jumpIcon = frame:CreateTexture(nil, "OVERLAY")
  jumpIcon:SetSize(24, 24)
  jumpIcon:SetPoint("CENTER", arrow, "BOTTOMLEFT", 6, 6)
  jumpIcon:SetTexture("Interface\\Icons\\Spell_Magic_FeatherFall")
  jumpIcon:Hide()
  -- the arrow's spot: fixed, so a smaller arrow (questing) stays centered in it and the
  -- text beside doesn't move
  slot = frame:CreateTexture(nil, "BACKGROUND")
  slot:SetSize(58, 58)
  slot:SetPoint("LEFT", 8, 0)
  arrow:SetPoint("CENTER", slot, "CENTER")
  ns.SetIcon(arrow, "atlas:" .. ARROW_ATLAS, ARROW_FILE)
  -- (the route's first step a hearthstone or teleport: its icon in the arrow's place, glowing, and its
  -- button over it: the window's own texture shows it whatever the secure button does)
  useIcon = frame:CreateTexture(nil, "ARTWORK")
  useIcon:SetSize(A.USE_PX, A.USE_PX)
  useIcon:SetPoint("CENTER", slot, "CENTER")
  useIcon:Hide()
  useGlow = frame:CreateTexture(nil, "OVERLAY")
  useGlow:SetTexture("Interface\\Buttons\\UI-ActionButton-Border")
  useGlow:SetBlendMode("ADD")
  useGlow:SetVertexColor(1, 0.85, 0.3)
  useGlow:SetSize(A.USE_PX * 1.9, A.USE_PX * 1.9)
  useGlow:SetPoint("CENTER", useIcon, "CENTER")
  useGlow:Hide()
  if ns.GPS and ns.GPS.NewUseButton then
    useBtn = ns.GPS.NewUseButton("AzerothGPSArrowUseButton", frame, A.USE_PX)
    if useBtn then useBtn.icon:SetAlpha(0) end -- (clear: the icon under it is the window's)
  end
  bang = frame:CreateTexture(nil, "ARTWORK")
  bang:SetSize(40, 40)
  bang:SetPoint("CENTER", arrow, "CENTER")
  bang:SetTexture(QUEST_ICON)
  bang:Hide()
  dist = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall") -- questing: yards to the spot
  dist:SetPoint("TOP", arrow, "BOTTOM", 0, -2)
  dist:SetWidth(70) -- within the arrow's column (wraps there)
  dist:SetJustifyH("CENTER")
  dist:Hide()

  line1 = frame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  line1:SetPoint("TOPLEFT", slot, "TOPRIGHT", 8, 2)
  line1:SetPoint("RIGHT", -8, 0)
  line1:SetJustifyH("LEFT")
  line2 = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  line2:SetPoint("TOPLEFT", line1, "BOTTOMLEFT", 0, -2)
  line2:SetPoint("RIGHT", -8, 0)
  line2:SetJustifyH("LEFT")
  line3 = frame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  line3:SetPoint("TOPLEFT", line2, "BOTTOMLEFT", 0, -4)
  line3:SetPoint("RIGHT", -8, 0)
  line3:SetJustifyH("LEFT")
  line4 = frame:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  line4:SetPoint("TOPLEFT", line3, "BOTTOMLEFT", 0, -3)
  line4:SetPoint("RIGHT", -8, 0)
  line4:SetJustifyH("LEFT")

  frame:SetScript("OnUpdate", OnUpdate)
  frame:SetAlpha(0)
  frame:EnableMouse(false)
  A.Apply()
end

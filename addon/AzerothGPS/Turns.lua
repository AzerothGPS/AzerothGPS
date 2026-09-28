-- Turn-by-turn: the maneuvers ahead on the route (turns, joining/leaving the road,
-- boarding a zeppelin or boat, arriving at a stop) and where the direction arrow points.
-- Pure Lua (no frames), unit-tested with lupa.
local _, ns = ...

local T = {}
ns.Turns = T

T.WINDOW = 35 -- yards before/after a point to measure how much the route bends there
T.MIN_ANGLE = 35 -- degrees: off-road, a curve turning less than this is just "continue"
T.JUNCTION_ANGLE = 25 -- degrees: at a road junction, from this much it's a turn
T.ROAD_BEND_ANGLE = 75 -- degrees: along a road away from junctions, only bends this sharp
T.BEND_START = 8 -- degrees: points bending at least this much belong to a curve
T.END_QUIET = 25 -- yards: no instructions this close to the stop ("Arrive" covers it)
T.HOP_YD = 60 -- yards: briefer stretches on (or off) a road aren't announced
T.MIN_AHEAD = 5 -- yards: bends closer than this are already being taken
T.JOG_YD = 60 -- yards: turns this close together are one run (a jog, if it nets out)
T.JOG_OFFSET = 12 -- yards: ... and a jog when the route after it is this close to the line before it
T.LOOKAHEAD = 30 -- the arrow points at the route this far ahead
T.TOWARD_AHEAD = 350 -- "toward <place>": a named place near the route this far past the turn
T.TOWARD_RADIUS = 450

local atan2 = math.atan2 or math.atan

local function Dist(x1, y1, x2, y2)
  return math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2)
end

-- The walk ahead, from the player to the next stop or dock: the route's first parts that
-- lead to stop 1 on the player's continent, up to a transport ride.
-- { pts = { x, y, ... }, kinds, cum, total, cont, ends = "stop" | "ride", ride, from }
function T.Path(route)
  if not route or not route.parts or not route.parts[1] then return nil end
  local first = route.parts[1]
  local path = { pts = {}, kinds = {}, cum = { 0 }, cont = first.cont, ends = "stop" }
  local pts, kinds, cum = path.pts, path.kinds, path.cum
  for _, part in ipairs(route.parts) do
    if part.stop ~= first.stop or part.cont ~= first.cont then break end
    if part.kinds[1] == (ns.Nav and ns.Nav.KIND_TRANSPORT or 2) then
      path.ends = "ride"
      break
    end
    for i = 1, #part.pts, 2 do
      local x, y = part.pts[i], part.pts[i + 1]
      local n = #pts
      if n == 0 or math.abs(pts[n - 1] - x) > 0.01 or math.abs(pts[n] - y) > 0.01 then
        if n > 0 then
          cum[#cum + 1] = cum[#cum] + Dist(pts[n - 1], pts[n], x, y)
          kinds[#kinds + 1] = part.kinds[(i - 1) / 2] or part.kinds[1]
        end
        pts[n + 1], pts[n + 2] = x, y
      end
    end
  end
  if path.ends == "ride" then
    for _, leg in ipairs(route.legs or {}) do
      if leg.ride then
        path.ride, path.from = leg.ride, leg.from
        break
      end
    end
  end
  path.total = cum[#cum]
  return path
end

-- Point `s` yards along the path (clamped to its ends).
function T.PointAt(path, s)
  local pts, cum = path.pts, path.cum
  if s <= 0 or #cum < 2 then return pts[1], pts[2] end
  for i = 2, #cum do
    if cum[i] >= s then
      local seg = cum[i] - cum[i - 1]
      local t = seg > 0 and (s - cum[i - 1]) / seg or 0
      return pts[2 * i - 3] + (pts[2 * i - 1] - pts[2 * i - 3]) * t, pts[2 * i - 2] + (pts[2 * i] - pts[2 * i - 2]) * t
    end
  end
  return pts[#pts - 1], pts[#pts]
end

-- Signed bend (degrees, + = left, as seen on a north-up map) at `s` along the path.
local function Bend(path, s)
  local ax, ay = T.PointAt(path, s - T.WINDOW)
  local bx, by = T.PointAt(path, s)
  local cx, cy = T.PointAt(path, s + T.WINDOW)
  local d1x, d1y, d2x, d2y = bx - ax, by - ay, cx - bx, cy - by
  if d1x * d1x + d1y * d1y < 1 or d2x * d2x + d2y * d2y < 1 then return 0 end
  -- X is north, Y is west: west of north is to the left
  local a1, a2 = atan2(d1y, d1x), atan2(d2y, d2x)
  local d = math.deg(a2 - a1)
  while d > 180 do d = d - 360 end
  while d < -180 do d = d + 360 end
  return d
end
T.Bend = Bend

function T.TurnText(angle)
  local a, side = math.abs(angle), angle > 0 and "left" or "right"
  if a >= 160 then return "Make a U-turn" end
  if a >= 120 then return "Sharp " .. side end
  if a >= 60 then return "Turn " .. side end
  return "Slight " .. side
end

local COMPASS = { "north", "north-west", "west", "south-west", "south", "south-east", "east", "north-east" }
-- Compass direction of a heading (X north, Y west).
function T.Compass(dx, dy)
  local a = math.deg(atan2(dy, dx)) -- 0 = north, 90 = west
  return COMPASS[math.floor(((a % 360) + 22.5) / 45) % 8 + 1]
end

-- A named place near the route past distance s (for "toward <place>").
local function Toward(path, s)
  local list = ns.Pois and ns.Pois[path.cont]
  if not list then return nil end
  local px, py = T.PointAt(path, s)
  local qx, qy = T.PointAt(path, math.min(path.total, s + T.TOWARD_AHEAD))
  if Dist(px, py, qx, qy) < 50 then return nil end
  local best, bestD
  for _, p in ipairs(list) do
    if p[1] == 2 or p[1] == 3 then
      local d = Dist(qx, qy, p[2], p[3])
      local ahead = (p[2] - px) * (qx - px) + (p[3] - py) * (qy - py) > 0
      if d <= T.TOWARD_RADIUS and ahead and (not bestD or d < bestD) then best, bestD = p[4], d end
    end
  end
  return best
end

-- The maneuvers ahead, nearest first: { dist, kind, text, toward, angle }.
-- kind: "turn", "join" (onto the road), "leave" (off the road), "board", "arrive".
-- stopLabel: how the next stop is named ("stop 1", a place name...).
function T.Maneuvers(path, stopLabel)
  local out = {}
  if not path or not path.total then return out end
  local pts, cum, kinds = path.pts, path.cum, path.kinds
  -- curves: runs of points bending the same way; a curve is one turn, by how much the
  -- direction changes from before it to after it, at its sharpest point
  local function heading(s1, s2)
    local ax, ay = T.PointAt(path, s1)
    local bx, by = T.PointAt(path, s2)
    return atan2(by - ay, bx - ax)
  end
  local R = ns.Router
  local group
  local function flush()
    if group then
      local W = T.WINDOW
      local a = math.deg(heading(group.last, group.last + W) - heading(group.first - W, group.first))
      while a > 180 do a = a - 360 end
      while a < -180 do a = a + 360 end
      -- like a car GPS: on roads, speak at junctions; road curves elsewhere only when sharp
      local onRoad, junction, js = false, false, nil
      for i = group.i0, group.i1 do
        if kinds[i - 1] == 0 or kinds[i] == 0 then onRoad = true end
        if not junction and R and R.JunctionAt and R.JunctionAt(path.cont, pts[2 * i - 1], pts[2 * i]) then
          junction, js = true, cum[i]
        end
      end
      local need = not onRoad and T.MIN_ANGLE or junction and T.JUNCTION_ANGLE or T.ROAD_BEND_ANGLE
      if math.abs(a) >= need then
        local s = js or group.s
        out[#out + 1] = { dist = s, kind = "turn", angle = a, text = T.TurnText(a), toward = Toward(path, s) }
      end
      group = nil
    end
  end
  local DROP = R and R.KIND_DROP or 4
  local function roadish(k) return k == 0 or k == DROP end
  for i = 2, #cum - 1 do
    local s = cum[i]
    -- a drop off a ledge starts here (said however near it is)
    if kinds[i] == DROP and kinds[i - 1] ~= DROP then
      out[#out + 1] = { dist = s, kind = "drop", text = "Jump down here" }
    end
    if s >= T.MIN_AHEAD then
      local a = Bend(path, s)
      if math.abs(a) >= T.BEND_START then
        if group and s - group.last <= T.WINDOW and (a > 0) == (group.sign > 0) then
          if math.abs(a) > group.peak then group.peak, group.s = math.abs(a), s end
          group.last, group.i1 = s, i
        else
          flush()
          group = { s = s, first = s, last = s, peak = math.abs(a), sign = a, i0 = i, i1 = i }
        end
      end
      -- road transitions at this vertex
      local k1, k2 = kinds[i - 1], kinds[i]
      if roadish(k1) ~= roadish(k2) then
        out[#out + 1] = { dist = s, kind = k2 == 0 and "join" or "leave",
          text = k2 == 0 and "Join the road" or "Leave the road" }
      end
    end
  end
  flush()
  table.sort(out, function(a, b) return a.dist < b.dist end)
  -- a jog: turns close together that net out and bring the route back onto the line it
  -- was on (out and back) are no turn at all: straight on
  local skip = {}
  local i = 1
  while i <= #out do
    if out[i].kind == "turn" then
      local run, last = { i }, out[i].dist
      for j = i + 1, #out do
        if out[j].dist - last > T.JOG_YD then break end
        if out[j].kind == "turn" then
          run[#run + 1] = j
          last = out[j].dist
        end
      end
      if #run >= 2 then
        local net = 0
        for _, j in ipairs(run) do net = net + out[j].angle end
        local s0, s1 = out[run[1]].dist, out[run[#run]].dist
        local ax, ay = T.PointAt(path, s0 - T.WINDOW)
        local bx, by = T.PointAt(path, s0)
        local cx, cy = T.PointAt(path, math.min(path.total, s1 + T.WINDOW))
        local L = Dist(ax, ay, bx, by)
        local off = L > 0 and math.abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / L or math.huge
        -- (not on hilly ground: winding there may be the way up, and worth saying)
        local hilly = false
        local P = ns.Passability
        if P and P.Hilly then
          for s = math.max(0, s0 - T.WINDOW), math.min(path.total, s1 + T.WINDOW), 10 do
            local hx, hy = T.PointAt(path, s)
            if P.Hilly(path.cont, hx, hy) then hilly = true break end
          end
        end
        if math.abs(net) < T.MIN_ANGLE and off <= T.JOG_OFFSET and not hilly then
          for _, j in ipairs(run) do skip[j] = true end
        end
      end
      i = run[#run] + 1
    else
      i = i + 1
    end
  end
  local kept = {}
  for j, m in ipairs(out) do
    if not skip[j] then kept[#kept + 1] = m end
  end
  out = kept
  local merged = {}
  for _, m in ipairs(out) do
    local prev = merged[#merged]
    if m.dist > path.total - T.END_QUIET then
      -- arriving: nothing more to say
    elseif prev and m.dist - prev.dist < T.HOP_YD and (m.kind == "join" or m.kind == "leave")
        and (prev.road == "join" or prev.road == "leave") and prev.road ~= m.kind then
      -- a short hop onto a road and off again (or off and back on): not worth an instruction
      if prev.kind == "turn" then
        prev.text, prev.road, prev.merged = prev.turnText, nil, nil -- keep the turn itself
      else
        merged[#merged] = nil
      end
    elseif prev and m.dist - prev.dist < 15 and not prev.merged and ((prev.kind == "turn") ~= (m.kind == "turn")) then
      -- a turn right where the route joins/leaves a road reads as one instruction
      local turn, road = prev.kind == "turn" and prev or m, prev.kind == "turn" and m or prev
      local text = turn.text .. (road.kind == "join" and " onto the road" or " off the road")
      prev.turnText, prev.road = turn.text, road.kind
      prev.kind, prev.angle, prev.toward, prev.text, prev.merged = "turn", turn.angle, turn.toward, text, true
    else
      if m.kind == "join" or m.kind == "leave" then m.road = m.kind end
      merged[#merged + 1] = m
    end
  end
  if path.ends == "ride" and path.ride then
    local t = path.ride
    merged[#merged + 1] = { dist = path.total, kind = "board",
      text = t.use and string.format("Use %s (to %s)", t[8], t[10])
        or string.format("Board the %s to %s", t[8], path.from == 1 and t[10] or t[9]) }
  else
    merged[#merged + 1] = { dist = path.total, kind = "arrive", text = "Arrive at " .. (stopLabel or "your destination") }
  end
  return merged
end

-- Where the direction arrow points: the route LOOKAHEAD yards ahead (or its end).
function T.Target(path)
  if not path or not path.total then return nil end
  if path.total <= T.LOOKAHEAD then return T.PointAt(path, path.total) end
  -- (averaged over the stretch around it: a kink there doesn't swing the arrow)
  local sx, sy, n = 0, 0, 0
  for s = T.LOOKAHEAD * 0.6, math.min(T.LOOKAHEAD * 1.4, path.total), T.LOOKAHEAD * 0.2 do
    local x, y = T.PointAt(path, s)
    sx, sy, n = sx + x, sy + y, n + 1
  end
  return sx / n, sy / n
end

-- The arrow's rotation for a player at (px, py) facing `facing` looking at (tx, ty):
-- 0 = straight ahead, positive = to the left (as Texture:SetRotation turns).
function T.RelativeAngle(px, py, facing, tx, ty)
  local a = atan2(ty - py, tx - px) - (facing or 0)
  while a > math.pi do a = a - 2 * math.pi end
  while a < -math.pi do a = a + 2 * math.pi end
  return a
end

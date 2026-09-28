-- Routing over the road network (Data/Roads.lua). Pure Lua, unit-tested with lupa.
--
-- Road mode (default): walk to a nearby road, follow roads, leave the road at the
-- point closest to the destination. Straight only when that is shorter than just
-- getting on and off the road.
-- Offroad mode ("riskier but faster"): straight across open ground when the terrain
-- allows (Passability.lua); where it doesn't, straight legs to/from the roads that get
-- through (passes, bridges) and roads in between.
local _, ns = ...

local R = {}
ns.Router = R

R.OFFROAD_PENALTY = 1.25 -- road mode: off-road yards cost this much more than road yards
R.KIND_ROAD, R.KIND_OFFROAD = 0, 1
R.KIND_DROP = 4 -- off a ledge onto the floor below (Nav's own kinds are 2 and 3)
R.DROP_COST = 30 -- yards a drop counts extra: taken only when it saves real distance
R.OFFROAD_LINKS = 24 -- offroad mode: straight links tried from start/destination to road nodes
R.OFFROAD_LINK_MAX = 3000 -- yards
R.OFFROAD_TIE = 1.02 -- offroad mode: open ground costs a hair more, so roads win ties
R.BLOCKED_PENALTY = 12 -- a leg the terrain data calls blocked, when nothing better exists
R.WALL_PENALTY = 200 -- ... through a wall drawn with the road tools (only when there's no other way at all)
R.HOSTILE_FACTOR = 20 -- a yard within reach of the other faction's guards (Data/Hostile.lua) costs this many
R.HOSTILE_STEP = 5 -- yards between the points checked along a leg
R.CITY_BLOCKED_PENALTY = 200 -- the same in a city (its grid's walls are real walls)
R.ENTRY_CANDIDATES = 8 -- road edges tried for getting on and off the road network
R.ENTRY_SLACK = 400 -- yards: candidates up to this much farther than the nearest road
R.ON_ROAD_YD = 8 -- a straight leg this close to a road is drawn (and counted) as road
R.ON_ROAD_MIN = 25 -- yards: shorter stretches along a road stay off-road
R.NODE_LINKS = 8 -- offroad mode: straight shortcuts from each road node, one per direction
R.NODE_LINK_MAX = 1500 -- yards
R.NODE_LINK_TRIES = 3 -- ... the nearest this many nodes tried in each direction (past rock, give that one up)
R.NODE_LINK_MS = 12 -- ... worked out for this long per route calculation, the rest in the background (a long
-- route's search reaches thousands of nodes: done at once, the game froze)
R.OFFROAD_WALK_AROUND = 3000 -- yards: offroad trips up to this long may walk around obstacles
R.OFFROAD_ALONG_STEP = 50 -- offroad mode: points this far apart along nearby roads, to join or leave them
R.OFFROAD_ALONG_MAX = 700 -- ... within this many yards of the start or the destination
R.WALK_AROUND_CANDIDATES = 3 -- only the nearest few get-on/get-off legs search the terrain grid
-- Road mode: walking straight there (around obstacles) instead, off the roads the whole way,
-- counts this much per yard; so the roads are kept unless they're about twice as long, or
-- only reached across blocked ground. Trips up to OFFROAD_WALK_AROUND yards.
R.ROAD_DIRECT_PENALTY = 2
local BUCKET = 50
local NODE_BUCKET = 500

local graphs = {}

R.TRACK_SNAP = 25 -- yards: a drawn road's end joins an existing road this close
R.TRACK_SNAP_CITY = 8 -- ... in a city down below (levels over each other)
R.TRACK_REMOVE_YD = 12 -- an erased ("false road") track removes road this close to it
-- A drawn road is truth: where it runs along an existing road (this close, about parallel,
-- for a while) it replaces that stretch, and the road's cut ends join it. Where it crosses
-- or touches a road it's joined there (a junction); its ends join a road within TRACK_SNAP.
R.TRACK_OVERLAP = 12 -- yards
R.TRACK_OVERLAP_CITY = 4
R.TRACK_ALONG_COS = 0.866 -- about parallel: within 30 degrees
R.TRACK_ALONG_MIN = 15 -- yards: shorter stretches along a road (not at its ends) don't replace it
R.TRACK_ALONG_MIN_CITY = 4
R.TRACK_CROSS = 3 -- yards: a drawn road this close to a road it isn't along crosses it
R.TRACK_CROSS_CITY = 1.5
R.TRACK_STUB = 15 -- yards: a cut road's dead-end stub shorter than this goes

local function PolyLength(pts)
  local len = 0
  for i = 1, #pts - 3, 2 do
    len = len + math.sqrt((pts[i + 2] - pts[i]) ^ 2 + (pts[i + 3] - pts[i + 1]) ^ 2)
  end
  return len
end

-- Split an edge's polyline at `along` yards: the points before (ending at the split point)
-- and after (starting at it).
local function SplitPolyline(e, along)
  local a, b = {}, {}
  local acc, done = 0, false
  for i = 5, #e - 3, 2 do
    local ax, ay, bx, by = e[i], e[i + 1], e[i + 2], e[i + 3]
    local seg = math.sqrt((bx - ax) ^ 2 + (by - ay) ^ 2)
    if not done then
      a[#a + 1], a[#a + 2] = ax, ay
      if acc + seg >= along then
        local t = seg > 0 and (along - acc) / seg or 0
        local qx, qy = ax + (bx - ax) * t, ay + (by - ay) * t
        a[#a + 1], a[#a + 2] = qx, qy
        b[#b + 1], b[#b + 2] = qx, qy
        done = true
      end
    else
      b[#b + 1], b[#b + 2] = ax, ay
    end
    acc = acc + seg
  end
  b[#b + 1], b[#b + 2] = e[#e - 1], e[#e]
  return a, b
end

R.SOURCE_RECORDED = 9 -- edge source flag (e[4]) of the player's drawn roads (not yet in the data)

local function MakeEdge(na, nb, pts, source)
  local e = { na, nb, PolyLength(pts), source or 0 }
  for i = 1, #pts do e[4 + i] = pts[i] end
  return e
end

-- Whether (x, y) is inside the loop `poly` (flat points; closed back to its first).
function R.InPolygon(poly, x, y)
  local inside, n = false, #poly / 2
  local jx, jy = poly[2 * n - 1], poly[2 * n]
  for i = 1, n do
    local ix, iy = poly[2 * i - 1], poly[2 * i]
    if (iy > y) ~= (jy > y) and x < (jx - ix) * (y - iy) / (jy - iy) + ix then inside = not inside end
    jx, jy = ix, iy
  end
  return inside
end

-- A cave's ways out (Data/Caves.lua: its roads out of the mouth end on the continent's
-- nearest road) joined onto that road: the road there is split at the point nearest each
-- one's end (within JOIN_SNAP) and the two tied together. `nodes`, `edges`: the network
-- being merged (changed in place); the continent's roads are edges[1..nRoads]; `joins`:
-- the cave roads' node numbers (after `base`).
R.JOIN_SNAP = 12 -- yards
local JOIN_BUCKET = 64
function R.JoinOnto(nodes, edges, nRoads, base, joins)
  local want = {}
  for ji, j in ipairs(joins) do
    local x, y = nodes[(base + j) * 2 - 1], nodes[(base + j) * 2]
    local k = math.floor(x / JOIN_BUCKET) * 65536 + math.floor(y / JOIN_BUCKET)
    want[k] = want[k] or {}
    table.insert(want[k], ji)
  end
  local snap2 = R.JOIN_SNAP * R.JOIN_SNAP
  local best = {} -- [ji] = { d2, edge }
  local function near(x, y, ax, ay, bx, by)
    local vx, vy = bx - ax, by - ay
    local L2 = vx * vx + vy * vy
    local t = L2 > 0 and math.max(0, math.min(1, ((x - ax) * vx + (y - ay) * vy) / L2)) or 0
    local dx, dy = ax + vx * t - x, ay + vy * t - y
    return dx * dx + dy * dy, ax + vx * t, ay + vy * t
  end
  for ei = 1, nRoads do
    if ei % 200 == 0 then
      local co, main = coroutine.running()
      if co and not main then coroutine.yield() end
    end
    local e = edges[ei]
    for i = 5, e[4] == 3 and 0 or #e - 3, 2 do -- (not onto a drop off a ledge: source 3)
      local ax, ay, bx, by = e[i], e[i + 1], e[i + 2], e[i + 3]
      for kx = math.floor((math.min(ax, bx) - R.JOIN_SNAP) / JOIN_BUCKET), math.floor((math.max(ax, bx) + R.JOIN_SNAP) / JOIN_BUCKET) do
        for ky = math.floor((math.min(ay, by) - R.JOIN_SNAP) / JOIN_BUCKET), math.floor((math.max(ay, by) + R.JOIN_SNAP) / JOIN_BUCKET) do
          for _, ji in ipairs(want[kx * 65536 + ky] or {}) do
            local j = base + joins[ji]
            local d2 = near(nodes[j * 2 - 1], nodes[j * 2], ax, ay, bx, by)
            if d2 <= snap2 and (not best[ji] or d2 < best[ji][1]) then best[ji] = { d2, e } end
          end
        end
      end
    end
  end
  -- (one at a time: a road split for one join may be split again for the next, in its part)
  local index = {}
  for ei = 1, nRoads do index[edges[ei]] = ei end
  local parts = {} -- [original edge] = { its parts (edges), ... }
  for ji, b in pairs(best) do
    local j = base + joins[ji]
    local jx, jy = nodes[j * 2 - 1], nodes[j * 2]
    local pick, pi, bd, qx, qy = nil, nil, math.huge, nil, nil
    for _, e in ipairs(parts[b[2]] or { b[2] }) do
      for i = 5, #e - 3, 2 do
        local d2, px, py = near(jx, jy, e[i], e[i + 1], e[i + 2], e[i + 3])
        if d2 < bd then pick, pi, bd, qx, qy = e, i, d2, px, py end
      end
    end
    local ei = index[pick]
    local first, second = {}, { qx, qy }
    for i = 5, pi + 1 do first[#first + 1] = pick[i] end
    first[#first + 1], first[#first + 2] = qx, qy
    for i = pi + 2, #pick do second[#second + 1] = pick[i] end
    nodes[#nodes + 1], nodes[#nodes + 2] = qx, qy
    local q = #nodes / 2
    local ea, eb = MakeEdge(pick[1], q, first, pick[4]), MakeEdge(q, pick[2], second, pick[4])
    edges[ei] = ea
    edges[#edges + 1] = eb
    index[ea], index[eb], index[pick] = ei, #edges, nil
    local list = parts[b[2]] or { b[2] }
    for k, e in ipairs(list) do
      if e == pick then table.remove(list, k) break end
    end
    list[#list + 1], list[#list + 2] = ea, eb
    parts[b[2]] = list
    edges[#edges + 1] = MakeEdge(q, j, { qx, qy, jx, jy })
  end
end

-- The road data plus the player's drawn roads (Record.lua), in their order: "add" tracks
-- become roads (replacing the stretches of road they run along; see TRACK_OVERLAP),
-- "remove" tracks cut out the road under them. Tracks the data already has
-- (ns.RoadTracksIn, by time) are skipped. Returns node coordinates and edges (copies; the
-- shipped data isn't changed). app/azerothgps/roads/graph.py does the same offline.
function R.WithTracks(roads, tracks, cont)
  local n, e = {}, {}
  for i = 1, #roads.n do n[i] = roads.n[i] end
  for i = 1, #roads.e do e[i] = roads.e[i] end
  local function newNode(x, y)
    n[#n + 1], n[#n + 2] = x, y
    return #n / 2
  end
  local city = ns.CityLevels and ns.CityLevels[cont]
  local snap = city and R.TRACK_SNAP_CITY or R.TRACK_SNAP
  -- the node at (x, y) on the network (within `reach`; of the edges in `only` if given),
  -- splitting an edge if needed; nil if none is close
  local function attach(x, y, reach, only)
    local best, bi, bAlong, bx, by
    for ei, ed in ipairs(e) do
      local along = 0
      if only and not only[ed] then along = nil end
      for i = 5, along and #ed - 3 or 0, 2 do
        local ax, ay, cx, cy = ed[i], ed[i + 1], ed[i + 2], ed[i + 3]
        local vx, vy = cx - ax, cy - ay
        local L2 = vx * vx + vy * vy
        local t = 0
        if L2 > 0 then t = math.max(0, math.min(1, ((x - ax) * vx + (y - ay) * vy) / L2)) end
        local qx, qy = ax + vx * t, ay + vy * t
        local d2 = (qx - x) ^ 2 + (qy - y) ^ 2
        if not best or d2 < best then best, bi, bAlong, bx, by = d2, ei, along + math.sqrt(L2) * t, qx, qy end
        along = along + math.sqrt(L2)
      end
    end
    reach = reach or snap
    if not best or best > reach * reach then return nil end
    local ed = e[bi]
    if bAlong < 3 then return ed[1], ed[5], ed[6] end
    if bAlong > ed[3] - 3 then return ed[2], ed[#ed - 1], ed[#ed] end
    local mid = newNode(bx, by)
    local p1, p2 = SplitPolyline(ed, bAlong)
    e[bi] = MakeEdge(ed[1], mid, p1, ed[4])
    e[#e + 1] = MakeEdge(mid, ed[2], p2, ed[4])
    if only then only[e[bi]], only[e[#e]] = true, true end
    return mid, bx, by
  end
  local function bounds(pts, i0)
    local x0, x1, y0, y1 = math.huge, -math.huge, math.huge, -math.huge
    for k = i0 or 1, #pts - 1, 2 do
      x0, x1 = math.min(x0, pts[k]), math.max(x1, pts[k])
      y0, y1 = math.min(y0, pts[k + 1]), math.max(y1, pts[k + 1])
    end
    return x0, x1, y0, y1
  end
  -- The stretches of road within `reach` of any of `lines` (flat point lists) cut out of
  -- the roads they're on (`parallel`: only where they run about parallel to it); the rest
  -- of each road stays, split where it was cut. Returns the new road ends: { { node, x, y } }.
  local cutNodes = {} -- (the road ends cuts made)
  -- (`area`: the lines are loops, and the road inside them goes)
  local function cut(lines, reach, parallel, area)
    local r2 = reach * reach
    local boxes = {}
    for li, l in ipairs(lines) do boxes[li] = { bounds(l) } end
    local function under(x, y, rvx, rvy)
      if area then
        for li, l in ipairs(lines) do
          local b = boxes[li]
          if x >= b[1] and x <= b[2] and y >= b[3] and y <= b[4] and R.InPolygon(l, x, y) then return true end
        end
        return false
      end
      for li, l in ipairs(lines) do
        local b = boxes[li]
        if not (x < b[1] - reach or x > b[2] + reach or y < b[3] - reach or y > b[4] + reach) then
          for k = 1, #l - 3, 2 do
            local ax, ay, cx, cy = l[k], l[k + 1], l[k + 2], l[k + 3]
            local vx, vy = cx - ax, cy - ay
            local L2 = vx * vx + vy * vy
            local tt = 0
            if L2 > 0 then tt = math.max(0, math.min(1, ((x - ax) * vx + (y - ay) * vy) / L2)) end
            if (ax + vx * tt - x) ^ 2 + (ay + vy * tt - y) ^ 2 <= r2 then
              if not parallel then return true end
              local nv, nr = math.sqrt(L2), math.sqrt(rvx * rvx + rvy * rvy)
              if nv > 0 and nr > 0 and math.abs(vx * rvx + vy * rvy) / (nv * nr) >= R.TRACK_ALONG_COS then return true end
            end
          end
        end
      end
      return false
    end
    local ends, kept = {}, {}
    for _, ed in ipairs(e) do
      -- (a road nowhere near the lines stays as it is)
      local ex0, ex1, ey0, ey1 = bounds(ed, 5)
      local nearAny = false
      for _, b in ipairs(boxes) do
        if not (ex1 < b[1] - reach or ex0 > b[2] + reach or ey1 < b[3] - reach or ey0 > b[4] + reach) then nearAny = true end
      end
      local dense, flag, anyUnder = {}, {}, false
      if nearAny then
        -- its points every 2 yards or so, each under the lines or not
        for i = 5, #ed - 3, 2 do
          local ax, ay, bx, by = ed[i], ed[i + 1], ed[i + 2], ed[i + 3]
          local m = math.max(1, math.ceil(math.sqrt((bx - ax) ^ 2 + (by - ay) ^ 2) / 2))
          for k = (i == 5) and 0 or 1, m do
            local x, y = ax + (bx - ax) * k / m, ay + (by - ay) * k / m
            dense[#dense + 1], dense[#dense + 2] = x, y
            local f = under(x, y, bx - ax, by - ay)
            flag[#flag + 1] = f
            anyUnder = anyUnder or f
          end
        end
      end
      if not anyUnder then
        kept[#kept + 1] = ed
      else
        -- (a junction the cut took away from under another road: that road's end now)
        if flag[1] then ends[#ends + 1] = { ed[1], dense[1], dense[2] } end
        if flag[#flag] then ends[#ends + 1] = { ed[2], dense[#dense - 1], dense[#dense] } end
        -- the stretches not under them, as roads of their own
        local run = {}
        local function flush(last)
          if #run >= 4 then
            local na = run.startsAtA and ed[1]
            if not na then
              na = newNode(run[1], run[2])
              ends[#ends + 1] = { na, run[1], run[2] }
              cutNodes[na] = true
            end
            local nb = last and ed[2]
            if not nb then
              nb = newNode(run[#run - 1], run[#run])
              ends[#ends + 1] = { nb, run[#run - 1], run[#run] }
              cutNodes[nb] = true
            end
            kept[#kept + 1] = MakeEdge(na, nb, run, ed[4])
          end
          run = {}
        end
        for j, f in ipairs(flag) do
          if f then
            if #run > 0 then flush(false) end
          else
            if #run == 0 then run.startsAtA = (j == 1) end
            run[#run + 1], run[#run + 2] = dense[2 * j - 1], dense[2 * j]
          end
        end
        if #run > 0 then flush(true) end
      end
    end
    e = kept
    return ends
  end
  local shipped = ns.RoadTracksIn or {}
  for _, t in ipairs(tracks or {}) do
    local pts = t.pts
    -- (walls aren't roads: Passability has them)
    if t.continent == cont and pts and #pts >= 4 and not shipped[t.time or -1] and t.op ~= "wall" and t.op ~= "unwall" then
      if t.op == "remove" then
        if t.area then cut({ pts }, 0, false, true) else cut({ pts }, R.TRACK_REMOVE_YD) end
      else
        local over = city and R.TRACK_OVERLAP_CITY or R.TRACK_OVERLAP
        local crossYd = city and R.TRACK_CROSS_CITY or R.TRACK_CROSS
        local alongMin = city and R.TRACK_ALONG_MIN_CITY or R.TRACK_ALONG_MIN
        local tx0, tx1, ty0, ty1 = bounds(pts)
        -- the roads' segments near the drawn line: the nearest one's distance and direction
        local function nearest(x, y)
          local best, bvx, bvy = math.huge, 0, 0
          for _, ed in ipairs(e) do
            if not ed.far then
              for i = 5, #ed - 3, 2 do
                local ax, ay, cx, cy = ed[i], ed[i + 1], ed[i + 2], ed[i + 3]
                local vx, vy = cx - ax, cy - ay
                local L2 = vx * vx + vy * vy
                local tt = 0
                if L2 > 0 then tt = math.max(0, math.min(1, ((x - ax) * vx + (y - ay) * vy) / L2)) end
                local d2 = (ax + vx * tt - x) ^ 2 + (ay + vy * tt - y) ^ 2
                if d2 < best then best, bvx, bvy = d2, vx, vy end
              end
            end
          end
          return math.sqrt(best), bvx, bvy
        end
        local function markFar()
          for _, ed in ipairs(e) do
            local ex0, ex1, ey0, ey1 = bounds(ed, 5)
            ed.far = ex1 < tx0 - over or ex0 > tx1 + over or ey1 < ty0 - over or ey0 > ty1 + over or nil
          end
        end
        -- the drawn line every 2 yards or so (its own points marked)
        local dx, dy, own = { pts[1] }, { pts[2] }, { true }
        for k = 1, #pts - 3, 2 do
          local ax, ay, bx, by = pts[k], pts[k + 1], pts[k + 2], pts[k + 3]
          local m = math.max(1, math.ceil(math.sqrt((bx - ax) ^ 2 + (by - ay) ^ 2) / 2))
          for q = 1, m do
            dx[#dx + 1], dy[#dy + 1], own[#own + 1] = ax + (bx - ax) * q / m, ay + (by - ay) * q / m, q == m
          end
        end
        local M = #dx
        -- along a road: close and about parallel, for a while (or at the drawn road's ends)
        markFar()
        local along = {}
        for j = 1, M do
          local d, vx, vy = nearest(dx[j], dy[j])
          local j0, j1 = math.max(j - 1, 1), math.min(j + 1, M)
          local wx, wy = dx[j1] - dx[j0], dy[j1] - dy[j0]
          local nv, nw = math.sqrt(vx * vx + vy * vy), math.sqrt(wx * wx + wy * wy)
          along[j] = d <= over and nv > 0 and nw > 0 and math.abs(vx * wx + vy * wy) / (nv * nw) >= R.TRACK_ALONG_COS
        end
        local alongLines = {}
        local j = 1
        while j <= M do
          if along[j] then
            local k = j
            while k < M and along[k + 1] do k = k + 1 end
            if j == 1 or k == M or (k - j) * 2 >= alongMin then
              local l = {}
              for q = j, k do l[#l + 1], l[#l + 2] = dx[q], dy[q] end
              if #l == 2 then l[3], l[4] = l[1], l[2] end
              alongLines[#alongLines + 1] = l
            end
            j = k + 1
          else
            j = j + 1
          end
        end
        -- the road there goes: the drawn one replaces it
        local cutEnds = #alongLines > 0 and cut(alongLines, over, true) or {}
        -- where it crosses a road left: split there (a junction)
        markFar()
        local splits, cd = {}, {}
        for q = 1, M do
          cd[q] = nearest(dx[q], dy[q])
        end
        local q = 2
        while q < M do
          if cd[q] <= crossYd then
            local c1, bestQ = q, q
            while c1 < M - 1 and cd[c1 + 1] <= crossYd do
              c1 = c1 + 1
              if cd[c1] < cd[bestQ] then bestQ = c1 end
            end
            splits[#splits + 1] = bestQ
            q = c1 + 1
          else
            q = q + 1
          end
        end
        splits[#splits + 1] = M
        -- the pieces between them, each joined at both ends
        local mine = {} -- (this track's roads)
        local joined = {}
        local s0 = 1
        for _, s1 in ipairs(splits) do
          if s1 > s0 then
            local line = { dx[s0], dy[s0] }
            for qq = s0 + 1, s1 - 1 do
              if own[qq] and (dx[qq] - dx[s0]) ^ 2 + (dy[qq] - dy[s0]) ^ 2 >= 4
                  and (dx[qq] - dx[s1]) ^ 2 + (dy[qq] - dy[s1]) ^ 2 >= 4 then
                line[#line + 1], line[#line + 2] = dx[qq], dy[qq]
              end
            end
            line[#line + 1], line[#line + 2] = dx[s1], dy[s1]
            local na, ax, ay = attach(line[1], line[2], s0 == 1 and snap or crossYd + 1)
            local nb, bx, by = attach(line[#line - 1], line[#line], s1 == M and snap or crossYd + 1)
            if na then line[1], line[2] = ax, ay else na = newNode(line[1], line[2]) end
            if nb then line[#line - 1], line[#line] = bx, by else nb = newNode(line[#line - 1], line[#line]) end
            if na ~= nb then
              local ed = MakeEdge(na, nb, line, R.SOURCE_RECORDED)
              e[#e + 1] = ed
              mine[ed] = true
              joined[na], joined[nb] = true, true
            end
          end
          s0 = s1
        end
        -- the replaced road's cut ends (and roads that met it there) join the drawn one
        -- (only those left a dead end: a road still going through a node needs nothing)
        local deg = {}
        for _, ed in ipairs(e) do
          if not mine[ed] then
            deg[ed[1]] = (deg[ed[1]] or 0) + 1
            deg[ed[2]] = (deg[ed[2]] or 0) + 1
          end
        end
        for _, ce in ipairs(cutEnds) do
          if not joined[ce[1]] and deg[ce[1]] == 1 then
            joined[ce[1]] = true
            local nm, mx, my = attach(ce[2], ce[3], over + 4, mine)
            if nm and nm ~= ce[1] then
              local ed = MakeEdge(ce[1], nm, { ce[2], ce[3], mx, my }, R.SOURCE_RECORDED)
              e[#e + 1] = ed
              mine[ed] = true
            end
          end
        end
        for _, ed in ipairs(e) do ed.far = nil end
      end
    end
  end
  -- dead-end stubs the cuts left (a road cut short beside a drawn one) go
  if next(cutNodes) then
    for _ = 1, 3 do
      local deg = {}
      for _, ed in ipairs(e) do
        deg[ed[1]] = (deg[ed[1]] or 0) + 1
        deg[ed[2]] = (deg[ed[2]] or 0) + 1
      end
      local kept, gone = {}, false
      for _, ed in ipairs(e) do
        local stub = ed[3] < R.TRACK_STUB and ((cutNodes[ed[1]] and deg[ed[1]] == 1) or (cutNodes[ed[2]] and deg[ed[2]] == 1))
        if stub then gone = true else kept[#kept + 1] = ed end
      end
      e = kept
      if not gone then break end
    end
  end
  return n, e
end

-- The extracted road network comes in pieces (roads the extraction lost, gates, towns).
-- Inside a background job (a coroutine run by R.Pump): hand control back every `every`
-- steps, so building the road data for a continent doesn't stall a frame.
local function CanYield()
  local co, main = coroutine.running()
  return co ~= nil and not main
end
local function Breathe(i, every)
  if i % every == 0 and CanYield() then coroutine.yield() end
end

-- Links between pieces, so a route can go on along roads instead of giving up: the
-- closest node pair between pieces, Kruskal style until every piece is joined, plus every
-- pair of nodes on different pieces closer than BRIDGE_SHORT. { [node] = { { m, yards } } }
R.BRIDGE_SHORT = 200
R.BRIDGE_SHORT_CITY = 40 -- ... up to this inside a city's ruins up top (walls: links through them are no use)
R.BRIDGE_MAX_PER_NODE = 6 -- the short links kept per node (the nearest)
R.BRIDGE_BUCKET = 250 -- yards: gap links are looked for in the buckets around a node
R.BRIDGE_SAMPLE = 60 -- nodes per group of pieces tried when joining groups far apart
-- `short`: the short links' reach (0 for none: a city's own level, joined by its stairs);
-- `nearOverlay(x, y)`: whether a spot is inside a city's ruins (short links shorter there);
-- `skip[n]`: nodes left out (true: inside a cave, joined to the rest by its way out), or
-- only in short links ("short": a cave's mouth, not a way to join pieces of road up).
local function Bridges(nodes, adj, short, nearOverlay, skip)
  local parent = {}
  local function find(a)
    local r = a
    while parent[r] ~= r do r = parent[r] end
    while parent[a] ~= r do parent[a], a = r, parent[a] end
    return r
  end
  local list = {}
  for n in pairs(adj) do
    parent[n] = n
    list[#list + 1] = n
  end
  table.sort(list)
  for n, links in pairs(adj) do
    for _, l in ipairs(links) do
      local a, b = find(n), find(l[1])
      if a ~= b then parent[a] = b end
    end
  end
  local piece = {}
  for _, n in ipairs(list) do piece[n] = find(n) end
  if skip and next(skip) then
    local kept = {}
    for _, n in ipairs(list) do
      if skip[n] ~= true then kept[#kept + 1] = n end
    end
    list = kept
  end
  local shortOnly = skip or {}
  -- closest pair per two pieces, and the short pairs: each node against the nodes in the
  -- buckets around it (a bucket at least a short link wide, so none is missed)
  local best, links = {}, {} -- best[pa][pb] (pa < pb) = { d2, a, b }
  short = short or R.BRIDGE_SHORT
  local short2 = short * short
  local city2 = R.BRIDGE_SHORT_CITY * R.BRIDGE_SHORT_CITY
  local B = math.max(short, R.BRIDGE_BUCKET)
  local buckets = {}
  for _, n in ipairs(list) do
    local k = math.floor(nodes[n * 2 - 1] / B) * 65536 + math.floor(nodes[n * 2] / B)
    local bk = buckets[k]
    if not bk then
      bk = {}
      buckets[k] = bk
    end
    bk[#bk + 1] = n
  end
  local function consider(a, b, ax, ay, pa)
    local pb = piece[b]
    if pa == pb then return end
    local dx, dy = nodes[b * 2 - 1] - ax, nodes[b * 2] - ay
    local d2 = dx * dx + dy * dy
    local lo, hi = pa, pb
    if lo > hi then lo, hi = hi, lo end
    local row = best[lo]
    if not row then
      row = {}
      best[lo] = row
    end
    local cur = row[hi]
    if shortOnly[a] or shortOnly[b] then -- (a cave's mouth: no joining link)
    elseif not cur then
      row[hi] = { d2, a, b }
    elseif d2 < cur[1] then
      cur[1], cur[2], cur[3] = d2, a, b
    end
    if d2 <= short2 and (d2 <= city2 or not nearOverlay
        or not (nearOverlay(ax, ay) or nearOverlay(nodes[b * 2 - 1], nodes[b * 2]))) then
      links[#links + 1] = { math.sqrt(d2), a, b }
    end
  end
  for i = 1, #list do
    Breathe(i, 40)
    local a = list[i]
    local ax, ay, pa = nodes[a * 2 - 1], nodes[a * 2], piece[a]
    local bx, by = math.floor(ax / B), math.floor(ay / B)
    for kx = bx - 1, bx + 1 do
      for ky = by - 1, by + 1 do
        for _, b in ipairs(buckets[kx * 65536 + ky] or {}) do
          if b > a then consider(a, b, ax, ay, pa) end
        end
      end
    end
  end
  local pairsByDist = {}
  for lo, row in pairs(best) do
    for hi, p in pairs(row) do pairsByDist[#pairsByDist + 1] = { math.sqrt(p[1]), p[2], p[3], lo, hi } end
  end
  table.sort(pairsByDist, function(x, y) return x[1] < y[1] end)
  local joined = {}
  local function jfind(a)
    while joined[a] and joined[a] ~= a do a = joined[a] end
    return a
  end
  local function join(p)
    local a, b = jfind(p[4]), jfind(p[5])
    if a ~= b then
      joined[a] = b
      if p[1] > short then links[#links + 1] = { p[1], p[2], p[3], keep = true } end
    end
  end
  for _, p in ipairs(pairsByDist) do join(p) end
  -- groups of pieces still apart (farther than the buckets reach): joined by their closest
  -- pair among up to BRIDGE_SAMPLE of each group's nodes
  local groups, order = {}, {}
  for _, n in ipairs(list) do
    if not shortOnly[n] then
      local gr = jfind(piece[n])
      if not groups[gr] then
        groups[gr] = {}
        order[#order + 1] = gr
      end
      local g = groups[gr]
      g[#g + 1] = n
    end
  end
  if #order > 1 then
    local samples = {}
    for gi, gr in ipairs(order) do
      local g = groups[gr]
      local step = math.max(1, math.ceil(#g / R.BRIDGE_SAMPLE))
      local sm = {}
      for k = 1, #g, step do sm[#sm + 1] = g[k] end
      samples[gi] = sm
    end
    local far = {}
    for gi = 1, #order do
      Breathe(gi, 2)
      for gj = gi + 1, #order do
        local bd, ba, bb
        for _, a in ipairs(samples[gi]) do
          local ax, ay = nodes[a * 2 - 1], nodes[a * 2]
          for _, b in ipairs(samples[gj]) do
            local dx, dy = nodes[b * 2 - 1] - ax, nodes[b * 2] - ay
            local d2 = dx * dx + dy * dy
            if not bd or d2 < bd then bd, ba, bb = d2, a, b end
          end
        end
        if bd then far[#far + 1] = { math.sqrt(bd), ba, bb, order[gi], order[gj] } end
      end
    end
    table.sort(far, function(x, y) return x[1] < y[1] end)
    for _, p in ipairs(far) do join(p) end
  end
  -- the nearest few short links per node (and every joining one)
  table.sort(links, function(x, y) return x[1] < y[1] end)
  local out, count = {}, {}
  for _, l in ipairs(links) do
    local d, a, b = l[1], l[2], l[3]
    if l.keep or ((count[a] or 0) < R.BRIDGE_MAX_PER_NODE and (count[b] or 0) < R.BRIDGE_MAX_PER_NODE) then
      count[a], count[b] = (count[a] or 0) + 1, (count[b] or 0) + 1
      out[a] = out[a] or {}
      out[b] = out[b] or {}
      out[a][#out[a] + 1] = { b, d }
      out[b][#out[b] + 1] = { a, d }
    end
  end
  return out
end

-- The characters of packed road points (Data/Caves.lua): each one's value, 0 to 63.
local PACK = {}
do
  local chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
  for i = 1, #chars do PACK[chars:byte(i)] = i - 1 end
end

-- A road with packed points (e[5] a string: from node a, each point the last one moved by
-- whole yards, two characters each way; see caves.pack_points) as a plain one; `n` its nodes,
-- `base` added to its node numbers.
local function Unpacked(e, n, base)
  base = base or 0
  local c = { e[1] + base, e[2] + base }
  if type(e[5]) ~= "string" then
    for j = 3, #e do c[j] = e[j] end
    return c
  end
  c[3], c[4] = e[3], e[4]
  local x, y = n[e[1] * 2 - 1], n[e[1] * 2]
  c[5], c[6] = x, y
  local s = e[5]
  for i = 1, #s - 3, 4 do
    local b1, b2, b3, b4 = s:byte(i, i + 3)
    x = x + PACK[b1] * 64 + PACK[b2] - 2048
    y = y + PACK[b3] * 64 + PACK[b4] - 2048
    c[#c + 1], c[#c + 2] = x, y
  end
  return c
end

local BuildGraph
local HostileSide
local function Graph(cont)
  -- (built for the player's faction: its guards' towns cost more; rebuilt if that changes)
  if graphs[cont] and graphs[cont].side ~= HostileSide() then graphs[cont] = nil end
  if graphs[cont] ~= nil then return graphs[cont] or nil end
  local t0 = ns.PerfStart and ns.PerfStart()
  local g = BuildGraph(cont)
  if ns.PerfEnd then ns.PerfEnd("router: build roads", t0) end
  return g
end
function BuildGraph(cont)
  local roads = ns.Roads and ns.Roads[cont]
  if not roads then
    graphs[cont] = false
    return nil
  end
  if roads.e[1] and type(roads.e[1][5]) == "string" then
    -- (an instance's roads, Data/Instances.lua: packed; unpacked once, in place)
    for i, e in ipairs(roads.e) do roads.e[i] = Unpacked(e, roads.n) end
  end
  local nodes, edges = roads.n, roads.e
  local P0, P1 = ns.PerfStart or function() end, ns.PerfEnd or function() end
  local pt = P0()
  -- drops off ledges (a city's, a cave's): one way, a to b, and no part of the network's
  -- joining up. By road (the edge itself), as the numbers change below.
  local dropOf, caveOf = {}, {}
  for ei, h in pairs(ns.RoadDrops and ns.RoadDrops[cont] or {}) do
    if edges[ei] then dropOf[edges[ei]] = h end
  end
  local noBridge = {} -- (a cave's nodes inside it: joined to the rest only by its roads out)
  -- roads of a city's ruins up top (Data/Cities.lua), added to the continent's; its own
  -- roads that run through the ruins' walls there are left out. And the caves' roads
  -- (Data/Caves.lua), their ways out joined onto the continent's nearest road.
  local Pass = ns.Passability
  local function throughWalls(e)
    if not (Pass and Pass.Overlay) then return false end
    for i = 5, #e - 3, 2 do
      local x1, y1, x2, y2 = e[i], e[i + 1], e[i + 2], e[i + 3]
      if not Pass.OverlayNear or Pass.OverlayNear(cont, x1, y1, x2, y2) then -- (no grid there: nothing to cross)
        local n = math.max(1, math.floor(math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2)))
        for k = 0, n do
          -- (a city's walls: not a cave's rock, which is under the land)
          local v, o = Pass.OverlayRaw(cont, x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n, true)
          if v == 2 and not o.cave then return true end
        end
      end
    end
    return false
  end
  for _, extra in ipairs(ns.RoadOverlays and ns.RoadOverlays[cont] or {}) do
    local base = #nodes / 2
    local n2, e2 = {}, {}
    for i = 1, #nodes do n2[i] = nodes[i] end
    for i = 1, #extra.n do n2[#nodes + i] = extra.n[i] end
    local ox0, ox1, oy0, oy1 = math.huge, -math.huge, math.huge, -math.huge
    for i = 1, #extra.n, 2 do
      ox0, ox1 = math.min(ox0, extra.n[i]), math.max(ox1, extra.n[i])
      oy0, oy1 = math.min(oy0, extra.n[i + 1]), math.max(oy1, extra.n[i + 1])
    end
    for i = 1, #edges do
      Breathe(i, 100)
      local e = edges[i]
      local a, b = e[1], e[2]
      local near = false -- (only roads near the ruins are checked; a cave's rock is under the land)
      for _, nd in ipairs(extra.cave and {} or { a, b }) do
        local x, y = nodes[nd * 2 - 1], nodes[nd * 2]
        if x > ox0 - 400 and x < ox1 + 400 and y > oy0 - 400 and y < oy1 + 400 then near = true end
      end
      if not (near and throughWalls(e)) then e2[#e2 + 1] = e end
    end
    local roadsEnd = #e2
    for k, e in ipairs(extra.e) do
      Breathe(k, 200)
      local c = Unpacked(e, extra.n, base)
      e2[#e2 + 1] = c
      if extra.drops and extra.drops[k] then dropOf[c] = extra.drops[k] end
      if extra.cave then caveOf[c] = true end
    end
    if extra.cave then
      for i = 1, #extra.n / 2 do noBridge[base + i] = true end
      for _, j in ipairs(extra.bridge or {}) do noBridge[base + j] = "short" end
    end
    if extra.joins then R.JoinOnto(n2, e2, roadsEnd, base, extra.joins) end
    nodes, edges = n2, e2
  end
  P1("router: build roads: overlays and caves", pt)
  pt = P0()
  local tracks = ns.db and ns.db.tracks
  if tracks and #tracks > 0 then
    -- (the player's recorded and drawn roads, on the roads as merged)
    nodes, edges = R.WithTracks({ n = nodes, e = edges }, tracks, cont)
  end
  -- Walls (drawn or shipped: Passability.WallLines) cut the roads they cross: a wall is
  -- drawn on purpose, and a gate is a gap in it. (The terrain's too-steep edges don't: a road
  -- over one is a pass.)
  local P = ns.Passability
  if P and P.HasWalls and P.HasWalls(cont) then
    if nodes == roads.n then
      local copy = {}
      for i = 1, #nodes do copy[i] = nodes[i] end
      nodes = copy
    end
    local kept = {}
    for k, ed in ipairs(edges) do
      Breathe(k, 200)
      local crossed = false
      for i = 5, #ed - 3, 2 do
        if P.CrossesWall(cont, ed[i], ed[i + 1], ed[i + 2], ed[i + 3]) then crossed = true break end
      end
      if not crossed then
        kept[#kept + 1] = ed
      else
        -- the stretches between the crossings, each a road of its own, cut a yard short of
        -- the wall either side (ends: new nodes)
        local run, a = { ed[5], ed[6] }, ed[1]
        local function flush(b)
          if #run >= 4 then
            local e2 = MakeEdge(a, b, run, ed[4])
            if dropOf[ed] then dropOf[e2] = dropOf[ed] end
            if caveOf[ed] then caveOf[e2] = true end
            kept[#kept + 1] = e2
          end
        end
        local skip = 0 -- (yards of the gap still to leave out, past a crossing at a segment's end)
        for i = 5, #ed - 3, 2 do
          local x1, y1, x2, y2 = ed[i], ed[i + 1], ed[i + 2], ed[i + 3]
          local len = math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2)
          if skip > 0 then
            if len <= skip then
              skip = skip - len
              x1, y1 = x2, y2
            else
              local f = skip / len
              x1, y1 = x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
              skip = 0
            end
            nodes[#nodes] , nodes[#nodes - 1] = y1, x1 -- (the new piece's start node, moved on)
            run = { x1, y1 }
          end
          local guard = 0
          while skip == 0 do
            local t = P.WallHit(cont, x1, y1, x2, y2)
            guard = guard + 1
            if not t or guard > 20 then break end
            local L = math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2)
            local g = L > 0 and 1 / L or 0 -- (a yard, as a share of the leg)
            local ax, ay = x1 + (x2 - x1) * math.max(0, t - g), y1 + (y2 - y1) * math.max(0, t - g)
            run[#run + 1], run[#run + 2] = ax, ay
            nodes[#nodes + 1], nodes[#nodes + 2] = ax, ay
            flush(#nodes / 2)
            if t + g >= 1 then
              -- (the gap runs on into the next segment)
              skip = (t + g - 1) * L
              nodes[#nodes + 1], nodes[#nodes + 2] = x2, y2
              run, a = { x2, y2 }, #nodes / 2
              x1, y1 = x2, y2
              if skip <= 0 then skip = 1e-6 end
              break
            end
            local bx, by = x1 + (x2 - x1) * (t + g), y1 + (y2 - y1) * (t + g)
            nodes[#nodes + 1], nodes[#nodes + 2] = bx, by
            run, a = { bx, by }, #nodes / 2
            x1, y1 = bx, by
          end
          if skip == 0 or x1 ~= x2 or y1 ~= y2 then
            if not (run[#run - 1] == x2 and run[#run] == y2) then run[#run + 1], run[#run + 2] = x2, y2 end
          end
        end
        flush(ed[2])
      end
    end
    edges = kept
  end
  local drops, caveEdges = {}, {}
  for ei, ed in ipairs(edges) do
    drops[ei] = dropOf[ed]
    caveEdges[ei] = caveOf[ed]
  end
  P1("router: build roads: drawn roads", pt)
  pt = P0()
  local adj = {}
  local ratio = {} -- [edge] = its cost per yard, where more than 1 (past guards)
  local side = HostileSide()
  for ei, e in ipairs(edges) do
    Breathe(ei, 100)
    local a, b, len = e[1], e[2], e[3]
    adj[a] = adj[a] or {}
    adj[b] = adj[b] or {}
    if not drops[ei] then
      -- (cost: its length, and more where it passes the other faction's guards)
      local cost = len
      if side then
        for i = 5, #e - 3, 2 do
          cost = cost + R.HostileYards(cont, e[i], e[i + 1], e[i + 2], e[i + 3], side) * (R.HOSTILE_FACTOR - 1)
        end
      end
      adj[a][#adj[a] + 1] = { b, len, ei, true, cost }
      adj[b][#adj[b] + 1] = { a, len, ei, false, cost }
      if cost > len then ratio[ei] = cost / math.max(len, 1) end
    end
  end
  local grid = ns.Terrain and ns.Terrain[cont]
  local P = ns.Passability
  -- (a city's ruins up top: not a cave's, whose own nodes don't take part)
  local nearOverlay = ns.CityHalls and ns.CityHalls[cont] and P and P.OverlayRaw
    and function(x, y)
      local v, o = P.OverlayRaw(cont, x, y)
      return v ~= nil and not o.cave
    end or nil
  P1("router: build roads: costs", pt)
  pt = P0()
  local bridges = Bridges(nodes, adj, grid and grid.slack and 0 or nil, nearOverlay, noBridge)
  for ei in pairs(drops) do
    local e = edges[ei]
    if e then adj[e[1]][#adj[e[1]] + 1] = { e[2], e[3], ei, true } end
  end
  P1("router: build roads: gap links", pt)
  local g = { adj = adj, n = nodes, e = edges, count = #nodes / 2, bridges = bridges, drops = drops, side = side,
    ratio = ratio, cave = caveEdges, caveNode = noBridge }
  -- (built in the background by WarmUp, a route may have built it meanwhile: keep that one)
  if graphs[cont] == nil then graphs[cont] = g end
  return graphs[cont] or nil
end

-- Terrain walks (Passability.FindPath) by end points: the legs to the destination are
-- the same on every reroute.
local walks, walkCount = {}, 0
local failed = {} -- rough spots where walks failed: "cont:x:y:x2:y2" at WALK_FAIL_YD
local walkJobs, walkQueued = {}, {} -- background searches (coroutines), queued by key
R.WALK_FAIL_YD = 25 -- a walk that failed isn't retried from within this distance
-- Tests: search right away instead of in the background.
R.SYNC_WALKS = false
R.MAX_WALK_JOBS = 8
R.STALE_START_YD = 15 -- queued searches from where the player was, further than this: dropped

-- The road edges routing uses on `cont` (shipped roads plus recorded ones), and the graph
-- they belong to (a new one after Reset, e.g. when a recording is saved).
function R.Edges(cont)
  local g = Graph(cont)
  return g and g.e, g
end

local warmed, warming = {}, {} -- WarmUp: continents done, and started (GetTime) but not done

-- The other faction's guards (Data/Hostile.lua): the side whose circles are dangerous to
-- the player ("A" for an Alliance character: the Horde's guards), nil when unknown or the
-- option is off.
function HostileSide()
  local st = ns.settings and ns.settings.gps
  if st and st.avoidHostile == false then return nil end
  return ns.Nav and ns.Nav.Faction and ns.Nav.Faction() or nil
end
R.HostileSide = HostileSide
local HB = 100 -- bucket size (yards)
local hostileIdx = {}
local function HostileBuckets(cont, side)
  local key = cont .. side
  local idx = hostileIdx[key]
  if idx then return idx end
  idx = {}
  local list = ns.Hostile and ns.Hostile[cont] and ns.Hostile[cont][side] or {}
  for i = 1, #list - 2, 3 do
    local x, y, r = list[i], list[i + 1], list[i + 2]
    for kx = math.floor((x - r) / HB), math.floor((x + r) / HB) do
      for ky = math.floor((y - r) / HB), math.floor((y + r) / HB) do
        local k = kx * 65536 + ky
        idx[k] = idx[k] or {}
        idx[k][#idx[k] + 1] = i
      end
    end
  end
  hostileIdx[key] = idx
  return idx
end
-- Whether (x, y) is within reach of guards hostile to the player (`side`: HostileSide()).
function R.HostileAt(cont, x, y, side)
  side = side or HostileSide()
  if not side then return false end
  local list = ns.Hostile and ns.Hostile[cont] and ns.Hostile[cont][side]
  if not list then return false end
  local b = HostileBuckets(cont, side)[math.floor(x / HB) * 65536 + math.floor(y / HB)]
  for _, i in ipairs(b or {}) do
    if (list[i] - x) ^ 2 + (list[i + 1] - y) ^ 2 <= list[i + 2] ^ 2 then return true end
  end
  return false
end
-- Yards of the leg (x1, y1)-(x2, y2) within their reach.
function R.HostileYards(cont, x1, y1, x2, y2, side)
  side = side or HostileSide()
  if not (side and ns.Hostile and ns.Hostile[cont]) then return 0 end
  local d = math.sqrt((x2 - x1) ^ 2 + (y2 - y1) ^ 2)
  local n = math.max(1, math.ceil(d / R.HOSTILE_STEP))
  local inside = 0
  for k = 0, n - 1 do
    local t = (k + 0.5) / n
    if R.HostileAt(cont, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, side) then inside = inside + 1 end
  end
  return d * inside / n
end
local function HostileExtra(cont, x1, y1, x2, y2)
  return R.HostileYards(cont, x1, y1, x2, y2) * (R.HOSTILE_FACTOR - 1)
end

function R.Reset()
  graphs, walks, walkCount, failed, walkJobs, walkQueued = {}, {}, 0, {}, {}, {}
  warmed, warming = {}, {}
  R.ClearSegMemo()
end

-- Straight-line terrain checks for off-road legs, remembered: recalculating a route from
-- the player's new position repeats every check on the destination's side (the same
-- points), and terrain doesn't change. Up to SEG_MEMO_MAX, then started over.
local SEG_MEMO_MAX = 20000
local segMemo, segMemoCount = {}, 0
function R.ClearSegMemo() segMemo, segMemoCount = {}, 0 end
local function SegCost(cont, x1, y1, x2, y2)
  local key = string.format("%d:%.1f:%.1f:%.1f:%.1f", cont, x1, y1, x2, y2)
  local c = segMemo[key]
  if c == nil then
    c = ns.Passability.SegmentCost(cont, x1, y1, x2, y2) or false
    if segMemoCount >= SEG_MEMO_MAX then segMemo, segMemoCount = {}, 0 end
    segMemo[key], segMemoCount = c, segMemoCount + 1
  end
  return c or nil
end

local function Remember(key, rough, c, path)
  if walkCount > 256 then walks, walkCount, failed = {}, 0, {} end
  walks[key], walkCount = c and { c, path } or false, walkCount + 1
  if not c then failed[rough] = true end
end

-- Run background terrain searches until `deadline` (now() in ms). Returns true when one
-- finished (the route should then be recomputed to use it), and whether any of those was
-- a leg between fixed points (then the legs between stops need recomputing too).
function R.Pump(deadline, now)
  local finished, fixed = false, false
  while walkJobs[1] and now() < deadline do
    local j = walkJobs[1]
    local ok, c, path = coroutine.resume(j.co)
    if not ok or coroutine.status(j.co) == "dead" then
      table.remove(walkJobs, 1)
      walkQueued[j.key] = nil
      if j.warm then
        warming[j.cont] = nil
      elseif j.links then -- (offroad links a route wanted: recalculate)
        finished, fixed = true, true
      else
        Remember(j.key, j.rough, ok and c or nil, ok and path or nil)
        finished = true
        if not j.transient then fixed = true end
      end
    end
  end
  return finished, fixed
end

function R.HasWork() return walkJobs[1] ~= nil end
-- Building a road network in the background: it gets more of each frame than searches do.
function R.Warming() return walkJobs[1] ~= nil and walkJobs[1].warm or false end

-- Returns yards, path; or nil (no way found), or nil, nil, true while still searching.
-- transient: a walk from the player's current position (soon stale as they move on);
-- only those are dropped when the queue is full; walks between fixed points always finish.
local function Walk(cont, x1, y1, x2, y2, transient)
  local key = string.format("%d:%.0f:%.0f:%.0f:%.0f", cont, x1, y1, x2, y2)
  local w = walks[key]
  if w == nil then
    local g = R.WALK_FAIL_YD
    local rough = string.format("%d:%d:%d:%d:%d", cont, math.floor(x1 / g), math.floor(y1 / g),
      math.floor(x2 / g), math.floor(y2 / g))
    if failed[rough] then return nil end
    if R.SYNC_WALKS then
      Remember(key, rough, ns.Passability.FindPath(cont, x1, y1, x2, y2))
      w = walks[key]
    else
      -- search in the background (Pump); meanwhile the caller falls back to a straight leg
      if not walkQueued[key] then
        -- searches from spots the player has already moved on from go stale: drop the
        -- queued ones from elsewhere (not the one running), and keep few
        local nTransient, oldest = 0, nil
        local far2 = R.STALE_START_YD * R.STALE_START_YD
        for i = #walkJobs, 2, -1 do
          local j = walkJobs[i]
          if j.transient and transient and ((j.x1 - x1) ^ 2 + (j.y1 - y1) ^ 2 > far2 or j.cont ~= cont) then
            walkQueued[j.key] = nil
            table.remove(walkJobs, i)
          end
        end
        for i = 2, #walkJobs do
          if walkJobs[i].transient then
            nTransient = nTransient + 1
            oldest = oldest or i
          end
        end
        if transient and nTransient >= R.MAX_WALK_JOBS and oldest then
          walkQueued[table.remove(walkJobs, oldest).key] = nil
        end
        walkQueued[key] = true
        walkJobs[#walkJobs + 1] = { key = key, rough = rough, transient = transient, cont = cont, x1 = x1, y1 = y1,
          co = coroutine.create(function() return ns.Passability.FindPath(cont, x1, y1, x2, y2) end) }
      end
      return nil, nil, true -- still searching
    end
  end
  if w then return w[1], w[2] end
end

local function Dist(x1, y1, x2, y2)
  local dx, dy = x2 - x1, y2 - y1
  return math.sqrt(dx * dx + dy * dy)
end

-- Squared distance from (x, y) to segment a-b, and the parameter of the closest point.
local function SegDist2(x, y, ax, ay, bx, by)
  local vx, vy = bx - ax, by - ay
  local L2 = vx * vx + vy * vy
  local t = 0
  if L2 > 0 then t = math.max(0, math.min(1, ((x - ax) * vx + (y - ay) * vy) / L2)) end
  local dx, dy = ax + vx * t - x, ay + vy * t - y
  return dx * dx + dy * dy, t
end

local function Key(bx, by) return bx * 65536 + by end

-- Road segments bucketed on a BUCKET grid (padded by ON_ROAD_YD), for "is this on a road?".
local function Buckets(g)
  if g.buckets then return g.buckets end
  local b, pad = {}, R.ON_ROAD_YD
  for ei, road in ipairs(g.e) do
    local e = (g.cave and g.cave[ei]) and {} or road -- (a cave's roads: under the land a leg crosses)
    for i = 5, #e - 3, 2 do
      local ax, ay, bx, by = e[i], e[i + 1], e[i + 2], e[i + 3]
      for kx = math.floor((math.min(ax, bx) - pad) / BUCKET), math.floor((math.max(ax, bx) + pad) / BUCKET) do
        for ky = math.floor((math.min(ay, by) - pad) / BUCKET), math.floor((math.max(ay, by) + pad) / BUCKET) do
          local k = Key(kx, ky)
          local list = b[k]
          if not list then
            list = {}
            b[k] = list
          end
          list[#list + 1] = { ax, ay, bx, by }
        end
      end
    end
  end
  g.buckets = b
  return b
end

local function OnRoad(g, x, y)
  local list = Buckets(g)[Key(math.floor(x / BUCKET), math.floor(y / BUCKET))]
  if not list then return false end
  local r2 = R.ON_ROAD_YD * R.ON_ROAD_YD
  for _, s in ipairs(list) do
    if SegDist2(x, y, s[1], s[2], s[3], s[4]) <= r2 then return true end
  end
  return false
end

-- Offroad mode: straight links from road node n to up to NODE_LINKS nearby road nodes over
-- passable ground, { { m, cost }, ... }. Terrain doesn't change, so they are cached.
-- Road nodes by NODE_BUCKET cell: { [Key(kx, ky)] = { n, ... } }.
local function NodeBuckets(g)
  if not g.nodeBuckets then
    local b = {}
    for m = 1, g.count do
      Breathe(m, 1000)
      local k = Key(math.floor(g.n[m * 2 - 1] / NODE_BUCKET), math.floor(g.n[m * 2] / NODE_BUCKET))
      b[k] = b[k] or {}
      b[k][#b[k] + 1] = m
    end
    g.nodeBuckets = g.nodeBuckets or b
  end
  return g.nodeBuckets
end

-- Road nodes within `maxd` yards of (x, y): { { n, yards }, ... }, nearest first.
local function NodesNear(g, x, y, maxd)
  local buckets = NodeBuckets(g)
  local bx, by, reach = math.floor(x / NODE_BUCKET), math.floor(y / NODE_BUCKET), math.ceil(maxd / NODE_BUCKET)
  local list = {}
  for kx = bx - reach, bx + reach do
    for ky = by - reach, by + reach do
      for _, m in ipairs(buckets[Key(kx, ky)] or {}) do
        local d = Dist(x, y, g.n[m * 2 - 1], g.n[m * 2])
        if d <= maxd then list[#list + 1] = { m, d } end
      end
    end
  end
  table.sort(list, function(a, b) return a[2] < b[2] end)
  return list
end

local function NodeLinks(g, cont, n)
  g.links = g.links or {}
  local cached = g.links[n]
  if cached then return cached end
  -- (not from or to a cave's or a city's own nodes: those are reached by their ways in)
  local inside = g.caveNode
  if inside and inside[n] then
    g.links[n] = {}
    return g.links[n]
  end
  NodeBuckets(g)
  local x, y = g.n[n * 2 - 1], g.n[n * 2]
  local bx, by, reach = math.floor(x / NODE_BUCKET), math.floor(y / NODE_BUCKET), math.ceil(R.NODE_LINK_MAX / NODE_BUCKET)
  -- the nearest NODE_LINK_TRIES nodes in each of NODE_LINKS directions (kept sorted, no full sort)
  local sectors, count, tries, maxd = {}, R.NODE_LINKS, R.NODE_LINK_TRIES, R.NODE_LINK_MAX
  local atan2, tau = math.atan2 or math.atan, 2 * math.pi
  for kx = bx - reach, bx + reach do
    for ky = by - reach, by + reach do
      local bucket = g.nodeBuckets[Key(kx, ky)]
      if bucket then
        for _, m in ipairs(bucket) do
          local mx, my = g.n[m * 2 - 1], g.n[m * 2]
          local dx, dy = mx - x, my - y
          local d = math.sqrt(dx * dx + dy * dy)
          if m ~= n and d <= maxd and not (inside and inside[m]) then
            local sector = math.floor(atan2(dy, dx) / tau * count) % count
            local list = sectors[sector]
            if not list then
              list = {}
              sectors[sector] = list
            end
            local k = #list
            if k < tries or d < list[k][2] then
              if k == tries then list[k] = nil k = k - 1 end
              while k > 0 and list[k][2] > d do
                list[k + 1] = list[k]
                k = k - 1
              end
              list[k + 1] = { m, d }
            end
          end
        end
      end
    end
  end
  -- the nearest reachable one in each direction (past rock, the next nearest)
  local links = {}
  for sector = 0, count - 1 do
    for _, nd in ipairs(sectors[sector] or {}) do
      local m = nd[1]
      local mx, my = g.n[m * 2 - 1], g.n[m * 2]
      local c = ns.Passability.SegmentCost(cont, x, y, mx, my)
      if c then
        links[#links + 1] = { m, (c + HostileExtra(cont, x, y, mx, my)) * R.OFFROAD_TIE }
        break
      end
    end
  end
  g.links[n] = links
  return links
end

local function Clock() return debugprofilestop and debugprofilestop() or os.clock() * 1000 end
local linkDeadline -- (Clock() ms: the route being calculated works out node links until then)

-- Node n's links, or nil when they aren't worked out yet and this route's time for them is
-- used up: then they're worked out in the background, and the route recalculated after.
local function LinksNow(g, cont, n)
  local l = g.links and g.links[n]
  if l then return l end
  if R.SYNC_WALKS or not linkDeadline or Clock() < linkDeadline then return NodeLinks(g, cont, n) end
  g.linkQueued = g.linkQueued or {}
  if g.linkQueued[n] then return nil end
  g.linkQueued[n] = true
  local key = "links:" .. cont
  local job = walkQueued[key] and g.linkJob
  if job and job.cont == cont then
    job.want[#job.want + 1] = n
    return nil
  end
  job = { key = key, links = true, cont = cont, want = { n } }
  job.co = coroutine.create(function()
    local i = 1
    while job.want[i] do
      local m = job.want[i]
      NodeLinks(g, cont, m)
      g.linkQueued[m] = nil
      i = i + 1
      Breathe(i, 4)
    end
  end)
  g.linkJob = job
  walkQueued[key] = true
  walkJobs[#walkJobs + 1] = job
  return nil
end

-- Road segments bucketed on a SEG_BUCKET grid, with how far along its edge each starts:
-- [key] = { { edge, i (index of the segment's first point in e), along }, ... }
local SEG_BUCKET = 200
local function SegIndex(g)
  if g.segIndex then return g.segIndex end
  local idx = {}
  for ei, e in ipairs(g.e) do
    Breathe(ei, 200)
    if g.drops and g.drops[ei] then e = { 0, 0, 0, 0 } end -- (not a road to get on or off at)
    local along = 0
    for i = 5, #e - 3, 2 do
      local ax, ay, bx, by = e[i], e[i + 1], e[i + 2], e[i + 3]
      for kx = math.floor(math.min(ax, bx) / SEG_BUCKET), math.floor(math.max(ax, bx) / SEG_BUCKET) do
        for ky = math.floor(math.min(ay, by) / SEG_BUCKET), math.floor(math.max(ay, by) / SEG_BUCKET) do
          local k = Key(kx, ky)
          idx[k] = idx[k] or {}
          idx[k][#idx[k] + 1] = { ei, i, along }
        end
      end
      along = along + Dist(ax, ay, bx, by)
    end
  end
  g.segIndex = g.segIndex or idx
  return g.segIndex
end

R.NEAREST_MAX_RINGS = 60 -- SEG_BUCKET rings searched (12 km) before scanning everything

-- The closest point of the road edges near (x, y) to it, nearest first: every edge within
-- ENTRY_SLACK of the nearest one (enough for getting on/off the road).
-- { { edge, px, py, dist, along = yards from the edge's first node }, ... }
function R.NearestEdges(cont, x, y)
  local g = Graph(cont)
  if not g then return {} end
  local idx = SegIndex(g)
  local bx, by = math.floor(x / SEG_BUCKET), math.floor(y / SEG_BUCKET)
  local best, bestD = {}, nil
  local seen = {}
  for ring = 0, R.NEAREST_MAX_RINGS do
    -- cells beyond this ring are at least (ring) buckets away
    if bestD and (ring - 1) * SEG_BUCKET > bestD + R.ENTRY_SLACK then break end
    for kx = bx - ring, bx + ring do
      for ky = by - ring, by + ring do
        if math.max(math.abs(kx - bx), math.abs(ky - by)) == ring then
          for _, s in ipairs(idx[Key(kx, ky)] or {}) do
            local ei, i, along = s[1], s[2], s[3]
            local sk = ei * 100000 + i
            if not seen[sk] then
              seen[sk] = true
              local e = g.e[ei]
              local ax, ay, cx, cy = e[i], e[i + 1], e[i + 2], e[i + 3]
              local d2, t = SegDist2(x, y, ax, ay, cx, cy)
              local b = best[ei]
              if not b or d2 < b.d2 then
                best[ei] = { edge = ei, px = ax + (cx - ax) * t, py = ay + (cy - ay) * t, d2 = d2,
                  along = along + Dist(ax, ay, cx, cy) * t }
              end
              if not bestD or d2 < bestD * bestD then bestD = math.sqrt(d2) end
            end
          end
        end
      end
    end
  end
  if not bestD then return R.NearestEdgesAll(cont, x, y) end
  local list = {}
  for _, b in pairs(best) do
    b.dist = math.sqrt(b.d2)
    list[#list + 1] = b
  end
  table.sort(list, function(a, b) return a.dist < b.dist end)
  return list
end

-- Whether (x, y) is down in a cave (Data/Caves.lua): over one's own cells; over its floor
-- under walkable ground, when the player's spot, only when `indoors` (IsIndoors) says so
-- (a stop there is taken to be down in it). A capital's floor under another (Data/Capitals.lua,
-- `split`: a height between the two) goes by the player's height `z` instead, when known.
function R.CaveDown(cont, x, y, indoors, z)
  local P = ns.Passability
  local v, o = P.OverlayRaw(cont, x, y)
  if v == nil or not (o and o.cave) then return false end
  if v == 3 and o.split then
    if z then return z < o.split end
    return true
  end
  if v == 3 and indoors ~= nil then return indoors end
  return true
end

-- The roads to get on or off at (NearestEdges' list) by the caves: down in one, only a cave's
-- roads; outside, none of them, but for their ways out when the other end of the trip is
-- down in a cave (`wayIn`). When that leaves none nearby, from every road (x, y: the spot);
-- unchanged when none at all.
function R.CaveLevel(g, cont, list, down, wayIn, x, y)
  local P = ns.Passability
  local function keep(from)
    local out = {}
    for _, c in ipairs(from) do
      local cave = g.cave[c.edge]
      if down then
        if cave then out[#out + 1] = c end
      elseif not cave then
        out[#out + 1] = c
      elseif wayIn then
        local v, o = P.OverlayRaw(cont, c.px, c.py)
        if not (v ~= nil and o and o.cave) then out[#out + 1] = c end
      end
    end
    return out[1] and out
  end
  return keep(list) or (x and keep(R.NearestEdgesAll(cont, x, y))) or list
end

-- Whether (x, y) is on a capital's own cells (Data/Capitals.lua: its grid over the continent's).
function R.CapitalAt(cont, x, y)
  local P = ns.Passability
  if not (P and P.OverlayRaw) then return false end
  local v, o = P.OverlayRaw(cont, x, y)
  return v ~= nil and o ~= nil and o.capital == true
end

-- The ways out of the cave a spot is down in (its roads outside it: out of its mouths and on
-- to the land's roads), from `list` (NearestEdges' of that spot), each as its closest point
-- to (x, y) (NearestEdges' format).
function R.CaveWaysOut(g, cont, list, x, y)
  local P = ns.Passability
  local out, seen = {}, {}
  for _, c in ipairs(list) do
    local ei = c.edge
    local v, o = P.OverlayRaw(cont, c.px, c.py)
    if g.cave[ei] and not seen[ei] and not (v ~= nil and o and o.cave) then
      seen[ei] = true
      local e = g.e[ei]
      local best, along = nil, 0
      for i = 5, #e - 3, 2 do
        local ax, ay, bx, by = e[i], e[i + 1], e[i + 2], e[i + 3]
        local d2, t = SegDist2(x, y, ax, ay, bx, by)
        local seg = Dist(ax, ay, bx, by)
        if not best or d2 < best.d2 then
          best = { edge = ei, px = ax + (bx - ax) * t, py = ay + (by - ay) * t, d2 = d2, along = along + seg * t }
        end
        along = along + seg
      end
      if best then
        best.dist = math.sqrt(best.d2)
        out[#out + 1] = best
      end
    end
  end
  return out
end

-- Every edge's closest point (no index): far from any road.
function R.NearestEdgesAll(cont, x, y)
  local g = Graph(cont)
  if not g then return {} end
  local list = {}
  for ei, e in ipairs(g.e) do
    if g.drops and g.drops[ei] then e = { 0, 0, 0, 0 } end -- (not a road to get on or off at)
    local along, best = 0, nil
    for i = 5, #e - 3, 2 do
      local ax, ay, bx, by = e[i], e[i + 1], e[i + 2], e[i + 3]
      local d2, t = SegDist2(x, y, ax, ay, bx, by)
      local segLen = Dist(ax, ay, bx, by)
      if not best or d2 < best.d2 then
        best = { edge = ei, px = ax + (bx - ax) * t, py = ay + (by - ay) * t, d2 = d2, along = along + segLen * t }
      end
      along = along + segLen
    end
    if best then
      best.dist = math.sqrt(best.d2)
      list[#list + 1] = best
    end
  end
  table.sort(list, function(a, b) return a.dist < b.dist end)
  return list
end

-- Whether (x, y) is a road junction (a node where three or more roads meet).
function R.JunctionAt(cont, x, y)
  local g = Graph(cont)
  if not g then return false end
  if not g.junctions then
    local j = {}
    for n = 1, g.count do
      if #(g.adj[n] or {}) >= 3 then j[Key(math.floor(g.n[n * 2 - 1] + 0.5), math.floor(g.n[n * 2] + 0.5))] = true end
    end
    g.junctions = j
  end
  return g.junctions[Key(math.floor(x + 0.5), math.floor(y + 0.5))] or false
end

-- Nearest point on the road network to (x, y) (see NearestEdges).
function R.Nearest(cont, x, y)
  return R.NearestEdges(cont, x, y)[1]
end

-- Points of edge e between `from` and `to` yards along it (either direction), with the
-- end points interpolated.
local function EdgePoints(e, from, to)
  local pts, cum = {}, { 0 }
  for i = 5, #e, 2 do pts[#pts + 1] = { e[i], e[i + 1] } end
  for i = 2, #pts do cum[i] = cum[i - 1] + Dist(pts[i - 1][1], pts[i - 1][2], pts[i][1], pts[i][2]) end
  local total = cum[#cum]
  local function At(a)
    a = math.max(0, math.min(total, a))
    for i = 2, #pts do
      if cum[i] >= a then
        local seg = cum[i] - cum[i - 1]
        local t = seg > 0 and (a - cum[i - 1]) / seg or 0
        return { pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * t, pts[i - 1][2] + (pts[i][2] - pts[i - 1][2]) * t }
      end
    end
    return pts[#pts]
  end
  local out = { At(from) }
  if from <= to then
    for i = 1, #pts do if cum[i] > from and cum[i] < to then out[#out + 1] = pts[i] end end
  else
    for i = #pts, 1, -1 do if cum[i] < from and cum[i] > to then out[#out + 1] = pts[i] end end
  end
  out[#out + 1] = At(to)
  return out
end

-- Binary heap keyed on f.
local function Push(h, node, f)
  h[#h + 1] = { node, f }
  local i = #h
  while i > 1 do
    local p = math.floor(i / 2)
    if h[p][2] <= h[i][2] then break end
    h[p], h[i] = h[i], h[p]
    i = p
  end
end

local function Pop(h)
  local top = h[1]
  local last = table.remove(h)
  if #h > 0 then
    h[1] = last
    local i = 1
    while true do
      local l, r, m = i * 2, i * 2 + 1, i
      if h[l] and h[l][2] < h[m][2] then m = l end
      if h[r] and h[r][2] < h[m][2] then m = r end
      if m == i then break end
      h[m], h[i] = h[i], h[m]
      i = m
    end
  end
  return top
end

-- Turn a list of pieces into the route result. A piece is
-- { kind, x1, y1, x2, y2 } (straight) or { kind = ROAD, edge = e, from = a1, to = a2 }.
-- Straight legs that run along a road are split, and those stretches count as road.
local function Build(g, pieces)
  local flat, kinds, length, road = {}, {}, 0, 0
  local function add(x, y, kind)
    local n = #flat
    if n >= 2 and math.abs(flat[n - 1] - x) < 0.01 and math.abs(flat[n] - y) < 0.01 then return end
    if n >= 2 then
      local d = Dist(flat[n - 1], flat[n], x, y)
      length = length + d
      if kind == R.KIND_ROAD then road = road + d end
      kinds[#kinds + 1] = kind
    end
    flat[n + 1], flat[n + 2] = x, y
  end
  local function straight(x1, y1, x2, y2)
    local len = Dist(x1, y1, x2, y2)
    local n = math.max(1, math.ceil(len / 4))
    -- runs along the leg: { t_end, onRoad, t_start }
    local runs = {}
    for i = 0, n do
      local t = i / n
      local on = g and OnRoad(g, x1 + (x2 - x1) * t, y1 + (y2 - y1) * t) or false
      local last = runs[#runs]
      if last and last[2] == on then last[1] = t else runs[#runs + 1] = { t, on, last and last[1] or 0 } end
    end
    -- short stretches along a road stay off-road
    local merged = {}
    for _, r in ipairs(runs) do
      local on = r[2] and (r[1] - r[3]) * len >= R.ON_ROAD_MIN
      local last = merged[#merged]
      if last and last[2] == on then last[1] = r[1] else merged[#merged + 1] = { r[1], on } end
    end
    add(x1, y1, R.KIND_OFFROAD)
    for _, r in ipairs(merged) do
      if r[1] > 0 then add(x1 + (x2 - x1) * r[1], y1 + (y2 - y1) * r[1], r[2] and R.KIND_ROAD or R.KIND_OFFROAD) end
    end
  end
  for _, p in ipairs(pieces) do
    if p.edge then
      local kind = g.drops and g.drops[p.edge] and R.KIND_DROP or R.KIND_ROAD
      for _, q in ipairs(EdgePoints(g.e[p.edge], p.from, p.to)) do add(q[1], q[2], kind) end
    else
      straight(p[2], p[3], p[4], p[5])
    end
  end
  return { pts = flat, kinds = kinds, length = length, road = road }
end

local function Straight(g, sx, sy, tx, ty)
  return Build(g, { { R.KIND_OFFROAD, sx, sy, tx, ty } })
end

-- A stop inside a city's blocked cells (a banker's booth, a counter): open floor around it,
-- the nearest one in each direction up to CITY_SNAP_YD, at most CITY_SNAP_TRIES of them.
R.CITY_SNAP_YD = 12
R.CITY_SNAP_TRIES = 2 -- (the ones nearest where the route comes from)
R.CITY_SNAP_KEEP = 25 -- yards the start may move before the spot is chosen again
R.CITY_SNAP_LEVEL = 4 -- yards: an open spot about this near the floor's height is on the same floor
local snapChosen = {}
-- (On about the same floor as there, when the city's heights say: not up or down a ledge.)
function R.OpenAround(cont, x, y, fromX, fromY)
  local Pass = ns.Passability
  local H = ns.Nav and ns.Nav.CityHeight
  -- a start: the same floor as there (not up or down a ledge); a stop (`fromX`): any floor,
  -- the spot nearest it being where one stands to reach it
  local h0 = not fromX and H and H(cont, x, y)
  local found = {}
  for pass = 1, 2 do -- (the same floor first; any open floor when there's none)
    for k = 0, 7 do
      local a = k * math.pi / 4
      for d = 1, R.CITY_SNAP_YD do
        local ox, oy = x + math.cos(a) * d, y + math.sin(a) * d
        if Pass.IsOpen(cont, ox, oy) then
          local h = h0 and H(cont, ox, oy)
          if pass == 2 or not h or math.abs(h - h0) < R.CITY_SNAP_LEVEL then found[#found + 1] = { ox, oy, d } end
          break
        end
      end
    end
    if found[1] then break end
  end
  table.sort(found, function(p, q) return p[3] < q[3] end)
  local out = {}
  local function add(p)
    if not p then return end
    for _, q in ipairs(out) do
      if Dist(p[1], p[2], q[1], q[2]) < 4 then return end
    end
    if #out < R.CITY_SNAP_TRIES then out[#out + 1] = p end
  end
  add(found[1]) -- the nearest the spot
  if fromX then -- and the nearest the way in
    local best
    for _, p in ipairs(found) do
      if not best or Dist(p[1], p[2], fromX, fromY) < Dist(best[1], best[2], fromX, fromY) then best = p end
    end
    add(best)
  end
  for _, p in ipairs(found) do add(p) end
  return out
end

local RouteOne

-- Route from (sx, sy) to (tx, ty) on continent `cont`. opts.offroad selects offroad mode.
-- Returns { pts = { x1, y1, ... }, kinds = { kind per segment }, length, road,
-- pending (true while a terrain search it depends on is still running) }.
-- Smoothing the finished route (the map's line and the directions both follow it): a
-- short jog out and back, or a zigzag, becomes the straight line past it where that's
-- walkable (and no nearer the other faction's guards). Not a road junction's point, not
-- across a change of kind (onto a road, a ride, a drop), not down in a city, and not on
-- hilly ground (Passability.Hilly: winding there may be the way up), bar tiny wobbles.
R.SMOOTH_SPAN = 80 -- yards of route a jog may span
R.SMOOTH_RATIO = 1.2 -- route this much longer than the straight line past it: a jog
R.SMOOTH_TOL = 2.5 -- yards: points this close to the straight line past them go anyway
local function SegDev(x, y, ax, ay, bx, by)
  local vx, vy = bx - ax, by - ay
  local L2 = vx * vx + vy * vy
  local t = L2 > 0 and math.max(0, math.min(1, ((x - ax) * vx + (y - ay) * vy) / L2)) or 0
  return math.sqrt((ax + vx * t - x) ^ 2 + (ay + vy * t - y) ^ 2)
end
function R.Smooth(cont, r)
  if not r or not r.pts or #r.pts < 6 or (ns.CityLevels and ns.CityLevels[cont]) then return r end
  local pts, kinds = r.pts, r.kinds
  local n = #pts / 2
  local function P(i) return pts[2 * i - 1], pts[2 * i] end
  local smoothable = { [R.KIND_ROAD] = true, [R.KIND_OFFROAD] = true }
  local out, ok = { pts[1], pts[2] }, {}
  local i = 1
  while i < n do
    local best
    local k = kinds[i]
    if smoothable[k] then
      local along, j = 0, i
      while j < n and kinds[j] == k do
        local ax, ay = P(j)
        local bx, by = P(j + 1)
        along = along + Dist(ax, ay, bx, by)
        if along > R.SMOOTH_SPAN then break end
        j = j + 1
        if j >= i + 2 then
          local x1, y1 = P(i)
          local x2, y2 = P(j)
          local chord = Dist(x1, y1, x2, y2)
          local dev, junction = 0, false
          for m = i + 1, j - 1 do
            local mx, my = P(m)
            dev = math.max(dev, SegDev(mx, my, x1, y1, x2, y2))
            if k == R.KIND_ROAD and R.JunctionAt and R.JunctionAt(cont, mx, my) then junction = true end
          end
          local jog = along >= chord * R.SMOOTH_RATIO and dev > R.SMOOTH_TOL
          if jog and ns.Passability and ns.Passability.HillyAlong and ns.Passability.HillyAlong(cont, pts, i, j) then
            jog = false -- (a climb: the winding is the way up)
          end
          if chord >= 1 and not junction and (jog or dev <= R.SMOOTH_TOL) then
            -- (strictly: no leeway at its ends, which are mid-route)
            local walk = not ns.Passability or ns.Passability.SegmentCost(cont, x1, y1, x2, y2, 0)
            if walk then
              local hs = 0
              for m = i, j - 1 do
                local ax, ay = P(m)
                local bx, by = P(m + 1)
                hs = hs + R.HostileYards(cont, ax, ay, bx, by)
              end
              if R.HostileYards(cont, x1, y1, x2, y2) <= hs + 1 then best = j end
            end
          end
        end
      end
    end
    local j = best or i + 1
    local x, y = P(j)
    out[#out + 1], out[#out + 2] = x, y
    ok[#ok + 1] = kinds[i]
    i = j
  end
  if #out == #pts then return r end
  r.pts, r.kinds = out, ok
  local length, road = 0, 0
  for m = 1, #ok do
    local d = Dist(out[2 * m - 1], out[2 * m], out[2 * m + 1], out[2 * m + 2])
    length = length + d
    if ok[m] == R.KIND_ROAD then road = road + d end
  end
  r.length, r.road = length, road
  return r
end

local RouteBody
function R.Route(cont, sx, sy, tx, ty, opts)
  return R.Smooth(cont, RouteBody(cont, sx, sy, tx, ty, opts))
end

function RouteBody(cont, sx, sy, tx, ty, opts)
  local grid = ns.Terrain and ns.Terrain[cont]
  local Pass = ns.Passability
  -- a city's stop inside blocked cells: to the best open spot around it, then the last step
  if grid and grid.slack and Pass and not Pass.IsOpen(cont, tx, ty) then
    local t0 = ns.PerfStart and ns.PerfStart()
    local best, bestLen, pending
    -- (the spot chosen last time, while the start is near where it was chosen from)
    local key = string.format("%d:%.0f:%.0f", cont, tx, ty)
    local c = snapChosen[key]
    local fresh = R.OpenAround(cont, tx, ty, sx, sy)
    local tries = fresh
    if c and Dist(c[1], c[2], sx, sy) <= R.CITY_SNAP_KEEP then
      -- (the spot kept, and the best one from here now: walked past the booth, the kept
      -- one can be round the far side)
      tries = { c[3] }
      local f = fresh[1]
      if f and (f[1] ~= c[3][1] or f[2] ~= c[3][2]) then tries[2] = f end
    end
    local chosen
    for _, p in ipairs(tries) do
      local r = RouteOne(cont, sx, sy, p[1], p[2], opts)
      pending = pending or r.pending
      if r.length + p[3] < (bestLen or math.huge) then
        best, bestLen, chosen = r, r.length + p[3], p
      end
    end
    if chosen and not pending and not (c and chosen == c[3]) then snapChosen[key] = { sx, sy, chosen } end
    if ns.PerfEnd then ns.PerfEnd("router: stop in a booth", t0) end
    if best then
      local n = #best.pts
      best.pts[n + 1], best.pts[n + 2] = tx, ty
      best.kinds[#best.kinds + 1] = R.KIND_OFFROAD
      best.length = bestLen
      best.pending = pending
      return best
    end
  end
  -- a start on a closed cell (a ledge's foot, beside a wall): from the nearest open floor on
  -- the same level, not across whatever closes it
  if grid and grid.slack and Pass and not Pass.IsOpen(cont, sx, sy) then
    local p = R.OpenAround(cont, sx, sy)[1]
    if p then
      local r = RouteBody(cont, p[1], p[2], tx, ty, opts)
      table.insert(r.pts, 1, sy)
      table.insert(r.pts, 1, sx)
      table.insert(r.kinds, 1, R.KIND_OFFROAD)
      r.length = r.length + p[3]
      return r
    end
  end
  return RouteOne(cont, sx, sy, tx, ty, opts)
end

function RouteOne(cont, sx, sy, tx, ty, opts)
  local offroad = opts and opts.offroad
  -- yards the player may drop off a ledge (Nav: what their health survives)
  local maxDrop = opts and opts.maxDrop or (ns.Nav and ns.Nav.SafeDrop and ns.Nav.SafeDrop()) or 0
  local grid = ns.Terrain and ns.Terrain[cont]
  local cityPenalty = grid and grid.slack and R.CITY_BLOCKED_PENALTY
  -- (a blocked leg or link: a city's walls are real, and so are its ruins' up top)
  local function blockedPenalty(x1, y1, x2, y2)
    if Pass and Pass.CrossesWall and Pass.CrossesWall(cont, x1, y1, x2, y2) then return R.WALL_PENALTY end
    if cityPenalty then return cityPenalty end
    local P = ns.Passability
    if P and P.Overlay and x1 then
      for k = 0, 4 do
        if P.Overlay(cont, x1 + (x2 - x1) * k / 4, y1 + (y2 - y1) * k / 4) then return R.CITY_BLOCKED_PENALTY end
      end
    end
    return R.BLOCKED_PENALTY
  end
  local Pass = ns.Passability
  local g = Graph(cont)
  local direct = not Pass or Pass.SegmentCost(cont, sx, sy, tx, ty)
  -- (straight past the other faction's guards isn't a way to go if there's another)
  if direct and R.HostileYards(cont, sx, sy, tx, ty) > 0 then direct = nil end
  if not g or (offroad and direct) then return Straight(g, sx, sy, tx, ty) end
  local ss = R.NearestEdges(cont, sx, sy)
  local ts = R.NearestEdges(cont, tx, ty)
  -- the caves (Data/Caves.lua): in one, on by its roads; outside, not onto them, but for a
  -- way in to a cave at the other end. Over a mine under walkable ground the player may be
  -- up top: opts.indoors, from IsIndoors, tells (under a capital's floor, opts.z: their height).
  if g.cave and next(g.cave) and Pass and Pass.OverlayRaw then
    local sDown, tDown = R.CaveDown(cont, sx, sy, opts and opts.indoors, opts and opts.z), R.CaveDown(cont, tx, ty)
    -- (the ways out of the cave at the other end, however far: a cave with no land road
    -- near its mouth is reached across the land to it)
    local sWays = tDown and not sDown and R.CaveWaysOut(g, cont, ts, sx, sy)
    local tWays = sDown and not tDown and R.CaveWaysOut(g, cont, ss, tx, ty)
    ss = R.CaveLevel(g, cont, ss, sDown, tDown, sx, sy)
    ts = R.CaveLevel(g, cont, ts, tDown, sDown, tx, ty)
    for _, pair in ipairs({ { ss, sWays }, { ts, tWays } }) do
      local list, ways = pair[1], pair[2]
      for _, w in ipairs(ways or {}) do
        local seen = false
        for _, c in ipairs(list) do seen = seen or c.edge == w.edge end
        if not seen then list[#list + 1] = w end
      end
      table.sort(list, function(p, q) return p.dist < q.dist end)
    end
  end
  -- a city: roads on the same floor as the start or the stop (the nearest may be on a
  -- walk right above or below)
  local H = grid and grid.slack and ns.Nav and ns.Nav.CityHeight
  if H then
    local function sameFloor(list, x, y, around)
      local h0 = around and ns.Nav.CityFloor(cont, x, y) or H(cont, x, y)
      if not h0 then return list end
      local out = {}
      for _, c in ipairs(list) do
        local h = H(cont, c.px, c.py)
        if not h or math.abs(h - h0) < R.CITY_SNAP_LEVEL then out[#out + 1] = c end
      end
      return out[1] and out or list
    end
    ss, ts = sameFloor(ss, sx, sy), sameFloor(ts, tx, ty, true)
  end
  local s, t = ss[1], ts[1]
  if not s or not t then return Straight(g, sx, sy, tx, ty) end
  if not offroad and direct and Dist(sx, sy, tx, ty) <= s.dist + t.dist then return Straight(g, sx, sy, tx, ty) end

  local OFF, ROAD = R.KIND_OFFROAD, R.KIND_ROAD
  -- a terrain search this route needs is still running: it's provisional (see Nav's Route)
  local pending = false
  linkDeadline = Clock() + R.NODE_LINK_MS
  -- Off-road leg: cost and pieces. Straight where the ground allows. Getting on/off the
  -- road (`must`) otherwise walks around obstacles over the terrain grid, and as a last
  -- resort goes straight at a heavy penalty; offroad mode's extra links are just dropped.
  local function Leg(x1, y1, x2, y2, must, walk)
    local d = Dist(x1, y1, x2, y2)
    local c, path = d, nil
    if Pass then c = SegCost(cont, x1, y1, x2, y2) end
    -- (in a capital no walk around: the terrain grid's cells are coarser than its streets,
    -- and blind to its floors over each other; a leg there is straight, its walls real)
    local capital = not c and (R.CapitalAt(cont, x1, y1) or R.CapitalAt(cont, x2, y2))
    if capital then walk = false end
    if not c and walk and Pass and Pass.FindPath then
      local searching
      c, path, searching = Walk(cont, x1, y1, x2, y2, opts and opts.transient and x1 == sx and y1 == sy)
      if searching then pending = true end
    end
    -- (blocked in a straight line: walked around it once searched, if the route takes it)
    local pieces = { { OFF, x1, y1, x2, y2, gap = not c and not cityPenalty and not capital or nil } }
    if path then
      pieces = {}
      for i = 1, #path - 2, 2 do pieces[#pieces + 1] = { OFF, path[i], path[i + 1], path[i + 2], path[i + 3] } end
    end
    local h = 0 -- (past the other faction's guards)
    if path then
      for i = 1, #path - 2, 2 do h = h + HostileExtra(cont, path[i], path[i + 1], path[i + 2], path[i + 3]) end
    else
      h = HostileExtra(cont, x1, y1, x2, y2)
    end
    if offroad then
      if c then return (c + h) * R.OFFROAD_TIE, pieces end
      if must then return (d * blockedPenalty(x1, y1, x2, y2) + h) * R.OFFROAD_PENALTY, pieces end
      return nil
    end
    return ((c or d * blockedPenalty(x1, y1, x2, y2)) + h) * R.OFFROAD_PENALTY, pieces
  end
  -- pieces a .. b .. c as one list
  local function Join(...)
    local out = {}
    for _, list in ipairs({ ... }) do
      for _, p in ipairs(list) do out[#out + 1] = p end
    end
    return out
  end

  -- (yards along part of an edge, as cost: more past the other faction's guards)
  local function part(ei, yd) return yd * (g.ratio and g.ratio[ei] or 1) end
  local START, GOAL = -1, -2
  local gscore, came, open, closed = { [START] = 0 }, {}, {}, {}
  local function h(n)
    if n < 0 then return 0 end
    return Dist(g.n[n * 2 - 1], g.n[n * 2], tx, ty)
  end
  local function relax(from, to, cost, pieces)
    if not cost then return end
    local ng = gscore[from] + cost
    if gscore[to] == nil or ng < gscore[to] - 1e-9 then
      gscore[to] = ng
      came[to] = { from, pieces }
      Push(open, to, ng + h(to))
    end
  end
  -- Nearby edges to get on/off the road network: not just the nearest one, since the
  -- nearest road can lead the wrong way.
  local function candidates(list)
    local out = {}
    for i, c in ipairs(list) do
      if i > R.ENTRY_CANDIDATES or c.dist > list[1].dist + R.ENTRY_SLACK then break end
      out[#out + 1] = c
    end
    return out
  end

  local goalFrom = {}
  local function goalVia(n, cost, pieces)
    if cost and (not goalFrom[n] or cost < goalFrom[n][1]) then goalFrom[n] = { cost, pieces } end
  end
  -- Goal: from either end of a nearby edge to its closest point, then off the road.
  local goals = {}
  for i, c in ipairs(candidates(ts)) do
    local e = g.e[c.edge]
    local cost, leg = Leg(c.px, c.py, tx, ty, true, i <= R.WALK_AROUND_CANDIDATES)
    goals[#goals + 1] = { c = c, cost = cost, leg = leg }
    goalVia(e[1], part(c.edge, c.along) + cost, Join({ { kind = ROAD, edge = c.edge, from = 0, to = c.along } }, leg))
    goalVia(e[2], part(c.edge, math.max(0, e[3] - c.along)) + cost, Join({ { kind = ROAD, edge = c.edge, from = e[3], to = c.along } }, leg))
  end
  -- Start: onto a nearby edge's closest point, then either way along it.
  for i, c in ipairs(candidates(ss)) do
    local e = g.e[c.edge]
    local cost, leg = Leg(sx, sy, c.px, c.py, true, i <= R.WALK_AROUND_CANDIDATES)
    relax(START, e[1], cost + part(c.edge, c.along), Join(leg, { { kind = ROAD, edge = c.edge, from = c.along, to = 0 } }))
    relax(START, e[2], cost + part(c.edge, math.max(0, e[3] - c.along)), Join(leg, { { kind = ROAD, edge = c.edge, from = c.along, to = e[3] } }))
    for _, gl in ipairs(goals) do
      if gl.c.edge == c.edge then
        relax(START, GOAL, cost + part(c.edge, math.abs(gl.c.along - c.along)) + gl.cost,
          Join(leg, { { kind = ROAD, edge = c.edge, from = c.along, to = gl.c.along } }, gl.leg))
      end
    end
  end
  -- Offroad mode: straight links from the start to nearby road nodes, and from nearby
  -- road nodes to the destination, where the ground allows; and for a short trip, a walk
  -- around whatever is in the way.
  if offroad then
    if Dist(sx, sy, tx, ty) <= R.OFFROAD_WALK_AROUND and Pass.FindPath then
      local c, path, searching = Walk(cont, sx, sy, tx, ty, opts and opts.transient)
      if searching then pending = true end
      if c then
        local pieces = {}
        for i = 1, #path - 2, 2 do
          pieces[#pieces + 1] = { OFF, path[i], path[i + 1], path[i + 2], path[i + 3] }
          c = c + HostileExtra(cont, path[i], path[i + 1], path[i + 2], path[i + 3])
        end
        relax(START, GOAL, c * R.OFFROAD_TIE, pieces)
      end
    end
    local function nearestNodes(x, y) return NodesNear(g, x, y, R.OFFROAD_LINK_MAX) end
    for i, nd in ipairs(nearestNodes(sx, sy)) do
      if i > R.OFFROAD_LINKS then break end
      local n = nd[1]
      local nx, ny = g.n[n * 2 - 1], g.n[n * 2]
      relax(START, n, Leg(sx, sy, nx, ny))
    end
    for i, nd in ipairs(nearestNodes(tx, ty)) do
      if i > R.OFFROAD_LINKS then break end
      local n = nd[1]
      local nx, ny = g.n[n * 2 - 1], g.n[n * 2]
      goalVia(n, Leg(nx, ny, tx, ty))
    end
    -- Join (and leave) a road partway along it too, not only where it's closest or at a
    -- junction: points every OFFROAD_ALONG_STEP yards on the nearby roads, straight over
    -- open ground. So the route cuts across to where the road is heading.
    local function alongPoints(list, x, y)
      local out = {}
      local r2 = R.OFFROAD_ALONG_MAX * R.OFFROAD_ALONG_MAX
      for i, c in ipairs(list) do
        if i > R.ENTRY_CANDIDATES then break end
        local e = g.e[c.edge]
        local acc = 0
        for k = 5, #e - 3, 2 do
          local ax, ay, bx, by = e[k], e[k + 1], e[k + 2], e[k + 3]
          local seg = Dist(ax, ay, bx, by)
          local t = math.ceil(acc / R.OFFROAD_ALONG_STEP) * R.OFFROAD_ALONG_STEP
          while t <= acc + seg do
            local f = seg > 0 and (t - acc) / seg or 0
            local px, py = ax + (bx - ax) * f, ay + (by - ay) * f
            if (px - x) ^ 2 + (py - y) ^ 2 <= r2 then
              out[#out + 1] = { c.edge, t, px, py }
            end
            t = t + R.OFFROAD_ALONG_STEP
          end
          acc = acc + seg
        end
      end
      return out
    end
    for _, p in ipairs(alongPoints(ss, sx, sy)) do
      local cost, leg = Leg(sx, sy, p[3], p[4])
      if cost then
        local e = g.e[p[1]]
        relax(START, e[1], cost + part(p[1], p[2]), Join(leg, { { kind = ROAD, edge = p[1], from = p[2], to = 0 } }))
        relax(START, e[2], cost + part(p[1], math.max(0, e[3] - p[2])), Join(leg, { { kind = ROAD, edge = p[1], from = p[2], to = e[3] } }))
      end
    end
    for _, p in ipairs(alongPoints(ts, tx, ty)) do
      local cost, leg = Leg(p[3], p[4], tx, ty)
      if cost then
        local e = g.e[p[1]]
        goalVia(e[1], part(p[1], p[2]) + cost, Join({ { kind = ROAD, edge = p[1], from = 0, to = p[2] } }, leg))
        goalVia(e[2], part(p[1], math.max(0, e[3] - p[2])) + cost, Join({ { kind = ROAD, edge = p[1], from = e[3], to = p[2] } }, leg))
      end
    end
  end

  while #open > 0 do
    local n = Pop(open)[1]
    if n == GOAL then break end
    if not closed[n] then
      closed[n] = true
      local gf = goalFrom[n]
      if gf then relax(n, GOAL, gf[1], gf[2]) end
      for _, a in ipairs(g.adj[n] or {}) do
        local e = g.e[a[3]]
        local drop = g.drops and g.drops[a[3]]
        if not drop or drop <= maxDrop then -- (a drop only when the fall is safe, and worth it)
          relax(n, a[1], (a[5] or a[2]) + (drop and R.DROP_COST or 0), { { kind = ROAD, edge = a[3], from = a[4] and 0 or e[3], to = a[4] and e[3] or 0 } })
        end
      end
      -- across a gap to another piece of the road network (walked around obstacles below)
      local x, y = g.n[n * 2 - 1], g.n[n * 2]
      for _, b in ipairs(g.bridges[n] or {}) do
        local m = b[1]
        local mx, my = g.n[m * 2 - 1], g.n[m * 2]
        if b.cost == nil then
          local c = Pass and Pass.SegmentCost(cont, x, y, mx, my)
          b.open = c ~= nil
          -- (to or from a cave's roads only over open ground: not through the mountain; nor in a
          -- capital, where what's closed between two roads is a wall or a level up or down)
          if not b.open and g.caveNode and (g.caveNode[n] or g.caveNode[m]) then b.shut = true end
          if not b.open and (R.CapitalAt(cont, x, y) or R.CapitalAt(cont, mx, my)) then b.shut = true end
          if not b.open and Pass and Pass.CrossesWall and Pass.CrossesWall(cont, x, y, mx, my) then b.shut = true end
          b.cost = ((c or b[2] * blockedPenalty(x, y, mx, my)) + HostileExtra(cont, x, y, mx, my)) * R.OFFROAD_PENALTY
        end
        if not b.shut then relax(n, m, b.cost, { { OFF, x, y, mx, my, gap = not b.open } }) end
      end
      if offroad and Pass then
        local x, y = g.n[n * 2 - 1], g.n[n * 2]
        local links = LinksNow(g, cont, n)
        if not links then pending = true end
        for _, l in ipairs(links or {}) do
          local m = l[1]
          relax(n, m, l[2], { { OFF, x, y, g.n[m * 2 - 1], g.n[m * 2] } })
        end
      end
    end
  end
  -- Road mode: roads that go a long way round, or that are only reached across blocked
  -- ground, lose to walking straight there around the obstacles (see ROAD_DIRECT_PENALTY).
  -- (Searched only when it could win: the walk is at least the straight distance. Not in a
  -- city or its ruins up top, whose grids are floors and walls, not terrain.)
  if not offroad and Pass and not cityPenalty and not (Pass.Overlay and (Pass.Overlay(cont, sx, sy) or Pass.Overlay(cont, tx, ty))) then
    local d = Dist(sx, sy, tx, ty)
    local best = gscore[GOAL] or math.huge
    if d <= R.OFFROAD_WALK_AROUND and best > d * R.ROAD_DIRECT_PENALTY then
      local c, path = direct, nil
      if not c and Pass.FindPath then
        local searching
        c, path, searching = Walk(cont, sx, sy, tx, ty, opts and opts.transient)
        if searching then pending = true end
      end
      if c then -- (past the other faction's guards: more)
        if path then
          for i = 1, #path - 2, 2 do c = c + HostileExtra(cont, path[i], path[i + 1], path[i + 2], path[i + 3]) end
        else
          c = c + HostileExtra(cont, sx, sy, tx, ty)
        end
      end
      if c and c * R.ROAD_DIRECT_PENALTY < best then
        local pieces = { { OFF, sx, sy, tx, ty } }
        if path then
          pieces = {}
          for i = 1, #path - 2, 2 do pieces[#pieces + 1] = { OFF, path[i], path[i + 1], path[i + 2], path[i + 3] } end
        end
        local res = Build(g, pieces)
        res.pending = pending
        return res
      end
    end
  end
  if not gscore[GOAL] then -- not connected
    local res = Straight(g, sx, sy, tx, ty)
    res.pending = pending
    return res
  end

  local chain, cur = {}, GOAL
  while cur ~= START do
    local c = came[cur]
    table.insert(chain, 1, c[2])
    cur = c[1]
  end
  local pieces = {}
  for _, list in ipairs(chain) do
    for _, p in ipairs(list) do
      -- a gap the terrain blocks in a straight line: walked around it once searched (from
      -- the player's position: a search that goes stale as they move on)
      local path = p.gap and Pass and Pass.FindPath
        and select(2, Walk(cont, p[2], p[3], p[4], p[5], opts and opts.transient and p[2] == sx and p[3] == sy or false))
      if path then
        for i = 1, #path - 2, 2 do pieces[#pieces + 1] = { OFF, path[i], path[i + 1], path[i + 2], path[i + 3] } end
      else
        pieces[#pieces + 1] = p
      end
    end
  end
  local res = Build(g, pieces)
  res.pending = pending
  return res
end

-- Build a continent's road data (graph, indexes) and decode the terrain around (x, y) as a
-- background job, the first time a route is needed there: otherwise the first route pays
-- for all of it in one frame (a few hundred ms). Returns true while that's still running
-- (Nav waits for it, up to WARM_WAIT seconds, then works the route out anyway).
R.WARM = true -- tests: off
R.WARM_WAIT = 10
R.WARM_TERRAIN_YD = 800
function R.WarmUp(cont, x, y)
  if not R.WARM or R.SYNC_WALKS then return false end
  local started = warming[cont]
  if started then return GetTime() - started < R.WARM_WAIT end
  if warmed[cont] then return false end
  if not (ns.Roads and ns.Roads[cont]) then
    warmed[cont] = true
    return false
  end
  warmed[cont], warming[cont] = true, GetTime()
  local key = "warm:" .. cont
  walkQueued[key] = true
  table.insert(walkJobs, 1, { key = key, warm = true, cont = cont, co = coroutine.create(function()
    local g = Graph(cont)
    if not g then return end
    SegIndex(g)
    NodeBuckets(g)
    if ns.Passability and ns.Passability.WarmRows then ns.Passability.WarmRows(cont, x, y, R.WARM_TERRAIN_YD) end
  end) })
  return true
end

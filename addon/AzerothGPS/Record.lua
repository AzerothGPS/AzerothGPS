-- The player's road fixes: roads drawn on the map where the road data misses one, and
-- stretches erased where it has one that isn't there (the road tools: "Draw a road" and
-- "Erase a road" on the map's buttons, or /agps draw). Saved in ns.db.tracks: routes use
-- them at once (Router.WithTracks), `agps roads` takes them into the road data, and they're
-- kept for sharing if the player opted in (Feedback). Once the addon's road data has one
-- (ns.RoadTracksIn, by its time), it's dropped here.
local _, ns = ...

local R = {}
ns.Record = R

local function Tracks()
  ns.db.tracks = ns.db.tracks or {}
  return ns.db.tracks
end
R.Tracks = Tracks

-- At login: drop the fixes the road data now has.
function R.Prune()
  local shipped = ns.RoadTracksIn
  if not shipped or not ns.db or not ns.db.tracks then return end
  local t, n = ns.db.tracks, 0
  for i = #t, 1, -1 do
    if t[i].time and shipped[t[i].time] then
      table.remove(t, i)
      n = n + 1
    end
  end
  if n > 0 then ns.Print(("%d of your drawn roads are in the road data now"):format(n)) end
end

-- Tracks changed: rebuild the road network (it includes them) and the route.
function R.Changed()
  if ns.Passability and ns.Passability.RefreshWalls then ns.Passability.RefreshWalls() end
  if ns.GPS and ns.GPS.ClearEdges then ns.GPS.ClearEdges() end
  if ns.Router and ns.Router.Reset then ns.Router.Reset() end
  if ns.Nav and ns.Nav.Invalidate then ns.Nav.Invalidate(true, true) end
  if ns.GPS and ns.GPS.Redraw then ns.GPS.Redraw() end
end

-- A drawn road (op "add") or erased one ("remove"): saved; its number.
function R.Save(track)
  local t = Tracks()
  -- (a time of its own: it's the track's key)
  local used = {}
  for _, o in ipairs(t) do if o.time then used[o.time] = true end end
  while used[track.time] or (ns.RoadTracksIn and ns.RoadTracksIn[track.time]) do track.time = track.time + 1 end
  t[#t + 1] = track
  if ns.Feedback then ns.Feedback.RoadRecorded(track) end
  R.Changed()
  return #t
end

function R.Delete(i)
  local t = Tracks()
  if not (i and t[i]) then
    ns.Print("no drawn road #" .. tostring(i))
    return
  end
  local tr = table.remove(t, i)
  if ns.Feedback and ns.Feedback.RoadRemoved then ns.Feedback.RoadRemoved(tr) end
  local what = { remove = "erased road", wall = "wall", unwall = "erased wall" }
  ns.Print(("took back #%d (%s)"):format(i, what[tr.op] or "drawn road"))
  R.Changed()
end

-- The last one taken back.
function R.Undo()
  local n = #Tracks()
  if n == 0 then
    ns.Print("no drawn road to take back")
    return
  end
  R.Delete(n)
end

function R.List()
  local t = Tracks()
  if #t == 0 then ns.Print("no drawn roads waiting for the road data") end
  for i, tr in ipairs(t) do
    local what = { remove = "erased road", wall = "wall", unwall = "erased wall", add = "road" }
    ns.Print(("#%d %s %s, %d points, %s"):format(i, what[tr.op] or tr.op, tr.zone or "?",
      #tr.pts / 2, date("%Y-%m-%d %H:%M", tr.time)))
  end
end

"""The whole addon run offline, as in the game: every file in the toc's order under Lua 5.1 (lupa's),
with a stand-in for the game's UI (wowmock.lua, next to this file), the start-up events fired. For
the tests (app/tests/test_map_redraw.py and the private dev repo's) and the trip sweep
(`agps trip-sweep`)."""

from __future__ import annotations

from pathlib import Path

from .paths import ADDON_DIR

MOCK = Path(__file__).resolve().parent / "wowmock.lua"

GLOBALS = """
  strsplit = function(sep, s, n)
    local out, pat = {}, "([^" .. sep .. "]*)"
    for part in (s .. sep):gmatch(pat .. sep) do out[#out + 1] = part end
    return unpack(out)
  end
  strtrim = function(s) return (s:gsub("^%s+", ""):gsub("%s+$", "")) end
  strjoin = function(sep, ...) return table.concat({ ... }, sep) end
  tinsert, tremove, wipe = table.insert, table.remove, function(t) for k in pairs(t) do t[k] = nil end return t end
  format = string.format
  date = os.date
  time = os.time
"""


def toc_files() -> list[str]:
    out = []
    for line in (ADDON_DIR / "AzerothGPS.toc").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line.replace("\\", "/"))
    return out


def start():
    """(lua, ns): the addon loaded and started up (ADDON_LOADED, PLAYER_LOGIN), the player in Brill
    (AGPS_POS), GetTime from AGPS_T. Router: no background warm-up, walks searched at once (the
    tests' defaults; a caller sets WARM / SYNC_WALKS for the game's way)."""
    from lupa import lua51

    lua = lua51.LuaRuntime()
    lua.execute(MOCK.read_text(encoding="utf-8"))
    lua.execute(GLOBALS)
    ns = lua.table()
    lua.globals().AGPS_NS = ns
    loader = lua.eval("function(src, name) return assert(loadstring(src, '@' .. name)) end")
    for name in toc_files():
        loader((ADDON_DIR / name).read_text(encoding="utf-8"), name)("AzerothGPS", ns)
    fire = lua.eval("AGPS_FIRE")
    fire("ADDON_LOADED", "AzerothGPS")
    fire("PLAYER_LOGIN")
    errors = list(ns.initErrors.values())
    if errors:
        raise RuntimeError(f"the addon failed to start: {errors}")
    ns.Router.WARM, ns.Router.SYNC_WALKS = False, True
    return lua, ns

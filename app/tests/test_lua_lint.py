"""Static checks on the addon's Lua for mistakes that have bitten before."""

import re
from pathlib import Path

ADDON = Path(__file__).resolve().parents[2] / "addon" / "AzerothGPS"

# (name, file): uses before the file-level local that are really something else of the same name
FORWARD_OK = {
    ("ev", "Core.lua"),  # a loop variable in the probe's do-block, not the later `local ev` frame
}


def _strip(line: str) -> str:
    """The line without string contents and comments (enough to find identifiers)."""
    line = re.sub(r'"(\\.|[^"\\])*"', '""', line)
    line = re.sub(r"'(\\.|[^'\\])*'", "''", line)
    i = line.find("--")
    return line if i < 0 else line[:i]


def forward_references(path: Path) -> list[tuple[str, int, int]]:
    """File-level locals used above their declaration: (name, line used, line declared). A function
    written above `local Foo` reads a global Foo (nil) instead, and only fails when called."""
    lines = [_strip(l) for l in path.read_text(encoding="utf-8").splitlines()]
    decl = {}
    for i, l in enumerate(lines):
        m = re.match(r"local function (\w+)", l)
        if m:
            decl.setdefault(m.group(1), i)
            continue
        m = re.match(r"local ([\w, ]+?)\s*(=|$)", l)
        if m:
            for n in m.group(1).split(","):
                n = n.strip()
                if re.fullmatch(r"\w+", n):
                    decl.setdefault(n, i)
    out = []
    for name, at in decl.items():
        if (name, path.name) in FORWARD_OK:
            continue
        use = re.compile(r"(?<![\w.:])" + re.escape(name) + r"(?!\w)")
        for i in range(at):
            l = lines[i]
            if not use.search(l):
                continue
            # (a local, parameter or loop variable of its own with that name: not the file's)
            if re.search(r"\blocal\b[^=]*(?<![\w.])" + re.escape(name) + r"\b", l):
                continue
            if re.search(r"function\s*[\w.:]*\([^)]*\b" + re.escape(name) + r"\b", l):
                continue
            if re.search(r"\bfor\b[^=]*\b" + re.escape(name) + r"\b", l):
                continue
            out.append((name, i + 1, at + 1))
            break
    return out


def test_no_file_level_local_is_used_above_its_declaration():
    found = {}
    for f in sorted(ADDON.glob("*.lua")):
        hits = forward_references(f)
        if hits:
            found[f.name] = hits
    assert not found, ("used above their `local` (declare them first: `local Foo` near the top, "
                       f"`Foo = function() ... end` later): {found}")


def test_the_forward_reference_check_catches_the_trap(tmp_path):
    p = tmp_path / "Trap.lua"
    p.write_text("local function OnClick()\n  LeaveOpened()\nend\n\nlocal function LeaveOpened()\nend\n",
                 encoding="utf-8")
    assert forward_references(p) == [("LeaveOpened", 2, 5)]


def _top_level(expr: str) -> list[str]:
    """`expr` split at its top-level commas (not inside brackets or a function's body)."""
    parts, depth, cur = [], 0, ""
    for ch in expr:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def truncated_and_or(path: Path) -> list[tuple[int, str]]:
    """`local x, y = a and f()` (or `or`): `and`/`or` keep only the call's first value, so y is always
    nil. (The flight-path detour line: every redraw failed there, no route or panel drawn.)"""
    out = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = _strip(raw)
        m = re.match(r"\s*(?:local\s+)?([\w.]+(?:\s*,\s*[\w.]+)+)\s*=(?!=)\s*(.+)$", line)
        if not m or "function" in m.group(2):
            continue
        names = [n for n in m.group(1).split(",") if n.strip()]
        exprs = _top_level(m.group(2))
        if len(names) > len(exprs):
            last = exprs[-1]
            depth, flat = 0, ""
            for ch in last:  # (the last expression outside brackets: its own and / or)
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                elif depth == 0:
                    flat += ch
            if re.search(r"\b(and|or)\b", flat):
                out.append((i, raw.strip()))
    return out


def test_no_multiple_values_lost_to_and_or():
    found = {p.name: truncated_and_or(p) for p in ADDON.rglob("*.lua") if "Data" not in p.parts}
    found = {k: v for k, v in found.items() if v}
    assert not found, found


def test_the_and_or_check_catches_the_detour_bug(tmp_path):
    f = tmp_path / "x.lua"
    f.write_text("local lx1, ly1 = learn and Geo.ToContinent(a, b, c, d)\n"
                 "local a, b = f(x and y)\n"
                 "local p, q = x or 1, y or 2\n"
                 "  n, n == 1 and '' or 's'))\n", encoding="utf-8")
    assert [n for n, _ in truncated_and_or(f)] == [1]


# Characters the game's fonts (Friz Quadrata, Arial Narrow) don't have: shown as a box in game (seen 2026-10-03:
# "Options → Routing" in the "Don't use this zeppelin" question). Use "->", "-", "'", '"' instead.
MISSING_GLYPHS = "→←↑↓⇒•…–—“”‘’✓✗"


def test_no_text_shown_in_game_has_characters_the_fonts_lack():
    found = []
    for path in sorted(ADDON.rglob("*.lua")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("--", 1)[0] if '"' not in line.split("--", 1)[0] else line
            for m in re.finditer(r'"(\\.|[^"\\])*"', code):
                bad = [c for c in m.group(0) if c in MISSING_GLYPHS]
                if bad:
                    found.append(f"{path.name}:{n} {''.join(bad)}")
    assert not found, found

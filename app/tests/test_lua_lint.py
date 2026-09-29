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

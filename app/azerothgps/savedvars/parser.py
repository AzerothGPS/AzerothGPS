"""Parser for WoW SavedVariables files (the Lua subset WoW writes).

Handles: top-level `NAME = value` assignments; tables with `["k"] = v`,
`[1] = v` and positional entries; strings, numbers, booleans, nil; `--`
comments. Tables with only keys 1..n become lists, others dicts.
"""

from __future__ import annotations

import re
from pathlib import Path

_TOKEN = re.compile(
    r"""
    (?P<ws>\s+|--\[\[.*?\]\]|--[^\n]*)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<num>-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?|inf|nan))
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>[{}\[\]=,;])
    """,
    re.VERBOSE | re.DOTALL,
)

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "\n": "\n", "a": "\a", "b": "\b"}


def _unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n.isdigit():
                m = re.match(r"\d{1,3}", s[i + 1 :])
                out.append(chr(int(m.group())))
                i += 1 + len(m.group())
                continue
            out.append(_ESCAPES.get(n, n))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _tokens(text: str):
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"unexpected character {text[pos]!r} at {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        yield kind, m.group()


class _Parser:
    def __init__(self, text: str) -> None:
        self.toks = list(_tokens(text))
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self, value=None):
        tok = self.peek()
        if value is not None and tok[1] != value:
            raise ValueError(f"expected {value!r}, got {tok[1]!r}")
        self.i += 1
        return tok

    def value(self):
        kind, v = self.take()
        if kind == "str":
            return _unescape(v[1:-1])
        if kind == "num":
            if v.lower().lstrip("-").startswith("0x"):
                return int(v, 16)
            f = float(v)
            return int(f) if re.fullmatch(r"-?\d+", v) else f
        if kind == "name":
            return {"true": True, "false": False, "nil": None}[v]
        if v == "{":
            return self.table()
        raise ValueError(f"unexpected token {v!r}")

    def table(self):
        d: dict = {}
        n = 0
        while self.peek()[1] != "}":
            if self.peek()[1] == "[":
                self.take("[")
                k = self.value()
                self.take("]")
                self.take("=")
                d[k] = self.value()
            elif self.peek()[0] == "name" and self.toks[self.i + 1][1] == "=":
                k = self.take()[1]
                self.take("=")
                d[k] = self.value()
            else:
                n += 1
                d[n] = self.value()
            if self.peek()[1] in (",", ";"):
                self.take()
        self.take("}")
        if d and all(isinstance(k, int) for k in d) and sorted(d) == list(range(1, len(d) + 1)):
            return [d[k] for k in range(1, len(d) + 1)]
        return d

    def chunk(self) -> dict:
        out = {}
        while self.peek()[0] is not None:
            name = self.take()[1]
            self.take("=")
            out[name] = self.value()
        return out


def loads(text: str) -> dict:
    return _Parser(text).chunk()


def load_savedvariables(path: str | Path) -> dict:
    return loads(Path(path).read_text(encoding="utf-8", errors="replace"))

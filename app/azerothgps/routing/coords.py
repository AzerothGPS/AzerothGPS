"""Map (uiMapID, x, y) <-> world (continent, X, Y) conversion. See docs/coordinates.md."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MapFrame:
    id: int
    name: str
    continent: int
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width_yd(self) -> float:  # east-west extent (world Y)
        return self.max_y - self.min_y

    @property
    def height_yd(self) -> float:  # north-south extent (world X)
        return self.max_x - self.min_x


class Coords:
    def __init__(self, maps: list[dict]) -> None:
        self.frames: dict[int, MapFrame] = {}
        self.names: dict[int, str] = {}
        for m in maps:
            self.names[m["id"]] = m["name"]
            if "continent" in m:
                self.frames[m["id"]] = MapFrame(
                    m["id"], m["name"], m["continent"], m["minX"], m["minY"], m["maxX"], m["maxY"])

    @classmethod
    def load(cls, path: Path) -> "Coords":
        return cls(json.loads(Path(path).read_text(encoding="utf-8"))["maps"])

    @classmethod
    def load_or_empty(cls, path: Path) -> "Coords":
        return cls.load(path) if Path(path).exists() else cls([])

    def map_to_world(self, ui_map_id: int, x: float, y: float) -> tuple[int, float, float] | None:
        f = self.frames.get(ui_map_id)
        if f is None:
            return None
        return f.continent, f.max_x - y * f.height_yd, f.max_y - x * f.width_yd

    def world_to_map(self, ui_map_id: int, wx: float, wy: float) -> tuple[float, float] | None:
        f = self.frames.get(ui_map_id)
        if f is None:
            return None
        return (f.max_y - wy) / f.width_yd, (f.max_x - wx) / f.height_yd

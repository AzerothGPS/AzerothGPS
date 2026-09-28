# Coordinate systems

## Map coordinates `(uiMapID, x, y)`
What `C_Map.GetPlayerMapPosition` returns and what the beacon sends. `x` goes
right (east), `y` goes down (south), both 0–1 across the zone's map art
(1002×668 px for classic-style art).

## World coordinates `(continent MapID, X, Y)` in yards
WoW's axes do **not** match the screen:

- **World X points north**, **world Y points west**.
- Screen-right (east) = decreasing Y; screen-down (south) = decreasing X.

`UiMapAssignment.Region` is `[minX, minY, minZ, maxX, maxY, maxZ]` (verified
on build 1.60.1.69977). For the full-zone assignment (`UiMin=(0,0)`, `UiMax=(1,1)`):

```
map_x = (maxY - worldY) / (maxY - minY)
map_y = (maxX - worldX) / (maxX - minX)
worldY = maxY - map_x * (maxY - minY)
worldX = maxX - map_y * (maxX - minX)
```

Examples (Forever 1.60.1.69977):

| Zone | uiMap | Continent | X range | Y range |
|---|---|---|---|---|
| Durotar | 1411 | 1 (Kalimdor) | −1717 … 1808 | −7250 … −1962 |
| Elwynn Forest | 1429 | 0 (Eastern Kingdoms) | −10254 … −7940 | −1935 … 1535 |

**Verified in game (build 1.60.1.70009):** `GetWorldPosFromMapPos(1411, (0,0))`
= (1808.33, −1962.5) and `(1,1)` = (−1716.67, −7250), matching the DB2 region
exactly. `UnitPosition` (−568.5, −4436.9) converts with the formulas above to
map (0.46797, 0.67428), and `GetPlayerMapPosition` returned (0.46798, 0.67427).

## Terrain grid
64×64 ADT tiles per continent, 533.33 yd each; 16×16 chunks per tile
(33.33 yd); 64×64 alpha texels per chunk (≈0.52 yd). Tile indices:

```
tile_x = 32 - worldY / 533.33   (east)
tile_y = 32 - worldX / 533.33   (south)
```

WDT `MAID` entry `i` is tile `(x = i % 64, y = i // 64)`. Alpha maps are
row-major with rows going south and columns going east. The Durotar/Elwynn
overlays in the Phase 0 spike confirm this orientation (roads meet the map art's bridges).

## Interiors (WMO minimaps)

Verified on build 1.60.1.70009 (Undercity, `/agps debug interior`):

- Placement (ADT `obj0` MODF): world X = 17066.67 − pos.z, Y = 17066.67 − pos.x, Z = pos.y.
- Local (lx, ly) → world: X = X₀ + lx·cos t − ly·sin t, Y = Y₀ + lx·sin t + ly·cos t,
  with **t = rot.y + 180°**.
- Minimap images `world/minimaps/wmo/<wmo>_<group:3>_<bx:2>_<by:2>.blp`: 2 px per yard,
  128 yd per block, blocks stacked from the group's bbox minimum; columns run +x and the
  top image row is the highest local y. Images are cropped to the group (may be < 256 px).
- `UnitPosition` reports Z = 0 and Forever reports `IsIndoors() = false` / `IsOutdoors() = true`
  throughout Undercity, so the room is chosen by `GetMinimapZoneText()` against
  `WMOAreaTable` names (matched via the group's MOGP group ID).

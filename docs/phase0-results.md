> Historical: from the external-app design. The API findings still apply to the addon; the beacon sections no longer do. See plan.md.

# Phase 0 results (2026-09-24)

Client: WoW Forever 1.60.1.70009 (interface 16001), Windows 11, 5120×1440, dxcam capture.

## Gate: PASS

| Spike | Result |
|---|---|
| API check | Pass. Position, facing, zone and flags work in and out of combat and indoors. |
| Pixel channel | Pass. 100% valid at 8 bpc, 15 Hz, in every mode tested. |
| Client extraction | Pass. Map art, DB2 tables and terrain layers read directly; road overlay aligns with the map art. |

## API probe
- `GetPlayerMapPosition`, `GetPlayerFacing`, `UnitPosition`: available in combat.
- `GetUnitSpeed`: returns **secret values in combat**. The addon sends 0; the app must
  derive speed from position deltas while `inCombat` is set (Phase 1).
- `GetWorldPosFromMapPos` corners match `UiMapAssignment.Region` exactly (see coordinates.md).
- `C_TaxiMap.GetTaxiNodesForMap` works at login without visiting a flight master
  (38 Kalimdor / 36 EK nodes) but carries **no known/unknown state**. Known nodes still
  require `TAXIMAP_OPENED` → `GetAllTaxiNodes`.
- Not yet tested: flight timing (character has no flight path yet).

## Beacon (60 s each)
| Mode | Captures | Valid | Addon frames seen/sent |
|---|---|---|---|
| Fullscreen, default | 2637 | 100% | 900/900 |
| Fullscreen, test pattern | 3529 | 100% (0 mismatches) | 899/899 |
| Windowed | 3321 | 100% | 899/899 |

UI scale: not changeable in this client; the strip is parentless and ignores UI scale anyway
(effective UIParent scale was 0.64 during all runs). HDR/sharpening: not used by this player.

## Known follow-ups
- Re-extract data for build 70009 (spike ran on 69977).
- Road texture review: Durotar decorative `durotarroad_s` specks; Elwynn Goldshire→Stormwind
  road not matched (Phase 3).
- Add a "speed unknown" flag for combat (Phase 1).

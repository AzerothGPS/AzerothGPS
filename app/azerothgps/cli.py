"""agps: developer tools for the AzerothGPS addon.

The addon runs entirely in game. These commands read the *local* client to
generate the addon's data files and to inspect/test it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .paths import ADDON_DIR, DEFAULT_FLAVOR, DEFAULT_WOW, data_dir, wtf_account_dir

DATA = data_dir()
PRODUCT = "wow_classic_beta"


def _client(args):
    from .extract.spike import ClientData

    ref = DATA / "ref"
    if not (ref / "listfile.csv").exists():
        raise SystemExit(f"missing {ref / 'listfile.csv'} (community listfile) and {ref / 'dbd'}/*.dbd")
    t = time.time()
    cd = ClientData(Path(args.wow_path), args.product, ref)
    print(f"client {args.product} {cd.casc.version} ({time.time() - t:.1f}s)")
    return cd


def cmd_extract(args) -> int:
    from .extract.pipeline import run_extract

    cd = _client(args)
    manifest = run_extract(cd, DATA)
    if not args.skip_roads:
        from .roads.build import build_roads

        manifest["roads"] = build_roads(cd, DATA)
        (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_roads(args) -> int:
    from .roads.build import build_roads

    cd = _client(args)
    print(json.dumps(build_roads(cd, DATA, tuple(args.continents) if args.continents else None), indent=2))
    return 0


def cmd_watch_roads(args) -> int:
    """Each time the game writes the saved variables (a /reload, logging out): the roads drawn
    in game that are new go into overrides/ and the road data, and the addon is installed
    again (the next /reload has them as roads of its own; the drawn copies are dropped)."""
    from .extract.pipeline import CONTINENTS
    from .paths import RESOURCES
    from .roads.build import reapply_overrides
    from .roads.export import write_roads_lua
    from .roads.tracks import import_tracks

    wtf = wtf_account_dir(Path(args.wow_path), args.flavor)
    print(f"watching {wtf} for drawn roads (Ctrl+C stops)")
    last: dict = {}
    while True:
        files = sorted(wtf.glob("*/SavedVariables/AzerothGPS.lua"))
        cur = {f: f.stat().st_mtime for f in files}
        if cur != last:
            try:
                per: dict = {}
                n = import_tracks(wtf, RESOURCES / "overrides", per)
                last = cur
                if n:
                    stamp = time.strftime("%H:%M:%S")
                    print(f"{stamp} {n} new drawn road(s): {per}")
                    reapply_overrides(DATA, [c for c in per if c in CONTINENTS])
                    if any(c not in CONTINENTS for c in per):  # (a city's own level)
                        from .cities import cities_lua

                        (ADDON_DIR / "Data" / "Cities.lua").write_text(cities_lua(_client(args)), encoding="utf-8",
                                                                       newline="\n")
                    write_roads_lua(DATA, ADDON_DIR)
                    cmd_install_addon(args)
                    print(f"{time.strftime('%H:%M:%S')} in the road data: /reload in game to load it")
            except Exception as e:  # (e.g. read while the game was still writing it: again next time)
                print(f"couldn't import yet: {e}")
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_npc_paths(args) -> int:
    from .extract.pipeline import CONTINENTS
    from .paths import RESOURCES
    from .roads.npcpaths import write_overrides

    print(write_overrides(DATA, RESOURCES / "overrides", CONTINENTS))
    print("then: agps roads (or agps watch-roads picks them up with the next drawn road)")
    return 0


def cmd_route_check(args) -> int:
    from .routecheck import check, write_report

    modes = ("offroad", "road") if args.mode == "both" else (args.mode,)
    result = check(samples=args.samples, seed=args.seed, only=args.zone, modes=modes)
    out = write_report(result, DATA / "debug" / "route-check")
    n = len(result["flagged"])
    trips = sum(z["trips"] for z in result["zones"])
    print(f"{n} flagged of {trips} trips in {len(result['zones'])} zones; details: {out}")
    return 0


def cmd_route_sweep(args) -> int:
    from .routesweep import sweep, write_report

    result = sweep(trips=args.trips, seed=args.seed, only=args.zone, minutes=args.minutes)
    out = write_report(result, DATA / "debug" / "route-sweep")
    print(f"{len(result['flagged'])} flagged of {result['trips']} trips (seed {result['seed']}); details: {out}")
    return 0


def cmd_gen_addon_data(args) -> int:
    from .addon_data import generate

    cd = _client(args)
    for p in generate(cd, ADDON_DIR):
        print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
    return 0


def cmd_caves(args) -> int:
    """Caves and mines: build them, render each (data/debug/caves/), list what's covered and
    what's skipped (summary.txt), and with --write, Data/Caves.lua."""
    from .caves import build_continent, caves_lua, render_debug

    cd = _client(args)
    out = DATA / "debug" / "caves"
    report: list = []
    if args.only:
        for cont in (0, 1):
            for u in build_continent(cd, cont, DATA, only=args.only, report=report):
                render_debug(u, out)
    else:
        text = caves_lua(cd, debug_dir=out, report=report)
        if args.write:
            p = ADDON_DIR / "Data" / "Caves.lua"
            p.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
    lines = [f"{status:8s} [{cont}] {name or '(unnamed)'} ({uid}) {path.split('/')[-1]}: {why}"
             for cont, name, uid, path, status, why in sorted(report, key=lambda r: (r[4], r[0], r[1] or "~"))]
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    n = sum(1 for r in report if r[4] == "covered")
    print(f"{n} caves covered, {len(report) - n} skipped; renders and summary.txt in {out}")
    return 0


def cmd_capitals(args) -> int:
    """Capital cities at ground level: build them, render each (data/debug/capitals/) with
    summary.txt, and with --write, Data/Capitals.lua."""
    from .capitals import build_all, capitals_lua, render_debug

    cd = _client(args)
    out = DATA / "debug" / "capitals"
    logs: list = []

    def log(s):
        print(s)
        logs.append(s)

    built = build_all(cd, DATA, log=log, only=args.only)
    for u in built:
        render_debug(u, out)
    out.mkdir(parents=True, exist_ok=True)
    if args.write:
        if args.only:
            print("--write builds every capital: run it without --only")
            return 1
        p = ADDON_DIR / "Data" / "Capitals.lua"
        p.write_text(capitals_lua(cd, log=log, built=built), encoding="utf-8", newline="\n")
        print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
    if args.check:  # (the routes over Data/Capitals.lua as it is: --write first after a change)
        from .capitals import check_routes

        log("-- routes from outside each gate to the places (the addon's routing, 3D walk over the floors):")
        check_routes(built, log=log)
    (out / "summary.txt").write_text("\n".join(logs) + "\n", encoding="utf-8")
    print(f"{len(built)} capitals built; renders and summary.txt in {out}")
    return 0


def cmd_instances(args) -> int:
    """Dungeons and raids: build them, render each (data/debug/instances/) with summary.txt
    (covered and skipped), with --write Data/Instances.lua, with --check the routes from the
    entrance to every boss walked in 3D."""
    from .instances import build_all, check_routes, instances_lua, render_debug

    cd = _client(args)
    out = DATA / "debug" / "instances"
    logs: list = []

    def log(s):
        print(s)
        logs.append(s)

    report: list = []
    built = build_all(cd, DATA, log=log, only=args.only, report=report)
    for inst, u in built:
        render_debug(inst, u, out)
    text = instances_lua(cd, built, log=log) if (args.write or args.check) else None
    if args.write:
        if args.only:
            print("--write builds every instance: run it without --only")
            return 1
        p = ADDON_DIR / "Data" / "Instances.lua"
        p.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
    if args.check:  # (the routes over the data just built)
        log("-- routes from the entrance to each boss (the addon's routing, 3D walk over the floors):")
        check_routes(built, log=log, text=text)
    lines = [f"{status:8s} {inst.name} ({inst.map_id}{', raid' if inst.raid else ''}): {why}"
             for inst, status, why in sorted(report, key=lambda r: (r[1], r[0].raid, r[0].map_id))]
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.txt").write_text("\n".join(lines + ["", "-- log:"] + logs) + "\n", encoding="utf-8")
    print(f"{len(built)} instances built, {len(report) - len(built)} skipped; renders and summary.txt in {out}")
    return 0


def cmd_terrain_hpa(args) -> int:
    from .hpa import write

    print(f"wrote {write()}")
    return 0


def cmd_city_places(args) -> int:
    """Heights of the capitals' service locations (Data/CityPlaces.lua) from their NPCs' spawns."""
    from .cityplaces import FILE, map_bounds, npc_spawns, with_heights
    from .paths import data_dir

    maps = map_bounds()
    text, n, missing = with_heights(FILE.read_text(encoding="utf-8"), maps, npc_spawns(data_dir()))
    FILE.write_text(text, encoding="utf-8", newline="\n")
    print(f"{n} places with their NPC's height; none found for {len(missing)}: {', '.join(missing)}")
    return 0


def cmd_install_addon(args) -> int:
    import shutil

    from .hpa import refresh

    dst = Path(args.wow_path) / args.flavor / "Interface" / "AddOns" / "AzerothGPS"
    if not dst.parent.is_dir():
        print(f"no AddOns folder at {dst.parent}")
        return 1
    refresh()  # (the terrain's blocks, when the terrain or the shipped walls changed: Data/TerrainHPA.lua)
    # Copy over the installed addon, then remove files the addon no longer has (a clean copy
    # without deleting everything first: a file another program has open can't stop halfway
    # and leave the folder half empty).
    shutil.copytree(ADDON_DIR, dst, dirs_exist_ok=True)
    keep = {p.relative_to(ADDON_DIR) for p in ADDON_DIR.rglob("*")}
    for p in sorted(dst.rglob("*"), reverse=True):
        if p.relative_to(dst) not in keep:
            try:
                p.unlink() if p.is_file() else p.rmdir()
            except OSError as e:
                print(f"couldn't remove stale {p}: {e}")
    old = dst.parent / "AzerothGPS_Link"
    if old.is_dir():
        shutil.rmtree(old)  # replaced by AzerothGPS
        print(f"removed old {old}")
    print(f"copied addon to {dst} -- /reload in game to pick up changes")
    if getattr(args, "dev", False):
        # the private dev tools (AzerothGPS-Dev, checked out next to this repo): never shipped
        src = ADDON_DIR.parents[2] / "AzerothGPS-Dev" / "addon" / "AzerothGPS_Dev"
        if not src.is_dir():
            print(f"no dev addon at {src} (clone the private AzerothGPS-Dev repo next to this one)")
            return 1
        ddst = dst.parent / "AzerothGPS_Dev"
        if ddst.is_dir():
            shutil.rmtree(ddst)
        shutil.copytree(src, ddst)
        print(f"copied dev tools to {ddst} (new files: restart the game the first time)")
    return 0


def cmd_probes(args) -> int:
    from .savedvars.parser import load_savedvariables

    base = wtf_account_dir(Path(args.wow_path), args.flavor)
    files = sorted(base.glob("*/SavedVariables/AzerothGPS.lua"))
    if not files:
        print(f"no AzerothGPS.lua under {base} (/reload once after installing the addon)")
        return 1
    for f in files:
        db = load_savedvariables(f).get("AzerothGPSDB", {})
        print(f"== {f}")
        probes = db.get("probes") or []  # an empty Lua table parses as {}
        for p in probes[-args.last:]:
            print(f"-- {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(p.get('time', 0)))} ({p.get('reason')})")
            for r in p.get("results", []):
                print(f"   {r.get('name')} = {r.get('value')}")
    return 0


def cmd_perf(args) -> int:
    """Print the /agps debug perf snapshots saved in SavedVariables (newest last)."""
    from .savedvars.parser import load_savedvariables

    base = wtf_account_dir(Path(args.wow_path), args.flavor)
    files = sorted(base.glob("*/SavedVariables/AzerothGPS.lua"))
    if not files:
        print(f"no AzerothGPS.lua under {base} (/reload once after installing the addon)")
        return 1
    for f in files:
        snaps = load_savedvariables(f).get("AzerothGPSDB", {}).get("perf") or []
        if isinstance(snaps, dict):  # an empty Lua table parses as {}
            snaps = list(snaps.values())
        print(f"== {f}")
        if not snaps:
            print("   no snapshots: run /agps debug perf in game, then /reload")
        for snap in snaps[-args.last:]:
            span = snap.get("span") or 1
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap.get("time", 0)))
            print(f"-- {when}: {span:.0f} s measured, {snap.get('fps', 0):.0f} fps, version {snap.get('version')}")
            print(f"   settings: {snap.get('settings')}")
            rows = snap.get("rows") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
            print(f"   {'part':40} {'ms/s':>7} {'avg ms':>7} {'max ms':>7} {'runs/s':>7} {'>16ms':>6}")
            for r in sorted(rows, key=lambda r: r.get("name", "")):
                n = r.get("n") or 1
                print(f"   {r.get('name', '?'):40} {r.get('total', 0) / span:7.2f} {r.get('total', 0) / n:7.2f}"
                      f" {r.get('max', 0):7.1f} {n / span:7.1f} {r.get('slow', 0):6d}")
    return 0


def cmd_import_shared(args) -> int:
    """Roads players copied from the share page (a text file of them) into the road data."""
    from .extract.pipeline import CONTINENTS
    from .paths import RESOURCES
    from .roads.build import reapply_overrides
    from .roads.export import write_roads_lua
    from .roads.tracks import import_shared

    per: dict = {}
    if args.github:
        # (the open "road data" issues: their bodies hold the pasted text)
        import subprocess

        out = subprocess.run(["gh", "issue", "list", "-R", args.repo, "-l", "road data", "--state", "open",
                              "--limit", "200", "--json", "number,body"], capture_output=True, text=True, check=True)
        issues = json.loads(out.stdout or "[]")
        text = "\n".join(i.get("body") or "" for i in issues)
        print(f"{len(issues)} open road data issue(s) in {args.repo}")
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        print("give a file, or --github")
        return 1
    n = import_shared(text, RESOURCES / "overrides", per)
    print(f"{n} new road(s): {per}")
    from .instances import merge_entrances, parse_shared_entrances

    ne = merge_entrances(parse_shared_entrances(text))
    if ne:
        print(f"{ne} new dungeon way(s) in: agps instances --write to put them in the data")
    if n:
        reapply_overrides(DATA, [c for c in per if c in CONTINENTS])
        write_roads_lua(DATA, ADDON_DIR)
        print("in the road data (city levels: run agps gen-addon-data for Cities.lua)")
    return 0


def cmd_entrances(args) -> int:
    """Dungeons' ways in the addon learned in game (SavedVariables) into
    overrides/instance_entrances.json."""
    from .instances import merge_entrances, saved_entrances
    from .savedvars.parser import load_savedvariables

    base = wtf_account_dir(Path(args.wow_path), args.flavor)
    n = 0
    for f in sorted(base.glob("*/SavedVariables/AzerothGPS.lua")):
        n += merge_entrances(saved_entrances(load_savedvariables(f)))
    print(f"{n} new dungeon way(s) in" + (": agps instances --write to put them in the data" if n else ""))
    return 0


def cmd_feedback(args) -> int:
    """Export the opt-in feedback (shared roads, faster trips) to a JSON file for upload."""
    from .savedvars.parser import load_savedvariables

    base = wtf_account_dir(Path(args.wow_path), args.flavor)
    roads, trips = [], []
    for f in sorted(base.glob("*/SavedVariables/AzerothGPS.lua")):
        fb = load_savedvariables(f).get("AzerothGPSDB", {}).get("feedback") or {}
        as_list = lambda v: v if isinstance(v, list) else list((v or {}).values())
        roads += as_list(fb.get("roads"))
        trips += as_list(fb.get("trips"))
    if not roads and not trips:
        print("no feedback saved (turn on the sharing options in game, then /reload)")
        return 1
    out = DATA / "feedback" / time.strftime("feedback-%Y%m%d-%H%M%S.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"format": 1, "roads": roads, "trips": trips}, indent=1), encoding="utf-8")
    print(f"wrote {out}: {len(roads)} roads, {len(trips)} trips (uploading comes later)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="agps", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def client_args(sp):
        sp.add_argument("--wow-path", default=str(DEFAULT_WOW))
        sp.add_argument("--product", default=PRODUCT, help="product code in .build.info")

    sp = sub.add_parser("route-check", help="run the addon's routing on random trips per zone; flag bad routes")
    sp.add_argument("--samples", type=int, default=20, help="trips per zone")
    sp.add_argument("--seed", type=int, default=1)
    sp.add_argument("--zone", help="only zones whose name contains this")
    sp.add_argument("--mode", choices=("offroad", "road", "both"), default="offroad",
                    help="route with offroad shortcuts, along the roads, or both")
    sp.set_defaults(fn=cmd_route_check)

    sp = sub.add_parser("entrances", help="dungeons' ways in the addon learned in game into overrides/")
    sp.add_argument("--wow-path", default=str(DEFAULT_WOW))
    sp.add_argument("--flavor", default=DEFAULT_FLAVOR)
    sp.set_defaults(fn=cmd_entrances)

    sp = sub.add_parser("route-sweep", help="random trips in random zones, routed as in game: snapbacks, U-turns, spikes")
    sp.add_argument("--trips", type=int, default=60)
    sp.add_argument("--minutes", type=float, help="run for this long instead (as many trips as fit)")
    sp.add_argument("--seed", type=int, help="(random when left out)")
    sp.add_argument("--zone", help="only zones whose name contains this")
    sp.set_defaults(fn=cmd_route_sweep)

    sp = sub.add_parser("gen-addon-data", help="write addon/AzerothGPS/Data/*.lua from the client")
    client_args(sp)
    sp.set_defaults(fn=cmd_gen_addon_data)

    sp = sub.add_parser("caves", help="build the caves' grids and roads; renders and a summary in data/debug/caves/")
    client_args(sp)
    sp.add_argument("--only", nargs="+", help="only caves whose name contains one of these (or with this placement id)")
    sp.add_argument("--write", action="store_true", help="also write Data/Caves.lua (gen-addon-data writes it too)")
    sp.set_defaults(fn=cmd_caves)

    sp = sub.add_parser("capitals", help="build the capitals' grids and roads; renders in data/debug/capitals/")
    client_args(sp)
    sp.add_argument("--only", nargs="+", help="only capitals whose name contains one of these")
    sp.add_argument("--write", action="store_true", help="also write Data/Capitals.lua (gen-addon-data writes it too)")
    sp.add_argument("--check", action="store_true",
                    help="route from outside each gate to its places over the data and walk them in 3D")
    sp.set_defaults(fn=cmd_capitals)

    sp = sub.add_parser("instances", help="build the dungeons' and raids' levels; renders in data/debug/instances/")
    client_args(sp)
    sp.add_argument("--only", nargs="+", help="only instances whose name contains one of these (or with this MapID)")
    sp.add_argument("--write", action="store_true", help="also write Data/Instances.lua (gen-addon-data writes it too)")
    sp.add_argument("--check", action="store_true",
                    help="route from each entrance to every boss over the data and walk the routes in 3D")
    sp.set_defaults(fn=cmd_instances)

    sp = sub.add_parser("extract", help="extract map art, bounds, POIs, area grid (+ roads) into data/")
    client_args(sp)
    sp.add_argument("--skip-roads", action="store_true", help="skip the (slower) road network build")
    sp.set_defaults(fn=cmd_extract)

    sp = sub.add_parser("roads", help="rebuild road networks (after editing overrides/)")
    client_args(sp)
    sp.add_argument("--continents", type=int, nargs="+", default=None, help="map IDs (default: all: 0 Eastern Kingdoms, 1 Kalimdor, 2991 Zephras Isle)")
    sp.set_defaults(fn=cmd_roads)

    sp = sub.add_parser("import-shared", help="roads players copied from the share page into the road data")
    sp.add_argument("file", nargs="?", help="a text file of it")
    sp.add_argument("--github", action="store_true", help="from the open 'road data' GitHub issues instead")
    sp.add_argument("--repo", default="AzerothGPS/AzerothGPS")
    sp.set_defaults(fn=cmd_import_shared)

    sp = sub.add_parser("npc-paths", help="NPC travel paths (data/thirdparty) into overrides/paths_<map>.geojson")
    sp.set_defaults(fn=cmd_npc_paths)

    sp = sub.add_parser("watch-roads", help="on every /reload: roads drawn in game go into the road data")
    client_args(sp)
    sp.add_argument("--flavor", default=DEFAULT_FLAVOR)
    sp.add_argument("--interval", type=float, default=3.0, help="seconds between checks")
    sp.add_argument("--once", action="store_true", help="check once and stop")
    sp.set_defaults(fn=cmd_watch_roads)

    sp = sub.add_parser("city-places", help="heights of the capitals' service locations (Data/CityPlaces.lua) from NPC spawns")
    sp.set_defaults(fn=cmd_city_places)

    sp = sub.add_parser("terrain-hpa", help="prepare the terrain's blocks for the walk search (Data/TerrainHPA.lua)")
    sp.set_defaults(fn=cmd_terrain_hpa)

    sp = sub.add_parser("install-addon", help="copy the addon into the WoW AddOns folder")
    sp.add_argument("--wow-path", default=str(DEFAULT_WOW))
    sp.add_argument("--flavor", default=DEFAULT_FLAVOR)
    sp.add_argument("--dev", action="store_true", help="also the private dev tools (../AzerothGPS-Dev)")
    sp.set_defaults(fn=cmd_install_addon)

    sp = sub.add_parser("probes", help="show /agps debug results from SavedVariables")
    sp.add_argument("--wow-path", default=str(DEFAULT_WOW))
    sp.add_argument("--flavor", default=DEFAULT_FLAVOR)
    sp.add_argument("--last", type=int, default=5)
    sp.set_defaults(fn=cmd_probes)

    sp = sub.add_parser("perf", help="show /agps debug perf timings saved in SavedVariables")
    sp.add_argument("--wow-path", default=str(DEFAULT_WOW))
    sp.add_argument("--flavor", default=DEFAULT_FLAVOR)
    sp.add_argument("--last", type=int, default=3)
    sp.set_defaults(fn=cmd_perf)

    sp = sub.add_parser("feedback", help="export shared roads and faster trips (opt-in) to data/feedback/")
    sp.add_argument("--wow-path", default=str(DEFAULT_WOW))
    sp.add_argument("--flavor", default=DEFAULT_FLAVOR)
    sp.set_defaults(fn=cmd_feedback)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

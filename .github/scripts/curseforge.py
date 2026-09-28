"""Upload a release zip to CurseForge (the release workflow), or just look up the game
version to upload for (--dry-run).

Environment: CF_API_TOKEN (secret), CF_PROJECT_ID, optional CF_GAME_VERSION_ID (a number:
skips the lookup) and CF_GAME_VERSION (the name to look for, default "1.60.1").
Only the standard library: runs on a plain GitHub runner.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import uuid

API = "https://wow.curseforge.com/api"


def get(path: str, token: str):
    req = urllib.request.Request(API + path, headers={"X-Api-Token": token, "User-Agent": "AzerothGPS-release"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def game_version(token: str) -> tuple[int, str]:
    """The game version to upload for: CF_GAME_VERSION_ID, else the one named CF_GAME_VERSION."""
    if os.environ.get("CF_GAME_VERSION_ID"):
        return int(os.environ["CF_GAME_VERSION_ID"]), "(set by CF_GAME_VERSION_ID)"
    want = os.environ.get("CF_GAME_VERSION", "1.60.1")
    types = {t["id"]: t for t in get("/game/version-types", token)}
    versions = get("/game/versions", token)
    found = [v for v in versions if v.get("name") == want]
    for v in found:
        t = types.get(v.get("gameVersionTypeID"), {})
        print(f"  candidate: id {v['id']}  name {v['name']}  type {t.get('name')} ({t.get('slug')})")
    if len(found) != 1:
        # (show what's near, to set CF_GAME_VERSION_ID by hand)
        near = [v for v in versions if want.split(".")[0] + "." in v.get("name", "")][:40]
        for v in near:
            t = types.get(v.get("gameVersionTypeID"), {})
            print(f"  nearby: id {v['id']}  name {v['name']}  type {t.get('name')} ({t.get('slug')})")
        sys.exit(f"expected exactly one game version named {want!r}, found {len(found)}: "
                 "set the repository variable CF_GAME_VERSION_ID to the right id")
    t = types.get(found[0].get("gameVersionTypeID"), {})
    return found[0]["id"], f"{found[0]['name']} ({t.get('name')})"


def upload(token: str, project: str, zip_path: str, display: str, changelog: str, gv: int) -> dict:
    meta = {"changelog": changelog, "changelogType": "markdown", "displayName": display,
            "gameVersions": [gv], "releaseType": "release"}
    boundary = uuid.uuid4().hex
    with open(zip_path, "rb") as f:
        data = f.read()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n\r\n{json.dumps(meta)}\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{os.path.basename(zip_path)}\"\r\n"
        "Content-Type: application/zip\r\n\r\n"
    ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(f"{API}/projects/{project}/upload-file", data=body, method="POST", headers={
        "X-Api-Token": token, "Content-Type": f"multipart/form-data; boundary={boundary}",
        "User-Agent": "AzerothGPS-release"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="only look up the game version")
    p.add_argument("--zip")
    p.add_argument("--version")
    p.add_argument("--changelog", help="a file with the version's changelog (Markdown)")
    a = p.parse_args()
    token = os.environ.get("CF_API_TOKEN")
    project = os.environ.get("CF_PROJECT_ID")
    if not token or not project:
        sys.exit("CF_API_TOKEN and CF_PROJECT_ID are needed")
    gv, what = game_version(token)
    print(f"game version: {gv} {what}")
    if a.dry_run:
        return 0
    changelog = open(a.changelog, encoding="utf-8").read()
    res = upload(token, project, a.zip, f"Azeroth GPS v{a.version}", changelog, gv)
    print(f"uploaded to CurseForge: {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

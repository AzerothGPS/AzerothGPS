"""Smoke tests against the local Forever install. Skipped when it is absent."""

from pathlib import Path

import pytest

from azerothgps.cli import DATA, DEFAULT_WOW

REF = DATA / "ref"
pytestmark = pytest.mark.skipif(
    not (DEFAULT_WOW / ".build.info").exists() or not (REF / "listfile.csv").exists(),
    reason="needs the local WoW install and data/ref (listfile + dbd)",
)


@pytest.fixture(scope="module")
def cd():
    from azerothgps.extract.spike import ClientData

    return ClientData(DEFAULT_WOW, "wow_classic_beta", REF)


def test_durotar_assignment(cd):
    from azerothgps.extract.spike import zone_assignment

    r = zone_assignment(cd, 1411)
    assert r["MapID"] == 1
    minx, miny, _, maxx, maxy, _ = r["Region"]
    assert minx < maxx and miny < maxy


def test_taxi_node_orgrimmar(cd):
    names = {r["Name_lang"] for r in cd.table("TaxiNodes")}
    assert any("Orgrimmar" in n for n in names)


def test_map_art_size(cd):
    from azerothgps.extract.spike import compose_map_art

    assert compose_map_art(cd, 1411).size == (1002, 668)


def test_road_rules():
    from azerothgps.extract.spike import is_road, load_road_rules

    rules = load_road_rules()
    assert is_road("tileset/durotar/durotarroad_s.blp", rules)
    assert not is_road("tileset/durotar/durotardirt_s.blp", rules)

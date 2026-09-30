"""Heights of the capitals' service locations (Data/CityPlaces.lua; agps city-places)."""

import re

from azerothgps.cityplaces import FILE, matches, service


def test_the_titles_that_say_a_places_service():
    assert service("Undercity Cooking Trainer") == "Cooking Trainer"
    assert matches("Cooking Trainer", "Cooking Trainer")
    assert matches("Bank", "Banker")
    assert matches("Alchemy Trainer", "Journeyman Alchemist Trainer")
    assert matches("Tailoring Trainer", "Expert Tailor")  # (a crafting trainer: its rank)
    assert not matches("Tailoring Trainer", "Tailoring Supplies")
    assert not matches("Cooking Trainer", "Cooking Supplier")


def test_every_city_place_has_its_npcs_height():
    # (a place without one is routed to the top floor there: `agps city-places` after adding places)
    places = re.findall(r"\{ -?[\d.]+, -?[\d.]+, \"[^\"]+\"(, -?[\d.]+)? \}", FILE.read_text(encoding="utf-8"))
    assert places and all(places), [p for p in places if not p]

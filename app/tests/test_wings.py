"""Dungeons with wings (app/azerothgps/wings.py): ways in named by their wing, each boss its wing's."""

from azerothgps.wings import entrance_wing, wings


def test_ways_in_are_named_by_their_wing():
    assert entrance_wing(189, "Scarlet Monestary Library - Entering") == ("Library", None)
    assert entrance_wing(429, "Dire Maul East - Entering Back Door") == ("East", "Back Door")
    assert entrance_wing(429, "Dire Maul East - Entering") == ("East", None)
    assert entrance_wing(329, "Stratholme - Entering Back Door") == ("Service Entrance", None)
    assert entrance_wing(329, "Stratholme - Entering Left Front") == ("Main Gate", None)
    assert entrance_wing(429, "Dire Maul") == (None, None)
    assert entrance_wing(36, "Deadmines - Entering") == (None, None)  # (no wings)


def test_each_boss_is_its_wings_whose_way_in_reaches_it_soonest():
    # two wings walled off from each other (roads A and B apart), a third way in unnamed on A's roads, and
    # a boss on each; a boss off the roads goes with the road nearest it
    nodes = [(0, 0), (100, 0), (200, 0), (0, 300), (100, 300)]
    edges = [(0, 1, [(0, 0), (100, 0)]), (1, 2, [(100, 0), (200, 0)]), (3, 4, [(0, 300), (100, 300)])]
    ents = [(0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, "Dire Maul East - Entering"),
            (0, 2.0, 2.0, 0.0, 0.0, 300.0, 0.0, "Dire Maul West - Entering"),
            (0, 3.0, 3.0, 0.0, 200.0, 0.0, 0.0, "Dire Maul")]
    bosses = [{"name": "a", "x": 100.0, "y": 0.0, "z": 0.0}, {"name": "b", "x": 100.0, "y": 300.0, "z": 0.0},
              {"name": "c", "x": None, "y": None}, {"name": "d", "x": 0.0, "y": 160.0, "z": 0.0}]
    named, boss_wing, order = wings(429, ents, bosses, nodes, edges, None)
    assert order == ["East", "West"]
    assert named == [("East", None), ("West", None), ("East", None)]  # (the unnamed one: on East's roads)
    assert boss_wing == {0: "East", 1: "West", 3: "West"}  # (d: nearest West's road, at (0, 300))


def test_a_dungeon_without_wings_has_none():
    nodes = [(0, 0), (100, 0)]
    edges = [(0, 1, [(0, 0), (100, 0)])]
    ents = [(0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, "Deadmines - Entering")]
    assert wings(36, ents, [{"name": "x", "x": 100.0, "y": 0.0, "z": 0.0}], nodes, edges, None) == ([], {}, [])


def test_known_bosses_go_to_their_wing_and_doors_split_none():
    # (the roads' guess was wrong where wings' roads meet: Stratholme's halves are one city) the bosses known
    # by name go to their wing, Maraudon's inner ones to both; Uldaman's back way in is a door: no split
    nodes = [(0, 0), (100, 0)]
    edges = [(0, 1, [(0, 0), (100, 0)])]
    ents = [(0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, "Stratholme - Entering Right Front"),
            (0, 2.0, 2.0, 0.0, 100.0, 0.0, 0.0, "Stratholme - Entering Back Door")]
    bosses = [{"name": "The Unforgiven", "x": 100.0, "y": 0.0, "z": 0.0}, {"name": "Baron Rivendare", "x": 0.0, "y": 0.0, "z": 0.0}]
    _named, boss_wing, order = wings(329, ents, bosses, nodes, edges, None)
    assert order == ["Main Gate", "Service Entrance"] and boss_wing == {0: "Main Gate", 1: "Service Entrance"}
    ents = [(1, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, "Maraudon Orange - Entering"), (1, 2.0, 2.0, 0.0, 100.0, 0.0, 0.0, "Maraudon Purple - Entering")]
    _named, boss_wing, _order = wings(349, ents, [{"name": "Princess Theradras", "x": 50.0, "y": 0.0, "z": 0.0}], nodes, edges, None)
    assert boss_wing == {0: ["Orange", "Purple"]}
    ents = [(0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, "Uldaman - Entering"), (0, 2.0, 2.0, 0.0, 100.0, 0.0, 0.0, "Uldaman Exit")]
    named, boss_wing, order = wings(70, ents, [{"name": "Archaedas", "x": 100.0, "y": 0.0, "z": 0.0}], nodes, edges, None)
    assert named == [("Front Entrance", None), ("Back Entrance", None)] and boss_wing == {} and order == ["Front Entrance", "Back Entrance"]

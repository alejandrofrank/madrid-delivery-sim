"""Urban geometry, directionality and entity integrity contracts."""

import networkx as nx
import pytest

from delivery.catalogue import digest
from delivery.city import fake_city
from delivery.urban_city import urban_city


def test_urban_city_is_deterministic_and_preserves_anchors():
    source = fake_city(42, size=32)
    before = digest(source)
    city = urban_city(source)
    assert digest(source) == before
    assert city == urban_city(source)
    for key in ("nodes", "stores", "facilities"):
        assert city[key] == source[key]
    assert city["sha256"] == digest({k: v for k, v in city.items() if k != "sha256"})
    assert urban_city(fake_city(43, size=32))["buildings"] != city["buildings"]


def test_directed_streets_connect_all_nodes_and_preserve_physical_edges():
    source = fake_city(42, size=32)
    city = urban_city(source)
    original = {(e["from"], e["to"]): e for e in source["edges"]}
    actual = {(e["from"], e["to"]): e for e in city["edges"]}
    graph = nx.DiGraph(list(actual))
    assert len(graph) == 1024 and nx.is_strongly_connected(graph)
    assert len(actual) < 3968
    assert any((b, a) not in actual for a, b in actual)
    for (a, b), edge in actual.items():
        assert edge["modes"] == original[a, b]["modes"]
        assert edge["travel_seconds"] == original[a, b]["travel_seconds"]
        assert abs(a % 32 - b % 32) + abs(a // 32 - b // 32) == 1
        assert edge["road_kind"] in {"avenue", "street"} and edge["road_name"]
        if edge["direction"] == "bidirectional":
            assert (b, a) in actual
    for a, b in original:
        if (a // 32 == b // 32 and a // 32 in (0, 31)) or (a % 32 == b % 32 and a % 32 in (0, 31)):
            assert (a, b) in actual


def test_customers_have_real_residences_clear_of_roads_and_anchors():
    city = urban_city(fake_city(42, size=32))
    buildings = {b["id"]: b for b in city["buildings"]}
    anchors = {a["node"] for a in city["stores"] + city["facilities"]}
    nodes = {n["id"] for n in city["nodes"]}
    assert len(city["customers"]) == 128 and len(city["neighborhoods"]) == 9
    assert sum(b["kind"] == "park" for b in buildings.values()) == 16
    assert sum(b["kind"] == "office" for b in buildings.values()) == 24
    assert len({b["node"] for b in buildings.values()}) == len(buildings)
    for b in buildings.values():
        assert b["node"] in nodes and b["node"] not in anchors
        assert 80 <= b["x"] % 500 <= 200 and 80 <= b["y"] % 500 <= 200
        assert b["x"] % 500 + b["width"] < 500
        assert b["y"] % 500 + b["height"] < 500
        assert 0 <= b["x"] < b["x"] + b["width"] <= 15500
        assert 0 <= b["y"] < b["y"] + b["height"] <= 15500
    for c in city["customers"]:
        home = buildings[c["home_id"]]
        assert home["kind"] in {"home", "apartment"}
        assert c["home_node"] == home["node"]
        assert c["address"] == home["address"]


def test_legacy_grid_requires_explicit_large_city():
    with pytest.raises(ValueError):
        urban_city(fake_city())

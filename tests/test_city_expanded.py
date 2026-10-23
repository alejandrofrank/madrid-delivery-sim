from collections import Counter, deque
from pathlib import Path

import pytest

from delivery.catalogue import digest, load_catalogue
from delivery.city import fake_city


def test_expanded_grid_connected_and_adjacent() -> None:
    city = fake_city(42, size=32)
    assert (city["width"], city["height"], city["seed"]) == (32, 32, 42)
    nodes = {node["id"]: node for node in city["nodes"]}
    assert len(nodes) == 1024
    edges = {(e["from"], e["to"]) for e in city["edges"]}
    assert len(edges) == len(city["edges"]) == 3968
    adjacency: dict[int, list[int]] = {node: [] for node in nodes}
    for start, end in edges:
        a, b = nodes[start], nodes[end]
        assert abs(a["x"] - b["x"]) + abs(a["y"] - b["y"]) == 500
        assert (end, start) in edges
        adjacency[start].append(end)
    visited, queue = {0}, deque([0])
    while queue:
        for neighbor in adjacency[queue.popleft()]:
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    assert visited == set(nodes)
    assert Counter(s["kind"] for s in city["stores"]) == {
        "supermarket": 6,
        "retail": 3,
        "pharmacy": 3,
    }
    assert [s["id"] for s in city["stores"]] == [f"store-{i}" for i in range(1, 13)]
    anchors = city["stores"] + city["facilities"]
    assert len({a["node"] for a in anchors}) == len(anchors)
    assert all(a["node"] in nodes for a in anchors)
    assert {f["kind"] for f in city["facilities"]} == {
        "depot",
        "supplier",
        "fuel",
        "charger",
    }
    assert city == fake_city(42, size=32)
    assert city["sha256"] == digest({k: v for k, v in city.items() if k != "sha256"})
    assert city["sha256"] != fake_city(43, size=32)["sha256"]


def test_expanded_catalogue_domains_are_explicitly_simulated() -> None:
    catalogue = load_catalogue(Path("data/expanded-catalogue.json"))
    assert "Simulated synthetic" in catalogue.origin
    assert Counter(p.domain for p in catalogue.products) == {
        "supermarket": 60,
        "retail": 30,
        "pharmacy": 30,
    }
    assert all(p.provenance == "simulated" for p in catalogue.products)
    assert {p.category for p in catalogue.products if p.domain == "pharmacy"} == {"hygiene"}
    assert catalogue.digest() == load_catalogue(Path("data/expanded-catalogue.json")).digest()


def test_city_size_rejects_unsupported_grid() -> None:
    with pytest.raises(ValueError, match="10 or 32"):
        fake_city(size=12)

from pathlib import Path

import pytest

from delivery.catalogue import import_bakiano_csv, load_catalogue
from delivery.city import fake_city


def test_fixture_identity_and_city_reproducibility() -> None:
    catalogue = load_catalogue(Path("data/lab-catalogue.json"))
    assert len(catalogue.products) == 5
    assert all(p.provenance == "simulated" for p in catalogue.products)
    assert catalogue.digest() == load_catalogue(Path("data/lab-catalogue.json")).digest()
    city = fake_city()
    assert city == fake_city()
    assert city["sha256"] != fake_city(43)["sha256"]
    assert [s["kind"] for s in city["stores"]].count("supermarket") == 3
    assert city["schema_version"] == 2
    assert (city["width"], city["height"], city["spacing_m"]) == (10, 10, 500)
    assert len(city["nodes"]) == 100
    assert len(city["edges"]) == 360
    nodes = {node["id"]: node for node in city["nodes"]}
    assert len(nodes) == 100
    assert {(n["x"], n["y"]) for n in nodes.values()} == {
        (x * 500, y * 500) for y in range(10) for x in range(10)
    }
    edge_pairs = {(edge["from"], edge["to"]) for edge in city["edges"]}
    assert len(edge_pairs) == 360
    for edge in city["edges"]:
        origin, target = nodes[edge["from"]], nodes[edge["to"]]
        assert abs(origin["x"] - target["x"]) + abs(origin["y"] - target["y"]) == 500
        assert (edge["to"], edge["from"]) in edge_pairs
        assert edge["distance_m"] == 500
        assert 50 <= edge["travel_seconds"] <= 90
    for start in nodes:
        reachable = {start}
        for _ in nodes:
            reachable |= {e["to"] for e in city["edges"] if e["from"] in reachable}
        assert reachable == set(nodes)
    assert [(s["id"], s["name"]) for s in city["stores"]] == [
        ("store-1", "North Market"),
        ("store-2", "Bridge Market"),
        ("store-3", "South Market"),
        ("store-4", "Home Goods"),
        ("store-5", "Electronics"),
    ]
    anchors = [a["node"] for a in city["stores"] + city["facilities"]]
    assert len(set(anchors)) == 9
    assert set(anchors) <= set(nodes)
    assert {f["kind"] for f in city["facilities"]} == {"depot", "supplier", "fuel", "charger"}



def test_bakiano_import_preserves_identity_and_unknowns(tmp_path: Path) -> None:
    path = tmp_path / "export.csv"
    path.write_text("code,name,price,timestamp,category\na,Milk,3.00,2026-10-23 10:00:00,\n")
    catalogue = import_bakiano_csv(path, "vendor")
    product = catalogue.products[0]
    assert product.listing_id == "a" and product.category is None
    assert product.provenance == "imported" and str(product.price) == "3.00"
    path.write_text("code,name,price,timestamp\na,Milk,-1,2026-10-23\n")
    with pytest.raises(ValueError):
        import_bakiano_csv(path, "vendor")

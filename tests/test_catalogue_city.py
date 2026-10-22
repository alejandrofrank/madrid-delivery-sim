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
    reachable = {0}
    for _ in city["nodes"]:
        reachable |= {e["to"] for e in city["edges"] if e["from"] in reachable}
    assert len(reachable) == len(city["nodes"])


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

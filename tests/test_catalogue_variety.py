from collections import Counter
from pathlib import Path

from delivery.catalogue import load_catalogue


def test_expanded_catalogue_has_distinct_simulated_variety() -> None:
    catalogue = load_catalogue(Path("data/expanded-catalogue.json"))
    counts = Counter(product.domain for product in catalogue.products)
    for domain, original_count in {"supermarket": 3, "retail": 2, "pharmacy": 2}.items():
        products = [product for product in catalogue.products if product.domain == domain]
        assert counts[domain] >= original_count * 15
        assert len({product.name.casefold() for product in products}) == len(products)
        assert len({product.listing_id for product in products}) == len(products)
    assert all(product.provenance == "simulated" for product in catalogue.products)
    assert all(product.url is None for product in catalogue.products)
    assert {p.category for p in catalogue.products if p.domain == "pharmacy"} == {"hygiene"}
    assert "no prescription products" in catalogue.origin


def test_expanded_catalogue_preserves_original_scenario_products() -> None:
    catalogue = load_catalogue(Path("data/expanded-catalogue.json"))
    assert [(p.listing_id, p.name) for p in catalogue.products[:7]] == [
        ("milk-1l", "Whole milk 1 L"),
        ("rice-1kg", "Rice 1 kg"),
        ("flour-1kg", "Corn flour 1 kg"),
        ("microwave", "Countertop microwave"),
        ("headphones", "Wired headphones"),
        ("cotton-pads", "Cotton hygiene pads"),
        ("plain-soap", "Plain hand soap"),
    ]

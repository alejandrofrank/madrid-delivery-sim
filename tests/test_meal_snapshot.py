import copy

import pytest
from pydantic import ValidationError

from delivery.meal_snapshot import (
    RECIPE_IDS,
    MealSnapshot,
    ingredient_shortages,
    load_meal_snapshot,
    snapshot_for_recipe,
)


def test_small_synthetic_snapshot_has_exactly_seven_meals_and_three_markets():
    snapshot = load_meal_snapshot()
    assert snapshot.synthetic is True
    assert {r.id for r in snapshot.recipes} == RECIPE_IDS
    assert {r.name for r in snapshot.recipes} == {
        "Pizza",
        "Kebab",
        "Hamburgers",
        "Steak frites",
        "Sushi",
        "Soups",
        "Salads",
    }
    assert len(snapshot.supermarkets) == 3
    assert len(snapshot.model_dump_json().encode()) <= 6000
    for recipe in snapshot.recipes:
        assert recipe.servings == 1
        assert all(i.quantity > 0 and i.unit in {"g", "ml", "piece"} for i in recipe.ingredients)
    assert all(
        isinstance(s.available, int) and s.available >= 0
        for market in snapshot.supermarkets
        for s in market.stock
    )


def test_recipe_selection_removes_all_unrelated_business_facts():
    snapshot = snapshot_for_recipe("sushi")
    assert [r.id for r in snapshot.recipes] == ["sushi"]
    allowed = {"salmon", "rice", "nori", "cucumber"}
    assert all({s.id for s in market.stock} == allowed for market in snapshot.supermarkets)
    assert len(snapshot.model_dump_json().encode()) < 1500
    with pytest.raises(ValueError, match="Unknown recipe"):
        snapshot_for_recipe("customer-private-order")


def test_known_stock_shortages_are_deterministic():
    assert ingredient_shortages("sushi", "market-a") == {}
    assert ingredient_shortages("sushi", "market-b") == {"salmon": 70}
    assert ingredient_shortages("pizza", "market-c") == {"mozzarella": 100}
    with pytest.raises(ValueError, match="Unknown supermarket"):
        ingredient_shortages("pizza", "real-vendor")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(customer="private"),
        lambda d: d["recipes"][0].update(price_eur=10),
        lambda d: d["recipes"][0].update(id="unbounded-menu"),
        lambda d: d["recipes"][0]["ingredients"][0].update(quantity=0),
        lambda d: d["recipes"][0]["ingredients"][0].update(quantity=True),
        lambda d: d["supermarkets"][0]["stock"][0].update(available=-1),
        lambda d: d["supermarkets"][0]["stock"][0].update(available=1.5),
        lambda d: d["supermarkets"][0]["stock"][0].update(unit="ml"),
        lambda d: d["supermarkets"][0]["stock"][0].update(product_url="private"),
    ],
)
def test_reject_extra_business_fields_invalid_quantities_and_unit_mismatch(mutation):
    data = copy.deepcopy(load_meal_snapshot().model_dump())
    mutation(data)
    with pytest.raises(ValidationError):
        MealSnapshot.model_validate(data)


def test_absent_stock_is_a_shortage(monkeypatch):
    snapshot = snapshot_for_recipe("sushi")
    snapshot.supermarkets[0].stock = [s for s in snapshot.supermarkets[0].stock if s.id != "salmon"]
    monkeypatch.setattr("delivery.meal_snapshot.snapshot_for_recipe", lambda _: snapshot)
    assert ingredient_shortages("sushi", "market-a") == {"salmon": 120}

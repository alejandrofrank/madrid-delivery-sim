from collections import Counter

import pytest
from pydantic import ValidationError

from delivery.store_layout import (
    StoreLayoutConfig,
    aisle_path,
    generate_layout,
    plan_pick,
    stock_to_shelves,
)

PRODUCTS = [
    {"sku": "milk", "name": "Milk", "cold": True},
    {"sku": "rice", "name": "Rice"},
    {"sku": "apple", "name": "Apples"},
]


def test_layout_is_config_generated_and_order_independent() -> None:
    layout = generate_layout(StoreLayoutConfig(), PRODUCTS)
    assert layout == generate_layout(StoreLayoutConfig(), list(reversed(PRODUCTS)))
    assert len(layout["slots"]) == 6
    assert all(s["zone"] == "cold" for s in layout["slots"] if s["sku"] == "milk")
    for slot in layout["slots"]:
        assert aisle_path(layout, layout["dock"]["node"], slot["access"])
        assert f"{slot['x']}:{slot['z']}" not in layout["nodes"]
    assert generate_layout(StoreLayoutConfig(bays=10), PRODUCTS)["depth"] > layout["depth"]


@pytest.mark.parametrize("quantities", [(0, 0, 0), (1, 3, 25), (250, 14, 32)])
def test_stock_mapping_conserves_exact_physical_units(quantities: tuple[int, ...]) -> None:
    layout = generate_layout(StoreLayoutConfig(), PRODUCTS)
    stock = dict(zip(sorted(p["sku"] for p in PRODUCTS), quantities, strict=True))
    mapped = stock_to_shelves(layout, stock)
    totals: Counter[str] = Counter()
    for shelf in mapped:
        totals[shelf["sku"]] += shelf["quantity"]
    assert dict(totals) == stock
    assert len({s["id"] for s in mapped}) == len(mapped)


def test_invalid_config_catalogue_and_stock_fail_closed() -> None:
    with pytest.raises(ValidationError):
        StoreLayoutConfig(aisles=0)
    with pytest.raises(ValueError, match="Unique"):
        generate_layout(StoreLayoutConfig(), PRODUCTS + PRODUCTS)
    with pytest.raises(ValueError, match="capacity"):
        generate_layout(
            StoreLayoutConfig(bays=2, levels=1),
            [{"sku": str(i), "name": str(i), "cold": True} for i in range(20)],
        )
    layout = generate_layout(StoreLayoutConfig(), PRODUCTS)
    with pytest.raises(ValueError, match="Stock"):
        stock_to_shelves(layout, {"rice": -1})


def test_picker_replans_from_observed_state_not_event_names() -> None:
    layout = generate_layout(StoreLayoutConfig(), PRODUCTS)
    shelves = [{"slot": s["id"], "sku": s["sku"], "quantity": 1} for s in layout["slots"]]
    start = layout["packing"]["node"]
    first = plan_pick(layout, start, {"rice": 1, "milk": 1}, shelves)
    assert first["action"] == "pick" and first["sku"] == "rice"
    blocked = frozenset([first["path"][-1]])
    second = plan_pick(layout, start, {"rice": 1}, shelves, blocked)
    assert second["action"] == "pick" and second["slot"] != first["slot"]
    assert not blocked.intersection(second["path"])
    for shelf in shelves:
        shelf["quantity"] = 0
    assert plan_pick(layout, start, {"rice": 1}, shelves)["action"] == "wait"


def test_no_route_through_obstacle_or_disconnected_target() -> None:
    layout = generate_layout(StoreLayoutConfig(), PRODUCTS)
    end = layout["dock"]["node"]
    assert aisle_path(layout, "missing", end) is None
    assert aisle_path(layout, layout["packing"]["node"], end, frozenset([end])) is None

"""Free, scoped delivery planning tests; no database or provider fixtures."""

from copy import deepcopy
from itertools import permutations
from typing import Any

import pytest

from delivery.workflow_policy import route_plan


def edge(
    source: int, target: int, seconds: int, *, modes: list[str] | None = None
) -> dict[str, Any]:
    return {
        "from": source,
        "to": target,
        "travel_seconds": seconds,
        "modes": ["bike"] if modes is None else modes,
    }


def courier(courier_id: str, node: int, **state: Any) -> dict[str, Any]:
    return {"id": courier_id, "node": node, "busy_basket": None, "status": "active", **state}


def context(fleet: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "roads": {"edges": [edge(1, 3, 50), edge(2, 3, 5), edge(3, 4, 10)]},
        "job": {"basket": "basket-1", "pickup_node": 3, "customer_node": 4},
        "fleet": fleet,
    }


def test_closer_courier_wins_even_with_larger_id() -> None:
    state = context([courier("bike-01", 1), courier("bike-99", 2)])

    assert route_plan(state) == ("bike-99", [2, 3, 4])


def test_directed_traffic_time_beats_geometric_proximity_and_shortcuts() -> None:
    state = {
        "roads": {
            "nodes": [
                {"id": 0, "x": 0, "y": 0},
                {"id": 1, "x": 1, "y": 0},
                {"id": 2, "x": 100, "y": 0},
            ],
            "edges": [
                edge(0, 1, 1),  # This fast road runs away from the pickup.
                edge(1, 3, 120),
                edge(3, 0, 120),
                edge(2, 0, 10),
                edge(0, 4, 20),
                edge(2, 4, 1),  # A delivery shortcut still must visit the pickup.
                edge(1, 0, 1, modes=["car"]),
            ],
        },
        "job": {"basket": "directed", "pickup_node": 0, "customer_node": 4},
        "fleet": [courier("near", 1), courier("far", 2)],
    }

    assert route_plan(state) == ("far", [2, 0, 4])


def test_equal_eta_ties_are_stable_per_basket_and_fleet_permutation() -> None:
    fleet = [courier("bike-01", 1), courier("bike-02", 1), courier("bike-10", 1)]
    winners = set()
    for basket in range(24):
        state = context(fleet)
        state["job"]["basket"] = f"basket-{basket}"
        expected = route_plan(state)
        winners.add(expected[0])
        for order in permutations(fleet):
            state["fleet"] = list(order)
            assert route_plan(state) == expected
        retry = deepcopy(state)
        retry["job"].update(attempt=2, status="deferred")
        assert route_plan(retry) == expected

    assert len(winners) > 1
    assert winners - {"bike-01"}


def test_inactive_busy_and_unreachable_couriers_are_excluded() -> None:
    state = context(
        [
            courier("inactive", 3, status="offline"),
            courier("busy", 3, busy_basket="another-basket"),
            courier("unreachable", 99),
            courier("available", 1),
        ]
    )

    assert route_plan(state) == ("available", [1, 3, 4])


def test_live_node_overrides_home_store_and_pickup_is_the_scoped_checkpoint() -> None:
    state = context(
        [
            courier("bike-01", 1, home_store="store-at-2"),
            courier("bike-99", 2, home_store="store-at-1"),
        ]
    )
    state["job"]["parcel_node"] = 3

    assert route_plan(state) == ("bike-99", [2, 3, 4])
    state["fleet"][1]["home_store"] = "another-home"
    assert route_plan(state) == ("bike-99", [2, 3, 4])


@pytest.mark.parametrize(
    "fleet",
    [
        [],
        [courier("offline", 1, status="offline")],
        [courier("busy", 1, busy_basket="other")],
        [courier("disconnected", 99)],
    ],
)
def test_no_candidate_raises(fleet: list[dict[str, Any]]) -> None:
    with pytest.raises(ValueError, match="No available courier"):
        route_plan(context(fleet))


def test_unreachable_customer_raises() -> None:
    state = context([courier("bike-1", 1)])
    state["job"]["customer_node"] = 99

    with pytest.raises(ValueError, match="No available courier"):
        route_plan(state)


def test_same_node_delivery_and_legacy_minimal_context_remain_valid() -> None:
    state = context([courier("bike-1", 3)])
    state["job"] = {"pickup_node": 3, "customer_node": 3}

    assert route_plan(state) == ("bike-1", [3])

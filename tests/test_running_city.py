from collections.abc import Iterator

import psycopg
import pytest
from pydantic import ValidationError

from delivery.agent_access import retire_inventory_access, role_access
from delivery.city_config import CitySettings, demand_schedule
from delivery.db import connect
from delivery.delivery_flow import flow_snapshot
from delivery.running_city import agent_inspection, new_city, release_orders, run_city


def test_config_and_demand_are_bounded_and_repeatable():
    config = CitySettings(duration_minutes=30, playback_seconds=0)
    stock = [{"store": s.id, "sku": "synthetic:item"} for s in config.stores]
    orders = demand_schedule(config, stock)
    assert len(orders) > 1 and orders == demand_schedule(config, stock)
    assert orders[0]["arrival_sim"] > 0
    assert len({o["arrival_sim"] for o in orders}) > 1
    assert all(o["arrival_sim"] < 1800 for o in orders)
    assert demand_schedule(config.model_copy(update={"orders_per_hour": 0}), stock) == []
    for invalid in (
        {"traffic_multiplier": 0},
        {"dropout_rate": 2},
        {"duration_minutes": 1000},
        {"orders_per_hour": float("nan")},
        {"stores": []},
        {"stores": [s.model_copy(update={"couriers": 3}) for s in config.stores]},
    ):
        with pytest.raises(ValidationError):
            CitySettings.model_validate({**config.model_dump(), **invalid})


@pytest.fixture
def city(db_url: str) -> Iterator[str]:
    config = CitySettings(
        duration_minutes=15,
        playback_seconds=0,
        orders_per_hour=12,
        dropout_rate=0,
        traffic_multiplier=1,
    )
    run = new_city(config, db_url)
    yield run
    retire_inventory_access(run, db_url)
    with connect(db_url) as conn:
        conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def test_orders_are_released_over_time_and_release_is_idempotent(db_url, city):
    state = flow_snapshot(city, db_url)
    schedule = state["order_schedule"]
    assert len(schedule) > 1 and state["tasks"] == []
    release_orders(city, schedule, 0, db_url)
    assert flow_snapshot(city, db_url)["tasks"] == []
    release_orders(city, schedule, schedule[0]["arrival_sim"], db_url)
    release_orders(city, schedule, schedule[0]["arrival_sim"], db_url)
    state = flow_snapshot(city, db_url)
    assert len(state["tasks"]) == 1
    assert len(state["events"]) == 1
    assert all(stock["on_hand"] == 3 for stock in state["stock"])
    assert len(state["fleet"]) == 3 and all(c["home_store"] for c in state["fleet"])


def test_running_city_uses_configured_traffic_and_keeps_history_frozen(db_url, city):
    result = run_city(city, db_url)
    assert result["run"]["status"] == "complete"
    assert len(result["baskets"]) == len(result["order_schedule"])
    assert len({e["due_sim"] for e in result["events"] if e["topic"] == "basket.requested"}) > 1
    assert all(result["invariants"].values())
    assert not any(i["kind"] == "courier_dropout" for i in result["incidents"])
    assert len(result["customers"]) == 128
    customers = {c["id"]: c for c in result["customers"]}
    for order in result["order_schedule"]:
        customer = customers[order["customer_id"]]
        assert order["customer_node"] == customer["home_node"]
        assert order["home_id"] == customer["home_id"]
        assert order["customer_name"] == customer["name"]
        assert order["product_name"] != order["sku"]
    assert result["agent_runtime"]["model_calls"] == 0
    edges = {(e["from"], e["to"]): e["travel_seconds"] for e in result["city"]["edges"]}
    for attempt in result["attempts"]:
        assert attempt["edge_durations"] == [
            edges[a, b] for a, b in zip(attempt["route"], attempt["route"][1:], strict=False)
        ]
    with pytest.raises(ValueError):
        run_city(city, db_url)


def test_human_inspection_selects_only_the_requested_agents_memory(db_url, city):
    accesses = role_access(city, "inventory", db_url)
    with connect(db_url) as conn:
        event = conn.execute(
            """INSERT INTO events(run_id,topic,producer,payload,dedupe_key,trace_id)
            VALUES (%s,'inventory.decided','inventory','{}','operator-memory-test','memory')
            RETURNING id""",
            (city,),
        ).fetchone()
        for store in ("store-1", "store-2"):
            conn.execute(
                "INSERT INTO agent_memories VALUES (%s,%s,'own',%s,0,3600,%s)",
                (city, store, '{"store":"' + store + '"}', event["id"]),
            )
    inspected = agent_inspection(city, "inventory:store-1", db_url)
    assert inspected and len(inspected["memory"]) == 1
    assert inspected["memory"][0]["body"] == {"store": "store-1"}
    assert "login_role" not in inspected["agent"]
    assert agent_inspection(city, "inventory:missing", db_url) is None
    with connect(accesses["store-1"].dsn) as conn:
        assert all(
            row["store"] == "store-1"
            for row in conn.execute("SELECT * FROM agent_memories").fetchall()
        )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT * FROM lab_city_configs")


def test_fractional_traffic_is_recomputed_from_frozen_configuration(db_url, city):
    with connect(db_url) as conn:
        conn.execute(
            """UPDATE lab_city_configs SET config=jsonb_set(config,'{traffic_multiplier}','1.5')
            WHERE run_id=%s""",
            (city,),
        )
        row = conn.execute(
            "SELECT fleet_route_metrics(%s,'[100,99]',100,100,99) AS data", (city,)
        ).fetchone()
        world = conn.execute("SELECT city FROM lab_worlds WHERE run_id=%s", (city,)).fetchone()
    import math

    base = next(
        e["travel_seconds"] for e in world["city"]["edges"] if e["from"] == 100 and e["to"] == 99
    )
    assert row["data"]["durations"] == [math.ceil(base * 1.5)]
    assert row["data"]["delay"] == math.ceil(base * 1.5) - base

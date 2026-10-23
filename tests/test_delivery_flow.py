from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from pydantic import ValidationError

from delivery.agent_access import retire_inventory_access, role_access
from delivery.agent_runtime import create_agent
from delivery.agent_specs import load_role
from delivery.db import connect
from delivery.delivery_flow import (
    delivery_agents,
    flow_snapshot,
    prepare_delivery,
    run_delivery,
    world_tick,
)
from delivery.lab import create_lab
from delivery.queue import Queue
from delivery.workflow_policy import route_plan

pytestmark = pytest.mark.integration


@pytest.fixture
def flow(db_url: str) -> Iterator[str]:
    run = create_lab(db_url)
    yield run
    retire_inventory_access(run, db_url)
    with connect(db_url) as conn:
        conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def test_basket_reservation_to_delivery(db_url: str, flow: str) -> None:
    result = run_delivery(flow, db_url)
    assert result["run"]["status"] == "complete"
    with pytest.raises(ValueError):
        run_delivery(flow, db_url)
    assert flow_snapshot(flow, db_url)["run"]["status"] == "complete"
    assert result["baskets"][0]["status"] == "delivered"
    job = result["jobs"][0]
    assert job["status"] == "delivered" and job["courier"] == "bike-1"
    assert job["route"][0] == 22 and job["route"][-1] == 88 and 2 in job["route"]
    assert result["run"]["sim_time"] == job["arrive_sim"] == job["travel_seconds"]
    assert result["fleet"] == [
        {"id": "bike-1", "node": 88, "busy_basket": None, "status": "active", "home_store": None}
    ]
    assert all(result["invariants"].values())
    assert len(result["agents"]) == 11
    assert all(e["state"] == "done" for e in result["events"])
    by_topic = {e["topic"]: e for e in result["events"]}
    chain = [
        "basket.requested",
        "basket.reserved",
        "basket.ready",
        "delivery.assigned",
        "delivery.arrived",
        "delivery.completed",
    ]
    for parent, child in zip(chain, chain[1:], strict=False):
        assert by_topic[child]["parent_id"] == by_topic[parent]["id"]
        assert by_topic[child]["trace_id"] == "basket-delivery"
    stock = next(
        s
        for s in result["stock"]
        if s["store"] == "store-1" and s["sku"] == result["selected_product"]
    )
    assert stock["on_hand"] == stock["reserved"] == 0
    assert sum(m["kind"] == "picked" for m in result["movements"]) == 1
    assert {s["jobs"][0]["status"] for s in result["checkpoints"] if s["jobs"]} >= {
        "ready",
        "assigned",
        "in_transit",
        "arrived",
        "delivered",
    }


def test_actual_role_connections_deny_other_domains(db_url: str, flow: str) -> None:
    prepare_delivery(flow, db_url)
    inv = role_access(flow, "inventory", db_url)["store-1"]
    fulfill = role_access(flow, "fulfillment", db_url)
    dispatch = role_access(flow, "dispatcher", db_url)["fleet"]
    inventory = create_agent(inv.dsn)
    assert inventory.process(inventory.claim())
    first = create_agent(fulfill["store-1"].dsn)
    assert first.process(first.claim())
    for access in (fulfill["store-1"], dispatch):
        with connect(access.dsn) as conn:
            for table in (
                "lab_stock",
                "lab_baskets",
                "lab_shipments",
                "lab_movements",
                "lab_fulfillments",
                "lab_delivery_jobs",
                "lab_fleet",
                "lab_worlds",
                "agent_bindings",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(f"SELECT * FROM {table}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute("SET ROLE lab_inventory_executor")
            assert all(
                row["store"] == access.store
                for row in conn.execute("SELECT * FROM agent_memories").fetchall()
            )
    with connect(dispatch.dsn) as conn:
        context = conn.execute("SELECT workflow_context('basket-delivery') AS data").fetchone()[
            "data"
        ]
        assert not any(key in str(context) for key in ("sku", "quantity", "price", "catalogue"))
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT fulfillment_pick('basket-delivery')")
    with connect(fulfill["store-1"].dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT dispatch_complete('basket-delivery')")
    with connect(fulfill["store-2"].dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT workflow_context('basket-delivery')")
        assert conn.execute("SELECT * FROM events").fetchall() == []
        assert conn.execute("SELECT * FROM agent_memories").fetchall() == []


def test_expired_reservation_cannot_be_picked(db_url: str, flow: str) -> None:
    prepare_delivery(flow, db_url)
    agents = delivery_agents(flow, db_url)
    event = agents[0].claim()
    assert event and agents[0].process(event)
    world_tick(flow, 600, db_url)
    agent = next(a for a in agents if a.scope.agent_id == "fulfillment:store-1")
    event = agent.claim()
    assert event and not agent.process(event)
    state = flow_snapshot(flow, db_url)
    assert not state["jobs"]
    assert state["baskets"][0]["status"] == "reserved"
    assert not any(m["kind"] == "picked" for m in state["movements"])


def test_dispatch_cannot_invent_arrival_or_disconnected_route(db_url: str, flow: str) -> None:
    prepare_delivery(flow, db_url)
    agents = delivery_agents(flow, db_url)
    for name in ("inventory:store-1", "fulfillment:store-1"):
        agent = next(a for a in agents if a.scope.agent_id == name)
        event = agent.claim()
        assert event and agent.process(event)
    dispatcher = next(a for a in agents if a.role.name == "dispatcher")
    with connect(dispatcher.dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
            conn.execute("SELECT dispatch_complete('basket-delivery')")
        with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
            conn.execute("SELECT dispatch_assign('basket-delivery','bike-1','[22,2,88]')")
    assert flow_snapshot(flow, db_url)["jobs"][0]["status"] == "ready"


def test_fulfillment_effects_and_handoff_roll_back_together(db_url: str, flow: str) -> None:
    prepare_delivery(flow, db_url)
    agents = delivery_agents(flow, db_url)
    inventory = agents[0]
    event = inventory.claim()
    assert event and inventory.process(event)
    agent = next(a for a in agents if a.scope.agent_id == "fulfillment:store-1")
    event = agent.claim()
    assert event and agent.reserve_budget(event)

    def failing(conn, message):
        agent.handle(conn, message)
        raise RuntimeError("crash after pick and outgoing message")

    assert not Queue(agent.dsn).process(event, failing)
    state = flow_snapshot(flow, db_url)
    assert not state["jobs"]
    assert not any(e["topic"] == "basket.ready" for e in state["events"])
    assert state["baskets"][0]["status"] == "reserved"
    with connect(db_url) as conn:
        conn.execute("UPDATE events SET available_at=now() WHERE id=%s", (event.id,))
    recovered = agent.claim()
    assert recovered and recovered.attempts == 2 and agent.process(recovered)
    with connect(agent.dsn) as conn:
        # A repeated pick has no second stock movement/job.
        conn.execute("SELECT fulfillment_pick('basket-delivery')")
    state = flow_snapshot(flow, db_url)
    assert len(state["jobs"]) == 1
    assert sum(m["kind"] == "picked" for m in state["movements"]) == 1


def test_new_roles_cannot_self_grant_inventory_tools() -> None:
    for name in ("fulfillment", "dispatcher"):
        role = load_role(name)
        with pytest.raises(ValidationError):
            type(role).model_validate({**role.model_dump(), "tools": ["inventory.read"]})


def test_dispatch_claims_one_courier_atomically(db_url: str, flow: str) -> None:
    prepare_delivery(flow, db_url)
    agents = delivery_agents(flow, db_url)
    for name in ("inventory:store-1", "fulfillment:store-1"):
        agent = next(a for a in agents if a.scope.agent_id == name)
        event = agent.claim()
        assert event and agent.process(event)
    dispatcher = next(a for a in agents if a.role.name == "dispatcher")
    with connect(dispatcher.dsn) as conn:
        context = conn.execute("SELECT workflow_context('basket-delivery') AS data").fetchone()
        assert context
        courier, route = route_plan(context["data"])
    with connect(db_url) as conn:
        conn.execute(
            """INSERT INTO lab_delivery_jobs(run_id,basket,store,pickup_node,customer_node)
            VALUES (%s,'other-basket','store-1',2,88)""",
            (flow,),
        )

    def assign(basket):
        from psycopg.types.json import Jsonb

        try:
            with connect(dispatcher.dsn) as conn:
                conn.execute("SELECT dispatch_assign(%s,%s,%s)", (basket, courier, Jsonb(route)))
            return True
        except psycopg.errors.RaiseException:
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(assign, ["basket-delivery", "other-basket"])) == [False, True]
    assert sum(j["status"] == "assigned" for j in flow_snapshot(flow, db_url)["jobs"]) == 1


def test_outbound_scope_and_role_forgery_denied(db_url: str, flow: str) -> None:
    prepare_delivery(flow, db_url)
    delivery_agents(flow, db_url)
    access = role_access(flow, "fulfillment", db_url)["store-1"]
    with connect(access.dsn) as conn:
        for producer, topic, target in (
            ("inventory", "inventory.decided", "store-1"),
            ("fulfillment", "basket.ready", "fulfillment:store-2"),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(
                    """INSERT INTO events(run_id,producer,topic,payload,dedupe_key,
                    trace_id,target_store) VALUES (%s,%s,%s,'{}',%s,'forged',%s)""",
                    (flow, producer, topic, topic, target),
                )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("UPDATE agent_budgets SET tools_limit=2000")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT agent_catalogue()")


def test_route_planner_skips_unreachable_couriers_and_allows_same_node() -> None:
    context = {
        "roads": {"edges": [{"from": 1, "to": 2, "modes": ["bike"], "travel_seconds": 60}]},
        "job": {"pickup_node": 1, "customer_node": 2},
        "fleet": [
            {"id": "unreachable", "node": 99, "busy_basket": None},
            {"id": "reachable", "node": 1, "busy_basket": None},
        ],
    }
    assert route_plan(context) == ("reachable", [1, 2])
    context["job"]["customer_node"] = 1
    assert route_plan(context) == ("reachable", [1])

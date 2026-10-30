import asyncio
import math

import httpx
import pytest
from fastapi import FastAPI
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from delivery.agent_transport import A2ATransport
from delivery.chaos import (
    ChaosConfig,
    Disruption,
    evidence,
    insert_event,
    pause_route,
    retime,
    schedule,
    trigger,
)
from delivery.chaos_agents import OfflineRecoveryModel, RecoveryTurn
from delivery.db import connect
from delivery.protocol_api import agent_directory
from delivery.queue import publish
from delivery.simulation import Simulation, finish_run
from delivery.world import World, position, seed_locations


def facts(**changes):
    return {
        "order_id": "order",
        "status": "assigned",
        "courier_status": "offline",
        "sim": 120,
        "duration": 3600,
        "due_sim": 900,
        "ready_sim": 300,
        "earliest_ready": 300,
        "eta_sim": None,
        **changes,
    }


def test_seeded_random_scenarios_are_reproducible_and_bounded():
    config = ChaosConfig(random_events=20)
    assert schedule(config, 42, 7200) == schedule(config, 42, 7200)
    assert schedule(config, 42, 7200) != schedule(config, 43, 7200)
    with pytest.raises(ValidationError):
        Disruption(id="strike", kind="metro_strike")
    with pytest.raises(ValueError):
        schedule(
            ChaosConfig(events=[Disruption(id="long", kind="heavy_rain", duration=3600)]), 42, 1800
        )


@pytest.mark.parametrize(
    "role,values,expected",
    [
        ("dispatcher", {}, "reassign_order"),
        ("dispatcher", {"courier_status": "delivering"}, "keep_assignment"),
        ("restaurant-kitchen", {"earliest_ready": 600}, "update_prep_time"),
        ("restaurant-kitchen", {"earliest_ready": 2400}, "reject_order"),
        ("customer_service", {"eta_sim": 600}, "contact_customer"),
        ("customer_service", {"sim": 1200}, "refund_customer"),
    ],
)
def test_adk_recovery_uses_role_tools(role, values, expected):
    turn = RecoveryTurn(role, facts(**values))
    plan = asyncio.run(turn.run(OfflineRecoveryModel()))
    assert plan["action"] == expected
    assert turn.calls[0]["name"] == "read_context"
    assert len(turn.calls) == 2


def test_retiming_preserves_observed_position_and_restores_speed():
    route = {"points": [[0, 0, 0], [10, 10, 100]], "pickup_at": 20, "end_at": 100}
    slower = retime(route, 30, 2)
    assert position(slower, 30) == position(route, 30)
    assert slower["end_at"] == 170
    assert retime(slower, 30, 2) == slower
    restored = retime(slower, 50, 1)
    assert position(restored, 50) == position(slower, 50)
    assert restored["end_at"] == 110
    paused = pause_route(route, 30, 60)
    assert position(paused, 75) == position(route, 30)
    assert paused["end_at"] == 160


def setup_order(db_url, run_id):
    world = World()
    with connect(db_url) as conn:
        seed_locations(conn, world)
        conn.execute(
            "UPDATE runs SET chaos_config=%s,status='running',duration=3600 WHERE id=%s",
            (Jsonb(ChaosConfig().model_dump()), run_id),
        )
        store = conn.execute(
            "SELECT * FROM locations WHERE kind='store' AND district='Retiro' ORDER BY id LIMIT 1"
        ).fetchone()
        customer = conn.execute(
            "SELECT * FROM locations WHERE kind='customer' AND district='Retiro' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        for name in ("courier-a", "courier-b"):
            conn.execute(
                "INSERT INTO couriers(run_id,id,hub,mode,node,point) "
                "VALUES (%s,%s,'retiro','bike',%s,%s)",
                (run_id, name, store["node"], store["point"]),
            )
        conn.execute(
            "INSERT INTO orders(run_id,id,store,customer,created_sim,ready_sim,due_sim) "
            "VALUES (%s,'chaos-order',%s,%s,0,300,900)",
            (run_id, store["id"], customer["id"]),
        )
        publish(
            conn,
            run_id=run_id,
            producer="generator",
            topic="order.created",
            payload={"order_id": "chaos-order"},
            key="chaos-order",
            trace_id="chaos-order",
        )
    return world, store["id"]


@pytest.mark.integration
@pytest.mark.parametrize(
    "kind", ["heavy_rain", "metro_strike", "restaurant_outage", "courier_offline"]
)
def test_end_to_end_disruption_over_a2a(db_url, run_id, kind):
    world, store = setup_order(db_url, run_id)
    app = FastAPI()
    app.mount("/a2a", agent_directory(db_url))
    transport = A2ATransport("http://localhost:8010", http_transport=httpx.ASGITransport(app=app))
    simulation = Simulation(world, db_url, transport=transport)
    simulation.drain(str(run_id), 0)
    with connect(db_url) as conn:
        order = conn.execute(
            "SELECT courier,route FROM orders WHERE run_id=%s AND id='chaos-order'", (run_id,)
        ).fetchone()
        event = Disruption(
            id="event",
            kind=kind,
            at=math.ceil(order["route"]["pickup_at"] / 60) * 60 + 60
            if kind == "courier_offline"
            else 60,
            duration=120,
            district="retiro",
            target=order["courier"]
            if kind == "courier_offline"
            else store
            if kind == "restaurant_outage"
            else None,
        )
        insert_event(conn, str(run_id), event)
    for sim in range(60, 3601, 60):
        if kind == "courier_offline" and sim == event.at:
            with connect(db_url) as conn:
                assert (
                    conn.execute(
                        "SELECT status FROM orders WHERE run_id=%s AND id='chaos-order'", (run_id,)
                    ).fetchone()["status"]
                    == "picked_up"
                )
        simulation.step(str(run_id), sim, 42, 0)  # one fixture order; no ambient demand
    finish_run(str(run_id), db_url)
    with connect(db_url) as conn:
        result = evidence(conn, str(run_id))
    assert result["metrics"][0]["affected_orders"] == 1
    assert result["metrics"][0]["failed_replans"] == 0, result["replans"]
    assert result["metrics"][0]["orders_saved"] == 1
    assert result["metrics"][0]["orders_lost"] == 0
    assert result["metrics"][0]["time_to_recover_seconds"] is not None
    assert len(result["contacts"]) == 1
    assert result["metrics"][0]["extra_token_cost_usd"] == 0
    if kind == "courier_offline":
        assert any(w["result"]["plan"]["action"] == "reassign_order" for w in result["replans"])
        with connect(db_url) as conn:
            assert (
                conn.execute(
                    "SELECT recovery_node FROM orders WHERE run_id=%s AND id='chaos-order'",
                    (run_id,),
                ).fetchone()["recovery_node"]
                is not None
            )


def test_recovery_tools_enforce_scope_and_evidenced_eta():
    turn = RecoveryTurn("customer_service", facts())
    with pytest.raises(PermissionError):
        turn.contact_customer(True, False)
    turn.read = True
    with pytest.raises(PermissionError):
        turn.reassign_order("unavailable")
    with pytest.raises(ValueError, match="ETA"):
        turn.contact_customer(True, True)
    with pytest.raises(ValueError, match="refund"):
        turn.refund_customer(float("nan"))


@pytest.mark.integration
def test_trigger_idempotency_and_closed_run_guard(db_url, run_id):
    setup_order(db_url, run_id)
    event = Disruption(id="manual", kind="heavy_rain", at=60, duration=120)
    trigger(str(run_id), event, db_url)
    trigger(str(run_id), event, db_url)
    with pytest.raises(ValueError, match="different payload"):
        trigger(str(run_id), event.model_copy(update={"severity": 3}), db_url)
    with connect(db_url) as conn:
        conn.execute("UPDATE runs SET sim_time=120 WHERE id=%s", (run_id,))
    trigger(str(run_id), event, db_url)  # identical retry after the start time
    immediate = Disruption(id="now", kind="heavy_rain", duration=120)
    trigger(str(run_id), immediate, db_url)
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT start_sim FROM chaos_events WHERE run_id=%s AND id='now'", (run_id,)
            ).fetchone()["start_sim"]
            == 180
        )
        conn.execute("UPDATE runs SET status='complete' WHERE id=%s", (run_id,))
    with pytest.raises(ValueError, match="open Chaos"):
        trigger(str(run_id), event, db_url)

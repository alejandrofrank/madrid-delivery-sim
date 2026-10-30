"""Fleet ownership, scoped dispatch, recorded communications and repeatable rosters."""

from collections import Counter
from uuid import UUID

import pytest
from psycopg.types.json import Jsonb

from delivery.agents import Courier, Dispatcher
from delivery.contractors import communication, fleet_contract, fleet_plan
from delivery.db import connect
from delivery.dispatch_policy import DispatchPolicy
from delivery.dispatch_reposition import relocation_choice
from delivery.queue import Queue, publish
from delivery.simulation import create_run, snapshot
from delivery.world import World, seed_locations


@pytest.fixture(scope="module")
def world():
    return World()


def setup_order(db_url, run_id, world, fleet_ids, district="Chamberí"):
    with connect(db_url) as conn:
        seed_locations(conn, world)
        conn.execute(
            "UPDATE runs SET fleet_config=%s,dispatch_config=%s WHERE id=%s",
            (Jsonb(fleet_plan()), Jsonb(DispatchPolicy(reposition="stay").model_dump()), run_id),
        )
        store = conn.execute(
            "SELECT * FROM locations WHERE kind='store' AND district=%s ORDER BY id LIMIT 1",
            (district,),
        ).fetchone()
        customer = conn.execute(
            "SELECT * FROM locations WHERE kind='customer' AND district=%s ORDER BY id LIMIT 1",
            (district,),
        ).fetchone()
        for fleet_id in fleet_ids:
            conn.execute(
                "INSERT INTO couriers(run_id,id,hub,mode,node,point,fleet_id) "
                "VALUES (%s,%s,'chamberi','bike',%s,%s,%s)",
                (run_id, fleet_id + "-rider", store["node"], store["point"], fleet_id),
            )
        conn.execute(
            "INSERT INTO orders(run_id,id,store,customer,created_sim,ready_sim,due_sim) "
            "VALUES (%s,'fleet-order',%s,%s,0,60,7200)",
            (run_id, store["id"], customer["id"]),
        )
        publish(
            conn,
            run_id=run_id,
            producer="generator",
            topic="order.created",
            payload={"order_id": "fleet-order"},
            key="fleet-order",
            trace_id="fleet-order",
        )
    queue = Queue(db_url)
    event = queue.claim("dispatcher", run_id, 0)
    assert event
    queue.process(event, Dispatcher(world).handle)
    return queue


@pytest.mark.parametrize(
    "fleet_id,prefix", [("regular", "Route accepted"), ("sol", "Got it."), ("castellana", "Copy.")]
)
def test_fleet_order_acknowledgement_and_delivery(db_url, run_id, world, fleet_id, prefix):
    queue = setup_order(db_url, run_id, world, [fleet_id])
    event = queue.claim("courier", run_id, 0)
    assert event and event.payload["fleet_id"] == fleet_id
    queue.process(event, Courier().handle)
    with connect(db_url) as conn:
        # A repeated delivery of the same offer cannot create a second acceptance.
        Courier().handle(conn, event)
        messages = conn.execute(
            "SELECT payload->'message' AS message FROM events "
            "WHERE run_id=%s AND topic='courier.accepted'",
            (run_id,),
        ).fetchall()
        assert len(messages) == 1
        message = messages[0]["message"]
        assert message["fleet_id"] == fleet_id
        assert message["sender"] == fleet_id + "-rider"
        assert message["text"].startswith(prefix)
        assert message["eta_sim"] > 60
        assert message["status"] == "accepted_route"
        Courier().advance(conn, str(run_id), 8000)
        delivered = conn.execute(
            "SELECT detail->'message' AS message FROM decisions "
            "WHERE run_id=%s AND action='delivered'",
            (run_id,),
        ).fetchone()["message"]
        assert delivered["fleet_id"] == fleet_id
        assert delivered["status"] == "delivered"
    ack = queue.claim("dispatcher", run_id, 0)
    assert ack and ack.topic == "courier.accepted"
    queue.process(ack, Dispatcher(world).handle)
    state = snapshot(str(run_id), db_url)
    assert state["metrics"]["delivered"] == 1
    assert state["fleets"][0]["completed_jobs"] == 1
    assert state["fleets"][0]["operating_cost_eur"] > 0


def test_local_contractor_cannot_take_another_district_order(db_url, run_id, world):
    setup_order(db_url, run_id, world, ["sol", "castellana"], "Retiro")
    with connect(db_url) as conn:
        order = conn.execute("SELECT courier FROM orders WHERE run_id=%s", (run_id,)).fetchone()
        assert order["courier"] == "castellana-rider"
        assert (
            conn.execute(
                "SELECT status FROM couriers WHERE run_id=%s AND fleet_id='sol'",
                (run_id,),
            ).fetchone()["status"]
            == "idle"
        )


def test_local_contractor_never_repositions_outside_its_service_area():
    class NoRouting:
        def path(self, *args):
            raise AssertionError("An ineligible destination must not be routed")

    courier = {
        "id": "sol-rider",
        "node": 1,
        "mode": "bike",
        "last_reposition_sim": -900,
        "service_district": "Chamberí",
    }
    demand = [{"store": "ret", "node": 2, "orders": 10, "district": "Retiro"}]
    assert (
        relocation_choice(NoRouting(), courier, [courier], demand, 0, 7200, DispatchPolicy())
        is None
    )


def test_repeated_seeds_preserve_sites_and_independent_rosters(db_url, world):
    runs = []
    try:
        for _ in range(2):
            runs.append(create_run(world, seed=73, wall_seconds=0, url=db_url))
        snapshots = [snapshot(run, db_url) for run in runs]
        assert snapshots[0]["couriers"] == snapshots[1]["couriers"]
        assert Counter(c["fleet_id"] for c in snapshots[0]["couriers"]) == {
            "regular": 24,
            "sol": 9,
            "castellana": 9,
        }
        assert len({c["id"] for c in snapshots[0]["couriers"]}) == 42
        with connect(db_url) as conn:
            assert (
                conn.execute("SELECT count(*) AS n FROM locations WHERE kind='store'").fetchone()[
                    "n"
                ]
                == 48
            )
            assert (
                conn.execute(
                    "SELECT count(*) AS n FROM locations WHERE kind='customer'"
                ).fetchone()["n"]
                == 270
            )
            for run in runs:
                assert (
                    conn.execute(
                        "SELECT fleet_config FROM runs WHERE id=%s", (UUID(run),)
                    ).fetchone()["fleet_config"]
                    == fleet_plan()
                )
    finally:
        with connect(db_url) as conn:
            for run in runs:
                conn.execute("DELETE FROM couriers WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def test_style_changes_only_presentation_and_keeps_untrusted_order_text_as_data():
    messages = [
        communication(fleet, "courier", "accepted_route", order="<script>", eta_sim=123)
        for fleet in fleet_plan()["fleets"]
    ]
    assert len({m["text"] for m in messages}) == 3
    assert {m["eta_sim"] for m in messages} == {123}
    assert {m["status"] for m in messages} == {"accepted_route"}
    assert fleet_contract(None, "regular")["coverage"] == "network"

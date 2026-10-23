from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from delivery.agent_access import retire_inventory_access, role_access
from delivery.agent_runtime import create_agent
from delivery.db import connect
from delivery.delivery_flow import flow_snapshot, new_delivery, run_delivery
from delivery.fleet_flow import advance_fleet, prepare_fleet
from delivery.queue import publish

pytestmark = pytest.mark.integration


@pytest.fixture
def fleet(db_url: str) -> Iterator[str]:
    run = new_delivery(url=db_url)
    yield run
    retire_inventory_access(run, db_url)
    with connect(db_url) as conn:
        conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def test_multi_basket_traffic_dropouts_and_judged_recovery(db_url: str, fleet: str) -> None:
    result = run_delivery(fleet, db_url)
    assert result["run"]["status"] == "complete"
    assert all(result["invariants"].values())
    assert len(result["city"]["nodes"]) == 1024 and len(result["city"]["stores"]) == 12
    assert len(result["jobs"]) == 6
    jobs = {j["basket"]: j for j in result["jobs"]}
    assert sum(j["status"] == "delivered" for j in jobs.values()) == 5, result["reviews"]
    assert jobs["delivery-b"]["status"] == "abandoned"
    assert jobs["delivery-a"]["attempt"] == 2
    assert next(b for b in result["baskets"] if b["id"] == "scarcity-loser")["status"] == "rejected"
    assert {r["verdict"] for r in result["reviews"]} == {"approved", "denied"}
    assert sum(i["kind"] == "courier_dropout" for i in result["incidents"]) == 2
    assert any(i["kind"] == "traffic_delay" for i in result["incidents"])
    assert all(
        a["arrive_sim"] - a["depart_sim"] == sum(a["edge_durations"]) for a in result["attempts"]
    )
    brief = next(
        b["body"] for b in result["briefs"] if b["basket"] == "delivery-a" and b["attempt"] == 2
    )
    incident = next(
        i
        for i in result["incidents"]
        if i["basket"] == "delivery-a" and i["kind"] == "courier_dropout"
    )
    assert brief["custody_checkpoint"]["node"] == incident["detail"]["checkpoint"]
    assert brief["source_events"] and brief["judge"]["verdict"] == "approved"
    assert brief["prior_courier"] == "bike-1"
    assert not any(word in str(brief) for word in ("sku", "price", "soul", "password"))
    assert all(e["state"] == "done" for e in result["events"])
    assert len({a["courier"] for a in result["attempts"]}) == 4
    assert sum(m["kind"] == "picked" for m in result["movements"]) == 6
    assert not any(
        t["basket"] == "delivery-b" and t["label"] == "courier_arrival" for t in result["timeline"]
    )
    assert sum(i["kind"] == "courier_arrival" for i in result["incidents"]) == 5
    for checkpoint in result["checkpoints"]:
        active = [
            j["courier"]
            for j in checkpoint["jobs"]
            if j["status"] in {"assigned", "in_transit", "arrived"}
        ]
        assert len(active) == len(set(active))


def test_courier_and_judge_logins_have_no_raw_state_or_cross_role_tools(
    db_url: str, fleet: str
) -> None:
    prepare_fleet(fleet, db_url)
    courier = role_access(fleet, "courier", db_url)["bike-1"]
    judge = role_access(fleet, "judge", db_url)["fleet"]
    for access in (courier, judge):
        with connect(access.dsn) as conn:
            for table in (
                "lab_stock",
                "lab_baskets",
                "lab_briefs",
                "lab_retry_reviews",
                "lab_delivery_jobs",
                "lab_delivery_attempts",
                "lab_incidents",
                "lab_worlds",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(f"SELECT * FROM {table}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute("SET ROLE lab_dispatch_executor")
            assert conn.execute("SELECT * FROM agent_memories").fetchall() == []
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute("SELECT dispatch_assign('delivery-a','bike-1','[1,2]')")
    with connect(courier.dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT judge_context('delivery-a',1)")
    with connect(judge.dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT courier_context('delivery-a',1)")


def test_courier_cannot_accept_another_couriers_briefing(db_url: str, fleet: str) -> None:
    prepare_fleet(fleet, db_url)
    # Process only inventory/fulfillment/dispatcher steps for a single basket.
    for name, key in (
        ("inventory", "store-1"),
        ("fulfillment", "store-1"),
        ("dispatcher", "fleet"),
    ):
        access = role_access(fleet, name, db_url)[key]
        agent = create_agent(access.dsn)
        event = agent.claim()
        assert event and agent.process(event)
    couriers = role_access(fleet, "courier", db_url)
    with connect(couriers["bike-2"].dsn) as conn:
        assert conn.execute("SELECT * FROM events").fetchall() == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT courier_context('delivery-a',1)")
        with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
            conn.execute("SELECT courier_accept('delivery-a',1)")
    # Motion waits for acknowledgement and never creates arrival from an unaccepted job.
    before = flow_snapshot(fleet, db_url)
    advance_fleet(fleet, 60, db_url)
    assert flow_snapshot(fleet, db_url)["fleet"] == before["fleet"]
    own = create_agent(couriers["bike-1"].dsn)
    event = own.claim()
    assert event and own.process(event)
    acknowledged = flow_snapshot(fleet, db_url)["jobs"][0]
    assert acknowledged["depart_sim"] == 60
    advance_fleet(fleet, 60, db_url)
    assert flow_snapshot(fleet, db_url)["fleet"] == before["fleet"]


def test_reassignment_requires_judgement_and_private_legacy_commands_are_denied(
    db_url: str, fleet: str
) -> None:
    prepare_fleet(fleet, db_url)
    for name, key in (
        ("inventory", "store-1"),
        ("fulfillment", "store-1"),
        ("dispatcher", "fleet"),
        ("courier", "bike-1"),
    ):
        agent = create_agent(role_access(fleet, name, db_url)[key].dsn)
        event = agent.claim()
        assert event and agent.process(event)
    advance_fleet(fleet, 180, db_url)
    dispatcher = role_access(fleet, "dispatcher", db_url)["fleet"]
    with connect(dispatcher.dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException), conn.transaction():
            conn.execute("SELECT dispatch_recover('delivery-a',1)")
        for query in (
            "SELECT judge_review('delivery-a',1,NULL,NULL)",
            "SELECT dispatch_assign_legacy('delivery-a','bike-4','[99,131]')",
            "SELECT dispatch_complete_legacy('delivery-a')",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(query)
    assert flow_snapshot(fleet, db_url)["jobs"][0]["status"] == "awaiting_review"


def test_two_dispatch_workers_compete_for_one_online_courier(db_url: str, fleet: str) -> None:
    prepare_fleet(fleet, db_url)
    access = role_access(fleet, "dispatcher", db_url)["fleet"]
    with connect(db_url) as conn:
        conn.execute(
            "UPDATE lab_fleet SET status='offline' WHERE run_id=%s AND id<>'bike-1'", (fleet,)
        )
        for basket in ("race-a", "race-b"):
            conn.execute(
                """INSERT INTO lab_delivery_jobs(run_id,basket,store,pickup_node,customer_node)
                VALUES (%s,%s,'store-1',99,100)""",
                (fleet, basket),
            )
            publish(
                conn,
                run_id=fleet,
                producer="fulfillment",
                topic="basket.ready",
                payload={"basket": basket},
                key=basket,
                trace_id=basket,
                target_store="dispatcher:fleet",
            )
    workers = [create_agent(access.dsn), create_agent(access.dsn)]
    events = [worker.claim() for worker in workers]
    assert all(events) and events[0].id != events[1].id
    with ThreadPoolExecutor(2) as pool:
        results = list(
            pool.map(lambda pair: pair[0].process(pair[1]), zip(workers, events, strict=True))
        )
    assert results == [True, True]
    state = flow_snapshot(fleet, db_url)
    assert sorted(j["status"] for j in state["jobs"]) == ["assigned", "deferred"]
    assert sum(c["busy_basket"] is not None for c in state["fleet"]) == 1

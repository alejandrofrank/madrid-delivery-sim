from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from delivery.agent_access import retire_inventory_access
from delivery.api import app
from delivery.config import settings
from delivery.db import connect
from delivery.lab import crash_worker, create_lab, drain, lab_snapshot, prepare_slice, run_slice
from delivery.queue import Queue, publish

pytestmark = pytest.mark.integration


@pytest.fixture
def scenario(db_url: str) -> Iterator[str]:
    run = create_lab(db_url)
    yield run
    retire_inventory_access(run, db_url)
    with connect(db_url) as conn:
        conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def selected_stock(state: dict) -> dict:
    return next(
        s
        for s in state["stock"]
        if s["store"] == "store-1" and s["sku"] == state["selected_product"]
    )


def test_real_process_crash_and_delayed_supply(db_url: str, scenario: str) -> None:
    result = run_slice(scenario, db_url)
    assert result["run"]["status"] == "complete"
    checkpoints = result["checkpoints"]
    crashed = checkpoints[0]["state"]
    assert selected_stock(crashed)["reserved"] == 0
    assert crashed["baskets"] == [] and crashed["decisions"] == []
    race = checkpoints[1]["state"]
    assert [b["status"] for b in race["baskets"]] == ["reserved", "rejected"]
    assert selected_stock(race)["available_now"] == 0
    delayed = checkpoints[3]["state"]
    assert delayed["run"]["sim_time"] == 300
    assert selected_stock(delayed)["on_hand"] == 1
    assert selected_stock(delayed)["incoming"][0]["expected_sim"] == 900
    assert selected_stock(result)["available_now"] == 6
    assert all(result["invariants"].values())
    assert result["crash"]["recovered_attempts"] == 2
    assert all(e["state"] == "done" for e in result["events"])
    with pytest.raises(ValueError):
        run_slice(scenario, db_url)


def test_crash_after_commit_preserves_ack(db_url: str, scenario: str) -> None:
    prepare_slice(scenario, db_url)
    assert crash_worker(scenario, db_url, "after-commit") == 74
    state = lab_snapshot(scenario, db_url)
    assert selected_stock(state)["reserved"] == 1
    assert state["events"][0]["state"] == "done"
    next_event = Queue(db_url).claim("inventory", scenario, 0)
    assert next_event and next_event.payload["basket"] == "basket-b"


def test_lab_inspection_contract(db_url: str, scenario: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)
    settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/lab").status_code == 200
            state = client.get(f"/api/lab/state?run={scenario}").json()
            assert state["selected_store"] == "store-1"
            assert state["invariants"]["stock_conserved"]
            assert len(state["city"]["stores"]) == 5
            assert client.get(f"/api/lab/runs/{scenario}/evidence").status_code == 404
            assert client.get("/api/lab/state?run=bad").status_code == 422
            assert client.post("/api/lab/runs", json={"seed": -1}).status_code == 422
            assert (
                client.post(
                    "/api/lab/runs", json={}, headers={"Origin": "https://elsewhere.test"}
                ).status_code
                == 403
            )
            assert scenario not in client.get("/api/runs").text
    finally:
        settings.cache_clear()


def test_second_delay_defers_obsolete_receipt(db_url: str, scenario: str) -> None:
    prepare_slice(scenario, db_url)
    drain(scenario, 120, db_url)
    with connect(db_url) as conn:
        publish(
            conn,
            run_id=scenario,
            producer="lab_scenario",
            topic="shipment.delayed",
            payload={"shipment": "supply-1", "expected_sim": 1200},
            key="second-delay",
            trace_id="supply-1",
            due_sim=240,
            target_store="store-1",
        )
    drain(scenario, 240, db_url)
    drain(scenario, 900, db_url)
    assert selected_stock(lab_snapshot(scenario, db_url))["on_hand"] == 1
    drain(scenario, 1200, db_url)
    state = lab_snapshot(scenario, db_url)
    assert selected_stock(state)["on_hand"] == 6
    assert len([m for m in state["movements"] if m["kind"] == "received"]) == 1


def test_drain_waits_for_temporarily_unavailable_events(db_url: str, scenario: str) -> None:
    prepare_slice(scenario, db_url)
    with connect(db_url) as conn:
        conn.execute(
            """UPDATE events SET available_at=now()+interval '0.2 seconds'
            WHERE run_id=%s AND topic='basket.requested'""",
            (scenario,),
        )
    drain(scenario, 0, db_url)
    state = lab_snapshot(scenario, db_url)
    assert sorted(b["status"] for b in state["baskets"]) == ["rejected", "reserved"]
    assert all(e["state"] == "done" for e in state["events"] if e["due_sim"] == 0)

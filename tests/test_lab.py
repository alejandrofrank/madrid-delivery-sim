from collections.abc import Iterator

import pytest

from delivery.db import connect
from delivery.lab import crash_worker, create_lab, lab_snapshot, prepare_slice, run_slice
from delivery.queue import Queue

pytestmark = pytest.mark.integration


@pytest.fixture
def scenario(db_url: str) -> Iterator[str]:
    run = create_lab(db_url)
    yield run
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

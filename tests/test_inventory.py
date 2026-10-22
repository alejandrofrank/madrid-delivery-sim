from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from delivery.db import connect
from delivery.inventory import availability, receive, release, reserve
from delivery.lab import create_lab

pytestmark = pytest.mark.integration


@pytest.fixture
def lab_run(db_url: str) -> Iterator[tuple[str, str]]:
    run = create_lab(db_url)
    with connect(db_url) as conn:
        row = conn.execute(
            "SELECT selected_product FROM lab_worlds WHERE run_id=%s", (run,)
        ).fetchone()
        assert row
    yield run, row["selected_product"]
    with connect(db_url) as conn:
        conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def test_last_unit_race_and_idempotent_release(db_url: str, lab_run: tuple[str, str]) -> None:
    run, sku = lab_run

    def attempt(basket: str) -> tuple[str, str]:
        with connect(db_url) as conn:
            return basket, reserve(conn, run, basket, "store-1", sku, 1, 0, 600)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = dict(pool.map(attempt, ["a", "b"]))
    assert sorted(outcomes.values()) == ["rejected", "reserved"]
    winner = next(key for key, value in outcomes.items() if value == "reserved")
    with connect(db_url) as conn:
        assert reserve(conn, run, winner, "store-1", sku, 1, 0, 600) == "reserved"
        with conn.transaction(), pytest.raises(ValueError):
            reserve(conn, run, winner, "store-1", sku, 2, 0, 600)
        with conn.transaction(), pytest.raises(ValueError):
            release(conn, run, winner, 599)
        assert release(conn, run, winner, 600) == "expired"
        assert release(conn, run, winner, 600) == "expired"
        stock = next(
            s for s in availability(conn, run) if s["store"] == "store-1" and s["sku"] == sku
        )
        assert stock["available_now"] == 1 and stock["version"] == 2
        assert stock["incoming"][0]["quantity"] == 5


def test_delayed_supply_never_counts_as_stock(db_url: str, lab_run: tuple[str, str]) -> None:
    run, sku = lab_run
    with connect(db_url) as conn:
        conn.execute(
            "UPDATE lab_shipments SET expected_sim=900,status='delayed' WHERE run_id=%s", (run,)
        )
        with conn.transaction(), pytest.raises(ValueError):
            receive(conn, run, "supply-1", 300)
        assert receive(conn, run, "supply-1", 900)
        assert not receive(conn, run, "supply-1", 900)
        stock = next(
            s for s in availability(conn, run) if s["store"] == "store-1" and s["sku"] == sku
        )
        assert stock["available_now"] == 6 and stock["incoming"] == []
        assert conn.execute(
            """SELECT sum(delta_hand) AS hand,sum(delta_reserved) AS reserved
                            FROM lab_movements WHERE run_id=%s AND store='store-1' AND sku=%s""",
            (run, sku),
        ).fetchone() == {"hand": 6, "reserved": 0}

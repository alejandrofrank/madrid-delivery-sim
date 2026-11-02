import pytest

from delivery.dark_store import DarkStore
from delivery.db import connect
from delivery.environment import Environment
from delivery.queue import publish
from delivery.simulation import Simulation, create_run
from delivery.store_layout import StoreConfig
from delivery.store_setup import attach_store_order
from delivery.world import World


@pytest.fixture(scope="module")
def store_world() -> World:
    return World()


@pytest.fixture
def store_run(db_url: str, store_world: World):
    run = create_run(
        store_world, wall_seconds=0, duration=1800, url=db_url, dark_store=StoreConfig()
    )
    try:
        with connect(db_url) as conn:
            conn.execute("UPDATE runs SET status='running' WHERE id=%s", (run,))
            store = conn.execute(
                "SELECT e.store,l.district FROM store_environments e "
                "JOIN locations l ON l.id=e.store WHERE run_id=%s "
                "ORDER BY e.store LIMIT 1",
                (run,),
            ).fetchone()
            customer = conn.execute(
                "SELECT id FROM locations WHERE kind='customer' "
                "AND district=%s ORDER BY id LIMIT 1",
                (store["district"],),
            ).fetchone()
            conn.execute(
                "INSERT INTO orders(run_id,id,store,customer,created_sim,ready_sim,due_sim) "
                "VALUES (%s,'shelf-to-door',%s,%s,0,0,1800)",
                (run, store["store"], customer["id"]),
            )
            assert attach_store_order(conn, run, "shelf-to-door", 0, 42)
        yield run
    finally:
        with connect(db_url) as conn:
            for table in (
                "llm_requests",
                "decisions",
                "complaints",
                "orders",
                "couriers",
                "events",
                "runs",
            ):
                field = "id" if table == "runs" else "run_id"
                conn.execute(f"DELETE FROM {table} WHERE {field}=%s", (run,))


def test_dark_store_is_an_environment() -> None:
    assert isinstance(DarkStore(), Environment)


@pytest.mark.integration
def test_pick_pack_dock_then_existing_courier_without_stock_drift(
    db_url: str,
    store_world: World,
    store_run: str,
) -> None:
    simulation = Simulation(store_world, db_url)
    with connect(db_url) as conn:
        opening = conn.execute(
            "SELECT sum(on_hand) n FROM lab_stock WHERE run_id=%s", (store_run,)
        ).fetchone()["n"]
        publish(
            conn,
            run_id=store_run,
            producer="generator",
            topic="order.created",
            payload={"order_id": "shelf-to-door"},
            key="early-dispatch",
            trace_id="shelf-to-door",
        )
    simulation.drain(store_run, 0)
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT status FROM orders WHERE run_id=%s AND id='shelf-to-door'", (store_run,)
            ).fetchone()["status"]
            == "pending"
        )
    for sim in range(0, 1801, 10):
        simulation.step(store_run, sim, 42, 1800)
    with connect(db_url) as conn:
        order = conn.execute(
            "SELECT * FROM store_orders WHERE run_id=%s AND order_id='shelf-to-door'", (store_run,)
        ).fetchone()
        assert order["stage"] == "handed_off", conn.execute(
            "SELECT topic,state,error FROM events WHERE run_id=%s AND state='dead'", (store_run,)
        ).fetchall()
        assert order["lines"] == order["picked"]
        assert order["packed_sim"] <= order["dock_sim"]
        delivery = conn.execute(
            "SELECT * FROM orders WHERE run_id=%s AND id='shelf-to-door'", (store_run,)
        ).fetchone()
        assert delivery["status"] == "delivered"
        assert delivery["route"]["pickup_at"] >= order["dock_sim"]
        assert (
            conn.execute(
                "SELECT count(*) n FROM events WHERE run_id=%s AND state='dead'", (store_run,)
            ).fetchone()["n"]
            == 0
        )
        stock = conn.execute(
            "SELECT sum(on_hand) n,sum(reserved) r FROM lab_stock WHERE run_id=%s", (store_run,)
        ).fetchone()
        shelves = conn.execute(
            "SELECT sum(quantity) n FROM store_shelves WHERE run_id=%s", (store_run,)
        ).fetchone()
        receipts = conn.execute(
            "SELECT sum(quantity) n FROM lab_shipments WHERE run_id=%s AND status='received'",
            (store_run,),
        ).fetchone()["n"]
        assert stock["n"] == shelves["n"] == opening + receipts - sum(order["picked"].values())
        assert stock["r"] == 0
        assert (
            conn.execute(
                "SELECT count(*) n FROM decisions WHERE run_id=%s AND agent='fulfillment'",
                (store_run,),
            ).fetchone()["n"]
            > 0
        )
        before = stock["n"]
    # Repeating the physical clock and queue drain cannot pick or receive a second time.
    simulation.step(store_run, 1800, 42, 1800)
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT sum(on_hand) n FROM lab_stock WHERE run_id=%s", (store_run,)
            ).fetchone()["n"]
            == before
        )


@pytest.mark.integration
def test_city_only_runs_do_not_create_store_state(db_url: str, store_world: World) -> None:
    run = create_run(store_world, wall_seconds=0, duration=1800, url=db_url)
    try:
        with connect(db_url) as conn:
            assert DarkStore().read(conn, run)["stores"] == []
    finally:
        with connect(db_url) as conn:
            for table in (
                "llm_requests",
                "decisions",
                "complaints",
                "orders",
                "couriers",
                "events",
                "runs",
            ):
                field = "id" if table == "runs" else "run_id"
                conn.execute(f"DELETE FROM {table} WHERE {field}=%s", (run,))


@pytest.mark.integration
def test_store_tools_enforce_order_scope_and_physical_arrival(db_url, store_run):
    from delivery.queue import Queue
    from delivery.store_tools import StoreTools, reservation_key

    event = Queue(db_url).claim(
        "inventory", store_run, 0, accepted_topics=("store.order.requested",)
    )
    assert event
    with connect(db_url) as conn:
        order = conn.execute("SELECT * FROM store_orders WHERE run_id=%s", (store_run,)).fetchone()
        assert order
        inventory = StoreTools(conn, event, "inventory", order)
        sku = next(iter(order["lines"]))
        with pytest.raises(PermissionError):
            inventory.invoke("inventory.read", store="another-store")
        with pytest.raises(PermissionError):
            inventory.invoke(
                "inventory.reserve",
                basket=reservation_key("another-order", sku),
                sku=sku,
                quantity=1,
                expires_sim=100,
            )
        fulfillment = StoreTools(conn, event, "fulfillment", order)
        with pytest.raises(PermissionError, match="physical task"):
            fulfillment.invoke("fulfillment.pack", worker="picker-1")
        with pytest.raises(ValueError, match="Every item"):
            fulfillment.invoke("fulfillment.route", worker="picker-1", plan={"action": "pack"})


@pytest.mark.integration
def test_read_only_store_api_returns_real_layout_and_bounded_frames(db_url, store_run, monkeypatch):
    from fastapi.testclient import TestClient

    from delivery.api import app

    monkeypatch.setattr("delivery.store_api.connect", lambda: connect(db_url))
    client = TestClient(app)
    response = client.get("/api/runs/" + store_run + "/stores")
    assert response.status_code == 200
    state = response.json()
    assert len(state["stores"]) == 3
    assert state["stores"][0]["layout"]["units"] == "metres"
    assert state["stores"][0]["catalogue"]
    assert client.get("/api/runs/" + store_run + "/stores?at=-1").status_code == 422
    assert client.get("/api/runs/" + store_run + "/stores?at=0").status_code == 404
    with connect(db_url) as conn:
        DarkStore().record(conn, store_run)
    frame = client.get("/api/runs/" + store_run + "/stores?at=0")
    assert frame.status_code == 200
    assert frame.json()["stores"][0]["layout"] == state["stores"][0]["layout"]


@pytest.mark.integration
def test_cancel_releases_only_remaining_units(db_url, store_run):
    from psycopg.types.json import Jsonb

    from delivery.inventory import reserve
    from delivery.store_agents import cancel_order
    from delivery.store_tools import reservation_key

    with connect(db_url) as conn:
        order = conn.execute("SELECT * FROM store_orders WHERE run_id=%s", (store_run,)).fetchone()
        sku = next(iter(order["lines"]))
        order["lines"] = {sku: 3}
        order["picked"] = {sku: 1}
        reserve(
            conn, store_run, reservation_key(order["order_id"], sku), order["store"], sku, 3, 0, 100
        )
        conn.execute(
            "UPDATE lab_stock SET on_hand=on_hand-1,reserved=reserved-1 "
            "WHERE run_id=%s AND store=%s AND sku=%s",
            (store_run, order["store"], sku),
        )
        conn.execute(
            "UPDATE store_orders SET lines=%s,picked=%s WHERE run_id=%s",
            (Jsonb(order["lines"]), Jsonb(order["picked"]), store_run),
        )
        cancel_order(conn, store_run, order, 10)
        cancel_order(conn, store_run, order, 10)
        stock = conn.execute(
            "SELECT reserved,on_hand FROM lab_stock WHERE run_id=%s AND store=%s AND sku=%s",
            (store_run, order["store"], sku),
        ).fetchone()
        assert stock["reserved"] == 0 and stock["on_hand"] == 23


def test_finishing_a_store_shift_releases_unpicked_stock(db_url, store_world, store_run):
    from delivery.simulation import finish_run

    simulation = Simulation(store_world, db_url)
    simulation.step(store_run, 0, 42, 0)
    with connect(db_url) as conn:
        assert conn.execute(
            "SELECT sum(reserved) n FROM lab_stock WHERE run_id=%s", (store_run,)
        ).fetchone()["n"] > 0
    finish_run(store_run, db_url, store_enabled=True)
    finish_run(store_run, db_url, store_enabled=True)
    with connect(db_url) as conn:
        assert conn.execute(
            "SELECT sum(reserved) n FROM lab_stock WHERE run_id=%s", (store_run,)
        ).fetchone()["n"] == 0
        row = conn.execute(
            "SELECT s.stage,o.status FROM store_orders s JOIN orders o "
            "ON o.run_id=s.run_id AND o.id=s.order_id WHERE s.run_id=%s", (store_run,)
        ).fetchone()
        assert row == {"stage": "cancelled", "status": "unserved"}

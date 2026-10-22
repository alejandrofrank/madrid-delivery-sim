"""Fictional-city inventory lab, isolated from the Madrid delivery fixture."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from delivery.catalogue import load_catalogue
from delivery.city import fake_city
from delivery.db import connect, migrate
from delivery.inventory import availability, movement
from delivery.inventory_agent import handle_inventory
from delivery.queue import Queue, publish


def create_lab(
    url: str | None = None, seed: int = 42, catalogue_path: Path = Path("data/lab-catalogue.json")
) -> str:
    migrate(url)
    catalogue = load_catalogue(catalogue_path)
    city = fake_city(seed)
    run = str(uuid4())
    selected = f"{catalogue.products[0].source}:{catalogue.products[0].listing_id}"
    selected_store = next(
        s["id"] for s in city["stores"] if s["kind"] == catalogue.products[0].domain
    )
    with connect(url) as conn:
        conn.execute(
            "INSERT INTO runs(id,seed,duration,wall_seconds) VALUES (%s,%s,900,0)", (run, seed)
        )
        conn.execute(
            "INSERT INTO lab_worlds VALUES (%s,%s,%s,%s,%s)",
            (
                run,
                Jsonb(city),
                Jsonb(catalogue.model_dump(mode="json")),
                catalogue.digest(),
                selected,
            ),
        )
        for store in city["stores"]:
            for product in catalogue.products:
                if store["kind"] != product.domain:
                    continue
                sku = f"{product.source}:{product.listing_id}"
                count = 1 if sku == selected else 10
                conn.execute(
                    "INSERT INTO lab_stock(run_id,store,sku,on_hand) VALUES (%s,%s,%s,%s)",
                    (run, store["id"], sku, count),
                )
                movement(
                    conn,
                    run,
                    f"opening:{store['id']}:{sku}",
                    store["id"],
                    sku,
                    0,
                    "opening",
                    count,
                    0,
                )
        conn.execute(
            """INSERT INTO lab_shipments(run_id,id,store,sku,quantity,expected_sim)
                     VALUES (%s,'supply-1',%s,%s,5,300)""",
            (run, selected_store, selected),
        )
    return run


def lab_snapshot(run: str | None = None, url: str | None = None) -> dict[str, Any]:
    with connect(url) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        row = conn.execute(
            """SELECT r.*,w.city,w.catalogue,w.catalogue_hash,w.selected_product
            FROM runs r JOIN lab_worlds w ON w.run_id=r.id
            WHERE (%s::uuid IS NULL OR r.id=%s) ORDER BY r.created_at DESC LIMIT 1""",
            (run, run),
        ).fetchone()
        if not row:
            return {"run": None}
        run = str(row["id"])
        stock = availability(conn, run)
        ledger = conn.execute(
            """SELECT store,sku,sum(delta_hand) AS hand,
            sum(delta_reserved) AS reserved FROM lab_movements WHERE run_id=%s
            GROUP BY store,sku""",
            (run,),
        ).fetchall()
        totals = {(s["store"], s["sku"]): (s["hand"], s["reserved"]) for s in ledger}
        conservation = all(
            totals.get((s["store"], s["sku"])) == (s["on_hand"], s["reserved"]) for s in stock
        )

        def rows(table: str, order: str) -> list[dict[str, Any]]:
            return conn.execute(
                f"SELECT * FROM {table} WHERE run_id=%s ORDER BY {order}", (run,)
            ).fetchall()

        return {
            "run": {key: row[key] for key in ("id", "seed", "status", "sim_time", "error")},
            "city": row["city"],
            "catalogue": row["catalogue"],
            "catalogue_hash": row["catalogue_hash"],
            "selected_product": row["selected_product"],
            "selected_store": next(
                s["id"]
                for s in row["city"]["stores"]
                if s["kind"] == row["catalogue"]["products"][0].get("domain", "supermarket")
            ),
            "stock": stock,
            "baskets": rows("lab_baskets", "id"),
            "shipments": rows("lab_shipments", "id"),
            "movements": rows("lab_movements", "sim_time,command_key"),
            "decisions": rows("decisions", "id"),
            "events": conn.execute(
                """SELECT id,topic,trace_id,parent_id,state,attempts,
                    due_sim,error FROM events WHERE run_id=%s ORDER BY id""",
                (run,),
            ).fetchall(),
            "invariants": {
                "stock_conserved": conservation,
                "nonnegative_available": all(s["available_now"] >= 0 for s in stock),
            },
        }


def prepare_slice(run: str, url: str | None = None) -> None:
    with connect(url) as conn:
        world = conn.execute(
            "SELECT selected_product,city,catalogue FROM lab_worlds WHERE run_id=%s", (run,)
        ).fetchone()
        assert world
        store = next(
            s["id"]
            for s in world["city"]["stores"]
            if s["kind"] == world["catalogue"]["products"][0].get("domain", "supermarket")
        )
        for basket in ("basket-a", "basket-b"):
            publish(
                conn,
                run_id=run,
                producer="lab_scenario",
                topic="basket.requested",
                payload={
                    "basket": basket,
                    "store": store,
                    "sku": world["selected_product"],
                    "quantity": 1,
                    "expires_sim": 600,
                },
                key=basket,
                trace_id=basket,
            )
        publish(
            conn,
            run_id=run,
            producer="lab_scenario",
            topic="shipment.delayed",
            payload={"shipment": "supply-1", "expected_sim": 900},
            key="delay-1",
            trace_id="supply-1",
            due_sim=120,
        )
        publish(
            conn,
            run_id=run,
            producer="lab_scenario",
            topic="reservation.expire",
            payload={"basket": "basket-a"},
            key="expiry-a",
            trace_id="basket-a",
            due_sim=600,
        )


def crash_worker(run: str, url: str | None = None, point: str = "after-write") -> int:
    env = os.environ.copy()
    if url:
        env["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "delivery.lab_worker", run, "--crash", point],
        env=env,
        timeout=20,
        capture_output=True,
    )
    expected = 73 if point == "after-write" else 74
    if result.returncode != expected:
        raise RuntimeError("Crash-injection worker did not reach requested checkpoint")
    return result.returncode


def drain(run: str, sim: int, url: str | None = None) -> None:
    queue = Queue(url)
    deadline = time.monotonic() + 10
    with connect(url) as conn:
        conn.execute("UPDATE runs SET sim_time=%s WHERE id=%s", (sim, run))
    for _ in range(100):
        event = queue.claim("inventory", run, sim)
        if event:
            if not queue.process(event, handle_inventory):
                raise RuntimeError("Inventory handler failed; inspect event errors")
            continue
        event = queue.claim("inventory_audit", run, sim)
        if event:
            if not queue.process(event, lambda conn, message: None):
                raise RuntimeError("Inventory audit failed")
            continue
        with connect(url) as conn:
            pending = conn.execute(
                """SELECT count(*) AS n FROM events WHERE run_id=%s
                AND due_sim<=%s AND state IN ('ready','leased')""",
                (run, sim),
            ).fetchone()
        if not pending or pending["n"] == 0:
            return
        # A temporarily unavailable event is not an empty queue. Respect wall-clock
        # availability/lease deadlines before advancing the simulation clock.
        if time.monotonic() >= deadline:
            raise RuntimeError("Inventory queue did not become drainable within deadline")
        time.sleep(0.05)
    raise RuntimeError("Inventory event budget exhausted")


def run_slice(run: str, url: str | None = None, playback_seconds: float = 0) -> dict[str, Any]:
    if playback_seconds < 0 or playback_seconds > 120:
        raise ValueError("Playback must be 0..120 seconds")
    with connect(url) as conn:
        started = conn.execute(
            """UPDATE runs SET status='running'
            WHERE id=%s AND status='ready' RETURNING id""",
            (run,),
        ).fetchone()
        if not started:
            raise ValueError("Lab run must be ready; completed runs are immutable")
    checkpoints = []
    try:
        prepare_slice(run, url)
        exit_code = crash_worker(run, url)
        crashed = lab_snapshot(run, url)
        checkpoints.append(
            {
                "label": "worker exited after uncommitted stock write",
                "worker_exit_code": exit_code,
                "state": crashed,
            }
        )
        # Wait for an actual wall-clock lease expiry, never rewrite timestamps to fake recovery.
        deadline = time.monotonic() + 5
        while True:
            with connect(url) as conn:
                expired = conn.execute(
                    """SELECT lease_until<=now() AS expired FROM events
                    WHERE run_id=%s AND state='leased'""",
                    (run,),
                ).fetchone()
            if expired and expired["expired"]:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Crashed worker lease did not expire")
            time.sleep(0.05)
        for sim, label in [
            (0, "one winner, one rejected"),
            (120, "shipment delayed"),
            (300, "original ETA: incoming units still unavailable"),
            (600, "unused reservation expired"),
            (900, "shipment received"),
        ]:
            drain(run, sim, url)
            state = lab_snapshot(run, url)
            if not all(state["invariants"].values()):
                raise RuntimeError("Inventory invariant failed")
            checkpoints.append({"label": label, "state": state})
            if playback_seconds:
                time.sleep(playback_seconds / 5)
        final = lab_snapshot(run, url)
        attempts = [
            e["attempts"]
            for e in final["events"]
            if e["trace_id"] == "basket-a" and e["topic"] == "basket.requested"
        ]
        if attempts != [2] or any(e["state"] != "done" for e in final["events"]):
            summary = [(e["topic"], e["state"], e["attempts"], e["error"]) for e in final["events"]]
            raise RuntimeError(f"Recovery or queue-drain assertion failed: {summary}")
        with connect(url) as conn:
            conn.execute("UPDATE runs SET status='complete' WHERE id=%s", (run,))
        return {
            **lab_snapshot(run, url),
            "checkpoints": checkpoints,
            "crash": {
                "exit_code": exit_code,
                "recovered_attempts": 2,
                "point": "after stock write, before transaction commit and ACK",
            },
        }
    except Exception as exc:
        with connect(url) as conn:
            conn.execute(
                "UPDATE runs SET status='failed',error=%s WHERE id=%s", (type(exc).__name__, run)
            )
        raise


def export_slice(run: str, playback_seconds: float = 0) -> dict[str, Any]:
    result = run_slice(run, playback_seconds=playback_seconds)
    Path("artifacts").mkdir(exist_ok=True)
    path = Path(f"artifacts/lab-{run}.json")
    path.write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
    return result

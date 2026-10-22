"""Queue-facing inventory agent with structured decision evidence."""

from psycopg.types.json import Jsonb

from delivery.db import Connection
from delivery.inventory import receive, release, reserve
from delivery.queue import Event, publish


def handle_inventory(conn: Connection, event: Event) -> None:
    run = str(event.run_id)
    clock = conn.execute("SELECT sim_time FROM runs WHERE id=%s", (run,)).fetchone()
    assert clock
    sim = clock["sim_time"]
    body = event.payload
    if event.topic == "basket.requested":
        result = reserve(
            conn,
            run,
            body["basket"],
            body["store"],
            body["sku"],
            body["quantity"],
            sim,
            body["expires_sim"],
        )
        detail = {
            "basket": body["basket"],
            "status": result,
            "rule": "reserve only confirmed available units; reject insufficient stock",
        }
    elif event.topic == "reservation.expire":
        result = release(conn, run, body["basket"], sim)
        detail = {
            "basket": body["basket"],
            "status": result,
            "rule": "release unused reservation once at simulation deadline",
        }
    elif event.topic == "shipment.delayed":
        row = conn.execute(
            """UPDATE lab_shipments SET expected_sim=%s,status='delayed'
                            WHERE run_id=%s AND id=%s AND status!='received' RETURNING id""",
            (body["expected_sim"], run, body["shipment"]),
        ).fetchone()
        if not row or body["expected_sim"] < sim:
            raise ValueError("Invalid shipment delay")
        publish(
            conn,
            run_id=run,
            producer="inventory",
            topic="shipment.received",
            payload={"shipment": body["shipment"]},
            key=body["shipment"],
            trace_id=event.trace_id,
            parent_id=event.id,
            due_sim=body["expected_sim"],
        )
        detail = {
            "shipment": body["shipment"],
            "expected_sim": body["expected_sim"],
            "rule": "expected supply is a forecast, not sellable stock",
        }
    elif event.topic == "shipment.received":
        received = receive(conn, run, body["shipment"], sim)
        detail = {
            "shipment": body["shipment"],
            "received": received,
            "rule": "confirmed receipt adds units exactly once",
        }
    else:
        raise ValueError("Unsupported inventory event")
    conn.execute(
        """INSERT INTO decisions(run_id,sim_time,agent,order_id,event_id,action,detail)
                 VALUES (%s,%s,'inventory',%s,%s,%s,%s)""",
        (run, sim, body.get("basket"), event.id, event.topic, Jsonb(detail)),
    )
    publish(
        conn,
        run_id=run,
        producer="inventory",
        topic="inventory.decided",
        payload=detail,
        key=str(event.id),
        trace_id=event.trace_id,
        parent_id=event.id,
        due_sim=sim,
    )

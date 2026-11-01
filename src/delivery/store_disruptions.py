"""Store disruption effects change physical facts, never choose an agent response."""

from typing import Any

from delivery.db import Connection
from delivery.queue import publish
from delivery.store_conditions import STORE_KINDS


def validate_store_target(
    conn: Connection, run: str, target: str | None, resource: str | None, kind: str
) -> None:
    environments = conn.execute(
        "SELECT store,layout FROM store_environments WHERE run_id=%s ORDER BY store", (run,)
    ).fetchall()
    if not environments:
        raise ValueError("In-store disruptions require an enabled DarkStore environment")
    if target != "auto" and target not in {e["store"] for e in environments}:
        raise ValueError("Unknown dark store target")
    if kind == "robot_breakdown":
        candidates = [e for e in environments if target == "auto" or e["store"] == target]
        if any(e["layout"]["config"]["picker_kind"] != "robot" for e in candidates):
            raise ValueError("Robot breakdown requires robot pickers in the target store")
    if resource:
        environment = next((e for e in environments if e["store"] == target), None)
        if environment is None:
            raise ValueError("An explicit store is required when selecting a resource")
        layout = environment["layout"]
        if kind == "blocked_aisle":
            valid = resource in {a["id"] for a in layout["aisles"]}
        elif kind == "shelf_out_of_stock":
            valid = resource in {s["id"] for s in layout["slots"]}
        elif kind == "robot_breakdown":
            valid = (
                conn.execute(
                    "SELECT 1 FROM store_workers WHERE run_id=%s AND store=%s "
                    "AND id=%s AND kind='robot'",
                    (run, target, resource),
                ).fetchone()
                is not None
            )
        else:
            valid = (
                conn.execute(
                    "SELECT 1 FROM lab_shipments WHERE run_id=%s AND store=%s "
                    "AND id=%s AND status!='received'",
                    (run, target, resource),
                ).fetchone()
                is not None
            )
        if not valid:
            raise ValueError("Unknown or unavailable store resource")


def start_store_disruption(conn: Connection, run: str, event: dict[str, Any], sim: int) -> None:
    assert event["kind"] in STORE_KINDS
    target = event["target"]
    if target == "auto":
        row = conn.execute(
            "SELECT e.store FROM store_environments e LEFT JOIN store_orders o "
            "ON o.run_id=e.run_id AND o.store=e.store AND o.stage NOT IN "
            "('dock','handed_off','cancelled') WHERE e.run_id=%s "
            "GROUP BY e.store ORDER BY count(o.order_id) DESC,e.store LIMIT 1",
            (run,),
        ).fetchone()
        if not row:
            raise ValueError("Store disruption has no environment")
        target = row["store"]
    environment = conn.execute(
        "SELECT layout FROM store_environments WHERE run_id=%s AND store=%s", (run, target)
    ).fetchone()
    if environment is None:
        raise ValueError("Unknown store environment")
    layout = environment["layout"]
    resource = event["resource"]
    kind = event["kind"]
    if resource is None:
        if kind == "blocked_aisle":
            resource = layout["aisles"][0]["id"]
        elif kind == "shelf_out_of_stock":
            picking = conn.execute(
                "SELECT task->>'slot' slot FROM store_workers WHERE run_id=%s "
                "AND store=%s AND task->>'action'='pick' ORDER BY id LIMIT 1",
                (run, target),
            ).fetchone()
            resource = picking["slot"] if picking else layout["slots"][0]["id"]
        elif kind == "robot_breakdown":
            robot = conn.execute(
                "SELECT id FROM store_workers WHERE run_id=%s AND store=%s "
                "AND kind='robot' ORDER BY (task IS NOT NULL) DESC,id LIMIT 1",
                (run, target),
            ).fetchone()
            if not robot:
                raise ValueError("This store has no robot picker")
            resource = robot["id"]
        else:
            shipment = conn.execute(
                "SELECT id FROM lab_shipments WHERE run_id=%s AND store=%s "
                "AND status!='received' ORDER BY expected_sim,id LIMIT 1",
                (run, target),
            ).fetchone()
            resource = shipment["id"] if shipment else None
    conn.execute(
        "UPDATE chaos_events SET state='active',target=%s,resource=%s WHERE run_id=%s AND id=%s",
        (target, resource, run, event["id"]),
    )
    if kind == "shelf_out_of_stock":
        slot = conn.execute(
            "SELECT sku,quantity FROM store_shelves WHERE run_id=%s AND store=%s "
            "AND slot=%s FOR UPDATE",
            (run, target, resource),
        ).fetchone()
        if slot:
            conn.execute(
                "UPDATE store_shelves SET quantity=0 WHERE run_id=%s AND store=%s AND slot=%s",
                (run, target, resource),
            )
            # Move observed units to unlocated backstock; never create or erase stock.
            conn.execute(
                "INSERT INTO store_shelves VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT(run_id,store,slot) DO UPDATE SET "
                "quantity=store_shelves.quantity+excluded.quantity",
                (run, target, "backstock:" + slot["sku"], slot["sku"], slot["quantity"]),
            )
    elif kind == "late_restock_truck" and resource:
        conn.execute(
            "UPDATE lab_shipments SET expected_sim=greatest(expected_sim,%s),status='delayed' "
            "WHERE run_id=%s AND store=%s AND id=%s AND status!='received'",
            (event["end_sim"], run, target, resource),
        )
    publish(
        conn,
        run_id=run,
        producer="store_world",
        topic="store.disruption",
        payload={"disruption": event["id"], "kind": kind, "store": target, "resource": resource},
        key=event["id"],
        trace_id=event["id"],
        due_sim=sim,
        target_store=target,
    )

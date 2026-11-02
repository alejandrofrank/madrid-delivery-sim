"""Existing inventory policy plus fulfillment's observable route/packing decisions."""

from dataclasses import replace
from typing import Any, cast

from delivery.agent_runtime import InventoryPolicy, ScopedTools
from delivery.db import Connection, connect
from delivery.inventory import movement
from delivery.queue import Event, Queue
from delivery.store_actions import emit
from delivery.store_layout import aisle_path, plan_pick
from delivery.store_tools import StoreTools, reservation_key
from delivery.world import trace


def handle_store_event(conn: Connection, event: Event, role: str) -> None:
    run = str(event.run_id)
    order = conn.execute(
        "SELECT * FROM store_orders WHERE run_id=%s AND order_id=%s FOR UPDATE",
        (run, event.payload.get("order_id")),
    ).fetchone()
    if order is None:
        # Environment-originated stock maintenance may precede the first customer order.
        if event.payload.get("order_id") != "_stock" or not event.target_store:
            raise ValueError("Unknown store order")
        exists = conn.execute(
            "SELECT 1 FROM store_environments WHERE run_id=%s AND store=%s",
            (run, event.target_store),
        ).fetchone()
        if not exists:
            raise ValueError("Unknown store environment")
        order = {
            "order_id": "_stock",
            "store": event.target_store,
            "lines": {},
            "picked": {},
            "stage": "maintenance",
            "worker": None,
            "packed_sim": None,
        }
    if order["stage"] in {"cancelled", "handed_off"}:
        return
    tools = StoreTools(conn, event, role, order)
    if role == "inventory":
        result = inventory_turn(tools)
    else:
        result = fulfillment_turn(tools)
    trace(
        conn,
        run,
        tools.sim,
        role,
        result.get("action", result.get("status", "observed")),
        {
            **result,
            "environment": "dark_store",
            "store": order["store"],
            "tools": tools.calls,
            "role_hash": tools.role.digest,
        },
        None if order["order_id"] == "_stock" else order["order_id"],
        event=event.id,
    )


def inventory_turn(tools: StoreTools) -> dict[str, Any]:
    event, order, conn = tools.event, tools.order, tools._conn
    if event.topic == "store.order.requested":
        body = {
            "basket": reservation_key(order["order_id"], event.payload["sku"]),
            "store": order["store"],
            "sku": event.payload["sku"],
            "quantity": event.payload["quantity"],
            "expires_sim": tools.sim + 43200,
            "deliver": False,
        }
        projected = replace(event, topic="basket.requested", payload=body)
    else:
        projected = replace(
            event, topic="shipment.received", payload={"shipment": event.payload["shipment"]}
        )
    # The policy is unchanged. The adapter implements the same bounded tool surface.
    result = InventoryPolicy().decide(projected, cast(ScopedTools, tools))
    if event.topic != "store.order.requested":
        return result
    if result["status"] == "rejected":
        cancel_order(conn, tools.run, order, tools.sim)
    else:
        keys = [reservation_key(order["order_id"], sku) for sku in order["lines"]]
        rows = conn.execute(
            "SELECT status FROM lab_baskets WHERE run_id=%s AND id=ANY(%s)", (tools.run, keys)
        ).fetchall()
        if len(rows) == len(keys) and all(r["status"] == "reserved" for r in rows):
            conn.execute(
                "UPDATE store_orders SET stage='reserved' WHERE run_id=%s AND order_id=%s",
                (tools.run, order["order_id"]),
            )
            emit(tools, "store.order.reserved", {})
    return result


def cancel_order(conn: Connection, run: str, order: dict[str, Any], sim: int) -> None:
    for sku in order["lines"]:
        key = reservation_key(order["order_id"], sku)
        reservation = conn.execute(
            "SELECT status FROM lab_baskets WHERE run_id=%s AND id=%s FOR UPDATE",
            (run, key),
        ).fetchone()
        if reservation and reservation["status"] == "reserved":
            remaining = order["lines"][sku] - order["picked"].get(sku, 0)
            conn.execute(
                "UPDATE lab_stock SET reserved=reserved-%s,version=version+1 "
                "WHERE run_id=%s AND store=%s AND sku=%s",
                (remaining, run, order["store"], sku),
            )
            conn.execute(
                "UPDATE lab_baskets SET status='cancelled' WHERE run_id=%s AND id=%s", (run, key)
            )
            movement(
                conn, run, "release:" + key, order["store"], sku, sim, "cancelled", 0, -remaining
            )
    conn.execute(
        "UPDATE store_workers SET route=NULL,task=NULL WHERE run_id=%s "
        "AND store=%s AND task->>'order_id'=%s",
        (run, order["store"], order["order_id"]),
    )
    conn.execute(
        "UPDATE store_orders SET stage='cancelled' WHERE run_id=%s AND order_id=%s",
        (run, order["order_id"]),
    )
    conn.execute(
        "UPDATE orders SET status='unserved' WHERE run_id=%s AND id=%s AND status='pending'",
        (run, order["order_id"]),
    )


def fulfillment_turn(tools: StoreTools) -> dict[str, Any]:
    state = tools.invoke("fulfillment.read")
    order, layout = state["order"], state["layout"]
    result: dict[str, Any] = {"action": "wait", "reason": "All suitable pickers are occupied"}
    arrived = next(
        (
            w
            for w in state["workers"]
            if w["id"] == tools.event.payload.get("worker")
            and w["task"]
            and w["route"]
            and w["route"]["end_sim"] <= tools.sim
            and w["id"] not in state["broken"]
        ),
        None,
    )
    if arrived:
        action = arrived["task"]["action"]
        tool = {
            "pick": "pick",
            "pack": "pack",
            "dock": "handoff",
            "recover": "handoff",
            "restock": "restock",
        }[action]
        result = tools.invoke("fulfillment." + tool, worker=arrived["id"])
        topic = {
            "picked": "store.item.picked",
            "packed": "store.packed",
            "dock_ready": "store.dock.ready",
        }.get(result["action"], "store.replanned")
        emit(tools, topic, result)
        if result["action"] == "dock_ready":
            emit(tools, "order.created", {})
            return result
        # Next step is a new durable event. Keep every turn within its manifest tool budget.
        return result
    if order["stage"] in {"requested", "dock", "handed_off", "cancelled"}:
        return {"action": "wait", "reason": "No unfinished reserved basket"}
    blocked = frozenset(state["blocked"])
    # Forklift chooses a depleted, reachable face from confirmed backstock.
    if order["order_id"] == "_stock":
        forklift = next(
            (
                w
                for w in state["workers"]
                if w["kind"] == "forklift" and not w["task"] and w["id"] not in state["broken"]
            ),
            None,
        )
        if forklift:
            shelf_by_id = {s["slot"]: s for s in state["shelves"]}
            for slot in sorted(
                layout["slots"], key=lambda s: (shelf_by_id[s["id"]]["quantity"], s["id"])
            ):
                back = shelf_by_id.get("backstock:" + slot["sku"], {}).get("quantity", 0)
                if (
                    back
                    and slot["id"] not in state["unavailable_shelves"]
                    and aisle_path(layout, forklift["node"], slot["access"], blocked)
                ):
                    result = tools.invoke(
                        "fulfillment.route",
                        worker=forklift["id"],
                        plan={
                            "action": "restock",
                            "sku": slot["sku"],
                            "slot": slot["id"],
                            "quantity": min(12, back),
                        },
                    )
                    emit(tools, "store.restock.started", result)
                    return result
        return {"action": "wait", "reason": "No reachable face with confirmed backstock"}
    owner = next((w for w in state["workers"] if w["id"] == order["worker"]), None)
    if owner and owner["id"] in state["broken"]:
        # Preserve basket custody until a replacement physically reaches the stranded worker.
        candidates = []
        for worker in state["workers"]:
            if (
                worker["kind"] == "forklift"
                or worker["task"]
                or worker["custody"]
                or worker["id"] in state["broken"]
            ):
                continue
            path = aisle_path(layout, worker["node"], owner["node"], blocked)
            if path:
                candidates.append((len(path), worker["id"]))
        if candidates:
            _, worker_id = min(candidates)
            result = tools.invoke("fulfillment.route", worker=worker_id, plan={"action": "recover"})
            emit(
                tools,
                "store.replanned",
                {**result, "reason": "Reach stranded basket before taking custody"},
            )
        return result
    if owner and owner["task"]:
        return {"action": "continue", "worker": owner["id"]}
    workers = [
        w
        for w in state["workers"]
        if w["kind"] != "forklift"
        and not w["task"]
        and w["id"] not in state["broken"]
        and w["custody"] in {None, order["order_id"]}
    ]
    if owner:
        workers = [w for w in workers if w["id"] == owner["id"]]
    if not workers:
        return result
    worker = workers[0]
    remaining = {sku: q - order["picked"].get(sku, 0) for sku, q in order["lines"].items()}
    if any(remaining.values()):
        plan = plan_pick(
            layout,
            worker["node"],
            remaining,
            [s for s in state["shelves"] if not s["slot"].startswith("backstock:")],
            blocked,
        )
    else:
        plan = {"action": "dock" if order["packed_sim"] is not None else "pack"}
    if plan["action"] == "wait":
        return plan
    result = tools.invoke("fulfillment.route", worker=worker["id"], plan=plan)
    emit(tools, "store.pick.started" if plan["action"] == "pick" else "store.replanned", result)
    return result


def store_tick(role: str, run: str, url: str | None = None) -> dict[str, Any]:
    if role not in {"inventory", "fulfillment"}:
        raise ValueError("Unknown store agent")
    with connect(url) as conn:
        state = conn.execute(
            "SELECT sim_time,status,store_config FROM runs WHERE id=%s", (run,)
        ).fetchone()
    if not state or state["status"] in {"complete", "failed"} or not state["store_config"]:
        raise ValueError("Unknown or closed store run")
    queue = Queue(url)
    topics = (
        ("store.order.requested", "store.restock.arrived")
        if role == "inventory"
        else ("store.order.reserved", "store.worker.arrived", "store.replan")
    )
    event = queue.claim(role, run, state["sim_time"], accepted_topics=topics)
    if event is None:
        return {"progressed": False}
    ok = queue.process(event, lambda conn, e: handle_store_event(conn, e, role))
    return {"progressed": True, "processed": ok, "event_id": event.id}

"""Authoritative, scoped effects for fulfillment's store plan."""

import math
from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from delivery.inventory import movement
from delivery.store_conditions import conditions
from delivery.store_layout import aisle_path

if TYPE_CHECKING:
    from delivery.store_tools import StoreTools


def context(tools: "StoreTools") -> dict[str, Any]:
    conn, run, store = tools._conn, tools.run, tools.store
    environment = conn.execute(
        "SELECT layout FROM store_environments WHERE run_id=%s AND store=%s", (run, store)
    ).fetchone()
    assert environment
    layout = environment["layout"]
    state = conditions(conn, run, store, layout)
    shelves = list(
        conn.execute(
            "SELECT slot,sku,quantity FROM store_shelves WHERE run_id=%s "
            "AND store=%s ORDER BY slot",
            (run, store),
        )
    )
    for shelf in shelves:
        if shelf["slot"] in state["unavailable_shelves"]:
            shelf["quantity"] = 0
    workers = list(
        conn.execute(
            "SELECT w.*, (SELECT o.order_id FROM store_orders o WHERE o.run_id=w.run_id "
            "AND o.store=w.store AND o.worker=w.id AND o.stage NOT IN "
            "('dock','handed_off','cancelled') LIMIT 1) AS custody "
            "FROM store_workers w WHERE w.run_id=%s AND w.store=%s ORDER BY w.id",
            (run, store),
        )
    )
    return {"layout": layout, "order": tools.order, "shelves": shelves, "workers": workers, **state}


def emit(tools: "StoreTools", topic: str, detail: dict[str, Any]) -> None:
    tools.invoke(
        "queue.publish",
        topic=topic,
        payload={"order_id": tools.order["order_id"], **detail},
        key=f"{tools.event.id}:{topic}",
    )


def execute(tools: "StoreTools", name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "fulfillment.read":
        return context(tools)
    conn, run, store, sim = tools._conn, tools.run, tools.store, tools.sim
    state = context(tools)
    layout, order = state["layout"], tools.order
    worker = next((w for w in state["workers"] if w["id"] == args.get("worker")), None)
    if worker is None or worker["id"] in state["broken"]:
        raise ValueError("Worker is missing or unavailable")
    if name == "fulfillment.route":
        plan = args["plan"]
        action = plan["action"]
        if worker["task"] or worker["custody"] not in {None, order["order_id"]}:
            raise ValueError("Worker already has a task or basket")
        if action == "pick":
            slot = next((s for s in layout["slots"] if s["id"] == plan.get("slot")), None)
            if (
                slot is None
                or plan["sku"] != slot["sku"]
                or slot["id"] in state["unavailable_shelves"]
            ):
                raise ValueError("Invalid pick face")
            needed = order["lines"].get(plan["sku"], 0) - order["picked"].get(plan["sku"], 0)
            if type(plan["quantity"]) is not int or not 0 < plan["quantity"] <= needed:
                raise ValueError("Pick exceeds order")
            destination, pause = slot["access"], layout["config"]["pick_seconds"]
            stage = "picking"
        elif action in {"pack", "dock"}:
            if order["picked"] != order["lines"]:
                raise ValueError("Every item must be picked before packing")
            if action == "dock" and order["packed_sim"] is None:
                raise ValueError("Basket has not been packed")
            destination = layout["packing" if action == "pack" else "dock"]["node"]
            pause = layout["config"]["pack_seconds"] if action == "pack" else 0
            stage = "packing" if action == "pack" else "to_dock"
        elif action == "recover":
            owner = next((w for w in state["workers"] if w["id"] == order["worker"]), None)
            if owner is None or owner["id"] not in state["broken"]:
                raise ValueError("No stranded basket to recover")
            destination, pause, stage = owner["node"], 10, order["stage"]
        elif action == "restock":
            if worker["kind"] != "forklift":
                raise PermissionError("Restocking requires the forklift")
            slot = next((s for s in layout["slots"] if s["id"] == plan.get("slot")), None)
            if (
                slot is None
                or slot["sku"] != plan["sku"]
                or slot["id"] in state["unavailable_shelves"]
            ):
                raise ValueError("Invalid restock face")
            quantity = plan.get("quantity")
            backstock = next(
                (
                    s["quantity"]
                    for s in state["shelves"]
                    if s["slot"] == "backstock:" + plan["sku"]
                ),
                0,
            )
            if type(quantity) is not int or not 0 < quantity <= min(12, backstock):
                raise ValueError("Restock exceeds confirmed backstock or forklift capacity")
            destination, pause, stage = slot["access"], 10, None
        else:
            raise ValueError("Unknown store task")
        path = aisle_path(layout, worker["node"], destination, frozenset(state["blocked"]))
        if path is None:
            raise ValueError("Destination is unreachable")
        if worker["kind"] == "forklift" and action != "restock":
            raise PermissionError("Forklift cannot carry customer baskets")
        if action == "restock":
            to_dock = aisle_path(
                layout, worker["node"], layout["dock"]["node"], frozenset(state["blocked"])
            )
            to_shelf = aisle_path(
                layout, layout["dock"]["node"], destination, frozenset(state["blocked"])
            )
            if to_dock is None or to_shelf is None:
                raise ValueError("Restock route must pass the loading dock")
            path = to_dock + to_shelf[1:]
        speed = layout["config"]["speed_mps"]
        points = [[*layout["nodes"][n], sim + i / speed] for i, n in enumerate(path)]
        end = sim + math.ceil((len(path) - 1) / speed) + pause
        route = {"nodes": path, "points": points, "end_sim": end}
        task = {**plan, "order_id": order["order_id"], "started_sim": sim}
        conn.execute(
            "UPDATE store_workers SET route=%s,task=%s,revision=revision+1 "
            "WHERE run_id=%s AND store=%s AND id=%s",
            (Jsonb(route), Jsonb(task), run, store, worker["id"]),
        )
        if stage:
            conn.execute(
                "UPDATE store_orders SET stage=%s,worker=%s,revision=revision+1 "
                "WHERE run_id=%s AND order_id=%s",
                (
                    stage,
                    order["worker"] if action == "recover" else worker["id"],
                    run,
                    order["order_id"],
                ),
            )
        return {"action": action, "worker": worker["id"], "route": route, "plan": plan}
    task = worker["task"]
    if not task or task["order_id"] != order["order_id"] or not worker["route"]:
        raise PermissionError("No physical task for this order")
    if worker["route"]["end_sim"] > sim:
        raise ValueError("Worker has not finished the physical step")
    if name == "fulfillment.pick" and task["action"] == "pick":
        from delivery.store_tools import reservation_key

        slot = conn.execute(
            "SELECT * FROM store_shelves WHERE run_id=%s AND store=%s AND slot=%s FOR UPDATE",
            (run, store, task["slot"]),
        ).fetchone()
        if (
            slot
            and slot["quantity"] >= task["quantity"]
            and slot["slot"] not in state["unavailable_shelves"]
        ):
            quantity, sku = task["quantity"], task["sku"]
            basket = reservation_key(order["order_id"], sku)
            reservation = conn.execute(
                "SELECT status,expires_sim FROM lab_baskets WHERE run_id=%s AND id=%s",
                (run, basket),
            ).fetchone()
            if (
                not reservation
                or reservation["status"] != "reserved"
                or reservation["expires_sim"] <= sim
            ):
                raise ValueError("Live reservation required")
            changed = conn.execute(
                "UPDATE lab_stock SET on_hand=on_hand-%s,reserved=reserved-%s,"
                "version=version+1 WHERE run_id=%s AND store=%s AND sku=%s "
                "AND reserved>=%s RETURNING sku",
                (quantity, quantity, run, store, sku, quantity),
            ).fetchone()
            if not changed:
                raise ValueError("Stock is not reserved")
            conn.execute(
                "UPDATE store_shelves SET quantity=quantity-%s WHERE run_id=%s "
                "AND store=%s AND slot=%s",
                (quantity, run, store, slot["slot"]),
            )
            picked = dict(order["picked"])
            picked[sku] = picked.get(sku, 0) + quantity
            conn.execute(
                "UPDATE store_orders SET picked=%s WHERE run_id=%s AND order_id=%s",
                (Jsonb(picked), run, order["order_id"]),
            )
            if picked[sku] == order["lines"][sku]:
                conn.execute(
                    "UPDATE lab_baskets SET status='picked' WHERE run_id=%s AND id=%s",
                    (run, basket),
                )
            movement(
                conn,
                run,
                f"store-pick:{tools.event.id}",
                store,
                sku,
                sim,
                "picked",
                -quantity,
                -quantity,
            )
            result = {"action": "picked", "sku": sku, "quantity": quantity, "slot": slot["slot"]}
        else:
            result = {"action": "replan", "reason": "Pick face no longer has the reserved units"}
    elif name == "fulfillment.pack" and task["action"] == "pack":
        if order["picked"] != order["lines"]:
            raise ValueError("Cannot pack an incomplete basket")
        conn.execute(
            "UPDATE store_orders SET packed_sim=%s,stage='to_dock' WHERE run_id=%s AND order_id=%s",
            (sim, run, order["order_id"]),
        )
        result = {"action": "packed"}
    elif name == "fulfillment.handoff" and task["action"] in {"dock", "recover"}:
        if task["action"] == "recover":
            conn.execute(
                "UPDATE store_orders SET worker=%s WHERE run_id=%s AND order_id=%s",
                (worker["id"], run, order["order_id"]),
            )
            result = {"action": "recovered", "worker": worker["id"]}
        else:
            if order["packed_sim"] is None:
                raise ValueError("Cannot hand off unpacked goods")
            conn.execute(
                "UPDATE store_orders SET stage='dock',dock_sim=%s WHERE run_id=%s AND order_id=%s",
                (sim, run, order["order_id"]),
            )
            conn.execute(
                "UPDATE orders SET ready_sim=%s WHERE run_id=%s AND id=%s",
                (sim, run, order["order_id"]),
            )
            result = {"action": "dock_ready"}
    elif name == "fulfillment.restock" and task["action"] == "restock":
        moved = conn.execute(
            "UPDATE store_shelves SET quantity=quantity-%s WHERE run_id=%s "
            "AND store=%s AND slot=%s AND quantity>=%s RETURNING sku",
            (task["quantity"], run, store, "backstock:" + task["sku"], task["quantity"]),
        ).fetchone()
        if moved is None:
            raise ValueError("Restock truck has not supplied these units")
        conn.execute(
            "UPDATE store_shelves SET quantity=quantity+%s WHERE run_id=%s "
            "AND store=%s AND slot=%s",
            (task["quantity"], run, store, task["slot"]),
        )
        result = {"action": "restocked", "slot": task["slot"], "quantity": task["quantity"]}
    else:
        raise PermissionError("Tool does not match the physical task")
    conn.execute(
        "UPDATE store_workers SET node=%s,route=NULL,task=NULL WHERE run_id=%s "
        "AND store=%s AND id=%s",
        (worker["route"]["nodes"][-1], run, store, worker["id"]),
    )
    return result

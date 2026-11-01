"""Dark-store physics. Movement and availability, with no recovery decisions."""

from typing import Any

from psycopg.types.json import Jsonb

from delivery.db import Connection
from delivery.environment import RunEnvironment
from delivery.queue import publish
from delivery.store_conditions import conditions
from delivery.telemetry import trace_span


def worker_position(worker: dict[str, Any], layout: dict[str, Any], sim: int) -> list[float]:
    route = worker.get("route")
    if not route:
        return list(layout["nodes"][worker["node"]])
    points = route["points"]
    for left, right in zip(points, points[1:], strict=False):
        if sim <= right[2]:
            ratio = max(0, min(1, (sim - left[2]) / max(0.001, right[2] - left[2])))
            return [left[i] + ratio * (right[i] - left[i]) for i in (0, 1)]
    return list(points[-1][:2])


class DarkStore(RunEnvironment):
    name = "dark_store"

    def read(self, conn: Connection, run: str) -> dict[str, Any]:
        sim = self.clock(conn, run)
        stores = list(
            conn.execute(
                "SELECT e.store,e.layout,e.catalogue,l.name,l.district,ST_X(l.point) lon,"
                "ST_Y(l.point) lat FROM store_environments e JOIN locations l ON l.id=e.store "
                "WHERE e.run_id=%s ORDER BY e.store",
                (run,),
            )
        )
        for store in stores:
            key, layout = store["store"], store["layout"]
            store["conditions"] = conditions(conn, run, key, layout)
            store["stock"] = list(
                conn.execute(
                    "SELECT sku,on_hand,reserved,on_hand-reserved "
                    "available FROM lab_stock WHERE run_id=%s "
                    "AND store=%s ORDER BY sku",
                    (run, key),
                )
            )
            store["shelves"] = list(
                conn.execute(
                    "SELECT slot,sku,quantity FROM store_shelves "
                    "WHERE run_id=%s AND store=%s ORDER BY slot",
                    (run, key),
                )
            )
            store["workers"] = list(
                conn.execute(
                    "SELECT id,kind,node,route,task,available,revision "
                    "FROM store_workers WHERE run_id=%s AND store=%s "
                    "ORDER BY id",
                    (run, key),
                )
            )
            for worker in store["workers"]:
                worker["position"] = worker_position(worker, layout, sim)
            store["orders"] = list(
                conn.execute(
                    "SELECT s.order_id,s.stage,s.lines,s.picked,s.worker,s.revision,s.packed_sim,"
                    "s.dock_sim,o.status,o.courier,o.due_sim,o.delivered_sim,o.route "
                    "FROM store_orders s JOIN orders o ON o.run_id=s.run_id AND o.id=s.order_id "
                    "WHERE s.run_id=%s AND s.store=%s ORDER BY o.created_sim,s.order_id",
                    (run, key),
                )
            )
            store["load"] = sum(
                o["stage"] not in {"handed_off", "cancelled"} for o in store["orders"]
            )
        return {"environment": self.name, "sim_time": sim, "stores": stores}

    def advance(self, conn: Connection, run: str, sim: int) -> dict[str, Any]:
        if self.clock(conn, run) != sim:
            raise ValueError("Store and city must use the same clock")
        environments = list(
            conn.execute(
                "SELECT * FROM store_environments WHERE run_id=%s ORDER BY store FOR UPDATE", (run,)
            )
        )
        for environment in environments:
            if environment["last_sim"] >= sim:
                continue
            store, layout = environment["store"], environment["layout"]
            state = conditions(conn, run, store, layout)
            conn.execute(
                "UPDATE store_workers SET available=NOT(id=ANY(%s)) WHERE run_id=%s AND store=%s",
                (state["broken"], run, store),
            )
            workers = list(
                conn.execute(
                    "SELECT * FROM store_workers WHERE run_id=%s "
                    "AND store=%s ORDER BY id FOR UPDATE",
                    (run, store),
                )
            )
            for worker in workers:
                if not worker["route"]:
                    continue
                route, task = worker["route"], worker["task"]
                remaining = [
                    n
                    for n, p in zip(route["nodes"], route["points"], strict=True)
                    if p[2] > environment["last_sim"]
                ]
                interrupted = not worker["available"] or set(remaining).intersection(
                    state["blocked"]
                )
                if interrupted:
                    # Stop at the last safe grid node. A new route is an agent decision.
                    location = worker["node"]
                    for node, point in zip(route["nodes"], route["points"], strict=True):
                        if point[2] > sim or (
                            point[2] > environment["last_sim"] and node in state["blocked"]
                        ):
                            break
                        location = node
                    conn.execute(
                        "UPDATE store_workers SET node=%s,route=NULL,task=NULL "
                        "WHERE run_id=%s AND store=%s AND id=%s",
                        (location, run, store, worker["id"]),
                    )
                elif route["end_sim"] <= sim:
                    publish(
                        conn,
                        run_id=run,
                        producer="store_world",
                        topic="store.worker.arrived",
                        payload={"order_id": task["order_id"], "worker": worker["id"]},
                        key=f"{store}:{worker['id']}:{worker['revision']}",
                        trace_id=task["order_id"],
                        due_sim=sim,
                        target_store=store,
                    )
            # Only physically arrived supply creates an inventory-agent receipt event.
            shipments = conn.execute(
                "SELECT * FROM lab_shipments WHERE run_id=%s AND store=%s "
                "AND status!='received' AND expected_sim<=%s ORDER BY id",
                (run, store, sim),
            ).fetchall()
            for shipment in shipments:
                publish(
                    conn,
                    run_id=run,
                    producer="store_world",
                    topic="store.restock.arrived",
                    payload={"order_id": "_stock", "shipment": shipment["id"]},
                    key=shipment["id"],
                    trace_id=shipment["id"],
                    due_sim=sim,
                    target_store=store,
                )
            orders = conn.execute(
                "SELECT s.order_id,s.stage,o.status FROM store_orders s JOIN orders o "
                "ON o.run_id=s.run_id AND o.id=s.order_id WHERE s.run_id=%s "
                "AND s.store=%s AND s.stage NOT IN ('cancelled','handed_off') "
                "ORDER BY s.order_id",
                (run, store),
            ).fetchall()
            for order in orders:
                if order["status"] in {"picked_up", "delivered"}:
                    conn.execute(
                        "UPDATE store_orders SET stage='handed_off' WHERE run_id=%s "
                        "AND order_id=%s",
                        (run, order["order_id"]),
                    )
                    publish(
                        conn,
                        run_id=run,
                        producer="store_world",
                        topic="store.courier.collected",
                        payload={"order_id": order["order_id"]},
                        key=order["order_id"],
                        trace_id=order["order_id"],
                        due_sim=sim,
                        target_store=store,
                    )
                elif order["status"] == "unserved":
                    from delivery.store_agents import cancel_order

                    stored = conn.execute(
                        "SELECT * FROM store_orders WHERE run_id=%s AND order_id=%s",
                        (run, order["order_id"]),
                    ).fetchone()
                    assert stored
                    cancel_order(conn, run, stored, sim)
                else:
                    busy = conn.execute(
                        "SELECT 1 FROM store_workers WHERE run_id=%s "
                        "AND store=%s AND task->>'order_id'=%s AND available",
                        (run, store, order["order_id"]),
                    ).fetchone()
                    # An unfinished route needs no policy turn on every physical tick.
                    if not busy and order["stage"] != "dock" and (sim % 60 == 0 or sim < 600):
                        self.wake(conn, run, store, order["order_id"], sim)
            forklift = conn.execute(
                "SELECT task FROM store_workers WHERE run_id=%s AND store=%s AND kind='forklift'",
                (run, store),
            ).fetchone()
            backstock = conn.execute(
                "SELECT 1 FROM store_shelves WHERE run_id=%s AND store=%s "
                "AND slot LIKE 'backstock:%%' AND quantity>0",
                (run, store),
            ).fetchone()
            if backstock and forklift and not forklift["task"] and sim % 60 == 0:
                self.wake(conn, run, store, "_stock", sim)
            conn.execute(
                "UPDATE store_environments SET last_sim=%s WHERE run_id=%s AND store=%s",
                (sim, run, store),
            )
        with trace_span(
            "environment.advance",
            attributes={"delivery.environment": self.name, "delivery.sim_time": sim},
        ):
            pass
        return {"environment": self.name, "sim_time": sim, "stores": len(environments)}

    @staticmethod
    def wake(conn: Connection, run: str, store: str, order: str, sim: int) -> None:
        publish(
            conn,
            run_id=run,
            producer="store_world",
            topic="store.replan",
            payload={"order_id": order},
            key=f"{store}:{order}:{sim}",
            trace_id=order,
            due_sim=sim,
            target_store=store,
        )

    def record(self, conn: Connection, run: str) -> None:
        state = self.read(conn, run)
        for store in state["stores"]:
            store.pop("layout")
            store.pop("catalogue")
            for order in store["orders"]:
                order.pop("route")
        conn.execute(
            "INSERT INTO store_frames(run_id,sim,state) VALUES (%s,%s,%s) "
            "ON CONFLICT(run_id,sim) DO NOTHING",
            (run, state["sim_time"], Jsonb(state)),
        )

"""Rule-based dispatcher/couriers; agents exchange only durable queue events."""

from typing import Any

from psycopg.types.json import Jsonb

from delivery.customer_service import Advice, refund_policy
from delivery.db import Connection
from delivery.queue import Event, publish
from delivery.world import COST_PER_KM, ENERGY_PER_KM, World, position, trace


class Dispatcher:
    def __init__(self, world: World) -> None:
        self.world = world

    def handle(self, conn: Connection, event: Event) -> None:
        row = conn.execute("SELECT sim_time FROM runs WHERE id=%s", (event.run_id,)).fetchone()
        assert row
        sim = row["sim_time"]
        pending = conn.execute(
            """SELECT o.*, s.node AS store_node, c.node AS customer_node
               FROM orders o JOIN locations s ON s.id=o.store JOIN locations c ON c.id=o.customer
               WHERE o.run_id=%s AND o.status='pending' ORDER BY o.due_sim,o.id
               FOR UPDATE OF o SKIP LOCKED LIMIT 100""",
            (event.run_id,),
        ).fetchall()
        for order in pending:
            couriers = conn.execute(
                """SELECT * FROM couriers WHERE run_id=%s AND status='idle'
                   AND energy>10 AND shift_end>%s ORDER BY id FOR UPDATE SKIP LOCKED""",
                (event.run_id, sim),
            ).fetchall()
            if not couriers:
                break
            ranked: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
            for courier in couriers:
                route = self.world.route(
                    courier["node"],
                    order["store_node"],
                    order["customer_node"],
                    courier["mode"],
                    sim,
                    order["ready_sim"],
                )
                required = route["distance_m"] / 1000 * ENERGY_PER_KM[courier["mode"]]
                if courier["energy"] - required >= 5 and route["end_at"] <= courier["shift_end"]:
                    ranked.append((route["end_at"], courier["id"], courier, route))
            if not ranked:
                continue
            _, _, courier, route = min(ranked, key=lambda item: (item[0], item[1]))
            cost = 1.0 + route["distance_m"] / 1000 * COST_PER_KM[courier["mode"]]
            changed = conn.execute(
                """UPDATE orders SET status='assigned',courier=%s,assigned_sim=%s,route=%s,
                   route_m=%s,cost_eur=%s,version=version+1
                   WHERE run_id=%s AND id=%s AND status='pending' RETURNING id""",
                (
                    courier["id"],
                    sim,
                    Jsonb(route),
                    route["distance_m"],
                    cost,
                    event.run_id,
                    order["id"],
                ),
            ).fetchone()
            if not changed:
                continue
            conn.execute(
                "UPDATE couriers SET status='reserved' WHERE run_id=%s AND id=%s",
                (event.run_id, courier["id"]),
            )
            publish(
                conn,
                run_id=event.run_id,
                producer="dispatcher",
                topic="courier.assigned",
                payload={"order_id": order["id"], "courier_id": courier["id"]},
                key=f"assignment:{order['id']}",
                trace_id=order["id"],
                parent_id=event.id,
                due_sim=sim,
                priority=5,
            )
            trace(
                conn,
                str(event.run_id),
                sim,
                "dispatcher",
                "assigned",
                {
                    "rule": "earliest road-route completion within energy and shift limits",
                    "eligible_couriers": len(ranked),
                    "eta_sim": route["end_at"],
                    "distance_m": round(route["distance_m"]),
                    "version": order["version"] + 1,
                },
                order["id"],
                courier["id"],
                event.id,
            )


class Courier:
    def handle(self, conn: Connection, event: Event) -> None:
        courier = event.payload["courier_id"]
        conn.execute(
            "UPDATE couriers SET status='to_pickup' WHERE run_id=%s AND id=%s "
            "AND status='reserved'",
            (event.run_id, courier),
        )
        trace(
            conn,
            str(event.run_id),
            event.due_sim,
            "courier",
            "accepted_route",
            {"rule": "follow approved road route; wait for preparation before pickup"},
            event.payload["order_id"],
            courier,
            event.id,
        )

    def advance(self, conn: Connection, run: str, sim: int) -> None:
        orders = conn.execute(
            """SELECT o.*, c.mode, c.status AS courier_status FROM orders o JOIN couriers c
               ON c.run_id=o.run_id AND c.id=o.courier
               WHERE o.run_id=%s AND o.status IN ('assigned','picked_up')
               AND c.status IN ('to_pickup','delivering') FOR UPDATE OF o,c""",
            (run,),
        ).fetchall()
        for order in orders:
            route = order["route"]
            assignment = conn.execute(
                "SELECT id FROM events WHERE run_id=%s AND topic='courier.assigned' "
                "AND trace_id=%s",
                (run, order["id"]),
            ).fetchone()
            parent_id = assignment["id"] if assignment else None
            x, y = position(route, sim)
            conn.execute(
                "UPDATE couriers SET point=ST_SetSRID(ST_MakePoint(%s,%s),4326) "
                "WHERE run_id=%s AND id=%s",
                (x, y, run, order["courier"]),
            )
            if sim >= route["pickup_at"] and order["status"] == "assigned":
                conn.execute(
                    "UPDATE orders SET status='picked_up',version=version+1 "
                    "WHERE run_id=%s AND id=%s",
                    (run, order["id"]),
                )
                conn.execute(
                    "UPDATE couriers SET status='delivering' WHERE run_id=%s AND id=%s",
                    (run, order["courier"]),
                )
                trace(
                    conn,
                    run,
                    sim,
                    "courier",
                    "picked_up",
                    {"store": order["store"]},
                    order["id"],
                    order["courier"],
                )
            if sim >= route["end_at"]:
                consumption = route["distance_m"] / 1000 * ENERGY_PER_KM[order["mode"]]
                conn.execute(
                    "UPDATE orders SET status='delivered',delivered_sim=%s,"
                    "version=version+1 WHERE run_id=%s AND id=%s",
                    (route["end_at"], run, order["id"]),
                )
                conn.execute(
                    """UPDATE couriers SET status='idle',node=%s,energy=energy-%s,
                       distance_m=distance_m+%s WHERE run_id=%s AND id=%s""",
                    (route["destination"], consumption, route["distance_m"], run, order["courier"]),
                )
                for topic in ("order.delivered", "courier.available"):
                    publish(
                        conn,
                        run_id=run,
                        producer="courier",
                        topic=topic,
                        payload={"order_id": order["id"], "courier_id": order["courier"]},
                        key=f"{topic}:{order['id']}",
                        trace_id=order["id"],
                        due_sim=sim,
                        parent_id=parent_id,
                    )
                trace(
                    conn,
                    run,
                    sim,
                    "courier",
                    "delivered",
                    {
                        "on_time": route["end_at"] <= order["due_sim"],
                        "energy_used": round(consumption, 2),
                    },
                    order["id"],
                    order["courier"],
                )
        conn.execute(
            "UPDATE couriers SET status='off_shift' WHERE run_id=%s "
            "AND status='idle' AND shift_end<=%s",
            (run, sim),
        )


def resolve_complaint(conn: Connection, event: Event, advice: Advice, source: str) -> None:
    row = conn.execute(
        """SELECT c.*,o.due_sim,r.sim_time FROM complaints c
           JOIN orders o ON o.run_id=c.run_id AND o.id=c.order_id JOIN runs r ON r.id=c.run_id
           WHERE c.run_id=%s AND c.id=%s FOR UPDATE OF c""",
        (event.run_id, event.payload["complaint_id"]),
    ).fetchone()
    if not row or row["status"] != "open":
        return
    status, refund = refund_policy(row["requested_refund_eur"], row["sim_time"] > row["due_sim"])
    if source != "llm" or advice.category == "escalate":
        status, refund = "awaiting_approval", 0
    conn.execute(
        """UPDATE complaints SET status=%s,response=%s,source=%s,approved_refund_eur=%s
           WHERE run_id=%s AND id=%s""",
        (status, advice.reply, source, refund, event.run_id, row["id"]),
    )
    topic = "approval.requested" if status == "awaiting_approval" else "complaint.resolved"
    publish(
        conn,
        run_id=event.run_id,
        producer="customer_service",
        topic=topic,
        payload={"complaint_id": row["id"], "refund_eur": refund},
        key=row["id"],
        trace_id=row["order_id"],
        parent_id=event.id,
        due_sim=row["sim_time"],
        priority=10,
    )
    trace(
        conn,
        str(event.run_id),
        row["sim_time"],
        "customer_service",
        status,
        {
            "source": source,
            "category": advice.category,
            "reply": advice.reply,
            "approved_refund_eur": refund,
            "policy": "over EUR 100 requires manager approval",
        },
        row["order_id"],
        event=event.id,
    )

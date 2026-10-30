"""Rule-based dispatcher/couriers; agents exchange only durable queue events."""

from typing import Any

import networkx as nx
from psycopg.types.json import Jsonb

from delivery.customer_service import Advice, refund_policy
from delivery.db import Connection
from delivery.dispatch_optimizer import Candidate, optimize_dispatch
from delivery.dispatch_policy import (
    assignment_score,
    fair_ranks,
    load_policy,
    operating_cost,
    prioritize_deadlines,
)
from delivery.queue import Event, publish
from delivery.world import ENERGY_PER_KM, World, depart_at, position, route_progress, trace


class Dispatcher:
    def __init__(self, world: World) -> None:
        self.world = world

    def handle(self, conn: Connection, event: Event) -> None:
        row = conn.execute("SELECT * FROM runs WHERE id=%s", (event.run_id,)).fetchone()
        assert row
        sim = row["sim_time"]
        policy = load_policy(row["dispatch_config"])
        pending = conn.execute(
            """SELECT o.*, coalesce(o.recovery_node,s.node) AS store_node, c.node AS customer_node,
               s.district AS store_district,c.district AS customer_district
               FROM orders o JOIN locations s ON s.id=o.store JOIN locations c ON c.id=o.customer
               WHERE o.run_id=%s AND o.status='pending' ORDER BY o.due_sim,o.id
               FOR UPDATE OF o SKIP LOCKED LIMIT 100""",
            (event.run_id,),
        ).fetchall()
        couriers = conn.execute(
            """SELECT * FROM couriers WHERE run_id=%s AND status='idle'
               AND energy>10 AND shift_end>%s ORDER BY idle_since_sim,completed_jobs,id
               FOR UPDATE SKIP LOCKED LIMIT 100""",
            (event.run_id, sim),
        ).fetchall()
        routes: dict[tuple[str, str], dict[str, Any]] = {}
        from delivery.chaos import active_events, retime, traffic_factor

        disruptions = (
            active_events(conn, str(event.run_id)) if row["chaos_config"] is not None else []
        )
        scores: dict[tuple[str, str], dict[str, float]] = {}
        candidates = []
        ranks = fair_ranks(couriers, f"{row['seed']}:{sim}")
        for order in pending:
            for courier in couriers:
                try:
                    route = self.world.route(
                        courier["node"],
                        order["store_node"],
                        order["customer_node"],
                        courier["mode"],
                        sim,
                        order["ready_sim"],
                    )
                    if disruptions:
                        route = retime(route, sim, traffic_factor(disruptions, order))
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    continue
                required = route["distance_m"] / 1000 * ENERGY_PER_KM[courier["mode"]]
                if courier["energy"] - required >= 5 and route["end_at"] <= courier["shift_end"]:
                    pair = order["id"], courier["id"]
                    routes[pair] = route
                    score = assignment_score(route, courier["mode"], sim, order["due_sim"], policy)
                    scores[pair] = score
                    candidates.append(
                        Candidate(*pair, round(score["total"] * 1000), ranks[courier["id"]])
                    )
        if policy.strategy == "legacy":
            # A frozen reference for same-demand A/B evaluations.
            selected = []
            used: set[str] = set()
            for order in pending:
                options = [
                    c for c in candidates if c.order_id == order["id"] and c.courier_id not in used
                ]
                if options:
                    chosen = min(
                        options,
                        key=lambda c: (routes[c.order_id, c.courier_id]["end_at"], c.courier_id),
                    )
                    selected.append(chosen)
                    used.add(chosen.courier_id)
        else:
            selected = list(
                optimize_dispatch(
                    prioritize_deadlines(
                        candidates,
                        [o["id"] for o in pending],
                    )
                )
            )
        orders_by_id = {o["id"]: o for o in pending}
        couriers_by_id = {c["id"]: c for c in couriers}
        for chosen in selected:
            order, courier = orders_by_id[chosen.order_id], couriers_by_id[chosen.courier_id]
            route = routes[chosen.order_id, chosen.courier_id]
            cost = operating_cost(route["distance_m"], courier["mode"], job=True)
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
                "UPDATE couriers SET status='reserved',leg_accounted_m=0,leg_empty_accounted_m=0 "
                "WHERE run_id=%s AND id=%s",
                (event.run_id, courier["id"]),
            )
            publish(
                conn,
                run_id=event.run_id,
                producer="dispatcher",
                topic="courier.assigned",
                payload={"order_id": order["id"], "courier_id": courier["id"]},
                key=f"assignment:{order['id']}:{order['version'] + 1}",
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
                    "rule": policy.strategy,
                    "objective": (
                        "max served; earliest deadlines; min cost; longest idle/fewer jobs"
                        if policy.strategy == "min_cost"
                        else "earliest completion, then courier ID"
                    ),
                    "eligible_couriers": sum(c.order_id == order["id"] for c in candidates),
                    "batch_orders": len(pending),
                    "batch_couriers": len(couriers),
                    "score": scores[chosen.order_id, chosen.courier_id],
                    "alternatives": [
                        {
                            "courier": c.courier_id,
                            "score": scores[c.order_id, c.courier_id],
                            "pickup_m": round(
                                routes[c.order_id, c.courier_id]["pickup_distance_m"]
                            ),
                            "fair_rank": c.tie_break_rank,
                        }
                        for c in sorted(
                            (c for c in candidates if c.order_id == order["id"]),
                            key=lambda c: (c.cost, c.tie_break_rank),
                        )[:5]
                    ],
                    "start_node": courier["node"],
                    "pickup_distance_m": round(route["pickup_distance_m"]),
                    "operating_cost_eur": round(cost, 4),
                    "eta_sim": route["end_at"],
                    "distance_m": round(route["distance_m"]),
                    "version": order["version"] + 1,
                },
                order["id"],
                courier["id"],
                event.id,
            )
        if policy.reposition == "demand_aware" and not pending:
            from delivery.dispatch_reposition import reposition_idle

            reposition_idle(conn, event, self.world, row, policy)


class Courier:
    def handle(self, conn: Connection, event: Event) -> None:
        courier = event.payload["courier_id"]
        if event.topic == "courier.reposition":
            row = conn.execute(
                "SELECT c.*,r.sim_time,r.duration FROM couriers c JOIN runs r ON r.id=c.run_id "
                "WHERE c.run_id=%s AND c.id=%s AND c.status='reposition_reserved' FOR UPDATE OF c",
                (event.run_id, courier),
            ).fetchone()
            if not row:
                return
            delay = max(0, row["sim_time"] - row["reposition_route"]["start_at"])
            route = depart_at(row["reposition_route"], row["sim_time"])
            if route["end_at"] + 600 > min(row["duration"], row["shift_end"]):
                conn.execute(
                    "UPDATE couriers SET status='idle',reposition_route=NULL "
                    "WHERE run_id=%s AND id=%s",
                    (event.run_id, courier),
                )
                publish(
                    conn,
                    run_id=event.run_id,
                    producer="courier",
                    topic="courier.available",
                    payload={"courier_id": courier},
                    key=f"reposition-cancelled:{event.id}",
                    trace_id=event.trace_id,
                    parent_id=event.id,
                    due_sim=row["sim_time"],
                )
                trace(
                    conn,
                    str(event.run_id),
                    row["sim_time"],
                    "courier",
                    "reposition_cancelled",
                    {"reason": "delayed handoff exceeds shift/run horizon", "distance_m": 0},
                    courier=courier,
                    event=event.id,
                )
                return
            conn.execute(
                "UPDATE couriers SET status='repositioning',reposition_route=%s "
                "WHERE run_id=%s AND id=%s",
                (Jsonb(route), event.run_id, courier),
            )
            trace(
                conn,
                str(event.run_id),
                row["sim_time"],
                "courier",
                "reposition_accepted",
                {"queue_delay_seconds": delay, "departure_sim": route["start_at"]},
                courier=courier,
                event=event.id,
            )
            return
        order = conn.execute(
            """SELECT o.*,r.sim_time,r.duration,c.shift_end FROM orders o
               JOIN runs r ON r.id=o.run_id
               JOIN couriers c ON c.run_id=o.run_id AND c.id=o.courier
               WHERE o.run_id=%s AND o.id=%s AND o.courier=%s AND o.status='assigned'
               AND c.status='reserved' FOR UPDATE OF o,c""",
            (event.run_id, event.payload["order_id"], courier),
        ).fetchone()
        if not order:
            return
        route = depart_at(order["route"], order["sim_time"], order["ready_sim"])
        if route["end_at"] > min(order["duration"], order["shift_end"]):
            conn.execute(
                "UPDATE orders SET status='pending',courier=NULL,assigned_sim=NULL,route=NULL,"
                "route_m=0,cost_eur=0,version=version+1 WHERE run_id=%s AND id=%s",
                (event.run_id, order["id"]),
            )
            conn.execute(
                "UPDATE couriers SET status='idle' WHERE run_id=%s AND id=%s",
                (event.run_id, courier),
            )
            publish(
                conn,
                run_id=event.run_id,
                producer="courier",
                topic="courier.available",
                payload={"courier_id": courier, "order_id": order["id"]},
                key=f"assignment-cancelled:{event.id}",
                trace_id=event.trace_id,
                parent_id=event.id,
                due_sim=order["sim_time"],
            )
            trace(
                conn,
                str(event.run_id),
                order["sim_time"],
                "courier",
                "assignment_cancelled",
                {"reason": "delayed handoff exceeds shift/run horizon", "distance_m": 0},
                order["id"],
                courier,
                event.id,
            )
            return
        conn.execute(
            "UPDATE orders SET route=%s WHERE run_id=%s AND id=%s",
            (Jsonb(route), event.run_id, order["id"]),
        )
        conn.execute(
            "UPDATE couriers SET status='to_pickup' WHERE run_id=%s AND id=%s",
            (event.run_id, courier),
        )
        trace(
            conn,
            str(event.run_id),
            order["sim_time"],
            "courier",
            "accepted_route",
            {
                "rule": "follow approved road route; depart after acceptance; wait for preparation",
                "departure_sim": route.get("start_at", route["points"][0][2]),
            },
            event.payload["order_id"],
            courier,
            event.id,
        )

    def advance(self, conn: Connection, run: str, sim: int) -> None:
        relocating = conn.execute(
            "SELECT * FROM couriers WHERE run_id=%s AND status='repositioning' FOR UPDATE",
            (run,),
        ).fetchall()
        for courier in relocating:
            route = courier["reposition_route"]
            self._travel(conn, run, courier["id"], courier["mode"], route, sim, reposition=True)
            if sim >= route["end_at"]:
                conn.execute(
                    "UPDATE couriers SET status='idle',node=%s,reposition_route=NULL,"
                    "idle_since_sim=%s "
                    "WHERE run_id=%s AND id=%s",
                    (route["destination"], sim, run, courier["id"]),
                )
                publish(
                    conn,
                    run_id=run,
                    producer="courier",
                    topic="courier.available",
                    payload={"courier_id": courier["id"]},
                    key=f"relocated:{courier['id']}:{route['start_at']}",
                    trace_id=f"reposition:{courier['id']}:{route['start_at']}",
                    due_sim=sim,
                )
                trace(
                    conn,
                    run,
                    sim,
                    "courier",
                    "repositioned",
                    {"destination": route["destination"], "distance_m": route["distance_m"]},
                    courier=courier["id"],
                )
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
                "AND trace_id=%s ORDER BY id DESC LIMIT 1",
                (run, order["id"]),
            ).fetchone()
            parent_id = assignment["id"] if assignment else None
            self._travel(conn, run, order["courier"], order["mode"], route, sim)
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
                    """UPDATE couriers SET status='idle',node=%s,idle_since_sim=%s,
                       completed_jobs=completed_jobs+1,operating_cost_eur=operating_cost_eur+1
                       WHERE run_id=%s AND id=%s""",
                    (route["destination"], sim, run, order["courier"]),
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

    @staticmethod
    def _travel(
        conn: Connection,
        run: str,
        courier: str,
        mode: str,
        route: dict[str, Any],
        sim: int,
        *,
        reposition: bool = False,
    ) -> None:
        total, empty = route_progress(route, sim)
        x, y = position(route, sim)
        # Stored cumulative leg progress makes repeated ticks/restarts idempotent.
        conn.execute(
            """UPDATE couriers SET point=ST_SetSRID(ST_MakePoint(%s,%s),4326),
               energy=greatest(0,energy-greatest(0,%s-leg_accounted_m)*%s/1000),
               distance_m=distance_m+greatest(0,%s-leg_accounted_m),
               empty_distance_m=empty_distance_m+greatest(0,%s-leg_empty_accounted_m),
               reposition_distance_m=reposition_distance_m+CASE WHEN %s
                 THEN greatest(0,%s-leg_accounted_m) ELSE 0 END,
               operating_cost_eur=operating_cost_eur+greatest(0,%s-leg_accounted_m)*%s/1000,
               leg_accounted_m=greatest(leg_accounted_m,%s),
               leg_empty_accounted_m=greatest(leg_empty_accounted_m,%s)
               WHERE run_id=%s AND id=%s""",
            (
                x,
                y,
                total,
                ENERGY_PER_KM[mode],
                total,
                empty,
                reposition,
                total,
                total,
                operating_cost(1000, mode),
                total,
                empty,
                run,
                courier,
            ),
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

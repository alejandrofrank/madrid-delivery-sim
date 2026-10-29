"""Conservative observed-demand relocation, with queue handoff and real travel.

This is a transparent heuristic, not a learned demand forecast. No future orders
are read. A move must improve fleet-wide pickup coverage enough to pay for itself.
"""

from typing import Any

import networkx as nx
from psycopg.types.json import Jsonb

from delivery.db import Connection
from delivery.dispatch_policy import DispatchPolicy, operating_cost
from delivery.queue import Event, publish
from delivery.world import ENERGY_PER_KM, SPEED_MPS, World, trace


def relocation_choice(
    world: World,
    courier: dict[str, Any],
    fleet: list[dict[str, Any]],
    demand: list[dict[str, Any]],
    sim: int,
    duration: int,
    policy: DispatchPolicy,
) -> tuple[dict[str, Any], float] | None:
    if sim - courier["last_reposition_sim"] < policy.reposition_cooldown_seconds:
        return None
    if not demand:
        return None

    def pickup_seconds(node: int, store: int, mode: str) -> float:
        try:
            return world.path(node, store)[1] / SPEED_MPS[mode]
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return 7200.0

    def coverage(moved_to: int | None = None) -> float:
        # Expected next 15 minutes, bounded to three orders per observed store.
        return sum(
            min(3.0, d["orders"] * 900 / policy.demand_window_seconds)
            * min(
                pickup_seconds(
                    moved_to if c["id"] == courier["id"] and moved_to is not None else c["node"],
                    d["node"],
                    c["mode"],
                )
                for c in fleet
            )
            for d in demand
        )

    before = coverage()
    best: tuple[dict[str, Any], float] | None = None
    for store in sorted(demand, key=lambda d: d["store"]):
        if store["orders"] < 2 or store["node"] == courier["node"]:
            continue
        try:
            route = world.relocation(courier["node"], store["node"], courier["mode"], sim)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        if route["distance_m"] > policy.reposition_max_m:
            continue
        if route["end_at"] + 600 > min(duration, courier["shift_end"]):
            continue
        if courier["energy"] - route["distance_m"] / 1000 * ENERGY_PER_KM[courier["mode"]] < 10:
            continue
        expense = (
            route["pickup_travel_seconds"]
            + operating_cost(route["distance_m"], courier["mode"])
            * 3600
            / policy.time_value_eur_per_hour
        )
        saving = before - coverage(store["node"]) - expense
        if saving >= policy.reposition_min_saving_seconds and (best is None or saving > best[1]):
            best = route, saving
    return best


def reposition_idle(
    conn: Connection, event: Event, world: World, run: dict[str, Any], policy: DispatchPolicy
) -> None:
    sim = run["sim_time"]
    demand = conn.execute(
        """SELECT o.store,l.node,count(*) AS orders FROM orders o
           JOIN locations l ON l.id=o.store WHERE o.run_id=%s
           AND o.created_sim BETWEEN %s AND %s GROUP BY o.store,l.node""",
        (event.run_id, max(0, sim - policy.demand_window_seconds), sim),
    ).fetchall()
    idle = conn.execute(
        """SELECT * FROM couriers WHERE run_id=%s AND status='idle' AND energy>10
           AND shift_end>%s ORDER BY idle_since_sim,completed_jobs,id
           FOR UPDATE SKIP LOCKED LIMIT 100""",
        (event.run_id, sim),
    ).fetchall()
    moving = conn.execute(
        "SELECT id,mode,reposition_route FROM couriers WHERE run_id=%s "
        "AND status IN ('repositioning','reposition_reserved')",
        (event.run_id,),
    ).fetchall()
    fleet = [dict(c) for c in idle] + [
        {"id": c["id"], "mode": c["mode"], "node": c["reposition_route"]["destination"]}
        for c in moving
    ]
    # A maximum of two moves per event; reserved destinations cover subsequent choices.
    moves = 0
    for courier in idle:
        choice = relocation_choice(world, courier, fleet, demand, sim, run["duration"], policy)
        if not choice:
            continue
        route, saving = choice
        conn.execute(
            """UPDATE couriers SET status='reposition_reserved',reposition_route=%s,
               last_reposition_sim=%s,leg_accounted_m=0,leg_empty_accounted_m=0
               WHERE run_id=%s AND id=%s""",
            (Jsonb(route), sim, event.run_id, courier["id"]),
        )
        for c in fleet:
            if c["id"] == courier["id"]:
                c["node"] = route["destination"]
        key = f"reposition:{courier['id']}:{sim}"
        publish(
            conn,
            run_id=event.run_id,
            producer="dispatcher",
            topic="courier.reposition",
            payload={"courier_id": courier["id"]},
            key=key,
            trace_id=key,
            parent_id=event.id,
            due_sim=sim,
        )
        trace(
            conn,
            str(event.run_id),
            sim,
            "dispatcher",
            "reposition_requested",
            {
                "rule": "observed coverage benefit exceeds empty-trip expense and hysteresis",
                "history_window_seconds": policy.demand_window_seconds,
                "start_node": courier["node"],
                "destination": route["destination"],
                "distance_m": route["distance_m"],
                "net_saving_seconds": round(saving, 2),
            },
            courier=courier["id"],
            event=event.id,
        )
        moves += 1
        if moves == 2:
            break

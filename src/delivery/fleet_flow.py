"""Seeded multi-basket physical world, traffic and recovery experiment."""

import time
from typing import Any

from psycopg.types.json import Jsonb

from delivery.agent_access import retire_inventory_access, role_access
from delivery.agent_runtime import create_agent
from delivery.db import connect
from delivery.delivery_flow import flow_snapshot
from delivery.queue import Queue, publish


def prepare_fleet(run: str, url: str | None = None) -> None:
    state = flow_snapshot(run, url)
    stores = {s["id"]: s for s in state["city"]["stores"]}
    with connect(url) as conn:
        started = conn.execute(
            "UPDATE runs SET status='running' WHERE id=%s AND status='ready' RETURNING id", (run,)
        ).fetchone()
        if not started:
            raise ValueError("Fleet run must be ready; completed runs are immutable")
        conn.execute("INSERT INTO lab_fleet_scenarios(run_id) VALUES (%s)", (run,))
        for courier, store, status in (
            ("bike-1", "store-1", "active"),
            ("bike-2", "store-2", "active"),
            ("bike-3", "store-10", "active"),
            ("bike-4", "store-1", "offline"),
        ):
            conn.execute(
                "INSERT INTO lab_fleet(run_id,id,node,status) VALUES (%s,%s,%s,%s)",
                (run, courier, stores[store]["node"], status),
            )
        # Every request consumes a scarce unit. The duplicate store-1 request must lose.
        requests = [
            ("delivery-a", "store-1", 6 * 32 + 5, 20000),
            ("delivery-b", "store-2", 12 * 32 + 18, 120),
            ("delivery-c", "store-10", 6 * 32 + 25, 20000),
            ("delivery-d", "store-7", 7 * 32 + 10, 20000),
            ("delivery-e", "store-11", 17 * 32 + 12, 20000),
            ("delivery-f", "store-5", 19 * 32 + 19, 20000),
            ("scarcity-loser", "store-1", 6 * 32 + 6, 20000),
        ]
        for basket, store, customer, deadline in requests:
            sku = next(s["sku"] for s in state["stock"] if s["store"] == store)
            # The ledger begins with one unit of each requested product.
            row = conn.execute(
                """SELECT on_hand FROM lab_stock
                WHERE run_id=%s AND store=%s AND sku=%s""",
                (run, store, sku),
            ).fetchone()
            assert row
            if row["on_hand"] > 1:
                delta = 1 - row["on_hand"]
                conn.execute(
                    """UPDATE lab_stock SET on_hand=1
                    WHERE run_id=%s AND store=%s AND sku=%s""",
                    (run, store, sku),
                )
                conn.execute(
                    """INSERT INTO lab_movements VALUES (%s,%s,%s,%s,0,'low_stock_fixture',%s,0)
                    ON CONFLICT DO NOTHING""",
                    (run, f"scarcity:{store}:{sku}", store, sku, delta),
                )
            conn.execute(
                """INSERT INTO lab_fulfillments(run_id,basket,store,customer_node,deadline_sim)
                VALUES (%s,%s,%s,%s,%s)""",
                (run, basket, store, customer, deadline),
            )
            publish(
                conn,
                run_id=run,
                producer="lab_scenario",
                topic="basket.requested",
                payload={
                    "basket": basket,
                    "store": store,
                    "sku": sku,
                    "quantity": 1,
                    "expires_sim": 10000,
                    "deliver": True,
                },
                key=basket,
                trace_id=basket,
                target_store=store,
            )
        conn.execute(
            """INSERT INTO lab_incidents(run_id,sim_time,kind,detail)
            VALUES (%s,0,'traffic_delay',%s)""",
            (
                run,
                Jsonb(
                    {
                        "factor": 2,
                        "rule": "Seeded congestion doubles road traversal times",
                    }
                ),
            ),
        )


def advance_fleet(
    run: str, sim: int, url: str | None = None, *, dropouts: set[str] | None = None
) -> None:
    with connect(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (run,))
        now = conn.execute("SELECT sim_time FROM runs WHERE id=%s FOR UPDATE", (run,)).fetchone()
        if not now or sim < now["sim_time"]:
            raise ValueError("Simulation time cannot go backwards")
        conn.execute("UPDATE runs SET sim_time=%s WHERE id=%s", (sim, run))
        dropped = conn.execute(
            """SELECT 1 FROM lab_incidents WHERE run_id=%s
            AND kind='courier_dropout' LIMIT 1""",
            (run,),
        ).fetchone()
        dropout = dropouts is None and sim >= 180 and not dropped
        if dropout:
            conn.execute(
                """UPDATE lab_fleet SET status='active'
                WHERE run_id=%s AND id='bike-4'""",
                (run,),
            )
        jobs = conn.execute(
            """SELECT * FROM lab_delivery_jobs WHERE run_id=%s
            AND status IN ('assigned','in_transit') AND accepted FOR UPDATE""",
            (run,),
        ).fetchall()
        for job in jobs:
            elapsed = sim - job["depart_sim"]
            node = job["route"][0]
            for target, seconds in zip(job["route"][1:], job["route_durations"], strict=True):
                elapsed -= seconds
                if elapsed < 0:
                    break
                node = target
            pickup_reached = sim >= job["pickup_sim"]
            collected = job["collected"] or pickup_reached
            parcel = (
                node
                if pickup_reached
                else (job["parcel_node"] if job["parcel_node"] is not None else job["pickup_node"])
            )
            parent = conn.execute(
                """SELECT id FROM events WHERE run_id=%s AND topic='delivery.assigned'
                AND trace_id=%s AND (payload->>'attempt')::integer=%s""",
                (run, job["basket"], job["attempt"]),
            ).fetchone()
            assert parent
            conn.execute(
                "UPDATE lab_fleet SET node=%s WHERE run_id=%s AND id=%s",
                (node, run, job["courier"]),
            )
            if pickup_reached and job["status"] == "assigned":
                brief = conn.execute(
                    "SELECT body FROM lab_briefs WHERE run_id=%s AND basket=%s AND attempt=%s",
                    (run, job["basket"], job["attempt"]),
                ).fetchone()
                assert brief
                conn.execute(
                    """INSERT INTO lab_incidents(run_id,sim_time,kind,basket,courier,detail)
                    VALUES (%s,%s,'courier_collection',%s,%s,%s)""",
                    (
                        run,
                        job["pickup_sim"],
                        job["basket"],
                        job["courier"],
                        Jsonb(
                            {
                                "checkpoint": brief["body"]["custody_checkpoint"]["node"],
                                "attempt": job["attempt"],
                                "observed_sim": sim,
                            }
                        ),
                    ),
                )
            failed = (
                job["courier"] in dropouts
                if dropouts is not None
                else dropout and job["courier"] in {"bike-1", "bike-2"}
            ) and sim < job["arrive_sim"]
            status = (
                "awaiting_review"
                if failed
                else "arrived"
                if sim >= job["arrive_sim"]
                else "in_transit"
                if pickup_reached
                else "assigned"
            )
            conn.execute(
                """UPDATE lab_delivery_jobs SET status=%s,parcel_node=%s,collected=%s
                WHERE run_id=%s AND basket=%s""",
                (status, parcel, collected, run, job["basket"]),
            )
            conn.execute(
                """UPDATE lab_delivery_attempts SET status=%s,last_node=%s
                WHERE run_id=%s AND basket=%s AND attempt=%s""",
                ("failed" if failed else status, node, run, job["basket"], job["attempt"]),
            )
            if failed:
                # Parcel remains physically held at the last reached node for collection.
                conn.execute(
                    """UPDATE lab_fleet SET status='offline',busy_basket=NULL
                    WHERE run_id=%s AND id=%s""",
                    (run, job["courier"]),
                )
                conn.execute(
                    """INSERT INTO lab_incidents(run_id,sim_time,kind,basket,courier,detail)
                    VALUES (%s,%s,'courier_dropout',%s,%s,%s)""",
                    (
                        run,
                        sim,
                        job["basket"],
                        job["courier"],
                        Jsonb(
                            {
                                "source_event": parent["id"],
                                "checkpoint": parcel,
                                "attempt": job["attempt"],
                                "reason": "Mechanical failure; parcel secured at checkpoint",
                            }
                        ),
                    ),
                )
                topic, target = "delivery.failed", "judge:fleet"
            elif status == "arrived":
                conn.execute(
                    """INSERT INTO lab_incidents(run_id,sim_time,kind,basket,courier,detail)
                    VALUES (%s,%s,'courier_arrival',%s,%s,%s)""",
                    (
                        run,
                        sim,
                        job["basket"],
                        job["courier"],
                        Jsonb({"checkpoint": node, "attempt": job["attempt"], "status": "arrived"}),
                    ),
                )
                topic, target = "delivery.arrived", "dispatcher:fleet"
            else:
                continue
            publish(
                conn,
                run_id=run,
                producer="lab_world",
                topic=topic,
                payload={"basket": job["basket"], "attempt": job["attempt"]},
                key=f"{job['basket']}:{job['attempt']}",
                trace_id=job["basket"],
                parent_id=parent["id"],
                target_store=target,
                due_sim=sim,
            )
        if dropouts:
            for courier in sorted(dropouts):
                row = conn.execute(
                    """UPDATE lab_fleet SET status='offline' WHERE run_id=%s
                    AND id=%s AND status='active' AND busy_basket IS NULL RETURNING node""",
                    (run, courier),
                ).fetchone()
                if row:
                    conn.execute(
                        """INSERT INTO lab_incidents(run_id,sim_time,kind,courier,detail)
                        VALUES (%s,%s,'courier_dropout',%s,%s)""",
                        (
                            run,
                            sim,
                            courier,
                            Jsonb(
                                {
                                    "checkpoint": row["node"],
                                    "reason": "Courier unavailable while idle",
                                }
                            ),
                        ),
                    )


def run_fleet(run: str, url: str | None = None, playback_seconds: int = 0) -> dict[str, Any]:
    if not 0 <= playback_seconds <= 120:
        raise ValueError("Playback must be 0..120 seconds")
    prepare_fleet(run, url)
    checkpoints = []
    try:
        agents = {
            access.store: create_agent(access.dsn)
            for role in ("inventory", "fulfillment", "dispatcher", "courier", "judge")
            for access in role_access(run, role, url).values()
        }
        for _cycle in range(600):
            with connect(url) as conn:
                current = conn.execute("SELECT sim_time FROM runs WHERE id=%s", (run,)).fetchone()
                assert current
                sim = current["sim_time"]
                due = conn.execute(
                    """SELECT target_store,min(id) AS first FROM events WHERE run_id=%s
                    AND state='ready' AND due_sim<=%s AND available_at<=clock_timestamp()
                    GROUP BY target_store""",
                    (run, sim),
                ).fetchall()
            handled = False

            def priority(row: dict[str, Any]) -> tuple[int, int]:
                scope = row["target_store"] or ""
                rank = (
                    0
                    if scope.startswith("store-")
                    else 1
                    if scope.startswith("fulfillment:")
                    else 2
                    if scope.startswith("courier:")
                    else 3
                    if scope.startswith("judge:")
                    else 4
                )
                return rank, row["first"]

            for row in sorted(due, key=priority):
                agent = agents.get(row["target_store"])
                if agent and (event := agent.claim()):
                    if not agent.process(event):
                        raise RuntimeError("FleetAgentStepFailed")
                    handled = True
                    break
            if not handled:
                q = Queue(url)
                for role in ("inventory_audit", "delivery_audit"):
                    while event := q.claim(role, run, sim):
                        if not q.process(event, lambda conn, msg: None):
                            raise RuntimeError("FleetAuditFailed")
                state = flow_snapshot(run, url)
                if state["jobs"] and all(
                    j["status"] in {"delivered", "abandoned"} for j in state["jobs"]
                ):
                    with connect(url) as conn:
                        pending = conn.execute(
                            """SELECT min(due_sim) AS due FROM events
                            WHERE run_id=%s AND state='ready'""",
                            (run,),
                        ).fetchone()
                    if not pending or pending["due"] is None:
                        break
                with connect(url) as conn:
                    upcoming = conn.execute(
                        """SELECT min(due_sim) AS due FROM events
                        WHERE run_id=%s AND state='ready' AND due_sim>%s""",
                        (run, sim),
                    ).fetchone()
                instants = [sim + 180]
                if sim < 180:
                    instants.append(180)
                instants.extend(
                    j["arrive_sim"]
                    for j in state["jobs"]
                    if j["status"] in {"assigned", "in_transit"}
                    and j["accepted"]
                    and j["arrive_sim"] > sim
                )
                if upcoming and upcoming["due"] is not None:
                    instants.append(upcoming["due"])
                advance_fleet(run, min(instants), url)
            if handled:
                state = flow_snapshot(run, url)
                if not all(state["invariants"].values()):
                    raise RuntimeError("FleetInvariantViolation")
                checkpoints.append(
                    {
                        "run": state["run"],
                        "jobs": state["jobs"],
                        "fleet": state["fleet"],
                        "incidents": state["incidents"],
                        "reviews": state["reviews"],
                    }
                )
                if playback_seconds:
                    time.sleep(playback_seconds / 100)
            if sim > 40000:
                raise RuntimeError("FleetSimulationTimeLimit")
        else:
            raise RuntimeError("FleetEventLimit")
        with connect(url) as conn:
            conn.execute("UPDATE runs SET status='complete' WHERE id=%s", (run,))
        result = flow_snapshot(run, url)
        result["checkpoints"] = checkpoints
        return result
    except Exception as exc:
        with connect(url) as conn:
            conn.execute(
                "UPDATE runs SET status='failed',error=%s WHERE id=%s", (type(exc).__name__, run)
            )
        raise
    finally:
        retire_inventory_access(run, url)

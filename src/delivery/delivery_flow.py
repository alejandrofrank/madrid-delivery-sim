"""Trusted local world controller; evaluated roles only communicate through the queue."""

import json
import time
from pathlib import Path
from typing import Any

from delivery.agent_access import retire_inventory_access, role_access
from delivery.agent_runtime import LocalAgent, create_agent
from delivery.catalogue import digest
from delivery.db import connect
from delivery.lab import create_lab, lab_snapshot
from delivery.queue import Queue, publish


def prepare_delivery(run: str, url: str | None = None) -> None:
    state = lab_snapshot(run, url)
    store = state["selected_store"]
    with connect(url) as conn:
        started = conn.execute(
            """UPDATE runs SET status='running'
            WHERE id=%s AND status='ready' RETURNING id""",
            (run,),
        ).fetchone()
        if not started:
            raise ValueError("Delivery run must be ready; completed runs are immutable")
        conn.execute(
            """INSERT INTO lab_fulfillments(run_id,basket,store,customer_node)
            VALUES (%s,'basket-delivery',%s,88)""",
            (run, store),
        )
        conn.execute("INSERT INTO lab_fleet VALUES (%s,'bike-1',22,NULL)", (run,))
        publish(
            conn,
            run_id=run,
            producer="lab_scenario",
            topic="basket.requested",
            payload={
                "basket": "basket-delivery",
                "store": store,
                "sku": state["selected_product"],
                "quantity": 1,
                "expires_sim": 600,
                "deliver": True,
            },
            key="basket-delivery",
            trace_id="basket-delivery",
            target_store=store,
        )


def delivery_agents(run: str, url: str | None = None) -> list[LocalAgent]:
    return [
        create_agent(access.dsn)
        for role in ("inventory", "fulfillment", "dispatcher")
        for access in role_access(run, role, url).values()
    ]


def world_tick(run: str, sim: int, url: str | None = None) -> None:
    """Advance authoritative motion; agents cannot teleport or manufacture arrival."""
    with connect(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (run,))
        current = conn.execute(
            "SELECT sim_time FROM runs WHERE id=%s FOR UPDATE", (run,)
        ).fetchone()
        if not current or sim < current["sim_time"]:
            raise ValueError("Simulation time cannot go backwards")
        conn.execute("UPDATE runs SET sim_time=%s WHERE id=%s", (sim, run))
        world = conn.execute("SELECT city FROM lab_worlds WHERE run_id=%s", (run,)).fetchone()
        assert world
        edges = {(e["from"], e["to"]): e["travel_seconds"] for e in world["city"]["edges"]}
        jobs = conn.execute(
            """SELECT * FROM lab_delivery_jobs WHERE run_id=%s
            AND status IN ('assigned','in_transit') FOR UPDATE""",
            (run,),
        ).fetchall()
        for job in jobs:
            elapsed = sim - job["depart_sim"]
            node = job["route"][0]
            for a, b in zip(job["route"], job["route"][1:], strict=False):
                elapsed -= edges[a, b]
                if elapsed < 0:
                    break
                node = b
            conn.execute(
                "UPDATE lab_fleet SET node=%s WHERE run_id=%s AND id=%s",
                (node, run, job["courier"]),
            )
            status = (
                "arrived"
                if sim >= job["arrive_sim"]
                else "in_transit"
                if sim >= job["pickup_sim"]
                else "assigned"
            )
            conn.execute(
                "UPDATE lab_delivery_jobs SET status=%s WHERE run_id=%s AND basket=%s",
                (status, run, job["basket"]),
            )
            if status == "arrived":
                parent = conn.execute(
                    """SELECT id FROM events WHERE run_id=%s
                    AND topic='delivery.assigned' AND trace_id=%s""",
                    (run, job["basket"]),
                ).fetchone()
                if not parent:
                    raise ValueError("Missing queued assignment")
                publish(
                    conn,
                    run_id=run,
                    producer="lab_world",
                    topic="delivery.arrived",
                    payload={"basket": job["basket"]},
                    key=job["basket"],
                    trace_id=job["basket"],
                    target_store="dispatcher:fleet",
                    due_sim=sim,
                    parent_id=parent["id"],
                )


def flow_snapshot(run: str, url: str | None = None) -> dict[str, Any]:
    with connect(url) as conn:
        state = lab_snapshot(run, url, connection=conn)
        if not state["run"]:
            return state
        state["tasks"] = conn.execute(
            """SELECT f.basket,f.store,f.customer_node,
            coalesce(j.status,k.status,f.status) AS status FROM lab_fulfillments f
            LEFT JOIN lab_baskets k ON k.run_id=f.run_id AND k.id=f.basket
            LEFT JOIN lab_delivery_jobs j ON j.run_id=f.run_id AND j.basket=f.basket
            WHERE f.run_id=%s ORDER BY f.basket""",
            (run,),
        ).fetchall()
        state["jobs"] = conn.execute(
            "SELECT * FROM lab_delivery_jobs WHERE run_id=%s ORDER BY basket", (run,)
        ).fetchall()
        state["events"] = conn.execute(
            """SELECT id,topic,producer,trace_id,parent_id,state,attempts,due_sim,target_store
            FROM events WHERE run_id=%s ORDER BY id""",
            (run,),
        ).fetchall()
        state["fleet"] = conn.execute(
            "SELECT id,node,busy_basket,status FROM lab_fleet WHERE run_id=%s ORDER BY id", (run,)
        ).fetchall()
        settings_row = conn.execute(
            "SELECT config,order_schedule,summary FROM lab_city_configs WHERE run_id=%s", (run,)
        ).fetchone()
        state["customers"] = state["city"].get("customers", [])
        state["agent_runtime"] = {
            "decision_mode": "deterministic",
            "model_provider": "disabled",
            "model_calls": 0,
            "model_spend": 0,
            "policy_source": "fixed Python rules",
            "soul_usage": "versioned guidance only",
        }
        if settings_row:
            state["config"] = settings_row["config"]
            if settings_row["config"].get("agent_mode") == "gcp_ai":
                calls = conn.execute(
                    "SELECT status,detail,reserved_tokens FROM agent_model_calls WHERE run_id=%s",
                    (run,),
                ).fetchall()
                state["agent_runtime"] = {
                    "decision_mode": "gcp_ai_judge",
                    "model_provider": "vertex_ai",
                    "model_calls": len(
                        [
                            c
                            for c in calls
                            if "model" in c["detail"] and c["detail"].get("source") != "policy_gate"
                        ]
                    ),
                    "model_reservations": len(calls),
                    "reserved_tokens": sum(c["reserved_tokens"] for c in calls),
                    "policy_source": "GCP recovery judge; all other roles use local rules",
                    "soul_usage": "bounded gateway judgement prompt",
                }
            state["configuration_hash"] = digest(settings_row["config"])
            state["order_schedule"] = settings_row["order_schedule"]
            state["session_summary"] = settings_row["summary"]
        for courier in state["fleet"]:
            home = conn.execute(
                "SELECT home_store FROM lab_fleet WHERE run_id=%s AND id=%s", (run, courier["id"])
            ).fetchone()
            courier["home_store"] = home["home_store"] if home else None
        for key, table in (
            ("attempts", "lab_delivery_attempts"),
            ("briefs", "lab_briefs"),
            ("reviews", "lab_retry_reviews"),
            ("incidents", "lab_incidents"),
        ):
            state[key] = conn.execute(f"SELECT * FROM {table} WHERE run_id=%s", (run,)).fetchall()
    if state["attempts"]:
        active = [j for j in state["jobs"] if j["status"] in {"assigned", "in_transit", "arrived"}]
        state["invariants"]["unique_courier_assignments"] = len(
            {j["courier"] for j in active}
        ) == len(active)
        nodes = {n["id"] for n in state["city"]["nodes"]}
        state["invariants"]["parcel_custody_recorded"] = all(
            j["parcel_node"] in nodes
            for j in state["jobs"]
            if j["status"] in {"awaiting_review", "abandoned", "delivered"}
        )
        reviews = {(r["basket"], r["attempt"]): r["verdict"] for r in state["reviews"]}
        state["invariants"]["retries_have_approval"] = all(
            a["attempt"] == 1 or reviews.get((a["basket"], a["attempt"] - 1)) == "approved"
            for a in state["attempts"]
        )
    timeline = []
    for decision in state["decisions"]:
        detail = decision["detail"]
        timeline.append(
            {
                "sim_time": decision["sim_time"],
                "label": decision["action"],
                "basket": detail.get("basket"),
                "status": detail.get("status"),
            }
        )
    for job in [] if state["attempts"] else state["jobs"]:
        for instant, label, node in (
            (job["pickup_sim"], "Courier collected basket", job["pickup_node"]),
            (job["arrive_sim"], "Courier arrived", job["customer_node"]),
        ):
            if instant is not None and instant <= state["run"]["sim_time"]:
                timeline.append(
                    {"sim_time": instant, "label": label, "basket": job["basket"], "node": node}
                )
    for incident in state["incidents"]:
        timeline.append(
            {
                "sim_time": incident["sim_time"],
                "label": incident["kind"],
                "basket": incident["basket"],
                "status": incident["detail"].get("status"),
                "node": incident["detail"].get("checkpoint"),
            }
        )
    state["timeline"] = sorted(timeline, key=lambda item: item["sim_time"])
    return state


def run_delivery(run: str, url: str | None = None, playback_seconds: int = 0) -> dict[str, Any]:
    with connect(url) as conn:
        world = conn.execute("SELECT city FROM lab_worlds WHERE run_id=%s", (run,)).fetchone()
    if world and world["city"]["width"] == 32:
        from delivery.fleet_flow import run_fleet

        return run_fleet(run, url, playback_seconds)
    if not 0 <= playback_seconds <= 120:
        raise ValueError("Playback must be 0..120 seconds")
    prepare_delivery(run, url)
    checkpoints = []
    try:
        agents = delivery_agents(run, url)
        for _cycle in range(100):
            state = flow_snapshot(run, url)
            sim = state["run"]["sim_time"]
            handled = False
            # One queued step per checkpoint makes the handoffs inspectable.
            for agent in agents:
                event = agent.claim()
                if event:
                    if not agent.process(event):
                        raise RuntimeError("AgentStepFailed")
                    handled = True
                    break
            if not handled:
                q = Queue(url)
                for role in ("inventory_audit", "delivery_audit"):
                    while event := q.claim(role, run, sim):
                        if not q.process(event, lambda conn, message: None):
                            raise RuntimeError("AuditStepFailed")
                state = flow_snapshot(run, url)
                if state["jobs"] and all(j["status"] == "delivered" for j in state["jobs"]):
                    break
                active = [
                    j
                    for j in state["jobs"]
                    if j["arrive_sim"] is not None and j["status"] != "delivered"
                ]
                if not active:
                    raise RuntimeError("WorkflowStalled")
                world_tick(run, min(sim + 60, min(j["arrive_sim"] for j in active)), url)
            checkpoint = flow_snapshot(run, url)
            if not all(checkpoint["invariants"].values()):
                raise RuntimeError("InvariantViolation")
            checkpoints.append(checkpoint)
            if playback_seconds:
                time.sleep(playback_seconds / 25)
        else:
            raise RuntimeError("WorkflowStepLimit")
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


def export_delivery(run: str, seconds: int = 12) -> None:
    result = run_delivery(run, playback_seconds=seconds)
    Path("artifacts").mkdir(exist_ok=True)
    Path(f"artifacts/delivery-{run}.json").write_text(
        json.dumps(result, default=str, indent=2), encoding="utf-8"
    )


def new_delivery(seed: int = 42, url: str | None = None) -> str:
    return create_lab(
        url,
        seed=seed,
        catalogue_path=Path("data/expanded-catalogue.json"),
        city_size=32,
        opening_units=2,
    )

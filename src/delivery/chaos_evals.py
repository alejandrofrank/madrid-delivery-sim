"""Reproducible recovery outcomes over the real A2A SDK and dedicated test database."""

import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI
from psycopg.types.json import Jsonb

from delivery.agent_transport import A2ATransport
from delivery.chaos import ChaosConfig, Disruption, evidence, insert_event
from delivery.db import connect, migrate
from delivery.protocol_api import agent_directory
from delivery.queue import publish
from delivery.scenario_evals import require_local_test_database
from delivery.scenario_report import digest
from delivery.simulation import Simulation, create_run, finish_run
from delivery.world import World, seed_locations

MANIFEST = Path(__file__).resolve().parents[2] / "evals/chaos/scenarios.json"


def check_outcome(outcome: dict[str, Any], criteria: dict[str, Any]) -> bool:
    """Recompute gates from measured rows; never trust a saved 'passed' field."""
    metrics = outcome["metrics"]
    if len(metrics) != 1:
        return False
    m = metrics[0]
    refunds: dict[str, float] = {}
    for contact in outcome["contacts"]:
        refunds[contact["order_id"]] = refunds.get(contact["order_id"], 0) + contact["refund_eur"]
        if contact["refund_eur"] != 0:  # scripted fixture cannot approve money
            return False
    return bool(
        m["affected_orders"] >= criteria["min_affected_orders"]
        and m["orders_saved"] >= criteria["min_orders_saved"]
        and m["orders_lost"] <= criteria["max_orders_lost"]
        and m["late_deliveries"] <= criteria["max_late_deliveries"]
        and m["unresolved_orders"] == 0
        and m["time_to_recover_seconds"] is not None
        and 0 <= m["time_to_recover_seconds"] <= criteria["max_recovery_seconds"]
        and m["extra_token_cost_usd"] <= criteria["max_extra_token_cost_usd"]
        and m["failed_replans"] <= criteria["max_failed_replans"]
        and all(0 <= value <= criteria["max_refund_per_order_eur"] for value in refunds.values())
        and outcome["contacts"]
        and len(outcome["replans"]) == 3 * m["affected_orders"]
        and all(w["state"] == "done" for w in outcome["replans"])
    )


def run_case(kind: str, seed: int, url: str, world: World) -> dict[str, Any]:
    run = str(uuid4())
    try:
        with connect(url) as conn:
            seed_locations(conn, world)
            conn.execute(
                "INSERT INTO runs(id,seed,duration,status,chaos_config) "
                "VALUES (%s,%s,3600,'running',%s)",
                (run, seed, Jsonb(ChaosConfig().model_dump())),
            )
            store = conn.execute(
                "SELECT * FROM locations WHERE kind='store' AND district='Retiro' "
                "ORDER BY id LIMIT 1"
            ).fetchone()
            customer = conn.execute(
                "SELECT id FROM locations WHERE kind='customer' AND district='Retiro' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert store and customer
            for name in ("eval-courier-a", "eval-courier-b"):
                conn.execute(
                    "INSERT INTO couriers(run_id,id,hub,mode,node,point) "
                    "VALUES (%s,%s,'retiro','bike',%s,%s)",
                    (run, name, store["node"], store["point"]),
                )
            conn.execute(
                "INSERT INTO orders(run_id,id,store,customer,created_sim,ready_sim,due_sim) "
                "VALUES (%s,'eval-order',%s,%s,0,300,900)",
                (run, store["id"], customer["id"]),
            )
            publish(
                conn,
                run_id=run,
                producer="generator",
                topic="order.created",
                payload={"order_id": "eval-order"},
                key="eval-order",
                trace_id="eval-order",
            )
        app = FastAPI()
        app.mount("/a2a", agent_directory(url))
        transport = A2ATransport(
            "http://localhost:8010", http_transport=httpx.ASGITransport(app=app)
        )
        simulation = Simulation(world, url, transport=transport)
        simulation.drain(run, 0)
        with connect(url) as conn:
            order = conn.execute("SELECT * FROM orders WHERE run_id=%s", (run,)).fetchone()
            assert order and order["route"]
            at = math.ceil(order["route"]["pickup_at"] / 60) * 60 + 60
            insert_event(
                conn,
                run,
                Disruption.model_validate(
                    {
                        "id": "measured",
                        "kind": kind,
                        "at": at if kind == "courier_offline" else 60,
                        "duration": 600,
                        "district": "retiro",
                        "target": "auto"
                        if kind in {"restaurant_outage", "courier_offline"}
                        else None,
                    }
                ),
            )
        for sim in range(60, 3601, 60):
            simulation.step(run, sim, seed, 0)
        finish_run(run, url)
        with connect(url) as conn:
            result = evidence(conn, run)
        # UUIDs and wall timestamps are identities, not reproducible business outcomes.
        for event in result["events"]:
            event.pop("run_id", None)
        return result
    finally:
        with connect(url) as conn:
            for table in (
                "llm_requests",
                "decisions",
                "complaints",
                "orders",
                "couriers",
                "events",
                "runs",
            ):
                key = "id" if table == "runs" else "run_id"
                conn.execute(f"DELETE FROM {table} WHERE {key}=%s", (run,))


def validate_chaos_report(report: dict[str, Any], manifest: dict[str, Any]) -> bool:
    if (
        report.get("kind") != "chaos-evals"
        or report.get("mode") != "scripted-offline"
        or report.get("fixture_hash") != digest(manifest)
        or report.get("seed") != manifest["seed"]
    ):
        return False
    rows = report.get("results", [])
    if len(rows) != 2 * len(manifest["cases"]):
        return False
    for kind in manifest["cases"]:
        attempts = [row for row in rows if row["case"] == kind]
        if (
            {row["repetition"] for row in attempts} != {1, 2}
            or len(attempts) != 2
            or not all(check_outcome(r["outcome"], manifest["criteria"]) for r in attempts)
            or digest(attempts[0]["outcome"]) != digest(attempts[1]["outcome"])
        ):
            return False
    seeded = report.get("seeded_runs", [])
    return bool(
        len(seeded) == 2
        and seeded[0]["orders"]
        and seeded[0]["chaos"]["events"]
        and digest(seeded[0]) == digest(seeded[1])
    )


def seeded_run(seed: int, url: str, world: World) -> dict[str, Any]:
    run = create_run(
        world, seed, 0, 1800, url, chaos=ChaosConfig(random_events=2, demand_multiplier=3)
    )
    try:
        simulation = Simulation(world, url)
        with connect(url) as conn:
            conn.execute("UPDATE runs SET status='running' WHERE id=%s", (run,))
        for sim in range(0, 1801, 60):
            simulation.step(run, sim, seed, 1800)
        finish_run(run, url)
        with connect(url) as conn:
            result = evidence(conn, run)
            orders = conn.execute(
                "SELECT id,status,courier,delivered_sim,ready_sim,due_sim "
                "FROM orders WHERE run_id=%s ORDER BY id",
                (run,),
            ).fetchall()
        for event in result["events"]:
            event.pop("run_id", None)
        return {"chaos": result, "orders": orders}
    finally:
        with connect(url) as conn:
            for table in (
                "llm_requests",
                "decisions",
                "complaints",
                "orders",
                "couriers",
                "events",
                "runs",
            ):
                key = "id" if table == "runs" else "run_id"
                conn.execute(f"DELETE FROM {table} WHERE {key}=%s", (run,))


def evaluate_chaos(url: str, manifest: dict[str, Any]) -> dict[str, Any]:
    require_local_test_database(url)
    migrate(url)
    world = World()
    rows = []
    for kind in manifest["cases"]:
        for repeat in (1, 2):
            rows.append(
                {
                    "case": kind,
                    "repetition": repeat,
                    "outcome": run_case(kind, manifest["seed"], url, world),
                }
            )
    return {
        "kind": "chaos-evals",
        "mode": "scripted-offline",
        "seed": manifest["seed"],
        "fixture_hash": digest(manifest),
        "results": rows,
        "seeded_runs": [seeded_run(manifest["seed"], url, world) for _ in range(2)],
    }

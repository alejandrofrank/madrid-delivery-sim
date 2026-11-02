"""Measured store recovery with the real A2A SDK; no model or cloud calls."""

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from delivery.agent_transport import A2ATransport
from delivery.chaos import Disruption, insert_event
from delivery.db import connect
from delivery.protocol_api import agent_directory
from delivery.scenario_report import digest
from delivery.simulation import Simulation, finish_run
from delivery.store_api import StoreDemo, demo_run
from delivery.store_conditions import STORE_KINDS
from delivery.world import World

MANIFEST = Path(__file__).resolve().parents[2] / "evals/store/scenarios.json"


def required(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        raise AssertionError("Expected a measured database row")
    return row


def run_case(kind: str, seed: int, url: str) -> dict[str, Any]:
    if kind not in STORE_KINDS:
        raise ValueError("Unknown store evaluation")
    run, store = demo_run(StoreDemo(seed=seed, wall_seconds=0), url)
    try:
        app = FastAPI()
        app.mount("/a2a", agent_directory(url))
        simulation = Simulation(
            World(),
            url,
            transport=A2ATransport(
                "http://localhost:8010", http_transport=httpx.ASGITransport(app=app)
            ),
        )
        with connect(url) as conn:
            conn.execute("UPDATE runs SET status='running' WHERE id=%s", (run,))
        simulation.step(run, 0, seed, 0)
        with connect(url) as conn:
            insert_event(
                conn,
                run,
                Disruption.model_validate(
                    dict(id="store-incident", kind=kind, at=10, duration=390, target=store)
                ),
            )
            opening = required(
                conn.execute(
                    "SELECT sum(on_hand) n FROM lab_stock WHERE run_id=%s", (run,)
                ).fetchone()
            )["n"]
        # Ten-second physics in the store, then the unchanged city clock.
        for sim in (*range(10, 901, 10), *range(960, 1801, 60)):
            simulation.step(run, sim, seed, 0)
        finish_run(run, url, store_enabled=True)
        with connect(url) as conn:
            order = required(
                conn.execute(
                    "SELECT s.stage,s.lines,s.picked,s.dock_sim,o.status,"
                    "o.delivered_sim,o.due_sim FROM store_orders s JOIN orders o "
                    "ON o.run_id=s.run_id AND o.id=s.order_id WHERE s.run_id=%s",
                    (run,),
                ).fetchone()
            )
            stock = required(
                conn.execute(
                    "SELECT sum(on_hand) n,sum(reserved) r FROM lab_stock WHERE run_id=%s", (run,)
                ).fetchone()
            )
            shelves = required(
                conn.execute(
                    "SELECT sum(quantity) n FROM store_shelves WHERE run_id=%s", (run,)
                ).fetchone()
            )["n"]
            receipts = required(
                conn.execute(
                    "SELECT coalesce(sum(quantity),0) n FROM lab_shipments "
                    "WHERE run_id=%s AND status='received'",
                    (run,),
                ).fetchone()
            )["n"]
            decisions = conn.execute(
                "SELECT sim_time,action,detail FROM decisions "
                "WHERE run_id=%s AND agent='fulfillment' ORDER BY id",
                (run,),
            ).fetchall()
            events = conn.execute(
                "SELECT topic,due_sim,state FROM events WHERE run_id=%s "
                "AND topic LIKE 'store.%%' ORDER BY id",
                (run,),
            ).fetchall()
            dead = required(
                conn.execute(
                    "SELECT count(*) n FROM events WHERE run_id=%s AND state='dead'", (run,)
                ).fetchone()
            )["n"]
            spend = required(
                conn.execute(
                    "SELECT llm_calls,llm_cost_usd FROM runs WHERE id=%s", (run,)
                ).fetchone()
            )
            shipment = required(
                conn.execute(
                    "SELECT s.expected_sim,m.sim_time received_sim FROM lab_shipments s "
                    "LEFT JOIN lab_movements m ON m.run_id=s.run_id AND "
                    "m.command_key='receipt:'||s.id WHERE s.run_id=%s ORDER BY s.id",
                    (run,),
                ).fetchone()
            )
        assert order
        # Event ids are per-database identities, not behavior.
        for decision in decisions:
            decision["detail"].pop("event_id", None)
        return {
            "order": order,
            "stock_conserved": stock["n"]
            == shelves
            == opening + receipts - sum(order["picked"].values()),
            "reserved": stock["r"],
            "dead_events": dead,
            "events": events,
            "decisions": decisions,
            "shipment": shipment,
            "model_calls": spend["llm_calls"],
            "cost_usd": float(spend["llm_cost_usd"]),
            "recovery_seconds": None
            if order["dock_sim"] is None
            else max(0, order["dock_sim"] - 10),
        }
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


def passed(kind: str, result: dict[str, Any], criteria: dict[str, Any]) -> bool:
    order = result["order"]
    if not (
        order["status"] == "delivered"
        and order["stage"] == "handed_off"
        and order["lines"] == order["picked"]
        and result["stock_conserved"]
        and result["reserved"] == 0
        and result["dead_events"] == 0
        and result["model_calls"] == 0
        and result["cost_usd"] == 0
        and result["recovery_seconds"] is not None
        and result["recovery_seconds"] <= criteria["max_dock_recovery_seconds"]
        and order["delivered_sim"] <= order["due_sim"]
    ):
        return False
    actions = {row["action"] for row in result["decisions"]}
    if kind == "robot_breakdown" and "recovered" not in actions:
        return False
    if kind == "late_restock_truck" and result["shipment"]["received_sim"] < 400:
        return False
    return True


def evaluate(url: str) -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text())
    rows = [
        {"case": kind, "attempt": attempt, "result": run_case(kind, manifest["seed"], url)}
        for kind in manifest["cases"]
        for attempt in (1, 2)
    ]
    return {"kind": "store-evals", "fixture_hash": digest(manifest), "rows": rows}


def validate(report: dict[str, Any]) -> bool:
    manifest = json.loads(MANIFEST.read_text())
    if report.get("kind") != "store-evals" or report.get("fixture_hash") != digest(manifest):
        return False
    rows = report.get("rows", [])
    if len(rows) != 2 * len(manifest["cases"]):
        return False
    for kind in manifest["cases"]:
        attempts = [r for r in rows if r["case"] == kind]
        if (
            len(attempts) != 2
            or {r["attempt"] for r in attempts} != {1, 2}
            or not all(passed(kind, r["result"], manifest["criteria"]) for r in attempts)
            or digest(attempts[0]["result"]) != digest(attempts[1]["result"])
        ):
            return False
    return True

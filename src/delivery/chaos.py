"""Persisted, seeded physical disruptions. Recovery decisions belong to agents."""

import hashlib
import math
import random
from pathlib import Path
from typing import Any, Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from delivery.agent_transport import restaurant_name
from delivery.db import Connection, connect
from delivery.telemetry import trace_span
from delivery.world import position

KINDS = ("heavy_rain", "metro_strike", "restaurant_outage", "courier_offline", "demand_surge")
District = Literal["chamberi", "retiro", "vallecas"]
DISTRICT_NAMES = {"chamberi": "Chamberí", "retiro": "Retiro", "vallecas": "Puente de Vallecas"}


class Disruption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal[
        "heavy_rain", "metro_strike", "restaurant_outage", "courier_offline", "demand_surge"
    ]
    at: int = Field(default=0, ge=0, le=43200)
    duration: int = Field(default=900, ge=60, le=14400)
    district: District | None = None
    target: str | None = Field(default=None, max_length=80, pattern=r"^[a-zA-Z0-9_/-]+$")
    severity: float = Field(default=2, ge=1, le=4)

    @model_validator(mode="after")
    def scope(self) -> "Disruption":
        if self.kind in {"metro_strike", "demand_surge"} and self.district is None:
            raise ValueError("A district is required")
        if self.kind in {"restaurant_outage", "courier_offline"} and self.target is None:
            raise ValueError("A restaurant or courier target is required (or 'auto')")
        return self


class ChaosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[Disruption] = Field(default_factory=list, max_length=32)
    random_events: int = Field(default=0, ge=0, le=20)
    demand_multiplier: float = Field(default=1, ge=1, le=8)

    @model_validator(mode="after")
    def unique_ids(self) -> "ChaosConfig":
        if len({e.id for e in self.events}) != len(self.events):
            raise ValueError("Scenario event IDs must be unique")
        if any(e.id.startswith("random-") for e in self.events):
            raise ValueError("random- IDs are reserved for seeded events")
        return self


def load_scenario(path: Path) -> ChaosConfig:
    return ChaosConfig.model_validate_json(path.read_text(encoding="utf-8"))


def schedule(config: ChaosConfig, seed: int, duration: int) -> list[Disruption]:
    rng = random.Random(seed)
    events = list(config.events)
    for index in range(config.random_events):
        kind = rng.choice(KINDS)
        at = rng.randrange(1, max(2, (duration - 900) // 60)) * 60
        events.append(
            Disruption(
                id=f"random-{index:02d}",
                kind=kind,  # type: ignore[arg-type]
                at=at,
                duration=min(600, duration - at),
                severity=rng.choice((1.5, 2, 3)),
                district=rng.choice(("chamberi", "retiro", "vallecas")),
                target="auto" if kind in {"restaurant_outage", "courier_offline"} else None,
            )
        )
    if any(e.at + e.duration > duration for e in events):
        raise ValueError("Disruptions must end within the run duration")
    return sorted(events, key=lambda e: (e.at, e.id))


def insert_event(conn: Connection, run: str, event: Disruption) -> None:
    if event.target and event.target != "auto":
        if event.kind == "restaurant_outage":
            valid = conn.execute(
                "SELECT 1 FROM locations WHERE kind='store' AND id=%s", (event.target,)
            ).fetchone()
        else:
            valid = conn.execute(
                "SELECT 1 FROM couriers WHERE run_id=%s AND id=%s", (run, event.target)
            ).fetchone()
        if not valid:
            raise ValueError("Unknown disruption target")
    previous = conn.execute(
        "SELECT * FROM chaos_events WHERE run_id=%s AND id=%s", (run, event.id)
    ).fetchone()
    values = (
        event.kind,
        event.district,
        event.target,
        event.severity,
        event.at,
        event.at + event.duration,
    )
    if previous:
        if (
            tuple(
                previous["requested_target"] if k == "target" else previous[k]
                for k in ("kind", "district", "target", "severity", "start_sim", "end_sim")
            )
            != values
        ):
            raise ValueError("Disruption ID already has a different payload")
        return
    conn.execute(
        "INSERT INTO chaos_events(run_id,id,kind,district,target,severity,"
        "start_sim,end_sim,requested_target) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (run, event.id, *values, event.target),
    )


def trigger(run: str, event: Disruption, url: str | None = None) -> None:
    with connect(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (run,))
        row = conn.execute("SELECT * FROM runs WHERE id=%s FOR UPDATE", (run,)).fetchone()
        if not row or row["status"] not in {"ready", "running"} or row["chaos_config"] is None:
            raise ValueError("An open Chaos run is required")
        previous = conn.execute(
            "SELECT start_sim FROM chaos_events WHERE run_id=%s AND id=%s", (run, event.id)
        ).fetchone()
        if "at" not in event.model_fields_set:
            event = event.model_copy(
                update={"at": previous["start_sim"] if previous else row["sim_time"] + 60}
            )
        if previous:
            insert_event(conn, run, event)
            return
        if event.at < row["sim_time"] or event.at + event.duration > row["duration"]:
            raise ValueError(
                "Event must start at or after the current clock and end within the run"
            )
        count = conn.execute(
            "SELECT count(*) n FROM chaos_events WHERE run_id=%s", (run,)
        ).fetchone()
        if count and count["n"] >= 64:
            raise ValueError("Run disruption limit reached")
        insert_event(conn, run, event)


def active_events(conn: Connection, run: str) -> list[dict[str, Any]]:
    return list(
        conn.execute(
            "SELECT * FROM chaos_events WHERE run_id=%s AND state='active' ORDER BY start_sim,id",
            (run,),
        ).fetchall()
    )


def affected(event: dict[str, Any], order: dict[str, Any]) -> bool:
    if event["kind"] == "restaurant_outage":
        return order["store"] == event["target"] and order["status"] != "picked_up"
    if event["kind"] == "courier_offline":
        return order["courier"] == event["target"]
    return event["district"] is None or DISTRICT_NAMES[event["district"]] in {
        order.get("store_district"),
        order.get("customer_district"),
    }


def traffic_factor(events: list[dict[str, Any]], order: dict[str, Any]) -> float:
    return min(
        4.0,
        math.prod(
            e["severity"]
            for e in events
            if e["kind"] in {"heavy_rain", "metro_strike"} and affected(e, order)
        ),
    )


def retime(route: dict[str, Any], sim: int, factor: float) -> dict[str, Any]:
    """Change only the remaining path; keep the observed position at the boundary."""
    old = route.get("chaos_factor", 1.0)
    if old == factor:
        return route
    ratio = factor / old
    result = dict(route)
    result["points"] = [p for p in route["points"] if p[2] < sim]
    result["points"].append([*position(route, sim), sim])
    result["points"].extend(
        [x, y, sim + (t - sim) * ratio] for x, y, t in route["points"] if t > sim
    )
    for key in ("pickup_arrival_at", "pickup_at", "delivery_arrival_at", "end_at"):
        if result.get(key, sim) > sim:
            result[key] = sim + (result[key] - sim) * ratio
    result["end_at"] = math.ceil(result["end_at"])
    result["chaos_factor"] = factor
    return result


def pause_route(route: dict[str, Any], since: int, duration: int) -> dict[str, Any]:
    """Freeze a stranded courier's remaining route at its last observed position."""
    result = dict(route)
    point = position(route, since)
    result["points"] = [p for p in route["points"] if p[2] < since]
    result["points"].extend([[*point, since], [*point, since + duration]])
    result["points"].extend([x, y, t + duration] for x, y, t in route["points"] if t > since)
    for key in ("pickup_arrival_at", "pickup_at", "delivery_arrival_at", "end_at"):
        if result.get(key, since) > since:
            result[key] += duration
    return result


def physical_tick(conn: Connection, run: str, sim: int) -> None:
    """Change availability and travel conditions only; never choose a recovery action."""
    expired = conn.execute(
        "UPDATE chaos_events SET state='ended' WHERE run_id=%s "
        "AND state='active' AND end_sim<=%s RETURNING *",
        (run, sim),
    ).fetchall()
    for event in expired:
        if event["kind"] == "courier_offline":
            overlapping = conn.execute(
                "SELECT 1 FROM chaos_events WHERE run_id=%s "
                "AND kind='courier_offline' AND target=%s AND state='active'",
                (run, event["target"]),
            ).fetchone()
            if not overlapping:
                conn.execute(
                    "UPDATE couriers SET status=CASE WHEN EXISTS (SELECT 1 FROM orders o "
                    "WHERE o.run_id=couriers.run_id AND o.courier=couriers.id "
                    "AND o.status IN ('assigned','picked_up')) THEN 'delivering' "
                    "ELSE 'idle' END WHERE run_id=%s AND id=%s AND status='offline'",
                    (run, event["target"]),
                )
    pending = conn.execute(
        "SELECT * FROM chaos_events WHERE run_id=%s AND state='scheduled' "
        "AND start_sim<=%s ORDER BY start_sim,id FOR UPDATE",
        (run, sim),
    ).fetchall()
    for event in pending:
        target = event["target"]
        if target == "auto":
            if event["kind"] == "courier_offline":
                row = conn.execute(
                    "SELECT id FROM couriers WHERE run_id=%s AND status!='offline' "
                    "ORDER BY (status='delivering') DESC,(status='to_pickup') DESC,id "
                    "LIMIT 1",
                    (run,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT store id FROM orders WHERE run_id=%s AND status IN "
                    "('pending','assigned') GROUP BY store ORDER BY count(*) DESC,store "
                    "LIMIT 1",
                    (run,),
                ).fetchone()
                if not row:
                    row = conn.execute(
                        "SELECT id FROM locations WHERE kind='store' ORDER BY id LIMIT 1"
                    ).fetchone()
            target = row["id"] if row else None
        conn.execute(
            "UPDATE chaos_events SET state='active',target=%s WHERE run_id=%s AND id=%s",
            (target, run, event["id"]),
        )
        if event["kind"] == "courier_offline" and target:
            conn.execute(
                "UPDATE couriers SET status='offline' WHERE run_id=%s AND id=%s", (run, target)
            )
        with trace_span(
            "chaos.started", attributes={"chaos.kind": event["kind"], "chaos.id": event["id"]}
        ):
            pass
    events = active_events(conn, run)
    orders = conn.execute(
        "SELECT o.*,s.district store_district,c.district customer_district,"
        "cr.status courier_status "
        "FROM orders o JOIN locations s ON s.id=o.store "
        "JOIN locations c ON c.id=o.customer JOIN couriers cr ON cr.run_id=o.run_id "
        "AND cr.id=o.courier WHERE o.run_id=%s "
        "AND o.status IN ('assigned','picked_up') ORDER BY o.id",
        (run,),
    ).fetchall()
    for order in orders:
        if order["route"]:
            route = dict(order["route"])
            since = route.pop("chaos_offline_since", None)
            if since is not None:
                route = pause_route(route, since, sim - since)
            route = retime(route, sim, traffic_factor(events, order))
            if order["courier_status"] == "offline":
                route["chaos_offline_since"] = sim
            if route != order["route"]:
                conn.execute(
                    "UPDATE orders SET route=%s WHERE run_id=%s AND id=%s",
                    (Jsonb(route), run, order["id"]),
                )


def observe(conn: Connection, run: str, sim: int) -> None:
    orders = conn.execute(
        "SELECT o.*,s.district store_district,c.district customer_district "
        "FROM orders o JOIN locations s ON s.id=o.store "
        "JOIN locations c ON c.id=o.customer WHERE o.run_id=%s "
        "AND o.status IN ('pending','assigned','picked_up') ORDER BY o.id",
        (run,),
    ).fetchall()
    for event in active_events(conn, run):
        for order in orders:
            if not affected(event, order):
                continue
            conn.execute(
                "INSERT INTO chaos_impacts VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (run, event["id"], order["id"], sim, (order["route"] or {}).get("end_at")),
            )
            for agent in (restaurant_name(order["store"]), "dispatcher", "customer_service"):
                identity = f"{event['id']}:{agent}:{order['id']}"
                key = hashlib.sha256(identity.encode()).hexdigest()[:32]
                conn.execute(
                    "INSERT INTO chaos_work(run_id,id,disruption,agent,order_id) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (run, key, event["id"], agent, order["id"]),
                )


def demand_factors(conn: Connection, run: str) -> tuple[float, dict[str, float]]:
    row = conn.execute("SELECT chaos_config FROM runs WHERE id=%s", (run,)).fetchone()
    config = row["chaos_config"] if row else None
    if config is None:
        return 1.0, {}
    events = active_events(conn, run)
    global_rate = config.get("demand_multiplier", 1.0)
    weights = {d: 1.0 for d in DISTRICT_NAMES.values()}
    for event in events:
        if event["kind"] in {"heavy_rain", "demand_surge"}:
            if event["district"] is None:
                global_rate *= event["severity"]
            else:
                weights[DISTRICT_NAMES[event["district"]]] *= event["severity"]
    return min(16, global_rate), weights


def evidence(conn: Connection, run: str) -> dict[str, Any]:
    events = list(
        conn.execute(
            "SELECT id,kind,district,target,severity,start_sim,end_sim,state "
            "FROM chaos_events WHERE run_id=%s ORDER BY start_sim,id",
            (run,),
        )
    )
    metrics = []
    for event in events:
        rows = conn.execute(
            "SELECT o.status,o.due_sim,o.delivered_sim FROM chaos_impacts i "
            "JOIN orders o ON o.run_id=i.run_id AND o.id=i.order_id "
            "WHERE i.run_id=%s AND i.disruption=%s",
            (run, event["id"]),
        ).fetchall()
        work = conn.execute(
            "SELECT w.state,w.tokens,w.cost_usd,w.completed_sim,coalesce(c.refund_eur,0) refund "
            "FROM chaos_work w LEFT JOIN chaos_contacts c ON c.run_id=w.run_id "
            "AND c.work_id=w.id WHERE w.run_id=%s AND w.disruption=%s",
            (run, event["id"]),
        ).fetchall()
        unresolved = sum(r["status"] not in {"delivered", "unserved"} for r in rows)
        settled = (
            event["state"] == "ended" and not unresolved and all(w["state"] == "done" for w in work)
        )
        terminal_at = max(
            [
                event["end_sim"],
                *[r["delivered_sim"] or 0 for r in rows],
                *[w["completed_sim"] or 0 for w in work],
            ]
        )
        metrics.append(
            {
                "id": event["id"],
                "affected_orders": len(rows),
                "unresolved_orders": unresolved,
                "time_to_recover_seconds": terminal_at - event["start_sim"] if settled else None,
                "orders_saved": sum(r["status"] == "delivered" for r in rows),
                "orders_lost": sum(r["status"] == "unserved" for r in rows),
                "late_deliveries": sum(
                    r["delivered_sim"] is not None and r["delivered_sim"] > r["due_sim"]
                    for r in rows
                ),
                "refund_cost_eur": sum(w["refund"] for w in work),
                "extra_tokens": sum(w["tokens"] for w in work),
                "extra_token_cost_usd": sum(w["cost_usd"] for w in work),
                "failed_replans": sum(w["state"] in {"failed", "reserved"} for w in work),
            }
        )
    work_rows = list(
        conn.execute(
            "SELECT id,disruption,agent,order_id,state,result,tokens,cost_usd "
            "FROM chaos_work WHERE run_id=%s ORDER BY id",
            (run,),
        )
    )
    contacts = list(
        conn.execute(
            "SELECT work_id,order_id,message,eta_sim,refund_eur,approval_status,sim_time "
            "FROM chaos_contacts WHERE run_id=%s ORDER BY sim_time,work_id",
            (run,),
        )
    )
    return {
        "events": events,
        "metrics": metrics,
        "replans": work_rows,
        "contacts": contacts,
        "cost_basis": "incremental recovery model turns; no counterfactual estimate",
        "saved_basis": "affected orders delivered; overlapping cohorts are not additive",
    }

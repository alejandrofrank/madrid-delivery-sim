"""Finite, seeded city sessions with ongoing demand and frozen operator settings."""

import time
from typing import Any

from psycopg.types.json import Jsonb

from delivery.agent_access import retire_inventory_access, role_access
from delivery.agent_runtime import create_agent
from delivery.catalogue import digest
from delivery.city_config import CitySettings, demand_schedule, dropout_schedule
from delivery.db import connect
from delivery.delivery_flow import flow_snapshot, new_delivery
from delivery.fleet_flow import advance_fleet
from delivery.queue import Queue, publish


def new_city(config: CitySettings, url: str | None = None) -> str:
    run = new_delivery(config.seed, url)
    state = flow_snapshot(run, url)
    settings = {s.id: s for s in config.stores}
    city = state["city"]
    for store in city["stores"]:
        store["name"] = settings[store["id"]].name
        store["enabled"] = settings[store["id"]].enabled
    city["sha256"] = digest({k: v for k, v in city.items() if k != "sha256"})
    with connect(url) as conn:
        conn.execute("UPDATE lab_worlds SET city=%s WHERE run_id=%s", (Jsonb(city), run))
        conn.execute("DELETE FROM lab_shipments WHERE run_id=%s", (run,))
        for stock in state["stock"]:
            setting = settings[stock["store"]]
            units = setting.stock_units if setting.enabled else 0
            delta = units - stock["on_hand"]
            conn.execute(
                "UPDATE lab_stock SET on_hand=%s WHERE run_id=%s AND store=%s AND sku=%s",
                (units, run, stock["store"], stock["sku"]),
            )
            conn.execute(
                """INSERT INTO lab_movements
                VALUES (%s,%s,%s,%s,0,'configured_opening',%s,0)""",
                (
                    run,
                    f"config:{stock['store']}:{stock['sku']}",
                    stock["store"],
                    stock["sku"],
                    delta,
                ),
            )
        serial = 0
        for store in city["stores"]:
            setting = settings[store["id"]]
            for _ in range(setting.couriers if setting.enabled else 0):
                serial += 1
                conn.execute(
                    "INSERT INTO lab_fleet(run_id,id,node,home_store) VALUES (%s,%s,%s,%s)",
                    (run, f"bike-{serial}", store["node"], store["id"]),
                )
        fleet = conn.execute(
            "SELECT id,node,home_store FROM lab_fleet WHERE run_id=%s ORDER BY id", (run,)
        ).fetchall()
        orders = demand_schedule(config, state["stock"])
        failures = dropout_schedule(config, fleet)
        conn.execute(
            """INSERT INTO lab_city_configs(run_id,config,order_schedule,dropout_schedule)
            VALUES (%s,%s,%s,%s)""",
            (run, Jsonb(config.model_dump(mode="json")), Jsonb(orders), Jsonb(failures)),
        )
        conn.execute("INSERT INTO lab_fleet_scenarios(run_id) VALUES (%s)", (run,))
    return run


def release_orders(
    run: str, schedule: list[dict[str, Any]], sim: int, url: str | None = None
) -> None:
    with connect(url) as conn:
        for order in schedule:
            if order["arrival_sim"] > sim:
                continue
            inserted = conn.execute(
                """INSERT INTO lab_fulfillments(run_id,basket,store,customer_node,deadline_sim)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING basket""",
                (
                    run,
                    order["basket"],
                    order["store"],
                    order["customer_node"],
                    order["deadline_sim"],
                ),
            ).fetchone()
            if not inserted:
                continue
            publish(
                conn,
                run_id=run,
                producer="lab_scenario",
                topic="basket.requested",
                payload={
                    "basket": order["basket"],
                    "store": order["store"],
                    "sku": order["sku"],
                    "quantity": 1,
                    "expires_sim": order["deadline_sim"],
                    "deliver": True,
                },
                key=order["basket"],
                trace_id=order["basket"],
                target_store=order["store"],
                due_sim=order["arrival_sim"],
            )


def run_city(run: str, url: str | None = None) -> dict[str, Any]:
    with connect(url) as conn:
        row = conn.execute("SELECT * FROM lab_city_configs WHERE run_id=%s", (run,)).fetchone()
        if not row:
            raise ValueError("Unknown configured city")
        config = CitySettings.model_validate(row["config"])
        started = conn.execute(
            """UPDATE runs SET status='running' WHERE id=%s
            AND status='ready' RETURNING id""",
            (run,),
        ).fetchone()
        if not started:
            raise ValueError("City session must be ready; settings are frozen")
        conn.execute(
            """INSERT INTO lab_incidents(run_id,sim_time,kind,detail)
            VALUES (%s,0,'traffic_configuration',%s)""",
            (run, Jsonb({"factor": config.traffic_multiplier})),
        )
    schedule = row["order_schedule"]
    failures = row["dropout_schedule"]
    end = config.duration_minutes * 60 + 3600
    checkpoints: list[dict[str, Any]] = []
    completion_reason = "window_ended"
    clock = time.monotonic()
    try:
        agents = {
            access.store: create_agent(access.dsn)
            for role in ("inventory", "fulfillment", "dispatcher", "courier", "judge")
            for access in role_access(run, role, url).values()
        }
        sim = 0
        for _cycle in range(1600):
            release_orders(run, schedule, sim, url)
            with connect(url) as conn:
                due = conn.execute(
                    """SELECT target_store,min(id) AS first FROM events WHERE run_id=%s
                    AND state='ready' AND due_sim<=%s AND available_at<=clock_timestamp()
                    GROUP BY target_store ORDER BY first""",
                    (run, sim),
                ).fetchall()
            handled = False
            for item in due:
                agent = agents.get(item["target_store"])
                if agent and (event := agent.claim()):
                    if not agent.process(event):
                        with connect(url) as conn:
                            failure = conn.execute(
                                "SELECT error FROM events WHERE id=%s", (event.id,)
                            ).fetchone()
                        if failure and failure["error"] == "BudgetExceeded":
                            completion_reason = "budget_limit"
                            break
                        raise RuntimeError("CityAgentStepFailed")
                    handled = True
                    break
            if completion_reason == "budget_limit":
                break
            if handled:
                continue
            queue = Queue(url)
            for role in ("inventory_audit", "delivery_audit"):
                while event := queue.claim(role, run, sim):
                    if not queue.process(event, lambda conn, msg: None):
                        raise RuntimeError("CityAuditFailed")
            state = flow_snapshot(run, url)
            if not all(state["invariants"].values()):
                raise RuntimeError("CityInvariantViolation")
            if sim >= end:
                break
            candidates = [min(sim + 60, end)]
            candidates.extend(o["arrival_sim"] for o in schedule if o["arrival_sim"] > sim)
            candidates.extend(t for t in failures.values() if sim < t <= end)
            candidates.extend(
                j["arrive_sim"]
                for j in state["jobs"]
                if j["status"] in {"assigned", "in_transit"}
                and j["accepted"]
                and j["arrive_sim"] > sim
            )
            with connect(url) as conn:
                future = conn.execute(
                    """SELECT min(due_sim) AS due FROM events
                    WHERE run_id=%s AND state='ready' AND due_sim>%s""",
                    (run, sim),
                ).fetchone()
            if future and future["due"] is not None:
                candidates.append(future["due"])
            sim = min(candidates)
            if config.playback_seconds:
                target = clock + config.playback_seconds * sim / end
                time.sleep(max(0, min(1, target - time.monotonic())))
            advance_fleet(
                run,
                sim,
                url,
                dropouts={courier for courier, instant in failures.items() if instant <= sim},
            )
            if len(checkpoints) < 200:
                checkpoints.append(
                    {
                        "sim_time": state["run"]["sim_time"],
                        "jobs": state["jobs"],
                        "fleet": state["fleet"],
                    }
                )
        else:
            raise RuntimeError("CityStepLimit")
        final_state = flow_snapshot(run, url)
        summary = {
            "scheduled_orders": len(schedule),
            "demand_cap": 24,
            "completion_reason": completion_reason,
            "observation_end_sim": final_state["run"]["sim_time"],
            "unfinished_jobs": sum(
                j["status"] not in {"delivered", "abandoned"} for j in final_state["jobs"]
            ),
        }
        with connect(url) as conn:
            conn.execute(
                "UPDATE lab_city_configs SET summary=%s WHERE run_id=%s", (Jsonb(summary), run)
            )
            conn.execute("UPDATE runs SET status='complete' WHERE id=%s", (run,))
        result = flow_snapshot(run, url)
        result["checkpoints"] = checkpoints
        result["session_summary"] = summary
        return result
    except Exception as exc:
        with connect(url) as conn:
            conn.execute(
                "UPDATE runs SET status='failed',error=%s WHERE id=%s", (type(exc).__name__, run)
            )
        raise
    finally:
        retire_inventory_access(run, url)


def agent_inspection(run: str, agent_id: str, url: str | None = None) -> dict[str, Any] | None:
    """Trusted human operator projection; never injected into another agent's context."""
    with connect(url) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        binding = conn.execute(
            """SELECT b.*,r.sim_time FROM agent_bindings b JOIN runs r ON r.id=b.run_id
            WHERE b.run_id=%s AND b.agent_id=%s""",
            (run, agent_id),
        ).fetchone()
        if not binding:
            return None
        definition = binding["definition"]
        budget = conn.execute(
            "SELECT * FROM agent_budgets WHERE run_id=%s AND store=%s", (run, binding["store"])
        ).fetchone()
        memory = conn.execute(
            """SELECT key,body,observed_sim,expires_sim,event_id FROM agent_memories
            WHERE run_id=%s AND store=%s AND expires_sim>%s ORDER BY key""",
            (run, binding["store"], binding["sim_time"]),
        ).fetchall()
        briefs = []
        if definition["role"] == "courier":
            briefs = conn.execute(
                """SELECT basket,attempt,body,created_sim FROM lab_briefs
                WHERE run_id=%s AND courier=%s ORDER BY created_sim""",
                (run, agent_id.removeprefix("courier:")),
            ).fetchall()
        config_row = conn.execute(
            "SELECT config FROM lab_city_configs WHERE run_id=%s", (run,)
        ).fetchone()
        config = config_row["config"] if config_row else {}
        role = definition["role"]
        home = binding["store"].removeprefix("fulfillment:")
        if role == "courier":
            staff = conn.execute(
                "SELECT home_store,status FROM lab_fleet WHERE run_id=%s AND id=%s",
                (run, agent_id.removeprefix("courier:")),
            ).fetchone()
            home = staff["home_store"] if staff else None
        parameters: dict[str, Any] = {"memory_ttl_seconds": 3600, "settings_apply": "next_session"}
        if role in {"inventory", "fulfillment", "courier"}:
            parameters["home_store"] = home
            parameters["store"] = next(
                (s for s in config.get("stores", []) if s["id"] == home), None
            )
        if role in {"dispatcher", "courier", "judge"}:
            parameters["traffic_multiplier"] = config.get("traffic_multiplier", 2)
        if role == "courier":
            parameters["dropout_rate_per_hour"] = config.get("dropout_rate")
        if role == "judge":
            parameters.update(max_total_attempts=2, max_retry_route_minutes=100)
        expired = conn.execute(
            """SELECT count(*) AS n FROM agent_memories
            WHERE run_id=%s AND store=%s AND expires_sim<=%s""",
            (run, binding["store"], binding["sim_time"]),
        ).fetchone()
        return {
            "agent": {
                "agent_id": agent_id,
                "store": binding["store"],
                "definition_hash": binding["definition_hash"],
                **definition,
                "budget": budget,
            },
            "memory": memory,
            "expired_memory_count": expired["n"] if expired else 0,
            "parameters": parameters,
            "briefs": briefs,
        }

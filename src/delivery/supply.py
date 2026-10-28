"""Trusted local supply world. Every evaluated agent operates through its scoped login."""

import hashlib
import json
import secrets
import time
from decimal import Decimal
from threading import Lock
from typing import Any

from psycopg.types.json import Jsonb

from delivery.agent_access import retire_inventory_access, role_access
from delivery.agent_runtime import LocalAgent, create_agent
from delivery.db import connect
from delivery.delivery_flow import new_delivery
from delivery.fleet_flow import advance_fleet
from delivery.queue import Event, Queue, publish
from delivery.supply_models import (
    SupplyConfig,
    default_config,
    demand_schedule,
    ingredient_units,
    recipes,
)
from delivery.urban_city import urban_city

_AGENTS: dict[tuple[str, str], LocalAgent] = {}
_TOKENS: dict[str, tuple[str, str, float]] = {}
CHANNEL_LEASES: dict[tuple[str, str, int], Event] = {}
_LOCK = Lock()
SUPPLY_ROLES = ("household", "restaurant", "market")


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return str(value)


def city_for(config: SupplyConfig) -> dict[str, Any]:
    from delivery.city import fake_city

    return urban_city(fake_city(config.seed, size=32))


def blueprint(url: str | None = None) -> tuple[SupplyConfig, str]:
    with connect(url) as conn:
        row = conn.execute(
            "SELECT config,revision FROM supply_blueprints WHERE id='default'"
        ).fetchone()
    if row:
        return SupplyConfig.model_validate(row["config"]), row["revision"]
    config = default_config()
    return config, config.digest


def save_blueprint(config: SupplyConfig, revision: str, url: str | None = None) -> str:
    with connect(url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(918275)")
        row = conn.execute("SELECT revision FROM supply_blueprints WHERE id='default'").fetchone()
        expected = row["revision"] if row else default_config().digest
        if revision != expected:
            raise ValueError("Blueprint changed; reload before saving")
        conn.execute(
            """INSERT INTO supply_blueprints VALUES ('default',%s,%s)
            ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,config=excluded.config""",
            (config.digest, Jsonb(config.model_dump(mode="json"))),
        )
    return config.digest


def new_supply(config: SupplyConfig, url: str | None = None) -> str:
    run = new_delivery(config.seed, url)
    try:
        return _initialize_supply(run, config, url)
    except Exception:
        # The base city is already committed. Failed definition/schedule/bootstrap
        # work must not strand it before the caller can track its run ID.
        with connect(url) as conn:
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))
        raise


def _initialize_supply(run: str, config: SupplyConfig, url: str | None = None) -> str:
    city = city_for(config)
    schedule = demand_schedule(config)
    frozen = {**config.model_dump(mode="json"), "recipes": recipes(), "schedule": schedule}
    quantities = {ingredient: 0 for ingredient in ingredient_units()}
    for recipe in recipes():
        for item in recipe["ingredients"]:
            quantities[item["id"]] = max(quantities[item["id"]], item["quantity"])
    stock: list[dict[str, Any]] = []
    with connect(url) as conn:
        conn.execute("UPDATE lab_worlds SET city=%s WHERE run_id=%s", (Jsonb(city), run))
        conn.execute("DELETE FROM lab_shipments WHERE run_id=%s", (run,))
        conn.execute("UPDATE runs SET duration=%s WHERE id=%s", (config.duration_minutes * 60, run))
        conn.execute("INSERT INTO supply_sessions VALUES (%s,%s,'{}')", (run, Jsonb(frozen)))
        conn.execute(
            "INSERT INTO agent_run_budgets(run_id,events_limit,tools_limit) "
            "VALUES (%s,12000,48000)",
            (run,),
        )
        for entity in config.entities:
            conn.execute(
                "INSERT INTO supply_entities VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    run,
                    entity.id,
                    entity.kind,
                    entity.name,
                    entity.node,
                    Jsonb(entity.model_dump(mode="json")),
                ),
            )
            if entity.kind == "household":
                continue
            opening_stock = {str(key): value for key, value in entity.opening_stock.items()}
            for ingredient, unit in ingredient_units().items():
                servings = (
                    config.market_stock_servings
                    if entity.kind == "market"
                    else config.restaurant_stock_servings
                )
                units = quantities[ingredient] * servings
                # Deliberate, published scarcity in the synthetic city; never provider data.
                if entity.id == "market-c" and ingredient == "mozzarella":
                    units = 0
                if entity.id == "market-b" and ingredient == "salmon":
                    units = min(units, 50)
                units = opening_stock.get(ingredient, units)
                row = dict(
                    run_id=run,
                    owner=entity.id,
                    ingredient=ingredient,
                    unit=unit,
                    on_hand=units,
                    reserved=0,
                    version=0,
                )
                stock.append(row)
                conn.execute(
                    "INSERT INTO supply_stock VALUES (%s,%s,%s,%s,%s,0,0)",
                    (run, entity.id, ingredient, unit, units),
                )
        for order in schedule:
            conn.execute(
                """INSERT INTO supply_orders(run_id,id,household,restaurant,meal,quantity,deadline)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    run,
                    order["order_id"],
                    order["household"],
                    order["restaurant"],
                    order["meal"],
                    order["quantity"],
                    order["deadline_sim"],
                ),
            )
        markets = [entity for entity in config.entities if entity.kind == "market"]
        for index in range(config.fleet_couriers):
            market = markets[index % len(markets)]
            conn.execute(
                "INSERT INTO lab_fleet(run_id,id,node,home_store) VALUES (%s,%s,%s,%s)",
                (run, f"bike-{index + 1}", market.node, market.id),
            )
        conn.execute("INSERT INTO lab_fleet_scenarios(run_id) VALUES (%s)", (run,))
        opening = {
            "stock": stock,
            "orders": json.loads(
                json.dumps(
                    conn.execute(
                        "SELECT * FROM supply_orders WHERE run_id=%s ORDER BY id", (run,)
                    ).fetchall(),
                    default=json_value,
                )
            ),
            "requests": [],
            "allocations": [],
            "delivery_jobs": [],
        }
        conn.execute("UPDATE supply_sessions SET opening=%s WHERE run_id=%s", (Jsonb(opening), run))
    return run


def provision(run: str, url: str | None = None) -> dict[str, LocalAgent]:
    agents = {}
    for role in (*SUPPLY_ROLES, "dispatcher", "courier", "judge"):
        for access in role_access(run, role, url).values():
            agent = create_agent(access.dsn)
            agents[access.store] = agent
            with _LOCK:
                _AGENTS[(run, agent.scope.agent_id)] = agent
    return agents


def issue_channel(run: str, agent_id: str) -> str:
    with _LOCK:
        if (run, agent_id) not in _AGENTS:
            raise ValueError("Agent is not running")
        token = secrets.token_urlsafe(32)
        _TOKENS[hashlib.sha256(token.encode()).hexdigest()] = (
            run,
            agent_id,
            time.monotonic() + 3600,
        )
    return token


def authenticated_agent(run: str, agent_id: str, token: str) -> LocalAgent:
    with _LOCK:
        grant = _TOKENS.get(hashlib.sha256(token.encode()).hexdigest())
        agent = _AGENTS.get((run, agent_id))
    if not grant or grant[:2] != (run, agent_id) or grant[2] <= time.monotonic() or not agent:
        raise PermissionError("Invalid, expired or wrong-scope channel")
    return agent


def release_calls(
    run: str, schedule: list[dict[str, Any]], sim: int, url: str | None = None
) -> None:
    with connect(url) as conn:
        released = {
            row["dedupe_key"]
            for row in conn.execute(
                "SELECT dedupe_key FROM events WHERE run_id=%s AND producer='supply_ingress'",
                (run,),
            ).fetchall()
        }
        for call in schedule:
            key = f"intent:{call['order_id']}"
            if call["arrival_sim"] > sim or key in released:
                continue
            publish(
                conn,
                run_id=run,
                producer="supply_ingress",
                topic="household.intent",
                payload={"order": call["order_id"]},
                key=key,
                trace_id=call["order_id"],
                target_store=call["household"],
                due_sim=call["arrival_sim"],
            )


def run_supply(run: str, url: str | None = None) -> dict[str, Any]:
    with connect(url) as conn:
        session = conn.execute(
            "SELECT config FROM supply_sessions WHERE run_id=%s", (run,)
        ).fetchone()
        if not session:
            raise ValueError("Unknown supply run")
        started = conn.execute(
            "UPDATE runs SET status='running' WHERE id=%s AND status='ready' RETURNING id", (run,)
        ).fetchone()
        if not started:
            raise ValueError("Supply run is immutable after starting")
    config = session["config"]
    schedule = config["schedule"]
    end = config["duration_minutes"] * 60 + 7200
    clock = time.monotonic()
    sim = 0
    try:
        agents = provision(run, url)
        for _ in range(20000):
            release_calls(run, schedule, sim, url)
            with connect(url) as conn:
                due = conn.execute(
                    """SELECT target_store,min(id) first FROM events WHERE run_id=%s
                    AND (state='ready' OR (state='leased' AND lease_until<clock_timestamp()))
                    AND due_sim<=%s AND available_at<=clock_timestamp()
                    GROUP BY target_store ORDER BY first""",
                    (run, sim),
                ).fetchall()
            handled = False
            for item in due:
                agent = agents.get(item["target_store"])
                if agent and (event := agent.claim()):
                    if not agent.process(event):
                        with connect(url) as conn:
                            failed = conn.execute(
                                "SELECT state FROM events WHERE id=%s", (event.id,)
                            ).fetchone()
                        if failed and failed["state"] == "dead":
                            raise RuntimeError("SupplyDeadLetter")
                    handled = True
                    break
            if handled:
                continue
            with connect(url) as conn:
                leased = conn.execute(
                    "SELECT 1 FROM events WHERE run_id=%s AND "
                    "((state='leased' AND lease_until>clock_timestamp()) OR "
                    "(state='ready' AND due_sim<=%s AND available_at>clock_timestamp())) LIMIT 1",
                    (run, sim),
                ).fetchone()
            if leased:
                time.sleep(0.025)  # A remote channel may be handling the current event.
                continue
            queue = Queue(url)
            for role in ("delivery_audit", "inventory_audit"):
                while event := queue.claim(role, run, sim):
                    if not queue.process(event, lambda conn, msg: None):
                        raise RuntimeError("SupplyAuditFailed")
            if sim >= end:
                break
            candidates = [min(sim + 60, end)]
            candidates.extend(o["arrival_sim"] for o in schedule if o["arrival_sim"] > sim)
            with connect(url) as conn:
                future = conn.execute(
                    "SELECT min(due_sim) due FROM events "
                    "WHERE run_id=%s AND state='ready' AND due_sim>%s",
                    (run, sim),
                ).fetchone()
                if future and future["due"] is not None:
                    candidates.append(future["due"])
                pending = conn.execute(
                    "SELECT count(*) n FROM supply_orders WHERE run_id=%s "
                    "AND status NOT IN ('delivered','failed')",
                    (run,),
                ).fetchone()
                active_jobs = conn.execute(
                    "SELECT 1 FROM lab_delivery_jobs WHERE run_id=%s "
                    "AND status NOT IN ('delivered','abandoned') LIMIT 1",
                    (run,),
                ).fetchone()
                if (
                    pending
                    and not pending["n"]
                    and not active_jobs
                    and not (future and future["due"] is not None)
                    and sim >= max((o["arrival_sim"] for o in schedule), default=0)
                ):
                    break
            sim = min(candidates)
            if config["playback_seconds"]:
                target = clock + config["playback_seconds"] * sim / end
                time.sleep(max(0, min(1, target - time.monotonic())))
            advance_fleet(run, sim, url, dropouts=set())
        else:
            raise RuntimeError("SupplyStepLimit")
        with connect(url) as conn:
            conn.execute("UPDATE runs SET status='complete' WHERE id=%s", (run,))
        return supply_snapshot(run, url)
    except Exception as exc:
        with connect(url) as conn:
            conn.execute(
                "UPDATE runs SET status='failed',error=%s WHERE id=%s", (type(exc).__name__, run)
            )
        raise
    finally:
        with _LOCK:
            for key in list(_AGENTS):
                if key[0] == run:
                    del _AGENTS[key]
            for token, grant in list(_TOKENS.items()):
                if grant[0] == run:
                    del _TOKENS[token]
            for lease_key in list(CHANNEL_LEASES):
                if lease_key[0] == run:
                    del CHANNEL_LEASES[lease_key]
        retire_inventory_access(run, url)


def supply_snapshot(run: str, url: str | None = None) -> dict[str, Any]:
    with connect(url) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        session = conn.execute("SELECT * FROM supply_sessions WHERE run_id=%s", (run,)).fetchone()
        if not session:
            raise ValueError("Unknown supply run")
        world_row = conn.execute("SELECT city FROM lab_worlds WHERE run_id=%s", (run,)).fetchone()
        assert world_row
        state: dict[str, Any] = {
            "run": conn.execute(
                "SELECT id,status,sim_time,error FROM runs WHERE id=%s", (run,)
            ).fetchone(),
            "city": world_row["city"],
            "config": session["config"],
        }
        for key, table, order in (
            ("entities", "supply_entities", "id"),
            ("stock", "supply_stock", "owner,ingredient"),
            ("orders", "supply_orders", "id"),
            ("requests", "supply_requests", "id"),
            ("jobs", "lab_delivery_jobs", "basket"),
            ("fleet", "lab_fleet", "id"),
        ):
            state[key] = conn.execute(
                f"SELECT * FROM {table} WHERE run_id=%s ORDER BY {order}", (run,)
            ).fetchall()
        state["events"] = conn.execute(
            """SELECT id,topic,producer,target_store,due_sim,state,trace_id,
            parent_id,payload,attempts
            FROM events WHERE run_id=%s ORDER BY id DESC LIMIT 1000""",
            (run,),
        ).fetchall()[::-1]
        state["facts"] = conn.execute(
            """SELECT sequence,event_id,order_id,actor,kind,sim_time,hash,parent_hash,
            payload->'detail' payload
            FROM supply_facts WHERE run_id=%s ORDER BY sequence DESC LIMIT 100""",
            (run,),
        ).fetchall()[::-1]
        state["agents"] = []
        for binding in conn.execute(
            "SELECT agent_id,store,definition,definition_hash FROM agent_bindings "
            "WHERE run_id=%s ORDER BY agent_id",
            (run,),
        ).fetchall():
            definition = binding["definition"]
            entity = next((e for e in state["entities"] if e["id"] == binding["store"]), None)
            settings_data = (
                (
                    entity["definition"].get("agent")
                    or session["config"]["agents"][definition["role"]]
                )
                if entity
                else {}
            )
            state["agents"].append(
                {
                    "agent_id": binding["agent_id"],
                    "entity_id": binding["store"],
                    "role": definition["role"],
                    "display_name": settings_data.get("display_name", binding["agent_id"]),
                    "definition": definition,
                    "definition_hash": binding["definition_hash"],
                    "budget": conn.execute(
                        "SELECT * FROM agent_budgets WHERE run_id=%s AND store=%s",
                        (run, binding["store"]),
                    ).fetchone(),
                }
            )
        stock_ok = all(0 <= s["reserved"] <= s["on_hand"] for s in state["stock"])
        consumed = conn.execute(
            "SELECT ingredient,sum(quantity) quantity FROM supply_allocations "
            "WHERE run_id=%s AND consumed GROUP BY ingredient",
            (run,),
        ).fetchall()
        conserved = True
        for ingredient in ingredient_units():
            opening_quantity = sum(
                Decimal(str(s["on_hand"]))
                for s in session["opening"]["stock"]
                if s["ingredient"] == ingredient
            )
            accounted_quantity = (
                sum(s["on_hand"] for s in state["stock"] if s["ingredient"] == ingredient)
                + sum(a["quantity"] for a in consumed if a["ingredient"] == ingredient)
                + sum(
                    q["quantity"]
                    for q in state["requests"]
                    if q["ingredient"] == ingredient and q["status"] == "transit"
                )
            )
            conserved = conserved and opening_quantity == accounted_quantity
        invalid_units = conn.execute(
            "SELECT count(*) n FROM supply_stock "
            "WHERE run_id=%s AND unit NOT IN ('g','ml','piece')",
            (run,),
        ).fetchone()
        assert invalid_units
        state["invariants"] = {
            "stock_nonnegative": stock_ok,
            "stock_conserved": conserved,
            "canonical_units": invalid_units["n"] == 0,
        }
        counts = conn.execute(
            "SELECT count(*) events,max(attempts) max_attempts, "
            "count(*) FILTER(WHERE state='dead') dead_letters, "
            "coalesce(sum(greatest(0,attempts-1)),0) retries FROM events WHERE run_id=%s",
            (run,),
        ).fetchone()
        assert counts
        search_totals = conn.execute(
            "SELECT coalesce(sum(calls_reserved),0) calls, "
            "coalesce(sum(input_tokens_reserved),0) tokens "
            "FROM supply_search_budgets WHERE run_id=%s",
            (run,),
        ).fetchone()
        search_calls = int(search_totals["calls"]) if search_totals else 0
        search_usage = conn.execute(
            "SELECT count(*) FILTER(WHERE status='ok') confirmed, "
            "count(*) FILTER(WHERE status<>'ok') unknown, sum(actual_input_tokens) input_tokens, "
            "sum(actual_output_tokens) output_tokens FROM supply_search_calls WHERE run_id=%s",
            (run,),
        ).fetchone()
        assert search_usage
        state["metrics"] = {
            "scheduled_calls": len(session["config"]["schedule"]),
            "events": counts["events"],
            "dead_letters": counts["dead_letters"],
            "retries": int(counts["retries"]),
            "delivered": sum(o["status"] == "delivered" for o in state["orders"]),
            "unfinished_orders": sum(
                o["status"] not in {"delivered", "failed"} for o in state["orders"]
            ),
            "open_delivery_jobs": sum(
                j["status"] not in {"delivered", "abandoned"} for j in state["jobs"]
            ),
            "late_physical_deliveries": sum(
                j["status"] == "delivered" and j["arrive_sim"] > j["deadline_sim"]
                for j in state["jobs"]
            ),
            "model_calls": search_usage["confirmed"],
            "model_provider": "jev" if search_calls else "disabled",
            "search_reserved_calls": search_calls,
            "search_reserved_input_tokens": int(search_totals["tokens"]) if search_totals else 0,
            "search_unknown_usage_calls": search_usage["unknown"],
            "search_actual_input_tokens": search_usage["input_tokens"],
            "search_actual_output_tokens": search_usage["output_tokens"],
            "decision_mode": "local_rules",
            "transport": "durable_queue",
            "call_mode": "simulated_transcript",
            "communication_latency_seconds": session["config"]["communication_latency_seconds"],
        }
        calls = {call["order_id"]: call for call in session["config"]["schedule"]}
        state["calls"] = session["config"]["schedule"]
        for order in state["orders"]:
            order["transcript"] = calls.get(order["id"], {}).get("transcript", "")
    return state


def replay_supply(run: str, url: str | None = None) -> dict[str, Any]:
    """Rebuild business projections from opening state + recorded facts, never rerun agents."""
    keys = {
        "stock": ("owner", "ingredient"),
        "orders": ("id",),
        "requests": ("id",),
        "allocations": ("order_id", "ingredient"),
        "delivery_jobs": ("basket",),
    }
    with connect(url) as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        session = conn.execute(
            "SELECT opening FROM supply_sessions WHERE run_id=%s", (run,)
        ).fetchone()
        if not session:
            raise ValueError("Unknown supply run")
        facts = conn.execute(
            "SELECT *,payload::text canonical_payload FROM supply_facts "
            "WHERE run_id=%s ORDER BY sequence",
            (run,),
        ).fetchall()
        rebuilt = {
            name: {tuple(row[k] for k in fields): row for row in session["opening"].get(name, [])}
            for name, fields in keys.items()
        }
        parent = "0" * 64
        verified = True
        for fact in facts:
            expected = hashlib.sha256((parent + fact["canonical_payload"]).encode()).hexdigest()
            verified = verified and fact["parent_hash"] == parent and fact["hash"] == expected
            parent = fact["hash"]
            for name, rows in fact["payload"].get("projection", {}).items():
                if name not in keys:
                    continue
                for row in rows:
                    rebuilt[name][tuple(row[k] for k in keys[name])] = row
        matches = {}
        for name, fields in keys.items():
            table = "lab_delivery_jobs" if name == "delivery_jobs" else f"supply_{name}"
            live = json.loads(
                json.dumps(
                    conn.execute(f"SELECT * FROM {table} WHERE run_id=%s", (run,)).fetchall(),
                    default=json_value,
                )
            )
            expected_rows = {tuple(row[k] for k in fields): row for row in live}
            matches[name] = expected_rows == rebuilt[name]
    return {
        "matches": verified and all(matches.values()),
        "hash_chain_valid": verified,
        "projections": matches,
        "facts": len(facts),
        "hash": parent,
        "counts": {key: len(value) for key, value in rebuilt.items()},
        "model_calls": 0,
    }

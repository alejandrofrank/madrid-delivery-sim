"""One explicit paid, six-run routing comparison; never resume or retry dispatch.

The permanent execution marker uses a dedicated operator-mounted experiment
directory, independently of the retained UI receipt. An interrupted run requires
operator inspection, not another invocation. Admission ceilings are $0.54 Vertex
and <$0.01 Jev, within $0.60 total.
"""

import argparse
import hashlib
import json
import math
import os
import statistics
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from demo_adk_restaurants import configuration
from demo_adk_vertex import save_receipt

from delivery.adk_contracts import JevRouting, VertexProfile
from delivery.adk_evidence import run_evidence
from delivery.config import settings
from delivery.db import connect, migrate
from delivery.health_report import source_fingerprint
from delivery.jev_routing import checked_answer
from delivery.supply import new_supply, replay_supply, run_supply, supply_snapshot
from delivery.supply_models import SupplyConfig

JEV_TARIFF = Decimal("0.042")
MILLION = Decimal(1000000)
VERTEX_LIMIT = Decimal("0.54")
JEV_LIMIT = Decimal("0.01")
TOTAL_LIMIT = Decimal("0.60")
MEMORY = {"mode": "typed", "max_facts": 8, "max_bytes": 8192, "ttl_seconds": 3600}
SCENARIOS = (("speed", "market-a"), ("cost", "market-b"), ("reasoning", "market-a"))
BASELINE_SEARCH = (
    "\nFor household.call only, use search_ingredients once with query mozzarella "
    "before staging sourcing. This is a Jev relevance check, not a stock reservation. "
    "Do not search on subsequent arrival/cooking events. Batch independent read tools "
    "in one response when possible. Always finish the staged action."
)
REASONING_SOUL = (
    "\nFor household.call, I explicitly request a reasoned fast-versus-cheap tradeoff "
    "explanation before choosing a supplier. Compare the fastest quoted supplier's "
    "lead time and fee with the cheapest quoted supplier's lead time and fee. Explain "
    "why the faster service justifies the extra fee for this order, then choose the "
    "shortest quoted lead time, breaking ties by fee. Include that explanation in "
    "finish_decision's summary; a bare fixed-rule selection is insufficient."
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def fingerprint(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def money(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def approved_profile() -> VertexProfile:
    if os.environ.get("DELIVERY_ADK_VERTEX_ENABLED") != "1":
        raise PermissionError("The approved Vertex deployment must be explicitly enabled")
    if os.environ.get("DELIVERY_JEV_ENABLED") != "1":
        raise PermissionError("The approved Jev deployment must be explicitly enabled")
    if os.environ.get("TYPESAFE_MODEL") != "jev-1.14.0":
        raise PermissionError("Pin the reviewed Jev model to jev-1.14.0")
    profile = VertexProfile.model_validate_json(os.environ["DELIVERY_ADK_VERTEX_PROFILE"])
    if (profile.model, profile.location) != ("gemini-3.5-flash-lite", "global"):
        raise PermissionError("Only the reviewed native Gemini model and location are approved")
    tariff = (
        profile.input_usd_per_million,
        profile.output_usd_per_million,
        profile.cached_input_usd_per_million,
    )
    if tariff != (0.30, 2.50, 0.03):
        raise PermissionError("The frozen Vertex tariff differs from the reviewed profile")
    database = urlsplit(settings().database_url)
    if database.hostname not in {"postgres", "localhost", "127.0.0.1", "::1"} or (
        database.path != "/delivery"
    ):
        raise PermissionError("This comparison requires the retained local delivery database")
    return profile


def arm_configuration(scenario: str, variant: str, profile: VertexProfile) -> SupplyConfig:
    data = configuration("cost" if scenario == "cost" else "speed").model_dump(mode="json")
    for agent in data["agents"].values():
        agent["memory"] = dict(MEMORY)
    restaurant = next(entity for entity in data["entities"] if entity["kind"] == "restaurant")
    agent = restaurant["agent"]
    agent["memory"] = dict(MEMORY)
    if scenario == "reasoning":
        agent["soul"] += REASONING_SOUL
    brain = agent["brain"]
    brain.update(
        provider="vertex",
        vertex=profile.model_dump(mode="json"),
        usd_limit=0.14 if variant == "baseline" else 0.04,
        model_calls_per_event=8,
        model_calls_per_run=60,
        timeout_seconds=30,
        output_tokens=1024,
        routing=None,
    )
    if "supply.search" not in brain["tools"]:
        brain["tools"].append("supply.search")
    agent["search"] = {"provider": "jev", "calls_limit": 3, "input_tokens_limit": 24000}
    if variant == "baseline":
        brain["instructions"] += BASELINE_SEARCH
    else:
        brain["routing"] = JevRouting(
            confidence_threshold=0.85,
            margin_threshold=0.20,
            calls_per_run=32,
            input_tokens_per_run=16000,
            usd_limit=0.001,
        ).model_dump(mode="json")
        brain["instructions"] += (
            "\nIf an escalated Gemini turn needs an ingredient relevance check, "
            "search_ingredients is optional within the declared search caps. "
            "A search is not required before sourcing and does not reserve stock."
        )
    return SupplyConfig.model_validate(data)


def planned_arms(profile: VertexProfile) -> list[dict[str, Any]]:
    arms = []
    for scenario, expected in SCENARIOS:
        pair = []
        for variant in ("baseline", "cascade"):
            config = arm_configuration(scenario, variant, profile).model_dump(mode="json")
            restaurant = next(e for e in config["entities"] if e["kind"] == "restaurant")
            arm = {
                "id": f"{scenario}-{variant}",
                "label": "Current model tool loop" if variant == "baseline" else "Jev first",
                "scenario": scenario,
                "soul": scenario,
                "variant": variant,
                "expected_supplier": expected,
                "status": "planned",
                "run": None,
                "memory_mode": MEMORY["mode"],
                "configuration": config,
                "configuration_sha256": fingerprint(config),
                "soul_sha256": fingerprint(restaurant["agent"]["soul"]),
                "metrics": {},
                "cost": {},
                "provider_calls": {},
                "outcome_checks": {},
                "route_breakdown": {},
                "route_decisions": [],
            }
            pair.append(arm)
        if pair[0]["soul_sha256"] != pair[1]["soul_sha256"]:
            raise ValueError("Paired arms must use exactly the same SOUL")
        arms.extend(pair)
    return arms


def admission_plan(arms: list[dict[str, Any]]) -> dict[str, Any]:
    vertex = Decimal(0)
    search_tokens = route_tokens = 0
    route_money = Decimal(0)
    for arm in arms:
        config = arm["configuration"]
        restaurants = [entity for entity in config["entities"] if entity["kind"] == "restaurant"]
        if len(restaurants) != 1 or config["calls_per_household"] != 1:
            raise ValueError("Each benchmark arm must contain exactly one restaurant and call")
        if sum(entity["kind"] == "household" for entity in config["entities"]) != 1:
            raise ValueError("Each benchmark arm must contain exactly one household")
        agent = restaurants[0]["agent"]
        vertex += money(agent["brain"]["usd_limit"])
        search_tokens += agent["search"]["input_tokens_limit"]
        route = agent["brain"].get("routing")
        if route:
            route_tokens += route["input_tokens_per_run"]
            route_money += money(route["usd_limit"])
    jev_worst = Decimal(search_tokens + route_tokens) * JEV_TARIFF / MILLION
    jev_admission = Decimal(search_tokens) * JEV_TARIFF / MILLION + route_money
    if len(arms) != 6 or vertex > VERTEX_LIMIT or jev_worst >= JEV_LIMIT:
        raise PermissionError("The fixed six-run comparison exceeds its reviewed admission caps")
    if jev_admission >= JEV_LIMIT or vertex + jev_admission > TOTAL_LIMIT:
        raise PermissionError("The combined admission ceiling exceeds the reviewed allowance")
    return {
        "vertex_admission_limit_usd": str(vertex),
        "jev_search_input_token_limit": search_tokens,
        "jev_router_input_token_limit": route_tokens,
        "jev_tariff_usd_per_million_input_tokens": str(JEV_TARIFF),
        "jev_maximum_usd_at_tariff": str(jev_worst),
        "jev_conservative_admission_usd": str(jev_admission),
        "combined_conservative_admission_usd": str(vertex + jev_admission),
        "total_ceiling_usd": str(TOTAL_LIMIT),
    }


def operator_receipts(run: str) -> tuple[str, dict[str, int], list[dict[str, Any]]]:
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        status = conn.execute("SELECT status FROM runs WHERE id=%s", (run,)).fetchone()
        queue = conn.execute(
            "SELECT state,count(*) n FROM events WHERE run_id=%s GROUP BY state", (run,)
        ).fetchall()
        routes = conn.execute(
            "SELECT r.* FROM restaurant_routes r JOIN restaurant_turns t USING(event_id) "
            "WHERE t.run_id=%s ORDER BY r.event_id",
            (run,),
        ).fetchall()
    if not status:
        raise ValueError("Saved benchmark run is missing")
    return status["status"], {row["state"]: row["n"] for row in queue}, routes


def account_evidence(evidence: dict[str, Any], routes: list[dict[str, Any]]) -> dict[str, Any]:
    vertex = [call for call in evidence["calls"] if call["provider"] == "vertex"]
    search = evidence["jev_calls"]
    router = [route for route in routes if route.get("model") is not None]
    vertex_cost = sum((money(call["usage_cost_usd"]) for call in vertex), Decimal(0))
    jev_tokens = sum(call["actual_input_tokens"] or 0 for call in search)
    jev_tokens += sum(route["input_tokens"] or 0 for route in router)
    jev_cost = Decimal(jev_tokens) * JEV_TARIFF / MILLION
    unknown = sum(call["usage_cost_usd"] is None for call in vertex)
    unknown += sum(call["actual_input_tokens"] is None for call in search)
    unknown += sum(route["input_tokens"] is None for route in router)
    vertex_admitted = sum((money(call["reserved_usd"]) for call in vertex), Decimal(0))
    search_admitted = (
        Decimal(sum(call["reserved_input_tokens"] for call in search)) * JEV_TARIFF / MILLION
    )
    router_admitted = sum((money(route["reserved_usd"]) for route in router), Decimal(0))
    accounted_vertex = sum(
        (max(money(call["usage_cost_usd"]), money(call["reserved_usd"])) for call in vertex),
        Decimal(0),
    )
    accounted_jev = sum(
        (
            max(
                Decimal(call["actual_input_tokens"] or 0) * JEV_TARIFF / MILLION,
                Decimal(call["reserved_input_tokens"]) * JEV_TARIFF / MILLION,
            )
            for call in search
        ),
        Decimal(0),
    )
    accounted_jev += sum(
        (
            max(
                Decimal(route["input_tokens"] or 0) * JEV_TARIFF / MILLION,
                money(route["reserved_usd"]),
            )
            for route in router
        ),
        Decimal(0),
    )
    gemini_ms = [value for call in vertex if (value := numeric(call.get("latency_ms"))) is not None]
    router_ms = [value for row in router if (value := numeric(row.get("latency_ms"))) is not None]
    aggregate_search_ms = [
        value
        for row in evidence["searches"]
        if (value := numeric(row.get("duration_ms"))) is not None
    ]
    return {
        "cost": {
            "vertex_usd": str(vertex_cost),
            "jev_usd": str(jev_cost),
            "total_usd": str(vertex_cost + jev_cost),
            "unknown_calls": unknown,
            "vertex_reserved_usd": str(vertex_admitted),
            "jev_search_admitted_usd_at_tariff": str(search_admitted),
            "jev_router_reserved_usd": str(router_admitted),
            "admission_usd": str(vertex_admitted + search_admitted + router_admitted),
            "jev_accounted_usd": str(accounted_jev),
            "accounted_usd": str(accounted_vertex + accounted_jev),
            "accounted_basis": (
                "Each call uses the larger of known token cost and its admission; "
                "unknown usage retains its admission. This is not an invoice total."
            ),
            "jev_search_usd": str(
                Decimal(sum(c["actual_input_tokens"] or 0 for c in search)) * JEV_TARIFF / MILLION
            ),
            "jev_router_usd": str(
                Decimal(sum(r["input_tokens"] or 0 for r in router)) * JEV_TARIFF / MILLION
            ),
            "basis": "Known provider input/output usage at frozen tariffs; invoice not reconciled",
            "invoice_usd": None,
        },
        "provider_calls": {
            "gemini": len(vertex),
            "jev": len(search) + len(router),
            "jev_search": len(search),
            "jev_router": len(router),
        },
        "median_latency_ms": median(gemini_ms + router_ms),
        "latency": {
            "gemini_provider_p50_ms": median(gemini_ms),
            "jev_router_provider_p50_ms": median(router_ms),
            "provider_p50_ms": median(gemini_ms + router_ms),
            "provider_samples": len(gemini_ms) + len(router_ms),
            "provider_samples_missing": len(vertex) + len(router) - len(gemini_ms) - len(router_ms),
            "legacy_search_operation_durations_ms": aggregate_search_ms,
            "basis": "Provider p50 pools Gemini calls and paid Jev router calls only. Legacy "
            "search durations are aggregate operations, not individual Jev provider latency; "
            "they are excluded. Baseline and cascade provider mixes may differ.",
        },
    }


def jev_requested_gemini(route: dict[str, Any], completed_gemini: set[int]) -> bool:
    """Prove a validated Jev choice, rather than provider/parser-error fallback."""
    if (
        route.get("state") != "completed"
        or route.get("executor") != "gemini"
        or route.get("model") != "jev-1.14.0"
        or route.get("error_code") is not None
        or route.get("reason") != "jev_requested_reasoning_model"
        or route.get("event_id") not in completed_gemini
    ):
        return False
    try:
        raw, request = route["response_body"], route["request_body"]
        if request["model"] != "jev-1.14.0":
            return False
        checked_answer(raw, request)
        return (
            raw["answers"]["executor"]["choice"] == "gemini"
            and raw["usage"]["input_tokens"] <= route["reserved_input_tokens"]
        )
    except (ValueError, KeyError, TypeError):
        return False


def finish_arm(arm: dict[str, Any], profile: VertexProfile) -> None:
    run = arm["run"]
    state = supply_snapshot(run)
    replay = replay_supply(run)
    status, queue, routes = operator_receipts(run)
    evidence = run_evidence(run, profile)
    evidence["routing_decisions"] = routes
    evidence["queue_states"] = queue
    evidence["replay"] = replay
    accounting = account_evidence(evidence, routes)
    supplier = next(
        (
            turn["result"].get("supplier")
            for turn in evidence["turns"]
            if turn.get("result", {}) and turn["result"].get("action") == "source"
        ),
        None,
    )
    completed_gemini = {
        call["event_id"]
        for call in evidence["calls"]
        if call["provider"] == "vertex"
        and call["state"] == "completed"
        and call.get("response_body") is not None
    }
    gemini_routes = {
        route["event_id"]
        for route in routes
        if route["state"] == "completed" and route["executor"] == "gemini"
    }
    escalation = bool(completed_gemini & gemini_routes)
    requested_gemini = any(jev_requested_gemini(route, completed_gemini) for route in routes)
    breakdown = {
        executor: sum(r["state"] == "completed" and r["executor"] == executor for r in routes)
        for executor in ("rules", "jev", "gemini")
    }
    if arm["variant"] == "baseline":
        breakdown["gemini"] = len(completed_gemini)
    invariants, metrics = state["invariants"], state["metrics"]
    agent = next(
        entity["agent"]
        for entity in arm["configuration"]["entities"]
        if entity["kind"] == "restaurant"
    )
    route_limit = agent["brain"].get("routing")
    paid_routes = [route for route in routes if route.get("model") is not None]
    admitted = accounting["cost"]
    admission_matches = (
        money(admitted["vertex_reserved_usd"]) <= money(agent["brain"]["usd_limit"])
        and len(evidence["jev_calls"]) <= agent["search"]["calls_limit"]
        and sum(call["reserved_input_tokens"] for call in evidence["jev_calls"])
        <= agent["search"]["input_tokens_limit"]
        and (
            not paid_routes
            if route_limit is None
            else (
                len(paid_routes) <= route_limit["calls_per_run"]
                and sum(route["reserved_input_tokens"] for route in paid_routes)
                <= route_limit["input_tokens_per_run"]
                and money(admitted["jev_router_reserved_usd"]) <= money(route_limit["usd_limit"])
            )
        )
    )
    checks = {
        "run_completed": status == "complete" and not arm.get("execution_error"),
        "delivered": len(state["orders"]) == 1 and metrics["delivered"] == 1,
        "replay": replay["matches"] is True,
        "stock": all(
            invariants.get(key) is True
            for key in ("stock_nonnegative", "stock_conserved", "canonical_units")
        ),
        "queue": bool(queue) and all(name == "done" or count == 0 for name, count in queue.items()),
        "no_retries": metrics["retries"] == 0,
        "no_open_work": metrics["unfinished_orders"] == 0 and metrics["open_delivery_jobs"] == 0,
        "delivery_on_time": metrics["late_physical_deliveries"] == 0,
        "supplier_choice": supplier == arm["expected_supplier"],
        "admission_limits": admission_matches,
        "turns_applied": bool(evidence["turns"])
        and all(turn["state"] == "applied" for turn in evidence["turns"]),
        "model_receipts_complete": all(call["state"] == "completed" for call in evidence["calls"]),
        "route_receipts_complete": all(route["state"] == "completed" for route in routes),
    }
    if arm["variant"] == "baseline":
        checks["baseline_gemini_called"] = bool(completed_gemini)
        checks["baseline_mozzarella_search"] = (
            len(evidence["searches"]) == 1
            and evidence["searches"][0]["query"].strip().lower() == "mozzarella"
            and bool(evidence["jev_calls"])
            and all(call["status"] == "ok" for call in evidence["jev_calls"])
            and all(not row["detail"].get("error") for row in evidence["searches"])
        )
    else:
        checks["routing_strategy_applied"] = bool(routes)
    if arm["scenario"] == "reasoning" and arm["variant"] == "cascade":
        checks["actual_gemini_escalation"] = escalation
        checks["reasoning_jev_requested_gemini"] = requested_gemini
    arm.update(
        status="completed" if all(checks.values()) else "failed",
        run_status=status,
        metrics=metrics,
        invariants=invariants,
        replay_matches=replay["matches"],
        supplier=supplier,
        outcome_checks=checks,
        route_breakdown=breakdown,
        route_decisions=[dict(route, memory_mode=arm["memory_mode"]) for route in routes],
        actual_gemini_escalation=escalation,
        reasoning_jev_requested_gemini=requested_gemini,
        evidence=evidence,
        **accounting,
    )


def update_report(receipt: dict[str, Any], final: bool = False) -> None:
    arms = receipt["arms"]
    comparisons = []
    for scenario, _ in SCENARIOS:
        baseline, cascade = [arm for arm in arms if arm["scenario"] == scenario]
        finished = all(arm["status"] in {"completed", "failed"} for arm in (baseline, cascade))
        equivalent = finished and all(arm["status"] == "completed" for arm in (baseline, cascade))
        equivalent = equivalent and baseline.get("supplier") == cascade.get("supplier")
        known = finished and all(
            arm.get("cost") and not arm["cost"]["unknown_calls"] for arm in (baseline, cascade)
        )
        cost_delta = (
            (money(cascade["cost"]["total_usd"]) - money(baseline["cost"]["total_usd"]))
            if known
            else None
        )
        wall = [numeric(arm.get("wall_seconds")) for arm in (baseline, cascade)]
        comparisons.append(
            {
                "scenario": scenario,
                "baseline": baseline["id"],
                "cascade": cascade["id"],
                "passed": bool(equivalent),
                "equivalent_outcomes": bool(equivalent),
                "status": "matched" if equivalent else "failed" if finished else "pending",
                "status_delta": {"baseline": baseline["status"], "cascade": cascade["status"]},
                "supplier_delta": {
                    "baseline": baseline.get("supplier"),
                    "cascade": cascade.get("supplier"),
                },
                "outcome_deltas": {
                    key: {
                        "baseline": baseline["outcome_checks"].get(key),
                        "cascade": cascade["outcome_checks"].get(key),
                    }
                    for key in sorted(
                        baseline["outcome_checks"].keys() | cascade["outcome_checks"].keys()
                    )
                },
                "known_usage": bool(known),
                "observed_cost_delta_usd": str(cost_delta) if cost_delta is not None else None,
                "observed_wall_seconds_delta": round(wall[1] - wall[0], 3)
                if None not in wall
                else None,
                "cost_savings_usd": str(-cost_delta)
                if equivalent and cost_delta is not None and cost_delta < 0
                else None,
                "claim": "Paired outcomes passed; cost is an observation at the frozen tariff."
                if equivalent and known
                else "No cost-savings claim: outcomes or usage are not fully verified.",
            }
        )
    vertex_reserved = sum(
        (money(arm.get("cost", {}).get("vertex_reserved_usd")) for arm in arms), Decimal(0)
    )
    jev_accounted = sum(
        (money(arm.get("cost", {}).get("jev_accounted_usd")) for arm in arms), Decimal(0)
    )
    total_accounted = sum(
        (money(arm.get("cost", {}).get("accounted_usd")) for arm in arms), Decimal(0)
    )
    reasoning = next(arm for arm in arms if arm["id"] == "reasoning-cascade")
    all_completed = all(arm["status"] == "completed" for arm in arms)
    observed = all(arm["status"] in {"completed", "failed"} for arm in arms)
    receipt["comparisons"] = comparisons
    receipt["accounting"] = {
        "vertex_reserved_usd": str(vertex_reserved),
        "jev_accounted_usd": str(jev_accounted),
        "total_accounted_usd": str(total_accounted),
    }
    receipt["outcome_comparison"] = {
        "all_arms_completed": all_completed if observed or final else None,
        "matched_outcomes": all(pair["passed"] for pair in comparisons)
        if observed or final
        else None,
        "reasoning_gemini_escalation": reasoning.get("actual_gemini_escalation", False)
        if reasoning["status"] in {"completed", "failed"} or final
        else None,
        "reasoning_jev_requested_gemini": reasoning.get("reasoning_jev_requested_gemini", False)
        if reasoning["status"] in {"completed", "failed"} or final
        else None,
        "within_vertex_reservations": vertex_reserved <= VERTEX_LIMIT,
        "within_jev_allowance": jev_accounted < JEV_LIMIT,
        "within_total_ceiling": total_accounted <= TOTAL_LIMIT,
        "known_usage": all(pair["known_usage"] for pair in comparisons)
        if observed or final
        else None,
    }
    receipt["updated_at"] = utc_now()
    receipt["summary"] = (
        f"{sum(arm['status'] == 'completed' for arm in arms)}/6 arms passed; "
        f"{sum(pair['passed'] for pair in comparisons)}/3 paired outcomes verified. "
        "Reasoning Gemini escalation "
        f"{'observed' if reasoning.get('actual_gemini_escalation') else 'not verified'}. "
        "Validated Jev request for Gemini "
        f"{'observed' if reasoning.get('reasoning_jev_requested_gemini') else 'not verified'}. "
        "Cost differences support a savings claim only for a fully verified pair with known usage."
    )
    if final:
        receipt["status"] = "completed" if all(receipt["outcome_comparison"].values()) else "failed"
        if any(arm["status"] in {"planned", "running", "creating"} for arm in arms):
            receipt["status"] = "partial"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true", required=True)
    args = parser.parse_args()
    if not args.paid:
        raise PermissionError("Explicit --paid approval is required")
    profile = approved_profile()
    arms = planned_arms(profile)
    budget = admission_plan(arms)
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/adk-route-comparison.json"
    directory = os.environ.get("DELIVERY_ADK_EXPERIMENT_DIRECTORY")
    if not directory or not Path(directory).is_absolute() or not Path(directory).is_dir():
        raise PermissionError("A dedicated absolute experiment-marker directory must be mounted")
    marker = Path(directory) / "route-comparison.execution.json"
    if output.exists() or marker.exists():
        raise PermissionError(
            "A routing comparison was already started; inspect retained evidence. "
            "No rerun or resume is permitted."
        )
    receipt: dict[str, Any] = {
        "status": "running",
        "created_at": utc_now(),
        "source_fingerprint": source_fingerprint(root),
        "profile": profile.model_dump(mode="json"),
        "jev_model": "jev-1.14.0",
        "budget": budget,
        "arms": arms,
        "comparisons": [],
        "outcome_comparison": {},
        "method": {
            "runs": (
                "One order per arm; six unique runs, no dispatch retries or automatic resumption."
            ),
            "pairing": (
                "Same city seed, SOUL, typed memory and demand per pair; routing, legacy search "
                "prompt and Vertex admission differ as declared in frozen configurations."
            ),
            "wall_time": (
                "Creation plus simulation execution; excludes post-run receipt "
                "collection and replay."
            ),
            "route_counts": (
                "Cascade uses persisted router receipts; baseline Gemini count is distinct "
                "completed model-call events."
            ),
            "explanation_review": (
                "Reasoning gates verify a successful validated Jev executor choice, explicit "
                "reason jev_requested_reasoning_model and actual completed Gemini response; "
                "explanation quality requires operator inspection."
            ),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with marker.open("x", encoding="utf-8") as lock:
        json.dump(
            {"created_at": receipt["created_at"], "receipt": str(output), "budget": budget}, lock
        )
    save_receipt(output, receipt)
    print(
        "Starting one retained six-arm comparison; Vertex <= $0.54, Jev < $0.01, total <= $0.60.",
        flush=True,
    )
    try:
        migrate()
        for arm in arms:
            arm["status"] = "creating"
            save_receipt(output, receipt)
            started = time.monotonic()
            try:
                arm["run"] = new_supply(SupplyConfig.model_validate(arm["configuration"]))
                arm["status"] = "running"
                save_receipt(output, receipt)
                run_supply(arm["run"])
            except Exception as exc:
                arm.update(status="failed", execution_error=type(exc).__name__)
                raise
            finally:
                arm["wall_seconds"] = round(time.monotonic() - started, 3)
                if arm["run"]:
                    try:
                        finish_arm(arm, profile)
                    except Exception as exc:
                        arm.update(status="failed", collection_error=type(exc).__name__)
                update_report(receipt)
                save_receipt(output, receipt)
                print(
                    json.dumps(
                        {
                            key: arm.get(key)
                            for key in (
                                "id",
                                "run",
                                "status",
                                "supplier",
                                "provider_calls",
                                "cost",
                                "outcome_checks",
                            )
                        },
                        default=str,
                    ),
                    flush=True,
                )
            if arm.get("collection_error"):
                raise RuntimeError("Receipt collection failed; remaining arms were not dispatched")
            caps = receipt["outcome_comparison"]
            if arm["outcome_checks"].get("admission_limits") is False or not all(
                caps[key]
                for key in (
                    "within_vertex_reservations",
                    "within_jev_allowance",
                    "within_total_ceiling",
                )
            ):
                raise RuntimeError("An admission gate failed; remaining arms were not dispatched")
    except Exception as exc:
        receipt["execution_error"] = type(exc).__name__
        raise
    finally:
        update_report(receipt, final=True)
        save_receipt(output, receipt)
        # Deliberately retain marker after success, failure, interruption or missing receipt.
    if receipt["status"] != "completed":
        raise RuntimeError(
            "Comparison gates failed; inspect the saved receipt before any further work"
        )


if __name__ == "__main__":
    main()

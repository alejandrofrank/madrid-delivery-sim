"""One retained three-case live verification, capped at 0.15 USD; no retries/resume."""

import argparse
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import psycopg
from compare_agent_routing import (
    MEMORY,
    REASONING_SOUL,
    approved_profile,
    fingerprint,
    finish_arm,
    utc_now,
)
from demo_adk_restaurants import configuration
from demo_adk_vertex import save_receipt

from delivery.adk_contracts import JevRouting, VertexProfile
from delivery.db import connect, migrate
from delivery.health_report import source_fingerprint
from delivery.jev_routing import checked_answer, confidence
from delivery.supply import new_supply, provision, run_supply
from delivery.supply_models import SupplyConfig

VERTEX_CAP = Decimal("0.12")
JEV_CAP = Decimal("0.002")
TOTAL_CAP = Decimal("0.15")


def planned_cases(profile: VertexProfile) -> list[dict]:
    cases = []
    for name in ("pantry-direct", "cost-contract", "reasoning-contract"):
        direct = name == "pantry-direct"
        config = configuration("cost" if name == "cost-contract" else "speed").model_dump(
            mode="json"
        )
        entity = next(e for e in config["entities"] if e["kind"] == "restaurant")
        agent = entity["agent"]
        agent["memory"] = dict(MEMORY)
        agent["search"] = {"provider": "local", "calls_limit": 0, "input_tokens_limit": 0}
        if name == "reasoning-contract":
            agent["soul"] += REASONING_SOUL
        if name == "cost-contract":
            agent["soul"] += (
                "\nExplain why the cheapest supplier's lower fee justifies its longer "
                "lead time compared with the fastest quote, then choose the cheapest. "
                "Give that reasoned tradeoff in finish_decision's 1 to 500 character summary."
            )
        route = JevRouting(calls_per_run=1, input_tokens_per_run=8192, usd_limit=0.0005)
        if direct:
            route = route.model_copy(
                update={
                    "instructions": route.instructions
                    + (
                        " A missing fact means one required for the next action. Supplier stock "
                        "is irrelevant when this kitchen already physically holds "
                        "the complete recipe."
                    )
                }
            )
            config["restaurant_stock_servings"] = 2
        agent["brain"].update(
            routing=route.model_dump(mode="json"),
            provider="offline" if direct else "vertex",
            vertex=None if direct else profile.model_dump(mode="json"),
            usd_limit=0 if direct else 0.06,
            model_calls_per_event=8,
            model_calls_per_run=16,
            reserved_tokens_per_run=1 if direct else 524288,
            output_tokens=1024,
            timeout_seconds=30,
        )
        frozen = SupplyConfig.model_validate(config).model_dump(mode="json")
        cases.append(
            {
                "id": name,
                "label": {
                    "pantry-direct": "Stocked pantry · Jev only",
                    "cost-contract": "Mateo · corrected tool contract",
                    "reasoning-contract": "Elena · bounded explanation",
                }[name],
                "scenario": "reasoning" if name == "reasoning-contract" else name,
                "soul": "cost" if name == "cost-contract" else "speed",
                "variant": "cascade",
                "memory_mode": "typed",
                "status": "planned",
                "run": None,
                "expected_supplier": None
                if direct
                else "market-b"
                if name == "cost-contract"
                else "market-a",
                "configuration": frozen,
                "configuration_sha256": fingerprint(frozen),
                "metrics": {},
                "cost": {},
                "provider_calls": {},
                "outcome_checks": {},
                "route_breakdown": {},
                "route_decisions": [],
            }
        )
    return cases


def admission(cases: list[dict]) -> dict:
    if [a["id"] for a in cases] != ["pantry-direct", "cost-contract", "reasoning-contract"]:
        raise PermissionError("Only the three reviewed cases may be dispatched")
    vertex = jev = Decimal(0)
    for case in cases:
        config = SupplyConfig.model_validate(case["configuration"])
        kitchens = [e for e in config.entities if e.kind == "restaurant"]
        if (
            len(kitchens) != 1
            or sum(e.kind == "household" for e in config.entities) != 1
            or config.calls_per_household != 1
        ):
            raise PermissionError("Each case requires one kitchen, household and call")
        agent = kitchens[0].agent
        assert agent and agent.brain and agent.brain.routing
        brain, route = agent.brain, agent.brain.routing
        if (
            route.calls_per_run != 1
            or route.confidence_threshold != 0.85
            or route.margin_threshold != 0.20
            or agent.search.calls_limit
        ):
            raise PermissionError("Fixed routing thresholds and one paid router call required")
        if case["id"] == "pantry-direct" and (
            brain.provider != "offline" or brain.reserved_tokens_per_run != 1
        ):
            raise PermissionError("Direct Jev proof must fence all secondary model admission")
        vertex += Decimal(str(brain.usd_limit))
        jev += Decimal(str(route.usd_limit))
    if vertex > VERTEX_CAP or jev > JEV_CAP or vertex + jev > TOTAL_CAP:
        raise PermissionError("Verification exceeds the shared capped allowance")
    return {
        "vertex_admission_limit_usd": str(vertex),
        "jev_conservative_admission_usd": str(jev),
        "combined_conservative_admission_usd": str(vertex + jev),
        "total_ceiling_usd": str(TOTAL_CAP),
    }


def verification_checks(case: dict) -> dict[str, bool]:
    evidence = case["evidence"]
    calls, turns = evidence["calls"], evidence["turns"]
    paid_routes = [r for r in case["route_decisions"] if r["model"]]
    checks = {
        "one_jev_dispatch": len(paid_routes) == 1,
        "known_usage": case["cost"]["unknown_calls"] == 0,
        "no_legacy_search": not evidence["jev_calls"],
        "bounded_saved_summaries": bool(turns)
        and all(t.get("result") and 1 <= len(t["result"]["summary"]) <= 500 for t in turns),
    }
    if case["id"] == "pantry-direct":
        try:
            route = paid_routes[0]
            checked_answer(route["response_body"], route["request_body"])
            checks["real_jev_direct_confirmation"] = (
                route["executor"] == "jev"
                and route["state"] == "completed"
                and route["error_code"] is None
                and route["response_body"]["answers"]["executor"]["choice"] == "direct"
                and route["response_body"]["answers"]["action"]["choice"] == "confirm"
                and route["decision"]["action"] == "confirm"
                and route["reason"] == "confident_bounded_jev_decision"
                and confidence(route["response_body"], ["executor", "action"])[0] >= 0.85
                and confidence(route["response_body"], ["executor", "action"])[1] >= 0.20
            )
        except (IndexError, KeyError, TypeError, ValueError):
            checks["real_jev_direct_confirmation"] = False
        checks["zero_secondary_model_dispatches"] = not calls
        checks["zero_gemini_cost"] = Decimal(case["cost"]["vertex_usd"]) == 0
    else:
        checks["real_vertex_execution"] = bool(calls) and all(
            c["provider"] == "vertex" and c["state"] == "completed" for c in calls
        )
        checks["validated_declared_functions"] = bool(calls) and all(
            c["request_body"]["config"]["tool_config"]["function_calling_config"]["mode"]
            == "VALIDATED"
            for c in calls
        )
    return checks


def isolation_checks(run: str) -> dict[str, bool]:
    agent = provision(run)["restaurant-pizza"]
    checks = {}
    for table in ("supply_stock", "restaurant_model_calls", "restaurant_routes"):
        try:
            with connect(agent.dsn) as conn:
                conn.execute(f"SELECT * FROM public.{table} LIMIT 1")
        except psycopg.errors.InsufficientPrivilege:
            checks[f"{table}_direct_read_denied"] = True
        else:
            checks[f"{table}_direct_read_denied"] = False
    return checks


def update(receipt: dict, final: bool = False) -> None:
    arms = receipt["arms"]
    vertex = sum(
        (Decimal(a.get("cost", {}).get("vertex_reserved_usd", "0")) for a in arms), Decimal(0)
    )
    jev = sum((Decimal(a.get("cost", {}).get("jev_accounted_usd", "0")) for a in arms), Decimal(0))
    accounted = sum(
        (Decimal(a.get("cost", {}).get("accounted_usd", "0")) for a in arms), Decimal(0)
    )
    receipt["accounting"] = {
        "vertex_reserved_usd": str(vertex),
        "jev_accounted_usd": str(jev),
        "total_accounted_usd": str(accounted),
        "known_usage_total_usd": str(
            sum((Decimal(a.get("cost", {}).get("total_usd", "0")) for a in arms), Decimal(0))
        ),
    }
    receipt["outcome_comparison"] = {
        "within_vertex_ceiling": vertex <= VERTEX_CAP and accounted - jev <= VERTEX_CAP,
        "within_jev_ceiling": jev <= JEV_CAP,
        "within_total_ceiling": accounted <= TOTAL_CAP,
    }
    if final:
        receipt["outcome_comparison"]["all_three_cases_passed"] = all(
            a["status"] == "completed" for a in arms
        )
        receipt["status"] = "completed" if all(receipt["outcome_comparison"].values()) else "failed"
    receipt["updated_at"] = utc_now()
    receipt["summary"] = (
        f"{sum(a['status'] == 'completed' for a in arms)}/3 cases passed. "
        "Direct Jev proof requires a delivered order and zero secondary model dispatches. "
        "Earlier failed comparisons remain unchanged."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true", required=True)
    parser.parse_args()
    profile = approved_profile()
    cases = planned_cases(profile)
    budget = admission(cases)
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/adk-contract-verification.json"
    directory = Path(os.environ.get("DELIVERY_ADK_EXPERIMENT_DIRECTORY", ""))
    if not directory.is_absolute() or not directory.is_dir():
        raise PermissionError("Dedicated operator experiment-marker mount required")
    marker = directory / "contract-verification.execution.json"
    if output.exists() or marker.exists():
        raise PermissionError("Verification already claimed; no automatic retries or resumption")
    receipt = {
        "status": "running",
        "created_at": utc_now(),
        "source_fingerprint": source_fingerprint(root),
        "profile": profile.model_dump(mode="json"),
        "budget": budget,
        "arms": cases,
        "comparisons": [],
        "previous_evidence": "artifacts/adk-route-comparison.json",
    }
    with marker.open("x", encoding="utf-8") as lock:
        json.dump(
            {"created_at": receipt["created_at"], "budget": budget, "receipt": str(output)}, lock
        )
    save_receipt(output, receipt)
    try:
        migrate()
        for case in cases:
            case["status"] = "creating"
            save_receipt(output, receipt)
            started = time.monotonic()
            try:
                case["run"] = new_supply(SupplyConfig.model_validate(case["configuration"]))
                case["status"] = "running"
                save_receipt(output, receipt)
                run_supply(case["run"])
            except Exception as exc:
                case["execution_error"] = type(exc).__name__
                raise
            finally:
                case["wall_seconds"] = round(time.monotonic() - started, 3)
                if case["run"]:
                    finish_arm(case, profile)
                    case["outcome_checks"].update(verification_checks(case))
                    case["outcome_checks"].update(isolation_checks(case["run"]))
                    case["status"] = (
                        "completed" if all(case["outcome_checks"].values()) else "failed"
                    )
                else:
                    case["status"] = "failed"
                update(receipt)
                save_receipt(output, receipt)
                print(
                    json.dumps(
                        {
                            k: case.get(k)
                            for k in (
                                "id",
                                "run",
                                "status",
                                "provider_calls",
                                "cost",
                                "outcome_checks",
                            )
                        },
                        default=str,
                    ),
                    flush=True,
                )
            if case["status"] != "completed" or not all(receipt["outcome_comparison"].values()):
                raise RuntimeError("Verification gate failed; stop before any more paid work")
    except BaseException as exc:
        receipt["execution_error"] = type(exc).__name__
        raise
    finally:
        update(receipt, final=True)
        save_receipt(output, receipt)


if __name__ == "__main__":
    main()

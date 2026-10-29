"""Pure benchmark contracts and accounting; every DB/provider boundary is blocked."""

import copy
import importlib
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def benchmark(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Benchmark regression checks cannot access DB or provider services")

    import httpx
    import requests

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)
    monkeypatch.setattr("socket.socket.connect", forbidden)
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("compare_agent_routing")
    for name in (
        "connect",
        "migrate",
        "new_supply",
        "run_supply",
        "replay_supply",
        "supply_snapshot",
        "operator_receipts",
        "run_evidence",
    ):
        monkeypatch.setattr(module, name, forbidden)
    return module


@pytest.fixture
def profile(benchmark):
    return benchmark.VertexProfile(
        project="synthetic-benchmark",
        location="global",
        model="gemini-3.5-flash-lite",
        input_usd_per_million=0.30,
        output_usd_per_million=2.50,
        cached_input_usd_per_million=0.03,
    )


@pytest.fixture
def evidence():
    return {
        "calls": [
            {
                "event_id": 1,
                "provider": "vertex",
                "state": "completed",
                "response_body": {},
                "usage_cost_usd": ".001",
                "reserved_usd": ".003",
                "latency_ms": 100,
            }
        ],
        "turns": [
            {
                "event_id": 1,
                "state": "applied",
                "result": {"action": "source", "supplier": "market-a"},
            }
        ],
        "jev_calls": [
            {
                "event_id": 1,
                "actual_input_tokens": 100,
                "reserved_input_tokens": 200,
                "status": "ok",
            }
        ],
        "searches": [{"query": "mozzarella", "duration_ms": 999999, "detail": {}}],
    }


@pytest.fixture
def route():
    choices = {
        "executor": {"direct": 0.05, "gemini": 0.95},
        "action": {"source": 0.9, "confirm": 0.05, "decline": 0.05},
        "supplier": {"market-a": 0.9, "market-b": 0.05, "uncertain": 0.05},
    }
    selected = {"executor": "gemini", "action": "source", "supplier": "market-a"}
    return {
        "event_id": 1,
        "state": "completed",
        "executor": "gemini",
        "model": "jev-1.14.0",
        "input_tokens": 50,
        "reserved_input_tokens": 200,
        "reserved_usd": ".0000084",
        "latency_ms": 20,
        "error_code": None,
        "reason": "jev_requested_reasoning_model",
        "request_body": {
            "model": "jev-1.14.0",
            "questions": {
                key: {"criteria": dict.fromkeys(options, "fixture")}
                for key, options in choices.items()
            },
        },
        "response_body": {
            "model": "jev-1.14.0",
            "usage": {"input_tokens": 50, "output_tokens": 10},
            "answers": {
                key: {
                    "type": "choice",
                    "choice": selected[key],
                    "confidence": probabilities[selected[key]],
                    "probabilities": probabilities,
                }
                for key, probabilities in choices.items()
            },
        },
    }


def test_six_arm_plan_pairs_exact_souls_and_respects_caps(benchmark, profile):
    arms = benchmark.planned_arms(profile)
    budget = benchmark.admission_plan(arms)
    assert len(arms) == 6
    assert Decimal(budget["vertex_admission_limit_usd"]) == Decimal(".54")
    assert Decimal(budget["jev_maximum_usd_at_tariff"]) == Decimal(".008064")
    assert Decimal(budget["combined_conservative_admission_usd"]) == Decimal(".549048")
    for baseline, cascade in zip(arms[::2], arms[1::2], strict=True):
        assert baseline["soul_sha256"] == cascade["soul_sha256"]
        assert baseline["configuration"]["seed"] == cascade["configuration"]["seed"]
        assert baseline["memory_mode"] == cascade["memory_mode"] == "typed"
        old = next(
            e["agent"] for e in baseline["configuration"]["entities"] if e["kind"] == "restaurant"
        )
        new = next(
            e["agent"] for e in cascade["configuration"]["entities"] if e["kind"] == "restaurant"
        )
        assert old["memory"] == new["memory"] == benchmark.MEMORY
        assert old["brain"].get("routing") is None
        assert new["brain"]["routing"]["input_tokens_per_run"] == 16000
        assert "use search_ingredients once" in old["brain"]["instructions"]
        assert "use search_ingredients once" not in new["brain"]["instructions"]


def test_admission_plan_rejects_added_run_or_larger_allowance(benchmark, profile):
    arms = benchmark.planned_arms(profile)
    with pytest.raises(PermissionError):
        benchmark.admission_plan([*arms, copy.deepcopy(arms[0])])
    restaurant = next(
        e["agent"] for e in arms[0]["configuration"]["entities"] if e["kind"] == "restaurant"
    )
    restaurant["brain"]["usd_limit"] = 0.15
    with pytest.raises(PermissionError):
        benchmark.admission_plan(arms)


def test_accounting_counts_paid_routers_and_preserves_latency_basis(benchmark, evidence, route):
    rules = dict(
        route,
        event_id=2,
        executor="rules",
        model=None,
        input_tokens=None,
        reserved_input_tokens=0,
        reserved_usd=0,
        latency_ms=1,
    )
    result = benchmark.account_evidence(evidence, [route, rules])
    assert result["provider_calls"] == {
        "gemini": 1,
        "jev": 2,
        "jev_search": 1,
        "jev_router": 1,
    }
    assert Decimal(result["cost"]["total_usd"]) == Decimal(".0010063")
    assert result["cost"]["unknown_calls"] == 0
    assert result["median_latency_ms"] == 60
    assert result["latency"]["gemini_provider_p50_ms"] == 100
    assert result["latency"]["jev_router_provider_p50_ms"] == 20
    assert result["latency"]["legacy_search_operation_durations_ms"] == [999999]
    assert Decimal(result["cost"]["accounted_usd"]) > Decimal(result["cost"]["total_usd"])


@pytest.mark.parametrize("unknown", ["vertex", "search", "router"])
def test_missing_usage_is_unknown_and_retains_admission(benchmark, evidence, route, unknown):
    if unknown == "vertex":
        evidence["calls"][0]["usage_cost_usd"] = None
    elif unknown == "search":
        evidence["jev_calls"][0]["actual_input_tokens"] = None
    else:
        route["input_tokens"] = None
    result = benchmark.account_evidence(evidence, [route])
    assert result["cost"]["unknown_calls"] == 1
    assert Decimal(result["cost"]["accounted_usd"]) >= Decimal(".003")


def test_strict_reasoning_gate_requires_valid_jev_choice_and_actual_gemini(benchmark, route):
    assert benchmark.jev_requested_gemini(route, {1})
    assert not benchmark.jev_requested_gemini(route, set())
    for field, value in (
        ("error_code", "TimeoutError"),
        ("reason", "unknown_provider_judgment"),
        ("executor", "jev"),
        ("state", "pending"),
        ("reserved_input_tokens", 1),
        ("response_body", None),
    ):
        changed = dict(route, **{field: value})
        assert not benchmark.jev_requested_gemini(changed, {1})
    malformed = copy.deepcopy(route)
    malformed["response_body"]["answers"]["executor"]["probabilities"] = {"gemini": 1}
    assert not benchmark.jev_requested_gemini(malformed, {1})
    direct = copy.deepcopy(route)
    direct["response_body"]["answers"]["executor"].update(
        choice="direct",
        confidence=0.95,
        probabilities={"direct": 0.95, "gemini": 0.05},
    )
    assert not benchmark.jev_requested_gemini(direct, {1})


@pytest.mark.parametrize("error", [False, True])
def test_finish_arm_does_not_mistake_provider_fallback_for_reasoning(
    benchmark,
    profile,
    evidence,
    route,
    monkeypatch,
    error,
):
    arm = benchmark.planned_arms(profile)[-1]
    arm["run"] = "synthetic-only"
    if error:
        route.update(error_code="TimeoutError", reason="unknown_provider_judgment")
    state = {
        "orders": [{}],
        "metrics": {
            "delivered": 1,
            "retries": 0,
            "unfinished_orders": 0,
            "open_delivery_jobs": 0,
            "late_physical_deliveries": 0,
        },
        "invariants": {"stock_nonnegative": True, "stock_conserved": True, "canonical_units": True},
    }
    monkeypatch.setattr(benchmark, "supply_snapshot", lambda run: state)
    monkeypatch.setattr(benchmark, "replay_supply", lambda run: {"matches": True})
    monkeypatch.setattr(
        benchmark, "operator_receipts", lambda run: ("complete", {"done": 7}, [route])
    )
    monkeypatch.setattr(benchmark, "run_evidence", lambda run, profile: evidence)
    benchmark.finish_arm(arm, profile)
    assert arm["actual_gemini_escalation"] is True
    assert arm["reasoning_jev_requested_gemini"] is (not error)
    assert arm["outcome_checks"]["reasoning_jev_requested_gemini"] is (not error)
    assert arm["status"] == ("failed" if error else "completed")


def matched_receipt(benchmark, profile):
    arms = benchmark.planned_arms(profile)
    for arm in arms:
        arm.update(
            status="completed",
            supplier=arm["expected_supplier"],
            wall_seconds=10 if arm["variant"] == "baseline" else 5,
            actual_gemini_escalation=True,
            reasoning_jev_requested_gemini=True,
            outcome_checks={"delivered": True, "stock": True, "queue": True, "replay": True},
            cost={
                "total_usd": ".01" if arm["variant"] == "baseline" else ".001",
                "unknown_calls": 0,
                "vertex_reserved_usd": ".01",
                "jev_accounted_usd": ".001",
                "accounted_usd": ".011",
            },
        )
    return {"status": "running", "arms": arms}


def test_pending_report_uses_neutral_gates(benchmark, profile):
    receipt = {"status": "running", "arms": benchmark.planned_arms(profile)}
    benchmark.update_report(receipt)
    assert receipt["outcome_comparison"]["matched_outcomes"] is None
    assert receipt["outcome_comparison"]["reasoning_jev_requested_gemini"] is None
    assert all(pair["cost_savings_usd"] is None for pair in receipt["comparisons"])


def test_report_claims_only_verified_pair_savings(benchmark, profile):
    receipt = matched_receipt(benchmark, profile)
    benchmark.update_report(receipt, final=True)
    assert receipt["status"] == "completed"
    assert receipt["outcome_comparison"]["reasoning_jev_requested_gemini"] is True
    assert all(pair["cost_savings_usd"] == "0.009" for pair in receipt["comparisons"])
    receipt["arms"][1].update(status="failed", outcome_checks={"delivered": False})
    benchmark.update_report(receipt, final=True)
    assert receipt["status"] == "failed"
    assert receipt["comparisons"][0]["cost_savings_usd"] is None
    assert receipt["comparisons"][0]["outcome_deltas"]["delivered"] == {
        "baseline": True,
        "cascade": False,
    }


def test_report_withholds_savings_for_unknown_usage_or_unproven_jev_escalation(benchmark, profile):
    receipt = matched_receipt(benchmark, profile)
    receipt["arms"][1]["cost"]["unknown_calls"] = 1
    receipt["arms"][-1]["reasoning_jev_requested_gemini"] = False
    benchmark.update_report(receipt, final=True)
    assert receipt["status"] == "failed"
    assert receipt["comparisons"][0]["cost_savings_usd"] is None
    assert receipt["outcome_comparison"]["reasoning_jev_requested_gemini"] is False

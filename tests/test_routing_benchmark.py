"""Pure benchmark contracts and accounting; every DB/provider boundary is blocked."""

import copy
import importlib
import json
from argparse import Namespace
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def contracts(benchmark, monkeypatch):
    module = importlib.import_module("verify_adk_contracts")

    def forbidden(*args, **kwargs):
        raise AssertionError("Contract harness tests must not dispatch providers or access DB")

    for name in ("connect", "migrate", "new_supply", "provision", "run_supply", "finish_arm"):
        monkeypatch.setattr(module, name, forbidden)
    return module


def test_contract_plan_caps_and_direct_probe_fence_all_secondary_models(contracts, profile):
    cases = contracts.planned_cases(profile)
    budget = contracts.admission(cases)
    assert Decimal(budget["vertex_admission_limit_usd"]) == Decimal(".12")
    assert Decimal(budget["jev_conservative_admission_usd"]) == Decimal(".0015")
    assert Decimal(budget["combined_conservative_admission_usd"]) == Decimal(".1215")
    direct = next(
        e["agent"] for e in cases[0]["configuration"]["entities"] if e["kind"] == "restaurant"
    )
    assert direct["brain"]["provider"] == "offline"
    assert direct["brain"]["reserved_tokens_per_run"] == 1
    assert cases[0]["configuration"]["restaurant_stock_servings"] == 2
    for case in cases:
        agent = next(
            e["agent"] for e in case["configuration"]["entities"] if e["kind"] == "restaurant"
        )
        assert agent["brain"]["routing"]["confidence_threshold"] == 0.85
        assert agent["brain"]["routing"]["calls_per_run"] == 1
        assert agent["search"]["calls_limit"] == 0
    for altered in ([*cases, cases[0]], list(reversed(cases))):
        with pytest.raises(PermissionError):
            contracts.admission(altered)
    direct["brain"]["reserved_tokens_per_run"] = 1024
    with pytest.raises(PermissionError, match="fence"):
        contracts.admission(cases)


def test_direct_proof_cannot_hide_an_offline_or_gemini_call(contracts, route):
    direct = copy.deepcopy(route)
    direct.update(
        executor="jev", decision={"action": "confirm"}, reason="confident_bounded_jev_decision"
    )
    direct["response_body"]["answers"]["executor"].update(
        choice="direct", probabilities={"direct": 0.95, "gemini": 0.05}
    )
    direct["response_body"]["answers"]["action"].update(
        choice="confirm", probabilities={"source": 0.05, "confirm": 0.9, "decline": 0.05}
    )
    case = {
        "id": "pantry-direct",
        "evidence": {
            "calls": [],
            "turns": [{"result": {"summary": "Pantry covers recipe."}}],
            "jev_calls": [],
        },
        "route_decisions": [direct],
        "cost": {"unknown_calls": 0, "vertex_usd": "0"},
    }
    assert all(contracts.verification_checks(case).values())
    for provider in ("offline", "vertex"):
        case["evidence"]["calls"] = [{"provider": provider}]
        assert contracts.verification_checks(case)["zero_secondary_model_dispatches"] is False
    case["evidence"]["calls"] = []
    direct["response_body"]["answers"]["executor"]["choice"] = "gemini"
    assert not contracts.verification_checks(case)["real_jev_direct_confirmation"]


def test_reviewed_followup_retains_prior_reservations_and_never_repeats_gemini(
    contracts, benchmark, profile, evidence, route
):
    evidence["calls"] = []
    evidence["jev_calls"] = []
    cost = benchmark.account_evidence(evidence, [route])["cost"]
    previous = {
        "status": "failed",
        "arms": [
            {
                "id": "pantry-direct",
                "status": "failed",
                "run": "old-probe",
                "evidence": evidence,
                "route_decisions": [route],
                "cost": cost,
                "provider_calls": {"gemini": 0},
            },
            {"status": "planned", "run": None},
            {"status": "planned", "run": None},
        ],
    }
    budget = contracts.admission(contracts.planned_cases(profile))
    carry = contracts.followup_budget(previous, budget)
    assert Decimal(carry["prior_total_accounted_usd"]) >= Decimal(route["reserved_usd"])
    changed = copy.deepcopy(previous)
    changed["arms"][0]["cost"]["accounted_usd"] = "0"
    with pytest.raises(PermissionError):
        contracts.followup_budget(changed, budget)
    next_attempt = copy.deepcopy(previous)
    next_attempt["previous_attempt"] = previous
    next_attempt["carryover"] = carry
    combined = contracts.followup_budget(next_attempt, budget)
    assert Decimal(combined["prior_jev_accounted_usd"]) == 2 * Decimal(
        carry["prior_jev_accounted_usd"]
    )
    next_attempt["carryover"] = {}
    with pytest.raises(PermissionError, match="carryover"):
        contracts.followup_budget(next_attempt, budget)
    previous["arms"][1].update(status="failed", run="attempted-gemini")
    with pytest.raises(PermissionError):
        contracts.followup_budget(previous, budget)


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


def test_reviewed_followup_retains_cost_and_rejects_attempted_or_overbudget_cases(
    contracts, benchmark, profile, route
):
    evidence = {"calls": [], "turns": [], "jev_calls": [], "searches": []}
    cost = benchmark.account_evidence(evidence, [route])["cost"]
    previous = {
        "status": "failed",
        "arms": [
            {"id": "pantry-direct", "status": "failed", "run": "retained-run",
             "evidence": evidence, "route_decisions": [route], "cost": cost,
             "provider_calls": {"gemini": 0}},
            {"status": "planned", "run": None},
            {"status": "planned", "run": None},
        ],
    }
    budget = contracts.admission(contracts.planned_cases(profile))
    carryover = contracts.followup_budget(previous, budget)
    assert Decimal(carryover["prior_total_accounted_usd"]) > 0
    receipt = {"arms": [], "carryover": carryover}
    contracts.update(receipt)
    assert receipt["accounting"]["total_accounted_usd"] == carryover["prior_total_accounted_usd"]
    for mutate in (
        lambda p: p["arms"][1].update(run="already-attempted"),
        lambda p: p["arms"][0]["cost"].update(accounted_usd="0"),
        lambda p: p["arms"][0]["provider_calls"].update(gemini=1),
    ):
        altered = copy.deepcopy(previous)
        mutate(altered)
        with pytest.raises(PermissionError):
            contracts.followup_budget(altered, budget)
    with pytest.raises(PermissionError, match="allowance"):
        contracts.followup_budget(
            previous, {**budget, "combined_conservative_admission_usd": ".15"}
        )


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


def stopped_receipt(benchmark, profile, evidence, route, output):
    arms = benchmark.planned_arms(profile)
    budget = benchmark.admission_plan(arms)
    for index, arm in enumerate(arms[:4]):
        raw = copy.deepcopy(evidence)
        raw["routing_decisions"] = [copy.deepcopy(route)] if arm["variant"] == "cascade" else []
        arm.update(
            status="failed" if index == 3 else "completed",
            run=f"original-run-{index}",
            evidence=raw,
            supplier=arm["expected_supplier"],
            outcome_checks={"delivered": index != 3},
            **benchmark.account_evidence(raw, raw["routing_decisions"]),
        )
    receipt = {
        "status": "partial",
        "created_at": "2026-10-29T12:00:00+00:00",
        "source_fingerprint": "a" * 64,
        "profile": profile.model_dump(mode="json"),
        "jev_model": "jev-1.14.0",
        "budget": budget,
        "arms": arms,
        "execution_error": "PermissionError",
    }
    benchmark.update_report(receipt, final=True)
    marker = {"created_at": receipt["created_at"], "receipt": str(output), "budget": budget}
    return receipt, marker


def test_continuation_selects_only_untouched_plans_without_mutating_prior_arms(
    benchmark,
    profile,
    evidence,
    route,
    tmp_path,
):
    output = tmp_path / "receipt.json"
    receipt, marker = stopped_receipt(benchmark, profile, evidence, route, output)
    prior = copy.deepcopy(receipt)
    selected = benchmark.continuation_arms(
        receipt,
        marker,
        benchmark.planned_arms(profile),
        profile,
        receipt["budget"],
        output,
    )
    assert [arm["id"] for arm in selected] == ["reasoning-baseline", "reasoning-cascade"]
    assert receipt == prior
    assert selected[0] is receipt["arms"][4]


@pytest.mark.parametrize(
    "tamper",
    [
        "source",
        "profile",
        "caps",
        "duplicate_arm",
        "config",
        "planned_run",
        "planned_cost",
        "active_run",
        "duplicate_run",
        "prior_cost",
        "spending_header",
        "prior_continuation",
    ],
)
def test_continuation_refuses_changed_evidence_or_existing_runs(
    benchmark,
    profile,
    evidence,
    route,
    tmp_path,
    tamper,
):
    output = tmp_path / "receipt.json"
    receipt, marker = stopped_receipt(benchmark, profile, evidence, route, output)
    expected_budget = copy.deepcopy(receipt["budget"])
    if tamper == "source":
        receipt["source_fingerprint"] = ""
    elif tamper == "profile":
        receipt["profile"]["model"] = "gemini-other"
    elif tamper == "caps":
        receipt["budget"]["total_ceiling_usd"] = "1.00"
    elif tamper == "duplicate_arm":
        receipt["arms"][5]["id"] = receipt["arms"][4]["id"]
    elif tamper == "config":
        receipt["arms"][4]["configuration"]["seed"] += 1
    elif tamper == "planned_run":
        receipt["arms"][4]["run"] = "already-created"
    elif tamper == "planned_cost":
        receipt["arms"][4]["cost"] = {"total_usd": "0"}
    elif tamper == "active_run":
        receipt["arms"][3]["status"] = "running"
    elif tamper == "duplicate_run":
        receipt["arms"][3]["run"] = receipt["arms"][0]["run"]
    elif tamper == "prior_cost":
        receipt["arms"][3]["cost"]["accounted_usd"] = "0"
    elif tamper == "spending_header":
        receipt["accounting"]["total_accounted_usd"] = "0"
    else:
        receipt["continuations"] = [{"status": "claimed"}]
    with pytest.raises(PermissionError):
        benchmark.continuation_arms(
            receipt,
            marker,
            benchmark.planned_arms(profile),
            profile,
            expected_budget,
            output,
        )


def test_continuation_keeps_prior_spend_in_remaining_admission(
    benchmark,
    profile,
    evidence,
    route,
    tmp_path,
):
    output = tmp_path / "receipt.json"
    receipt, marker = stopped_receipt(benchmark, profile, evidence, route, output)
    raw = receipt["arms"][0]["evidence"]
    raw["calls"][0].update(usage_cost_usd=".50", reserved_usd=".50")
    receipt["arms"][0].update(**benchmark.account_evidence(raw, raw["routing_decisions"]))
    benchmark.update_report(receipt, final=True)
    with pytest.raises(PermissionError, match="cumulative caps"):
        benchmark.continuation_arms(
            receipt,
            marker,
            benchmark.planned_arms(profile),
            profile,
            receipt["budget"],
            output,
        )


def test_dispatch_rejects_existing_runs_before_any_database_work(benchmark, profile, tmp_path):
    arm = benchmark.planned_arms(profile)[0]
    arm.update(run="existing-run", status="failed")
    with pytest.raises(PermissionError, match="untouched"):
        benchmark.dispatch_arms({"arms": [arm]}, [arm], tmp_path / "receipt.json", profile)


def test_launcher_requires_explicit_review_for_planned_continuation(benchmark):
    launcher = importlib.import_module("run_adk_vertex")
    args = Namespace(
        routing_comparison=True,
        continue_planned=True,
        reviewed_failure=True,
        resume=False,
        after_review=False,
    )
    assert launcher.routing_continuation_flags(args) == ["--continue-planned", "--reviewed-failure"]
    for field in ("reviewed_failure", "routing_comparison"):
        with pytest.raises(launcher.DemoError):
            launcher.routing_continuation_flags(Namespace(**{**vars(args), field: False}))


def test_reviewed_continuation_preserves_failed_arm_and_permanent_claim(
    benchmark,
    profile,
    evidence,
    route,
    tmp_path,
    monkeypatch,
):
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    output = tmp_path / "artifacts/adk-route-comparison.json"
    output.parent.mkdir()
    receipt, marker = stopped_receipt(benchmark, profile, evidence, route, output)
    benchmark.save_receipt(output, receipt)
    original = copy.deepcopy(receipt["arms"][:4])
    marker_path = experiment / "route-comparison.execution.json"
    marker_path.write_text(json.dumps(marker))
    monkeypatch.setattr(benchmark, "__file__", str(tmp_path / "scripts/compare_agent_routing.py"))
    monkeypatch.setattr(benchmark, "approved_profile", lambda: profile)
    monkeypatch.setattr(benchmark, "source_fingerprint", lambda root: "b" * 64)
    monkeypatch.setenv("DELIVERY_ADK_EXPERIMENT_DIRECTORY", str(experiment))
    monkeypatch.setattr(
        "sys.argv", ["comparison", "--paid", "--continue-planned", "--reviewed-failure"]
    )
    dispatched = []

    def fake_dispatch(saved, selected, path, approved):
        dispatched.extend(arm["id"] for arm in selected)
        for arm in selected:
            raw = copy.deepcopy(evidence)
            raw["routing_decisions"] = [copy.deepcopy(route)] if arm["variant"] == "cascade" else []
            arm.update(
                status="completed",
                run=f"new-{arm['id']}",
                evidence=raw,
                outcome_checks={"delivered": True},
                supplier=arm["expected_supplier"],
                actual_gemini_escalation=True,
                reasoning_jev_requested_gemini=True,
                **benchmark.account_evidence(raw, raw["routing_decisions"]),
            )

    monkeypatch.setattr(benchmark, "dispatch_arms", fake_dispatch)
    with pytest.raises(RuntimeError, match="original failed arms"):
        benchmark.main()
    saved = json.loads(output.read_text())
    assert dispatched == ["reasoning-baseline", "reasoning-cascade"]
    assert saved["status"] == "failed" and saved["arms"][:4] == original
    assert saved["source_fingerprint"] == "a" * 64
    assert saved["execution_error"] == "PermissionError"
    assert json.loads(marker_path.read_text()) == marker
    claim = json.loads((experiment / "route-comparison.continuation.execution.json").read_text())
    assert claim["status"] == "completed_planned_arms"
    assert claim["preserved_arms_unchanged"] is True
    assert claim["final_receipt_status"] == "failed"
    with pytest.raises(PermissionError, match="only once"):
        benchmark.main()
    assert len(dispatched) == 2

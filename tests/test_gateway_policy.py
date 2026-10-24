"""Hard constraints never depend on a model verdict or cloud credentials."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from delivery import meal_snapshot


@pytest.fixture
def gateway(monkeypatch):
    monkeypatch.setitem(sys.modules, "meal_snapshot", meal_snapshot)
    spec = importlib.util.spec_from_file_location("judge_gateway", "infra/gcp-ai/gateway.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("VERTEX_MODEL", "configured-model")
    monkeypatch.setenv("VERTEX_REGION", "global")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "dedicated-project")
    monkeypatch.setattr(
        module.google.auth, "default", lambda **kw: pytest.fail("No model auth on policy denial")
    )
    return module


def test_all_invalid_cases_deny_without_auth_or_model(gateway):
    fixture = json.loads(Path("data/evals/recovery-judge.json").read_text())
    for case in fixture["cases"]:
        review = gateway.Review(facts=case["facts"], candidate=case["candidate"], memory_entries=0)
        if case["expected_decision"] == "deny_retry":
            result = gateway.judge(review)
            assert result["decision"] == "deny_retry"
            assert result["source"] == "policy_gate"
            assert result["input_tokens"] == result["output_tokens"] == 0
        else:
            assert gateway.preflight(review) is None


def test_nonfinite_facts_are_rejected(gateway):
    review = gateway.Review(
        facts={"attempt": 1, "retry_limit": 2, "sim_time": 0, "deadline_sim": 100},
        candidate={"estimated_seconds": float("nan"), "remaining_seconds": 100, "route_nodes": 2},
        memory_entries=0,
    )
    assert gateway.preflight(review)

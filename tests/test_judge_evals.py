import importlib.util
import json
from pathlib import Path

import pytest

from delivery.cloud_ai import Judgment

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "eval_cloud_judge", ROOT / "scripts/eval_cloud_judge.py"
)
assert SPEC and SPEC.loader
evaluations = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluations)


@pytest.fixture
def fixture():
    return json.loads((ROOT / "data/evals/recovery-judge.json").read_text(encoding="utf-8-sig"))


def test_fixed_baseline_never_uses_network(fixture, monkeypatch):
    monkeypatch.setattr(
        "delivery.cloud_ai.urlopen", lambda *a, **kw: pytest.fail("Unexpected network call")
    )
    result = evaluations.evaluate(fixture)
    assert result["summary"]["passed"] == 6
    assert result["summary"]["hard_policy_violations"] == 0
    assert result["summary"]["approval_agreement"] == 1
    assert "estimated_cost_usd" not in result
    assert result["mode"] == "offline-baseline"


def test_model_approval_is_measured_as_hard_violation(fixture):
    class Approve:
        def review(self, context, memory, *, candidate):
            return Judgment(
                decision="approve_retry",
                reason="yes",
                model="mock",
                input_tokens=10,
                output_tokens=2,
            )

    result = evaluations.evaluate(fixture, Approve(), pricing=(1, 2))
    assert result["summary"]["hard_policy_violations"] == 5
    assert result["summary"]["approval_agreement"] == pytest.approx(1 / 6)
    assert result["summary"]["input_tokens"] == 60
    assert result["summary"]["output_tokens"] == 12
    assert result["estimated_cost_usd"] == pytest.approx(0.000084)


@pytest.mark.parametrize(
    "error,status", [(TimeoutError, "provider_error"), (ValueError, "schema_failure")]
)
def test_errors_are_not_reported_as_model_denials(fixture, error, status):
    class Fails:
        def review(self, *args, **kwargs):
            raise error("failure")

    result = evaluations.evaluate(fixture, Fails())
    assert all(r["actual_decision"] is None and r["status"] == status for r in result["results"])
    assert result["summary"]["approval_agreement"] is None
    assert result["summary"]["passed"] == 0


def test_gateway_receives_fixture_context_and_bounded_calls(fixture):
    class Capture:
        calls = []

        def review(self, context, memory, *, candidate):
            self.calls.append((context, candidate))
            assert memory == []
            return Judgment(
                decision="deny_retry", reason="mock", model="mock", input_tokens=1, output_tokens=1
            )

    judge = Capture()
    evaluations.evaluate(fixture, judge, max_cases=2)
    assert len(judge.calls) == 2
    assert judge.calls[0][0]["job"]["retry_limit"] == 2
    with pytest.raises(ValueError, match="between"):
        evaluations.evaluate(fixture, judge, max_cases=13)
    assert len(judge.calls) == 2


def test_oracle_checks_cost_boundary_and_attempt_limit(fixture):
    case = fixture["cases"][0]
    case["candidate"]["estimated_seconds"] = 6000
    assert evaluations.baseline(case) == "approve_retry"
    case["candidate"]["estimated_seconds"] = 6001
    assert evaluations.baseline(case) == "deny_retry"
    case["candidate"]["estimated_seconds"] = 300
    case["facts"]["attempt"] = case["facts"]["retry_limit"]
    assert evaluations.baseline(case) == "deny_retry"


def test_malformed_response_is_schema_failure(fixture):
    class Malformed:
        def review(self, *args, **kwargs):
            return {"decision": "approve_retry", "tool": "execute"}

    result = evaluations.evaluate(fixture, Malformed(), max_cases=1)
    assert result["summary"]["schema_failures"] == 1
    assert result["results"][0]["actual_decision"] is None

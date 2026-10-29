import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from google.cloud.aiplatform_v1beta1.types import evaluation_service

from delivery.cloud_ai import EvalCostCaps, VertexPointwiseJudge, pointwise_payload


def case():
    return {"id": "one", "prompt": "Where is my order?", "order_status": "assigned",
            "advice": {"category": "status", "reply": "Your order is assigned."}}


def test_payload_matches_google_schema_and_uses_cheapest_flash_lite():
    body = pointwise_payload("where", "assigned", "Assigned.")
    parsed = evaluation_service.EvaluateInstancesRequest.from_json(json.dumps(body))
    assert parsed.autorater_config.autorater_model == "gemini-2.5-flash-lite"
    assert parsed.autorater_config.sampling_count == 1
    assert parsed.autorater_config.generation_config.max_output_tokens == 256
    assert parsed.pointwise_metric_input.instance.json_instance


def test_paid_calls_forbidden_in_pr_ci(tmp_path, monkeypatch):
    caps = EvalCostCaps(tmp_path / "ledger", "run")
    with pytest.raises(PermissionError):
        VertexPointwiseJudge("project-test", caps)
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    with pytest.raises(PermissionError):
        VertexPointwiseJudge("project-test", caps, paid=True)


def test_schema_length_and_invented_tools_are_checked_before_auth(tmp_path, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    caps = EvalCostCaps(tmp_path / "ledger", "run")
    judge = VertexPointwiseJudge("project-test", caps, paid=True,
                                 token_provider=lambda: pytest.fail("Auth before checks"))
    for changes, category in [
        ({"advice": {"category": "bad", "reply": "x"}}, "schema"),
        ({"advice": {"category": "status", "reply": "x" * 501}}, "length"),
        ({"calls": [{"name": "refund", "args": {}}]}, "invented_tool"),
    ]:
        assert judge.review({**case(), **changes})["code_failures"][0]["category"] == category


def test_timeout_keeps_reservation_and_never_retries(tmp_path, monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    sent = []

    def timeout(*args, **kwargs):
        sent.append(args)
        raise TimeoutError()

    monkeypatch.setattr("delivery.cloud_ai.urlopen", timeout)
    caps = EvalCostCaps(tmp_path / "ledger", "run", max_calls=2, max_usd=.01)
    judge = VertexPointwiseJudge("project-test", caps, paid=True, token_provider=lambda: "test")
    with pytest.raises(TimeoutError):
        judge.review(case())
    with pytest.raises(PermissionError):
        judge.review({**case(), "id": "two"})
    assert len(sent) == 1


def test_concurrent_durable_admission_cannot_exceed_budget(tmp_path):
    path = tmp_path / "ledger"
    caps = EvalCostCaps(path, "run", max_calls=12, max_usd=.02)

    def reserve(i):
        try:
            caps.reserve(str(i), b"{}")
            return True
        except PermissionError:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert sum(pool.map(reserve, range(12))) == 2
    restarted = EvalCostCaps(path, "run", max_calls=12, max_usd=.02)
    with pytest.raises(PermissionError):
        restarted.reserve("next", b"{}")
    with pytest.raises(ValueError, match="cannot change"):
        EvalCostCaps(path, "run", max_usd=.05)


def test_success_uses_pointwise_endpoint_and_replay_is_not_resent(tmp_path, monkeypatch):
    from io import BytesIO

    monkeypatch.delenv("CI", raising=False)
    requests = []

    def transport(request, timeout):
        requests.append(request)
        assert request.full_url.endswith("/locations/us-central1:evaluateInstances")
        assert timeout == 30
        body = json.loads(request.data)
        assert body["autoraterConfig"]["samplingCount"] == 1
        return BytesIO(b'{"pointwiseMetricResult":{"score":1,"explanation":"Grounded."}}')

    monkeypatch.setattr("delivery.cloud_ai.urlopen", transport)
    caps = EvalCostCaps(tmp_path / "ledger", "run")
    judge = VertexPointwiseJudge("project-test", caps, paid=True, token_provider=lambda: "test")
    assert judge.review(case())["judgment"]["score"] == 1
    with pytest.raises(PermissionError, match="already reserved"):
        judge.review(case())
    assert len(requests) == 1

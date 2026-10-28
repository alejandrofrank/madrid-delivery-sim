from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from delivery.durable_inference import local_proposal
from delivery.fleet_policy import cloud_judgement


def saved_judgement(decision="approve_retry", state="succeeded"):
    context = {
        "job": {"deadline_sim": 100, "pickup_node": 1, "customer_node": 2},
        "roads": {"edges": [{"from": 1, "to": 2, "travel_seconds": 20, "modes": ["bike"]}]},
        "fleet": [{"id": "bike-1", "node": 1, "busy_basket": None}],
    }
    event = SimpleNamespace(id=1, payload={"basket": "private", "attempt": 1})
    receipt = {
        "id": "request-1",
        "event_id": 1,
        "event_payload": event.payload,
        "request_hash": "digest",
        "definition_hash": "role",
        "context": context,
        "memory": [],
        "sim_time": 10,
        "proposal": local_proposal(context, 10),
        "state": state,
        "dispatch_attempt": 1,
        "prepared_attempt": 1,
        "result": {"decision": decision, "fallback": None, "provider": "gcp_ai"},
    }
    tools = SimpleNamespace(
        inference_receipt=receipt, sim=10, scope=SimpleNamespace(definition_hash="role")
    )
    return event, tools, context


@pytest.mark.parametrize("decision,approved", [("approve_retry", True), ("deny_retry", False)])
def test_cloud_receipt_can_only_veto_local_candidate(monkeypatch, decision, approved):
    network = Mock(side_effect=AssertionError("policy must never invoke network"))
    monkeypatch.setattr("delivery.cloud_ai.CloudJudge.review", network)
    event, tools, context = saved_judgement(decision)
    courier, route, audit = cloud_judgement(event, tools, context, [], "bike-1", [1, 2])
    assert (courier, route) == (("bike-1", [1, 2]) if approved else (None, None))
    assert audit["request_id"] == "request-1" and audit["fallback"] is None
    network.assert_not_called()


def test_unknown_outcome_is_fail_closed_without_network(monkeypatch):
    network = Mock(side_effect=AssertionError("unknown cannot be retried"))
    monkeypatch.setattr("delivery.cloud_ai.CloudJudge.review", network)
    event, tools, context = saved_judgement(state="unknown")
    tools.inference_receipt["result"] = {
        "provider": "gcp_ai",
        "error": "RuntimeError",
        "fallback": "fail_closed",
    }
    courier, route, audit = cloud_judgement(event, tools, context, [], "bike-1", [1, 2])
    assert courier is None and route is None
    assert audit["error"] == "RuntimeError" and audit["fallback"] == "fail_closed"
    network.assert_not_called()


@pytest.mark.parametrize("changed", ["memory", "sim", "proposal", "payload", "role"])
def test_incompatible_saved_approval_is_fail_closed(changed):
    event, tools, context = saved_judgement()
    if changed == "memory":
        tools.inference_receipt["memory"] = [{"body": "changed"}]
    elif changed == "sim":
        tools.sim = 11
    elif changed == "proposal":
        tools.inference_receipt["proposal"] = {"courier": "other"}
    elif changed == "payload":
        tools.inference_receipt["event_payload"] = {"basket": "another", "attempt": 1}
    else:
        tools.scope.definition_hash = "different-role"
    courier, route, audit = cloud_judgement(event, tools, context, [], "bike-1", [1, 2])
    assert courier is None and route is None
    assert audit["error"] == "PreconditionsChanged"
    assert tools.inference_receipt["result"]["decision"] == "approve_retry"


def test_direct_policy_without_saved_receipt_has_no_provider_capability():
    event, tools, context = saved_judgement()
    tools.inference_receipt = None
    with pytest.raises(PermissionError, match="durable"):
        cloud_judgement(event, tools, context, [], "bike-1", [1, 2])

import io
import json

import pytest

from delivery.cloud_ai import CloudJudge, Judgment, identity_token, sanitized_request


def test_only_bounded_numeric_facts_leave_machine():
    payload = sanitized_request(
        {
            "job": {"attempt": 1, "secret": "private", "cost_eur": float("nan")},
            "roads": {"private": "graph"},
        },
        [{"body": "private memory"}],
        candidate={"courier": "private-id", "route": [1, 2], "estimated_seconds": 200},
    )
    assert payload == {
        "facts": {"attempt": 1},
        "memory_entries": 1,
        "candidate": {"estimated_seconds": 200},
    }


@pytest.mark.parametrize("url", ["http://x.run.app", "https://evil.test", "https://x.run.app/a"])
def test_reject_non_cloud_run_origins(url):
    with pytest.raises(ValueError):
        CloudJudge(url)


def test_authenticated_bounded_request(monkeypatch):
    result = {
        "decision": "deny_retry",
        "reason": "No time",
        "model": "explicit-model",
        "input_tokens": 10,
        "output_tokens": 12,
    }

    def fake_open(request, timeout):
        assert request.full_url == "https://judge-abc.run.app/judge"
        assert request.get_header("Authorization") == "Bearer test-token"
        assert timeout == 30
        assert "private" not in request.data.decode()
        return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setattr("delivery.cloud_ai.urlopen", fake_open)
    judge = CloudJudge("https://judge-abc.run.app", lambda: "test-token")
    assert judge.review({"job": {}}, [], candidate=None).decision == "deny_retry"


def test_reject_arbitrary_model_actions():
    with pytest.raises(ValueError):
        Judgment(decision="execute_sql", reason="bad", model="m", input_tokens=0, output_tokens=1)


def test_reject_approval_without_proposal(monkeypatch):
    raw = json.dumps(
        {
            "decision": "approve_retry",
            "reason": "Go",
            "model": "m",
            "input_tokens": 1,
            "output_tokens": 2,
        }
    ).encode()
    monkeypatch.setattr("delivery.cloud_ai.urlopen", lambda *a, **kw: io.BytesIO(raw))
    with pytest.raises(ValueError, match="local route"):
        CloudJudge("https://judge-abc.run.app", lambda: "t").review({}, [], candidate=None)


def test_reject_oversized_model_response(monkeypatch):
    monkeypatch.setattr("delivery.cloud_ai.urlopen", lambda *a, **kw: io.BytesIO(b"x" * 17000))
    with pytest.raises(ValueError, match="byte budget"):
        CloudJudge("https://judge-abc.run.app", lambda: "t").review({}, [], candidate=None)


def test_local_adc_uses_keyless_id_token_impersonation(monkeypatch):
    import google.auth
    from google.auth import impersonated_credentials

    captured = {}
    source = object()
    target = object()
    monkeypatch.setenv(
        "DELIVERY_GCP_AI_CALLER_SERVICE_ACCOUNT", "caller@example.iam.gserviceaccount.com"
    )
    monkeypatch.setattr(google.auth, "default", lambda **kw: (source, "project"))

    def credentials(**kwargs):
        captured.update(kwargs)
        return target

    class Token:
        token = "minted-id-token"

        def __init__(self, given_target, **kwargs):
            assert given_target is target
            captured.update(kwargs)

        def refresh(self, request):
            captured["refreshed"] = True

    monkeypatch.setattr(impersonated_credentials, "Credentials", credentials)
    monkeypatch.setattr(impersonated_credentials, "IDTokenCredentials", Token)
    assert identity_token("https://judge-abc.run.app") == "minted-id-token"
    assert captured["source_credentials"] is source
    assert captured["lifetime"] == 300
    assert captured["target_audience"] == "https://judge-abc.run.app"
    assert captured["include_email"] and captured["refreshed"]


def test_classic_cloud_run_origin_is_supported():
    assert CloudJudge("https://judgement-abc-ew.a.run.app", lambda: "token").endpoint.endswith(
        ".a.run.app"
    )

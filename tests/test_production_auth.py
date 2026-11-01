import json

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from delivery.production_auth import AuthPolicy, ProductionAuth, verify_google_identity


def client(role="api", identity="operator@example.org", verified=True):
    async def receipt(request):
        return JSONResponse({"principal": request.state.principal})

    app = Starlette(routes=[Route("/{path:path}", receipt, methods=[
        "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"
    ])])
    policy = AuthPolicy("https://live.example", role, frozenset({"operator@example.org"}),
                        {"scheduler@project.iam.gserviceaccount.com": ["dispatcher"]})

    def verify(token, audience):
        assert audience == "https://live.example"
        if token != "valid":
            raise ValueError("sensitive verifier detail")
        return {"email": identity, "email_verified": verified}

    return TestClient(ProductionAuth(app, policy, verify))


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@pytest.mark.parametrize("path", ["/api/runs", "/api/supply/runs", "/mcp/", "/static/app.js"])
def test_all_live_routes_require_identity(method, path):
    assert client().request(method, path).status_code == 401
    response = client().request(method, path, headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert "sensitive" not in response.text


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_all_mutations_require_operator_not_just_valid_token(method):
    headers = {"Authorization": "Bearer valid"}
    assert client(identity="outsider@example.org").request(
        method, "/api/new-write-endpoint", headers=headers
    ).status_code == 403
    assert client().request(method, "/api/new-write-endpoint", headers=headers).status_code == 200


def test_a2a_role_and_target_are_both_bound():
    service = client("dispatcher", "scheduler@project.iam.gserviceaccount.com")
    headers = {"Authorization": "Bearer valid"}
    assert service.post("/a2a/dispatcher/", headers=headers).status_code == 200
    assert service.get("/a2a/dispatcher/.well-known/agent-card.json",
                       headers=headers).status_code == 200
    for path in ("/a2a/customer_service/", "/a2a/restaurant-test/", "/api/runs", "/mcp/"):
        assert service.post(path, headers=headers).status_code == 403
    assert client().post("/a2a/dispatcher/", headers=headers).status_code == 403


def test_csrf_unverified_email_and_liveness():
    headers = {"Authorization": "Bearer valid", "Origin": "https://attacker.example"}
    assert client().post("/api/runs", headers=headers).status_code == 403
    assert client(verified=False).get("/", headers=headers).status_code == 401
    assert client().get("/livez").json() == {"status": "ok"}
    assert client().post("/livez").status_code == 401


def test_google_verifier_enforces_audience_and_verified_email(monkeypatch):
    def google_verify(token, request, audience):
        assert token == "signed" and audience == "https://live.example"
        return {"email": "caller@example.org", "email_verified": True}

    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", google_verify)
    assert verify_google_identity("signed", "https://live.example")["email_verified"]
    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", lambda *a, **k: {})
    with pytest.raises(ValueError):
        verify_google_identity("signed", "https://live.example")


def test_policy_rejects_missing_operator_and_plaintext_audience(monkeypatch):
    monkeypatch.setenv("DELIVERY_AUTH_AUDIENCE", "http://localhost")
    with pytest.raises(ValueError):
        AuthPolicy.from_env()
    monkeypatch.setenv("DELIVERY_AUTH_AUDIENCE", "https://live.example")
    monkeypatch.delenv("DELIVERY_OPERATOR_PRINCIPALS", raising=False)
    with pytest.raises(ValueError):
        AuthPolicy.from_env()
    monkeypatch.setenv("DELIVERY_OPERATOR_PRINCIPALS", json.dumps(["operator@example.org"]))
    assert AuthPolicy.from_env().service_role == "api"


def test_authenticated_a2a_uses_target_audience_for_discovery_and_messages(monkeypatch):
    import asyncio
    from uuid import uuid4

    import httpx
    from fastapi import FastAPI

    from delivery.a2a_server import QueuedAgentService, create_a2a_app
    from delivery.agent_transport import A2ATransport

    monkeypatch.setenv("DELIVERY_RUNTIME", "live")
    monkeypatch.setenv("DELIVERY_A2A_BASE_URL", "https://dispatcher.example")
    audience_calls = []

    def token(request, audience):
        audience_calls.append(audience)
        return "signed-test-token"

    monkeypatch.setattr("google.oauth2.id_token.fetch_id_token", token)
    monkeypatch.setattr(QueuedAgentService, "invoke", lambda self, command: {"ok": True})
    app = FastAPI()
    requests = []

    @app.middleware("http")
    async def inspect(request, call_next):
        requests.append((request.url.hostname, request.headers.get("authorization"),
                         request.headers.get("x-serverless-authorization")))
        return await call_next(request)

    app.mount("/a2a/dispatcher", create_a2a_app("dispatcher"))
    transport = A2ATransport("https://api.example", authenticated=True,
                             endpoints={"dispatcher": "https://dispatcher.example"},
                             http_transport=httpx.ASGITransport(app=app))
    assert asyncio.run(transport.send("dispatcher", {
        "run_id": str(uuid4()), "entity_id": "order-1"
    })) == {"ok": True}
    assert audience_calls == ["https://dispatcher.example"]
    assert len(requests) == 2
    assert all(r == ("dispatcher.example", "Bearer signed-test-token",
                     "Bearer signed-test-token") for r in requests)

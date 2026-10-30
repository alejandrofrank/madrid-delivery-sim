"""Cloud Run IAM plus application authorization; no shared secrets or JSON keys."""

import asyncio
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


def role_for_agent(agent: str) -> str:
    return "restaurant" if agent.startswith("restaurant-") else agent


def verify_google_identity(token: str, audience: str) -> dict[str, Any]:
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.id_token import verify_oauth2_token

    claims = dict(verify_oauth2_token(token, GoogleRequest(), audience=audience))
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise ValueError("Verified Google identity required")
    return claims


@dataclass(frozen=True)
class AuthPolicy:
    audience: str
    service_role: str
    operators: frozenset[str]
    # Caller identity -> exact target agent roles. Never supplied by the request.
    callers: dict[str, list[str]]

    @classmethod
    def from_env(cls) -> "AuthPolicy":
        audience = os.environ.get("DELIVERY_AUTH_AUDIENCE", "")
        role = os.environ.get("DELIVERY_SERVICE_ROLE", "api")
        operators = json.loads(os.environ.get("DELIVERY_OPERATOR_PRINCIPALS", "[]"))
        callers = json.loads(os.environ.get("DELIVERY_A2A_CALLERS", "{}"))
        if (not audience.startswith("https://") or role not in {
            "api", "dispatcher", "restaurant", "customer_service"
        } or not isinstance(operators, list) or not isinstance(callers, dict)
            or any(not isinstance(e, str) or "@" not in e for e in operators)
            or any(not isinstance(e, str) or "@" not in e or not isinstance(v, list)
                   or any(r not in {"dispatcher", "restaurant", "customer_service"} for r in v)
                   for e, v in callers.items())):
            raise ValueError("Invalid production identity policy")
        if role == "api" and not operators:
            raise ValueError("Live API requires explicit operator principals")
        return cls(audience.rstrip("/"), role, frozenset(operators), callers)

    def permits(self, email: str, path: str, method: str) -> bool:
        if path.startswith("/a2a/"):
            target = role_for_agent(path.split("/", 3)[2])
            return (self.service_role == target
                    and target in self.callers.get(email, []))
        # Workers expose no management APIs, UI, arbitrary MCP or filesystem views.
        return self.service_role == "api" and email in self.operators


class ProductionAuth:
    """Wrap the entire ASGI application, including mounted protocol servers.

    Every route is private except a content-free liveness probe. Cloud Run IAM
    rejects unauthorized invokers first; this layer checks the role/path as well.
    X-Serverless-Authorization is for Cloud Run, Authorization for this verifier.
    """

    def __init__(
        self, app: ASGIApp, policy: AuthPolicy,
        verifier: Callable[[str, str], dict[str, Any]] = verify_google_identity,
    ) -> None:
        self.app, self.policy, self.verifier = app, policy, verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["path"] == "/livez" and scope["method"] in {"GET", "HEAD"}:
            await JSONResponse({"status": "ok"})(scope, receive, send)
            return
        request = Request(scope)
        header = request.headers.get("authorization", "")
        try:
            scheme, token = header.split(" ", 1)
            if scheme.lower() != "bearer" or not token or len(token) > 8192:
                raise ValueError("Invalid token")
            claims = await asyncio.to_thread(self.verifier, token, self.policy.audience)
            email = claims["email"]
            if claims.get("email_verified") is not True:
                raise ValueError("Unverified email")
        except Exception:
            await JSONResponse({"detail": "Authentication required"}, 401)(scope, receive, send)
            return
        origin = request.headers.get("origin")
        if ((origin and origin != self.policy.audience)
                or not self.policy.permits(email, scope["path"], scope["method"])):
            await JSONResponse({"detail": "Permission denied"}, 403)(scope, receive, send)
            return
        scope.setdefault("state", {})["principal"] = email
        await self.app(scope, receive, send)

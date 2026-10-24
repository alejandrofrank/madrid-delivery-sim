"""Optional authenticated remote judgement. No tools, credentials or world writes."""

import json
import math
import os
import re
from collections.abc import Callable
from typing import Any, Literal
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field

MAX_OUTPUT_TOKENS = 256
MAX_REQUEST_BYTES = 8192
TIMEOUT_SECONDS = 30


class Judgment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["approve_retry", "deny_retry"]
    reason: str = Field(min_length=1, max_length=600)
    model: str = Field(min_length=1, max_length=200)
    input_tokens: int = Field(ge=0, le=8192)
    output_tokens: int = Field(ge=0, le=MAX_OUTPUT_TOKENS)


def sanitized_request(
    context: dict[str, Any], memory: list[Any], *, candidate: dict[str, Any] | None
) -> dict[str, Any]:
    """Only allowlisted numeric facts leave the machine; memory text never leaves."""
    job = context.get("job", {})
    facts = {}
    for key in ("attempt", "retry_limit", "deadline_sim", "sim_time", "cost_eur"):
        value = job.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            facts[key] = value
    proposal: dict[str, Any] | None = None
    if candidate is not None:
        proposal = {}
        for key in ("estimated_seconds", "remaining_seconds", "route_nodes"):
            value = candidate.get(key)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value >= 0
            ):
                proposal[key] = value
    payload = {"facts": facts, "candidate": proposal, "memory_entries": min(len(memory), 100)}
    if len(json.dumps(payload).encode()) > MAX_REQUEST_BYTES:
        raise ValueError("Judgement request exceeds byte budget")
    return payload


def identity_token(audience: str) -> str:
    # google-auth ships with google-genai; lazy import keeps local mode independent.
    from google.auth.transport.requests import Request as AuthRequest
    from google.oauth2.id_token import fetch_id_token

    caller = os.environ.get("DELIVERY_GCP_AI_CALLER_SERVICE_ACCOUNT")
    if caller:
        import google.auth
        from google.auth import impersonated_credentials

        source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        target = impersonated_credentials.Credentials(
            source_credentials=source,
            target_principal=caller,
            target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
            lifetime=300,
        )
        credentials = impersonated_credentials.IDTokenCredentials(
            target, target_audience=audience, include_email=True
        )
        credentials.refresh(AuthRequest())
        return str(credentials.token)
    return str(fetch_id_token(AuthRequest(), audience))


class CloudJudge:
    def __init__(self, endpoint: str, token_provider: Callable[[], str] | None = None) -> None:
        if not re.fullmatch(r"https://[a-z0-9-]+\.run\.app", endpoint):
            raise ValueError("A Cloud Run HTTPS service origin is required")
        self.endpoint = endpoint
        self.token_provider = token_provider or (lambda: identity_token(endpoint))

    def review(
        self, context: dict[str, Any], memory: list[Any], *, candidate: dict[str, Any] | None
    ) -> Judgment:
        payload = sanitized_request(context, memory, candidate=candidate)
        request = Request(
            self.endpoint + "/judge",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + self.token_provider(),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(16385)
        if len(raw) > 16384:
            raise ValueError("Judgement response exceeds byte budget")
        result = Judgment.model_validate_json(raw)
        if candidate is None and result.decision == "approve_retry":
            raise ValueError("Cannot approve without a local route proposal")
        return result

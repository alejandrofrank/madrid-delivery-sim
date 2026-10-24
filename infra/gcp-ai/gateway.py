"""Private Cloud Run gateway; platform IAM authenticates callers before this app."""

import json
import os
import re
from typing import Literal

import google.auth
from fastapi import FastAPI, HTTPException
from google.auth.transport.requests import AuthorizedSession
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


class Facts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    attempt: float | int | None = None
    retry_limit: float | int | None = None
    deadline_sim: float | int | None = None
    sim_time: float | int | None = None
    cost_eur: float | int | None = None


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    estimated_seconds: float | int | None = None
    remaining_seconds: float | int | None = None
    route_nodes: float | int | None = None


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    facts: Facts
    candidate: Proposal | None
    memory_entries: int = Field(ge=0, le=100)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["approve_retry", "deny_retry"]
    reason: str = Field(min_length=1, max_length=600)


@app.post("/judge")
def judge(review: Review) -> dict:
    payload = review.model_dump(exclude_none=True)
    if len(json.dumps(payload).encode()) > 8192:
        raise HTTPException(413, "Request budget exceeded")
    model = os.environ["VERTEX_MODEL"]
    region = os.environ["VERTEX_REGION"]
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    if not all(re.fullmatch(r"[a-zA-Z0-9._-]+", x) for x in (model, region, project)):
        raise HTTPException(503, "Invalid gateway configuration")
    host = (
        "aiplatform.googleapis.com" if region == "global" else f"{region}-aiplatform.googleapis.com"
    )
    url = (
        f"https://{host}/v1/projects/{project}/locations/{region}/"
        f"publishers/google/models/{model}:generateContent"
    )
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    body = {
        "systemInstruction": {
            "parts": [
                {
                    "text": (
                        "Review a simulated parcel retry. Choose approve_retry or deny_retry only. "
                        "Deny if facts are insufficient or there is no candidate, "
                        "retry limit is exhausted, "
                        "or estimated_seconds exceeds remaining_seconds or 6000. "
                        "No tools or actions are available. Explain briefly; return JSON only."
                    )
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": json.dumps(payload)}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 256,
            "candidateCount": 1,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "required": ["decision", "reason"],
                "properties": {
                    "decision": {"type": "STRING", "enum": ["approve_retry", "deny_retry"]},
                    "reason": {"type": "STRING"},
                },
            },
        },
    }
    try:
        with AuthorizedSession(credentials) as session:
            counted = session.post(
                url.removesuffix(":generateContent") + ":countTokens",
                json={key: body[key] for key in ("systemInstruction", "contents")},
                timeout=5,
            )
            counted.raise_for_status()
            if not 0 <= counted.json()["totalTokens"] <= 8192:
                raise ValueError("Input token budget exceeded")
            response = session.post(url, json=body, timeout=15, stream=True)
            response.raise_for_status()
            chunks = []
            size = 0
            for chunk in response.iter_content(4096):
                size += len(chunk)
                if size > 65536:
                    raise ValueError("Vertex response too large")
                chunks.append(chunk)
        data = json.loads(b"".join(chunks))
        candidate = data["candidates"][0]
        if candidate["finishReason"] != "STOP":
            raise ValueError("Incomplete model output")
        decision = Decision.model_validate_json(candidate["content"]["parts"][0]["text"])
        if review.candidate is None and decision.decision == "approve_retry":
            raise ValueError("Missing route proposal")
        usage = data["usageMetadata"]
        output = usage["candidatesTokenCount"]
        if not 0 <= output <= 256 or not 0 <= usage["promptTokenCount"] <= 8192:
            raise ValueError("Token budget exceeded")
        return {
            **decision.model_dump(),
            "model": model,
            "input_tokens": usage["promptTokenCount"],
            "output_tokens": output,
        }
    except Exception as exc:
        raise HTTPException(502, "Model judgement unavailable") from exc

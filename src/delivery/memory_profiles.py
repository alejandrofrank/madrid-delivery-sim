"""Bounded recall representations over canonical, scoped typed observations.

Profiles change what an agent can recall, never its tools or source of authority.
Postgres owns scope, fact validation, retention and the immutable revision ledger.
Callers retain the canonical facts for provenance and stale-result fencing.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MemoryMode = Literal["none", "text", "json", "typed"]
MemoryFacts = list[dict[str, Any]]
MemoryProjection = MemoryFacts | str | dict[str, Any]


class MemoryProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: MemoryMode = "typed"
    max_facts: int = Field(default=8, ge=1, le=8, strict=True)
    max_bytes: int = Field(default=8192, ge=256, le=8192, strict=True)
    ttl_seconds: int = Field(default=3600, ge=60, le=86400, strict=True)


_SCOPE_KEYS = ("run_id", "store", "owner_role", "context_type", "context_id")
_SOURCE_KEYS = (
    "fact_id",
    "version",
    "event_id",
    "observed_sim",
    "expires_sim",
    "previous_id",
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _same_scope(facts: MemoryFacts) -> dict[str, Any]:
    """Fail closed on accidentally combined recall results; never choose a scope."""
    scope = {key: facts[0][key] for key in _SCOPE_KEYS if key in facts[0]} if facts else {}
    if any({key: fact[key] for key in _SCOPE_KEYS if key in fact} != scope for fact in facts):
        raise ValueError("Memory projection requires one canonical run, role and order scope")
    return scope


def _text_fact(fact: dict[str, Any]) -> str:
    source = ", ".join(
        f"{label}={fact[key]}"
        for key, label in (
            ("fact_id", "fact"),
            ("version", "version"),
            ("event_id", "event"),
            ("observed_sim", "observed"),
            ("expires_sim", "expires"),
            ("previous_id", "previous"),
        )
        if key in fact
    )
    return f"{fact['kind']} {fact['subject']}: {_json(fact['body'])} [{source}]"


def project_memory(profile: MemoryProfile | None, facts: MemoryFacts) -> MemoryProjection:
    """Project already scoped facts for a policy/model, leaving raw facts untouched.

    ``None`` preserves legacy recall exactly. Explicit profiles enforce the recall
    limits again at the representation boundary. Whole facts are omitted when
    they cannot fit; bodies and provenance are never truncated or summarized.
    Text and JSON are display formats for typed facts, rather than freeform
    storage or vector retrieval. Expiry is enforced by the scoped SQL recall.
    """
    if profile is None:
        return facts
    if profile.mode == "none":
        return []
    scope = _same_scope(facts)
    candidates = facts[: profile.max_facts]
    if profile.mode == "typed":
        selected: MemoryFacts = []
        for fact in candidates:
            if len(_json([*selected, fact]).encode("utf-8")) > profile.max_bytes:
                break
            selected.append(fact)
        return facts if len(selected) == len(facts) else selected
    if profile.mode == "text":
        lines = [f"Scope: {_json(scope)}"] if candidates else []
        for fact in candidates:
            line = _text_fact(fact)
            if len("\n".join([*lines, line]).encode("utf-8")) > profile.max_bytes:
                break
            lines.append(line)
        # A scope without a fact is not a memory observation.
        return "\n".join(lines) if len(lines) > 1 else ""
    result: dict[str, Any] = {"scope": scope, "facts": []}
    if len(_json(result).encode("utf-8")) > profile.max_bytes:
        return {"scope": {}, "facts": []}
    for fact in candidates:
        entry = {
            "kind": fact["kind"],
            "subject": fact["subject"],
            "body": fact["body"],
            "provenance": {key: fact[key] for key in _SOURCE_KEYS if key in fact},
        }
        proposed = {**result, "facts": [*result["facts"], entry]}
        if len(_json(proposed).encode("utf-8")) > profile.max_bytes:
            break
        result = proposed
    return result

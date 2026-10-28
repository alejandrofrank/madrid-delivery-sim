"""Durable, single-dispatch optional judgement outside worker DB connections.

A dispatch marker consumes the bounded allowance before provider I/O. If its
outcome cannot be known, a subsequent lease fails closed and never resends it.
This deliberately does not claim exactly-once provider execution or billing.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from delivery.cloud_ai import CloudJudge, Judgment, sanitized_request
from delivery.db import connect
from delivery.queue import Event

if TYPE_CHECKING:
    from delivery.agent_runtime import LocalAgent

Fault = Callable[[str], None] | None


def checkpoint(fault: Fault, stage: str) -> None:
    if fault is not None:
        fault(stage)


def local_proposal(context: dict[str, Any], sim: int) -> dict[str, Any]:
    """The model may only veto this locally computed, numeric route summary."""
    from delivery.workflow_policy import route_plan

    try:
        courier, route = route_plan(context)
    except ValueError:
        return {"courier": None, "route": None, "candidate": None}
    edges = {(e["from"], e["to"]): e["travel_seconds"] for e in context["roads"]["edges"]}
    candidate = {
        "estimated_seconds": sum(edges[a, b] for a, b in zip(route, route[1:], strict=False)),
        "remaining_seconds": max(0, context["job"]["deadline_sim"] - sim),
        "route_nodes": len(route),
    }
    return {"courier": courier, "route": route, "candidate": candidate}


def prepare(agent: "LocalAgent", event: Event) -> dict[str, Any]:
    """Commit a server-scoped observation and sealed request in one short tx."""
    if agent.role.name != "judge" or agent.role.policy != "gcp_ai" or not agent.cloud_endpoint:
        raise PermissionError("Configured cloud judge required")
    with connect(agent.dsn) as conn:
        row = conn.execute(
            "SELECT public.agent_inference_begin(%s,%s,%s,%s) AS request",
            (event.id, event.token, event.attempts, agent.cloud_endpoint),
        ).fetchone()
        assert row
        request = dict(row["request"])
        if request["state"] == "preparing":
            proposal = local_proposal(request["context"], request["sim_time"])
            outbound = sanitized_request(
                {"job": {**request["context"]["job"], "sim_time": request["sim_time"]}},
                request["memory"],
                candidate=proposal["candidate"],
            )
            row = conn.execute(
                "SELECT public.agent_inference_seal(%s,%s,%s,%s,%s,%s) AS request",
                (
                    event.id,
                    event.token,
                    event.attempts,
                    request["id"],
                    Jsonb(proposal),
                    Jsonb(outbound),
                ),
            ).fetchone()
            assert row
            request = dict(row["request"])
    return request


def ensure_result(agent: "LocalAgent", event: Event, *, fault: Fault = None) -> bool:
    """Prepare/dispatch/save, returning False only when another owner is busy/stale.

    Each connection context has exited before a hook adjacent to I/O or the
    provider itself runs. There are no automatic provider retries, including
    malformed responses, timeouts, and a process lost after dispatch commit.
    """
    request = prepare(agent, event)
    checkpoint(fault, "after_prepare")
    if request["state"] == "in_flight":
        return False
    if request["state"] == "prepared":
        with connect(agent.dsn) as conn:
            row = conn.execute(
                "SELECT public.agent_inference_dispatch(%s,%s,%s,%s) AS dispatch",
                (event.id, event.token, event.attempts, request["id"]),
            ).fetchone()
            assert row
            dispatch = row["dispatch"]
            request = dispatch["request"]
        if not dispatch["dispatch"]:
            return request["state"] in {"succeeded", "failed", "unknown"}
        checkpoint(fault, "after_dispatch")
        checkpoint(fault, "before_invoke")
        outcome: dict[str, Any] | None = None
        error: str | None = None
        try:
            # Even the transport adapter receives only numeric facts and a count;
            # scoped context, memory bodies, route/courier IDs stay in PostgreSQL.
            outbound = request["sanitized_request"]
            raw = CloudJudge(request["endpoint"]).review(
                {"job": outbound["facts"]},
                [None] * outbound["memory_entries"],
                candidate=outbound["candidate"],
            )
            result = Judgment.model_validate(raw.model_dump())
            if outbound["candidate"] is None and result.decision == "approve_retry":
                raise ValueError("Cannot approve without a local route proposal")
            outcome = result.model_dump()
        except Exception as exc:
            # Exception text may include response bodies or authentication data.
            error = type(exc).__name__
        checkpoint(fault, "after_response")
        checkpoint(fault, "before_result_save")
        with connect(agent.dsn) as conn:
            row = conn.execute(
                "SELECT public.agent_inference_save(%s,%s,%s,%s,%s,%s,%s) AS saved",
                (
                    event.id,
                    event.token,
                    event.attempts,
                    request["id"],
                    request["dispatch_token"],
                    Jsonb(outcome) if outcome is not None else None,
                    error,
                ),
            ).fetchone()
            assert row
            saved = bool(row["saved"])
        if not saved:
            return False
        checkpoint(fault, "after_result_save")
        return True
    return request["state"] in {"succeeded", "failed", "unknown"}


def saved_result(conn: Any, agent: "LocalAgent", event: Event) -> dict[str, Any]:
    """The effect transaction can read a receipt; it has no provider capability."""
    row = conn.execute(
        "SELECT public.agent_inference_read(%s,%s,%s) AS request",
        (event.id, event.token, event.attempts),
    ).fetchone()
    if not row:
        raise PermissionError("Durable inference receipt required")
    request = dict(row["request"])
    if request["endpoint"] != agent.cloud_endpoint or request["state"] not in {
        "succeeded",
        "failed",
        "unknown",
    }:
        raise PermissionError("Completed compatible inference receipt required")
    return request


def apply_receipt(conn: Any, event: Event, request: dict[str, Any]) -> None:
    row = conn.execute(
        "SELECT public.agent_inference_applied(%s,%s,%s,%s) AS applied",
        (event.id, event.token, event.attempts, request["id"]),
    ).fetchone()
    if not row or not row["applied"]:
        raise PermissionError("Inference apply lease expired")

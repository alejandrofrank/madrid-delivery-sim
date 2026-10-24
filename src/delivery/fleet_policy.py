"""Bounded local recovery policies; briefings and judgements are queued simulations."""

from typing import Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from delivery.agent_runtime import BasketRef, ScopedTools
from delivery.db import connect
from delivery.queue import Event
from delivery.workflow_policy import route_plan


class AttemptRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    basket: str = Field(min_length=1, max_length=100)
    attempt: int = Field(ge=1, le=10)


def recorded_context(context: dict[str, Any]) -> dict[str, Any]:
    """Record relevant observations once without duplicating the entire road graph."""
    return {
        key: (
            {"nodes": len(value["nodes"]), "edges": len(value["edges"])}
            if key == "roads"
            else value
        )
        for key, value in context.items()
    }


class FleetPolicy:
    def decide(
        self, event: Event, tools: ScopedTools, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        role = tools.role.name
        if event.topic in {"basket.ready", "dispatch.retry"}:
            basket = BasketRef.model_validate(event.payload).basket
            attempt = None
        else:
            ref = AttemptRef.model_validate(event.payload)
            basket, attempt = ref.basket, ref.attempt
        if context is None:
            name = {"judge": "judge.read", "courier": "courier.read"}.get(role, "dispatch.read")
            arguments: dict[str, Any] = {"basket": basket}
            if role in {"judge", "courier"}:
                arguments["attempt"] = attempt
            context = tools.invoke(name, **arguments)
        if (
            role == "dispatcher"
            and attempt is not None
            and context["job"].get("attempt") != attempt
        ):
            return {
                "basket": basket,
                "status": "stale_attempt_ignored",
                "attempt": attempt,
                "rule": "ignore delayed messages from superseded delivery attempts",
                "tools": tools.calls,
                "role_hash": tools.scope.definition_hash,
            }
        memory = tools.invoke("memory.read")
        emits: list[tuple[str, dict[str, Any], str, int]] = []
        if role == "judge":
            try:
                courier, route = route_plan(context)
            except ValueError:
                courier, route = None, None
            cloud_audit = None
            if tools.role.policy == "gcp_ai":
                courier, route, cloud_audit = cloud_judgement(
                    event, tools, context, memory, courier, route
                )
            result = tools.invoke(
                "judge.review", basket=basket, attempt=attempt, courier=courier, route=route
            )
            emits.append(
                (
                    "recovery.reviewed",
                    {"basket": basket, "attempt": attempt},
                    f"{basket}:{attempt}",
                    tools.sim,
                )
            )
            if cloud_audit is not None:
                result["cloud_judgement"] = cloud_audit
            rule = "approve a feasible bounded retry only within remaining deadline and cost cap"
        elif role == "courier":
            result = tools.invoke("courier.accept", basket=basket, attempt=attempt)
            emits.append(
                (
                    "courier.accepted",
                    {"basket": basket, "attempt": attempt},
                    f"{basket}:{attempt}",
                    tools.sim,
                )
            )
            rule = "accept only the current assigned attempt and its scoped custody briefing"
        elif event.topic == "recovery.reviewed":
            result = tools.invoke("dispatch.recover", basket=basket, attempt=attempt)
            if result["status"] == "ready":
                emits.append(
                    (
                        "dispatch.retry",
                        {"basket": basket},
                        f"recovery:{basket}:{attempt}",
                        tools.sim,
                    )
                )
            else:
                emits.append(
                    ("dispatch.noted", {"basket": basket}, f"denied:{basket}:{attempt}", tools.sim)
                )
            rule = "reassign only after an approved judge verdict; retain denied parcel custody"
        elif event.topic == "courier.accepted":
            result = {"basket": basket, "attempt": attempt, "status": "briefing_acknowledged"}
            emits.append(
                ("dispatch.noted", {"basket": basket}, f"accepted:{basket}:{attempt}", tools.sim)
            )
            rule = "record queued courier acknowledgement; the world controls movement"
        elif event.topic == "delivery.arrived":
            result = tools.invoke("dispatch.complete", basket=basket)
            emits.append(("delivery.completed", {"basket": basket}, basket, tools.sim))
            rule = "confirm only an authoritative arrival for the current accepted attempt"
        elif event.topic in {"basket.ready", "dispatch.retry"}:
            if context["job"]["status"] in {"ready", "deferred"}:
                try:
                    courier, route = route_plan(context)
                except ValueError:
                    result = tools.invoke("dispatch.defer", basket=basket)
                    emits.append(
                        (
                            "dispatch.retry",
                            {"basket": basket},
                            f"wait:{basket}:{tools.sim}",
                            tools.sim + 1200,
                        )
                    )
                else:
                    result = tools.invoke(
                        "dispatch.assign", basket=basket, courier=courier, route=route
                    )
                    payload = {"basket": basket, "attempt": result["attempt"]}
                    key = f"{basket}:{result['attempt']}"
                    emits.extend(
                        [
                            ("delivery.assigned", payload, key, tools.sim),
                            ("courier.briefed", payload, key, tools.sim),
                        ]
                    )
            else:
                result = {"basket": basket, "status": context["job"]["status"]}
            rule = "claim a free online courier atomically, or wait through a queued retry"
        else:
            raise PermissionError("Unsupported recovery event")
        tools.invoke("memory.write", key=f"last:{basket}", body=result)
        for topic, payload, key, due in emits:
            tools.invoke("queue.publish", topic=topic, payload=payload, key=key, due_sim=due)
        return {
            **result,
            "rule": rule,
            "observed_state": recorded_context(context),
            "memory_hits": len(memory),
            "tools": tools.calls,
            "scope": {"run": tools.scope.run, "namespace": tools.scope.store},
            "role_hash": tools.scope.definition_hash,
            "policy": tools.role.policy,
        }


def cloud_judgement(
    event: Event,
    tools: ScopedTools,
    context: dict[str, Any],
    memory: list[dict[str, Any]],
    courier: str | None,
    route: list[int] | None,
) -> tuple[str | None, list[int] | None, dict[str, Any]]:
    """Model can veto a local candidate; SQL still owns every feasibility gate."""
    from delivery.cloud_ai import CloudJudge

    candidate = None
    if route is not None:
        edges = {(e["from"], e["to"]): e["travel_seconds"] for e in context["roads"]["edges"]}
        candidate = {
            "estimated_seconds": sum(edges[a, b] for a, b in zip(route, route[1:], strict=False)),
            "remaining_seconds": context["job"]["deadline_sim"] - tools.sim,
            "route_nodes": len(route),
        }
    audit: dict[str, Any] = {"provider": "gcp_ai", "fallback": "fail_closed"}
    try:
        if not tools.cloud_endpoint:
            raise ValueError("Cloud endpoint required")
        model_context = {**context, "job": {**context.get("job", {}), "sim_time": tools.sim}}
        judgement = CloudJudge(tools.cloud_endpoint).review(
            model_context, memory, candidate=candidate
        )
        audit.update(judgement.model_dump())
        audit["fallback"] = None
        if judgement.decision != "approve_retry":
            courier, route = None, None
    except Exception as exc:
        audit["error"] = type(exc).__name__
        courier, route = None, None
    if tools.cloud_dsn is None:
        raise PermissionError("Durable cloud audit connection required")
    with connect(tools.cloud_dsn) as conn:
        conn.execute(
            "SELECT public.agent_record_model(%s,%s,%s)",
            (event.id, event.attempts, Jsonb(audit)),
        )
    return courier, route, audit

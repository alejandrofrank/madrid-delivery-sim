"""Rules-only fulfillment and dispatch policies using the shared scoped tool runtime."""

from typing import Any

import networkx as nx

from delivery.agent_runtime import BasketRef, ScopedTools
from delivery.queue import Event
from delivery.typed_memory import outcome_fact


def route_plan(context: dict[str, Any]) -> tuple[str, list[int]]:
    graph: nx.DiGraph[int] = nx.DiGraph()
    for edge in context["roads"]["edges"]:
        if "bike" in edge["modes"]:
            graph.add_edge(edge["from"], edge["to"], weight=edge["travel_seconds"])
    job = context["job"]
    candidates = []
    for courier in context["fleet"]:
        if courier["busy_basket"] is not None or courier.get("status", "active") != "active":
            continue
        try:
            first = nx.shortest_path(graph, courier["node"], job["pickup_node"], weight="weight")
            last = nx.shortest_path(
                graph, job["pickup_node"], job["customer_node"], weight="weight"
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        route = first + last[1:]
        seconds = sum(graph[a][b]["weight"] for a, b in zip(route, route[1:], strict=False))
        candidates.append((seconds, courier["id"], route))
    if not candidates:
        raise ValueError("No available courier")
    _, courier_id, route = min(candidates)
    return str(courier_id), list(route)


class WorkflowPolicy:
    def decide(self, event: Event, tools: ScopedTools) -> dict[str, Any]:
        if (
            (event.topic == "delivery.arrived" and "attempt" in event.payload)
            or tools.role.name in {"courier", "judge"}
            or event.topic
            in {
                "dispatch.retry",
                "recovery.reviewed",
                "courier.accepted",
            }
        ):
            from delivery.fleet_policy import FleetPolicy

            return FleetPolicy().decide(event, tools)
        basket = BasketRef.model_validate(event.payload).basket
        prefix = "fulfillment" if tools.role.name == "fulfillment" else "dispatch"
        context = tools.invoke(f"{prefix}.read", basket=basket)
        if context.get("expanded"):
            from delivery.fleet_policy import FleetPolicy

            return FleetPolicy().decide(event, tools, context)
        memory = tools.invoke("memory.read")
        if event.topic == "basket.reserved":
            result = tools.invoke("fulfillment.pick", basket=basket)
            topic = "basket.ready"
            rule = "pick a live own-store reservation once; hand off through the queue"
        elif event.topic == "basket.ready":
            if context["job"]["status"] == "ready":
                courier, route = route_plan(context)
                result = tools.invoke(
                    "dispatch.assign", basket=basket, courier=courier, route=route
                )
            else:
                result = {"basket": basket, "status": context["job"]["status"]}
            topic = "delivery.assigned"
            rule = "assign an available courier over connected roads via pickup and drop-off"
        elif event.topic == "delivery.arrived":
            result = tools.invoke("dispatch.complete", basket=basket)
            topic = "delivery.completed"
            rule = "confirm delivery only after authoritative world arrival"
        else:
            raise PermissionError("Unsupported workflow event")
        tools.invoke("memory.write", **outcome_fact(tools.role.name, event.topic, result))
        tools.invoke("queue.publish", topic=topic, payload={"basket": basket}, key=basket)
        return {
            **result,
            "rule": rule,
            "observed_state": context,
            "memory_hits": len(memory),
            "tools": tools.calls,
            "scope": {"run": tools.scope.run, "namespace": tools.scope.store},
            "role_hash": tools.scope.definition_hash,
            "policy": tools.role.policy,
        }

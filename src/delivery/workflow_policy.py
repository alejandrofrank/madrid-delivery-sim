"""Rules-only fulfillment and dispatch policies using the shared scoped tool runtime."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, Any, cast

import networkx as nx

from delivery.dispatch_optimizer import Candidate, optimize_dispatch

if TYPE_CHECKING:
    from delivery.agent_runtime import ScopedTools
    from delivery.queue import Event


def route_plan(context: dict[str, Any]) -> tuple[str, list[int]]:
    """Choose one scoped basket's quickest live-node route, with a stable fair tie.

    The projection contains one job, so this is a single-job use of the shared
    matcher. Per-basket hashes avoid permanently favoring a courier ID when
    travel times tie; they do not claim historical workload balancing.
    """
    graph: nx.DiGraph[int] = nx.DiGraph()
    for edge in context["roads"]["edges"]:
        if "bike" in edge["modes"]:
            graph.add_edge(edge["from"], edge["to"], weight=edge["travel_seconds"])
    job = context["job"]
    try:
        last = nx.shortest_path(graph, job["pickup_node"], job["customer_node"], weight="weight")
        delivery_seconds = nx.path_weight(graph, last, weight="weight")
        pickup_seconds, pickup_paths = cast(
            tuple[dict[int, float], dict[int, list[int]]],
            nx.single_source_dijkstra(
                graph.reverse(copy=False), job["pickup_node"], weight="weight"
            ),
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound) as error:
        raise ValueError("No available courier") from error

    # Real scoped jobs include basket; retain support for older minimal contexts.
    basket = str(job.get("basket", "scoped-basket"))
    candidates: list[Candidate] = []
    routes: dict[str, list[int]] = {}
    for courier in context["fleet"]:
        if courier["busy_basket"] is not None or courier.get("status", "active") != "active":
            continue
        if courier["node"] not in pickup_paths:
            continue
        courier_id = str(courier["id"])
        first = list(reversed(pickup_paths[courier["node"]]))
        routes[courier_id] = first + last[1:]
        rank = int.from_bytes(sha256(f"{basket}\0{courier_id}".encode()).digest()[:8], "big")
        candidates.append(
            Candidate(
                basket,
                courier_id,
                round((pickup_seconds[courier["node"]] + delivery_seconds) * 1000),
                rank,
            )
        )
    assignments = optimize_dispatch(candidates, max_orders=1)
    if not assignments:
        raise ValueError("No available courier")
    courier_id = assignments[0].courier_id
    return courier_id, routes[courier_id]


class WorkflowPolicy:
    def decide(self, event: Event, tools: ScopedTools) -> dict[str, Any]:
        from delivery.agent_runtime import BasketRef
        from delivery.typed_memory import outcome_fact

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

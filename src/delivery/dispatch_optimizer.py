"""Pure, bounded maximum-cardinality/minimum-cost fleet assignment.

The caller supplies only feasible edges and integer costs. No road, database,
clock, or provider access belongs here. Lower ``tie_break_rank`` values express
the caller's fair preference when the total primary cost is equal.
"""

from collections.abc import Iterable
from dataclasses import dataclass

import networkx as nx

MAX_BATCH_SIZE = 100


@dataclass(frozen=True, slots=True)
class Candidate:
    order_id: str
    courier_id: str
    cost: int
    tie_break_rank: int = 0

    def __post_init__(self) -> None:
        for name in ("order_id", "courier_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        for name in ("cost", "tie_break_rank"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative integer")


def optimize_dispatch(
    candidates: Iterable[Candidate],
    *,
    max_orders: int = MAX_BATCH_SIZE,
    max_couriers: int = MAX_BATCH_SIZE,
) -> tuple[Candidate, ...]:
    """Serve as many orders as possible, then minimize total cost and fair rank.

    Each order and courier can appear in at most one selected edge. Missing
    edges are infeasible; empty input produces no assignments. Duplicate pairs
    and oversized batches fail instead of silently changing the problem.

    Input iteration order never affects the result. Supply distinct, stable
    ranks for couriers to make otherwise equal choices independent of their
    names, for example ranks rotated by prior assignments. Equal ranks declare
    no fair preference; identifiers only stabilize those unspecified ties.
    Returned edges are sorted by order ID solely for application/audit output.
    """
    for name, value in (("max_orders", max_orders), ("max_couriers", max_couriers)):
        if type(value) is not int or not 1 <= value <= MAX_BATCH_SIZE:
            raise ValueError(f"{name} must be an integer from 1 to {MAX_BATCH_SIZE}")

    edges: dict[tuple[str, str], Candidate] = {}
    orders: set[str] = set()
    courier_ranks: dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, Candidate):
            raise TypeError("candidates must contain Candidate instances")
        pair = candidate.order_id, candidate.courier_id
        if pair in edges:
            raise ValueError(f"duplicate candidate pair: {pair!r}")
        edges[pair] = candidate
        orders.add(candidate.order_id)
        courier_ranks[candidate.courier_id] = min(
            courier_ranks.get(candidate.courier_id, candidate.tie_break_rank),
            candidate.tie_break_rank,
        )
        if len(orders) > max_orders or len(courier_ranks) > max_couriers:
            raise ValueError("dispatch batch exceeds the bounded order or courier count")
    if not edges:
        return ()

    # A unit of primary cost must dominate every possible aggregate fair rank.
    cardinality_bound = min(len(orders), len(courier_ranks))
    cost_scale = cardinality_bound * max(c.tie_break_rank for c in edges.values()) + 1
    graph: nx.DiGraph = nx.DiGraph()
    source, sink = ("source", ""), ("sink", "")
    graph.add_nodes_from((source, sink))
    for order_id in sorted(orders):
        graph.add_edge(source, ("order", order_id), capacity=1, weight=0)
    for courier_id in sorted(courier_ranks, key=lambda c: (courier_ranks[c], c)):
        graph.add_edge(("courier", courier_id), sink, capacity=1, weight=0)
    for candidate in sorted(
        edges.values(), key=lambda c: (c.order_id, c.tie_break_rank, c.courier_id)
    ):
        graph.add_edge(
            ("order", candidate.order_id),
            ("courier", candidate.courier_id),
            capacity=1,
            weight=candidate.cost * cost_scale + candidate.tie_break_rank,
        )

    # NetworkX first fixes maximum flow, so arbitrarily expensive feasible
    # assignments cannot be dropped in favor of a cheaper smaller matching.
    flow = nx.max_flow_min_cost(graph, source, sink)
    return tuple(
        candidate
        for candidate in sorted(edges.values(), key=lambda c: (c.order_id, c.courier_id))
        if flow[("order", candidate.order_id)].get(("courier", candidate.courier_id), 0)
    )

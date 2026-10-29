"""Frozen, inspectable dispatch economics; no model or external service access."""

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from delivery.dispatch_optimizer import Candidate
from delivery.world import COST_PER_KM


class DispatchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    strategy: Literal["min_cost", "legacy"] = "min_cost"
    reposition: Literal["stay", "demand_aware"] = "stay"
    initial_positions: Literal["distributed", "hubs"] = "distributed"
    time_value_eur_per_hour: float = Field(default=12, ge=1, le=100)
    late_weight: float = Field(default=20, ge=1, le=100)
    empty_time_weight: float = Field(default=1, ge=0, le=10)
    demand_window_seconds: int = Field(default=1800, ge=300, le=7200)
    reposition_max_m: int = Field(default=1500, ge=100, le=3000)
    reposition_cooldown_seconds: int = Field(default=900, ge=300, le=3600)
    reposition_min_saving_seconds: int = Field(default=120, ge=30, le=900)


def load_policy(config: dict[str, Any]) -> DispatchPolicy:
    # Historical runs with no frozen config retain their original policy.
    return DispatchPolicy.model_validate(
        config or {"strategy": "legacy", "initial_positions": "hubs"}
    )


def operating_cost(distance_m: float, mode: str, *, job: bool = False) -> float:
    """Synthetic marginal vehicle cost plus the existing €1 task fee."""
    return float(job) + distance_m / 1000 * COST_PER_KM[mode]


def assignment_score(
    route: dict[str, Any], mode: str, sim: int, due: int, policy: DispatchPolicy
) -> dict[str, float]:
    """Generalized seconds: service duration, lateness, empty time and money.

    Prep wait can equalize completion ETAs; explicit empty driving and money
    still distinguish couriers. The fixed task fee is excluded from ranking.
    """
    components = {
        "completion_seconds": max(0, route["end_at"] - sim),
        "late_penalty_seconds": max(0, route["end_at"] - due) * policy.late_weight,
        "empty_penalty_seconds": route["pickup_travel_seconds"] * policy.empty_time_weight,
        "vehicle_cost_seconds": operating_cost(route["distance_m"], mode)
        * 3600
        / policy.time_value_eur_per_hour,
    }
    return {**components, "total": sum(components.values())}


def fair_ranks(couriers: list[dict[str, Any]], salt: str) -> dict[str, int]:
    """Longest idle, then fewer jobs, then a reproducible non-lexical lottery."""
    ordered = sorted(
        couriers,
        key=lambda c: (
            c["idle_since_sim"],
            c["completed_jobs"],
            hashlib.sha256(f"{salt}:{c['id']}".encode()).digest(),
        ),
    )
    return {c["id"]: rank for rank, c in enumerate(ordered)}


def prioritize_deadlines(candidates: list[Candidate], order_ids: list[str]) -> list[Candidate]:
    """After maximum cardinality, serve earliest deadlines before comparing cost.

    Charging lateness only to selected jobs would make an already-late job ever
    more expensive and starve it. Binary ranks encode lexicographic service
    priority for the bounded batch. A unit dominates all possible economic costs;
    within the same served order set the economic objective is unchanged.
    """
    if not candidates:
        return []
    ranks = {order: i for i, order in enumerate(order_ids)}
    count = len(ranks)
    cardinality = min(count, len({c.courier_id for c in candidates}))
    scale = cardinality * max(c.cost for c in candidates) + 1
    return [
        Candidate(
            c.order_id,
            c.courier_id,
            c.cost + ((1 << count) - (1 << (count - ranks[c.order_id] - 1))) * scale,
            c.tie_break_rank,
        )
        for c in candidates
    ]

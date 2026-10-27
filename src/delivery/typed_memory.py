"""Versioned, role-specific observations, never authoritative inventory or instructions."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FactBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ReservationFact(FactBody):
    status: Literal["reserved", "rejected", "expired", "cancelled", "fulfilled"]


class ShipmentFact(FactBody):
    status: Literal["delayed", "deferred", "received", "already_received"]
    expected_sim: int | None = Field(default=None, ge=0, le=604800)


class FulfillmentFact(FactBody):
    status: Literal["picked"]


class DeliveryFact(FactBody):
    status: Literal[
        "ready",
        "assigned",
        "in_transit",
        "arrived",
        "delivered",
        "deferred",
        "awaiting_review",
        "abandoned",
        "briefing_acknowledged",
    ]
    attempt: int | None = Field(default=None, ge=1, le=10)
    courier: str | None = Field(default=None, min_length=1, max_length=100)
    eta_sim: int | None = Field(default=None, ge=0, le=604800)


class CourierFact(FactBody):
    status: Literal["accepted"]
    attempt: int = Field(ge=1, le=10)


class RecoveryFact(FactBody):
    verdict: Literal["approved", "denied"]
    attempt: int = Field(ge=1, le=10)
    reason: str = Field(min_length=1, max_length=240)
    estimated_seconds: int | None = Field(default=None, ge=0, le=604800)
    remaining_seconds: int = Field(ge=-604800, le=604800)


class MealFact(FactBody):
    status: Literal[
        "intent",
        "calling",
        "sourcing",
        "awaiting_approval",
        "cooking",
        "ready",
        "delivered",
        "failed",
    ]
    action: Literal[
        "calling",
        "restaurant_intake",
        "terminal_ignored",
        "deadline_expired",
        "late_ingredient_received",
        "unfulfillable",
        "substitution_offered",
        "stale_shortage_ignored",
        "household_approved",
        "household_declined",
        "stale_offer_ignored",
        "restaurant_approved",
        "ingredient_received",
        "meal_ready",
        "delivered",
        "delivery_failed",
        "awaiting_delivery",
        "status_observed",
    ]
    reason: str | None = Field(default=None, max_length=240)


class SupplierFact(FactBody):
    ingredient: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0, le=1000000)
    unit: Literal["g", "ml", "piece"]
    outcome: Literal[
        "supplier_reserved",
        "supplier_shortage",
        "supplier_dispatched",
        "forwarded",
        "stale_request_ignored",
        "terminal_ignored",
        "deadline_expired",
    ]


# kind -> role, entity within the order (request or whole order), accepted topics, body.
# SQL stores a snapshot of these schemas; a regression test prevents silent drift.
CONTRACTS: dict[str, tuple[str, str, tuple[str, ...], type[FactBody]]] = {
    "inventory.reservation": (
        "inventory",
        "order",
        ("basket.requested", "reservation.expire"),
        ReservationFact,
    ),
    "inventory.shipment": (
        "inventory",
        "shipment",
        ("shipment.delayed", "shipment.received"),
        ShipmentFact,
    ),
    "fulfillment.progress": ("fulfillment", "order", ("basket.reserved",), FulfillmentFact),
    "delivery.progress": (
        "dispatcher",
        "order",
        (
            "basket.ready",
            "dispatch.retry",
            "recovery.reviewed",
            "courier.accepted",
            "delivery.arrived",
        ),
        DeliveryFact,
    ),
    "courier.commitment": ("courier", "order", ("courier.briefed",), CourierFact),
    "recovery.verdict": ("judge", "order", ("delivery.failed",), RecoveryFact),
    "household.order": (
        "household",
        "order",
        ("household.intent", "household.offer", "household.status", "meal.delivery"),
        MealFact,
    ),
    "restaurant.order": (
        "restaurant",
        "order",
        (
            "household.call",
            "ingredient.shortage",
            "ingredient.arrived",
            "restaurant.approval",
            "restaurant.cook",
        ),
        MealFact,
    ),
    "market.request": ("market", "request", ("market.request", "market.transfer"), SupplierFact),
}


def validate_fact(kind: str, body: dict[str, Any], role: str, topic: str) -> dict[str, Any]:
    contract = CONTRACTS.get(kind)
    if not contract or contract[0] != role or topic not in contract[2]:
        raise PermissionError("Memory fact type is outside this role and incoming event")
    return contract[3].model_validate(body).model_dump(mode="json", exclude_none=True)


def outcome_fact(
    role: str,
    topic: str,
    result: dict[str, Any],
    context: dict[str, Any] | None = None,
    request: str | None = None,
) -> dict[str, Any]:
    """Project only role-relevant fields from trusted tools; never copy a whole context."""
    if role in {"household", "restaurant"}:
        return {
            "kind": f"{role}.order",
            "body": {k: result[k] for k in ("status", "action", "reason") if k in result},
        }
    if role == "market":
        row = next((r for r in (context or {}).get("requests", []) if r["id"] == request), None)
        if row is None:
            raise PermissionError("A supplier observation requires the current scoped request")
        return {
            "kind": "market.request",
            # Pending promises stay available through the transfer delay. Once
            # this market finishes its part, keep a short recall window and the
            # permanent audit revision instead of filling live memory all hour.
            "ttl_seconds": 3600 if result["action"] == "supplier_reserved" else 60,
            "body": {
                "ingredient": row["ingredient"],
                "quantity": float(row["quantity"]),
                "unit": row["unit"],
                "outcome": result["action"],
            },
        }
    if role == "inventory":
        if topic in {"basket.requested", "reservation.expire"}:
            return {"kind": "inventory.reservation", "body": {"status": result["status"]}}
        status = (
            "delayed"
            if topic == "shipment.delayed"
            else "deferred"
            if result.get("deferred")
            else "received"
            if result.get("received")
            else "already_received"
        )
        return {
            "kind": "inventory.shipment",
            "body": {
                "status": status,
                **({"expected_sim": result["expected_sim"]} if "expected_sim" in result else {}),
            },
        }
    if role == "fulfillment":
        return {"kind": "fulfillment.progress", "body": {"status": result["status"]}}
    if role == "courier":
        return {"kind": "courier.commitment", "body": {k: result[k] for k in ("status", "attempt")}}
    if role == "judge":
        return {
            "kind": "recovery.verdict",
            "body": {
                k: result[k]
                for k in ("verdict", "attempt", "reason", "estimated_seconds", "remaining_seconds")
                if k in result
            },
        }
    if role == "dispatcher":
        return {
            "kind": "delivery.progress",
            "body": {
                **{k: result[k] for k in ("status", "attempt", "courier") if k in result},
                **({"eta_sim": result["arrive_sim"]} if "arrive_sim" in result else {}),
            },
        }
    raise PermissionError("No memory contract for this role")

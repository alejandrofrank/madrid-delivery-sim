"""Run-frozen fleet contracts and factual, deterministic courier communications.

These are simulated operators, not affiliations with real delivery companies.
Wording never changes routing, deadlines, queue topics, or refund policy.
"""

from typing import Any


def fleet_plan() -> dict[str, Any]:
    return {
        "version": 1,
        "fleets": [
            {
                "id": "regular",
                "name": "Bakiano",
                "operator": "regular",
                "style": "direct",
                "coverage": "network",
                "modes_per_hub": ["bike", "bike", "moto", "moto", "van", "van", "bike", "moto"],
            },
            {
                "id": "sol",
                "name": "Sol Riders",
                "operator": "contractor",
                "style": "conversational",
                "coverage": "home_district",
                "modes_per_hub": ["bike", "bike", "bike"],
            },
            {
                "id": "castellana",
                "name": "Castellana Logistics",
                "operator": "contractor",
                "style": "radio",
                "coverage": "network",
                "modes_per_hub": ["moto", "moto", "van"],
            },
        ],
    }


def fleet_contract(config: dict[str, Any] | None, fleet_id: str) -> dict[str, Any]:
    for fleet in (config or {}).get("fleets", []):
        if fleet["id"] == fleet_id:
            return dict(fleet)
    # Historical runs and laboratory fixtures predate fleet contracts.
    return {
        "id": fleet_id,
        "name": "Bakiano",
        "operator": "regular",
        "style": "direct",
        "coverage": "network",
    }


def eligible(contract: dict[str, Any], courier: dict[str, Any], order: dict[str, Any]) -> bool:
    if contract["coverage"] != "home_district":
        return True
    return order["store_district"] == order["customer_district"] == courier["home_district"]


def communication(
    fleet: dict[str, Any],
    courier: str,
    action: str,
    *,
    order: str | None = None,
    eta_sim: float | None = None,
) -> dict[str, Any]:
    """One machine-readable envelope; stylistic differences only in its text."""
    phrases = {
        "accepted_route": "Route accepted",
        "picked_up": "Order collected",
        "delivered": "Delivery completed",
        "assignment_cancelled": "Cannot complete within shift; returning assignment",
        "reposition_accepted": "Moving to staging point",
        "reposition_cancelled": "Staging move cancelled; insufficient shift time",
        "repositioned": "At staging point; available",
    }
    fact = phrases[action]
    prefix = {"direct": "", "conversational": "Got it. ", "radio": "Copy. "}[fleet["style"]]
    if action in {"picked_up", "delivered", "repositioned"}:
        prefix = {"direct": "", "conversational": "Quick update. ", "radio": "Status. "}[
            fleet["style"]
        ]
    text = f"{prefix}{fact}."
    if order:
        text += f" Order {order}."
    if eta_sim is not None:
        minute = int((10 * 3600 + eta_sim + 59) // 60)
        text += f" Delivery ETA {minute // 60:02d}:{minute % 60:02d} (simulation)."
    return {
        "schema": "courier-status/1",
        "fleet_id": fleet["id"],
        "fleet_name": fleet["name"],
        "operator": fleet["operator"],
        "style": fleet["style"],
        "sender": courier,
        "recipient": "dispatcher",
        "status": action,
        "order_id": order,
        "eta_sim": eta_sim,
        "text": text,
        "source": "deterministic_courier",
    }

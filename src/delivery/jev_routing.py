"""Jev-first bounded decisions. Unknown judgments escalate; permissions never do."""

import json
import math
import time
from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from delivery.supply_search import JevClient, SearchError

if TYPE_CHECKING:
    from delivery.adk_restaurant import RestaurantTurn

Review = Callable[[dict[str, Any]], dict[str, Any]]
ACTION_TO_TOOL = {
    "source": "request_missing_ingredients",
    "confirm": "confirm_order",
    "receive": "receive_ingredient",
    "cook": "prepare_meal",
    "offer": "offer_substitution",
    "decline": "decline_order",
}


def decision_request(turn: "RestaurantTurn", order: dict[str, Any]) -> dict[str, Any]:
    """Read authenticated facts; omit unrelated stock, household identity and chat."""
    routing = turn.brain.routing
    assert routing
    recipe = turn.read_recipe()
    pantry = {row["ingredient"]: row for row in turn.read_pantry()}
    ingredients = []
    for item in recipe["ingredients"]:
        stock = pantry.get(item["id"], {})
        ingredients.append(
            {
                "id": item["id"],
                "unit": item["unit"],
                "required": item["quantity"] * order["quantity"],
                "available": stock.get("on_hand", 0) - stock.get("reserved", 0),
            }
        )
    needs_supplier = order["event"] != "household.call" or any(
        item["available"] < item["required"] for item in ingredients
    )
    suppliers = turn.find_suppliers() if needs_supplier else []
    memory = turn.recall_order_memory()
    actions = (
        {
            "source": "Source shortages from a quoted supplier, following the SOUL",
            "confirm": "Confirm only when physical pantry covers the recipe",
            "decline": "Decline only if the order cannot be safely fulfilled",
        }
        if order["event"] in {"household.call", "restaurant.approval"}
        else {
            "offer": "Offer the provided safe alternative for queued household approval",
            "decline": "Decline if no safe, consented option is possible",
        }
    )
    request: dict[str, Any] = {
        "model": routing.model,
        "state": {
            "policy": turn.brain.instructions,
            "soul": turn.agent.role.soul,
            "observations": {
                "event": order["event"],
                "meal": order["meal"],
                "deadline": order["deadline"],
                "sim_time": order["sim_time"],
                "ingredients": ingredients,
                "pantry_covers_recipe": not any(
                    item["available"] < item["required"] for item in ingredients
                ),
                "suppliers": suppliers,
                "safe_alternative": order.get("safe_alternative"),
                "selected_memory": memory,
            },
        },
        "questions": {
            "executor": {
                "type": "choice",
                "instructions": routing.instructions,
                "criteria": {
                    "direct": "A safe bounded decision is clear; no additional model needed",
                    "gemini": (
                        "Uncertain, conflicting, missing evidence, or a requested reasoned tradeoff"
                    ),
                },
            },
            "action": {
                "type": "choice",
                "instructions": "Select the permitted next action.",
                "criteria": actions,
            },
            "supplier": {
                "type": "choice",
                "instructions": (
                    "Choose the supplier following the SOUL; abstain if unclear or not sourcing."
                ),
                "criteria": {
                    **{
                        s["id"]: (
                            f"fee {s['procurement_fee_cents']} cents; "
                            f"lead time {s['estimated_seconds']} seconds"
                        )
                        for s in suppliers
                    },
                    "uncertain": "No supplier decision is needed or supported by the facts",
                },
            },
        },
    }
    if not needs_supplier:
        del request["questions"]["supplier"]
    return request


def checked_answer(raw: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    if set(raw) != {"model", "answers", "usage"} or raw["model"] != request["model"]:
        raise ValueError("Invalid router model/schema")
    if not isinstance(raw["answers"], dict) or set(raw["answers"]) != set(request["questions"]):
        raise ValueError("Invalid router questions")
    usage = raw["usage"]
    if (
        not isinstance(usage, dict)
        or "input_tokens" not in usage
        or any(type(v) is not int or v < 0 for v in usage.values())
        or set(usage) - {"input_tokens", "output_tokens"}
    ):
        raise ValueError("Invalid router usage")
    for key, question in request["questions"].items():
        answer = raw["answers"][key]
        allowed = set(question["criteria"])
        if not isinstance(answer, dict) or set(answer) - {
            "type",
            "choice",
            "confidence",
            "probabilities",
        }:
            raise ValueError("Invalid router answer")
        probs, confidence = answer.get("probabilities"), answer.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("Invalid router confidence")
        if (
            answer.get("type", "choice") != "choice"
            or answer.get("choice") not in allowed
            or type(confidence) not in {int, float}
            or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
            or not isinstance(probs, dict)
            or set(probs) != allowed
            or any(
                type(p) not in {int, float} or not math.isfinite(p) or not 0 <= p <= 1
                for p in probs.values()
            )
            or abs(sum(probs.values()) - 1) > 0.01
            or probs[answer["choice"]] != max(probs.values())
        ):
            raise ValueError("Invalid router probabilities")
    return raw


def confidence(raw: dict[str, Any], keys: list[str]) -> tuple[float, float]:
    confidences, margins = [], []
    for key in keys:
        answer = raw["answers"][key]
        values = sorted(answer["probabilities"].values(), reverse=True)
        confidences.append(float(answer["confidence"]))
        margins.append(float(values[0] - (values[1] if len(values) > 1 else 0)))
    return min(confidences), min(margins)


def stage(
    turn: "RestaurantTurn",
    action: str,
    supplier: str | None = None,
    substitute: str | None = None,
    label: str = "Jev",
) -> None:
    kwargs: dict[str, str] = {}
    if action == "source":
        assert supplier
        kwargs["supplier"] = supplier
    if action == "offer":
        assert substitute
        kwargs["substitute"] = substitute
    if action == "decline":
        kwargs["reason"] = "No safely supported fulfillment action in the scoped observations"
    getattr(turn, ACTION_TO_TOOL[action])(**kwargs)
    turn.finish_decision(f"{label} {action}: scoped facts and validated tool policy.")


def route_turn(turn: "RestaurantTurn", reviewer: Review | None = None) -> bool:
    """True = a staged direct plan, False = committed Gemini escalation receipt."""
    routing = turn.brain.routing
    assert routing
    order = turn.read_order()
    topic = order["event"]  # Never trust the caller's Event payload/topic.
    if topic in {"ingredient.arrived", "restaurant.cook"}:
        turn.sql("restaurant_route_begin", Jsonb({}), True)
        stage(
            turn, "receive" if topic == "ingredient.arrived" else "cook", label="No-model protocol"
        )
        assert turn.plan
        turn.sql(
            "restaurant_route_complete",
            "rules",
            Jsonb(turn.plan.model_dump()),
            None,
            None,
            None,
            "unambiguous_queue_protocol",
            None,
            0,
        )
        return True
    request = decision_request(turn, order)
    # Initialize the real transport before admission; missing credentials/opt-in
    # cannot accidentally enable a paid fallback. Unit tests inject a local double.
    if reviewer is None:
        client = JevClient()
        if client.model != routing.model:
            raise PermissionError("Router model differs from the approved deployment")
        reviewer = client.request
    turn.sql("restaurant_route_begin", Jsonb(request), False)
    turn.fault("before_jev_router")
    started = time.monotonic()
    raw: dict[str, Any] | None = None
    conf: float | None = None
    gap: float | None = None
    why, error = "uncertain_judgment", None
    direct, action, supplier = False, "", None
    try:
        raw = reviewer(request)
        turn.fault("after_jev_router")
        checked_answer(raw, request)
        if raw["usage"]["input_tokens"] > len(json.dumps(request).encode()) + 2048:
            raise ValueError("Usage exceeded router admission")
        answers = raw["answers"]
        action = answers["action"]["choice"]
        keys = ["executor", "action"] + (["supplier"] if action == "source" else [])
        conf, gap = confidence(raw, keys)
        direct = (
            answers["executor"]["choice"] == "direct"
            and conf >= routing.confidence_threshold
            and gap >= routing.margin_threshold
        )
        supplier = answers.get("supplier", {}).get("choice")
        obs = request["state"]["observations"]
        # Feasibility is independent of the classifier's certainty.
        if (
            (action == "source" and supplier not in {s["id"] for s in obs["suppliers"]})
            or (
                action == "confirm"
                and any(i["available"] < i["required"] for i in obs["ingredients"])
            )
            or (action == "offer" and not order.get("safe_alternative"))
        ):
            direct = False
            why = "unsupported_action_or_missing_evidence"
        elif not direct:
            why = (
                "jev_requested_reasoning_model"
                if answers["executor"]["choice"] == "gemini"
                else "below_confidence_or_margin"
            )
        else:
            why = "confident_bounded_jev_decision"
    except (ValueError, KeyError, TypeError, SearchError, TimeoutError) as exc:
        # Unknown usage remains reserved; do not retry Jev. Gemini is a distinct,
        # explicitly budgeted escalation for this unknown judgment.
        error = type(exc).__name__
        why = "unknown_provider_judgment"
    elapsed = min(60000, max(0, round((time.monotonic() - started) * 1000)))
    if direct:
        stage(turn, action, supplier, order.get("safe_alternative"))
    turn.sql(
        "restaurant_route_complete",
        "jev" if direct else "gemini",
        Jsonb(turn.plan.model_dump()) if turn.plan else None,
        Jsonb(raw) if raw is not None else None,
        Decimal(str(conf)) if conf is not None else None,
        Decimal(str(gap)) if gap is not None else None,
        why,
        error,
        elapsed,
    )
    return direct

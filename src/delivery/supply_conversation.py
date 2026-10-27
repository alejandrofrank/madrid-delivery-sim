"""Read-only, deterministic conversation presentation for the local operator.

These sentences describe recorded queue envelopes; they are not generated dialogue.
No presentation data is returned through an agent's scoped tools.
"""

import hashlib
import json
from typing import Any

_FIRST = (
    "Alba",
    "Bruno",
    "Clara",
    "Diego",
    "Elena",
    "Hugo",
    "Inés",
    "Leo",
    "Lucía",
    "Mateo",
    "Nora",
    "Pablo",
    "Sara",
    "Vera",
    "Iván",
    "Sofía",
)
_LAST = (
    "Vega",
    "Costa",
    "Ríos",
    "Soler",
    "Gil",
    "Luna",
    "Paz",
    "Soto",
    "Rey",
    "Vidal",
    "Marín",
    "Cruz",
    "León",
    "Vila",
    "Mora",
    "Lara",
)
_ROLES = {
    "household": "Customer agent",
    "restaurant": "Kitchen agent",
    "market": "Stock agent",
    "courier": "Courier agent",
    "dispatcher": "Dispatcher",
    "judge": "Recovery judge",
}
_SYSTEM = {
    "supply_ingress": "Order scheduler",
    "lab_world": "City operations",
    "city_audit": "City audit",
    "lab_scenario": "Simulation scheduler",
}


def words(value: str) -> str:
    return value.replace("_", " ").replace(".", " ").strip().capitalize()


def participant(identity: str | None, entities: dict[str, dict[str, Any]]) -> dict[str, str]:
    identity = identity or "city_audit"
    entity_id = identity
    prefix, _, suffix = identity.partition(":")
    if prefix in _ROLES and suffix:
        entity_id = suffix if prefix in {"household", "restaurant", "market"} else identity
    entity = entities.get(entity_id, {})
    role = str(entity.get("kind", prefix))
    if identity in _SYSTEM or role not in _ROLES:
        name = _SYSTEM.get(identity, words(identity))
        return {
            "id": identity,
            "name": name,
            "initials": "•",
            "role": "System",
            "kind": "system",
            "entity": str(entity.get("name", "Local simulation")),
        }
    # Store IDs and authenticated agent IDs resolve to the same fictional person.
    digest = hashlib.sha256(entity_id.encode()).digest()
    first, last = _FIRST[digest[0] % len(_FIRST)], _LAST[digest[1] % len(_LAST)]
    return {
        "id": identity,
        "name": f"{first} {last}",
        "initials": first[0] + last[0],
        "role": _ROLES[role],
        "kind": role,
        "entity": str(entity.get("name", words(entity_id))),
    }


def memory_change(write: dict[str, Any]) -> dict[str, Any]:
    """Distinguish an audited baseline, expired memory and legacy unknown values."""
    known = "previous" in write
    previous = write.get("previous")
    expired = bool(previous and previous["expires_sim"] <= write["observed_sim"])
    before = previous["body"] if previous and not expired else {}
    after = write["body"]
    changes = []
    # Explicit presence flags distinguish a missing value from false, zero or null.
    for key in sorted(before.keys() | after.keys()):
        had, has = key in before, key in after
        if (
            known
            and had == has
            and json.dumps(before.get(key), sort_keys=True)
            == json.dumps(after.get(key), sort_keys=True)
        ):
            continue
        changes.append(
            {
                "field": key,
                "label": words(key),
                "had_before": had,
                "has_after": has,
                "before": before.get(key),
                "after": after.get(key),
            }
        )
    mode = (
        "unknown"
        if not known
        else "expired"
        if expired
        else "created"
        if previous is None
        else "updated"
        if changes
        else "unchanged"
    )
    return {**write, "mode": mode, "changes": changes}


def message_text(
    topic: str, payload: dict[str, Any], call: dict[str, Any] | None, request: dict[str, Any] | None
) -> str:
    amount = ""
    if request:
        ingredient = words(request["ingredient"]).lower()
        amount = f"{request['quantity']} {request['unit']} of {ingredient}"
    original = words(payload.get("ingredient", "the ingredient")).lower()
    proposed = words(payload.get("proposed", "the proposed alternative")).lower()
    texts = {
        "household.intent": "It’s time for this household’s scheduled meal order.",
        "household.call": (call or {}).get("transcript") or "I’d like to place a meal order.",
        "market.request": f"Can you supply {amount}?"
        if amount
        else "Can you supply this ingredient request?",
        "market.transfer": "Release the reserved ingredients for dispatch.",
        "ingredient.arrived": "The ingredient transfer is ready to be received by the kitchen.",
        "ingredient.shortage": "The supplier search could not fulfil this ingredient request.",
        "household.offer": f"May we replace {original} with {proposed}?",
        "restaurant.approval": "I approve the proposed ingredient substitution.",
        "household.status": "Please check the latest status of this meal order.",
        "restaurant.cook": "Check all ingredient allocations, then finish preparing the meal.",
        "basket.ready": "The meal is ready. Please arrange a courier.",
        "dispatch.retry": "Try assigning an available courier again.",
        "courier.briefed": "Please review your assigned delivery and custody briefing.",
        "courier.accepted": "I’ve reviewed the assigned delivery briefing.",
        "delivery.assigned": "A courier has been assigned. Please check the delivery attempt.",
        "delivery.arrived": "The courier arrival has been reported. Please confirm the handoff.",
        "delivery.completed": "The delivery completion has been reported.",
        "delivery.failed": "This delivery attempt failed. Please review recovery options.",
        "recovery.reviewed": "The recovery review is complete. Please apply the recorded decision.",
        "dispatch.noted": "Record the delivery outcome.",
        "meal.delivery": "Check whether the courier has delivered my meal.",
    }
    return texts.get(topic, f"Recorded message: {words(topic).lower()}.")


def conversation(data: dict[str, Any], entities: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = {d["event_id"]: d for d in data["decisions"]}
    facts = {f["event_id"]: f for f in data["facts"] if f["event_id"] is not None}
    writes: dict[int, list[dict[str, Any]]] = {}
    for write in data["memory_history"]:
        writes.setdefault(write["event_id"], []).append(memory_change(write))
    # A retained row is only a snapshot, never evidence of an unrecorded transition.
    for write in data["memories"]:
        if write["event_id"] not in writes:
            writes.setdefault(write["event_id"], []).append(memory_change(write))
    messages = []
    for event in data["events"]:
        parent = decisions.get(event["parent_id"]) or facts.get(event["parent_id"])
        decision = decisions.get(event["id"])
        fact = facts.get(event["id"])
        # Request details must come from the send-time after-image, never today's stock.
        parent_fact = facts.get(event["parent_id"], {})
        request = next(
            (
                r
                for r in parent_fact.get("request_state") or []
                if r["id"] == event["payload"].get("request")
            ),
            None,
        )
        received = decision or fact
        detail = received["detail"] if received else {}
        messages.append(
            {
                "event_id": event["id"],
                "topic": event["topic"],
                "state": event["state"],
                "sender": participant(event["sender"], entities),
                "recipient": participant(event["target_store"], entities),
                "sim_time": parent["sim_time"] if parent else event["due_sim"],
                "time_kind": "sent" if parent else "due",
                "due_sim": event["due_sim"],
                "processed_sim": received["sim_time"] if received else None,
                "text": message_text(event["topic"], event["payload"], data["call"], request),
                "outcome": {
                    k: detail[k] for k in ("action", "status", "reason", "rule") if k in detail
                },
                "memory": writes.get(event["id"], []),
                "attempts": event["attempts"],
            }
        )
    return sorted(messages, key=lambda m: (m["sim_time"], m["event_id"]))

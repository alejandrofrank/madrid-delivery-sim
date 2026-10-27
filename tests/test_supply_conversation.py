"""Presentation must not turn unknown historical state into invented dialogue."""

from delivery.supply_conversation import conversation, memory_change, participant


def test_personas_are_stable_across_store_and_agent_ids() -> None:
    entities = {"pizza": {"name": "Pizza Kitchen", "kind": "restaurant"}}
    a, b = participant("pizza", entities), participant("restaurant:pizza", entities)
    assert a["name"] == b["name"] and a["initials"] == b["initials"]
    assert a["role"] == "Kitchen agent" and a["entity"] == "Pizza Kitchen"
    assert participant("lab_world", {})["kind"] == "system"
    assert participant(None, {})["name"] == "City audit"


def test_memory_diff_preserves_absence_false_zero_null_and_removals() -> None:
    diff = memory_change(
        {
            "body": {"status": "cooking", "zero": 0, "flag": False, "null": None},
            "observed_sim": 20,
            "previous": {
                "body": {"status": "sourcing", "removed": None},
                "expires_sim": 21,
            },
        }
    )
    assert diff["mode"] == "updated"
    fields = {c["field"]: c for c in diff["changes"]}
    assert fields["status"]["before"] == "sourcing"
    assert fields["status"]["after"] == "cooking"
    for key in ("zero", "flag", "null"):
        assert fields[key]["has_after"] and not fields[key]["had_before"]
    assert fields["removed"]["had_before"] and not fields["removed"]["has_after"]


def test_memory_baselines_distinguish_new_expired_unchanged_and_legacy() -> None:
    write = {"body": {"status": "ready"}, "observed_sim": 30}
    assert memory_change(write)["mode"] == "unknown"
    assert memory_change({**write, "previous": None})["mode"] == "created"
    previous = {"body": write["body"], "expires_sim": 31}
    same = memory_change({**write, "previous": previous})
    assert same["mode"] == "unchanged" and same["changes"] == []
    expired = memory_change({**write, "previous": {**previous, "expires_sim": 30}})
    assert expired["mode"] == "expired"
    assert not expired["changes"][0]["had_before"]
    typed = memory_change(
        {
            "body": {"flag": 0},
            "observed_sim": 30,
            "previous": {"body": {"flag": False}, "expires_sim": 31},
        }
    )
    assert typed["mode"] == "updated" and typed["changes"][0]["field"] == "flag"


def test_conversation_uses_send_time_request_and_labels_unknown_timestamps() -> None:
    data = {
        "call": None,
        "events": [
            {
                "id": 2,
                "parent_id": 1,
                "topic": "market.request",
                "sender": "pizza",
                "target_store": "market-a",
                "state": "done",
                "due_sim": 50,
                "payload": {"request": "r"},
                "attempts": 1,
            },
            {
                "id": 3,
                "parent_id": None,
                "topic": "unknown.topic",
                "sender": "lab_world",
                "target_store": None,
                "state": "ready",
                "due_sim": 5,
                "payload": {},
                "attempts": 0,
            },
        ],
        "facts": [
            {
                "event_id": 1,
                "sim_time": 10,
                "detail": {},
                "request_state": [{"id": "r", "quantity": 200, "unit": "g", "ingredient": "flour"}],
            }
        ],
        "decisions": [
            {
                "event_id": 2,
                "sim_time": 55,
                "detail": {"action": "supplier_reserved", "status": "sourcing"},
            }
        ],
        "memory_history": [
            {
                "event_id": 2,
                "agent": "market:market-a",
                "key": "last:o",
                "body": {"status": "sourcing"},
                "observed_sim": 55,
                "expires_sim": 100,
                "previous": None,
            }
        ],
        "memories": [],
        "requests": [{"id": "r", "ingredient": "rice", "quantity": 999}],
    }
    chat = conversation(data, {"pizza": {"name": "Pizza Kitchen", "kind": "restaurant"}})
    assert chat[0]["time_kind"] == "due" and chat[0]["processed_sim"] is None
    assert chat[0]["text"] == "Recorded message: unknown topic."
    message = chat[1]
    assert message["text"] == "Can you supply 200 g of flour?"
    assert message["sim_time"] == 10 and message["due_sim"] == 50
    assert message["time_kind"] == "sent" and message["processed_sim"] == 55
    assert message["memory"][0]["mode"] == "created"
    data["facts"] = []
    assert conversation(data, {})[1]["text"] == "Can you supply this ingredient request?"
    # A world message's parent links its cause; it does not identify its sender/time.
    data["events"][0]["producer"] = "lab_world"
    data["decisions"].append({"event_id": 1, "sim_time": 10, "detail": {}})
    assert conversation(data, {})[1]["time_kind"] == "due"
    assert conversation(data, {})[1]["sim_time"] == 50

"""Reviewed recorded defaults remain useful without live infrastructure."""

import copy
import hashlib
import json
import socket
from pathlib import Path

import pytest

from delivery.product_examples import EXAMPLE_KINDS, load_example


@pytest.mark.parametrize("kind", sorted(EXAMPLE_KINDS))
def test_bundled_examples_are_complete_synthetic_read_only_and_zero_paid_calls(kind, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Loading an example attempted a service connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unavailable/private")
    monkeypatch.setenv("LLM_PROVIDER", "vertex")
    payload = load_example(kind)
    assert payload["recording"]["paid_model_calls"] == 0
    assert payload["recording"]["synthetic"] is True
    assert payload["recording"]["read_only"] is True
    assert len(payload["recording"]["source_revision"]) == 40


def test_inventory_example_explains_real_recovery_and_preserves_all_checkpoints():
    data = load_example("inventory")["data"]
    assert all(data["invariants"].values())
    assert data["crash"]["exit_code"] == 73
    assert data["crash"]["recovered_attempts"] == 2
    assert len(data["checkpoints"]) == 6
    assert any(checkpoint["state"]["run"]["sim_time"] == 300 for checkpoint in data["checkpoints"])
    assert all(event["state"] == "done" for event in data["events"])
    assert data["stock"] and data["agents"] and data["decisions"]
    assert "Synthetic" in data["catalogue"]["origin"]


def test_restaurant_example_retains_order_conversation_and_scoped_agent_evidence():
    data = load_example("restaurant")["data"]
    state = data["snapshot"]
    assert all(state["invariants"].values())
    assert data["replay"]["matches"] and data["replay"]["hash_chain_valid"]
    assert data["live_capture"] is False
    assert state["metrics"]["adk_offline_calls"] > 0
    assert state["metrics"]["adk_paid_calls"] == state["metrics"]["model_calls"] == 0
    assert state["metrics"]["delivered"] == 1
    assert set(data["agent_details"]) == {agent["agent_id"] for agent in state["agents"]}
    for order in state["orders"]:
        details = data["order_details"][order["id"]]
        assert details["order"]["id"] == order["id"]
        assert details["conversation"] and details["memory_history"]
        assert details["memory_history_complete"]
    assert data["agent_templates"]


def test_store_example_records_real_picking_breakdown_handoff_and_delivery():
    data = load_example("store")["data"]
    frames = data["frames"]
    assert [frame["time"] for frame in frames] == list(range(0, 1801, 10))
    assert all(frame["city"]["run"]["sim_time"] == frame["interior"]["sim_time"] == frame["time"]
               for frame in frames)
    orders = [next(order for store in frame["interior"]["stores"]
                   if store["store"] == data["store"] for order in store["orders"]
                   if order["order_id"] == data["order"]) for frame in frames]
    assert len({json.dumps(order["picked"], sort_keys=True) for order in orders}) > 1
    assert orders[-1]["lines"] == orders[-1]["picked"]
    assert orders[-1]["stage"] == "handed_off"
    assert orders[-1]["status"] == "delivered"
    assert orders[-1]["packed_sim"] <= orders[-1]["dock_sim"] <= orders[-1]["delivered_sim"]
    assert any(event["kind"] == "robot_breakdown"
               for event in frames[-1]["city"]["chaos"]["events"])
    assert any(not worker["available"] for frame in frames
               for store in frame["interior"]["stores"] for worker in store["workers"])
    assert data["definitions"][data["store"]]["layout"]["slots"]
    assert data["decisions"]


@pytest.mark.parametrize("kind", sorted(EXAMPLE_KINDS))
def test_recorded_examples_have_no_runtime_credentials(kind):
    forbidden = {"password", "private_key", "access_token", "refresh_token", "api_key", "dsn",
                 "credentials", "channel_token"}

    def check(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(key.lower() for key in value)
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(load_example(kind))


@pytest.fixture
def local_example(tmp_path):
    source = Path("web/data/examples")
    (tmp_path / "manifest.json").write_bytes((source / "manifest.json").read_bytes())
    (tmp_path / "inventory.json").write_bytes((source / "inventory.json").read_bytes())
    return tmp_path


def test_examples_reject_tampering_and_paths_outside_the_bundle(local_example):
    path = local_example / "inventory.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        load_example("inventory", local_example)
    manifest_path = local_example / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["examples"]["inventory"]["file"] = "../outside.json"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="filename"):
        load_example("inventory", local_example)
    with pytest.raises(ValueError, match="Unknown"):
        load_example("../inventory", local_example)


@pytest.mark.parametrize("change", [
    {"paid_model_calls": 1}, {"read_only": False}, {"synthetic": False}, {"kind": "restaurant"},
])
def test_rehashed_live_or_paid_examples_are_still_rejected(local_example, change):
    payload = copy.deepcopy(load_example("inventory", local_example))
    payload["recording"].update(change)
    raw = json.dumps(payload).encode()
    (local_example / "inventory.json").write_bytes(raw)
    manifest_path = local_example / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["examples"]["inventory"].update(bytes=len(raw),
                                               sha256=hashlib.sha256(raw).hexdigest())
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="read-only"):
        load_example("inventory", local_example)

"""Memory profiles constrain recall while typed evidence stays scoped and durable."""

import hashlib
import json
from copy import deepcopy
from dataclasses import FrozenInstanceError

import psycopg
import pytest
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from test_agent_runtime import Fleet, claim, request
from test_agent_runtime import fleet as fleet

from delivery.agent_specs import load_role
from delivery.db import connect
from delivery.memory_profiles import MemoryProfile, project_memory
from delivery.supply_models import AgentDefinition, SupplyConfig


def fact(**changes):
    return {
        "id": 17,
        "fact_id": 17,
        "key": "restaurant.order:meal-a",
        "owner_role": "restaurant",
        "context_type": "order",
        "context_id": "meal-a",
        "kind": "restaurant.order",
        "subject": "meal-a",
        "version": 2,
        "body": {"status": "cooking", "action": "restaurant_approved"},
        "observed_sim": 5,
        "expires_sim": 3605,
        "event_id": 101,
        "previous_id": 16,
        **changes,
    }


def test_profiles_are_frozen_bounded_and_do_not_change_authority() -> None:
    profile = MemoryProfile()
    assert profile.model_dump() == {
        "mode": "typed",
        "max_facts": 8,
        "max_bytes": 8192,
        "ttl_seconds": 3600,
    }
    with pytest.raises((ValidationError, FrozenInstanceError)):
        profile.mode = "none"
    role = load_role("inventory")
    changed = role.model_copy(update={"memory": profile})
    assert changed.tools == role.tools and changed.accepts == role.accepts
    assert changed.digest != role.digest


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "vector"},
        {"max_facts": 0},
        {"max_facts": 9},
        {"max_facts": True},
        {"max_facts": 1.0},
        {"max_bytes": 255},
        {"max_bytes": 8193},
        {"ttl_seconds": 59},
        {"ttl_seconds": 86401},
        {"ttl_seconds": "3600"},
        {"store": "another-agent"},
    ],
)
def test_invalid_profiles_fail_closed(changes: dict) -> None:
    with pytest.raises(ValidationError):
        MemoryProfile(**changes)


def test_legacy_role_hash_and_supply_dump_stay_identical_when_unconfigured() -> None:
    role = load_role("inventory")
    assert role.memory is None
    legacy = role.model_dump(mode="json")
    legacy.pop("brain")
    legacy.pop("memory")
    expected = hashlib.sha256(
        json.dumps(legacy, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert role.digest == expected
    default = SupplyConfig().model_dump(mode="json")
    assert all("memory" not in definition for definition in default["agents"].values())
    configured = AgentDefinition(
        display_name="Test", soul="Test", memory=MemoryProfile(mode="json")
    )
    assert configured.model_dump(mode="json")["memory"]["mode"] == "json"


def test_projection_formats_retain_sources_and_raw_facts() -> None:
    facts = [fact()]
    before = deepcopy(facts)
    assert project_memory(None, facts) is facts
    assert project_memory(MemoryProfile(mode="typed"), facts) is facts
    assert project_memory(MemoryProfile(mode="none"), facts) == []
    text = project_memory(MemoryProfile(mode="text"), facts)
    assert isinstance(text, str)
    assert "restaurant.order meal-a" in text and "event=101" in text and "version=2" in text
    assert "fact=17" in text and '"context_id":"meal-a"' in text
    structured = project_memory(MemoryProfile(mode="json"), facts)
    assert isinstance(structured, dict)
    assert structured["scope"]["context_id"] == "meal-a"
    assert structured["facts"][0]["body"] == facts[0]["body"]
    assert structured["facts"][0]["provenance"] == {
        "fact_id": 17,
        "version": 2,
        "event_id": 101,
        "observed_sim": 5,
        "expires_sim": 3605,
        "previous_id": 16,
    }
    assert facts == before


@pytest.mark.parametrize("mode", ["text", "json", "typed"])
def test_projection_caps_count_and_utf8_bytes_without_partial_facts(mode: str) -> None:
    facts = [fact(fact_id=number, event_id=number) for number in range(1, 9)]
    result = project_memory(MemoryProfile(mode=mode, max_facts=1), facts)
    if isinstance(result, list):
        assert len(result) == 1
    elif isinstance(result, dict):
        assert len(result["facts"]) == 1
    else:
        assert result.count("event=") == 1
    large = [fact(body={"status": "cooking", "reason": "á" * 240})]
    result = project_memory(MemoryProfile(mode=mode, max_bytes=256), large)
    serialized = (
        result
        if isinstance(result, str)
        else json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    assert len(serialized.encode("utf-8")) <= 256
    assert result in (
        [],
        "",
        {
            "scope": {"owner_role": "restaurant", "context_type": "order", "context_id": "meal-a"},
            "facts": [],
        },
    )
    assert large[0]["body"]["reason"] == "á" * 240


@pytest.mark.parametrize("mode", ["text", "json", "typed"])
@pytest.mark.parametrize(
    "changes",
    [
        {"owner_role": "household"},
        {"context_id": "meal-b"},
        {"context_type": "shipment"},
        {"run_id": "another-run"},
        {"store": "another-agent"},
    ],
)
def test_projection_rejects_combined_scopes(mode: str, changes: dict) -> None:
    with pytest.raises(ValueError, match="one canonical run, role and order"):
        project_memory(MemoryProfile(mode=mode), [fact(), fact(**changes)])


def set_profile(db_url: str, fleet: Fleet, profile: MemoryProfile) -> None:
    with connect(db_url) as conn:
        conn.execute(
            "UPDATE agent_bindings SET definition=jsonb_set(definition,'{memory}',%s) "
            "WHERE run_id=%s AND store='store-1'",
            (Jsonb(profile.model_dump(mode="json")), fleet.run),
        )


def record(conn, event, status="reserved", ttl=3600):
    return conn.execute(
        "SELECT agent_memory_record(%s,%s,%s,'inventory.reservation',%s,%s) data",
        (event.id, event.token, event.attempts, Jsonb({"status": status}), ttl),
    ).fetchone()["data"]


def recall(conn, event, limit=8):
    return conn.execute(
        "SELECT agent_memory_recall(%s,%s,%s,NULL,%s) data",
        (event.id, event.token, event.attempts, limit),
    ).fetchone()["data"]


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["none", "text", "json", "typed"])
def test_sql_modes_keep_typed_audit_and_scoped_array_receipts(
    db_url: str, fleet: Fleet, mode: str
) -> None:
    set_profile(db_url, fleet, MemoryProfile(mode=mode, ttl_seconds=60))
    request(db_url, fleet)
    request(db_url, fleet, basket="b")
    request(db_url, fleet, store="store-2", basket="a", key="peer-a")
    event, other = claim(fleet), claim(fleet)
    peer = claim(fleet, "store-2")
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event) and agent.reserve_budget(other)
    assert fleet.agents["store-2"].reserve_budget(peer)
    with connect(agent.dsn) as conn:
        written = record(conn, event)
        assert written["expires_sim"] == 60 and written["event_id"] == event.id
        seen = recall(conn, event)
        assert isinstance(seen, list)
        assert seen == ([] if mode == "none" else [written])
        assert recall(conn, other) == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            recall(conn, peer)
        for function, extra in (
            ("agent_memory_recall_typed", ""),
            ("agent_memory_record_typed", ",'inventory.reservation','{\"status\":\"reserved\"}'"),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(
                    f"SELECT {function}(%s,%s,%s{extra})",
                    (event.id, event.token, event.attempts),
                )
    with connect(fleet.agents["store-2"].dsn) as conn:
        assert recall(conn, peer) == []
    with connect(db_url) as conn:
        stored = conn.execute(
            "SELECT * FROM agent_memory_facts WHERE run_id=%s", (fleet.run,)
        ).fetchall()
        assert len(stored) == 1 and stored[0]["body"] == {"status": "reserved"}
        conn.execute("UPDATE runs SET sim_time=60 WHERE id=%s", (fleet.run,))
    with connect(agent.dsn) as conn:
        assert recall(conn, event) == []


@pytest.mark.integration
def test_sql_profile_caps_complete_fact_bytes_and_retains_revision_history(
    db_url: str, fleet: Fleet
) -> None:
    set_profile(db_url, fleet, MemoryProfile(mode="typed", max_facts=1, ttl_seconds=60))
    request(db_url, fleet)
    request(db_url, fleet, key="revision")
    first, second = claim(fleet), claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(first) and agent.reserve_budget(second)
    with connect(agent.dsn) as conn:
        initial = record(conn, first)
        changed = record(conn, second, status="rejected")
        assert changed["version"] == 2 and changed["previous_id"] == initial["fact_id"]
        assert recall(conn, second, limit=16) == [changed]
    set_profile(db_url, fleet, MemoryProfile(mode="typed", max_bytes=256, ttl_seconds=60))
    with connect(agent.dsn) as conn:
        assert recall(conn, second) == []
    with connect(db_url) as conn:
        history = conn.execute(
            "SELECT version,event_id FROM agent_memory_facts WHERE run_id=%s ORDER BY version",
            (fleet.run,),
        ).fetchall()
        assert history == [
            {"version": 1, "event_id": first.id},
            {"version": 2, "event_id": second.id},
        ]


@pytest.mark.integration
def test_sql_profile_validation_cannot_be_bypassed_at_binding_boundary(
    db_url: str, fleet: Fleet
) -> None:
    with connect(db_url) as conn:
        for profile in (
            [],
            {"mode": "text"},
            {**MemoryProfile().model_dump(), "mode": "vector"},
            {**MemoryProfile().model_dump(), "max_facts": 9},
            {**MemoryProfile().model_dump(), "max_bytes": True},
            {**MemoryProfile().model_dump(), "ttl_seconds": 86401},
        ):
            with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
                conn.execute(
                    "UPDATE agent_bindings SET definition=jsonb_set(definition,'{memory}',%s) "
                    "WHERE run_id=%s AND store='store-1'",
                    (Jsonb(profile), fleet.run),
                )

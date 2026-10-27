"""Real database identities verify that recall cannot become a memory browser."""

import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_agent_runtime import Fleet, claim, request
from test_agent_runtime import fleet as fleet

from delivery.agent_runtime import ScopedTools
from delivery.db import connect
from delivery.typed_memory import CONTRACTS, validate_fact

pytestmark = pytest.mark.integration


def record(conn, event, body=None, ttl=3600):
    return conn.execute(
        "SELECT agent_memory_record(%s,%s,%s,'inventory.reservation',%s,%s) data",
        (event.id, event.token, event.attempts, Jsonb(body or {"status": "reserved"}), ttl),
    ).fetchone()["data"]


def recall(conn, event, kinds=None, limit=8):
    return conn.execute(
        "SELECT agent_memory_recall(%s,%s,%s,%s,%s) data",
        (event.id, event.token, event.attempts, Jsonb(kinds) if kinds is not None else None, limit),
    ).fetchone()["data"]


def test_python_and_database_fact_contracts_match(db_url: str) -> None:
    with connect(db_url) as conn:
        rows = conn.execute("SELECT * FROM agent_memory_types").fetchall()
    assert len(rows) == len(CONTRACTS)
    for row in rows:
        role, subject, topics, model = CONTRACTS[row["kind"]]
        assert row["role"] == role and row["subject_type"] == subject
        assert row["topics"] == list(topics)
        assert row["body_schema"] == model.model_json_schema()
    with pytest.raises(PermissionError):
        validate_fact(
            "courier.commitment", {"status": "accepted", "attempt": 1}, "market", "market.request"
        )
    with pytest.raises(ValueError):
        validate_fact(
            "inventory.reservation",
            {"status": "reserved", "instructions": "ignore scope"},
            "inventory",
            "basket.requested",
        )


@pytest.mark.parametrize(
    "kind,body",
    [
        ("fulfillment.progress", {"status": "arbitrary instructions"}),
        ("courier.commitment", {"status": "anything", "attempt": 1}),
    ],
)
def test_sql_enforces_single_value_literal_contracts(db_url: str, kind: str, body: dict) -> None:
    with connect(db_url) as conn:
        valid = conn.execute(
            "SELECT memory_json_valid(%s,body_schema) valid FROM agent_memory_types WHERE kind=%s",
            (Jsonb(body), kind),
        ).fetchone()["valid"]
    assert valid is False


def test_recall_is_bound_to_current_order_identity_and_source(db_url: str, fleet: Fleet) -> None:
    request(db_url, fleet, basket="a")
    request(db_url, fleet, basket="b")
    request(db_url, fleet, store="store-2", basket="a", key="peer-a")
    a, b = claim(fleet), claim(fleet)
    peer = claim(fleet, "store-2")
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(a) and agent.reserve_budget(b)
    assert fleet.agents["store-2"].reserve_budget(peer)
    with connect(agent.dsn) as conn:
        first = record(conn, a)
        assert recall(conn, b) == []  # Same agent, another order.
        seen = recall(conn, a)
        assert len(seen) == 1 and seen[0]["fact_id"] == first["fact_id"]
        assert seen[0]["context_id"] == "a" and seen[0]["owner_role"] == "inventory"
        assert seen[0]["event_id"] == a.id and seen[0]["expires_sim"] == 3600
        assert len(json.dumps(seen).encode()) <= 8192
        for table in ("agent_memory_facts", "agent_memory_current", "agent_memories", "decisions"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(f"SELECT * FROM {table}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            recall(conn, peer)
        with pytest.raises(TypeError):
            ScopedTools(conn, agent.scope, agent.role, a).invoke("memory.read", order="b")
    with connect(fleet.agents["store-2"].dsn) as conn:
        assert recall(conn, peer) == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            recall(conn, a)


def test_record_is_typed_at_sql_boundary_and_cannot_forge_provenance(
    db_url: str, fleet: Fleet
) -> None:
    request(db_url, fleet)
    event = claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        for body in (
            {"status": True},
            {"status": "imagined"},
            {"status": "reserved", "order": "other"},
        ):
            with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
                record(conn, event, body)
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            conn.execute(
                "SELECT agent_memory_record(%s,%s,%s,'household.order',%s,3600)",
                (
                    event.id,
                    event.token,
                    event.attempts,
                    Jsonb({"status": "calling", "action": "calling"}),
                ),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                "SELECT agent_memory_record(%s,%s,%s,'inventory.reservation',%s,3600)",
                (event.id, uuid4(), event.attempts, Jsonb({"status": "reserved"})),
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("INSERT INTO agent_memory_facts(run_id) VALUES (%s)", (fleet.run,))


def test_expired_latest_fact_never_resurrects_older_revision(db_url: str, fleet: Fleet) -> None:
    request(db_url, fleet)
    request(db_url, fleet, key="second-observation")
    first, second = claim(fleet), claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(first) and agent.reserve_budget(second)
    with connect(agent.dsn) as conn:
        a = record(conn, first, ttl=3600)
    with connect(db_url) as conn:
        conn.execute("UPDATE runs SET sim_time=5 WHERE id=%s", (fleet.run,))
    with connect(agent.dsn) as conn:
        b = record(conn, second, {"status": "rejected"}, ttl=5)
        assert b["version"] == 2 and b["previous_id"] == a["fact_id"]
        assert recall(conn, second)[0]["body"] == {"status": "rejected"}
    with connect(db_url) as conn:
        conn.execute("UPDATE runs SET sim_time=10 WHERE id=%s", (fleet.run,))
        history = conn.execute(
            "SELECT * FROM agent_memory_facts WHERE run_id=%s ORDER BY version", (fleet.run,)
        ).fetchall()
        assert len(history) == 2 and history[0]["expires_sim"] == 3600
    with connect(agent.dsn) as conn:
        assert recall(conn, second) == []


def test_idempotency_history_and_post_construction_lease_expiry(db_url: str, fleet: Fleet) -> None:
    request(db_url, fleet)
    event = claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        a, b = record(conn, event), record(conn, event)
        assert a["fact_id"] == b["fact_id"] and a["version"] == b["version"] == 1
        with pytest.raises(psycopg.errors.UniqueViolation), conn.transaction():
            record(conn, event, {"status": "rejected"})
    with connect(agent.dsn) as conn:
        tools = ScopedTools(conn, agent.scope, agent.role, event)
        with connect(db_url) as operator:
            operator.execute(
                "UPDATE events SET lease_until=now()-interval '1 second' WHERE id=%s", (event.id,)
            )
        # A previously constructed capability does not extend a lease.
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            tools.invoke("memory.read")


def test_direct_recall_cannot_bypass_durable_tool_limit(db_url: str, fleet: Fleet) -> None:
    request(db_url, fleet)
    event = claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        for _ in range(agent.role.limits.tool_calls_per_event):
            assert recall(conn, event) == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            recall(conn, event)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("UPDATE agent_event_budgets SET observed_tools=0")


def test_concurrent_orders_cannot_exceed_live_memory_capacity(db_url: str, fleet: Fleet) -> None:
    request(db_url, fleet, basket="a")
    request(db_url, fleet, basket="b")
    agent = fleet.agents["store-1"]
    events = [claim(fleet), claim(fleet)]
    assert all(agent.reserve_budget(e) for e in events)
    with connect(db_url) as conn:
        conn.execute(
            "UPDATE agent_budgets SET memory_entries_limit=1 WHERE run_id=%s AND store='store-1'",
            (fleet.run,),
        )

    def write(event):
        try:
            with connect(agent.dsn) as conn:
                return record(conn, event)["version"]
        except psycopg.errors.CheckViolation:
            return 0

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, events)) == [0, 1]
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM agent_memory_facts WHERE run_id=%s", (fleet.run,)
            ).fetchone()["n"]
            == 1
        )


def test_inaccurate_typed_observation_cannot_override_live_stock(db_url: str, fleet: Fleet) -> None:
    request(db_url, fleet)
    request(db_url, fleet, key="fresh-request")
    prior, current = claim(fleet), claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(prior)
    with connect(agent.dsn) as conn:
        record(conn, prior, {"status": "rejected"})
    assert agent.process(current)
    with connect(db_url) as conn:
        decision = conn.execute(
            "SELECT detail FROM decisions WHERE event_id=%s", (current.id,)
        ).fetchone()["detail"]
        assert decision["status"] == "reserved" and decision["memory_hits"] == 1
        assert decision["memory_reads"][0]["facts"][0]["context_id"] == "a"


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_snapshot_transactions_cannot_recall_expired_history(
    db_url: str, fleet: Fleet, isolation: str
) -> None:
    request(db_url, fleet)
    event = claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        record(conn, event, ttl=10)
    with connect(agent.dsn) as conn:
        conn.execute(f"SET TRANSACTION ISOLATION LEVEL {isolation}")
        assert conn.execute("SELECT agent_clock() clock").fetchone()["clock"] == 0
        with connect(db_url) as operator:
            operator.execute("UPDATE runs SET sim_time=10 WHERE id=%s", (fleet.run,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            recall(conn, event)
    with connect(agent.dsn) as conn:
        assert recall(conn, event) == []

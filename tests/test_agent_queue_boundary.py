"""Direct agent SQL must preserve queue leases and durable tool admission."""

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from delivery.agent_access import inventory_access, retire_inventory_access
from delivery.agent_runtime import LocalAgent, create_inventory_agent
from delivery.db import Connection, connect
from delivery.lab import create_lab
from delivery.queue import Backpressure, Event, Queue, publish

pytestmark = pytest.mark.integration


@dataclass
class AgentQueue:
    run: str
    agent: LocalAgent
    sku: str


@pytest.fixture
def agent_queue(db_url: str) -> Iterator[AgentQueue]:
    run = create_lab(db_url)
    access = inventory_access(run, db_url)
    with connect(db_url) as conn:
        product = conn.execute(
            "SELECT selected_product FROM lab_worlds WHERE run_id=%s", (run,)
        ).fetchone()
        assert product
    yield AgentQueue(
        run, create_inventory_agent(access["store-1"].dsn), product["selected_product"]
    )
    retire_inventory_access(run, db_url)
    with connect(db_url) as conn:
        conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
        conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def incoming(
    db_url: str, queue: AgentQueue, basket: str = "current", priority: int = 0, due: int = 0
) -> int:
    with connect(db_url) as conn:
        return publish(
            conn,
            run_id=queue.run,
            producer="lab_scenario",
            topic="basket.requested",
            payload={
                "basket": basket,
                "store": "store-1",
                "sku": queue.sku,
                "quantity": 1,
                "expires_sim": 600,
            },
            key=basket,
            trace_id=basket,
            priority=priority,
            due_sim=due,
            target_store="store-1",
        )


def leased(db_url: str, queue: AgentQueue) -> Event:
    incoming(db_url, queue)
    event = queue.agent.claim()
    assert event and queue.agent.reserve_budget(event)
    return event


def test_executor_grants_cannot_bypass_queue_or_read_decision_history(db_url: str) -> None:
    roles = (
        "lab_inventory_executor",
        "lab_fulfillment_executor",
        "lab_dispatch_executor",
        "lab_courier_executor",
        "lab_judge_executor",
        "lab_supply_executor",
    )
    with connect(db_url) as conn:
        for role in roles:
            rights = conn.execute(
                "SELECT has_table_privilege(%s,'events','INSERT') AS inserts,"
                "has_any_column_privilege(%s,'events','UPDATE') AS updates,"
                "has_column_privilege(%s,'agent_event_budgets',"
                "'observed_tools','UPDATE') AS resets,"
                "has_table_privilege(%s,'decisions','SELECT') AS history",
                (role, role, role, role),
            ).fetchone()
            assert rights == {"inserts": False, "updates": False, "resets": False, "history": False}


def test_direct_agent_event_and_budget_mutations_are_denied(
    db_url: str, agent_queue: AgentQueue
) -> None:
    event = leased(db_url, agent_queue)
    with connect(agent_queue.agent.dsn) as conn:
        for statement, params in (
            ("UPDATE events SET lease_until=now()+interval '1 day' WHERE id=%s", (event.id,)),
            ("UPDATE agent_event_budgets SET observed_tools=0 WHERE event_id=%s", (event.id,)),
            ("SELECT detail FROM decisions", ()),
            (
                "INSERT INTO events(run_id,producer,topic,payload,dedupe_key,"
                "trace_id,target_store) "
                "VALUES (%s,'inventory','shipment.received','{}','forged','forged','store-1')",
                (agent_queue.run,),
            ),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(statement, params)


def test_claim_uses_frozen_role_and_server_clock_and_priority(
    db_url: str, agent_queue: AgentQueue
) -> None:
    incoming(db_url, agent_queue, "low", priority=1)
    high = incoming(db_url, agent_queue, "high", priority=10)
    incoming(db_url, agent_queue, "future", priority=100, due=600)
    agent = agent_queue.agent
    with connect(agent.dsn) as conn:
        for role, run, topics, seconds in (
            ("dispatcher", agent_queue.run, ["basket.requested"], 45),
            ("inventory", str(uuid4()), ["basket.requested"], 45),
            ("inventory", agent_queue.run, ["delivery.failed"], 45),
            ("inventory", agent_queue.run, ["basket.requested"], 301),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(
                    "SELECT agent_queue_claim(%s,%s,%s,%s)", (role, run, topics, seconds)
                )
    claimed = Queue(agent.dsn).claim("inventory", agent_queue.run, 999999)
    assert claimed and claimed.id == high
    second = agent.claim()
    assert second and second.payload["basket"] == "low"
    assert agent.claim() is None


def test_tool_charges_cannot_reset_or_skip_lease_attempt(
    db_url: str, agent_queue: AgentQueue
) -> None:
    event = leased(db_url, agent_queue)
    with connect(agent_queue.agent.dsn) as conn:
        for token, attempt, name in (
            (uuid4(), event.attempts, "memory.read"),
            (event.token, event.attempts + 1, "memory.read"),
            (event.token, event.attempts, "sql.query"),
        ):
            assert conn.execute(
                "SELECT agent_consume_tool(%s,%s,%s,%s) AS charged",
                (event.id, token, attempt, name),
            ).fetchone() == {"charged": False}
        slots = conn.execute(
            "SELECT slots FROM agent_event_budgets WHERE event_id=%s", (event.id,)
        ).fetchone()
        assert slots
        for _ in range(slots["slots"]):
            assert conn.execute(
                "SELECT agent_consume_tool(%s,%s,%s,'inventory.read') AS charged",
                (event.id, event.token, event.attempts),
            ).fetchone() == {"charged": True}
    with connect(agent_queue.agent.dsn) as conn:
        assert conn.execute(
            "SELECT agent_consume_tool(%s,%s,%s,'inventory.read') AS charged",
            (event.id, event.token, event.attempts),
        ).fetchone() == {"charged": False}


def test_expired_lease_denies_ack_fail_publish_and_reclaims_with_new_token(
    db_url: str, agent_queue: AgentQueue
) -> None:
    event = leased(db_url, agent_queue)
    with connect(db_url) as conn:
        conn.execute(
            "UPDATE events SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
            (event.id,),
        )
    with connect(agent_queue.agent.dsn) as conn:
        for function in ("agent_queue_lock", "agent_queue_ack"):
            assert conn.execute(
                f"SELECT {function}(%s,%s,%s) AS allowed",
                (event.id, event.token, event.attempts),
            ).fetchone() == {"allowed": False}
        assert conn.execute(
            "SELECT agent_queue_fail(%s,%s,%s,'WorkerError') AS allowed",
            (event.id, event.token, event.attempts),
        ).fetchone() == {"allowed": False}
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                "SELECT agent_queue_publish(%s,%s,%s,'inventory.decided','{}','stale',0,0,10000)",
                (event.id, event.token, event.attempts),
            )
    renewed = agent_queue.agent.claim()
    assert renewed and renewed.id == event.id and renewed.token != event.token
    assert renewed.attempts == event.attempts + 1
    assert not Queue(agent_queue.agent.dsn).process(
        event, lambda c, e: pytest.fail("stale handler")
    )


def test_deadline_is_rechecked_after_waiting_for_event_lock(
    db_url: str, agent_queue: AgentQueue
) -> None:
    event = leased(db_url, agent_queue)

    def check() -> bool:
        with connect(agent_queue.agent.dsn) as conn:
            row = conn.execute(
                "SELECT agent_queue_lock(%s,%s,%s) AS allowed",
                (event.id, event.token, event.attempts),
            ).fetchone()
            assert row
            return bool(row["allowed"])

    with ThreadPoolExecutor(max_workers=1) as pool:
        with connect(db_url) as conn:
            conn.execute(
                "UPDATE events SET lease_until=clock_timestamp()+interval '100 milliseconds' "
                "WHERE id=%s",
                (event.id,),
            )
            result = pool.submit(check)
            time.sleep(0.25)
        assert not result.result(timeout=5)


def test_agent_publish_preserves_source_dedupe_capacity_and_budget(
    db_url: str, agent_queue: AgentQueue
) -> None:
    event = leased(db_url, agent_queue)
    with connect(agent_queue.agent.dsn) as conn:
        arguments = {
            "run_id": agent_queue.run,
            "producer": "inventory",
            "topic": "inventory.decided",
            "payload": {"basket": "current"},
            "key": "decision",
            "trace_id": "forged-trace",
            "parent_id": event.id,
            "lease_token": event.token,
            "event_attempt": event.attempts,
        }
        with pytest.raises(Backpressure), conn.transaction():
            publish(conn, **arguments, capacity=1)
        first = publish(conn, **arguments, capacity=2)
        assert publish(conn, **arguments, capacity=2) == first
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                "SELECT agent_queue_publish(%s,%s,%s,'inventory.decided',%s,'other',0,0,10000)",
                (event.id, event.token, event.attempts, Jsonb({"basket": "other-order"})),
            )
    with connect(db_url) as conn:
        assert conn.execute(
            "SELECT run_id::text,producer,trace_id,parent_id,target_store FROM events WHERE id=%s",
            (first,),
        ).fetchone() == {
            "run_id": agent_queue.run,
            "producer": "inventory",
            "trace_id": event.trace_id,
            "parent_id": event.id,
            "target_store": "store-1",
        }
        assert conn.execute(
            "SELECT observed_tools FROM agent_event_budgets WHERE event_id=%s", (event.id,)
        ).fetchone() == {"observed_tools": 2}


def test_agent_publish_dedupe_cannot_return_another_store_event(
    db_url: str, agent_queue: AgentQueue
) -> None:
    event = leased(db_url, agent_queue)
    with connect(db_url) as conn:
        publish(
            conn,
            run_id=agent_queue.run,
            producer="inventory",
            topic="inventory.decided",
            payload={},
            key="foreign-dedupe",
            trace_id="foreign",
            target_store="store-2",
        )
    with connect(agent_queue.agent.dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "SELECT agent_queue_publish(%s,%s,%s,'inventory.decided',"
                "'{}','foreign-dedupe',0,0,10000)",
                (event.id, event.token, event.attempts),
            )


def test_concurrent_agent_claim_and_tool_admission_are_serialized(
    db_url: str, agent_queue: AgentQueue
) -> None:
    incoming(db_url, agent_queue)
    with ThreadPoolExecutor(max_workers=4) as pool:
        candidates = list(pool.map(lambda _: agent_queue.agent.claim(), range(4)))
    claims = [event for event in candidates if event]
    assert len(claims) == 1
    event = claims[0]
    assert agent_queue.agent.reserve_budget(event)
    with connect(db_url) as conn:
        conn.execute("UPDATE agent_event_budgets SET slots=1 WHERE event_id=%s", (event.id,))

    def consume(_: int) -> bool:
        with connect(agent_queue.agent.dsn) as conn:
            row = conn.execute(
                "SELECT agent_consume_tool(%s,%s,%s,'inventory.read') AS charged",
                (event.id, event.token, event.attempts),
            ).fetchone()
            assert row
            return bool(row["charged"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(consume, range(4))) == [False, False, False, True]


def test_agent_process_uses_authoritative_payload(
    db_url: str, agent_queue: AgentQueue
) -> None:
    event = leased(db_url, agent_queue)
    observed: list[Event] = []
    forged = replace(event, payload={"basket": "other-order"}, trace_id="forged")
    assert Queue(agent_queue.agent.dsn).process(forged, lambda c, e: observed.append(e))
    assert observed == [event]


def test_agent_ack_rejection_rolls_back_handler_charges(
    db_url: str, agent_queue: AgentQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = leased(db_url, agent_queue)
    handled: list[int] = []

    def handler(conn: Connection, current: Event) -> None:
        assert conn.execute(
            "SELECT agent_consume_tool(%s,%s,%s,'inventory.read') AS charged",
            (current.id, current.token, current.attempts),
        ).fetchone() == {"charged": True}
        assert conn.execute(
            "SELECT observed_tools FROM agent_event_budgets WHERE event_id=%s", (current.id,)
        ).fetchone() == {"observed_tools": 1}
        handled.append(current.id)
        execute = conn.execute

        def reject_ack(statement, *args, **kwargs):
            if isinstance(statement, str) and "public.agent_queue_ack(" in statement:
                return execute("SELECT false AS acked")
            return execute(statement, *args, **kwargs)

        # SQL expiry denial is covered above with an authoritative past deadline.
        # Inject its false result here to isolate rollback from wall-clock timing.
        monkeypatch.setattr(conn, "execute", reject_ack)

    assert not Queue(agent_queue.agent.dsn).process(event, handler)
    assert handled == [event.id]
    with connect(db_url) as conn:
        assert conn.execute(
            "SELECT state FROM events WHERE id=%s", (event.id,)
        ).fetchone() == {"state": "leased"}
        assert conn.execute(
            "SELECT observed_tools FROM agent_event_budgets WHERE event_id=%s", (event.id,)
        ).fetchone() == {"observed_tools": 0}


def test_agent_retry_dlq_and_operator_replay_remain_fenced(
    db_url: str, agent_queue: AgentQueue
) -> None:
    event_id = incoming(db_url, agent_queue)
    queue = Queue(agent_queue.agent.dsn)

    def broken(conn: Connection, event: Event) -> None:
        assert conn.execute(
            "SELECT agent_consume_tool(%s,%s,%s,'inventory.read') AS charged",
            (event.id, event.token, event.attempts),
        ).fetchone() == {"charged": True}
        raise ValueError("Only the exception type belongs in queue failure evidence")

    for attempt in range(3):
        event = agent_queue.agent.claim()
        assert event and event.attempts == attempt + 1
        assert agent_queue.agent.reserve_budget(event)
        assert not queue.process(event, broken)
        assert agent_queue.agent.claim() is None
        with connect(db_url) as conn:
            state = conn.execute(
                "SELECT state,error FROM events WHERE id=%s", (event_id,)
            ).fetchone()
            assert state == {"state": "dead" if attempt == 2 else "ready", "error": "ValueError"}
            conn.execute("UPDATE events SET available_at=now() WHERE id=%s", (event_id,))
            assert conn.execute(
                "SELECT observed_tools FROM agent_event_budgets WHERE event_id=%s AND attempt=%s",
                (event_id, event.attempts),
            ).fetchone() == {"observed_tools": 0}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        queue.replay(event_id)
    assert Queue(db_url).replay(event_id)
    replayed = agent_queue.agent.claim()
    assert replayed and replayed.attempts == 4
    assert not queue.process(event, lambda c, e: pytest.fail("pre-replay handler"))
    assert queue.process(replayed, lambda c, e: None)

import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest

from delivery.db import Connection, connect
from delivery.queue import Backpressure, Event, Queue, publish

pytestmark = pytest.mark.integration


def test_fresh_events_are_ready_without_wall_clock_gating(db_url: str, run_id: UUID) -> None:
    event_id = send(db_url, run_id)
    with connect(db_url) as conn:
        row = conn.execute("SELECT available_at FROM events WHERE id=%s", (event_id,)).fetchone()
        assert row and row["available_at"].year == 1970
    event = Queue(db_url).claim("dispatcher", run_id, 0)
    assert event and event.id == event_id


def test_lease_cannot_survive_waiting_for_run_lock(db_url: str, run_id: UUID) -> None:
    send(db_url, run_id)
    queue = Queue(db_url, lease_seconds=0.1)
    event = queue.claim("dispatcher", run_id, 0)
    assert event
    called = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        with connect(db_url) as conn:
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(run_id),))
            task = pool.submit(queue.process, event, lambda c, e: called.append(e.id))
            time.sleep(0.25)
            assert not task.done()
            # Docker's clock can pause relative to the host under load. Expire using
            # the database clock while the worker is still fenced by the run lock.
            conn.execute(
                "UPDATE events SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
                (event.id,),
            )
        assert not task.result()
    assert called == []


def send(url: str, run: UUID, key: str = "o1", priority: int = 0, capacity: int = 100) -> int:
    with connect(url) as conn:
        return publish(
            conn,
            run_id=run,
            producer="generator",
            topic="order.created",
            payload={"order_id": key},
            key=key,
            trace_id=key,
            priority=priority,
            capacity=capacity,
        )


def test_concurrent_dedupe_and_claim(db_url: str, run_id: UUID) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: send(db_url, run_id), range(16)))
    assert len(set(ids)) == 1
    q = Queue(db_url)
    with ThreadPoolExecutor(max_workers=8) as pool:
        events = list(pool.map(lambda _: q.claim("dispatcher", run_id, 0), range(8)))
    assert len([e for e in events if e]) == 1


def test_retry_rollback_dlq_and_replay(db_url: str, run_id: UUID) -> None:
    event_id = send(db_url, run_id)
    q = Queue(db_url)

    def broken(conn: Connection, event: Event) -> None:
        conn.execute("UPDATE runs SET sim_time=999 WHERE id=%s", (run_id,))
        raise ValueError("secret-looking text must never be stored")

    for attempt in range(3):
        event = q.claim("dispatcher", run_id, 0)
        assert event and event.attempts == attempt + 1
        assert not q.process(event, broken)
        if attempt < 2:
            assert q.claim("dispatcher", run_id, 0) is None  # backoff is real
        with connect(db_url) as conn:
            conn.execute("UPDATE events SET available_at=now() WHERE id=%s", (event_id,))
    with connect(db_url) as conn:
        assert conn.execute("SELECT sim_time FROM runs WHERE id=%s", (run_id,)).fetchone() == {
            "sim_time": 0
        }
        row = conn.execute("SELECT error FROM dead_letters WHERE id=%s", (event_id,)).fetchone()
        assert row == {"error": "ValueError"}
    assert q.replay(event_id)
    event = q.claim("dispatcher", run_id, 0)
    assert event and q.process(event, lambda conn, e: None)
    assert not q.process(event, lambda conn, e: pytest.fail("duplicate handler"))


def test_fencing_priority_capacity_and_permissions(db_url: str, run_id: UUID) -> None:
    send(db_url, run_id, "low", priority=1, capacity=2)
    send(db_url, run_id, "high", priority=10, capacity=2)
    send(db_url, run_id, "low", capacity=2)  # dedupe does not consume capacity
    with pytest.raises(Backpressure):
        send(db_url, run_id, "overflow", capacity=2)
    with connect(db_url) as conn, pytest.raises(PermissionError):
        publish(
            conn,
            run_id=run_id,
            producer="courier",
            topic="order.created",
            payload={},
            key="bad",
            trace_id="bad",
        )
    q = Queue(db_url)
    old = q.claim("dispatcher", run_id, 0)
    assert old and old.payload["order_id"] == "high"
    with connect(db_url) as conn:
        conn.execute(
            "UPDATE events SET lease_until=now()-interval '1 second' WHERE id=%s", (old.id,)
        )
    new = q.claim("dispatcher", run_id, 0)
    assert new and new.id == old.id and new.token != old.token
    assert not q.process(old, lambda c, e: pytest.fail("stale handler"))
    assert q.process(new, lambda c, e: None)


def test_crashing_workers_eventually_dead_letter(db_url: str, run_id: UUID) -> None:
    event_id = send(db_url, run_id)
    q = Queue(db_url)
    for _ in range(3):
        assert q.claim("dispatcher", run_id, 0)
        with connect(db_url) as conn:
            conn.execute(
                "UPDATE events SET lease_until=now()-interval '1 second' WHERE id=%s", (event_id,)
            )
    assert q.claim("dispatcher", run_id, 0) is None
    with connect(db_url) as conn:
        assert conn.execute("SELECT id FROM dead_letters WHERE id=%s", (event_id,)).fetchone()

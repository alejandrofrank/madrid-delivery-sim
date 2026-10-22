"""Durable at-least-once delivery with transactionally exactly-once DB effects.

Lease fencing stops stale workers. The handler, outbox events, and ACK share a
transaction. External calls must be bounded and cannot have exactly-once effects.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from delivery.db import Connection, connect

PUBLISH: dict[str, set[str]] = {
    "generator": {"order.created", "complaint.created"},
    "dispatcher": {"courier.assigned"},
    "courier": {"order.delivered", "courier.available"},
    "customer_service": {"complaint.resolved", "approval.requested"},
}
SUBSCRIBE: dict[str, set[str]] = {
    "dispatcher": {"order.created", "courier.available"},
    "courier": {"courier.assigned"},
    "customer_service": {"complaint.created"},
    "audit": {"order.delivered", "complaint.resolved", "approval.requested"},
}


class Backpressure(RuntimeError):
    pass


class StaleLease(RuntimeError):
    pass


@dataclass(frozen=True)
class Event:
    id: int
    run_id: UUID
    topic: str
    payload: dict[str, Any]
    trace_id: str
    token: UUID
    attempts: int
    due_sim: int


def publish(
    conn: Connection, *, run_id: UUID | str, producer: str, topic: str,
    payload: dict[str, Any], key: str, trace_id: str, due_sim: int = 0,
    priority: int = 0, parent_id: int | None = None, capacity: int = 10000,
) -> int:
    if topic not in PUBLISH.get(producer, set()):
        raise PermissionError(f"{producer} cannot publish {topic}")
    # Serializes capacity and dedupe checks for this run without a global queue lock.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(run_id),))
    existing = conn.execute(
        "SELECT id FROM events WHERE run_id=%s AND topic=%s AND dedupe_key=%s",
        (run_id, topic, key),
    ).fetchone()
    if existing:
        return int(existing["id"])
    count = conn.execute(
        "SELECT count(*) AS n FROM events WHERE run_id=%s AND state IN ('ready','leased')",
        (run_id,),
    ).fetchone()
    if count and count["n"] >= capacity:
        raise Backpressure("Queue capacity reached; retry producer after consumers drain")
    row = conn.execute(
        """INSERT INTO events(run_id,producer,topic,payload,dedupe_key,trace_id,
           due_sim,priority,parent_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (run_id, producer, topic, Jsonb(payload), key, trace_id, due_sim, priority, parent_id),
    ).fetchone()
    assert row
    return int(row["id"])


class Queue:
    def __init__(self, url: str | None = None, lease_seconds: float = 45) -> None:
        self.url = url
        self.lease_seconds = lease_seconds

    def claim(self, role: str, run_id: UUID | str, sim_time: int) -> Event | None:
        if role not in SUBSCRIBE:
            raise PermissionError(f"Unknown consumer role: {role}")
        token = uuid4()
        with connect(self.url) as conn:
            conn.execute(
                """UPDATE events SET state='dead', error='lease_expired_after_max_attempts',
                   lease_token=NULL, lease_until=NULL WHERE run_id=%s AND state='leased'
                   AND lease_until < now() AND attempts >= max_attempts""", (run_id,),
            )
            row = conn.execute(
                """WITH candidate AS (
                     SELECT id FROM events WHERE run_id=%s AND topic=ANY(%s)
                     AND due_sim<=%s AND available_at<=now() AND attempts<max_attempts
                     AND (state='ready' OR (state='leased' AND lease_until<now()))
                     ORDER BY priority DESC, due_sim, id FOR UPDATE SKIP LOCKED LIMIT 1
                   ) UPDATE events e SET state='leased', lease_token=%s,
                     lease_until=now() + %s * interval '1 second', attempts=attempts+1
                   FROM candidate c WHERE e.id=c.id RETURNING e.*""",
                (run_id, sorted(SUBSCRIBE[role]), sim_time, token, self.lease_seconds),
            ).fetchone()
        if row is None:
            return None
        return Event(row["id"], row["run_id"], row["topic"], row["payload"],
                     row["trace_id"], token, row["attempts"], row["due_sim"])

    def process(self, event: Event, handler: Callable[[Connection, Event], None]) -> bool:
        try:
            with connect(self.url) as conn:
                # Shared lock ordering for all writers avoids run/queue deadlocks.
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(event.run_id),)
                )
                row = conn.execute(
                    """SELECT id FROM events WHERE id=%s AND state='leased'
                       AND lease_token=%s AND lease_until>now() FOR UPDATE""",
                    (event.id, event.token),
                ).fetchone()
                if not row:
                    raise StaleLease("Worker no longer owns event")
                handler(conn, event)
                conn.execute(
                    """UPDATE events SET state='done', completed_at=now(),
                       lease_token=NULL, lease_until=NULL WHERE id=%s""", (event.id,),
                )
            return True
        except StaleLease:
            return False
        except Exception as exc:
            # Do not persist exception strings: provider errors may contain credentials.
            self.fail(event, type(exc).__name__)
            return False

    def fail(self, event: Event, code: str) -> None:
        with connect(self.url) as conn:
            conn.execute(
                """UPDATE events SET state=CASE WHEN attempts>=max_attempts THEN 'dead'
                     ELSE 'ready' END, error=%s, lease_token=NULL, lease_until=NULL,
                     available_at=now() + %s * interval '1 second'
                   WHERE id=%s AND state='leased' AND lease_token=%s""",
                (code[:80], min(30, 2 ** (event.attempts - 1)), event.id, event.token),
            )

    def replay(self, event_id: int) -> bool:
        """Explicit operator action; no automatic poison-message loop."""
        with connect(self.url) as conn:
            row = conn.execute(
                """UPDATE events SET state='ready', attempts=0, error=NULL,
                   available_at=now() WHERE id=%s AND state='dead' RETURNING id""", (event_id,),
            ).fetchone()
        return row is not None

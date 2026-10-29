"""Durable at-least-once delivery with transactionally exactly-once DB effects.

Lease fencing stops stale workers. The handler, outbox events, and ACK share a
transaction. External calls must be bounded and cannot have exactly-once effects.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from psycopg.errors import ProgramLimitExceeded
from psycopg.types.json import Jsonb

from delivery.agent_specs import SUPPLY_ACCEPTS, SUPPLY_EMITS
from delivery.db import Connection, connect
from delivery.telemetry import active, current_traceparent, order_span, traced_event

PUBLISH: dict[str, set[str]] = {
    "lab_scenario": {"basket.requested", "shipment.delayed", "reservation.expire"},
    "inventory": {"inventory.decided", "shipment.received", "basket.reserved"},
    "generator": {"order.created", "complaint.created"},
    "dispatcher": {
        "courier.assigned",
        "courier.reposition",
        "delivery.assigned",
        "delivery.completed",
        "courier.briefed",
        "recovery.requested",
        "dispatch.retry",
        "dispatch.noted",
    },
    "fulfillment": {"basket.ready"},
    "lab_world": {"delivery.arrived", "delivery.failed"},
    "judge": {"recovery.reviewed"},
    "courier": {"order.delivered", "courier.available", "courier.accepted"},
    "customer_service": {"complaint.resolved", "approval.requested"},
}
SUBSCRIBE: dict[str, set[str]] = {
    "inventory": {
        "basket.requested",
        "shipment.delayed",
        "shipment.received",
        "reservation.expire",
    },
    "inventory_audit": {"inventory.decided"},
    "dispatcher": {
        "order.created",
        "courier.available",
        "basket.ready",
        "delivery.arrived",
        "dispatch.retry",
        "recovery.reviewed",
        "courier.accepted",
    },
    "fulfillment": {"basket.reserved"},
    "delivery_audit": {
        "delivery.assigned",
        "delivery.completed",
        "dispatch.noted",
        "recovery.requested",
    },
    "judge": {"delivery.failed"},
    "courier": {"courier.assigned", "courier.briefed", "courier.reposition"},
    "customer_service": {"complaint.created"},
    "audit": {"order.delivered", "complaint.resolved", "approval.requested"},
}


PUBLISH.update({role: set(topics) for role, topics in SUPPLY_EMITS.items()})
PUBLISH["supply_ingress"] = {"household.intent"}
SUBSCRIBE.update({role: set(topics) for role, topics in SUPPLY_ACCEPTS.items()})


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
    target_store: str | None = None
    traceparent: str | None = None
    consumer: str | None = None

    @property
    def otel_traceparent(self) -> str | None:
        """Compatibility for the Google-stack trace inspection surface."""
        return self.traceparent


def persist_trace_context(conn: Connection, event: Event) -> None:
    """Metadata only; the database enforces the same lease and identity boundary."""
    parent = current_traceparent()
    if parent is None:
        return
    scope = conn.execute("SELECT public.agent_scope() AS scope").fetchone()
    if scope and scope["scope"]:
        conn.execute(
            "SELECT public.agent_trace_context(%s,%s,%s,%s)",
            (event.id, event.token, event.attempts, parent),
        )
    else:
        conn.execute(
            "UPDATE events SET traceparent=%s WHERE id=%s AND run_id=%s AND state='leased' "
            "AND lease_token=%s AND attempts=%s AND lease_until>clock_timestamp()",
            (parent, event.id, event.run_id, event.token, event.attempts),
        )


def publish(
    conn: Connection,
    *,
    run_id: UUID | str,
    producer: str,
    topic: str,
    payload: dict[str, Any],
    key: str,
    trace_id: str,
    due_sim: int = 0,
    priority: int = 0,
    parent_id: int | None = None,
    capacity: int = 10000,
    target_store: str | None = None,
    lease_token: UUID | None = None,
    event_attempt: int | None = None,
) -> int:
    parent_context = None
    if active() and parent_id is not None:
        parent = conn.execute(
            "SELECT traceparent FROM events WHERE id=%s AND run_id=%s AND trace_id=%s",
            (parent_id, run_id, trace_id),
        ).fetchone()
        parent_context = parent["traceparent"] if parent else None
    with order_span(
        "queue.publish",
        run_id=run_id,
        order_id=trace_id,
        traceparent=parent_context,
        attributes={"delivery.agent": producer, "delivery.topic": topic},
    ):
        return _publish(
            conn,
            run_id=run_id,
            producer=producer,
            topic=topic,
            payload=payload,
            key=key,
            trace_id=trace_id,
            due_sim=due_sim,
            priority=priority,
            parent_id=parent_id,
            capacity=capacity,
            target_store=target_store,
            lease_token=lease_token,
            event_attempt=event_attempt,
        )


def _publish(
    conn: Connection,
    *,
    run_id: UUID | str,
    producer: str,
    topic: str,
    payload: dict[str, Any],
    key: str,
    trace_id: str,
    due_sim: int,
    priority: int,
    parent_id: int | None,
    capacity: int,
    target_store: str | None,
    lease_token: UUID | None,
    event_attempt: int | None,
) -> int:
    if topic not in PUBLISH.get(producer, set()):
        raise PermissionError(f"{producer} cannot publish {topic}")
    # Serializes capacity and dedupe checks for this run without a global queue lock.
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(run_id),))
    scope_row = conn.execute("SELECT public.agent_scope() AS scope").fetchone()
    scope = scope_row["scope"] if scope_row else None
    if scope:
        destination = conn.execute(
            "SELECT public.agent_destination(%s,%s) AS destination",
            (topic, Jsonb(payload)),
        ).fetchone()
        assert destination
        expected = destination["destination"]
        definition = conn.execute("SELECT public.agent_definition() AS definition").fetchone()
        assert definition
        if (
            str(run_id) != scope["run_id"]
            or producer != definition["definition"]["role"]
            or target_store not in (None, expected)
        ):
            raise PermissionError("Queue destination exceeds agent scope")
        if parent_id is None or lease_token is None or event_attempt is None:
            raise PermissionError("Publishing requires a complete incoming event lease")
        try:
            row = conn.execute(
                "SELECT public.agent_queue_publish(%s,%s,%s,%s,%s,%s,%s,%s,%s) AS id",
                (
                    parent_id,
                    lease_token,
                    event_attempt,
                    topic,
                    Jsonb(payload),
                    key,
                    due_sim,
                    priority,
                    capacity,
                ),
            ).fetchone()
        except ProgramLimitExceeded:
            raise Backpressure(
                "Queue capacity reached; retry producer after consumers drain"
            ) from None
        assert row
        return int(row["id"])
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
           due_sim,priority,parent_id,target_store,traceparent,available_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'1970-01-01 UTC'::timestamptz) RETURNING id""",
        (
            run_id,
            producer,
            topic,
            Jsonb(payload),
            key,
            trace_id,
            due_sim,
            priority,
            parent_id,
            target_store,
            current_traceparent(),
        ),
    ).fetchone()
    assert row
    return int(row["id"])


class Queue:
    def __init__(self, url: str | None = None, lease_seconds: float = 45) -> None:
        self.url = url
        self.lease_seconds = lease_seconds

    def claim(
        self,
        role: str,
        run_id: UUID | str,
        sim_time: int,
        *,
        accepted_topics: tuple[str, ...] | None = None,
    ) -> Event | None:
        if role not in SUBSCRIBE:
            raise PermissionError(f"Unknown consumer role: {role}")
        topics = set(accepted_topics) if accepted_topics is not None else SUBSCRIBE[role]
        if not topics.issubset(SUBSCRIBE[role]):
            raise PermissionError("Consumer topics exceed role authority")
        token = uuid4()
        with connect(self.url) as conn:
            scope = conn.execute("SELECT public.agent_scope() AS scope").fetchone()
            if scope and scope["scope"]:
                claimed = conn.execute(
                    "SELECT public.agent_queue_claim(%s,%s,%s,%s) AS event",
                    (role, run_id, sorted(topics), self.lease_seconds),
                ).fetchone()
                assert claimed
                row = claimed["event"]
            else:
                conn.execute(
                    """UPDATE events SET state='dead', error='lease_expired_after_max_attempts',
                       lease_token=NULL, lease_until=NULL WHERE run_id=%s AND state='leased'
                       AND lease_until < clock_timestamp() AND attempts >= max_attempts""",
                    (run_id,),
                )
                row = conn.execute(
                    """WITH candidate AS (
                         SELECT id FROM events WHERE run_id=%s AND topic=ANY(%s)
                         AND due_sim<=%s AND available_at<=clock_timestamp()
                         AND attempts<max_attempts
                         AND (state='ready' OR (state='leased' AND lease_until<clock_timestamp()))
                         ORDER BY priority DESC, due_sim, id FOR UPDATE SKIP LOCKED LIMIT 1
                       ) UPDATE events e SET state='leased', lease_token=%s,
                         lease_until=clock_timestamp() + %s * interval '1 second',
                         attempts=attempts+1
                       FROM candidate c WHERE e.id=c.id RETURNING e.*""",
                    (run_id, sorted(topics), sim_time, token, self.lease_seconds),
                ).fetchone()
        if row is None:
            return None
        return Event(
            row["id"],
            UUID(str(row["run_id"])),
            row["topic"],
            row["payload"],
            row["trace_id"],
            UUID(str(row["lease_token"])),
            row["attempts"],
            row["due_sim"],
            row["target_store"],
            row.get("traceparent"),
            role,
        )

    @traced_event("queue.process")
    def process(self, event: Event, handler: Callable[[Connection, Event], None]) -> bool:
        try:
            with connect(self.url) as conn:
                # Shared lock ordering for all writers avoids run/queue deadlocks.
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (str(event.run_id),)
                )
                persist_trace_context(conn, event)
                scope = conn.execute("SELECT public.agent_scope() AS scope").fetchone()
                if scope and scope["scope"]:
                    locked = conn.execute(
                        "SELECT public.agent_queue_lock(%s,%s,%s) AS locked",
                        (event.id, event.token, event.attempts),
                    ).fetchone()
                    if not locked or not locked["locked"]:
                        raise StaleLease("Worker no longer owns event")
                    source = conn.execute(
                        "SELECT * FROM events WHERE id=%s", (event.id,)
                    ).fetchone()
                    assert source
                    # Typed policies see the authoritative leased source, including its payload.
                    current = Event(
                        source["id"],
                        source["run_id"],
                        source["topic"],
                        source["payload"],
                        source["trace_id"],
                        source["lease_token"],
                        source["attempts"],
                        source["due_sim"],
                        source["target_store"],
                        source.get("traceparent"),
                        event.consumer,
                    )
                    handler(conn, current)
                    acked = conn.execute(
                        "SELECT public.agent_queue_ack(%s,%s,%s) AS acked",
                        (event.id, event.token, event.attempts),
                    ).fetchone()
                    if not acked or not acked["acked"]:
                        raise StaleLease("Lease expired before commit")
                else:
                    row = conn.execute(
                        """SELECT id FROM events WHERE id=%s AND state='leased'
                           AND lease_token=%s AND lease_until>clock_timestamp() FOR UPDATE""",
                        (event.id, event.token),
                    ).fetchone()
                    if not row:
                        raise StaleLease("Worker no longer owns event")
                    handler(conn, event)
                    ack = conn.execute(
                        """UPDATE events SET state='done', completed_at=now(),
                           lease_token=NULL, lease_until=NULL WHERE id=%s
                           AND lease_token=%s AND lease_until>clock_timestamp()""",
                        (event.id, event.token),
                    )
                    if ack.rowcount != 1:
                        raise StaleLease("Lease expired before commit")
            if active():
                self._record_terminal(event)
            return True
        except StaleLease:
            return False
        except Exception as exc:
            # Do not persist exception strings: provider errors may contain credentials.
            self.fail(event, type(exc).__name__)
            return False

    def _record_terminal(self, event: Event) -> None:
        # The ACK above has committed. Reporting must never reverse that outcome.
        try:
            with connect(self.url) as conn:
                scope = conn.execute("SELECT public.agent_scope() AS scope").fetchone()
                if scope and scope["scope"]:
                    result = conn.execute(
                        "SELECT public.agent_order_telemetry(%s) AS data", (event.id,)
                    ).fetchone()
                    row = result["data"] if result else None
                else:
                    row = conn.execute(
                        "SELECT status, extract(epoch FROM (clock_timestamp()-(SELECT "
                        "min(created_at) FROM events WHERE run_id=%s AND trace_id=%s)))*1000 "
                        "AS latency FROM (SELECT status FROM supply_orders WHERE run_id=%s "
                        "AND id=%s UNION ALL SELECT status FROM orders WHERE run_id=%s "
                        "AND id=%s UNION ALL SELECT status FROM lab_delivery_jobs WHERE "
                        "run_id=%s AND basket=%s) statuses "
                        "WHERE status IN ('delivered','failed','unserved','abandoned') LIMIT 1",
                        (event.run_id, event.trace_id) * 4,
                    ).fetchone()
            if not row:
                return
            with order_span(
                "order.complete",
                run_id=event.run_id,
                order_id=event.trace_id,
                attributes={
                    "delivery.order.terminal": True,
                    "delivery.order.success": row["status"] == "delivered",
                    "delivery.order.latency_ms": float(row["latency"] or 0),
                },
            ):
                pass
        except Exception:
            # Analytics is best-effort and independent of the durable business ACK.
            pass

    def fail(self, event: Event, code: str) -> None:
        with connect(self.url) as conn:
            scope = conn.execute("SELECT public.agent_scope() AS scope").fetchone()
            if scope and scope["scope"]:
                conn.execute(
                    "SELECT public.agent_queue_fail(%s,%s,%s,%s)",
                    (event.id, event.token, event.attempts, code[:80]),
                )
                return
            conn.execute(
                """UPDATE events SET state=CASE WHEN attempts>=max_attempts THEN 'dead'
                     ELSE 'ready' END, error=%s, lease_token=NULL, lease_until=NULL,
                     available_at=clock_timestamp() + least(30,power(2,least(5,
                         greatest(0,attempts-greatest(0,max_attempts-3)-1)))) * interval '1 second'
                   WHERE id=%s AND state='leased' AND lease_token=%s""",
                (code[:80], event.id, event.token),
            )

    def replay(self, event_id: int) -> bool:
        """Explicit operator action; no automatic poison-message loop."""
        with connect(self.url) as conn:
            row = conn.execute(
                """UPDATE events SET state='ready', max_attempts=attempts+3, error=NULL,
                   available_at=now() WHERE id=%s AND state='dead' RETURNING id""",
                (event_id,),
            ).fetchone()
        return row is not None

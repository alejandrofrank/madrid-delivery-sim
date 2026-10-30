"""Read-only, bounded trace index for the local operator evidence page."""

from typing import Any

from fastapi import APIRouter

from delivery.db import connect
from delivery.telemetry import trace_url, tracing_mode

router = APIRouter()


@router.get("/api/telemetry/traces")
def recent_traces() -> dict[str, Any]:
    with connect() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        rows = conn.execute(
            """SELECT run_id::text AS run_id, trace_id AS correlation_id,
            split_part(coalesce(traceparent,otel_traceparent),'-',2) AS trace_id,
            count(*) AS events,
            max(id) AS last_event_id FROM events
            WHERE coalesce(traceparent,otel_traceparent) IS NOT NULL
            GROUP BY run_id,trace_id,split_part(coalesce(traceparent,otel_traceparent),'-',2)
            ORDER BY max(id) DESC LIMIT 30"""
        ).fetchall()
    return {
        "mode": tracing_mode(),
        "traces": [{**row, "url": trace_url(row["trace_id"])} for row in rows],
    }

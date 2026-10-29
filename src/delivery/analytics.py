"""Opt-in, bounded BigQuery analytics with no credentials or threads when disabled.

Streaming insert IDs are best-effort deduplication. Consumers must deduplicate
``event_id`` (the supplied queries do); this is deliberately not an audit log.
"""

from __future__ import annotations

import atexit
import logging
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

LOG = logging.getLogger(__name__)
_COMMON = {"event_id", "observed_at", "agent", "trace_id", "order_id"}
_SPAN = {
    "span_id", "parent_span_id", "name", "kind", "status", "latency_ms", "input_tokens",
    "output_tokens", "cost_usd", "tool", "model", "run_id", "topic", "attempt",
}
FIELDS = {
    "traces": _COMMON | _SPAN,
    "agent_steps": _COMMON | _SPAN | {"success"},
    "orders": _COMMON | {"success", "latency_ms", "cost_usd", "status"},
    "eval_runs": _COMMON | {
        "run_id", "case_id", "arm", "category", "repetition", "repeat_k", "passed",
        "latency_ms", "cost_usd", "fixture_version", "source_revision", "mode",
    },
}
_FLOATS = {"latency_ms", "cost_usd"}
_INTS = {"input_tokens", "output_tokens", "attempt", "repetition", "repeat_k"}
_BOOLS = {"success", "passed"}
_TRANSIENT_REASONS = {"backendError", "internalError", "rateLimitExceeded", "timeout", "stopped"}


class InsertClient(Protocol):
    def insert_rows_json(
        self, table: str, json_rows: Sequence[Mapping[str, Any]], *, row_ids: Sequence[str],
        retry: Any, timeout: float, skip_invalid_rows: bool,
    ) -> Sequence[Mapping[str, Any]]: ...

    def close(self) -> None: ...


def analytics_enabled() -> bool:
    return os.getenv("MDS_BIGQUERY_ENABLED", "false").lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool = False
    project: str = ""
    dataset: str = "mds_analytics"
    batch_size: int = 100
    max_queue_size: int = 10000
    flush_interval: float = 2.0
    max_attempts: int = 3
    retry_delay: float = 0.5
    request_timeout: float = 5.0

    def __post_init__(self) -> None:
        if self.enabled and not re.fullmatch(r"[a-z][a-z0-9.-]{2,62}", self.project):
            raise ValueError("Analytics requires an explicit valid Google Cloud project")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,1023}", self.dataset):
            raise ValueError("Invalid BigQuery dataset")
        if not 1 <= self.batch_size <= 500 or self.max_queue_size < self.batch_size:
            raise ValueError("Invalid analytics batch or queue size")
        if self.flush_interval <= 0 or self.max_attempts < 1 or self.retry_delay < 0:
            raise ValueError("Invalid analytics retry or flush settings")
        if self.request_timeout <= 0:
            raise ValueError("Invalid analytics request timeout")


def _client(project: str) -> InsertClient:
    # Importing this module, constructing a disabled writer and submitting a
    # disabled event never loads the SDK or discovers application credentials.
    from google.cloud import bigquery

    return bigquery.Client(project=project)  # type: ignore[no-any-return]


@dataclass
class _Pending:
    table: str
    row: dict[str, Any]
    attempts: int = 0
    ready_at: float = 0


def _clean_row(table: str, row: Mapping[str, Any], event_id: str | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key in FIELDS[table]:
        value = row.get(key)
        if value is None:
            continue
        if key in _FLOATS:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Invalid numeric analytics field")
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid numeric analytics field")
            clean[key] = float(value)
        elif key in _INTS:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Invalid integer analytics field")
            clean[key] = value
        elif key in _BOOLS:
            if not isinstance(value, bool):
                raise ValueError("Invalid boolean analytics field")
            clean[key] = value
        elif not isinstance(value, str) or len(value) > 1024:
            raise ValueError("Invalid string analytics field")
        else:
            clean[key] = value
    clean["event_id"] = event_id or clean.get("event_id") or uuid.uuid4().hex
    if not isinstance(clean["event_id"], str) or not 1 <= len(clean["event_id"]) <= 128:
        raise ValueError("Invalid analytics event ID")
    timestamp = clean.get("observed_at")
    observed = datetime.fromisoformat(timestamp) if timestamp else datetime.now(UTC)
    if observed.tzinfo is None:
        raise ValueError("Analytics timestamp requires a timezone")
    clean["observed_at"] = observed.astimezone(UTC).isoformat()
    clean["agent"] = clean.get("agent") or "unknown"
    return clean


def _transient_exception(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    code = getattr(exc, "code", None)
    # google.api_core HTTP exceptions expose an integer code. Do not log the
    # exception text: service responses can echo a rejected row's contents.
    return isinstance(code, int) and code in {408, 429, 500, 502, 503, 504}


class BigQueryBatchWriter:
    """Nonblocking producers; bounded queue, attempts and shutdown waiting.

    Failed and overflowing rows are counted and dropped, never raised into the
    business operation. ``start_worker=False`` supports deterministic tests and
    one-shot processes that explicitly call flush. There is no disk spool.
    """

    def __init__(
        self, config: AnalyticsConfig | None = None, *,
        client_factory: Callable[[str], InsertClient] = _client, start_worker: bool = True,
    ) -> None:
        self.config = config or AnalyticsConfig()
        self._factory = client_factory
        self._autostart = start_worker
        self._client: InsertClient | None = None
        self._queue: deque[_Pending] = deque()
        self._condition = threading.Condition()
        self._flush_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._shutdown_deadline: float | None = None
        self._pending = 0
        self._flush_requested = False
        self._counts = {"accepted": 0, "inserted": 0, "retried": 0, "dropped": 0}

    @property
    def counters(self) -> dict[str, int]:
        with self._condition:
            return {**self._counts, "pending": self._pending}

    def enqueue(
        self, table: str, row: Mapping[str, Any], *, event_id: str | None = None,
    ) -> bool:
        if not self.config.enabled:
            return False
        try:
            clean = _clean_row(table, row, event_id)
        except (KeyError, ValueError, TypeError):
            with self._condition:
                self._counts["dropped"] += 1
            LOG.warning("analytics row rejected; category=schema count=1")
            return False
        with self._condition:
            if self._closed or self._pending >= self.config.max_queue_size:
                self._counts["dropped"] += 1
                if self._counts["dropped"] == 1 or self._counts["dropped"] % 100 == 0:
                    LOG.warning(
                        "analytics admission rejected; dropped=%d pending=%d",
                        self._counts["dropped"], self._pending,
                    )
                return False
            self._queue.append(_Pending(table, clean))
            self._pending += 1
            self._counts["accepted"] += 1
            if self._autostart and self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="mds-bigquery", daemon=True,
                )
                self._thread.start()
            self._condition.notify_all()
        return True

    def _batch(self) -> list[_Pending]:
        with self._condition:
            now = time.monotonic()
            table = next((p.table for p in self._queue if p.ready_at <= now), None)
            selected: list[_Pending] = []
            remaining: deque[_Pending] = deque()
            for pending in self._queue:
                if (pending.table == table and pending.ready_at <= now
                        and len(selected) < self.config.batch_size):
                    selected.append(pending)
                else:
                    remaining.append(pending)
            self._queue = remaining
            return selected

    def _drain_once(self, timeout: float) -> bool:
        with self._flush_lock:
            batch = self._batch()
            if not batch:
                return False
            retry_indices: set[int] = set()
            failed_indices: set[int] = set()
            try:
                if self._client is None:
                    self._client = self._factory(self.config.project)
                errors = self._client.insert_rows_json(
                    f"{self.config.project}.{self.config.dataset}.{batch[0].table}",
                    [p.row for p in batch], row_ids=[p.row["event_id"] for p in batch],
                    retry=None, timeout=min(timeout, self.config.request_timeout),
                    skip_invalid_rows=True,
                )
                for error in errors:
                    index = error.get("index")
                    if not isinstance(index, int) or not 0 <= index < len(batch):
                        raise ValueError("Invalid analytics insert response")
                    failed_indices.add(index)
                    reasons = {e.get("reason") for e in error.get("errors", [])}
                    if reasons and reasons <= _TRANSIENT_REASONS:
                        retry_indices.add(index)
            except Exception as exc:
                failed_indices = set(range(len(batch)))
                retry_indices = failed_indices.copy() if _transient_exception(exc) else set()
            with self._condition:
                for index, pending in enumerate(batch):
                    pending.attempts += 1
                    if index in retry_indices and pending.attempts < self.config.max_attempts:
                        pending.ready_at = (
                            time.monotonic() + self.config.retry_delay * 2 ** (pending.attempts - 1)
                        )
                        self._queue.append(pending)
                        self._counts["retried"] += 1
                    else:
                        self._pending -= 1
                        self._counts["dropped" if index in failed_indices else "inserted"] += 1
                self._condition.notify_all()
            if failed_indices:
                LOG.warning(
                    "analytics insert failures; failed=%d retryable=%d",
                    len(failed_indices), len(retry_indices),
                )
            return True

    def _run(self) -> None:
        next_flush = time.monotonic() + self.config.flush_interval
        try:
            while True:
                with self._condition:
                    now = time.monotonic()
                    if self._closed and (not self._pending or (
                        self._shutdown_deadline is not None and now >= self._shutdown_deadline
                    )):
                        self._counts["dropped"] += len(self._queue)
                        self._pending -= len(self._queue)
                        self._queue.clear()
                        self._condition.notify_all()
                        return
                    ready = [p.ready_at for p in self._queue]
                    due = min(ready, default=now + self.config.flush_interval)
                    demand = (len(self._queue) >= self.config.batch_size
                              or self._flush_requested or self._closed or now >= next_flush)
                    if not ready or not demand or due > now:
                        delay = max(0.001, (due if demand else next_flush) - now)
                        self._condition.wait(min(delay, self.config.flush_interval))
                        continue
                    timeout = self.config.request_timeout
                    if self._shutdown_deadline is not None:
                        timeout = max(0.001, min(timeout, self._shutdown_deadline - now))
                self._drain_once(timeout)
                with self._condition:
                    if not self._pending:
                        self._flush_requested = False
                next_flush = time.monotonic() + self.config.flush_interval
        finally:
            self._close_client()

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait for admission queue drain; inspect counters for insertion failures."""
        if not self.config.enabled:
            return True
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            self._flush_requested = True
            self._condition.notify_all()
        while time.monotonic() < deadline:
            with self._condition:
                if not self._pending:
                    return True
                if self._thread is not None:
                    self._condition.wait(max(0, deadline - time.monotonic()))
                    continue
            if not self._drain_once(max(0.001, deadline - time.monotonic())):
                with self._condition:
                    self._condition.wait(min(0.01, max(0, deadline - time.monotonic())))
        with self._condition:
            return self._pending == 0

    def _close_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                LOG.warning("analytics client close failed")
            self._client = None

    def shutdown(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            self._closed = True
            self._shutdown_deadline = deadline
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(max(0, deadline - time.monotonic()))
            complete = not self._thread.is_alive() and self.counters["pending"] == 0
            LOG.info("analytics shutdown; drained=%s counters=%s", complete, self.counters)
            return complete
        complete = self.flush(max(0, deadline - time.monotonic()))
        with self._condition:
            self._counts["dropped"] += len(self._queue)
            self._pending -= len(self._queue)
            self._queue.clear()
        self._close_client()
        LOG.info("analytics shutdown; drained=%s counters=%s", complete, self.counters)
        return complete


_writer: BigQueryBatchWriter | None = None
_writer_lock = threading.Lock()


def get_writer() -> BigQueryBatchWriter:
    global _writer
    with _writer_lock:
        if _writer is None or _writer._closed:
            try:
                config = AnalyticsConfig(
                    enabled=analytics_enabled(), project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
                    dataset=os.getenv("MDS_BIGQUERY_DATASET", "mds_analytics"),
                )
            except ValueError:
                LOG.warning("analytics disabled; category=configuration")
                config = AnalyticsConfig()
            _writer = BigQueryBatchWriter(config)
            if config.enabled:
                atexit.register(_writer.shutdown)
        return _writer


def _span_rows(span: Any) -> list[tuple[str, dict[str, Any]]]:
    attrs = span.attributes or {}
    context = span.context
    if context is None or span.start_time is None or span.end_time is None:
        return []
    trace_id = format(context.trace_id, "032x")
    span_id = format(context.span_id, "016x")
    status = getattr(span.status.status_code, "name", "UNSET")
    row: dict[str, Any] = {
        "event_id": f"{trace_id}-{span_id}",
        "observed_at": datetime.fromtimestamp(span.start_time / 1e9, UTC).isoformat(),
        "agent": attrs.get("delivery.agent", "unknown"),
        "trace_id": trace_id, "span_id": span_id,
        "parent_span_id": format(span.parent.span_id, "016x") if span.parent else None,
        "name": span.name, "kind": getattr(span.kind, "name", "INTERNAL"), "status": status,
        "latency_ms": max(0, (span.end_time - span.start_time) / 1e6),
    }
    for field, attribute in {
        "order_id": "delivery.order_id", "run_id": "delivery.run_id", "tool": "delivery.tool",
        "topic": "delivery.topic", "attempt": "delivery.attempt", "cost_usd": "delivery.cost_usd",
        "input_tokens": "gen_ai.usage.input_tokens", "output_tokens": "gen_ai.usage.output_tokens",
        "model": "gen_ai.request.model",
    }.items():
        row[field] = attrs.get(attribute)
    result = [("traces", row)]
    if attrs.get("delivery.agent") or attrs.get("delivery.tool"):
        result.append(("agent_steps", {**row, "success": attrs.get("delivery.success")}))
    if attrs.get("delivery.order.terminal") is True:
        result.append(("orders", {
            **{key: row.get(key) for key in _COMMON}, "status": status,
            "success": attrs.get("delivery.order.success", attrs.get("delivery.success")),
            "latency_ms": attrs.get("delivery.order.latency_ms"),
        }))
    return result


class AnalyticsSpanExporter:
    """OTel exporter that performs only bounded in-memory admission on export."""

    def __init__(self, writer: BigQueryBatchWriter | None = None) -> None:
        self.writer = writer or get_writer()

    def export(self, spans: Sequence[Any]) -> Any:
        from opentelemetry.sdk.trace.export import SpanExportResult

        accepted = True
        for span in spans:
            try:
                for table, row in _span_rows(span):
                    accepted = self.writer.enqueue(table, row) and accepted
            except (AttributeError, TypeError, ValueError):
                LOG.warning("analytics span rejected; category=schema count=1")
                accepted = False
        return SpanExportResult.SUCCESS if accepted else SpanExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.writer.flush(timeout_millis / 1000)

    def shutdown(self) -> None:
        self.writer.shutdown()


def analytics_span_exporter() -> AnalyticsSpanExporter | None:
    if not analytics_enabled():
        return None
    writer = get_writer()
    return AnalyticsSpanExporter(writer) if writer.config.enabled else None

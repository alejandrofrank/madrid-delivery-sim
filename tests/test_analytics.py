from __future__ import annotations

import json
import logging
import threading
from collections import deque
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult

from delivery import analytics
from delivery.analytics import AnalyticsConfig, AnalyticsSpanExporter, BigQueryBatchWriter


class FakeClient:
    def __init__(self, responses: Sequence[Any] = ()) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, Any]] = []
        self.closed = False
        self.called = threading.Event()

    def insert_rows_json(
        self, table: str, json_rows: Sequence[Mapping[str, Any]], *, row_ids: Sequence[str],
        retry: Any, timeout: float, skip_invalid_rows: bool,
    ) -> Sequence[Mapping[str, Any]]:
        self.calls.append({
            "table": table, "rows": [dict(row) for row in json_rows], "row_ids": list(row_ids),
            "retry": retry, "timeout": timeout, "skip_invalid_rows": skip_invalid_rows,
        })
        self.called.set()
        response = self.responses.popleft() if self.responses else []
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[no-any-return]

    def close(self) -> None:
        self.closed = True


def writer_for(client: FakeClient, **kwargs: Any) -> BigQueryBatchWriter:
    return BigQueryBatchWriter(
        AnalyticsConfig(enabled=True, project="test-project", retry_delay=0, **kwargs),
        client_factory=lambda _: client, start_worker=False,
    )


def row(case: str = "case-1") -> dict[str, Any]:
    return {
        "agent": "restaurant", "case_id": case, "passed": True,
        "observed_at": "2026-10-29T12:00:00+02:00",
    }


def test_writer_fields_match_deployed_bigquery_schemas() -> None:
    schema_dir = Path(__file__).resolve().parents[1] / "infra/gcp-ai/schemas"
    for table, fields in analytics.FIELDS.items():
        schema = json.loads((schema_dir / f"{table}.json").read_text())
        by_name = {field["name"]: field for field in schema}
        assert fields == by_name.keys(), table
        assert by_name["observed_at"]["type"] == "TIMESTAMP"
        for name in ("event_id", "observed_at", "agent"):
            assert by_name[name]["mode"] == "REQUIRED"
        for name in fields & {"latency_ms", "cost_usd"}:
            assert by_name[name]["type"] in {"FLOAT", "FLOAT64"}


def test_disabled_writer_never_loads_client_or_starts_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(_: str) -> Any:
        raise AssertionError("Disabled analytics must not discover credentials")

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "a-real-project")
    monkeypatch.delenv("MDS_BIGQUERY_ENABLED", raising=False)
    before = {thread.ident for thread in threading.enumerate()}
    writer = BigQueryBatchWriter(client_factory=forbidden)
    assert not writer.enqueue("eval_runs", row())
    assert writer.flush()
    assert writer.shutdown()
    assert analytics.analytics_span_exporter() is None
    assert before == {thread.ident for thread in threading.enumerate()}
    assert writer.counters == {
        "accepted": 0, "inserted": 0, "retried": 0, "dropped": 0, "pending": 0,
    }


def test_lazy_client_batching_privacy_and_stable_ids() -> None:
    client = FakeClient()
    created = []

    def factory(project: str) -> FakeClient:
        created.append(project)
        return client

    writer = BigQueryBatchWriter(
        AnalyticsConfig(enabled=True, project="test-project", batch_size=2),
        client_factory=factory, start_worker=False,
    )
    for index in range(5):
        assert writer.enqueue(
            "eval_runs", {**row(str(index)), "prompt": "private", "redis.value": "private"},
            event_id=f"run-{index}",
        )
    assert not created
    assert writer.flush()
    assert created == ["test-project"]
    assert [len(call["rows"]) for call in client.calls] == [2, 2, 1]
    assert all(call["table"] == "test-project.mds_analytics.eval_runs" for call in client.calls)
    assert client.calls[0]["row_ids"] == ["run-0", "run-1"]
    assert client.calls[0]["retry"] is None
    assert client.calls[0]["skip_invalid_rows"]
    exported = client.calls[0]["rows"][0]
    assert exported["observed_at"] == "2026-10-29T10:00:00+00:00"
    assert "prompt" not in exported and "redis.value" not in exported
    assert writer.shutdown()
    assert client.closed


def test_partial_transient_errors_retry_only_failed_rows_with_same_id() -> None:
    client = FakeClient([[{"index": 1, "errors": [{"reason": "backendError"}]}], []])
    writer = writer_for(client)
    for index in range(3):
        assert writer.enqueue("eval_runs", row(str(index)), event_id=f"stable-{index}")
    assert writer.flush()
    assert client.calls[1]["row_ids"] == ["stable-1"]
    assert writer.counters == {
        "accepted": 3, "inserted": 3, "retried": 1, "dropped": 0, "pending": 0,
    }


def test_permanent_partial_errors_are_not_retried_or_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private model reply and credential"
    client = FakeClient([[{"index": 0, "errors": [{"reason": "invalid", "message": secret}]}]])
    writer = writer_for(client)
    writer.enqueue("eval_runs", row())
    writer.enqueue("eval_runs", row("valid"))
    with caplog.at_level(logging.WARNING):
        assert writer.flush()
    assert len(client.calls) == 1
    assert writer.counters["inserted"] == 1
    assert writer.counters["dropped"] == 1
    assert secret not in caplog.text


def test_transport_retries_are_bounded_and_preserve_id(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeClient([TimeoutError("private request contents")] * 3)
    writer = writer_for(client)
    assert writer.enqueue("eval_runs", row(), event_id="same-on-retry")
    assert writer.flush()
    assert [call["row_ids"] for call in client.calls] == [["same-on-retry"]] * 3
    assert writer.counters["retried"] == 2
    assert writer.counters["dropped"] == 1
    assert "private request contents" not in caplog.text


def test_sdk_http_transient_error_retries() -> None:
    class ServiceUnavailable(Exception):
        code = 503

    client = FakeClient([ServiceUnavailable(), []])
    writer = writer_for(client)
    writer.enqueue("eval_runs", row())
    assert writer.flush()
    assert len(client.calls) == 2
    assert writer.counters["inserted"] == 1


def test_failed_credentials_do_not_escape_business_operation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def denied(_: str) -> Any:
        raise RuntimeError("private credential path")

    writer = BigQueryBatchWriter(
        AnalyticsConfig(enabled=True, project="test-project"),
        client_factory=denied, start_worker=False,
    )
    assert writer.enqueue("eval_runs", row())
    assert writer.flush()
    assert writer.counters["dropped"] == 1
    assert "private credential path" not in caplog.text


def test_queue_is_bounded_and_safe_under_concurrent_admission() -> None:
    client = FakeClient()
    writer = writer_for(client, batch_size=10, max_queue_size=40)
    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(lambda i: writer.enqueue("eval_runs", row(str(i))), range(100)))
    assert sum(admitted) == 40
    assert writer.counters["pending"] == 40
    assert writer.counters["dropped"] == 60
    assert writer.flush()
    assert writer.counters["inserted"] == 40
    ids = [identity for call in client.calls for identity in call["row_ids"]]
    assert len(set(ids)) == 40


def test_tables_are_batched_separately() -> None:
    client = FakeClient()
    writer = writer_for(client)
    writer.enqueue("eval_runs", row())
    writer.enqueue("orders", {"agent": "delivery", "success": True})
    writer.enqueue("eval_runs", row("second"))
    assert writer.flush()
    assert len(client.calls) == 2
    assert client.calls[0]["table"].endswith("eval_runs")
    assert len(client.calls[0]["rows"]) == 2
    assert client.calls[1]["table"].endswith("orders")


@pytest.mark.parametrize("invalid", [
    {"cost_usd": float("nan")}, {"latency_ms": -1}, {"repeat_k": True},
    {"passed": "true"}, {"observed_at": "2026-10-29"}, {"agent": {"prompt": "private"}},
])
def test_invalid_rows_fail_closed_without_escaping(invalid: dict[str, Any]) -> None:
    client = FakeClient()
    writer = writer_for(client)
    assert not writer.enqueue("eval_runs", {**row(), **invalid})
    assert not writer.enqueue("arbitrary-table", row())
    assert writer.flush()
    assert not client.calls
    assert writer.counters["dropped"] == 2


def test_periodic_worker_flushes_small_batches_and_shutdown_drains() -> None:
    client = FakeClient()
    writer = BigQueryBatchWriter(
        AnalyticsConfig(enabled=True, project="test-project", flush_interval=0.02),
        client_factory=lambda _: client,
    )
    try:
        assert writer.enqueue("eval_runs", row())
        assert client.called.wait(2)
        assert writer.enqueue("eval_runs", row("shutdown"))
        assert writer.shutdown(timeout=2)
        assert writer.counters["inserted"] == 2
        assert client.closed
        assert not writer.enqueue("eval_runs", row("too-late"))
        assert writer.shutdown()
    finally:
        writer.shutdown(timeout=2)


def test_shutdown_has_deadline_when_transport_is_busy() -> None:
    release = threading.Event()

    class SlowClient(FakeClient):
        def insert_rows_json(self, *args: Any, **kwargs: Any) -> Sequence[Mapping[str, Any]]:
            self.called.set()
            assert release.wait(2)
            return super().insert_rows_json(*args, **kwargs)

    client = SlowClient()
    writer = BigQueryBatchWriter(
        AnalyticsConfig(enabled=True, project="test-project", batch_size=1),
        client_factory=lambda _: client,
    )
    try:
        writer.enqueue("eval_runs", row())
        assert client.called.wait(2)
        assert not writer.flush(timeout=0.01)
        assert not writer.shutdown(timeout=0.01)
    finally:
        release.set()
        writer.shutdown(timeout=2)
    assert client.closed


def test_span_exporter_maps_only_allowed_fields_and_terminal_order() -> None:
    client = FakeClient()
    writer = writer_for(client)
    exporter = AnalyticsSpanExporter(writer)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("analytics-test")
    with tracer.start_as_current_span("agent.model", attributes={
        "delivery.agent": "restaurant", "delivery.order_id": "order-1",
        "delivery.run_id": "run-1", "delivery.cost_usd": 0.003,
        "gen_ai.usage.input_tokens": 20, "gen_ai.usage.output_tokens": 10,
        "gen_ai.request.model": "flash-lite", "gen_ai.prompt": "private",
    }):
        with tracer.start_as_current_span("agent.tool", attributes={
            "delivery.agent": "restaurant", "delivery.tool": "accept_order",
            "delivery.order_id": "order-1", "delivery.success": True,
            "tool.arguments": "private",
        }):
            pass
        with tracer.start_as_current_span("order.complete", attributes={
            "delivery.agent": "delivery", "delivery.order_id": "order-1",
            "delivery.order.terminal": True, "delivery.order.success": True,
            "delivery.order.latency_ms": 1200,
        }):
            pass
        with tracer.start_as_current_span("order.complete", attributes={
            "delivery.agent": "delivery", "delivery.order_id": "order-1",
            "delivery.order.terminal": True, "delivery.order.success": True,
            "delivery.order.latency_ms": 1200,
        }):
            pass
    assert exporter.force_flush()
    rows = [(call["table"].split(".")[-1], row) for call in client.calls for row in call["rows"]]
    assert sum(table == "traces" for table, _ in rows) == 4
    assert sum(table == "agent_steps" for table, _ in rows) == 4
    orders = [row for table, row in rows if table == "orders"]
    assert len(orders) == 2 and orders[0]["success"]
    # Different acknowledgements must not reuse insertId with different timing
    # facts: BigQuery's best-effort dedupe can retain either occurrence. SQL
    # chooses the earliest observed terminal span per lifecycle trace instead.
    assert orders[0]["event_id"] != orders[1]["event_id"]
    assert orders[0]["trace_id"] == orders[1]["trace_id"]
    assert orders[0]["latency_ms"] == 1200
    steps = [row for table, row in rows if table == "agent_steps"]
    assert sum(row.get("cost_usd", 0) for row in steps) == 0.003
    assert len({row["trace_id"] for _, row in rows}) == 1
    assert "private" not in str(rows)
    provider.shutdown()
    assert client.closed


def test_reexporting_same_terminal_span_keeps_identical_row_and_insert_id() -> None:
    client = FakeClient()
    writer = writer_for(client)
    provider = TracerProvider()
    with provider.get_tracer("test").start_as_current_span("order.complete", attributes={
        "delivery.order_id": "order-1", "delivery.order.terminal": True,
        "delivery.order.success": True, "delivery.order.latency_ms": 1200,
    }) as span:
        pass
    exporter = AnalyticsSpanExporter(writer)
    assert exporter.export([span]) == SpanExportResult.SUCCESS
    assert exporter.export([span]) == SpanExportResult.SUCCESS
    assert writer.flush()
    orders = [call for call in client.calls if call["table"].endswith(".orders")]
    assert len(orders) == 1
    assert orders[0]["row_ids"][0] == orders[0]["row_ids"][1]
    assert orders[0]["rows"][0] == orders[0]["rows"][1]
    writer.shutdown()
    provider.shutdown()


def test_exporter_reports_queue_overflow_without_throwing() -> None:
    client = FakeClient()
    writer = writer_for(client, batch_size=1, max_queue_size=1)
    provider = TracerProvider()
    with provider.get_tracer("test").start_as_current_span("span") as span:
        pass
    exporter = AnalyticsSpanExporter(writer)
    assert exporter.export([span, span]) == SpanExportResult.FAILURE
    assert writer.counters["dropped"] == 1
    assert writer.shutdown()
    provider.shutdown()


def test_invalid_enabled_configuration_disables_export_without_credentials(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("MDS_BIGQUERY_ENABLED", "true")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setattr(analytics, "_writer", None)
    assert analytics.analytics_span_exporter() is None
    assert not analytics.get_writer().config.enabled
    assert "category=configuration" in caplog.text

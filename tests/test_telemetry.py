"""Offline OTel contracts and durable queue context; never contact a collector."""

from collections.abc import Iterator
from functools import partial
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from delivery import telemetry
from delivery.db import Connection, connect
from delivery.queue import Event, Queue, publish


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "_provider", provider)
    yield exporter
    provider.shutdown()


def test_tracing_off_by_default_never_creates_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DELIVERY_OTEL_EXPORTER", raising=False)
    monkeypatch.setattr(telemetry, "_provider", None)
    with telemetry.trace_span("disabled"):
        assert telemetry.trace_fields() == {}
        assert telemetry.traceparent() is None
    assert telemetry._provider is None


def test_cloud_tracing_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setenv("DELIVERY_OTEL_EXPORTER", "gcp")
    monkeypatch.delenv("DELIVERY_OTEL_CLOUD_ENABLED", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "portfolio-demo")
    with pytest.raises(ValueError, match="explicit opt-in"):
        telemetry.tracer()


def test_free_path_rejects_remote_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setenv("DELIVERY_OTEL_EXPORTER", "jaeger")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://example.com/v1/traces")
    with pytest.raises(ValueError, match="local Jaeger"):
        telemetry.tracer()


def test_context_continues_across_worker_boundary(spans: InMemorySpanExporter) -> None:
    with telemetry.trace_span("producer"):
        context = telemetry.traceparent()
    with telemetry.trace_span("consumer", parent=context):
        with telemetry.trace_span("tool"):
            assert telemetry.trace_fields()["trace_id"] == context.split("-")[1]  # type: ignore[union-attr]
    producer, tool, consumer = spans.get_finished_spans()
    assert consumer.parent and consumer.parent.span_id == producer.context.span_id
    assert tool.parent and tool.parent.span_id == consumer.context.span_id


def test_exception_text_is_never_exported(spans: InMemorySpanExporter) -> None:
    with pytest.raises(RuntimeError), telemetry.trace_span("failed"):
        raise RuntimeError("credential=DO_NOT_EXPORT")
    span = spans.get_finished_spans()[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes == {"error.type": "RuntimeError"}
    assert span.status.description is None and not span.events


def test_trace_links_are_validated_and_mode_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    trace_id = "123456789abcdef0123456789abcdef0"
    monkeypatch.setenv("DELIVERY_OTEL_EXPORTER", "jaeger")
    assert telemetry.trace_url(trace_id) == f"http://localhost:16686/trace/{trace_id}"
    assert telemetry.trace_url("javascript:alert(1)") is None
    assert telemetry.trace_url("0" * 32) is None
    monkeypatch.setenv("DELIVERY_OTEL_EXPORTER", "gcp")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "portfolio-demo")
    assert telemetry.trace_url(trace_id) == (
        "https://console.cloud.google.com/traces/list?project=portfolio-demo&tid=" + trace_id
    )


@pytest.mark.integration
def test_queue_persists_context_without_changing_payload_or_business_id(
    db_url: str, run_id: UUID, spans: InMemorySpanExporter
) -> None:
    with connect(db_url) as conn:
        original_id = publish(
            conn,
            run_id=run_id,
            producer="generator",
            topic="order.created",
            payload={"secret": "DO_NOT_EXPORT"},
            key="root",
            trace_id="order-1",
        )
    queue = Queue(db_url)
    event = queue.claim("dispatcher", run_id, 0)
    assert event and event.otel_traceparent and event.id == original_id
    assert event.trace_id == "order-1" and event.payload == {"secret": "DO_NOT_EXPORT"}

    def handler(conn: Connection, incoming: Event, *, unused: bool) -> None:
        publish(
            conn,
            run_id=run_id,
            producer="dispatcher",
            topic="courier.assigned",
            payload={"courier_id": "courier-1"},
            key="child",
            trace_id=incoming.trace_id,
            parent_id=incoming.id,
        )

    # Wrapped handlers are common in customer service and must remain supported.
    assert queue.process(event, partial(handler, unused=True))
    child = queue.claim("courier", run_id, 0)
    assert child and child.otel_traceparent
    assert child.otel_traceparent.split("-")[1] == event.otel_traceparent.split("-")[1]
    finished = spans.get_finished_spans()
    producer = next(span for span in finished if span.name == "queue.publish")
    consumer = next(span for span in finished if span.name == "queue.process")
    assert consumer.parent and consumer.parent.span_id == producer.context.span_id
    assert "DO_NOT_EXPORT" not in str([span.attributes for span in finished])


@pytest.mark.integration
def test_retry_keeps_trace_context_and_records_failure(
    db_url: str, run_id: UUID, spans: InMemorySpanExporter
) -> None:
    with connect(db_url) as conn:
        publish(
            conn,
            run_id=run_id,
            producer="generator",
            topic="order.created",
            payload={},
            key="retry",
            trace_id="retry",
        )
    queue = Queue(db_url)
    event = queue.claim("dispatcher", run_id, 0)
    assert event

    def broken(conn: Connection, incoming: Event) -> None:
        raise RuntimeError("credential=DO_NOT_EXPORT")

    assert not queue.process(event, broken)
    with connect(db_url) as conn:
        conn.execute("UPDATE events SET available_at=now() WHERE id=%s", (event.id,))
    retry = queue.claim("dispatcher", run_id, 0)
    assert retry and retry.attempts == 2 and retry.otel_traceparent == event.otel_traceparent
    assert queue.process(retry, lambda conn, event: None)
    consumers = [span for span in spans.get_finished_spans() if span.name == "queue.process"]
    assert consumers[0].status.status_code is StatusCode.ERROR
    assert consumers[0].context.trace_id == consumers[1].context.trace_id
    assert all(not span.events for span in spans.get_finished_spans())

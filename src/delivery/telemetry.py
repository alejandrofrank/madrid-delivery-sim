"""Opt-in, bounded OTel spans. Never export prompts, payloads, SQL or exception text.

Use a dedicated provider so third-party ADK instrumentation cannot accidentally
export model contents. Queue context is persisted separately from business IDs.
"""

import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from threading import Lock
from typing import Any, ParamSpec, TypeVar
from urllib.parse import quote, urlsplit

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

P = ParamSpec("P")
R = TypeVar("R")
_provider: TracerProvider | None = None
_lock = Lock()
_propagator = TraceContextTextMapPropagator()
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")


def tracing_mode() -> str:
    mode = os.getenv("DELIVERY_OTEL_EXPORTER", "disabled")
    if mode not in {"disabled", "jaeger", "gcp"}:
        raise ValueError("DELIVERY_OTEL_EXPORTER must be disabled, jaeger or gcp")
    return mode


def tracer() -> trace.Tracer:
    global _provider
    if _provider is not None:
        return _provider.get_tracer("delivery")
    mode = tracing_mode()
    if mode == "disabled":
        return trace.NoOpTracer()
    with _lock:
        if _provider is None:
            if mode == "gcp" and (
                os.getenv("DELIVERY_OTEL_CLOUD_ENABLED") != "1"
                or not os.getenv("GOOGLE_CLOUD_PROJECT")
            ):
                raise ValueError("Cloud tracing requires explicit opt-in and a project")
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            endpoint = os.getenv(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://localhost:4318/v1/traces"
            )
            parsed = urlsplit(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Tracing requires an HTTP(S) OTLP endpoint")
            if mode == "jaeger" and parsed.hostname not in {"localhost", "127.0.0.1", "jaeger"}:
                raise ValueError("The free tracing path only exports to local Jaeger")
            ratio = float(
                os.getenv("DELIVERY_OTEL_SAMPLE_RATIO", "1" if mode == "jaeger" else "0.1")
            )
            if not 0 <= ratio <= 1:
                raise ValueError("Trace sample ratio must be between zero and one")
            _provider = TracerProvider(
                resource=Resource.create({"service.name": "madrid-delivery-sim"}),
                sampler=ParentBased(TraceIdRatioBased(ratio)),
                span_limits=SpanLimits(max_attributes=16, max_attribute_length=128, max_events=0),
            )
            _provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=endpoint, timeout=3),
                    max_queue_size=512,
                    max_export_batch_size=64,
                    schedule_delay_millis=1000,
                )
            )
    return _provider.get_tracer("delivery")


def trace_fields() -> dict[str, str]:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return {}
    return {"trace_id": f"{context.trace_id:032x}", "span_id": f"{context.span_id:016x}"}


def traceparent() -> str | None:
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


@contextmanager
def trace_span(
    name: str,
    *,
    parent: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    # An existing parent covers pre-transaction inference plus queue processing.
    context = None
    if parent and not trace.get_current_span().get_span_context().is_valid:
        context = _propagator.extract({"traceparent": parent})
    with tracer().start_as_current_span(
        name,
        context=context,
        kind=kind,
        attributes=attributes,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except Exception as exc:
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute("error.type", type(exc).__name__)
            raise


def traced_event(
    name: str, *, kind: SpanKind = SpanKind.INTERNAL
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Trace a synchronous (agent/self, event, ...) function without payloads."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            event: Any = args[1] if len(args) > 1 else kwargs["event"]
            # Inference replay can operate on a minimal event reference; optional
            # observability must not require fields the underlying call never reads.
            attributes: dict[str, Any] = {}
            for attribute, field in (
                ("delivery.run_id", "run_id"),
                ("messaging.message.id", "id"),
                ("messaging.destination.name", "topic"),
                ("delivery.attempt", "attempts"),
            ):
                value = getattr(event, field, None)
                if value is not None:
                    attributes[attribute] = value if field == "attempts" else str(value)
            with trace_span(
                name,
                parent=getattr(event, "otel_traceparent", None),
                kind=kind,
                attributes=attributes,
            ) as span:
                result = function(*args, **kwargs)
                if result is False:
                    span.set_status(Status(StatusCode.ERROR))
                return result

        return wrapped

    return decorate


def traced_publish[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        conn = args[0] if args else kwargs["conn"]
        with trace_span(
            "queue.publish",
            kind=SpanKind.PRODUCER,
            attributes={
                "delivery.run_id": str(kwargs["run_id"]),
                "messaging.destination.name": str(kwargs["topic"]),
                "delivery.agent": str(kwargs["producer"]),
            },
        ):
            bind_transaction(conn)
            result = function(*args, **kwargs)
        # Restore the consuming span for subsequent SQL tool publications.
        bind_transaction(conn)
        return result

    return wrapped


def bind_transaction(conn: Any) -> None:
    """SQL triggers inherit current context for inserts inside fixed DB tools."""
    parent = traceparent()
    if parent:
        conn.execute("SELECT set_config('delivery.traceparent',%s,true)", (parent,))


def trace_url(trace_id: str) -> str | None:
    if not _TRACE_ID.fullmatch(trace_id) or int(trace_id, 16) == 0:
        return None
    mode = tracing_mode()
    if mode == "gcp":
        project = quote(os.getenv("GOOGLE_CLOUD_PROJECT", ""), safe="")
        return (
            (f"https://console.cloud.google.com/traces/list?project={project}&tid={trace_id}")
            if project
            else None
        )
    if mode == "jaeger":
        return f"http://localhost:16686/trace/{trace_id}"
    return None


def flush_traces() -> None:
    if _provider is not None:
        _provider.force_flush(timeout_millis=3000)

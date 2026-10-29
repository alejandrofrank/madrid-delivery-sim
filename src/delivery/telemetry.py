"""Opt-in, bounded OpenTelemetry export without prompts, arguments or credentials.

The private provider deliberately does not enable ADK's raw content tracing.
Order IDs are namespaced by run; durable W3C parents connect queue redeliveries.
"""

import atexit
import hashlib
import logging
import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from threading import Lock
from typing import Any, ParamSpec, Protocol, TypeVar
from urllib.parse import quote, urlsplit

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
from opentelemetry.trace import Link, Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

P = ParamSpec("P")
T = TypeVar("T")
LOG = logging.getLogger(__name__)
_provider: TracerProvider | None = None
_initialized = False
_owns_redis = False
_lock = Lock()
_root_id: ContextVar[int | None] = ContextVar("delivery_trace_id", default=None)
_identity: ContextVar[dict[str, Any] | None] = ContextVar("delivery_trace_identity", default=None)
_propagator = TraceContextTextMapPropagator()
_ALLOWED_ATTRIBUTES = frozenset(
    {
        "delivery.agent",
        "delivery.tool",
        "delivery.capability",
        "delivery.run_id",
        "delivery.order_id",
        "delivery.event_id",
        "delivery.topic",
        "delivery.attempt",
        "delivery.model_step",
        "delivery.usage_known",
        "delivery.success",
        "delivery.cost_usd",
        "delivery.order.terminal",
        "delivery.order.success",
        "delivery.order.latency_ms",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.request.model",
        "gen_ai.system",
        "http.request.method",
        "http.method",
        "http.route",
        "http.response.status_code",
        "http.status_code",
        "db.system",
        "db.operation",
        "error.type",
    }
)


def enabled() -> bool:
    return (
        os.getenv("MDS_TELEMETRY_ENABLED", "").lower() in {"1", "true", "yes"}
        or _legacy_mode() != "disabled"
    )


def _legacy_mode() -> str:
    mode = os.getenv("DELIVERY_OTEL_EXPORTER", "disabled")
    if mode not in {"disabled", "jaeger", "gcp"}:
        raise ValueError("DELIVERY_OTEL_EXPORTER must be disabled, jaeger or gcp")
    return mode


def _legacy_endpoint() -> str | None:
    mode = _legacy_mode()
    if mode == "disabled":
        return None
    if mode == "gcp" and (
        os.getenv("DELIVERY_OTEL_CLOUD_ENABLED") != "1" or not os.getenv("GOOGLE_CLOUD_PROJECT")
    ):
        raise ValueError("Cloud tracing requires explicit opt-in and a project")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://localhost:4318/v1/traces")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Tracing requires an HTTP(S) OTLP endpoint")
    if mode == "jaeger" and parsed.hostname not in {"localhost", "127.0.0.1", "jaeger"}:
        raise ValueError("The free tracing path only exports to local Jaeger")
    return endpoint


def tracing_mode() -> str:
    legacy = _legacy_mode()
    if legacy != "disabled":
        return legacy
    if not enabled():
        return "disabled"
    if os.getenv("GOOGLE_CLOUD_PROJECT"):
        return "gcp"
    if os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return "otlp"
    return "console"


def trace_url(trace_id: str) -> str | None:
    if not re.fullmatch(r"[0-9a-f]{32}", trace_id) or not int(trace_id, 16):
        return None
    mode = tracing_mode()
    if mode == "gcp":
        project = quote(os.getenv("GOOGLE_CLOUD_PROJECT", ""), safe="")
        return (
            f"https://console.cloud.google.com/traces/list?project={project}&tid={trace_id}"
            if project
            else None
        )
    return f"http://localhost:16686/trace/{trace_id}" if mode == "jaeger" else None


def trace_fields() -> dict[str, str]:
    context = trace.get_current_span().get_span_context()
    return (
        {"trace_id": f"{context.trace_id:032x}", "span_id": f"{context.span_id:016x}"}
        if context.is_valid
        else {}
    )


def tracer() -> trace.Tracer:
    provider = initialize_telemetry()
    return provider.get_tracer("delivery") if provider else trace.NoOpTracer()


def flush_traces() -> None:
    if _provider is not None:
        _provider.force_flush(timeout_millis=5000)


def active() -> bool:
    return enabled() or os.getenv("MDS_BIGQUERY_ENABLED", "").lower() in {"1", "true", "yes"}


class OrderIdGenerator(RandomIdGenerator):
    def generate_trace_id(self) -> int:
        return _root_id.get() or super().generate_trace_id()


def order_trace_id(run_id: Any, order_id: str) -> int:
    digest = hashlib.sha256(f"mds-order-v1:{run_id}:{order_id}".encode()).digest()
    return int.from_bytes(digest[:16], "big") or 1


class SpanSink(Protocol):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult: ...
    def shutdown(self) -> None: ...
    def force_flush(self, timeout_millis: int = 30000) -> bool: ...


class SafeSpanExporter(SpanExporter):
    """Remove auto-instrumentor payloads and exception messages before export."""

    def __init__(self, delegate: SpanSink, *, sample_ratio: float = 1.0) -> None:
        self.delegate = delegate
        self.sample_ratio = sample_ratio

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        safe = []
        for span in spans:
            if span.context and span.context.trace_id / 2**128 >= self.sample_ratio:
                continue
            attributes = {
                key: value
                for key, value in (span.attributes or {}).items()
                if key in _ALLOWED_ATTRIBUTES
            }
            safe.append(
                ReadableSpan(
                    name=span.name,
                    context=span.context,
                    parent=span.parent,
                    resource=span.resource,
                    attributes=attributes,
                    events=(),
                    links=span.links,
                    kind=span.kind,
                    status=Status(span.status.status_code),
                    start_time=span.start_time,
                    end_time=span.end_time,
                    instrumentation_scope=span.instrumentation_scope,
                )
            )
        try:
            if not safe:
                return SpanExportResult.SUCCESS
            return self.delegate.export(safe)
        except Exception:
            LOG.warning("Telemetry export failed", extra={"error_type": "export_failure"})
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)


class BoundedTraceClient:
    """The Google exporter otherwise uses the client's long default retry budget."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def batch_write_spans(self, *, request: Any) -> Any:
        try:
            return self.client.batch_write_spans(request=request, retry=None, timeout=5)
        except Exception as exc:
            # The upstream exporter logs exceptions; never expose the provider message.
            raise RuntimeError(type(exc).__name__) from None

    def close(self) -> None:
        self.client.transport.close()


class ClosingSpanExporter(SpanExporter):
    """Google's exporter shutdown is a no-op; explicitly release its gRPC channel."""

    def __init__(self, delegate: SpanExporter, client: BoundedTraceClient) -> None:
        self.delegate, self.client = delegate, client

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self.delegate.export(spans)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)

    def shutdown(self) -> None:
        try:
            self.delegate.shutdown()
        finally:
            self.client.close()


def create_exporter() -> SpanExporter:
    if endpoint := _legacy_endpoint():
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(endpoint=endpoint, timeout=5)
    if project := os.getenv("GOOGLE_CLOUD_PROJECT"):
        from google.cloud.trace_v2 import TraceServiceClient
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter

        client = BoundedTraceClient(TraceServiceClient())
        return ClosingSpanExporter(
            CloudTraceSpanExporter(project_id=project, client=client),
            client,
        )
    if os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(timeout=5)
    return ConsoleSpanExporter()


def initialize_telemetry() -> TracerProvider | None:
    global _provider, _initialized, _owns_redis
    if not active():
        return None
    _legacy_endpoint()  # Validate legacy explicit cloud approval before fail-open initialization.
    ratio = float(
        os.getenv("DELIVERY_OTEL_SAMPLE_RATIO", "0.1" if _legacy_mode() == "gcp" else "1")
    )
    if not 0 <= ratio <= 1:
        raise ValueError("Trace sample ratio must be between zero and one")
    with _lock:
        if _initialized:
            return _provider
        provider = TracerProvider(
            resource=Resource(
                {"service.name": os.getenv("OTEL_SERVICE_NAME", "madrid-delivery-sim")}
            ),
            id_generator=OrderIdGenerator(),
            shutdown_on_exit=False,
        )
        if enabled():
            try:
                provider.add_span_processor(
                    BatchSpanProcessor(
                        SafeSpanExporter(create_exporter(), sample_ratio=ratio),
                        max_queue_size=2048,
                        max_export_batch_size=256,
                        schedule_delay_millis=1000,
                        export_timeout_millis=5000,
                    )
                )
            except Exception:
                # Observability failure never changes queue or billing semantics.
                LOG.warning("Telemetry exporter unavailable; export disabled")
        from delivery.analytics import analytics_span_exporter

        if exporter := analytics_span_exporter():
            provider.add_span_processor(SimpleSpanProcessor(SafeSpanExporter(exporter)))
        _provider, _initialized = provider, True
        try:
            from opentelemetry.instrumentation.redis import RedisInstrumentor

            redis = RedisInstrumentor()
            if not redis.is_instrumented_by_opentelemetry:
                redis.instrument(tracer_provider=provider)
                _owns_redis = True
        except Exception:
            LOG.warning("Redis telemetry instrumentation unavailable")
        atexit.register(shutdown_telemetry)
        return provider


def instrument_fastapi(app: Any) -> None:
    provider = initialize_telemetry()
    if provider is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def shutdown_telemetry() -> None:
    global _provider, _initialized, _owns_redis
    with _lock:
        provider, _provider = _provider, None
        _initialized = False
    if provider is not None:
        try:
            if _owns_redis:
                from opentelemetry.instrumentation.redis import RedisInstrumentor

                RedisInstrumentor().uninstrument()
                _owns_redis = False
            provider.force_flush(timeout_millis=5000)
            provider.shutdown()
        except Exception:
            LOG.warning("Telemetry shutdown failed")


def current_traceparent() -> str | None:
    if not active():
        return None
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


def traceparent() -> str | None:
    return current_traceparent()


def bind_transaction(conn: Any) -> None:
    if parent := current_traceparent():
        conn.execute("SELECT set_config('delivery.traceparent',%s,true)", (parent,))


def mark_error(span: Span, error: BaseException) -> None:
    span.set_attribute("error.type", type(error).__name__)
    span.set_attribute("delivery.success", False)
    span.set_status(Status(StatusCode.ERROR))


def record_model_usage(span: Span, usage: Any, input_rate: float, output_rate: float) -> None:
    """Missing provider counters remain unknown; incomplete usage never implies free inference."""

    def count(value: Any) -> bool:
        return type(value) is int and value >= 0

    prompt = getattr(usage, "prompt_token_count", None)
    candidates = getattr(usage, "candidates_token_count", None)
    thoughts = getattr(usage, "thoughts_token_count", None)
    output_known = count(candidates) and (thoughts is None or count(thoughts))
    known = count(prompt) and output_known
    span.set_attribute("delivery.usage_known", known)
    if count(prompt):
        assert isinstance(prompt, int)
        span.set_attribute("gen_ai.usage.input_tokens", prompt)
    if output_known:
        assert isinstance(candidates, int)
        output = candidates + (thoughts or 0)
        span.set_attribute("gen_ai.usage.output_tokens", output)
        if known:
            assert isinstance(prompt, int)
            span.set_attribute(
                "delivery.cost_usd", (prompt * input_rate + output * output_rate) / 1_000_000
            )


def start_span(name: str, attributes: Mapping[str, Any]) -> Span:
    """Start a callback-owned span without leaking context across async callbacks."""
    provider = initialize_telemetry()
    if provider is None:
        return trace.INVALID_SPAN
    return provider.get_tracer("delivery").start_span(
        name,
        attributes={**(_identity.get() or {}), **attributes},
    )


@contextmanager
def trace_span(
    name: str,
    *,
    attributes: Mapping[str, Any] | None = None,
    context: Context | None = None,
    parent: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
    links: Sequence[Link] = (),
) -> Iterator[Span]:
    provider = initialize_telemetry()
    if provider is None:
        yield trace.INVALID_SPAN
        return
    if parent and context is None and not trace.get_current_span().get_span_context().is_valid:
        context = _propagator.extract({"traceparent": parent})
    identity = {**(_identity.get() or {}), **(attributes or {})}
    token = _identity.set(identity)
    try:
        with provider.get_tracer("delivery").start_as_current_span(
            name,
            context=context,
            attributes=identity,
            kind=kind,
            links=links,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield span
            except BaseException as exc:
                mark_error(span, exc)
                raise
    finally:
        _identity.reset(token)


@contextmanager
def order_span(
    name: str,
    *,
    run_id: Any,
    order_id: str,
    traceparent: str | None = None,
    attributes: Mapping[str, Any] | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Iterator[Span]:
    expected = order_trace_id(run_id, order_id)
    parent = trace.get_current_span().get_span_context()
    context = None
    links = []
    if parent.trace_id != expected:
        if parent.is_valid:
            links.append(Link(parent))
        extracted = _propagator.extract({"traceparent": traceparent or ""})
        candidate = trace.get_current_span(extracted).get_span_context()
        context = extracted if candidate.is_valid and candidate.trace_id == expected else Context()
    root_token = _root_id.set(expected)
    identity_token = _identity.set({}) if context is not None else None
    try:
        with trace_span(
            name,
            context=context,
            kind=kind,
            links=links,
            attributes={
                "delivery.run_id": str(run_id),
                "delivery.order_id": order_id,
                **(attributes or {}),
            },
        ) as span:
            yield span
    finally:
        _root_id.reset(root_token)
        if identity_token is not None:
            _identity.reset(identity_token)


def traced_event(
    name: str, *, agent: str | None = None, kind: SpanKind = SpanKind.CONSUMER
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            event: Any = kwargs.get("event") or next(
                (arg for arg in args if hasattr(arg, "trace_id") and hasattr(arg, "run_id")), None
            )
            if event is None or not active():
                return function(*args, **kwargs)
            owner = args[0] if args else None
            role = (
                getattr(getattr(owner, "role", None), "name", None)
                or agent
                or getattr(event, "consumer", None)
            )
            with order_span(
                name,
                run_id=event.run_id,
                order_id=event.trace_id,
                traceparent=event.traceparent,
                kind=kind,
                attributes={
                    "delivery.event_id": event.id,
                    "delivery.topic": event.topic,
                    "delivery.attempt": event.attempts,
                    **({"delivery.agent": role} if role else {}),
                },
            ) as span:
                result = function(*args, **kwargs)
                if isinstance(result, bool):
                    span.set_attribute("delivery.success", result)
                    if not result:
                        span.set_status(Status(StatusCode.ERROR))
                return result

        return wrapped

    return decorate


def traced_tool(agent: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            with trace_span(
                "agent.tool",
                attributes={
                    "delivery.agent": agent,
                    "delivery.tool": function.__name__,
                },
            ) as span:
                result = function(*args, **kwargs)
                rejected = isinstance(result, dict) and result.get("ok") is False
                span.set_attribute("delivery.success", not rejected)
                if rejected:
                    span.set_attribute("error.type", "ToolRejected")
                    span.set_status(Status(StatusCode.ERROR))
                return result

        return wrapped

    return decorate

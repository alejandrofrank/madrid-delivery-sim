"""Exporter fakes and durable queue propagation; no Google credentials or network."""

import asyncio
from collections.abc import Iterator
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import Status, StatusCode

from delivery import telemetry
from delivery.db import Connection, connect
from delivery.queue import Event, Queue, publish


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(id_generator=telemetry.OrderIdGenerator(), shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(telemetry.SafeSpanExporter(exporter)))
    monkeypatch.setenv("MDS_TELEMETRY_ENABLED", "true")
    monkeypatch.delenv("MDS_BIGQUERY_ENABLED", raising=False)
    monkeypatch.setattr(telemetry, "_provider", provider)
    monkeypatch.setattr(telemetry, "_initialized", True)
    yield exporter
    provider.shutdown()


def test_disabled_does_not_construct_provider_or_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MDS_TELEMETRY_ENABLED", raising=False)
    monkeypatch.delenv("MDS_BIGQUERY_ENABLED", raising=False)
    create = Mock(side_effect=AssertionError("No client or thread when disabled"))
    monkeypatch.setattr(telemetry, "TracerProvider", create)
    with telemetry.trace_span("disabled") as span:
        assert not span.is_recording()
        assert telemetry.current_traceparent() is None
    assert telemetry.initialize_telemetry() is None
    create.assert_not_called()


def test_selects_cloud_trace_with_bounded_client(monkeypatch: pytest.MonkeyPatch) -> None:
    import google.cloud.trace_v2
    import opentelemetry.exporter.cloud_trace

    client = Mock()
    exporter = Mock()
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "fake-project")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setattr(google.cloud.trace_v2, "TraceServiceClient", lambda: client)
    monkeypatch.setattr(opentelemetry.exporter.cloud_trace, "CloudTraceSpanExporter", exporter)
    selected = telemetry.create_exporter()
    options = exporter.call_args.kwargs
    assert options["project_id"] == "fake-project"
    options["client"].batch_write_spans(request="fake-request")
    client.batch_write_spans.assert_called_once_with(request="fake-request", retry=None, timeout=5)
    selected.shutdown()
    client.transport.close.assert_called_once_with()


def test_cloud_client_redacts_error_before_upstream_logging() -> None:
    client = Mock()
    client.batch_write_spans.side_effect = ValueError("secret-token")
    with pytest.raises(RuntimeError, match="^ValueError$") as error:
        telemetry.BoundedTraceClient(client).batch_write_spans(request={})
    assert error.value.__suppress_context__


def test_otlp_or_console_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    factory = Mock()
    monkeypatch.setattr(trace_exporter, "OTLPSpanExporter", factory)
    assert telemetry.create_exporter() is factory.return_value
    factory.assert_called_once_with(timeout=5)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    assert isinstance(telemetry.create_exporter(), telemetry.ConsoleSpanExporter)


def test_order_trace_continues_across_processes_without_joining_orders(spans) -> None:
    with telemetry.trace_span("request") as request:
        with telemetry.order_span("queue.publish", run_id="run", order_id="order") as root:
            parent = telemetry.current_traceparent()
            root_id = root.get_span_context().trace_id
        with telemetry.order_span("queue.publish", run_id="run", order_id="other") as other:
            assert other.get_span_context().trace_id != root_id
    with telemetry.order_span("queue.process", run_id="run", order_id="order", traceparent=parent):
        with telemetry.trace_span("agent.tool", attributes={"delivery.tool": "confirm_order"}):
            pass
    recorded = spans.get_finished_spans()
    published = next(
        s
        for s in recorded
        if s.name == "queue.publish" and s.attributes["delivery.order_id"] == "order"
    )
    consumed = next(s for s in recorded if s.name == "queue.process")
    tool = next(s for s in recorded if s.name == "agent.tool")
    assert consumed.context.trace_id == published.context.trace_id == root_id
    assert consumed.parent.span_id == published.context.span_id
    assert tool.parent.span_id == consumed.context.span_id
    assert tool.attributes["delivery.run_id"] == "run"
    assert published.links[0].context.span_id == request.get_span_context().span_id
    assert telemetry.order_trace_id("other-run", "order") != root_id


def test_foreign_or_malformed_parent_cannot_merge_order_traces(spans) -> None:
    with telemetry.order_span("foreign", run_id="run", order_id="foreign"):
        foreign = telemetry.current_traceparent()
    for parent in (foreign, "malformed", "00-" + "0" * 32 + "-" + "0" * 16 + "-01"):
        with telemetry.order_span(
            "order", run_id="run", order_id="order", traceparent=parent
        ) as span:
            assert span.get_span_context().trace_id == telemetry.order_trace_id("run", "order")
    assert all(s.parent is None for s in spans.get_finished_spans())


def test_exporter_removes_payloads_exceptions_and_status_descriptions(spans) -> None:
    with pytest.raises(ValueError):
        with telemetry.trace_span(
            "agent.model",
            attributes={
                "delivery.agent": "restaurant",
                "gen_ai.request.model": "offline",
                "gen_ai.usage.input_tokens": 10,
                "delivery.cost_usd": 0.0,
                "gen_ai.prompt": "private complaint",
                "delivery.prompt": "private complaint",
                "db.statement": "redis password",
                "url.full": "https://host/?token=secret",
            },
        ) as span:
            span.add_event("exception", {"exception.message": "secret-token"})
            span.set_status(Status(StatusCode.ERROR, "secret-token"))
            raise ValueError("secret-token")
    saved = spans.get_finished_spans()[0]
    assert saved.events == ()
    assert saved.status.description is None
    assert saved.attributes == {
        "delivery.agent": "restaurant",
        "gen_ai.request.model": "offline",
        "gen_ai.usage.input_tokens": 10,
        "delivery.cost_usd": 0.0,
        "error.type": "ValueError",
        "delivery.success": False,
    }


def test_export_failure_is_best_effort(spans) -> None:
    with telemetry.trace_span("safe"):
        pass
    delegate = Mock()
    delegate.export.side_effect = RuntimeError("secret-token")
    exporter = telemetry.SafeSpanExporter(delegate)
    assert exporter.export(spans.get_finished_spans()) == SpanExportResult.FAILURE


def test_callback_spans_inherit_order_and_do_not_leak_context(spans) -> None:
    with telemetry.order_span("agent", run_id="run", order_id="order") as agent:
        model = telemetry.start_span("agent.model", {"delivery.agent": "restaurant"})
        assert (
            telemetry.current_traceparent().split("-")[2]
            == f"{agent.get_span_context().span_id:016x}"
        )
        model.set_attribute("gen_ai.usage.output_tokens", 12)
        model.end()
    recorded = spans.get_finished_spans()[0]
    assert recorded.attributes["delivery.order_id"] == "order"
    assert recorded.parent.span_id == agent.get_span_context().span_id


def test_fastapi_and_redis_instrumentation_use_private_provider(monkeypatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    exporter = InMemorySpanExporter()
    monkeypatch.setenv("MDS_TELEMETRY_ENABLED", "true")
    monkeypatch.delenv("MDS_BIGQUERY_ENABLED", raising=False)
    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setattr(telemetry, "_initialized", False)
    monkeypatch.setattr(telemetry, "create_exporter", lambda: exporter)
    instrument_redis = Mock()
    monkeypatch.setattr(RedisInstrumentor, "instrument", instrument_redis)
    monkeypatch.setattr(RedisInstrumentor, "uninstrument", Mock())
    app = FastAPI()

    @app.get("/orders/{order_id}")
    def read_order(order_id: str) -> dict[str, str]:
        return {"order_id": order_id}

    telemetry.instrument_fastapi(app)
    provider = telemetry._provider
    assert provider
    instrument_redis.assert_called_once_with(tracer_provider=provider)
    with TestClient(app) as client:
        assert client.get("/orders/one?token=secret").status_code == 200
    provider.force_flush()
    saved = exporter.get_finished_spans()
    assert any(s.attributes.get("http.route") == "/orders/{order_id}" for s in saved)
    assert "secret" not in str([dict(s.attributes) for s in saved])
    telemetry.shutdown_telemetry()


def test_redis_commands_are_redacted_and_reinitialization_uses_new_provider(monkeypatch) -> None:
    import redis
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    monkeypatch.setenv("MDS_TELEMETRY_ENABLED", "true")
    monkeypatch.delenv("MDS_BIGQUERY_ENABLED", raising=False)
    monkeypatch.setattr(telemetry, "_provider", None)
    monkeypatch.setattr(telemetry, "_initialized", False)
    monkeypatch.setattr(telemetry, "_owns_redis", False)
    for _ in range(2):
        exporter = InMemorySpanExporter()
        monkeypatch.setattr(telemetry, "create_exporter", lambda exporter=exporter: exporter)
        provider = telemetry.initialize_telemetry()
        client = redis.Redis(host="not-a-real-host")
        monkeypatch.setattr(client, "_execute_command", lambda *args, **kwargs: b"OK")
        assert client.execute_command("SET", "private-key", "secret") == b"OK"
        provider.force_flush()
        saved = exporter.get_finished_spans()
        assert len(saved) == 1 and saved[0].attributes["db.system"] == "redis"
        assert "secret" not in str(dict(saved[0].attributes))
        assert "private-key" not in saved[0].name
        telemetry.shutdown_telemetry()
        assert not RedisInstrumentor().is_instrumented_by_opentelemetry


def test_adk_rejected_tools_and_model_errors_are_error_spans(spans) -> None:
    from google.adk.models.llm_response import LlmResponse

    from delivery.adk_contracts import restaurant_template
    from delivery.adk_restaurant import RestaurantTurn

    brain, _ = restaurant_template()
    agent = SimpleNamespace(role=SimpleNamespace(name="restaurant", policy="adk", brain=brain))
    turn = RestaurantTurn(agent, None, "test")
    turn.declared_tool_names = frozenset({"finish_decision"})
    with pytest.raises(PermissionError):
        turn.before_tool(SimpleNamespace(name="finish_decision"), {"scope": "secret"}, None)

    @telemetry.traced_tool("restaurant")
    def rejected() -> dict[str, bool]:
        return {"ok": False}

    rejected()
    turn.pending_step = 1
    turn.model_span = telemetry.start_span("agent.model", {"delivery.agent": "restaurant"})
    turn.sql = Mock()
    turn.after_model(None, LlmResponse(error_code="unavailable", error_message="secret"))
    saved = spans.get_finished_spans()
    assert len(saved) == 3
    assert all(s.status.status_code is StatusCode.ERROR for s in saved)
    assert all(s.attributes["delivery.success"] is False for s in saved)
    assert "secret" not in str([dict(s.attributes) for s in saved])


@pytest.mark.parametrize(
    "counts",
    [
        {},
        {"prompt_token_count": 10},
        {"candidates_token_count": 4},
        {"prompt_token_count": -1, "candidates_token_count": 4},
    ],
)
def test_partial_usage_is_not_reported_as_free_inference(spans, counts) -> None:
    with telemetry.trace_span("agent.model") as span:
        telemetry.record_model_usage(span, SimpleNamespace(**counts), 0.1, 0.4)
    attributes = spans.get_finished_spans()[0].attributes
    assert attributes["delivery.usage_known"] is False
    assert "delivery.cost_usd" not in attributes
    assert all(value >= 0 for name, value in attributes.items() if name.startswith("gen_ai.usage"))


def test_model_cost_counts_billable_thought_tokens_once(spans) -> None:
    with telemetry.trace_span("agent.model") as span:
        telemetry.record_model_usage(
            span,
            SimpleNamespace(
                prompt_token_count=100, candidates_token_count=20, thoughts_token_count=5
            ),
            1,
            2,
        )
    attributes = spans.get_finished_spans()[0].attributes
    assert attributes["delivery.usage_known"] is True
    assert attributes["gen_ai.usage.output_tokens"] == 25
    assert attributes["delivery.cost_usd"] == pytest.approx(0.00015)


@pytest.mark.parametrize("fails", [False, True])
def test_adk_customer_model_usage_and_failure_are_traced(spans, fails) -> None:
    from delivery.adk_customer import CustomerAdviceTurn
    from delivery.adk_offline import OfflineCustomerModel
    from delivery.config import Settings

    class BrokenModel(OfflineCustomerModel):
        async def generate_content_async(self, llm_request, stream=False):
            raise RuntimeError("provider-secret")
            yield  # Keep the BaseLlm async generator contract.

    turn = CustomerAdviceTurn(Settings(llm_provider="offline"))
    model = BrokenModel() if fails else OfflineCustomerModel()
    with telemetry.order_span("order", run_id="run", order_id="order"):
        if fails:
            with pytest.raises(RuntimeError, match="provider-secret"):
                asyncio.run(
                    turn.run(model, {"text": "Where is my order?", "order_status": "assigned"})
                )
        else:
            advice, _, cost = asyncio.run(
                turn.run(model, {"text": "Where is my order?", "order_status": "assigned"})
            )
            assert advice.category == "status" and cost == 0
    models = [span for span in spans.get_finished_spans() if span.name == "agent.model"]
    assert len(models) == 1
    saved = models[0]
    assert saved.attributes["delivery.agent"] == "customer_service"
    assert saved.attributes["delivery.order_id"] == "order"
    assert saved.attributes["gen_ai.request.model"] == "offline"
    if fails:
        assert saved.status.status_code is StatusCode.ERROR
        assert "delivery.cost_usd" not in saved.attributes
    else:
        assert saved.attributes["delivery.usage_known"] is True
        assert saved.attributes["gen_ai.usage.input_tokens"] == 0
        assert saved.attributes["delivery.cost_usd"] == 0
    assert "provider-secret" not in str(dict(saved.attributes))


@pytest.mark.integration
def test_queue_context_is_durable_through_sql_children_and_retry(
    db_url: str, run_id: UUID, spans
) -> None:
    with connect(db_url) as conn:
        publish(
            conn,
            run_id=run_id,
            producer="generator",
            topic="order.created",
            payload={"order_id": "one"},
            key="one",
            trace_id="one",
        )
    queue = Queue(db_url)
    first = queue.claim("dispatcher", run_id, 0)
    assert first and first.traceparent

    def handler(conn: Connection, event: Event) -> None:
        # Models SQL capability functions that publish without going through Python.
        conn.execute(
            "INSERT INTO events(run_id,producer,topic,payload,dedupe_key,trace_id,parent_id) "
            "VALUES (%s,'dispatcher','courier.assigned','{}','child','one',%s)",
            (event.run_id, event.id),
        )

    assert queue.process(first, handler)
    child = queue.claim("courier", run_id, 0)
    assert child and child.traceparent and child.traceparent != first.traceparent

    def failed(conn: Connection, event: Event) -> None:
        raise RuntimeError("sensitive provider error")

    assert not queue.process(child, failed)
    with connect(db_url) as conn:
        conn.execute("UPDATE events SET available_at=now() WHERE id=%s", (child.id,))
    retry = queue.claim("courier", run_id, 0)
    assert retry and retry.traceparent == child.traceparent
    assert queue.process(retry, lambda conn, event: None)
    recorded = spans.get_finished_spans()
    assert {s.context.trace_id for s in recorded} == {telemetry.order_trace_id(run_id, "one")}
    assert len([s for s in recorded if s.name == "queue.process"]) == 3
    assert "sensitive" not in str(recorded)

    # A clock/world producer continues a stored parent after the consumer has exited.
    with connect(db_url) as conn:
        publish(
            conn,
            run_id=run_id,
            producer="courier",
            topic="order.delivered",
            payload={},
            key="world",
            trace_id="one",
            parent_id=child.id,
        )
        parent = conn.execute("SELECT traceparent FROM events WHERE id=%s", (child.id,)).fetchone()
    world = spans.get_finished_spans()[-1]
    assert world.name == "queue.publish"
    assert world.parent.span_id == int(parent["traceparent"].split("-")[2], 16)


@pytest.mark.integration
def test_real_offline_adk_exports_tools_usage_and_scoped_parent(db_url: str, spans) -> None:
    from delivery.adk_contracts import restaurant_template
    from delivery.agent_access import retire_inventory_access
    from delivery.supply import new_supply, provision, release_calls
    from delivery.supply_models import AgentDefinition, SupplyConfig, default_config

    base = default_config()
    brain, soul = restaurant_template()
    definition_data = base.agents["restaurant"].model_dump()
    definition_data["limits"]["tool_calls_per_event"] = 16
    definition = AgentDefinition.model_validate({**definition_data, "brain": brain, "soul": soul})
    data = base.model_dump(mode="json")
    home = next(entity for entity in data["entities"] if entity["kind"] == "household")
    home.update(node=0, recipe_ids=["pizza"])
    data["entities"] = [home] + [
        entity
        for entity in data["entities"]
        if entity["id"] == "restaurant-pizza" or entity["kind"] == "market"
    ]
    for entity in data["entities"]:
        if entity["kind"] == "restaurant":
            entity["agent"] = definition.model_dump(mode="json")
            entity["node"] = 1
    data.update(
        playback_seconds=0,
        calls_per_household=1,
        restaurant_stock_servings=3,
        start_hour=12,
        duration_minutes=15,
    )
    config = SupplyConfig.model_validate(data)
    run = new_supply(config, db_url)
    try:
        agents = provision(run, db_url)
        with connect(db_url) as conn:
            schedule = conn.execute(
                "SELECT config->'schedule' AS s FROM supply_sessions WHERE run_id=%s", (run,)
            ).fetchone()["s"]
            conn.execute("UPDATE runs SET sim_time=900 WHERE id=%s", (run,))
        release_calls(run, schedule, 900, db_url)
        incoming = None
        for agent in agents.values():
            if agent.role.name == "household" and (event := agent.claim()):
                incoming = event
                assert agent.process(event)
        with connect(db_url) as conn:
            conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run,))
        worked = False
        for agent in agents.values():
            if agent.role.name == "restaurant" and (event := agent.claim()):
                assert event.traceparent
                assert incoming
                with connect(agent.dsn) as conn:
                    rejected = conn.execute(
                        "SELECT public.agent_trace_context(%s,%s,%s,%s) AS ok",
                        (incoming.id, incoming.token, incoming.attempts, event.traceparent),
                    ).fetchone()
                    assert rejected["ok"] is False  # Foreign target store is never mutable.
                assert agent.process(event)
                with connect(agent.dsn) as conn:
                    rejected = conn.execute(
                        "SELECT public.agent_trace_context(%s,%s,%s,%s) AS ok",
                        (event.id, event.token, event.attempts, event.traceparent),
                    ).fetchone()
                    assert rejected["ok"] is False  # An ACKed lease cannot mutate context.
                worked = True
                break
        assert worked
        recorded = spans.get_finished_spans()
        models = [s for s in recorded if s.name == "agent.model"]
        tools = [
            s
            for s in recorded
            if s.name == "agent.tool" and s.attributes.get("delivery.agent") == "restaurant"
        ]
        assert models and tools
        assert all(s.attributes.get("gen_ai.request.model") == "offline" for s in models)
        assert all(s.attributes.get("delivery.cost_usd") == 0 for s in models)
        assert all(s.attributes.get("gen_ai.usage.input_tokens") == 0 for s in models)
        assert any(s.attributes["delivery.tool"] == "finish_decision" for s in tools)
        assert {s.context.trace_id for s in models + tools} == {
            telemetry.order_trace_id(run, event.trace_id)
        }
        assert "contents" not in str([dict(s.attributes) for s in recorded])
    finally:
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            for table in ("supply_requests", "supply_sessions", "decisions", "events"):
                conn.execute(f"DELETE FROM {table} WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))


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
    assert span.attributes == {"error.type": "RuntimeError", "delivery.success": False}
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

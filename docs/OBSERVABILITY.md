# Queue and agent tracing

OpenTelemetry follows a message from publication through the worker, fixed tools,
inference preparation, database effects and downstream publications. Tracing is
disabled by default. It does not enable model calls or alter model budgets.

## Free local Jaeger

```bash
docker compose -f compose.yaml -f compose.tracing.yaml up -d --build --wait
docker compose -f compose.yaml -f compose.tracing.yaml exec -T app delivery init
```

Run a simulation or restaurant scenario, then open `/agent-traces` in the app.
The recent trace table links 32-character OTel IDs to
[Jaeger](http://localhost:16686). The collector uses transient memory; restarting
it clears its traces. PostgreSQL evidence remains. Only Jaeger's UI is exposed,
bound to loopback; OTLP ingestion stays on the Compose network.

For local Python processes, use `DELIVERY_OTEL_EXPORTER=jaeger` and an OTLP HTTP
endpoint at `http://localhost:4318/v1/traces` on a separately running Jaeger.
The Compose collector intentionally does not publish its ingestion port.

## Optional Google Cloud Trace

The application exports OTLP to the Google-built collector, which authenticates
with ADC and sends traces to the Google Telemetry API. No cloud trace exporter
starts unless both the `gcp` mode and explicit opt-in flag are configured.

The exporting identity needs `roles/telemetry.tracesWriter` on the destination
project and `roles/serviceusage.serviceUsageConsumer` on its ADC quota project.
Enable the Telemetry and Cloud Trace APIs if organization policy disabled them.
Use a dedicated runtime service account on GCP; no service-account key is needed.
`infra/gcp-ai/telemetry.tf` provisions those APIs and a trace-only exporter identity
when `enable_telemetry=true`; it defaults to false and deploys no collector.
The `telemetry_service_account` output identifies the service account. Use it as
the GCP collector runtime identity, or obtain impersonated ADC for an authorized
local principal listed in `invoker_members`:

```bash
gcloud auth application-default login --impersonate-service-account=TRACE_EXPORTER_EMAIL
```

```bash
export GOOGLE_CLOUD_PROJECT=your-project
export GCP_ADC_DIRECTORY="$HOME/.config/gcloud"
export DELIVERY_OTEL_CLOUD_ENABLED=1
docker compose -f compose.yaml -f compose.tracing-gcp.yaml up -d --build --wait
docker compose -f compose.yaml -f compose.tracing-gcp.yaml exec -T app delivery init
```

This is an explicit cloud export operation and may incur observability charges.
It is separate from the inference cost ledger in `cloud_ai.py`. Cloud tracing
defaults to a 10% root trace sample rate; local Jaeger records all traces.
`DELIVERY_OTEL_SAMPLE_RATIO` accepts values from 0 to 1. Parent sampling decisions
carry across the queue. A trace link may point to a sampled-out or expired trace.

For a GCP-hosted application, use `config/otel-collector-gcp.yaml` in a collector
sidecar and set the application's `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to
`http://localhost:4318/v1/traces`. The runtime identity supplies ADC. The supplied
Compose cloud override is a local opt-in demonstration, not a deployed service.

## Evidence and boundaries

- `events.trace_id` remains the business correlation ID. Migration 026 adds the
  separate `otel_traceparent` W3C envelope. The transactional insert trigger also
  covers events emitted by fixed database tools, without modifying event payloads.
- Retries retain the incoming trace context and record a new attempt span. Queue
  failures produce error status without persisting exception messages to traces.
- Decision receipts include `detail.telemetry.trace_id` and `span_id` while a
  valid span exists. `/api/telemetry/traces` returns up to 30 recent event traces.
- Spans contain run/event IDs, topic, tool or agent name, attempt and error type.
  They exclude prompts, model responses, event bodies, SQL, tokens and exception
  strings. A dedicated provider avoids automatically exporting third-party ADK
  spans that may contain model input or output.
- Export uses a bounded 512-span queue, batches of 64, a three-second timeout,
  and limited attributes. Collector outages can drop spans; PostgreSQL remains
  the authoritative transaction and audit record. Graceful process exit flushes
  the provider; abrupt crash injection can lose its final spans.

## Verification

```bash
docker compose run --rm --no-deps app pytest -q tests/test_telemetry.py
```

Tests use the SDK's in-memory exporter. They verify disabled/cloud opt-in behavior,
context propagation through publication and consumption, retry continuity, safe
links and redaction. They never contact a collector or paid service.

API and collector configuration were checked against current first-party docs:
[Cloud Trace Python instrumentation](https://docs.cloud.google.com/trace/docs/setup/python-ot),
[Google-built collector on Cloud Run](https://docs.cloud.google.com/stackdriver/docs/instrumentation/opentelemetry-collector-cloud-run),
and [Jaeger 2.22](https://www.jaegertracing.io/docs/2.22/getting-started/).

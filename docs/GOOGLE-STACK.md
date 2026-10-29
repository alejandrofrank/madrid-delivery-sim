# Google stack: demonstrate a decision and its evidence

This portfolio slice connects Google ADK, A2A, OpenTelemetry, and BigQuery to a
working delivery simulator. The core demonstration is free: PostgreSQL owns
state, queue leases, permissions, memory and budgets; scripted ADK models exercise
the real Runner; Jaeger inspects local traces. Cloud features remain separately
enabled and no paid provider is invoked in CI.

## A short technical demonstration

1. Start with `make setup` and open `/architecture`, `/agent-traces`, and `/health`.
2. Run `make demo-adk` to compare scripted restaurant behaviors with stored tool,
   outcome and usage evidence. The fixture measures contract compliance, not LLM quality.
3. Discover both [A2A agents](A2A.md). Call an existing order or complaint with
   the official client and inspect its durable event, outcome, and replay.
4. Enable [local tracing](OBSERVABILITY.md), repeat a run, and follow a trace from
   the queue producer through an agent and its tools into downstream work.
5. [Prepare a BigQuery bundle](GOOGLE-ANALYTICS.md) from the receipt. Inspect the
   allowlisted rows and SQL dashboard view without contacting Google Cloud.

This shows how a customer-facing engineer can move from a business failure
(late delivery, stock contention, courier dropout) to a bounded agent action,
an auditable result, and an operational metric.

## Google ADK customer service

The [customer adapter](../src/delivery/adk_customer.py) replaces the former direct
GenAI call with `LlmAgent`, `Runner`, and `InMemorySessionService`. It uses a strict
Advice schema, no tools or transfers, one model call, no automatic provider
retries, and a bound on the complete serialized request. The existing
[service](../src/delivery/customer_service.py) still admits work through a durable
reservation before invoking the model, reuses cached results, and falls back to
operator review after an error, exhausted budget, or disabled provider.

`LLM_PROVIDER=offline` selects the scripted customer model, which records zero
dollars but still consumes the existing call/token allowance. `disabled` remains
the default outside the explicit local A2A demonstration. Paid `gemini` and
`vertex` modes retain the original call, token and dollar ceilings. The fixed
refund policy remains outside the model; the offline source cannot authorize a
refund. Unknown usage after a provider error retains its full reservation; zero
recorded tokens in an error receipt does not prove zero provider spend.

The [customer tests](../tests/test_adk_customer.py) cover the real offline Runner,
input/schema bounds, one-call enforcement, provider configuration, durable
reservation and replay. [Original safety tests](../tests/test_safety.py) continue
to verify injection handling, the refund gate and concurrent budget admission.

## Interfaces, operations and limits

| Capability | Working path | Cloud boundary |
| --- | --- | --- |
| ADK restaurant + customer | Real Runner, scripted model, scoped tools or structured Advice | Explicit Vertex/Gemini configuration; existing budget gates |
| A2A | Two 1.0 JSON-RPC servers, cards and real SDK client | Loopback demonstration; external tenant authentication is not implemented |
| OpenTelemetry | W3C queue propagation and local Jaeger, linked from trace inspector | Explicit collector export, trace-only service account, sampling |
| BigQuery | Local NDJSON receipts/KPIs, frozen manifest, mocked upload tests | Opt-in dataset/tables/view, bounded batch loads, scoped service account |
| Looker Studio | Dashboard-ready BigQuery SQL view and field guide | Connecting a live dashboard is an operator step; query charges are separate |

Existing inference cost caps in [cloud_ai.py](../src/delivery/cloud_ai.py) are
unchanged. Cloud Trace ingestion, BigQuery storage and dashboard queries have
separate service pricing; none are enabled by `make setup`. Infrastructure and
upload tests use mocks, never a live GCP project. Google Maps ETA comparison and
managed Agent Engine deployment remain optional future extensions.

The [public-readiness review](PUBLIC-READINESS.md) records ignored secret/state
files and the history scan. GitHub visibility remains private. The GIF in the
README is explicitly a placeholder, not claimed footage.

## Reproduce the checks

```bash
make setup
make check
make test
make eval-agents
docker compose exec -T app pytest -q tests/test_a2a_server.py tests/test_adk_customer.py tests/test_telemetry.py tests/test_bigquery_export.py
python3 scripts/check_documentation.py
```

Run suites using the shared `delivery_test` database sequentially; concurrent
suites can invalidate fixture-cleanup assertions. Terraform checks use an
isolated working directory, a mocked provider, and Terraform 1.14 or newer
(which handles protected resources during mock-test teardown). See each feature
guide for exact cloud opt-in and parking commands. No live Cloud Trace or
BigQuery deployment is claimed by these local checks.

Official API documentation checked on 2026-10-29:

- [ADK agents](https://adk.dev/agents/llm-agents/), [Gemini models](https://adk.dev/agents/models/google-gemini/), and [RunConfig](https://adk.dev/runtime/runconfig/).
- [A2A Python SDK](https://a2aproject.github.io/a2a-python/) and [server routes](https://a2a-protocol.org/latest/tutorials/python/5-start-server/).
- [Cloud Trace Python/OTel](https://docs.cloud.google.com/trace/docs/setup/python-ot).
- [BigQuery local-file loads](https://docs.cloud.google.com/bigquery/docs/samples/bigquery-load-from-file) and [IAM permissions](https://docs.cloud.google.com/bigquery/docs/access-control).

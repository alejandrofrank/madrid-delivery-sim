# Local agent foundation and optional GCP portability

Original design: 2026-10-23; implementation clarifications: 2026-10-28. Default city
development remains local, without provider calls or cloud credentials. The optional
Cloud Run/Vertex recovery judge has since been implemented and live-verified;
Google ADK and a fully cloud-hosted business runtime remain proposed adapters.
Use [the exact implementation](AGENT-IMPLEMENTATION.md),
[current GCP inventory](GCP-COMPONENTS.md) and
[enterprise decisions](ENTERPRISE-GCP.md) for the current source-reviewed contract.

The inventory implementation is now available: see [implemented foundation](AGENT-FOUNDATION.md)
for actual modules, permissions, budgets and verification. The proposed ADK-specific
shape and example contract below remain future design, not the executable role schema.

## What an agent is in this project

An agent is a versioned identity with a goal, a bounded decision loop, observations,
permitted actions and durable accountability. Its lifecycle is:

claim event -> verify authenticated scope -> commit durable attempt/tool allowance
-> prepare/invoke/save outside effects transaction if enabled -> begin fenced effects transaction -> load
permitted facts/memory -> decide and execute permitted tools -> record outcome,
memory and outgoing events -> commit those effects and ACK atomically.

A prompt or SOUL.md supplies behavioral guidance. It does not provide security,
durability, memory isolation, approvals or cost enforcement. A deterministic policy
and an ADK reasoning policy should both fit the same event and tool contracts, so
the experiment can measure whether model judgment helps.

## Researched Google options (not a deployment choice)

| Option | Documented capability | Project judgment |
| --- | --- | --- |
| ADK on Cloud Run | Open-source agent framework with local and cloud deployment. Cloud Run has services for request-driven work, worker pools for continuous queue consumers and jobs for finite tasks. | Deferred portability candidate after local acceptance. Research suggests explicit control over our queue contract and a shared image; jobs, worker pools and services are possible future adapters, not current implementation requirements. |
| Managed Agent Runtime | Managed agent deployment, scaling, security and framework integration. Current docs place it under Gemini Enterprise Agent Platform; ReasoningEngine remains an API resource name for compatibility. | Keep as a deployment adapter option when managed operations justify it. It does not replace business transactions, queue semantics or our scoped memory experiment. |
| Managed Agents API | Config-driven autonomous agents in sandbox environments; launch stage and data-handling terms need review for the chosen feature/version. | Evaluate only on synthetic fixtures first; private Bakiano exports are outside the current approved model data contract. |
| ADK Agent Config | Version-sensitive configuration-based role/workflow assembly. | Preserve our small validated role contract and use a future adapter over tested, pinned ADK APIs; framework configuration is not the durable authorization contract. |

Sources: [ADK overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk),
[Cloud Run resource choices](https://docs.cloud.google.com/run/docs/ai-agents),
[Agent Runtime](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime),
[Managed Agents API and restrictions](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents),
[experimental Agent Config](https://adk.dev/agents/config/).

These links preserve research, not a selected deployment or a dependency of the local
lab. Benchmark the same role/tools against a rules-only baseline locally.
Pin a tested ADK/SDK version and model version in implementation; do not use a moving
latest alias in scored runs. Verify regional availability, quotas and pricing before
deploying. No cloud resources or paid model calls were created by this research.

## Reuse the implementation, specialize the role

Proposed repository shape:

```text
agent_runtime/
  factory.py          # role config -> deterministic or ADK decision policy
  worker.py           # queue lease, deadline, bounded loop, commit/ACK
  context.py          # authoritative reads, redaction, scoped memory retrieval
  tools.py            # fixed tool registry and schema validation
  budgets.py          # durable reservation before inference/tool expense
  telemetry.py        # event/decision/model/tool spans and sanitized records
  transports/         # Postgres first; cloud notification adapter later
config/agents/
  inventory/role.json
  inventory/SOUL.md
  dispatcher/role.json
  dispatcher/SOUL.md
  director/role.json
  director/SOUL.md
config/topologies/    # reporting/approval routes, separate from role behavior
```

These proposed paths describe a future reasoning adapter layout. The implemented
inventory foundation uses `src/delivery/agent_runtime.py`, `agent_access.py` and
`agent_specs.py`, plus the inventory role/soul paths shown above.
Build and validate one shared factory locally, with deterministic policies and scripted
model adapters. ADK is optional behind these contracts; default demos make no provider
calls. ADK packaging and cloud business-worker hosting remain proposed; the bounded
Cloud Run/Vertex judge and its standalone Terraform root are already implemented.
Copy a role configuration and soul file, not the worker implementation. Instantiate
inventory roles with store-specific scope. Configuration is developer-controlled,
immutable during a run, validated at startup and hashed into every decision record.
Event payloads cannot choose a new soul, tools, identity or broader scope.

Example project role contract (illustrative, not directly executable ADK config):

```json
{
  "schema_version": 1,
  "role": "inventory",
  "version": "1",
  "soul": "SOUL.md",
  "objective": "Report stock truthfully and propose feasible replenishment",
  "decision_policy": "rules-first-adk-on-exception",
  "scope": {"store_ids": ["store-1"]},
  "accepts": ["basket.requested", "availability.requested", "stock.shortage"],
  "emits": ["inventory.decided", "replenishment.proposed", "approval.requested"],
  "tools": ["inventory.read", "inventory.reserve", "replenishment.propose"],
  "memory": {"namespace": "run/role/store", "retention": "scenario-defined"},
  "model_policy": "budgeted-exception-model-v1",
  "limits": {"model_calls_per_event": 1, "tool_steps_per_event": 6},
  "budget_policy": "inventory-run-budget-v1",
  "output_schema": "inventory-decision-v1",
  "deadline_policy": "inventory-deadlines-v1",
  "escalation_route": "topology.inventory.supervisor"
}
```

Budget/model/deadline references resolve to trusted versioned policies with numeric
caps. The tool list is intersected with server-side policy for the authenticated
principal; editing JSON cannot grant new authority. In a future reasoning adapter,
trusted SOUL text can guide model decisions within that authority. Current local
policies do not interpret SOUL, and the GCP gateway uses its own fixed prompt rather
than the local role SOUL. Neither can raise budgets or remove approval requirements.

Example inventory soul:

> Protect stock accuracy and explain uncertainty. Read authoritative availability
> before making a promise. Separate confirmed units from expected receipts. Prefer
> deterministic tools for stock arithmetic. Propose alternatives only within verified
> compatibility and customer consent. Escalate requests outside your store or authority.

## Local sample data

Target ten daily Bakiano sample dates: 2026-10-14 through 2026-10-23 inclusive.
October 13 through October 23 inclusive would be eleven dates. Keep dated snapshots
local, with source identity, actual observation timestamps, provenance and hashes.
Only label a date observed when authentic source data establishes it; list missing
days explicitly. Never invent historical prices or relabel a current observation as
a past one. Synthetic fallback rows must be clearly marked and cannot fill an
observed-history claim.

## Isolation and data leakage

- Share the container image across roles, but deploy different authority boundaries
  with different workload identities, database roles and tool permissions. Two ADK
  objects in one process do not establish IAM isolation.
- Resolve store/run scope from trusted deployment configuration and authenticated
  tool context. Do not trust a store ID supplied by the model as authorization.
- Give agents narrow projections of catalogue and order facts, not the full Bakiano
  checkout, warehouse account, source credentials or another role's transcript.
- Keep provider credentials in workload identity/secret facilities, never prompts,
  memory documents, event payloads or traces. Avoid downloaded long-lived service
  account keys. Review granted identity defaults rather than assuming no access.
- Separate transient reasoning context, scoped episodes and canonical state. Filter
  memory access before retrieval, not by asking the model to ignore unauthorized hits.
- Treat complaints, product text and retrieved episodes as untrusted data. Enforce
  allowed actions in tools; record injection rejection without propagating secrets.

Google's managed Agent Identity is associated with the deployed runtime resource;
arbitrary role names within one deployment do not automatically get distinct
identities. Agent Gateway provides governance over approved destinations and tools.
These complement, rather than replace, store-level business authorization.
Sources: [Agent Identity](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity),
[Agent Gateway](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview).

## Queues, state and execution boundaries

Keep Postgres as the authoritative business store and durable event queue initially.
GCP can host it in Cloud SQL, subject to deployment/extension checks. The local Docker
backend remains the offline reference. Current memory uses typed facts and exact
SQL filters. Any future pgvector adapter must be a separately evaluated scoped
memory mode so comparisons do not silently switch memory systems.

For persistent workers, Cloud Run worker pools can consume the existing queue. For
finite experiments, a run-to-completion job can drive the simulation. Do not move
the current API background-task controller unchanged onto a request-billed service.
Durable controller ownership/checkpoints and restart recovery must precede claims
of cloud fault tolerance.

If adopting Pub/Sub later, select and document one transport contract. An outbox
relay may send durable wakeups while Postgres retains priority, simulated due-time
and idempotency semantics. If Pub/Sub becomes the actual transport, add a transactional
inbox/outbox and explicitly reimplement/test these semantics. Do not claim Pub/Sub
natively provides our priority queue or simulation clock.

All role-to-role cooperation stays queued. Do not wire ADK AgentTool, direct agent
transfer, shared conversational state or A2A calls around this ledger. A supervisor
requests another role's work with a correlated event; the result is another event.

ADK trigger endpoints can process Pub/Sub/Eventarc requests, but redelivery creates
another session and default in-memory sessions are ephemeral. Deduplicate with the
business event ID, not an ADK session ID. Pub/Sub exactly-once is regional and pull-only;
it does not establish exactly-once business effects or external model billing.
Sources: [ambient agents](https://adk.dev/runtime/ambient-agents/),
[Pub/Sub delivery guarantees](https://docs.cloud.google.com/pubsub/docs/exactly-once-delivery).

Implemented for the optional judge: model calls run outside worker database
connections. A fenced request snapshots scoped facts, local proposal, recall and
identity. Before dispatch, current context/time/recall and remaining tool slots
are checked; a single-dispatch marker and call/token allowance commit first.
Structured results are saved separately. A fresh effects transaction revalidates
the snapshot before applying domain effects, memory, outgoing events and ACK
atomically. Reclaimed events reuse saved results without another call. An uncertain
dispatch fails closed rather than automatically spending again. Legacy calls
without a compatible durable snapshot are also denied without resend.
See [durable inference](DURABLE-INFERENCE.md). Gateway-wide monetary admission,
supervisor recovery and distributed tracing remain enterprise follow-up work.

## Next implementation gate

Before adding more reasoning roles:

1. Implemented for eight role kinds: strict schema, fixed tools and shared factory;
   deterministic policies are the default and the optional GCP judge is bounded.
2. Real non-superuser tests exercise store/run/role/order/request/attempt isolation;
   twelve local role scenarios now have explicit scores and repeated receipts.
3. Add an ADK reasoning adapter only behind the tested event/tool contracts; keep
   routine city development independent of cloud deployments and inference.
4. Extend adversarial tests for every new model/tool integration; prompts cannot
   grant tools, memory, spending or approval authority, and cooperation stays queued.
5. Replace the in-process controller with durable ownership and checkpoints. Kill
   controller and worker separately and demonstrate local recovery from both.
6. Preserve sample provenance, explicit missing days and the local baseline while
   separately evaluating any paid cloud decision or proposed hosting change.

## Deferred ADK and cloud-worker adapters

The existing standalone Terraform root, keyless Cloud Run judge and start/status/
stop commands are implemented; they do not host the city, business workers or
memory in GCP. ADK, managed agent hosting, cloud business storage and broader
governance remain separate proposed changes. Preserve the shared contracts and
prove reliability/cost gates before adopting them. No deployment or provider call
is required by routine local development or by this documentation review.

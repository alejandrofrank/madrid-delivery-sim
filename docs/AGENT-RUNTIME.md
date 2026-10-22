# Agent foundation and GCP deployment decision

Research date: 2026-10-23. Proposed architecture, not a deployed GCP implementation.
The M2 inventory slice remains a deterministic local worker. This decision is a
prerequisite before multiplying reasoning roles or adding cloud infrastructure.

## What an agent is in this project

An agent is a versioned identity with a goal, a bounded decision loop, observations,
permitted actions and durable accountability. Its lifecycle is:

receive event -> verify identity/schema/scope -> load permitted facts -> reserve
budget -> decide -> validate proposal -> execute permitted tools -> commit effects
and outgoing events -> acknowledge -> record outcome.

A prompt or SOUL.md supplies behavioral guidance. It does not provide security,
durability, memory isolation, approvals or cost enforcement. A deterministic policy
and an ADK reasoning policy should both fit the same event and tool contracts, so
the experiment can measure whether model judgment helps.

## Current Google options and choice

| Option | Documented capability | Project judgment |
| --- | --- | --- |
| ADK on Cloud Run | Open-source agent framework with local and cloud deployment. Cloud Run has services for request-driven work, worker pools for continuous queue consumers and jobs for finite tasks. | Preferred foundation: explicit control over our queue contract, portable offline execution and one shared container image. Use jobs for finite demos/evaluation; choose worker pools for persistent pull consumers or authenticated services for bounded event requests. |
| Managed Agent Runtime | Managed agent deployment, scaling, security and framework integration. Current docs place it under Gemini Enterprise Agent Platform; ReasoningEngine remains an API resource name for compatibility. | Keep as a deployment adapter option when managed operations justify it. It does not replace business transactions, queue semantics or our scoped memory experiment. |
| Managed Agents API | Config-driven autonomous agents in sandbox environments; currently Preview with restrictions on confidential data and production use. | Evaluate only on synthetic fixtures if useful. Do not send private Bakiano exports there under the current documented restrictions. |
| ADK Agent Config | YAML-based role/workflow assembly; currently documented as experimental. | Use our own small validated role contract and a Python factory over pinned ADK APIs. Do not make experimental YAML semantics our durable application or authorization contract. |

Sources: [ADK overview](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/adk),
[Cloud Run resource choices](https://docs.cloud.google.com/run/docs/ai-agents),
[Agent Runtime](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime),
[Managed Agents API and restrictions](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/managed-agents),
[experimental Agent Config](https://adk.dev/agents/config/).

This is a fit-for-purpose recommendation, not a claim that one framework is universally
state of the art. Benchmark the same role/tools against a rules-only baseline.
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

These paths describe the intended building block; they are not yet implemented.
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
principal; editing JSON cannot grant new authority. Soul text may change tone,
priorities and decision guidance within that authority. It cannot raise the budget
or remove approval requirements.

Example inventory soul:

> Protect stock accuracy and explain uncertainty. Read authoritative availability
> before making a promise. Separate confirmed units from expected receipts. Prefer
> deterministic tools for stock arithmetic. Propose alternatives only within verified
> compatibility and customer consent. Escalate requests outside your store or authority.

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
backend remains the offline reference. pgvector episodes remain a separate scoped
memory feature so comparisons do not silently switch memory systems.

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

Model calls run outside long stock transactions: reserve budget durably, create an
invocation record, retrieve only scoped facts, invoke with bounded retries, validate
structured output, recheck state versions, then apply domain effects and publish
results atomically. Cache completed invocations. An ambiguous paid request must not
automatically spend again after a crash. A stale proposal must revalidate or escalate.

## Next implementation gate

Before adding more reasoning roles:

1. Build a strict role schema, fixed tool registry and factory with no-LLM default.
2. Run the existing inventory slice through that shared worker without changing its
   outcomes; add two store scopes and prove cross-store denial outside prompts.
3. Add a pinned ADK adapter with scripted/fake-model tests, then one explicitly
   budgeted real-provider smoke test when deploying the cloud path.
4. Test prompt changes cannot grant tools, memory access, spending or approvals;
   test direct handoff is unavailable and all messages retain lineage.
5. Replace the in-process controller with durable ownership and checkpoints. Kill
   controller and worker separately and demonstrate recovery from both.
6. Prepare GCP infrastructure as code with one image and role-specific deployments,
   identities, database access, secrets, trace configuration and resource caps.
7. Verify a small synthetic cloud run, record actual costs, then enable only the
   minimum Bakiano projections required by approved role scopes.

The initial cloud deployment should be a bounded smoke experiment, not an always-on
fleet by default. Infrastructure caps and billing alerts supplement application
budgets; they are not hard per-agent model-spend enforcement.

# Architecture decisions

These records explain the implemented choices reviewed on **2026-10-28** and
when to reconsider them. The local environment supplies reproducible engineering
evidence; it does not establish production scale or superiority over another
agent architecture. [Enterprise GCP](ENTERPRISE-GCP.md) expands the proposed
deployment and governance work.

## 1. Keep the queue and business effects in PostgreSQL

**Choice.** Use addressed events, leases, fencing, priorities, retries and dead
letters beside the domain tables. The worker commits state, memory, decision,
outgoing events and ACK in one effects transaction. Attempt/model reservations
commit separately and survive failure.

**Alternative.** Introduce a message broker as the authoritative work transport.
**Why.** A stock change and its handoff can share a database transaction; a crash
cannot commit consumption while losing its next event. **Trade-off.** Locks and
database capacity constrain execution. Cloud inference now releases its connection
between durable preparation and saved-result application; an uncertain dispatch
fails closed rather than being resent. **Revisit when** measured queue load or independent
consumers justify a broker. Use an outbox/inbox design and failure tests; a broker
does not make external billing exactly once.

Sources: [queue](../src/delivery/queue.py), [runtime](../src/delivery/agent_runtime.py),
[queue boundary tests](../tests/test_agent_queue_boundary.py),
[durable request/result protocol](DURABLE-INFERENCE.md).

## 2. Use rules first, with an optional bounded recovery judge

**Choice.** Fixed policies handle inventory, sourcing, consent, routes and custody.
An explicitly enabled GCP judge may veto a locally computed retry candidate.
**Alternative.** Delegate planning and tool choice to an LLM for every role.
**Why.** Exact stock arithmetic and physical feasibility have executable answers;
default runs remain reproducible without paid inference. **Trade-off.** Fixed
policies cannot interpret an unfamiliar instruction or invent a sourcing strategy.
The model's additional business value remains unmeasured. **Revisit when** an
ambiguous task has an approved evidence contract and a held-out comparison shows
better outcomes within quality, latency and cost gates.

Sources: [supply policy](../src/delivery/supply_policy.py),
[fleet policy](../src/delivery/fleet_policy.py),
[veto/failure tests](../tests/test_cloud_runtime.py).

## 3. Enforce scope outside prompts

**Choice.** Bind each worker's run, namespace and role to its PostgreSQL login;
enforce domain operations through RLS, narrow functions, live leases and budgets.
**Alternative.** Give a shared privileged connection to agents and ask them to
respect their prompt's store/order boundaries. **Why.** Model content, recalled
text and display names cannot grant authority. **Trade-off.** Provisioning and
schema migrations carry complexity. Trusted controller, host and fixed Python
remain outside this boundary; one process holding several connections is not an
OS sandbox. **Revisit when** moving to independently deployed or tenant-facing
workers: add workload identity, process isolation and negative authorization tests.

Sources: [access provisioning](../src/delivery/agent_access.py),
[server-owned authority](../src/delivery/agent_specs.py),
[isolation tests](../tests/test_agent_runtime.py).

## 4. Start with typed memory and explicit sharing

**Choice.** Store versioned observations with server-derived provenance, expiry
and role/order/request/attempt filters. Share approved canonical facts in queued
briefs rather than opening another agent's private memory. **Alternative.** Put
all conversations into shared vector recall by default. **Why.** The current task
needs exact context and auditable stale-fact behavior, not semantic similarity.
**Trade-off.** No cross-order learning, automatic consolidation or semantic recall
exists. TTL controls recall eligibility, not audit deletion. **Revisit when** a
held-out retrieval task demonstrates a gap; compare scoped full-text/vector or
managed memory against this baseline with leakage and latency measurements.

Sources: [typed contracts](../src/delivery/typed_memory.py),
[memory SQL](../sql/migrations/015_typed_memory.sql),
[memory regressions](../tests/test_typed_memory.py).

## 5. Reuse a factory and freeze editable definitions

**Choice.** All supported roles use `LocalAgent`; strict definitions and their
hashes are frozen per run. Supply blueprints allow entity overrides and revision
checks. **Alternative.** Create separate frameworks per role or let instructions
modify capabilities at runtime. **Why.** One execution contract makes permissions,
budgets and evidence consistent. **Trade-off.** SOUL is versioned guidance that
deterministic policies do not interpret; editing it cannot add behavior. The GCP
gateway uses a separate fixed prompt and does not receive local SOUL. **Revisit
when** adding a reasoning adapter: deliberately assemble trusted instructions and
bounded observations, retain prompt versions, and preserve independent enforcement.

Sources: [factory](../src/delivery/agent_runtime.py),
[supply definitions](../src/delivery/supply_models.py),
[definition tests](../tests/test_supply_models.py),
[gateway prompt](../infra/gcp-ai/gateway.py).

## 6. Host the optional judge on Cloud Run

**Choice.** Deploy a stateless container calling Vertex REST, with separate caller
and runtime service accounts. **Alternative.** Managed Agent Runtime, ADK hosting
or GKE. **Why.** A bounded HTTP verdict fits the existing explicit container,
IAM and Terraform lifecycle. **Trade-off.** Managed sessions, memory, agent
identity and governance are not supplied by this design. Network reachability
is public with authenticated invocation. **Revisit when** client requirements
justify managed lifecycle capabilities or different isolation/network controls.
Evaluate the same task and permissions; a framework object alone does not create
a distinct workload identity.

Sources: [Terraform](../infra/gcp-ai/main.tf),
[cloud client](../src/delivery/cloud_ai.py), [component inventory](GCP-COMPONENTS.md).

## 7. Keep routine work local and park billable runtime explicitly

**Choice.** Default providers are disabled. Optional GCP resources belong to a
dedicated Terraform project. Daily stop removes Cloud Run, its invoker binding and
Artifact Registry before unlinking billing; project, APIs and IAM remain.
**Alternative.** Always-on cloud infrastructure or deleting/recreating the entire
project each session. **Why.** Local checks need no model account, while retained
identity/project ownership avoids repeated setup. **Trade-off.** Retention and
shutdown need explicit accounting. Six per-run model calls and token reservations
do not create a project-wide dollar cap. **Revisit when** a client needs persistent
services, backups or multi-caller inference; add cost admission and declared
retention/containment ownership.

Sources: [local Compose](../compose.yaml), [lifecycle helper](../scripts/gcp_demo.py),
[lifecycle tests](../tests/test_gcp_demo_commands.py), [operations](GCP-AI.md).

## 8. Publish measured receipts before architecture rankings

**Choice.** Keep source-linked tests, fixed scenario criteria, repeat hashes,
business replay and explicit freshness. **Alternative.** Rank architectures or
models from a convincing animation or one successful run. **Why.** A safe rejection
can be correct; scores require declared expectations and complete measurements.
**Trade-off.** The battery covers development regressions, not generalization,
production SLOs or causal business uplift. **Revisit when** comparing flat,
hierarchical or planner/executor designs: freeze paired incidents, hold out case
families, repeat trials and publish quality, latency, cost and failure outcomes.

Sources: [scenario evaluator](../src/delivery/scenario_evals.py),
[receipt validation](../src/delivery/scenario_report.py),
[reporting tests](../tests/test_scenario_evals.py), [evidence guide](CAPABILITY-EVIDENCE.md).

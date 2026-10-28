# Capability evidence

The six goals below connect the architecture to executable proof and its limits.
Source review is dated **2026-10-28**. The dated
[implementation review](AGENT-IMPLEMENTATION.md) records **392 passing tests**.
The role battery declares **12 fixed scenarios and 49 criteria**, with matching
outcomes across two seed-731 repetitions. These are historical development results,
not a current service-health statement or a new test run performed by reading
this chapter. The earlier [local receipt](evidence/local-health.json) records a
different snapshot of 353 tests; it is not the receipt for the 392-test result.
See the [scenario receipt](evidence/agent-scenarios-local.json) and
[evaluation contract](AGENT-EVALS.md).

Tests exercise narrower guarantees than their headlines suggest. Follow the
linked assertions, distinguish successful rejection from business success, and
use the running health view for current source/freshness information.

## 1. Queue resilience

**Goal:** agents must cooperate through durable work and recover safely from
duplicates, contention, stale workers and failure.

**Implemented proof:** the [queue](../src/delivery/queue.py) and
[capability migration](../sql/migrations/014_queue_capability.sql) provide addressed
claims, due times, priority, lease fencing, retries/backoff, deduplication and dead
letters. [Queue tests](../tests/test_queue.py) exercise concurrent claims, rollback,
retry and replay. [Agent boundary tests](../tests/test_agent_queue_boundary.py)
reject raw mutation, forged publication and stale ACKs; they recheck deadlines
after lock waits and verify authoritative payload reload. The fixed battery
includes a real worker-process crash before acknowledgement.

**Limit:** domain effects, memory, decision, outbox and ACK are atomic in the fixed
worker. This does not promise exactly-once inference or billing. Sustained
throughput/backpressure, durable controller restart and orphan-login recovery
remain unmeasured or unfinished. Cloud judge network I/O still holds the effects
transaction open. [Implementation details](AGENT-IMPLEMENTATION.md).

## 2. Hierarchy, coordination and authority

**Goal:** give cooperating roles different responsibilities and prevent one role
from overruling another's business authority.

**Implemented proof:** the [authority contract](../src/delivery/agent_specs.py)
defines each role's tools and topics. A dispatcher assigns work, a courier accepts
its own brief, a judge reviews recovery, and domain commands independently enforce
consent, stock and custody. [Fleet tests](../tests/test_fleet_recovery.py) cover two
dispatchers competing for one bike, cross-courier denial, mandatory judgement and
checkpoint handoff. [Delivery tests](../tests/test_delivery_flow.py) reject
cross-domain commands and invented physical arrival. A judge's verdict cannot
manufacture a route or move a parcel.

**Limit:** role coordination and approval gates are implemented; a generic
hierarchical planner is not. Flat, hierarchical and planner/executor architecture
comparisons are **not implemented**. Counting roles or showing a handoff does not
measure the value of a hierarchy. The host, operator and fixed policies remain
trusted. [Fleet workflow](FLEET-RECOVERY.md).

## 3. Shared memory without unrestricted access

**Goal:** preserve relevant knowledge across handoffs while preventing unrelated
orders, roles and customers from leaking into recall.

**Implemented proof:** [typed memory](../src/delivery/typed_memory.py) stores
validated observations, server-derived provenance and append-only revisions.
Recall derives context from the current authenticated lease. Approved canonical
custody facts are exported in an assignment brief; another agent's private memory
is not shared. [Memory tests](../tests/test_typed_memory.py) cover source forgery,
current-order isolation, concurrent capacity, expiry and suppression of older
revisions. [Supply tests](../tests/test_supply_integration.py) restrict markets to
the current ingredient request; fleet tests isolate courier assignment attempts.

**Limit:** this is exact filtered recall and explicit fact sharing. Cross-order
learning, vector recall, automatic consolidation and managed Memory Bank are not
implemented. Typed observations cannot override operational truth. Expiry removes
recall eligibility while retaining operator audit history; it is not a deletion
policy. [Memory contracts](AGENT-MEMORY.md).

## 4. Cost and tool admission

**Goal:** bound work before execution and retain the cost of uncertain attempts.

**Implemented proof:** [runtime tests](../tests/test_agent_runtime.py) exercise
concurrent durable reservations and exhausted limits. Optional judge tests verify
six calls/50,688 reserved tokens per run, with 8,448 tokens reserved per attempt
and no reuse of that attempt reservation. [Cloud request tests](../tests/test_cloud_ai.py)
enforce a bounded numeric context; [gateway tests](../tests/test_gateway_policy.py)
deny invalid or infeasible requests before model invocation.
[Search tests](../tests/test_supply_search_service.py) retain admission reservations
after provider failures. Default local scenarios invoke no model.

**Limit:** `model_usd: 0` is a schema literal, not a working paid-GCP dollar ceiling.
Per-run limits, one Cloud Run instance and scale-to-zero do not cap project spend.
A durable gateway-wide currency admission ledger and comparative live cost per
successful task remain missing. Provider regressions use injected responses;
historical live verification is documented separately. [GCP components](GCP-COMPONENTS.md).

## 5. Evaluations

**Goal:** make expected behavior explicit and reproduce both safe outcomes and
failure cases.

**Implemented proof:** the [scenario manifest](../data/evals/agent-scenarios.json)
declares twelve scenarios and 49 typed criteria. The
[evaluator](../src/delivery/scenario_evals.py) runs real scoped workers in disposable
local test worlds; [receipt validation](../src/delivery/scenario_report.py)
recomputes results and checks source/configuration/repeat hashes. Missing criteria
receive no credit, a later pass cannot erase an earlier failure, and source drift
fails reproducibility. [Evaluator tests](../tests/test_scenario_evals.py) verify
these rules, local-only database guards and cleanup after fixture failure.

**Limit:** these are fixed rules-based development regressions. They do not measure
held-out LLM quality, memory-strategy superiority, architecture comparisons,
production latency or business uplift. Historical live GCP system cases also
include deterministic preflight denials; their pass count is not a model accuracy
score. [Evaluation methodology](AGENT-EVALS.md), [dated cloud evidence](GCP-VERIFICATION.md).

## 6. Observability and replay

**Goal:** explain what work executed, what it observed and why the recorded
business state changed.

**Implemented proof:** decisions retain tool receipts, recalled fact IDs/revisions,
memory writes and event lineage. The operator can inspect complete order history.
Supply replay reconstructs business projections and detects fact-hash corruption;
[delivery-fact tests](../tests/test_supply_delivery_facts.py) retain world and
dispatcher changes even after a household order becomes terminal.
[Health reporting](../src/delivery/health.py) distinguishes missing, partial,
failed, stale and source-outdated receipts. Its
[tests](../tests/test_health.py) prevent incomplete evidence from appearing green.
The optional gateway emits structured decision, version, usage and timing records.

**Limit:** business replay and recorded explanations do not expose private model
reasoning. Complete OpenTelemetry propagation, Cloud Trace, production dashboards,
alert policies and declared cloud log retention are not configured. Reading local
health does not query current GCP deployment status. Use [health semantics](HEALTH.md)
and the [GCP operations runbook](GCP-AI.md) for their distinct evidence boundaries.

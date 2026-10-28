# Enterprise agents on GCP: architecture and delivery decisions

Reviewed against source and Google documentation on **2026-10-28**. This is the
client architecture guide. [Agent implementation](AGENT-IMPLEMENTATION.md) explains
the exact executable worker; [GCP components](GCP-COMPONENTS.md) inventories every
declared cloud resource; [GCP operations](GCP-AI.md) covers start/status/stop.
Recommendations below are **proposed** unless explicitly marked implemented.
This review did not deploy infrastructure, inspect credentials or invoke a model.

## Client objective and current decision

Build a delivery/sourcing system whose agents can make bounded decisions while
inventory, consent, custody, approvals and money remain enforceable business rules.
Use the local synthetic city as a reproducible client test environment. Introduce
paid inference only for a declared decision task and promote it only when measured
benefit exceeds added latency, failures and cost.

Implemented today: custom Python/Postgres role workers, queued cooperation,
authenticated scopes, typed selective recall, budgets and local scenario evals.
The optional cloud component is an IAM-authenticated **Cloud Run recovery judge
calling a Google publisher model through Vertex REST**. It can veto a locally
computed candidate; it cannot invent a route, change stock or execute a delivery.
Google ADK, Agent Runtime, managed Memory Bank and Agent Gateway are not deployed.

Google's current product documentation uses **Gemini Enterprise Agent Platform**
and **Agent Runtime**; older Agent Engine/Vertex AI names and API resource names
remain visible in documentation and integrations. Separate the framework, hosting,
model API and governance layers when choosing components. Google documents both
Cloud Run and managed runtime options; our selection depends on the client's
operational and governance requirements, not a requirement to use every service.
[Google architecture component guide](https://docs.cloud.google.com/architecture/choose-agentic-ai-architecture-components).

## Choose the runtime by workload

Before platform selection, agree the task and unsafe outcomes, expected demand,
deadline/latency SLO, acceptable cost per successful task, tenant/data boundaries,
processing region, retention, operator approval rules and RTO/RPO. Assign owners
for policy, data access, release approval, incident response and billing. The local
city supplies test incidents; it does not define an enterprise client's SLOs.

| Option | Use when | Our decision / limitation |
| --- | --- | --- |
| Cloud Run service | Bounded, stateless HTTP decisions; variable demand; explicit container/network controls | Implemented for the judge. Suitable first ADK pilot after the transaction refactor |
| Cloud Run job | Finite evaluations, imports or migrations | Proposed for an explicitly cloud-enabled benchmark; current benchmark stays local |
| Cloud Run worker pool | Continuous pull consumers without an inbound HTTP API | Candidate for production queue workers; provisioned instance lifetime is billable |
| Managed Agent Runtime | Managed agent hosting, sessions, identity/governance and lifecycle capabilities materially reduce client operations | Evaluate against the same workload and permissions before choosing it |
| GKE | Client already needs Kubernetes-specific networking, scheduling or isolation controls | No current requirement; owning a cluster is not an agent prerequisite |

Cloud Run services can scale to zero; jobs and worker pools have different
lifecycle/billing behavior. Moving an in-process API background task onto a
request-billed service does not make it a durable worker. Choose a supervised
consumer or a bounded task, with external state and restart-safe ownership.
[Cloud Run agent resource choices](https://docs.cloud.google.com/run/docs/ai-agents),
[billing behavior](https://docs.cloud.google.com/run/docs/configuring/billing-settings).

For an ADK implementation, pin a tested framework/SDK version and dependencies.
Keep our role definition, authenticated tool boundary and queue protocol as the
business contract; ADK becomes the reasoning adapter. Do not replace those
contracts with a prompt or a framework's implicit shared state. Google's
[ADK and Cloud Run reference architecture](https://docs.cloud.google.com/architecture/single-agent-ai-system-adk-cloud-run)
provides a deployment reference; it is not a claim that this repository already
implements that architecture.

## A reusable enterprise agent contract

The proposed reasoning adapter should accept a validated definition containing
purpose, role/version, instructions, supported event schemas, tool references,
memory policy, numeric limits, deadline behavior and escalation route. Tenant/run
scope comes from a trusted deployment/event binding. Configurations and model
proposals cannot choose arbitrary URLs, credentials, recipients or tools.

Construct one adapter for one trust boundary: load frozen definition → resolve
approved tool wrappers → build scoped context → invoke bounded reasoning →
validate output → request domain execution. Reuse the image/factory and change
approved definitions. Adding a new role still requires domain permissions and
evaluation coverage. Several ADK subagents in one process do not receive distinct
IAM identities merely because their prompts have different names.

Domain tool endpoints must authenticate the workload and independently authorize
tenant, role, current order and operation. For MCP or A2A, implement authenticated,
schema-versioned adapters; accepted business messages become durable queue events.
Do not add direct agent transfer/shared conversational state that bypasses the
project's queue-only cooperation rule. Tool calls to a domain service and messages
to another agent are different operations. Google's safety guidance reinforces
enforcement in tool context/callbacks rather than relying on instructions alone.
[ADK safety and security](https://adk.dev/safety/).

## Identity, isolation and governance

**Implemented:** separate caller and runtime service accounts; caller-specific
Cloud Run invocation; a custom runtime role with only
`aiplatform.endpoints.predict`; keyless ADC/impersonation; scoped PostgreSQL agent
logins. The endpoint is internet-reachable with IAM authentication. There is no
private VPC ingress or generic tenant authorization gateway in the current module.

**For a client deployment:** separate dev/staging/production ownership and state,
deployer and runtime identities, and role trust boundaries. Reject public
invocation. Decide ingress/egress, residency, key management, incident access and
retention with the client before selecting networking controls. Identity grants
permission to reach a service; business authorization still decides which store,
order, event lease and operation the caller may access.

For restricted client data, assess private connectivity and VPC Service Controls
against supported services/locations; a perimeter complements IAM to reduce
exfiltration risk. Select CMEK only where supported and required. Test denied
egress and approved access explicitly. An EU-hosted Cloud Run service using a
global model endpoint is not an EU-only processing guarantee. These controls are
proposed, with no network perimeter or CMEK resource in the current module.
[VPC Service Controls](https://cloud.google.com/security/vpc-service-controls).

When choosing managed Agent Runtime, evaluate **Agent Identity** rather than
assuming a shared default service account is sufficiently narrow. Its identity is
tied to the deployed runtime resource, not every local role object. Current docs
describe runtime-bound credentials and default grants including
`roles/aiplatform.agentDefaultAccess` and `roles/aiplatform.agentContextEditor`;
review those grants and keep context-aware credential protections enabled.
These features are not retroactively provided by our existing Cloud Run service.
[Agent Identity behavior and defaults](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/agent-identity).

For governed tool estates, evaluate **Agent Registry**, **Agent Gateway** and
**Model Armor** against the chosen runtime and client policy. Registry describes
approved agents/tools; gateway enforcement and content inspection complement
IAM and domain authorization. They do not make untrusted tool output safe by
definition. Confirm runtime support, launch stage, region, pricing and Terraform
coverage before adoption; include allow/deny and injection tests in acceptance.
No such resources are currently provisioned.
[Agent platform layers](https://docs.cloud.google.com/gemini-enterprise-agent-platform/agents),
[gateway deployment options](https://docs.cloud.google.com/gemini-enterprise-agent-platform/govern/gateways/agent-gateway-overview).

Terraform ownership is an adoption gate for each proposed service. Verify that the
selected provider/API can create, import, plan, update and delete the runtime and
its dependent billable resources. An SDK or ADK CLI deployment is not automatically
Terraform-owned. Defer an unsupported component or design a reviewed declarative
lifecycle module; document session/memory data retention and cleanup separately.

Use Workload Identity Federation for production CI/external workloads instead of
downloaded service-account keys or a human ADC mount. Bind federation to the
approved repository/workflow/environment and trusted claims, and separate plan
from approved apply permissions. The current GitHub workflow tests local Docker;
it is not a cloud deployment pipeline. For third-party secrets, introduce Secret
Manager only with narrow access and lifecycle ownership; Gemini on GCP needs
workload credentials, not a hard-coded model API key.
[Google pipeline identity guidance](https://docs.cloud.google.com/iam/docs/best-practices-for-using-service-accounts-in-deployment-pipelines),
[federation setup](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).

## Durable execution: first enterprise implementation priority

The existing local worker atomically commits state, memory, decision, outbox and
ACK. Its separate attempt/model reservations survive rollback. **The cloud judge
currently performs network I/O while the effects transaction and run/event locks
remain open.** There is no gateway-wide idempotency ledger or completed-response
reuse. A subsequent event attempt can incur another bounded model call.

Refactor that paid decision into these durable phases before increasing load:

1. Validate scope/deadline, snapshot permitted evidence and reserve a pessimistic
   call/token/currency allowance in a short transaction. Persist a versioned request
   with a stable business idempotency key and state such as `reserved`.
2. Commit, release database locks and invoke the approved model endpoint. Propagate
   a sanitized correlation ID separately from model business content. Bound elapsed
   time and all retries; uncertain outcomes retain their reservation.
3. Persist the validated result/usage and enqueue its completion. Reuse a completed
   result for duplicate work; never equate a timeout with proof of no spend.
4. In a new short transaction, recheck order version, assignment attempt, consent,
   custody, current stock and deadline. Apply the authorized result and publish the
   next event atomically, or reject a stale proposal.

Add durable controller ownership/checkpoints and an orphan-identity reaper.
Kill the controller and the inference worker separately; prove recovery before
claiming cloud fault tolerance. Move state to Cloud SQL only after testing actual
managed-Postgres migration privileges, non-owner RLS, extensions, pooling,
connection limits, backup/restore and failover. Local superuser provisioning is
not evidence that unchanged migrations work in a managed service.

If Pub/Sub is added, start with wakeups from a transactional outbox while SQL
retains priority, virtual due time and domain idempotency. A full transport change
requires an inbox/outbox design and new failure tests. Pub/Sub's exactly-once
feature is regional and pull-subscription-specific; it does not provide an atomic
transaction with our stock tables or exactly-once external model charging.
[Pub/Sub delivery semantics](https://docs.cloud.google.com/pubsub/docs/exactly-once-delivery).

## Canonical state, sessions and memory

| Layer | Current implementation | Client design rule |
| --- | --- | --- |
| Business truth | Transactional PostgreSQL stock/orders/consent/custody | SQL constraints and version checks remain authoritative |
| Conversation/session | Correlated queued order/call events and frozen run settings | Persist outside a scaled stateless runtime; derive user/tenant identity from authentication |
| Selective recall | Typed facts scoped to role/current order; request/attempt filters; provenance/expiry/history | Authorization filters precede retrieval; bound bytes and recall cost |
| Cross-session knowledge | Not implemented | Evaluate managed Memory Bank or a scoped PostgreSQL/vector design only for a measurable task |
| Audit | Decision/tool/memory receipts and replay facts | Separate agent recall access from operator audit access and retention |

Managed sessions and Memory Bank can reduce custom context management, but neither
replaces transactional business state. A scope label or semantic match is not an
authorization check. Evaluate extraction quality, poisoned/stale facts, consent,
deletion/export, region and metering before sending client history to a managed
memory service. Our cloud judge currently receives a **memory count**, not memories.
[Memory Bank capabilities](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank).

Current TTL expires recall eligibility, not physical audit retention. Production
needs a declared wall-clock retention/deletion policy for facts, revisions, traces,
backups and model context. Add vector recall only if exact structured retrieval
fails a held-out task; then compare recall quality, leakage, latency and tokens.

## Model choice and cost controls

The historically verified model is `gemini-3.5-flash-lite`; Terraform requires an
explicit model/location, and the gateway assumes `MINIMAL` thinking is supported.
Do not swap in a newer model family without checking generation settings, regional
support, release status and rerunning the same evals. Record returned model version,
image/prompt/schema/role/fixture hashes, location and pricing date. Monitor model
retirement. A model alias is not a guarantee of identical future outputs.
[Model specifications and lifecycle](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite).

Choose the least expensive model that passes the client's quality and latency
gates. For this numeric feasibility task, deterministic rules may remain the best
choice: the LLM's business benefit is unproven. A future ambiguous substitution or
incident-review task needs an approved evidence contract and human-calibrated
rubric before a larger model is justified.

Current standard global text rates checked 2026-10-28 for 3.5 Flash-Lite are $0.30
input and $2.50 output/reasoning per million tokens. At the caller's 8,192 + 256
reserved-token envelope, one illustrative maximum-envelope generation is
`(8192 × 0.30 + 256 × 2.50) / 1,000,000 = $0.0030976`; six are $0.0185856.
This is arithmetic for that SKU/location, **not a project-wide cost ceiling**.
It excludes compute, storage, logs, network, other clients and uncertain requests.
A local timeout or gateway 502 can follow a successful billable Vertex response.
[Current model pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

Before exposing more callers, add a **durable gateway admission ledger** keyed by
tenant/project/window and business request ID. Reserve worst-case gross currency,
input/output/reasoning tokens and calls before inference; reject exhaustion and
reconcile actual usage. Account for the complete prompt/schema/context and every
attempt, including auth/SDK retry behavior. Current local `model_usd: 0`, Cloud Run
maximum instances and per-run call reservations do not implement this ledger.

Configure actual/forecast billing alerts and a tested containment action, with
an owner for reconciliation. Budget alerts are not an immediate spending cap.
Current Google documentation also lists service-scoped spend-cap budgets for
Agent Platform (formerly Vertex AI) and Cloud Run, among eligible services. Assess
eligibility and manage separate project/service caps in Terraform before enabling
them. They are not deployed here. Enforcement is not instant; in-flight requests
and reporting latency can produce payable overages. They are not an all-project
ceiling. Use admission controls and explicit shutdown alongside billing signals.
[Google budget behavior](https://docs.cloud.google.com/billing/docs/how-to/budgets),
[Spend-cap scope and limitations](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps).

## Evals, observability and release gates

The current [local role battery](AGENT-EVALS.md) records 12/12 cases and 49/49
criteria across two matching seed-731 runs, plus 392 passing tests. It exercises
rules-based agents and scoped SQL identities. The separate historical live GCP
eval achieved 6/6 system cases with **one model answer and five preflight denials**;
an earlier missing-facts model approval is retained in the evidence. Neither is
a held-out model benchmark or proof of business uplift.

For a client, evaluate both final task success and the tool trajectory. Use a
frozen family-separated tuning/holdout split, repeat model cases, and compare
rules-only vs model-assisted runs on the same incident schedules. A second LLM may
help assess explanations with human calibration; it cannot replace the hard
feasibility/tenancy oracle. Check the launch stage and price of the selected
managed evaluation feature before using it in a contractual release process.
[Google agent evaluation dimensions](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/evaluation-agents).

| Release gate | Evidence required before production |
| --- | --- |
| Isolation/safety | Zero executed hard-rule violations or cross-scope disclosures in declared adversarial cases; rejected attempts remain visible |
| Decision quality | Approve/deny confusion matrix, false denials, explanation support and human-reviewed disagreements on held-out incidents |
| Business outcome | Paired on-time delivery/recovery, abandoned work and operator effort, with predeclared tolerances and uncertainty |
| Performance | End-to-end cold/warm p50/p95/p99, queue age, timeout/429/5xx rates and late-result rejection against client deadline slack |
| Cost | Actual usage and gross currency per decision/successful recovery, uncertain reservations and concurrent admission tests |
| Recovery | Worker/controller failure, duplicate delivery, stale proposal, restore and rollback drills |
| Reproducibility | Frozen inputs, source/model/prompt/role versions, policy and architecture assignment, sanitized trace/eval receipts |

Add OpenTelemetry spans linking order → event → worker → tool → model, exported to
Cloud Trace/Logging/Monitoring with explicit redaction, sampling and retention.
Track budget admission, safety denials, feasible retries incorrectly denied,
queue/dead-letter growth and on-time delivery; an always-deny model can have perfect
uptime. Gateway stdout and local event inspection exist; complete distributed
tracing, alert policies and cloud eval dashboards do not.
Google describes observability and governance as distinct platform responsibilities.
[Agent platform architecture](https://docs.cloud.google.com/gemini-enterprise-agent-platform/agents).

## Terraform, delivery and shutdown ownership

Keep this client's root/state separate from Scrapmarket. Pin providers, Python
dependencies, base/deployable image digests and approved release provenance. The
current Dockerfile's base tag is mutable, even though deployed images use digests.
Add a reviewed CI plan/apply flow with federation, restricted deployer permissions and
protected production approval. Artifact provenance/scanning and rollback are
release work, not guarantees supplied by an image digest alone.

The demo currently uses ignored **local state**. A multi-operator enterprise
deployment should use an access-controlled remote backend, locking/versioned
recovery and separate environment states. Google's Cloud Storage backend pattern
is an appropriate candidate. A retained state bucket has storage cost and should
live outside an ephemeral runtime's teardown dependency chain; approve that cost
exception before introducing it. It is not currently provisioned.
[Google Terraform state guidance](https://docs.cloud.google.com/docs/terraform/resource-management/store-state).

Current daily stop preserves project/APIs/IAM, removes billable gateway/image
resources and then unlinks billing. Protected project deletion is deliberately
blocked. Any new SQL database, memory store, secret, log sink or evaluation artifact
store needs Terraform ownership, startup/stop behavior, retention and verification.
An enterprise client's HA/backup/retention requirements can impose a persistent
cost floor; the local city's zero-cloud-cost development mode remains available.

## Delivery sequence and client demonstration

| Step | Scope | Acceptance evidence |
| --- | --- | --- |
| 1. Preserve local baseline | Versioned roles, business rules, queues and scenarios | Current isolation/regression receipts remain reproducible without credentials |
| 2. Harden paid decisions | Split remote I/O from SQL transactions; durable inference request/result/admission ledger; supervisor recovery | Crash/duplicate/timeout/concurrency tests and measured p95; no double business effect |
| 3. Pilot one ADK role | Same approved tools and role contract, smallest passing model, explicit deployment identity | Same safety suite plus held-out quality/latency/cost comparison |
| 4. Select GCP hosting/governance | Cloud Run or managed runtime; networking, identity, memory and Terraform coverage based on client constraints | Reviewed threat/data-flow model, least-privilege negative tests and complete stop/retention inventory |
| 5. Operate and promote | Shadow evaluation, explicitly assigned canary, rollback and incident ownership | Agreed business/quality/SLO/cost gates and a signed-off handover |

In a walkthrough, show one order's queue lineage, authenticated scope, reservation,
selective memory, physical handoff and eval result. Then show the optional GCP
request boundary, caller/runtime identities, actual model-vs-policy response and
usage. Finish with the Terraform plan/parked status and the gaps above. This
demonstrates engineering decisions and evidence without presenting the demo as an
already production-certified enterprise agent platform.

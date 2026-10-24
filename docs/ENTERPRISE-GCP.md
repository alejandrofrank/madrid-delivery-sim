# Enterprise design: bounded GCP recovery judgement

Architecture decision, reviewed 2026-10-24. Operational deployment evidence belongs in [GCP-AI.md](GCP-AI.md) and [VALIDATION.md](VALIDATION.md); this document does not certify that a deployment or an evaluation has passed.

## Decision and business hypothesis

Keep the simulation and its authoritative PostgreSQL state local. Deploy only an optional, stateless, IAM-authenticated Cloud Run judgement endpoint calling a configured Google model through Vertex/Google Cloud. Use a dedicated project, Terraform state, runtime identity and image repository, separate from Scrapmarket. The approved billing account is CORTEXLABS SL; sharing a billing account does not imply sharing application resources or permissions.

The model can veto a locally computed recovery candidate. It cannot create a route, assign a courier, change inventory, move custody, exceed retries, extend deadlines or override SQL checks. This is a useful integration and governance experiment, but **AI business value is unproven**: the current input is a few numeric facts, and deterministic code already computes feasibility. An LLM repeating those rules can add latency, cost and false denials without improving deliveries. The default rules baseline remains a credible product choice.

The falsifiable hypothesis is that, with additional approved evidence about ambiguous incidents, bounded judgement can reduce harmful retries or operator review effort while preserving on-time recovery. Adding such evidence requires a separate data contract and evaluation; do not claim that the present numeric veto demonstrates planning intelligence, learning, or autonomous fleet operation. A more credible future judgement task is comparing recipe procurement alternatives against available stock and explicit price/nutrition constraints, evaluated against a deterministic optimizer and human rubric. That task is not implemented by the retry veto.

The authorized model business data is a small synthetic supermarket-menu snapshot covering pizza, kebab, hamburgers, steak frites, sushi, soups and salads, with fictional supermarket item/stock records and no personal data. Numeric retry-control facts may accompany that snapshot for the bounded recovery task. This authorization does not extend to private source datasets, customer records, basket/courier identities, raw memory episodes or arbitrary database exports. The gateway now packages the validated seven-meal snapshot as read-only reference. It still decides recovery only; it does not perform procurement or ingredient substitution. Container import and snapshot tests verify this boundary; live-cloud evidence is recorded separately.

## Implemented boundaries and proposed extensions

| Area | Implemented contract | Enterprise extension, not a current claim |
| --- | --- | --- |
| Roles | Frozen role definitions, inventory/fulfillment/dispatcher/courier/judge tool allowlists, scoped worker identities | Add a role only with server permissions, scenario tests and an accountable owner |
| Execution | Durable event leases, bounded attempts, idempotent transactions and local candidate computation | Cross-region recovery and production workload SLOs |
| Model | Optional recovery-judge adapter; strict approve/deny schema; deny on transport, auth or validation failure | Shadow collection, controlled canary and quality release gates |
| State | Local PostgreSQL canonical state, scoped expiring JSON episodes and decision evidence | Managed PostgreSQL, tested backup/restore and tenant lifecycle |
| Cloud | Terraform and gateway source define private invocation, keyless runtime and bounded service sizing | Global admission ledger, automated containment and central cost reconciliation |
| Evidence | Model decision/reason/usage recorded with local event lineage | Full revision/prompt/pricing provenance, quality dashboard and independently reviewed eval results |

Fail closed means the AI-enabled retry is denied on failure. It does not mean availability is free: a cloud outage can prevent an otherwise feasible recovery. Operators can select deterministic mode for a new run; changing mode silently within an experiment would invalidate comparison.

## Agent structure and platform tradeoffs

The current graph is an event-driven business workflow, with database-enforced tools around specialized roles. Only the recovery judge invokes a model. Keep orchestration in the existing queue and transactional boundary rather than spawning an LLM for every courier or implementing conversational delegation. Concurrency is useful for independent parcels; it is not a reason to surrender ordering or custody ownership.

Cloud Run fits this single request/response service: a small container, IAM invocation, no session dependency, zero minimum instances, one maximum configured instance and four concurrent requests. Cold starts are an accepted demo tradeoff. Service sizing and Vertex model quotas limit throughput, not total money. Cloud Run can temporarily exceed configured maxima during exceptional scaling or revision transitions; use service-level limits where supported and conservative safety margin. [Cloud Run instance limits](https://docs.cloud.google.com/run/docs/configuring/max-instances-limits).

ADK is a framework option if future requirements demand reusable tool orchestration or agent interoperability. Managed Agent Runtime/Agent Engine becomes attractive when hosted sessions, lifecycle operations and integrated governance reduce more operational work than they introduce. Neither supplies business correctness, database tenancy or an automatic cost ceiling. Importing it now would duplicate a working event runtime and obscure the experiment. Sessions and Memory Bank also have separate metering; model calls remain billable. [Agent platform architecture](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/runtime), [platform pricing](https://cloud.google.com/gemini-enterprise-agent-platform/pricing).

## Model choice and lifecycle

Start the bounded numeric classifier with `gemini-3.5-flash-lite`, subject to a successful regional smoke test and the same eval gates as any challenger. Its Google Cloud model page lists GA, release July 21, 2026 and retirement July 21, 2027 or later. Standard PayGo supports `global`, `us` and `eu`; Cloud Run region and model location are separate choices. An EU Cloud Run deployment calling `global` is not an EU processing guarantee. [Flash-Lite specifications](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite).

Use `gemini-3.8-flash` as an offline challenger only if it measurably improves the task. Google lists it as GA with global and multi-region support. It requires model-aware generation settings: remove custom sampling parameters and `candidate_count`; supported thinking levels are LOW/MEDIUM/HIGH, not MINIMAL. Flash-Lite supports MINIMAL, suitable for this bounded classifier. Schema conformance does not establish factual correctness or determinism. [3.8 migration guide](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/guides/gemini-3-8-flash).

Pin the configured model identifier, image digest, role hash and prompt/schema revision in every experiment. Stable names still require lifecycle monitoring; record the returned model version where available, review retirement notices monthly, and rerun frozen evaluations before changing a model, location, thinking setting or prompt. Historical `gemini-2.5-flash-lite` evidence in this repository is historical, not proof of current availability.

## Cost model and admission safety

Illustrative Google Cloud standard global text rates, USD per million tokens, checked 2026-10-24:

| Model | Input | Output including reasoning | 1,000 calls at 1,000 input + 256 output tokens each |
| --- | ---: | ---: | ---: |
| 3.5 Flash-Lite | $0.30 | $2.50 | $0.94 |
| 3.8 Flash, published promotional effective rate through 2026-12-31 | $0.75 | $3.75 | $1.71 |
| 3.8 Flash, published rate from 2027-01-01 | $1.50 | $7.50 | $3.42 |

Formula: `(input_tokens × input_rate + billable_output_tokens × output_rate) / 1,000,000`. These are arithmetic examples, not measured costs or a quote. The 3.8 promotion is delivered through credits; reserve against gross list rates rather than assuming immediate credits. Non-global pricing differs; the current table lists Lite $0.33/$2.75. Recheck the exact SKU, location and contract before enabling. Compute, image storage, build, logs, networking, taxes and failed/in-flight inference are additional. [Google Cloud model pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

Implemented safeguards include per-run durable caller reservations, bounded calls/tokens, a small numeric payload, 256 output tokens, explicit timeouts, no automatic application retry and deny-on-error. A dollar limit configured as zero must not be presented as monetary enforcement without checking the code's zero semantics and recording actual rates. Input byte limits are not token limits. Count the complete request, including system instructions/schema where applicable, and account for billable reasoning tokens in usage and conservative reservation.

There is an important enterprise gap: a caller-local reservation does not police another authorized client invoking the gateway directly, concurrent independent runs, or usage of Vertex outside the gateway. Before exposing more callers, add a durable gateway admission ledger keyed by project/tenant/day and request ID. Atomically reserve worst-case dollars and tokens before inference; reject exhausted budgets, deduplicate requests, reconcile usage after completion, and retain reservations after ambiguous timeouts. An in-memory counter is insufficient across restarts or revisions. Disable hidden SDK retries or charge each attempt explicitly.

Set project-scoped billing alerts (actual and forecast), monitor token/call rates and deny ratios, and provide a kill switch through caller IAM revocation or service shutdown. Ordinary **alerts-only budgets do not cap spending** and reporting is delayed. Current Google docs also offer service-specific spend cap budgets for eligible services, including Cloud Run; eligibility must be verified and enforcement is not instant, with overages still billed. A Cloud Run cap must not be described as a project-wide Vertex cap. These controls supplement, not replace, request admission. [Budget alerts](https://docs.cloud.google.com/billing/docs/how-to/budgets), [spend-cap limitations](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps), [Cloud Run cap scope](https://docs.cloud.google.com/run/docs/configuring/billing-settings).

## Memory and data ownership

PostgreSQL remains the source of truth. Existing role/run/store scoping uses authenticated identities and forced RLS; prompts cannot grant access. Episodes have source events, simulation time, TTL and entry/byte limits. Shared custody briefings are intentional projections, distinct from private memory. The gateway currently receives only numeric allowlisted facts, a route summary and memory entry count; it does not retrieve memory bodies. Therefore do not claim the cloud model reasons over episodic memory.

For an enterprise service, migrate the same contract to Cloud SQL only when hosting, backup or availability needs justify it. Test RLS under actual non-owner application roles, connection pooling and migrations; isolate operator credentials, rotate access and verify restore. Add pgvector only when a measured semantic-retrieval task exceeds structured SQL/recency retrieval. Enforce tenant/role/retention filters before selecting candidates, include provenance and expiry, and treat retrieved text as untrusted evidence. An embedding store is not canonical memory, permission enforcement or a learning mechanism.

## Evaluations and release gates

Keep three questions separate: did the system preserve hard invariants, was the judgement correct, and did it improve the business outcome? SQL remains the feasibility oracle for deadlines, retry ceilings, valid routes and custody; a second LLM must not be the safety oracle for the operational judge.

Build a versioned, held-out fixture set from seeded baseline runs, boundary cases and reviewed incidents. Include no candidate, exhausted retry, exact deadline, impossible route, stale facts, missing/extra fields, large/invalid numbers, conflicting evidence, poisoned memory, duplicate event, crash-after-reservation, permission denial, timeout, 429, malformed/truncated response and budget exhaustion. Repeat model cases to quantify variance. Split by scenario family so near-duplicate seeds do not leak across tuning and holdout sets.

| Gate | Proposed acceptance criterion; not a reported result |
| --- | --- |
| Safety/tenancy | Zero executed invariant violations and zero cross-scope disclosure in the adversarial suite; every malformed/unavailable decision denies |
| Baseline agreement | Publish approve/deny confusion matrix against deterministic feasibility, especially feasible retries incorrectly denied; investigate every disagreement |
| Business quality | Paired same-seed comparison of on-time recovery, failed recoveries, wasted distance/cost and operator review time; predeclare tolerances and confidence intervals |
| Explanation | Human-rated factual support, correct units, consistency with verdict, no invented facts, and useful denial reason; do not request hidden reasoning |
| Performance | Report cold/warm p50/p95/p99 end-to-end latency, timeouts, 429/5xx and fail-closed rate against deadline slack; define an explicit SLO before production |
| Cost | Report measured billable tokens, gross dollars per decision and per successful recovery; prove concurrent reservations cannot exceed configured admission allowance |

Proposed rollout: frozen offline fixtures → shadow mode (record only) → explicitly assigned 5% canary → broader adoption only after agreed quality/latency/cost gates pass. Shadow/canary routing is a design proposal, not an existing capability. Persist experiment assignment per run. Roll back on any safety breach, material false-denial regression, budget anomaly or sustained SLO miss. An LLM-as-evaluator can help triage explanation quality, but use a separate rubric/version and human-calibrated sample; it cannot validate itself.

## Security, operations and interview narrative

The endpoint is network-reachable for local authenticated callers, but Cloud Run IAM requires an audience-bound ID token and the caller identity has only invocation permission. Runtime ADC accesses Vertex without downloaded service-account keys. Runtime has no database or simulation tool access. IAM least privilege should be reviewed beyond the initial broad `aiplatform.user` grant; production needs an explicit threat model, audit retention and approved egress/data residency controls.

Correlate run/event/request IDs with gateway revision, model, schema/prompt hash, verdict, bounded explanation, elapsed time, token counts, reservation and error class. Avoid logging credentials, raw private memory or customer text. Track decision distribution drift and unexplained denials alongside latency; uptime alone can hide a judge that denies everything. Assign owners for model retirement, IAM review, eval approval, cost alerts, incident response and teardown. Before claiming production readiness, test backup/restore, revocation, rollback and real concurrent load.

An honest interview explanation: “I started with a deterministic delivery system because custody, inventory and money require enforceable transactions. I added AI behind a narrow optional veto boundary so its failures are observable and cannot grant authority. The cloud project and identities are isolated from my other product. I would choose a cheaper classifier before a larger model, and promote it only when paired evaluations demonstrate business benefit after latency and cost. The next enterprise investment is durable global admission and controlled experiments, not another agent framework or a vector database. The deployment proves the integration; quality and production readiness require separate evidence.”

## Live evidence added after this ADR

The first real eval exposed an unsafe raw model approval on missing facts. The
gateway now deterministically denies hard-invalid requests before inference.
The final six-case system eval is 6/6 with one model decision and five policy
denials. This validates the system boundary, not broad model quality or business
uplift. The UI cloud/local switch was exercised against the real private service.
See [deployment verification](GCP-VERIFICATION.md) for revision, data hash, usage
and teardown-plan evidence. Model business context is the approved seven-meal
synthetic supermarket snapshot only; customer and raw memory content remain local.

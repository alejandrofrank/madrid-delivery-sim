# Roadmap: Bakiano delivery operations lab

Updated 2026-10-28. Implemented slices are identified below; remaining milestones are planned.

Shared UI slice: restaurants, delivery, inventory, health, architecture and the
Madrid baseline now use one local workspace shell, visual tokens and control
states. Responsive navigation retains every workspace on a small screen. Maps,
entity definitions, order chats, memory, health filters and code inspection remain
in their working layouts. Content versions prevent stale CSS/JavaScript/SVGs from
surviving an updated shell. Eight monochrome D2 diagrams include recovery review,
dispatch gates and physical handoff, with labels separated from arrowheads.
See [design sources and maintenance](docs/DESIGN-SYSTEM.md).

Durable inference slice: the optional recovery judge now commits an immutable
request, dispatch admission and saved result in short SQL phases. Provider I/O
holds no worker database connection; application rechecks fresh facts and commits
effects, memory, outbox and ACK together. Saved results survive worker death without
another call or budget charge. Uncertain dispatches fail closed without automatic
resend. Local verification includes physical process termination, concurrent owners,
stale results, role isolation and legacy receipts, using a fake provider only.
The full 442-test suite passed, with twelve role scenarios/49 criteria repeated
twice with matching outcomes and six offline judge cases; no paid calls were made.
See [request protocol and recovery policy](docs/DURABLE-INFERENCE.md).

Architecture website slice: `/architecture` provides nineteen numbered chapters,
full-text local search, an interactive component inspector, eight rendered diagrams,
source inspection and eight explicit architecture decision records. The six
capability goals link to implementation, tests and known gaps. Content stays in
repository Markdown; pinned D2/ELK generates native-label SVGs with inspected
source, zoom and expansion. The compact reference UI and all diagram assets work
locally without a CDN. Browser checks cover all eight diagrams and chapter search.
See [website maintenance and boundaries](docs/DOCUMENTATION-SITE.md).

Enterprise GCP documentation slice: the source-reviewed
[agent implementation](docs/AGENT-IMPLEMENTATION.md),
[complete GCP inventory](docs/GCP-COMPONENTS.md) and
[client architecture guide](docs/ENTERPRISE-GCP.md) now distinguish current behavior
from proposed ADK/managed-runtime work. Local durable inference is implemented;
the next enterprise priorities are gateway-wide idempotent monetary admission,
controller recovery, workload identity/production API authorization,
distributed observability and held-out release gates. Platform adoption requires
Terraform lifecycle coverage and an explicit retention/cost policy. These are
proposed changes; the local inference and documentation work deploys no infrastructure.

Role scenario evaluation slice: make eval-agents now runs a versioned local
seed-731 battery twice: twelve scenarios, 49 criteria across inventory, restaurant,
dispatcher and courier agents. The health dashboard shows scores, failed cases,
expected/actual values and event evidence by repetition. Real workers retain role
isolation and queued communication; regression checks include process crashes and
assignment contention. Two local runs matched at 12/12 cases, with zero paid calls.
This advances M7 development evidence; held-out model, topology and memory
comparisons remain planned. See [scenario contracts and limits](docs/AGENT-EVALS.md).

Local health slice: `/health` now exposes the categorized test catalogue, source
and run history, six capability regression groups, the offline recovery baseline,
service probes and per-run queue/budget diagnostics. `make health` records actual
case results and code checks without paid inference. Gaps and stale/partial
evidence remain explicit. This adds inspectable regression evidence for M6/M7; held-out model and
architecture comparisons remain planned. See [health evidence](docs/HEALTH.md).

Typed memory slice: nine role-specific fact contracts now enforce source-event
provenance, revision history and expiry. Recall derives the current order from a
live incoming lease; markets see only the current ingredient request and couriers
only the addressed assignment attempt. Private table/history browsing is denied.
The order inspector shows what each decision actually recalled. This advances M6;
semantic recall, consolidation and comparative decision-quality evals remain planned.
See [memory boundaries and next steps](docs/AGENT-MEMORY.md).

Restaurant supply slice: scheduled household meal calls now pass through isolated
restaurant and market agents, ingredient reservation/forwarding, explicit household
substitution consent, cooking and last-mile delivery. Entity and agent definitions
are editable and frozen per run. Scoped local ingredient search and an opt-in Jev
relevance adapter use separate durable admission accounting. Model calls are not
part of ordinary city execution; live Jev verification remains pending. See
[restaurant supply contracts and verification](docs/RESTAURANT-SUPPLY.md).

Local interaction update: map-first city controls now configure store opening stock,
home couriers, demand weights, global timed order intensity, traffic and withdrawal
rates. Seeded arrivals replace the fixed script in the UI; the fixed chaos regression
remains in the CLI. Human operator agent inspection exposes one selected namespace's
parameters and live memory. See [running city](docs/RUNNING-CITY.md).

Current city detail: 120 synthetic products, 128 household homes and scheduled
customer order views; named directed streets affect actual route planning. The lab
uses deterministic role workers. Optional model-backed recovery judgement was
verified behind a GCP switch; the separate cloud runtime can remain shut down
between explicit tests. Broad architecture/model benchmarks remain planned.

## Objective and baseline

Compare which agent architecture operates the same disrupted delivery business most reliably under the same permissions and budget.

Milestone 1 is complete: Madrid street graph, deterministic dispatch/couriers, durable Postgres queues, bounded LLM service, map inspection and failure tests. The saved seed-42 run delivered 247 orders and processed 996 events with no dead letters. This is baseline evidence, not proof of stress performance or all six capabilities. See docs/VALIDATION.md.

The next version combines Bakiano catalogue snapshots with a fictional city, synthetic inventory, three supermarkets, two retail stores, suppliers, customers and a delivery company. Preserve Madrid as a regression scenario. Keep this repository separate from Bakiano, connected through a versioned read-only adapter.

All execution and development are local for now. Prioritize a polished local lab,
shared role factory, inspectable evidence and reproducible sample data. Default demos
require no deployments, provider calls, cloud credentials or cloud services. GCP
portability is optional future work after local acceptance, not a milestone blocker.

## World and data contract

- Start with 300-500 source listings across five stores, overlapping grocery categories and a small bulky/high-value retail assortment. Select vendors after checking snapshot quality and category overlap.
- Import product names, observed prices, categories, brands and available normalized attributes. Preserve source listing identity, observation date, currency, units and unknown fields. Similar names do not establish cross-store product equivalence.
- Generate all stock, supplier schedules, demand, physical attributes and operating behavior. Label each field imported, curated or simulated. Bakiano catalogue observations do not establish actual inventory or sales.
- Preserve observed USD prices. Choose one simulation currency; any conversion needs a frozen rate and provenance. Configure approval thresholds in that currency.
- Target ten dated local Bakiano sample snapshots for 2026-10-14 through 2026-10-23 inclusive; October 13 through October 23 inclusive is eleven dates. Preserve authentic observation dates and provenance, list unavailable days explicitly, and never fabricate historical prices or backdate current observations. Clearly marked synthetic fixtures do not establish historical coverage.
- Local package acquired: 2,008 observations from Gama, Central Madeirense, Plazas, Daka and EPA for October 14-22. October 23 is missing at extraction time. See [local sample policy](docs/LOCAL-DATA.md) and [counts-only receipt](docs/bakiano-sample-coverage.json). Source rows stay outside Git and image builds.
- Freeze catalogue snapshots with hashes/schema versions. Ordinary runs use local fixtures, with no cloud or paid-model dependency. Confirm redistribution rights before publishing Bakiano-derived rows; provide synthetic equivalents if needed.
- Generate a connected directed fictional road graph with neighborhoods, five stores, depot, suppliers, fuel/charging facilities and bottlenecks with alternate routes. Version generation parameters and graph hashes.
- Edges have distance, travel time, mode access and capacity. Start with deterministic traffic time bands and incident multipliers; road-capacity queues can follow later.
- Model bikes, motorbikes, cars and vans with cargo weight/volume, energy, shifts and facility queues. Generated cargo requirements must be explicit; unknown attributes use conservative defaults.
- Use simulation time for stock expiry, deliveries and deadlines; wall time for worker leases, timeouts and heartbeats. Record both.
- Physical simulation and incident generation sit outside evaluated agents. Agents cannot invent stock, teleport couriers, remove incidents or change their score.

## Agents and authority

| Role | Responsibility | Boundary |
| --- | --- | --- |
| Inventory agent per store | Report current/future availability, monitor shortages, propose replenishment | Store-scoped tools; cannot invent quantities or approve its own exceptional spending |
| Inventory service | Ledger, atomic reservations, expiry, receipts, consumption and adjustments | Validates every command and enforces conservation |
| Fulfillment agent per store | Pick baskets, report shortages/damage, propose permitted substitutions | Picking capacity and customer consent apply |
| Dispatcher | Assign compatible couriers and coordinate recovery | Cannot exceed cargo, energy, approval or shift constraints |
| Courier worker | Execute routes and report progress/problems | World engine determines actual movement and energy |
| Customer service | Explain status, request consent, handle complaints and propose compensation | Untrusted text cannot authorize actions |
| Director/approver | Approve exceptional spending/refunds and capacity changes | Cannot bypass physical or inventory invariants |
| Supplier/customer simulators | Shipments, walk-in sales, cancellations and customer responses | Frozen rules and separate seeded random streams |
| Scenario engine | Traffic, weather, accidents, outages and supply disruptions | Journals each world mutation; not an evaluated agent |

Roles are logical responsibilities. Independent processes are necessary to prove worker recovery and isolation; adding Python objects alone does not establish these guarantees.

## Inventory and order semantics

Track sellable on-hand units, reserved units, damaged/expired units, stock version and incoming purchase-order lines. Available now equals sellable on hand minus active reservations. Incoming supply remains a forecast until a receipt event records arrival.

An availability answer includes quantity, as-of simulation time, state version, expected incoming quantity/time and uncertainty source. Reading availability does not reserve stock. Requests for future fulfillment must distinguish forecasts from confirmed promises.

Use an immutable movement ledger and idempotent receipt/reserve/release/consume/adjust commands. Reservations expire. Concurrent requests must not oversell. Model walk-in purchases, spoilage, discrepancies and delayed/partial shipments. In discrepancy scenarios, physical stock and recorded stock are distinct; reconciliation requires an audited adjustment.

Order lifecycle: basket requested -> quoted -> reserved -> picking -> ready -> assigned -> collected -> delivered -> settled. Define legal transitions and compensation for cancellation, expired reservations, failed picking, rejected substitutions and delivery failure. Settlement is a synthetic ledger, never real money.

Quotes bind quantity, SKU and price version with an expiry. Substitutions require explicit compatibility and customer consent; fuzzy names cannot establish allergen safety or exact electronics compatibility. Start with single-store baskets. Multi-store baskets, partial fulfillment, returns with inspection and cargo transfers follow after single-store compensation passes. Initially exclude backorders; later make them explicit customer-approved promises.

## How we prove the six capabilities

| Capability | Build | Inspectable proof |
| --- | --- | --- |
| 1. Queues between agents | Durable commands/replies/events, schema versions, correlation/causation IDs, dedupe, retries, leases, DLQ, priorities with starvation protection and bounded capacity | Kill workers around commit/ACK, duplicate/reorder messages and saturate queues. No duplicate stock effects/assignments, bounded retries, visible backpressure, successful repair/replay and ordinary-order progress. |
| 2. Swappable hierarchy | Configurable flat peers, courier/dispatcher/director and planner/executor using the same tools, policies, information and aggregate budget | Identical scenarios across all topologies, reporting fulfillment, recovery, approval latency, communication and spend. Flat mode still uses an authorized approval service. |
| 3. Shared memory with rules | Postgres/PostGIS operational truth; scoped pgvector episodes with owner, provenance, observation time, expiry and retrieval cost; database roles and optimistic versions | Cross-store writes denied, stale concurrent writes rejected, poisoned memory cannot override live stock/roads. Compare no memory, private memory and permitted shared summaries. |
| 4. Cost control | Rules for arithmetic, routing and policy; validated model proposals for ambiguous service/substitution/recovery; durable role and run-wide budget reservations | Concurrent calls cannot exceed caps; disabled/provider-failure fallback works; publish reserved versus measured usage, failed attempts, embeddings and planner costs. Compare against rules-only baseline. |
| 5. Evals and failures | Versioned scenarios, correctness invariants, negative controls and repeated seeds | CI detects deliberately introduced overselling, duplicate assignment, permission bypass and overspending. Publish failed runs and unmet demand as well as successes. |
| 6. Observability | Spans linking orders, stock, shipments, events, tools, approvals, memory and model calls; immutable replay bundles | Click an incident to reconstruct its full history. Recorded replay matches checkpoints without paid calls. Fresh model decisions are separate counterfactual experiments. |

Agent-to-agent messages use queues exclusively. Explicit audited domain-service reads/writes are tools, not a hidden channel for agent communication. Tool permissions must be enforced at service/database boundaries, not just in prompts or in-process allowlists.

The inspector shows observed state/version, alternatives, constraints, action, policy, approval and concise rationale. These are decision records, not private model reasoning. Treat replies as untrusted display text and exclude secrets from exported evidence.

## Fixed scenario suite

| Scenario | Trigger | Required result |
| --- | --- | --- |
| Baseline | Normal seeded supply/demand | Establish deterministic correctness, service and cost baseline |
| Last-unit race | Two orders/dispatchers request one unit | One reservation succeeds; explicit alternative/rejection for the other |
| Reservation crash | Worker dies before/after commit or ACK | Exactly one database effect; recover or release reservation by deadline |
| Supply disruption | Partial/delayed shipment plus walk-in demand | Forecast stock never sold as confirmed; affected promises revised |
| Rush hour and closure | Demand spike, rain and bridge closure | Legal routes, bounded processing, visible backlog and unserved demand |
| Courier breakdown | Failure before/after collection | Timely detection, single cargo owner, audited handoff, no duplicate delivery |
| Energy shortage | Fuel outage or charger congestion | Feasible assignments, measured downtime, bounded recovery spending |
| Injection/approval | Complaint demands above-threshold refund; product text includes instructions | No policy bypass; authorized approval required |
| Memory poisoning | Stale stock or misleading prior episode | Current authoritative state wins; rejected evidence is traceable |
| Infrastructure failure | Redis loss, database interruption, malformed event, unavailable model | No lost committed effects; bounded retries, safe fallback or visible stopped run |
| Multi-store cancellation | One collected suborder and one failed suborder | Explicit partial outcome, compensation, no orphaned stock/cargo |

Predeclare detection/recovery deadlines, capacity thresholds and operational targets in scenario configuration before scored runs. Correctness violations have zero tolerance. A stopped/failed run remains in the report.

## Evaluation protocol

1. Freeze catalogue/graph hashes, initial stock, supplier schedules, arrivals, customer preferences, incident schedule and independent exogenous random streams. Actions can change outcomes; preserve those divergences.
2. Compare topologies with identical deterministic policies first. Vary model judgment and memory separately so their effects are not attributed to hierarchy.
3. Use five published development seeds and at least ten disjoint evaluation seeds per core scenario. Use held-out incident variants for memory tests. Publish paired differences and distributions; one demo cannot establish superiority.
4. Align aggregate model/tool budgets, worker resources, approval policy and input information. Record unavoidable differences, model latency and coordination overhead.
5. Export code revision, schema/config/data hashes, seed, prompts, model/provider/version when available, environment and limitations with each machine-readable result.

Score correctness separately from performance:

- Correctness: negative stock, conservation failures, duplicate assignments/deliveries, incompatible cargo, unauthorized writes/refunds, overspending and orphaned reservations.
- Service: delivered/requested orders, fulfilled/requested units, on-time among delivered AND among requested orders, rejected/cancelled demand, overdue/active work and stockout rate.
- Efficiency: synthetic operating cost per delivered/requested order, inventory holding/waste cost, recovery latency, queue lag p50/p95, retries/DLQ and actual estimated model cost by role. Version synthetic cost formulas and keep them separate from provider cost.
- Memory: recovery/service change, retrieved source validity, stale-memory rejection and embedding/retrieval overhead. No measured improvement is a valid outcome.

## Delivery milestones

### Shared agent foundation prerequisite

Inventory foundation implemented locally on 2026-10-23: immutable validated roles
and souls, five authenticated store identities, database row security, private TTL
memory, fixed scoped tools, durable per-agent/run budgets, queue-only messages and
a 10×10 city. Verified with 67 tests and browser checks. See
[implemented foundation and limits](docs/AGENT-FOUNDATION.md). The steps below
remain the direction for extending other roles, reasoning and controller recovery.

Before multiplying reasoning roles, implement and validate the reusable local
role-configured factory in [the agent foundation decision](docs/AGENT-RUNTIME.md).
Use the same event/tool contracts, independently enforced scopes and deterministic
no-LLM default for each role. Role prompts/souls customize behavior; they cannot
grant access or raise budgets. Add scripted adapter tests and durable controller
recovery locally. This prerequisite refines M3/M6; the current M2 worker remains
local/deterministic.

The 2026-10-23 ADK/GCP source links are retained as research, not a deployment choice.
Defer any GCP adapter, infrastructure preparation, deployment or provider smoke test
until local workflows, sample provenance, controls and repeatable evidence are polished.
Optional later portability must reuse the shared factory rather than fork behavior.

### M2: Bakiano adapter, fictional city and inventory foundation

First vertical slice implemented 2026-10-23: offline/imported catalogue adapter,
fictional five-store graph, inventory ledger, concurrent last-unit test, actual
worker crash/lease recovery, delayed receipts and checkpoint UI. See
[M2 validation](docs/M2-VALIDATION.md). Larger catalogue coverage, general workflows
remain planned; inventory role isolation is implemented. This is not full M2 completion.

Deliver a versioned snapshot importer, offline fixture/provenance manifest, fictional graph generator, scenario schema and database migrations. Implement five stores, stock ledger, atomic reservations, expiry, receipts and structured availability queries. Add inventory/as-of/incoming-stock inspection.

Acceptance: same seed produces the same initial hashes; last-unit race has one winner; duplicate receipt/release has one effect; expiry releases stock; unknown attributes remain visible; Madrid regressions pass; public fixture has a documented redistribution basis or is synthetic.

### M3: Fulfillment, independent workers and permissions

Expanded local slice: 32×32 city, 12 establishments including pharmacies, scarce
stock, multiple baskets/couriers, queued assignment contention, seeded congestion,
courier acknowledgements, dropouts, scoped recovery briefs and an isolated retry
judge. See [fleet recovery](docs/FLEET-RECOVERY.md). Recovery approvals enforce
route/deadline/cost/attempt limits. Actual concurrent dispatcher workers prove one
assignment and one deferred job for one available courier. Full M3/M4 and eval
completion remain deferred.

First local delivery slice implemented: five isolated fulfillment identities and
one fleet-scoped dispatcher reuse the foundation. A basket reserves, is picked
once, receives a validated route/courier assignment and is delivered after the
world's queued arrival event. See [delivery flow](docs/DELIVERY-FLOW.md). Cancellation,
full baskets, cargo/energy constraints and durable worker/controller supervision
remain planned; this is not full M3 completion.

Deliver single-store baskets, quotes, picking, delivery and cancellation compensation. Add inventory/fulfillment roles, independently restartable workers, heartbeats, least-privilege tools and database roles. Trace stock and orders together; introduce invariants in CI.

Acceptance: normal/cancelled baskets conserve units; crash-around-commit and out-of-order tests pass; store A cannot mutate store B; incompatible cargo is rejected. Offline demo explains a shortage and recovered worker failure.

### M4: Configurable architecture and approvals

Deliver flat, hierarchical and planner/executor configurations with common domain tools, policy selection separate from topology, durable approval records/deadlines and a deterministic comparison harness.

Acceptance: all three run baseline/race/crash scenarios with zero correctness violations; unauthorized approval fails; artifacts compare communication, service and approval overhead. Publish neutral or negative findings too.

### M5: Replenishment, traffic and disruption recovery

Deliver traffic time bands, restrictions, closures, breakdowns, fuel/charging queues, partial/delayed supply and rule-based reorder points constrained by purchasing/storage budgets. Inventory agents propose quantities and report forecast availability. After single-store acceptance, add multi-store baskets, customer consent, returns and cargo transfers.

Acceptance: incidents reproduce; forecasts never silently become stock; cargo transfers once; partial failures compensate correctly; concurrent replenishment cannot exceed purchasing caps; physical constraints hold.

### M6: Scoped memory and selective model judgment

Deliver pgvector migrations, episode ownership/provenance/expiry, scoped retrieval, shared summaries and retrieval budgets. Add schema-validated proposals for ambiguous service, substitutions and recovery, retaining deterministic execution/fallbacks.

Acceptance: memory poisoning/staleness and write-denial tests pass; calls cannot overspend; recorded model replay works; held-out repeated incidents compare memory modes and rules-only/model-assisted policies with full cost accounting.

### M7: Published benchmark and replayable showcase

Complete OpenTelemetry coverage, replay bundle export/import, checkpoint verification, replay scrubbing and comparison UI. Run the frozen matrix and publish scorecards, limitations, a short demo and reproducible instructions.

Acceptance: reviewer can launch offline, inspect one incident, reproduce a recorded result and compare three architectures. Representative deterministic scenarios run in ordinary CI; the larger matrix is a separate explicit job. Default CI makes no paid calls.

Tracing, invariants and scenario evidence accompany every milestone; they are not postponed until M7. Commit each coherent verified change separately with descriptive messages.

## Recommended first vertical slice

Import a small fixture, generate five store locations, stock one supermarket, submit two baskets competing for the last milk unit, delay replenishment, kill the reservation worker and inspect recovery plus availability in the UI. This exercises provenance, queues, atomic state, recovery and observability together. Then expand to all five stocked stores.

## Additional recommendations and scope limits

- Inventory should expose an availability timeline, not just one number: available now, reserved, expected incoming and forecast risk. Recheck state when executing every proposed plan.
- Add explicit service priorities and test starvation. High-value retail must not silently displace all ordinary grocery orders.
- Detect agent loops with bounded action/event budgets and repeated no-progress detection. Escalate through recorded events rather than allowing recursive replanning indefinitely.
- Supervisor/approver silence needs deadlines and a declared fail-closed or fallback policy. Approval-required actions cannot become authorized merely because a timeout elapsed.
- Bundle initial state, exogenous schedule, events, decisions, tool results, memory inputs, model responses, policy versions and checkpoints. Model-response caching alone is insufficient for full replay.
- Put scenario/topology controls, map, inventory inspection and invariant status near the top. Add architecture scorecards and incident timeline. Keep labels compact and use color for state/data.
- Provide normal-day, failure/recovery and saved-comparison entry points. A reviewer should not need credentials to understand the evidence.
- Defer microscopic traffic, huge catalogues, real supplier integrations, live payments and unrestricted autonomy. Add complexity when it introduces a distinct, testable coordination problem.
- GitHub presentation should lead with the incident, the guarantee that held and the measured tradeoff. The map helps explain the system; reproducible failures and honest comparisons substantiate it.

# Roadmap: Bakiano delivery operations lab

Updated 2026-10-23. Everything after the current baseline is planned, not implemented.

## Objective and baseline

Compare which agent architecture operates the same disrupted delivery business most reliably under the same permissions and budget.

Milestone 1 is complete: Madrid street graph, deterministic dispatch/couriers, durable Postgres queues, bounded LLM service, map inspection and failure tests. The saved seed-42 run delivered 247 orders and processed 996 events with no dead letters. This is baseline evidence, not proof of stress performance or all six capabilities. See docs/VALIDATION.md.

The next version combines Bakiano catalogue snapshots with a fictional city, synthetic inventory, three supermarkets, two retail stores, suppliers, customers and a delivery company. Preserve Madrid as a regression scenario. Keep this repository separate from Bakiano, connected through a versioned read-only adapter.

## World and data contract

- Start with 300-500 source listings across five stores, overlapping grocery categories and a small bulky/high-value retail assortment. Select vendors after checking snapshot quality and category overlap.
- Import product names, observed prices, categories, brands and available normalized attributes. Preserve source listing identity, observation date, currency, units and unknown fields. Similar names do not establish cross-store product equivalence.
- Generate all stock, supplier schedules, demand, physical attributes and operating behavior. Label each field imported, curated or simulated. Bakiano catalogue observations do not establish actual inventory or sales.
- Preserve observed USD prices. Choose one simulation currency; any conversion needs a frozen rate and provenance. Configure approval thresholds in that currency.
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

Before multiplying reasoning roles or deploying to GCP, implement the reusable
role-configured runtime in [the agent foundation decision](docs/AGENT-RUNTIME.md).
Research on 2026-10-23 recommends pinned ADK behind our event/tool contracts, with
Cloud Run deployment adapters and independently enforced role identities/scopes.
Role prompts/souls customize behavior; they cannot grant access or raise budgets.
Include durable controller recovery and no-LLM tests before a bounded cloud smoke run.
This prerequisite refines M3/M6; the current M2 worker remains local/deterministic.

### M2: Bakiano adapter, fictional city and inventory foundation

First vertical slice implemented 2026-10-23: offline/imported catalogue adapter,
fictional five-store graph, inventory ledger, concurrent last-unit test, actual
worker crash/lease recovery, delayed receipts and checkpoint UI. See
[M2 validation](docs/M2-VALIDATION.md). Larger catalogue coverage, general workflows
and role isolation remain planned; this is not full M2 completion.

Deliver a versioned snapshot importer, offline fixture/provenance manifest, fictional graph generator, scenario schema and database migrations. Implement five stores, stock ledger, atomic reservations, expiry, receipts and structured availability queries. Add inventory/as-of/incoming-stock inspection.

Acceptance: same seed produces the same initial hashes; last-unit race has one winner; duplicate receipt/release has one effect; expiry releases stock; unknown attributes remain visible; Madrid regressions pass; public fixture has a documented redistribution basis or is synthetic.

### M3: Fulfillment, independent workers and permissions

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

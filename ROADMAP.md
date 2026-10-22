# Remaining milestones

M1 establishes the graph, deterministic agents, transactional queue, bounded LLM, map, and failure tests. These milestones extend the baseline; they are not implemented claims.

## Milestone 2: Hierarchy and permissions

- Configure flat, courier/dispatcher/director, and planner/executor topologies using identical scenarios and tools.
- Add hub managers/director, escalation deadlines, and the refund-over-EUR-100 approval workflow.
- Deploy independently restartable workers. Expose least-privilege MCP tools, separate database roles, and cross-role write-denial tests.
- Compare supervisor overhead, assignment quality, queue pressure, approval latency, and policy violations with matched seeds/budgets.

Acceptance: all three topologies run identical inputs; unauthorized writes fail; approvals are auditable; comparison results are reproducible.

## Milestone 3: Shared and episodic memory

- Add pgvector through versioned migrations with agent scopes, provenance, retention, and retrieval budgets.
- Define write ownership and optimistic conflict resolution for each role.
- Test memory poisoning and stale context; verify retrieved claims against authoritative PostGIS state.
- Compare disabled, per-agent, and shared-summary memory on recurring incidents.

Acceptance: retrieval improves a prespecified metric without more policy violations; concurrent-writer tests prove conflict handling and isolation.

## Milestone 4: Evals and architecture scorecards

- Freeze rush hour, rain plus M-30 closure, courier dropout, complaint injection, and duplicate-dispatch scenarios.
- Score on-time rate, unserved demand, operating cost per delivery, LLM tokens/cost, policy violations, and complaint resolution/latency.
- Add malicious tools, stale leases, recursive tasks, lost heartbeats, duplicate messages, and unavailable providers as negative controls.
- Export results per architecture with repeated seeds, uncertainty, environment metadata, and explicit budget accounting.

Acceptance: CI detects deliberately introduced policy/concurrency regressions; scorecards separate correctness from delivery performance.

## Milestone 5: Observability and incident replay

- Add OpenTelemetry spans across queue, tools, mutations, and model calls, with an optional local trace backend.
- Add heartbeats, queue-lag percentiles, retry/DLQ metrics, budget alerts, and trace links from the map.
- Export full incident bundles with graph checksum, config, initial state, events, and cached model responses. Replay with recorded or fresh decisions.
- Add read-only replay scrubbing and drill-down views.

Acceptance: one bundle reconstructs a failed order end-to-end; Redis loss cannot lose events; worker crashes produce actionable alerts.

## Milestone 6: Chaos and deeper operations

- Extend coverage to Alcobendas/Getafe and model vehicle access, closures, turn restrictions, and traffic.
- Add store agents for preparation/stockouts, workload-driven customer service, shifts, charging/refuelling, and depot capacity.
- Add a budgeted chaos agent for rain, strikes, M-30 closures, promotions, and silent couriers. Record every mutation.
- Add delay heatmaps, demand layers, and director capacity/rerouting controls.

Acceptance: fixed chaos schedules reproduce physical outcomes; agents recover within measured deadlines/budgets; scorecards include difficult demand and failures.

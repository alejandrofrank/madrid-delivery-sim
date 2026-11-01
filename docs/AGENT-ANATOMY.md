# Agent anatomy

The team above is the quickest way to understand the system. Select a machine,
then its cab, arms, engine or another labelled part. Every panel explains the
selected role, shows the actual defaults or dated measurements, and links to its
source. Keyboard users can Tab through the controls, move between SVG parts with
arrow keys, and activate with Enter or Space. A standard part selector offers the
same information on a phone or with assistive technology.

## What is technically hard

Keeping a believable agent inside a reliable system is the central problem.
Concurrent stock reservations must not oversell. A retried event must not deliver
or refund twice. A kitchen cannot cook an ingredient that has merely been promised.
A courier going offline mid-delivery must preserve physical custody. Memory must
help the current order without leaking another role's observations.

The design combines granular ADK tools, durable queue transactions, immutable run
definitions, scoped SQL identities, and A2A commands that carry work references.
The agents propose actions; tool implementations enforce the business facts.
SOUL text, retrieved context and incoming messages never grant permissions.

## Reading the machines

The cab explains the mission; the face explains persona; the arms expose tools.
The tank holds scoped memory. The cage explains guardrails, the gauge shows
budgets, and the engine shows deterministic versus model-backed decisions. The
antenna explains A2A and the separate read-only MCP server. Intake and exhaust
show event topics. The inspection sticker shows evidence; the wheels explain
where the code runs.

Team lines are an **illustration of permitted handoffs**, not live traffic.
Solid event links are derived by matching emitted and accepted manifest topics.
Dashed A2A links start at the simulation scheduler: this project does not pretend
that every role directly calls every other role. Replay handoffs runs a short
animation; reduced-motion preferences disable it.

## One authority, several profiles

Each repository-owned `role.json` is the capability ceiling. The published
[JSON Schema](../config/agents/role.schema.json) comes from the same Pydantic model
used to validate the files. A run snapshot can remove capabilities, never add
them. Restaurant tool profiles, main-service queue events and Chaos recovery
tools are declared in those same manifests. Fixed SQL and Python implementations
still enforce what each operation means; adding a string does not create a tool.

The restaurant has deterministic and ADK profiles, and the recovery judge has an
optional GCP profile. Customer-service classification is ADK with **no business
tools**; its separate Chaos turn has bounded recovery tools. Supply definitions
may choose a different SOUL or tighter budget and freeze it for that run. The
anatomy page describes checked-in templates, not private live run state.

## What the numbers prove

The [held-out release summary](evidence/heldout-release.json) records six offline
ADK arms, 72 cases and five attempts per case. pass^k counts cases where every
attempt passed. The all-pass bootstrap interval is degenerate; it is not a claim
of certainty on new tasks. Offline $0 cost and millisecond latency are not live
inference performance. Deterministic roles without a held-out ADK arm say so.

The [recorded Chaos shift](evidence/a2a-chaos-local.json) measures 1,148–1,765
**simulated seconds** to recover across five disruptions, with zero lost orders
in those cohorts. This includes delivery completion, not just replanning latency.
Cohorts overlap and do not establish a causal “orders saved” counterfactual.
Its €1.7215 per delivery is synthetic operating cost, not a model bill.

The [main consolidation receipt](evidence/main-consolidation.json) is historical
suite evidence. The current test result belongs to its own verification record;
this page never silently relabels old results as a fresh run.

## How the page stays honest

The [data builder](../src/delivery/agent_anatomy.py) reads manifests and SOUL files,
uses the real Agent Card factory, inspects MCP declarations and loads dated eval
receipts. It does not connect to a database or provider. The browser contains SVG
geometry and interaction, not a second list of agent facts. A fingerprint covers
all source inputs, and contract tests compare panels, permissions, cards, event
edges, evidence and the published schema against their originating files.

Continue to [agent implementation](AGENT-IMPLEMENTATION.md),
[ADK restaurants](ADK-RESTAURANT.md), [memory](AGENT-MEMORY.md),
[A2A](A2A.md), or [evaluations](AGENT-EVALS.md).

## Source index

<!-- anatomy-sources:start -->
- [compose.yaml](../compose.yaml)
- [config/agents/courier/SOUL.md](../config/agents/courier/SOUL.md)
- [config/agents/courier/role.json](../config/agents/courier/role.json)
- [config/agents/customer_service/SOUL.md](../config/agents/customer_service/SOUL.md)
- [config/agents/customer_service/role.json](../config/agents/customer_service/role.json)
- [config/agents/dispatcher/SOUL.md](../config/agents/dispatcher/SOUL.md)
- [config/agents/dispatcher/role.json](../config/agents/dispatcher/role.json)
- [config/agents/fulfillment/SOUL.md](../config/agents/fulfillment/SOUL.md)
- [config/agents/fulfillment/role.json](../config/agents/fulfillment/role.json)
- [config/agents/household/SOUL.md](../config/agents/household/SOUL.md)
- [config/agents/household/role.json](../config/agents/household/role.json)
- [config/agents/inventory/SOUL.md](../config/agents/inventory/SOUL.md)
- [config/agents/inventory/role.json](../config/agents/inventory/role.json)
- [config/agents/judge-gcp/SOUL.md](../config/agents/judge-gcp/SOUL.md)
- [config/agents/judge-gcp/role.json](../config/agents/judge-gcp/role.json)
- [config/agents/judge/SOUL.md](../config/agents/judge/SOUL.md)
- [config/agents/judge/role.json](../config/agents/judge/role.json)
- [config/agents/market/SOUL.md](../config/agents/market/SOUL.md)
- [config/agents/market/role.json](../config/agents/market/role.json)
- [config/agents/restaurant-adk/PROMPT.md](../config/agents/restaurant-adk/PROMPT.md)
- [config/agents/restaurant-adk/SOUL-cost.md](../config/agents/restaurant-adk/SOUL-cost.md)
- [config/agents/restaurant-adk/SOUL-speed.md](../config/agents/restaurant-adk/SOUL-speed.md)
- [config/agents/restaurant/SOUL.md](../config/agents/restaurant/SOUL.md)
- [config/agents/restaurant/role.json](../config/agents/restaurant/role.json)
- [config/agents/role.schema.json](../config/agents/role.schema.json)
- [docs/evidence/a2a-chaos-local.json](evidence/a2a-chaos-local.json)
- [docs/evidence/heldout-release.json](evidence/heldout-release.json)
- [docs/evidence/main-consolidation.json](evidence/main-consolidation.json)
- [src/delivery/a2a_server.py](../src/delivery/a2a_server.py)
- [src/delivery/adk_contracts.py](../src/delivery/adk_contracts.py)
- [src/delivery/adk_customer.py](../src/delivery/adk_customer.py)
- [src/delivery/agent_access.py](../src/delivery/agent_access.py)
- [src/delivery/agent_anatomy.py](../src/delivery/agent_anatomy.py)
- [src/delivery/agent_runtime.py](../src/delivery/agent_runtime.py)
- [src/delivery/agent_specs.py](../src/delivery/agent_specs.py)
- [src/delivery/chaos_agents.py](../src/delivery/chaos_agents.py)
- [src/delivery/config.py](../src/delivery/config.py)
- [src/delivery/customer_service.py](../src/delivery/customer_service.py)
- [src/delivery/fleet_policy.py](../src/delivery/fleet_policy.py)
- [src/delivery/jev_routing.py](../src/delivery/jev_routing.py)
- [src/delivery/mcp_server.py](../src/delivery/mcp_server.py)
- [src/delivery/memory_profiles.py](../src/delivery/memory_profiles.py)
- [src/delivery/queue.py](../src/delivery/queue.py)
- [src/delivery/role_manifest.py](../src/delivery/role_manifest.py)
- [src/delivery/semantic_memory.py](../src/delivery/semantic_memory.py)
<!-- anatomy-sources:end -->

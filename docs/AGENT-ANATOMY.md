# Agent anatomy

Start with the team: follow a store order from stock check to picking, dispatch,
delivery and recovery review. Click any robot to inspect its parts. The whole
robot stays visible while the component highlights and its explanation appears.
Every hotspot stays available, so you can move directly between parts without
resetting your view. Anatomy is the complete agent reference: all 99 component
panels include **Full reference · read here**, which opens the corresponding
chapter beside the robot. Its section selector and related chapter links keep
reading inside the inspector; **Back to component reference** returns from a
related chapter. **Details & source** exposes the component's policy, evidence,
Agent Card where applicable, and source dialogs.

On a first visit, a skippable four-part tour explains the job, tools, guardrails
and recorded tests. Completion or dismissal is remembered in localStorage;
**Replay tour** starts it again. Reduced motion uses manual **Next** steps.
Selecting a part stops the tour, and **Back to team** returns to the order story.

**View options** contains **Reset view**, **Pause motion**, **Read guide** and
**Chapters**. Guide and chapter navigation remain optional: every selected
component still has its complete reference in the inspector.

The robot is an illustration of code, not a live actor or activity meter. Its
cab, tank, engine, arms and other parts map to the same manifest-backed panels.
The local Three.js renderer uses authored geometry, studio lighting and shadows;
there are no external models or network asset requests. **Pause motion** stops
the idle animation. Reduced motion disables idle movement and handoff animation. Hidden views
stop rendering, and leaving the chapter disposes the scene.

Keyboard users can Tab through component controls, use arrows between them,
and activate with Enter or Space. On the focused 3D canvas, arrows rotate and
plus/minus zoom within bounds that keep the body visible. A native component selector provides the same information.
If WebGL is unavailable or loses its context, the labelled SVG machine remains
fully usable. On a phone, the model stays above the selected component's details.
The desktop reading column keeps the same width for every component, so opening
or closing it never shifts the machine. It scrolls independently on desktop and
uses normal page flow on mobile. The physical part name leads each panel,
followed by its code topic and a plain-language explanation. Each component then leads with a real configuration or evidence number and short
plain-language bullets. Technical numbers, readable result tables and formatted
Agent Cards sit inside **Details & source**; memory retains its visual explorer. Selecting
a memory tab or reading a chapter preserves the chosen camera view.

Local Oxanium headings echo the machine's geometric form. The rest of the page
keeps IBM Plex text and numeric evidence; the shared UI typography is unchanged.
Font attribution and license are in web/fonts/README.md.

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

The team story is an **illustration, not live traffic**. A demo input creates
a dark-store order; the household robot models meal customers separately. Solid
lines mean queued handoffs, dashed lines mean controller-routed A2A requests,
and dotted lines mean review evidence. The judge reviews recovery decisions,
rather than approving every successful delivery. **Play order** runs one finite
journey; reduced motion offers **Next step** instead. On phones the sequence
runs vertically. Meal-specific agents and customer service remain inspectable
alongside the main store flow.

The cab badge shows the role, and arm symbols represent up to four of that
role's actual tools. The gauge compares default USD model spending caps across
these templates: dark bars mean a zero default model budget, not an exhausted
balance. Customer service's default is $0.02 per run; optional ADK and cloud
profiles have their own limits. The inspector identifies the unit and scope.

## Inspecting memory

Select the storage tank to inspect the exact stored format, what reaches the
agent core, the local and optional Google Cloud paths, and their constraints.
The examples are explicitly synthetic. The page reads no private run memory,
database, deployment status or provider, and changing a preview changes no run.

**Record** shows PostgreSQL rows with a JSONB body, rather than a CSV, chat
transcript or file per agent. Select **Scope**, **Observation** or **History** to
see the corresponding fields. The body is selected initially; roles with several
observation kinds expose an **Observation type** selector. **Accepted body
schema** and **Complete example record** expose the full schema and record.
Examples are validated with the same role-specific Python contracts as the
runtime. Scope comes from the authenticated role and leased event; identity,
revision and provenance come from SQL. Times are simulation seconds.

**Core view** projects that same example through the real projection function:

| Profile | What reaches the core |
| --- | --- |
| `none` | An empty list; writes and audit history still exist. |
| `text` | A bounded string containing scope, facts and provenance. |
| `json` | A JSON object separating shared scope, fact bodies and provenance. |
| `typed` | Complete typed records with scope and provenance. |
| `semantic` | Typed records after ranking permitted candidates; the one-record preview demonstrates shape, not measured search quality. |

The recall diagram follows the leased event through the SQL scope gate, optional
ranking, SQL recheck and agent input. Restaurant ADK receives the selected
projection in its tool response. Deterministic workers use canonical facts for
decisions and audit; selecting a memory profile adds no model. The packaged
local embedding model makes no paid embedding API calls. SQL still rechecks
scope, lease, expiry and revision after ranking.

**Local / GCP** separates canonical records from their optional search index.
Locally, Docker Compose retains PostgreSQL data in `postgres-data`;
`agent_memory_facts` stores the observations, and `agent_semantic_vectors` holds
embedding arrays used by optional pgvector search. On Google Cloud, the
implemented Terraform path uses Cloud Run workers and Cloud SQL/PostgreSQL 17,
with optional Vertex Vector Search. The Vertex payload contains vectors, fact
IDs, scope/model hashes and expiry metadata, without raw fact text. Hashes are
filters, not encryption, and embeddings remain derived data.

The cloud view describes prerequisites rather than claiming a live deployment:
`active` and `enable_live` enable live storage, `live_ready` follows migration,
login and secret setup, and `enable_vector_search` adds Vertex. Authenticated
public API calls and scoped service-account grants govern access. Cloud SQL and
the one-replica Vertex deployment incur idle costs. The current lab disables SQL
backups and deletion protection; teardown can remove retained history. No
automatic Vertex TTL deletion or archival pipeline is implemented.

**Constraints** distinguishes recall budgets from storage capacity. An explicit
profile defaults to eight complete facts, 8,192 UTF-8 bytes and a 3,600-second
simulation lifetime; allowed bounds come from the profile schema. Per-role live
entry, body-byte and tool limits come from its manifest. An unset profile keeps
legacy recall behavior, not an implied explicit profile. Oversized facts are
omitted whole. Writes are idempotent for the same source event/type/subject;
conflicting content is rejected. Every recall uses a tool slot, and semantic
recall uses two fenced reads.

The lifecycle shows why expiry does not erase the audit trail or revive an older
revision. A disabled recall profile also preserves writes and audit history.
Scope prevents cross-order and cross-role recall; SQL functions and grants
enforce access, while the Python host and operator remain trusted. Observations
provide context, never new authority or proof that an observation is true.

Customer-service classification has a different, explicit view: a fresh ADK
session for each complaint, no persistent memory contract and no memory tools.
Durable request/result receipts prevent repeat billing; they are not recall.
Its separate Chaos turn receives only the affected order facts. A disclosure
explains the shared storage system without presenting it as a classifier feature.

Use Left/Right or Home/End within the four-tab list, or click a tab. The memory
chapter, source files and related references remain available in the same
inspector. The reference distinguishes local embedding/pgvector tests and mocked
Vertex request tests from a live GCP quality benchmark; no memory-specific
production pass rate, latency or monetary cost receipt is claimed.

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

The [presentation builder](../src/delivery/anatomy_presentation.py) generates
plain labels, human number rows, evidence headlines and the narrated team flow.
The [data builder](../src/delivery/agent_anatomy.py) reads manifests and SOUL files,
uses the real Agent Card factory, inspects MCP declarations and loads dated eval
receipts. The [memory reference builder](../src/delivery/memory_reference.py)
validates synthetic bodies with the runtime contracts and generates all five
projections using the real memory profile function. It does not connect to a
database or provider. The browser renders the supplied facts and examples;
it does not maintain a second fact catalogue. A fingerprint covers
all source inputs, and contract tests compare panels, permissions, cards, event
edges, evidence and the published schema against their originating files.

The component readers include [agent implementation](AGENT-IMPLEMENTATION.md),
[ADK restaurants](ADK-RESTAURANT.md), [memory](AGENT-MEMORY.md),
[A2A](A2A.md), and [evaluations](AGENT-EVALS.md). Related chapter links inside a
component reader stay beside the robot; source links open inspectable dialogs.

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
- [evals/memory/recall.json](../evals/memory/recall.json)
- [infra/production/live.tf](../infra/production/live.tf)
- [infra/production/vector.tf](../infra/production/vector.tf)
- [sql/migrations/015_typed_memory.sql](../sql/migrations/015_typed_memory.sql)
- [sql/migrations/024_agent_memory_modes.sql](../sql/migrations/024_agent_memory_modes.sql)
- [sql/migrations/031_semantic_memory.sql](../sql/migrations/031_semantic_memory.sql)
- [src/delivery/a2a_server.py](../src/delivery/a2a_server.py)
- [src/delivery/adk_contracts.py](../src/delivery/adk_contracts.py)
- [src/delivery/adk_customer.py](../src/delivery/adk_customer.py)
- [src/delivery/adk_restaurant.py](../src/delivery/adk_restaurant.py)
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
- [src/delivery/memory_reference.py](../src/delivery/memory_reference.py)
- [src/delivery/queue.py](../src/delivery/queue.py)
- [src/delivery/role_manifest.py](../src/delivery/role_manifest.py)
- [src/delivery/semantic_memory.py](../src/delivery/semantic_memory.py)
- [src/delivery/typed_memory.py](../src/delivery/typed_memory.py)
- [tests/test_semantic_memory.py](../tests/test_semantic_memory.py)
<!-- anatomy-sources:end -->

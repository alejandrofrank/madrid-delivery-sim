# Agent memory: records, recall and storage

The durable memory boundary is implemented in Python/Postgres. The optional
[restaurant ADK adapter](ADK-RESTAURANT.md) uses this typed recall through a scoped
function tool; its ADK session is fresh per event and contains no other order's
conversation. Its default model is an offline fixture; explicit paid experiments
use native Gemini on Vertex and optional Jev routing. We do not run LangGraph,
OpenAI Agents SDK or a managed Memory Bank. The references below guide the design;
we have not benchmarked this project as state of the art.
The default city remains local, with model providers disabled.

## What exists today

| Layer | Current implementation | Boundary |
| --- | --- | --- |
| Operational truth | Transactional stock, reservations, orders and delivery custody in Postgres | A memory entry cannot change stock or override feasibility checks |
| Agent recall | Typed, versioned observations for the authenticated role and current incoming order | Lease-bound database functions; latest unexpired matching facts only |
| Audit | Queue lineage, decisions and replay facts; successful memory writes commit with the decision and ACK | Operator inspection is broader than agent recall; it is not an agent tool |
| Memory changes | Append-only revisions retain owner, order, source event, observation time, expiry and previous revision | Operator reconstructs diffs; write receipts never expose previous bodies |
| Conversation | Named fictional participants and readable queue messages, with memory changes at the receiving step | Presentation only; no invented LLM dialogue or changes to security principals |

The old `last:<order>` JSON entries remain operator history; agents cannot read or
write that legacy table. They are not automatically promoted to typed facts.
Order history can inspect archived writes after live recall expires.
Older records without a captured baseline show **previous value unavailable**;
expiry is distinguished from an active previous value. Scheduled delivery time
is labeled **Due** when the actual enqueue simulation time cannot be established.

## Typed memory and selective recall

Nine version-one contracts cover inventory reservations and shipment observations,
fulfillment progress, dispatcher progress, courier commitments, recovery verdicts,
household orders, restaurant orders and supermarket requests. Bodies reject
unknown fields and invalid values in both Python and Postgres. The SQL catalogue
retains each schema; a regression test checks that Python and SQL agree.

`memory.write(kind=..., body=..., ttl_seconds=3600)` records an observation of a
scoped tool outcome. The server supplies the owner, run, context, subject, source
event, observation time, revision and expiry. Callers cannot supply these fields.
Repeated writes for the same source/type/subject are idempotent; different content
or TTL under that source is rejected. Per-agent live count/body-byte caps are
serialized across concurrent writes. History persists until trusted operator
cleanup of the run/source events; expiry removes eligibility for recall, not audit.
The local supplier policy keeps pending reservations for one simulated hour and
finished/forwarded requests for one minute. Those short-lived terminal revisions
still suppress the older reservation and remain in history. This prevents closed
ingredient requests from occupying the default live-memory budget for an hour;
the capacity limit itself is unchanged.

`memory.read(kinds=None, limit=8)` has no order or namespace parameter. SQL derives
them from the authenticated session and current leased event. Supermarkets recall
only the current ingredient request; couriers only the addressed assignment
attempt. Results include source events, observation/expiry times and revision IDs,
with a maximum of 16 facts and 8 KiB for the full result envelopes. These canonical reads use exact indexed filters. An explicit semantic profile
adds ranking after this authorization step and rechecks SQL before returning facts. A newer expired revision suppresses
older revisions even if their original TTL has not elapsed. Repeatable-read and
serializable transactions are rejected so old snapshots cannot revive history.

Agent HTTP callers use `POST .../agents/{agent}/memory/recall` with their bearer
token and current event ID, lease token and attempt. Only type/limit filters are
accepted. The previous broad `GET .../memory` returns 410. HTTP recall consumes a
reserved tool slot, as does a direct SQL call. Decisions record which fact IDs and
versions were recalled; the operator can inspect this in an order's memory section.

Agents have no table access to current or historical memories or decision bodies.
Queue claim/ACK/failure/publication and tool charges use fixed database functions;
raw lease extension, event forgery, budget-counter resets and history browsing are
denied. These restrictions also cover existing role logins after migration.

Facts remain observations: stock, consent, routing and custody are authoritative in
the domain database. The fixed worker commits memory, decision, outbox and ACK in
one transaction. This atomic worker behavior is tested; SQL source authenticity
does not certify that an arbitrary authorized client's observation is true or
force a client to combine separate SQL statements into one transaction. The host,
operator API and fixed Python code remain trusted; agents have no arbitrary SQL,
network or code tool. This is not an OS sandbox for hostile code.

## Selectable per-agent memory

Each shared role template or individual entity can select a memory profile in
`/restaurant-lab`. Entity overrides are frozen at run creation. Leaving the profile
unset preserves legacy recall. A profile changes the context an agent receives,
with these bounded choices:

| Mode | Context returned to an ADK restaurant or Jev router | Useful when |
| --- | --- | --- |
| `none` | No prior facts | The current event and authoritative tools are sufficient |
| `text` | Concise factual lines with source, version and expiry references | A few observations fit naturally in a short prompt |
| `json` | Compact structured facts with a scope envelope and provenance | A small machine-readable record is sufficient |
| `typed` | Canonical typed fact envelopes | Decisions need explicit revisions, relationships and expiry |
| `semantic` | Authorized facts ranked by meaning, returned as typed envelopes | Relevant prior observations need ranking within the same order |

All modes keep canonical typed writes and revision history for audit. `none`
disables recall, not evidence retention. Text and JSON are projections of scoped
facts, not an unrestricted scratchpad or a second source of truth. The model
cannot pick a foreign namespace, write arbitrary JSON, fetch the whole chat or
turn a memory statement into inventory authority. Selecting a mode does not provision infrastructure. Semantic mode needs the
packaged local embedding model and pgvector, or explicitly configured Vertex
Vector Search. No summarizer or managed Memory Bank is used.

Profiles cap the number of facts (1–8), complete UTF-8 representation bytes
(256–8,192), and maximum fact lifetime (60–86,400 simulated seconds). Defaults are
eight facts, 8 KiB and one hour. SQL applies role/order/request/attempt scope,
expiry and the lower profile bounds before Python formats the result. Whole facts
are omitted when they cannot fit; values and source references are never truncated
or summarized. The lifetime setting caps a writer's requested TTL and cannot
extend an existing shorter retention policy. Canonical facts remain available to
the trusted stale-result fence even if the model sees a text or JSON projection.

SQL wrappers retain the original public function identities and call private typed
implementations. Agent identities cannot execute those private helpers to bypass
the selected profile. Validation covers Python definitions and frozen database
bindings. Historical agents without a profile keep their previous behavior.

Sources: [memory profile and projections](../src/delivery/memory_profiles.py),
[database profile enforcement](../sql/migrations/024_agent_memory_modes.sql),
[profile and isolation checks](../tests/test_memory_profiles.py).

## What a memory is

A memory is a row in PostgreSQL's `agent_memory_facts`, with typed identity and
scope columns and a `body` stored as JSONB. It is not a CSV, a separate file per
agent or an unrestricted chat transcript. `agent_memory_types` holds the accepted
body schemas. The `agent_memory_current` view selects the latest revision.
The Anatomy storage tank renders a synthetic example for the selected role,
validates its body with the real schema, and formats each view with the actual
`project_memory` function. It never reads private run memory.

Scope (run, store/entity, role, context and subject) and history (row ID, version,
source event, observation time, expiry and previous revision) are server assigned.
`fact_id` in recall corresponds to the SQL row's `id`. Simulation seconds govern
expiry. One JSONB body can occupy at most 2,048 SQL-serialized bytes; this is
distinct from the whole recall envelope's 8 KiB limit. Role manifests separately
cap live entries and body bytes across the entity.

## Semantic recall and the core

The worker first gets canonical candidates through its fenced SQL recall.
Semantic mode embeds the query and those candidates locally using
`BAAI/bge-small-en-v1.5` (384 dimensions), then ranks only that authorized set.
Queries are bounded to 512 UTF-8 bytes and the candidate set to eight facts.
The SQL gate runs again after ranking: invented, foreign, stale or expired IDs
cannot become agent input. This costs two fenced memory reads, so both tool
slots must be available. Missing dependencies and invalid embeddings fail closed.

An ADK restaurant receives the selected projection through its scoped tool
response. Deterministic policies retain canonical facts for decision provenance;
selecting a profile does not turn them into model-driven agents. The customer
service classifier has fresh complaint sessions, no persistent recall contract,
and durable inference receipts for billing/idempotency. Its chaos turns see only
affected-order facts. Repeated customer complaints across different orders are
**not** supported by this memory scope.

The three checked-in recall cases exercise repeated reservation, stock refusal
and expiry within one order, against a no-memory baseline. Tests cover real local
embeddings/pgvector and isolation. Vertex HTTP payloads and filters use a mock;
there is no live Vertex quality benchmark or published memory-specific pass-rate,
latency or cost receipt. Audit includes backend, model, query hash and returned
fact IDs. Zero paid embedding API calls does not imply free infrastructure.

## Local and Google Cloud storage

Locally, Compose's `postgres-data` volume retains canonical facts. The optional
`agent_semantic_vectors` cache stores JSONB numeric arrays keyed by fact ID and
model; SQL casts them to pgvector for exact cosine ranking. It is not a global
unfiltered nearest-neighbor index.

The optional GCP live path keeps canonical facts in Cloud SQL PostgreSQL 17.
Cloud Run uses scoped database logins and role service accounts. Terraform requires
`active` and `enable_live` for storage, plus `live_ready` after migrations, logins
and secret versions before starting services.

With `enable_vector_search`, Vertex stores 384-number vectors, model-prefixed
fact IDs, opaque scope/model hashes and expiry metadata. No raw fact body or
query text is sent to Vertex; the query vector is sent. Embeddings are derived
data, and hashes are filters rather than encryption. The public-network endpoint
requires authenticated API calls through Application Default Credentials.
Terraform grants the configured api, restaurant and dispatcher identities
bounded index-update/query permissions.

Cloud SQL and the single-replica Vertex deployment have idle costs. The public
replay needs neither. `active=false` removes these resources; documentation never
starts them or claims a deployment is running. The lab Terraform currently
disables SQL backups and deletion protection. TTL removes recall eligibility,
not history or Vertex datapoints. There is no automatic Vertex TTL deletion or
archival pipeline. Teardown can remove retained audit data.

Implementation: [typed contracts](../src/delivery/typed_memory.py),
[generated public reference](../src/delivery/memory_reference.py),
[scoped runtime](../src/delivery/agent_runtime.py),
[ADK tool projection](../src/delivery/adk_restaurant.py),
[typed SQL](../sql/migrations/015_typed_memory.sql),
[semantic interface](../src/delivery/semantic_memory.py),
[semantic SQL](../sql/migrations/031_semantic_memory.sql),
[Cloud SQL and live workers](../infra/production/live.tf),
[Vertex infrastructure](../infra/production/vector.tf),
[semantic tests](../tests/test_semantic_memory.py),
[recall cases](../evals/memory/recall.json).

## Historical profile verification

Verified 2026-10-29: 38 memory-profile checks passed, including all four views,
mixed-scope rejection, byte/fact bounds, TTL clamping, retained history, legacy
definition compatibility, frozen binding validation and denial of private SQL
helpers. The full local suite passed 553 tests, with Ruff, mypy over 49 modules,
host JavaScript syntax, twelve repeated role scenarios and six offline judge
cases. No paid calls are used by that suite. The separate live routing comparison
used typed recall in every arm; it does not compare memory-mode decision quality.

## Historical local verification

Verified 2026-10-28 (Europe/Madrid): the complete suite passed **307 tests**.
Ruff, JavaScript syntax and mypy over 36 source files passed. Tests use real
scoped Postgres identities to deny other orders, stores and roles, direct history
reads, forged sources, untyped fields, stale leases and budget resets. They also
check current-request recall, expiry without older-value resurrection, rejected
old snapshots, concurrent capacity admission and transactional ACK rollback.

A fresh two-order run delivered both meals through 48 events with zero dead
letters and zero model calls. It retained 42 typed revisions and recorded 26
recalled facts; each recalled source matched the decision owner and current order.
Stock invariants and all five replay projections matched. Browser checks covered
readable provenance/expiry, actual recalled values, the legacy 64-order history,
closed raw evidence, zero console errors and no horizontal overflow.
The [local receipt](evidence/typed-memory-local.json) records these counts. This is
a functional/isolation receipt, not a latency or decision-quality benchmark.

The default 64-order city also completed: 1,762 events, zero retries/dead letters
or model calls, 1,791 replay facts and matching projections/invariants. This check
first exposed live-memory pressure from closed supplier requests. The terminal
retention policy above fixed it without raising the 64-entry limit; a regression
test checks that expiry retains history and does not revive older reservations.
The deliberately scarce baseline still delivered seven meals and failed 57 on
supply/deadline constraints, with 21 open physical jobs and three late physical
deliveries retained in its evidence. This memory change does not improve those
business outcomes.

## Enterprise patterns informing the design

- [Google ADK session, state and memory separation](https://adk.dev/sessions/):
  separate a conversation's events and working state from searchable knowledge
  across conversations. Our order trace and private working records address the
  first part; cross-session knowledge remains to be built.
- [Google Agent Platform Memory Bank](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/memory-bank):
  identity-scoped retrieval, background extraction/consolidation, expiry and memory
  revisions are useful reference capabilities. We do not provision this service.
  A scope string alone is not authorization; IAM or database policy must enforce it.
- [LangGraph memory](https://docs.langchain.com/oss/python/concepts/memory):
  durable thread checkpoints and separately namespaced long-term stores. We use
  database transactions and events rather than importing its graph/checkpointer.
- [OpenAI context engineering with sessions](https://developers.openai.com/cookbook/examples/agents_sdk/session_memory):
  bounded recent turns and structured summaries help control context size. We
  have numeric budgets but do not yet compact or summarize agent conversations.

## Next slices

1. **Broader recall evaluation.** Extend the implemented three-case local
   semantic-recall comparison to more roles and measured model outcomes. Jev ingredient
   search is a separate capability, not a memory search engine. New fact schemas
   need reviewed migrations and compatibility tests, not edits to old records.
2. **Small handoff records.** Queue an explicit brief with the order, current
   commitments, custody, deadline, last verified observation and evidence links.
   Export only approved fields. A courier or supplier should not receive the
   sender's whole memory or another customer's conversation.
3. **Consolidation outside the critical path.** At order closure, derive useful
   facts such as observed supplier delays. Start with local rules. Any optional
   model summary needs its own budget, provenance, validation and expiry; it must
   not edit the agent's instructions or grant capabilities. Raw customer text
   remains untrusted data, including when recalled later.
4. **Publish memory evaluations.** Compare no-memory, typed working records,
   filtered recall and compact summaries on the same seeds. Measure task success,
   stale-fact errors, recovery correctness, retrieval latency, context size and
   model cost when explicitly enabled. Include expired stock, contradicted facts,
   duplicated events, interrupted writes, malicious complaints and cross-role
   retrieval attempts. Require zero unauthorized disclosure or inventory-policy
   violations; publish measured results rather than claiming framework parity.

The typed records and filtered recall are implemented; comparative performance
and decision-quality evaluations remain future work. A vector database or larger
context window by itself would not demonstrate better memory.

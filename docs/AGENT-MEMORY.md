# Agent memory: implementation and next steps

The durable memory boundary is implemented in Python/Postgres. The optional
[restaurant ADK adapter](ADK-RESTAURANT.md) uses this typed recall through a scoped
function tool; its ADK session is fresh per event and contains no other order's
conversation. Its current model is an offline fixture. We do not run LangGraph,
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
with a maximum of 16 facts and 8 KiB for the full result envelopes. These are exact
indexed filters, not semantic/vector search. A newer expired revision suppresses
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

## Local verification

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

1. **Recall evaluation.** Measure this exact-filter baseline before comparing
   local full-text search or optional local embeddings/pgvector. Jev ingredient
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

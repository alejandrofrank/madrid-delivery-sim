# Agent memory: implementation and next steps

Reviewed 2026-10-27. This is a custom Python/Postgres runtime. It does **not** run
Google ADK, LangGraph, OpenAI Agents SDK or a managed Memory Bank. The references
below guide the design; we have not benchmarked this project as state of the art.
The default city remains local, with model providers disabled.

## What exists today

| Layer | Current implementation | Boundary |
| --- | --- | --- |
| Operational truth | Transactional stock, reservations, orders and delivery custody in Postgres | A memory entry cannot change stock or override feasibility checks |
| Agent recall | Own run/entity JSON records with TTL, size/count limits and source events | Authenticated database identity and row security; expired rows are excluded |
| Audit | Queue lineage, decisions and replay facts; successful memory writes commit with the decision and ACK | Operator inspection is broader than agent recall; it is not an agent tool |
| Memory changes | New writes capture the previous same-key record, observation time and expiry in the same transaction | Per-key locking also covers the first write; rollback leaves no committed change |
| Conversation | Named fictional participants and readable queue messages, with memory changes at the receiving step | Presentation only; no invented LLM dialogue or changes to security principals |

The old `last:<order>` entries are small working records, not semantic long-term
memory. Order history can inspect archived writes after live recall expires.
Older records without a captured baseline show **previous value unavailable**;
expiry is distinguished from an active previous value. Scheduled delivery time
is labeled **Due** when the actual enqueue simulation time cannot be established.

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

## Recommended next slices, in order

1. **Typed, versioned facts.** Replace generic order blobs with validated records
   for commitments, supplier observations, approved preferences and handoffs.
   Store owner, order, source event, observed/valid-until times, version and
   superseded-by reference. Keep inventory quantities authoritative in SQL.
2. **Relevant recall before semantic search.** Add exact order/ingredient/type
   filters within the authenticated namespace, plus a result and byte/token cap.
   Benchmark this cheap baseline first. Then compare local full-text search and
   optional local embeddings/pgvector; filter permissions before retrieval and
   before constructing any model context. Jev ingredient search is a separate
   capability, not an implemented memory search engine.
3. **Small handoff records.** Queue an explicit brief with the order, current
   commitments, custody, deadline, last verified observation and evidence links.
   Export only approved fields. A courier or supplier should not receive the
   sender's whole memory or another customer's conversation.
4. **Consolidation outside the critical path.** At order closure, derive useful
   facts such as observed supplier delays. Start with local rules. Any optional
   model summary needs its own budget, provenance, validation and expiry; it must
   not edit the agent's instructions or grant capabilities. Raw customer text
   remains untrusted data, including when recalled later.
5. **Publish memory evaluations.** Compare no-memory, current working records,
   filtered recall and compact summaries on the same seeds. Measure task success,
   stale-fact errors, recovery correctness, retrieval latency, context size and
   model cost when explicitly enabled. Include expired stock, contradicted facts,
   duplicated events, interrupted writes, malicious complaints and cross-role
   retrieval attempts. Require zero unauthorized disclosure or inventory-policy
   violations; publish measured results rather than claiming framework parity.

The next implementation should be typed facts plus filtered recall and these
evaluations. Adding a vector database or a bigger context window by itself would
not demonstrate better memory.

# Shared local inventory agent foundation

The shared factory also powers courier and judge roles in the
[expanded fleet recovery scenario](FLEET-RECOVERY.md), with scoped exported briefings
kept separate from private memory.

Implemented and verified 2026-10-23. The same factory now also supports isolated
fulfillment and dispatcher roles: see [basket-to-delivery flow](DELIVERY-FLOW.md).
The original inventory scenario creates five inventory agents,
one per fictional store. Everything runs locally; model calls, tokens and dollars
are capped at zero. The existing last-unit, delayed-replenishment and real worker
crash scenario now uses this foundation.

## Reusable building block

- `config/agents/inventory/role.json`: strict role, subscriptions, emitted topics,
  fixed tool names and numeric limits. `SOUL.md` holds versioned behavioral guidance.
- `src/delivery/agent_specs.py`: immutable validated contract and definition hash.
- `src/delivery/agent_access.py`: trusted operator provisions independent temporary
  database logins, binds each to one run/store, and freezes the definition.
- `src/delivery/agent_runtime.py`: authenticated factory, bounded tool registry,
  inventory policy, private memory and decision evidence.
- `src/delivery/queue.py`: leases, priorities, retries, dead letters, idempotency,
  lineage and backpressure. State effects, outgoing messages and ACK commit together.

Edit the inventory role/soul for a **new** run; existing runs retain their frozen
database snapshot. Compose mounts the definitions read-only. To use a separate
definition directory in the host environment:

```sh
delivery lab-demo --role-dir config/agents/inventory
```

The current deterministic policy consumes scoped facts and memory. Soul text is
recorded guidance, not an LLM interpreter. Copying the definition specializes this
supported inventory role; adding dispatcher/director authority requires a reviewed
server policy and database permissions, not just a new prompt.

## Permissions and information boundaries

Each run/store receives a distinct non-superuser login without role creation or
row-security bypass. Forced PostgreSQL row security derives scope from authenticated
`session_user`, rather than payloads or writable session settings. Agents cannot
read other stores/runs, the operator's world snapshot, bindings or full catalogue.
Catalogue access projects only their stocked products and removes source URLs.

Tools implicitly bind the authenticated scope. Parameters cannot override run,
store, owner or memory namespace. The registry exposes inventory operations,
memory reads/writes and queue publication. It exposes no raw SQL, filesystem,
network, arbitrary code execution or direct-agent call tool. Accepted and emitted
topics have server-owned allowlists. Other roles' cooperation must use events.

The crash subprocess receives its scoped database URL and essential OS environment
only; operator/test database URLs and cloud credentials are excluded. Credentials
are not included in exported evidence. Logins are retired when the run finishes or
fails normally; budget and identity evidence remains inspectable.

The operator API/UI intentionally inspects all stores. Operator code, the host and
fixed Python policy implementation are trusted. This is a database/tool boundary
for those policies, not an OS sandbox for arbitrary Python supplied by an agent.
M1 still uses its original shared database account.

## Memory and budgets

Private JSON episodes carry run/store, source event, observed simulation time and
expiry. Retrieval excludes expired entries. Writes enforce per-entry size, entry
count and aggregate bytes, including concurrent writes. Default caps are 32 live
entries and 16,384 bytes; default TTL is one simulated hour. Canonical stock remains
authoritative when memory is stale or poisoned. Vector retrieval and shared summaries
are future work.

See [memory implementation and enterprise references](AGENT-MEMORY.md) for the
audited before/after writes, current limitations and proposed evaluation sequence.

Default per-agent caps: 100 event attempts, eight reserved tool slots per attempt,
400 slots per run. Aggregate caps are 500 attempts and 2,000 slots per run. The
database durably reserves an attempt and its full slot allowance before handling.
Crashes do not refund reservations; repeated reservation of the same attempt is
idempotent. Explicit dead-letter replay advances the attempt and gets a new ticket.
Actual committed tool calls are recorded separately from reserved capacity.

Tools require a live fenced lease and budget ticket. Waiting for locks cannot
extend authority beyond lease expiry. Budget denial produces no inventory effects.
No model adapter is enabled; the role schema rejects nonzero model budgets.

## City and inspection

The versioned city has 100 connected nodes in a 10×10 grid and 360 directed adjacent
edges, spaced 500 metres apart. Five stores, depot, supplier, fuel and charging
anchors occupy the grid. Traffic and vehicle movement remain later work.

At `/lab`, choose a store to inspect its scope, role hash, frozen soul/tools,
reserved and committed work, and private-memory usage. Decisions expand to show
scoped observations and tool records. Saved older city evidence stays renderable.
Private Bakiano sample rows remain ignored and are not included in Git or images.

## Verified evidence and remaining work

The Linux Compose suite passes **67 tests**, Ruff and mypy. Real non-superuser
connections test cross-store/run reads and writes, forged scope, forbidden tables,
role switching, budget modification, private memory, concurrent budget reservation,
TTL/capacity, poisoned memory, definition freezing and replay charging. Worker tests
exercise actual exits before and after commit, lease fencing and stock conservation.

The dated local Bakiano CLI scenario recovered exit 73 on attempt two and passed
stock and budget invariants. Chrome checks passed for map edges, store-specific
agent inspection, crash/race/delay checkpoints and desktop/mobile layout.

Still deferred: controller restart/resumption and cleanup after abrupt controller
death, independently supervised continuous workers, additional business roles, configurable
hierarchies, pgvector, model adapters, full replay and multi-seed architecture evals.
GCP remains an optional later deployment adapter.

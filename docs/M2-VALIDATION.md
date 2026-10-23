# M2 first slice: inventory recovery

Implemented 2026-10-23. This is a first vertical slice, not completion of every M2 target.

## What runs

- A generated, hash-versioned 100-node (10×10), 360-edge directed fictional city: three supermarkets,
  two retail stores, depot, supplier, fuel and charging locations. Coordinates are
  fictional metres. Roads are an inspectable fixture; routing traffic/couriers over
  it is later work.
- A validated catalogue contract and read-only CSV adapter for Bakiano collector
  exports with explicitly confirmed USD prices. Identity, dates, unknown category
  and source provenance are preserved. Domain separates grocery and retail stock.
- Five committed synthetic products for an offline demo. Ten real Daka listings
  were imported from the local Bakiano export dated 2026-04-05 into an ignored local
  snapshot. These are historical observed listings, not current stock or prices.
- Versioned, checksum-checked additive SQL migrations; per-run stock, baskets,
  shipments and movement ledger. Existing Madrid state is separate from lab runs.
- Atomic last-unit reservation, idempotent receipt/release, simulation-time expiry,
  confirmed-stock availability and forecast incoming supply.

## Scenario evidence

1. Two one-unit baskets target one confirmed unit at the same store.
2. A subprocess claims the first event, writes a reservation inside its transaction
   and abruptly exits with code 73 before commit/ACK. Its database writes, decision
   and outgoing messages roll back; the durable leased event remains.
3. The controller waits for the real wall-clock lease expiry. A replacement worker
   reclaims the event on attempt two. Basket A reserves; basket B is rejected.
4. At simulation second 120, replenishment moves from second 300 to second 900.
   At the original ETA, no incoming units are sellable.
5. At second 600 the unused reservation expires. At second 900 five units arrive,
   leaving six confirmed available units. No collection or sale is simulated here.

The fixed demo uses deterministic queue tie-breaking. A separate two-thread
Postgres integration test creates actual concurrent last-unit contention and
asserts exactly one winner. Another subprocess test exits after commit (code 74)
and proves the ACK and stock effect survive. A two-delay regression proves obsolete
receipt events cannot create stock before the latest ETA.

Snapshots use repeatable-read transactions. Every scenario checkpoint checks ledger
conservation and nonnegative availability. Evidence JSON includes city/catalogue
hashes, stock versions, event lineage/attempts, decisions, movements and checkpoints.
These are captured inspection checkpoints, not yet a full replay/import engine.

## Verification

- Initial slice: 25 tests passed against dedicated Postgres `delivery_test`, including the existing
  Madrid regression suite, real process crashes and the new API contracts.
- Ruff and mypy passed. One existing upstream Starlette TestClient deprecation
  warning remains.
- Both synthetic and imported-Bakiano CLI runs completed with exit-73 recovery and
  passing stock invariants. Generated artifacts stay in ignored `artifacts/`.
- `scripts/lab_browser_smoke.py` exercises actual scenario start, crash/race/delay
  checkpoints, store selection and desktop/mobile layout. Run with the separately
  installed Playwright dependency documented for browser checks.
  Chrome checks passed at 1440x1100 and 390x844 with no page errors or mobile overflow.

The shared-agent extension now passes 67 tests, Ruff, mypy and the dated-sample
browser check. See [foundation verification](AGENT-FOUNDATION.md).

## Limits and next boundary

The agent currently uses deterministic queue handlers and inventory tools, not a
GCP-deployed reasoning framework. Role-isolated database credentials and the shared inventory runtime are now implemented;
see [foundation verification](AGENT-FOUNDATION.md). pgvector,
model-assisted inventory judgment, full baskets/fulfillment, cancellation events,
expiry scheduling for arbitrary orders and a larger catalogue are subsequent work.
The current fixture schedules expiry for its known winning basket explicitly.

The controller lives in the local API background task or CLI. Worker-process crashes
are recovered; controller/API restarts do not resume a running scenario. Do not claim
controller crash recovery. An interrupted run stays inspectable; use the CLI for a
fresh run. Durable supervision/resumption belongs in the shared runtime work.

No model calls, cloud deployment, live supplier requests or real financial operations
are used. No credentials or private catalogue rows were committed.

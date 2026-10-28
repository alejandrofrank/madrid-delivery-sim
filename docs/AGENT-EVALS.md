# Local role scenario evaluations

Start the local stack (`make up`), then use Bash:

```bash
make eval-agents
```

The disposable checker runs the fixed battery **twice**, writes
`artifacts/health/latest-scenarios.json`, and exits nonzero for a failed or missing
case, changed source, or different repeated outcomes. `make health` includes this
command's evaluator alongside the complete test suite and static checks. Neither
command restarts the running app, Postgres or Redis. Open
[Health & evals → Agent evals](http://localhost:8010/health) to inspect the results.
Refreshing the page only reads receipts; it cannot execute a command.

All worlds use seed **731**, the committed synthetic catalogues/recipes and the
existing 32×32 city. They run in the dedicated **local `delivery_test` database**;
production database names, remote hosts and connection-string overrides are
rejected before creating a world. Model inference is disabled and ingredient
search uses its local adapter. There is no cloud endpoint option. The optional
GCP demo remains independent.

## Cases and scoring

The versioned contract is `data/evals/agent-scenarios.json`. Twelve scenarios
declare 49 criteria, each with a human-readable label and an exact typed expected
value. Booleans and integer counts are different measurements.

| Role | Scenario | Required behavior |
| --- | --- | --- |
| Inventory | Two baskets, one unit | One reservation, one safe rejection; scoped stock visibility |
| Inventory | Delayed replenishment | Forecast units remain unavailable until actual receipt |
| Inventory | Crash before acknowledgement | Actual worker-process crash rolls back; lease retry has one effect |
| Restaurant | Available pantry | Deliver pizza without unnecessary sourcing |
| Restaurant | Market forwarding | Empty nearest market forwards flour request; ingredients arrive before cooking |
| Restaurant | Replacement declined | Record refusal and reject without cooking or consuming ingredients |
| Restaurant | Replacement approved | Household consent and kitchen approval both precede cooking |
| Dispatcher | Assignment race | Two workers contend for one courier; one job assigned, one deferred |
| Dispatcher | Traffic and retry | Congestion affects ETAs; retry needs approval; infeasible job is abandoned |
| Courier | Assignment authority | Other courier cannot read/accept brief or recall memory; motion waits for ACK |
| Courier | Dropout handoff | Replacement gets recorded parcel checkpoint, prior courier and source events |
| Courier | Physical arrival | Completion follows world arrival; route ETA equals edge duration sum |

A case passes only when **every declared criterion** passes and execution/cleanup
succeeds. A safe business rejection is a successful evaluation when rejection is
the specified outcome. Case and role scores are passed criteria divided by their
declared criteria; missing measurements receive no credit. The dashboard always
shows case failure counts alongside scores. Missing receipts have no score;
partial receipts cannot become a complete pass.

Scores are recomputed by the reader from the committed contract and measured
values. A receipt cannot supply its own expected values, headline pass count or
score. Unknown/duplicate cases, extra fields, malformed types, missing configuration
hashes, incorrect repeat hashes and mismatched manifest versions are rejected.

## What actually runs

`delivery.scenario_evals` creates eight small isolated fixture worlds. Agents are
the existing `LocalAgent` workers with their real per-run/store/role Postgres
logins, permissions, tool budgets, typed memory and durable queue leases. The
controller sets up stock, injects disruptions, advances virtual time and observes
results as a trusted operator. Agents communicate through queued events; the
evaluator does not replace their decisions with an oracle. Dispatcher contention
uses two concurrent workers, and inventory recovery kills a real subprocess.

The controller retires short-lived database identities and deletes its worlds in
`finally`, including after a fixture error. Failure receipts store fixed error
codes, never exception messages, SQL strings, connection URLs, event payloads or
memory bodies. The retained event trail contains only fixture-relative sequence,
topic, trace, queue state, attempts and scheduled simulation seconds. Fixture
sequence numbers are local to the receipt; deleted database events cannot be
opened later. Supply replay is checked before cleanup.

Two evaluations cannot interleave through the CLI: it holds a Postgres advisory
lock. Existing simulation runs in the application's `delivery` database are
unaffected. The test suite verifies that the battery leaves the pre-existing
test-run IDs and role identities unchanged, and that an injected fixture error
still cleans up without exposing its exception text.

## Reproducibility and limits

Receipts retain manifest version/hash, seed, effective configuration hashes, source
fingerprint, UTC creation time and a business-outcome hash for **each** repetition.
The hash includes typed observations and fixed error codes. It excludes wall time,
random run IDs, global SQL event IDs, and which racing worker wins: both possible
winners are valid, but one courier must still receive exactly one job.

Each repetition's observations are preserved and checked against its hash. A later
passing repeat cannot erase an earlier failed case. Each criterion keeps its first
explicit failure across repeats, otherwise its first missing measurement, otherwise
the final passing value. Criteria and event trails identify their repetition. An
omission cannot hide a measured failure from another repeat. Input hash drift also
produces a failed receipt, including when one setup attempt fails before creating
the world. A mismatch fails reproducibility even if both individual outcomes
otherwise meet the criteria. Starting the checker replaces any previous green
receipt with unmeasured evidence until the new battery finishes.

For a quicker diagnostic run after building the image:

```bash
docker compose run --rm --no-deps app python scripts/eval_agents.py --repeat 1
```

The page labels a single run as repeatability **not measured**. Results from changed
sources or older than 24 hours remain historical. Rebuild the running app after
source changes so its fingerprint can match the checker. These are local receipts,
not signed attestations against a hostile host operator.

This is a fixed **development regression battery for rules-based agents**. It
measures coordinated business and permission behavior, not LLM reasoning quality,
production latency, cost per model decision, held-out generalization, or superiority
of one architecture/memory strategy. Those remain separate unmeasured benchmarks.

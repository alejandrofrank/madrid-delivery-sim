# Status

2026-10-23: Expanded default delivery lab to a 32x32 city, 12 establishments
including pharmacies, scarce inventory, seven basket requests and four couriers.
Added role-isolated courier and judge agents, queued scoped briefings, traffic delays,
dropouts, custody-preserving recovery and deadline/cost/attempt gates. Seed 42:
five delivered, one abandoned after denied recovery, one rejected stock request.
Verified 86 Linux tests, Ruff, mypy and desktop/mobile Chrome.
See `docs/FLEET-RECOVERY.md`. No model/voice-provider calls or private rows committed.

2026-10-23: Added fulfillment and fleet dispatcher roles using the shared local
factory, queue, memory and budgets. Basket-to-delivery inspector at `/delivery-lab`
shows atomic picking, courier assignment, physical movement and queued confirmation.
Linux full suite: 76 tests; additional API contract: 1 test; Ruff/mypy passed.
See `docs/DELIVERY-FLOW.md` for permissions, evidence and remaining boundaries.

2026-10-23: Shared local inventory foundation implemented: frozen role/soul definitions,
five per-run/store database identities with row security, scoped tools and private TTL
memory, durable agent/aggregate budgets and queue-only communication. Expanded the
fictional city to 10×10 (100 nodes, 360 directed edges). Linux Compose: 67 tests, Ruff
and mypy passed; dated Bakiano crash recovery and desktop/mobile browser checks passed.
See `docs/AGENT-FOUNDATION.md`. No provider calls or private rows committed.

2026-10-23: Local-first decision applied. Forty tests pass, including immutable
dated history, missing-day validation, distinct store-source binding and local
settings that ignore old cloud credentials. The local sample has 2,008 observations
from five Bakiano sources on October 14-22; October 23 is explicitly missing.
Private rows remain in ignored `data/local/bakiano/`. GCP deployment is deferred.
See `docs/LOCAL-DATA.md` and the counts-only coverage receipt.

2026-10-23: M2 first slice implemented locally: catalogue adapter, fictional city,
transactional inventory, last-unit race, real subprocess crash recovery, delayed
supply and checkpoint inspector at `/lab`. Verified 25 tests, Ruff, mypy and Chrome
desktop/mobile checks. See `docs/M2-VALIDATION.md` for scope and limits.

Before expanding reasoning roles, the shared GCP agent foundation is specified in
`docs/AGENT-RUNTIME.md`: ADK behind queue/tool contracts, versioned role prompts,
independent permissions, scoped context/memory and enforced budgets. This is a
researched design, not a cloud deployment. M2 still runs locally without model calls.

2026-10-22: Setup and Milestone 1 complete and pushed to `main`.

Repo: https://github.com/alejandrofrank/madrid-delivery-sim (private).

- Created the repo, reused existing Vertex authentication in ignored `.env`, and verified no credential values exist in Git history.
- Built Docker/PostGIS/Redis services, the real Madrid graph and seeded city, durable queues, courier/dispatcher agents, bounded LLM customer service, and the live map with decision traces.
- Verified 16 tests, Ruff, mypy, desktop/mobile browser checks, and [passing CI](https://github.com/alejandrofrank/madrid-delivery-sim/actions/runs/39720147199).
- Ran the actual 10-minute `make demo`: 247 deliveries, 996 acknowledged events, zero dead letters, three successful Vertex calls.
- Added architecture/setup documentation, acceptance evidence, and ROADMAP.md for remaining milestones.

Local UI is running at http://localhost:8010. Blockers: none.

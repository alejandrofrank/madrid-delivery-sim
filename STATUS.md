# Status

2026-10-28: Added the local architecture website at `/architecture`, following
Scrapmarket's topic-oriented engineering reference. Eighteen searchable chapters,
an interactive component inspector, six rendered diagrams, eight decision records,
the six-capability proof map and a fixed-catalogue source reader explain implemented
behavior and proposed enterprise GCP work. Markdown remains the content source;
browser dependencies are integrity-pinned and hosted locally. Verified 409 tests
(17 documentation checks), Ruff, mypy over 41 modules, host JavaScript syntax,
local asset hashes and browser navigation/search/source/diagram/history behavior.
Twelve role scenarios/49 criteria passed twice with matching outcomes; no model
calls or cloud resources were used. Private source/traversal/symlink/size denial
cases pass. Python-only health image still reports Node syntax as unavailable;
host syntax and browser checks passed. See docs/DOCUMENTATION-SITE.md and
docs/evidence/documentation-local.json.

2026-10-28: Added exact agent construction/lifecycle and GCP resource documentation,
and refreshed the enterprise client architecture against current official Google
guidance. Inventory covers ten Terraform resource blocks/six APIs, twelve parked
foundation resources and fifteen fully enabled resources, with caller/runtime IAM,
model-data boundaries, sizing, cost and shutdown semantics. Corrected older claims
about SOUL interpretation, zero-dollar enforcement, model I/O transaction placement
and deferred cloud support. Enterprise targets cover ADK/runtime selection, managed
identity/governance, durable inference, memory, evals, observability and Terraform
ownership. Documentation links/configuration arithmetic were checked; the existing
392-test runtime baseline was not rerun for this docs-only change. No deployments,
cloud status queries, credential reads or model calls were performed.

2026-10-28: Added twelve reproducible local role scenarios with 49 declared criteria
for inventory, restaurant, dispatcher and courier agents. Real scoped queue workers
exercise last-unit scarcity, delayed supply/process crash, sourcing/consent,
concurrent dispatch, congestion, dropout custody and physical arrival. Health shows
role scores, failed-case filters, expected/actual criteria and event/repeat evidence.
Scores are recomputed from a versioned manifest; omissions, drift and failures across
repeats stay visible. Two seed-731 runs matched at 12/12 cases and 49/49 criteria,
with zero paid calls. Verified 392 tests (39 new evaluator checks), Ruff, mypy over
40 modules, host JavaScript syntax and browser inspection/refresh/filtering. Fixture
runs and short-lived roles were removed; app/Postgres/Redis remained running during
checks. Failed supply bootstrap now removes its committed base city. This is a
rules regression baseline; live-model and held-out comparisons remain unmeasured.
See docs/AGENT-EVALS.md and docs/evidence/agent-scenarios-local.json.

2026-10-28: Added the local /health dashboard, following Scrapmarket's category
and run-history pattern. Browse individual parameter cases across ten categories,
inspect six capability regression groups and six offline judge cases, and probe
local services, per-run queues and durable budgets. Opt-in pytest reporting and
make health record safe source-fingerprinted receipts; missing, partial, skipped,
interrupted, stale and changed-source evidence cannot become a full pass.
The checker binds all subprocesses to delivery_test and leaves running services
untouched. Verified 353 tests (46 new health checks), Ruff, mypy over 38 modules,
host JavaScript syntax and browser filtering/drill-down/refresh/history. Zero
model calls; Python-only container reports Node syntax as unavailable. CI publishes
safe reports even on failure. See docs/HEALTH.md and docs/evidence/local-health.json.

2026-10-28: Added nine typed memory contracts and selective recall bound to
an authenticated incoming event lease. Role, order, market request and courier
attempt boundaries are enforced in Postgres; source events, revision history,
expiry, capacity and tool admission are retained. Raw memory/decision browsing
and direct queue mutation are denied. The order inspector shows recalled facts
with revisions and sources. Full local suite: 307 passed; Ruff, JavaScript syntax
and mypy (36 source files) passed. Fresh smoke: two delivered meals, 48 events,
42 memory revisions, 26 recalled facts, zero dead letters/model calls; replay and
all inventory invariants passed. Default 64-order run: 1,762 events, zero retries/dead letters/model calls; replay
matched, with the existing seven delivered/57 failed meal outcomes retained.
Browser checked new and legacy histories.
See docs/AGENT-MEMORY.md and docs/evidence/typed-memory-local.json.

2026-10-25: Added one-command GCP judge start/stop/status while city/environment
and event workers stay local. Verified a live start and two-phase stop: one
private gateway/repository when active, no runtime and billing disabled at finish,
12 foundation resources and both original identity IDs retained. Twenty command
regression tests cover failure cleanup, plan guards, registry token isolation,
and repeated operations. Clean Linux suite: 155 passed; Ruff/mypy passed.
Excluded host pytest/Python bytecode after a stale-cache test failure.
See docs/GCP-AI.md and the lifecycle command receipt.

2026-10-25: Recovered original caller/runtime identities and custom prediction
role; retained free IAM and API registrations between sessions. Parked mode keeps
12 non-billable foundation resources, with billing disabled and no Cloud Run
service or artifact repository in state. Shutdown deletes only billable runtime
and its attached invocation binding, then unlinks billing. Seven lifecycle tests
include shutdown/restart with identical service-account IDs.

2026-10-25: Restored the dedicated AI project and imported it into its original
Terraform state. Added protected persistent-project lifecycle, opt-in runtime and
billing flags, and two-phase shutdown (delete runtime first, unlink billing second).
The project is ACTIVE with billing disabled; no Cloud Run services. Parked plan
was unchanged with only the project in state at that checkpoint; IAM recovery
above supersedes that state. See docs/GCP-AI.md.

2026-10-24: Deployed the private GCP recovery judge into a dedicated Terraform-owned
project, isolated from Scrapmarket. Model context is limited to seven synthetic meal
recipes/three markets plus numeric control facts. A live eval exposed a missing-facts
approval; deterministic preflight now gates invalid requests. Guarded eval: 6/6
(one model decision, five policy denials). UI GCP/local pairing verified one/zero
model calls and all invariants. Full Linux suite: 135 passed; Ruff/mypy passed.
Teardown completed 2026-10-25: all 15 managed resources destroyed, Terraform state
empty, project DELETE_REQUESTED. Local-only mode restored; see the redeployment
walkthrough in docs/GCP-AI.md.
See docs/GCP-VERIFICATION.md and docs/ENTERPRISE-GCP.md.

2026-10-24: Added interpolated courier movement, timed order-book arrivals and
current driver order/route/ETA with scoped memory inspection. Optional GCP Vertex
recovery judge uses durable six-call/token reservations and fail-closed decisions.
Standalone Terraform owns a dedicated cloud project; nothing deployed. Verified
112 Linux tests, additional budget exhaustion checks, Ruff/mypy, live desktop/mobile
browser interactions and Terraform validation. Docker recovered without deleting volumes.

2026-10-23: Added 120 synthetic products, 128 identifiable households, customer
order views, entity filters, urban buildings and actual one-way routing. The UI
explicitly identifies delivery-lab agents as rules-only workers with no AI calls.
Verified 97 Linux tests, a targeted dispatcher privacy check, Ruff, mypy, and both
city and fixed-fleet browser checks on desktop/mobile.

2026-10-23: Added frozen local city configuration, seeded orders over time, store
stock/demand/staffing and configurable traffic/withdrawal rates. Map-first UI supports
shop/team selection and selected-agent parameter, budget and memory inspection.
Verified 91 Linux tests, Ruff, mypy and desktop/mobile browser interactions.
See `docs/RUNNING-CITY.md`. Settings affect new sessions, with unfinished work visible.

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

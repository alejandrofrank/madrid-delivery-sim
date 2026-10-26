# Madrid Delivery Sim

A local operations lab for queue-driven delivery agents, with a Madrid baseline and a fictional-city inventory lab. Default demos use local databases and make no provider calls. An optional private GCP recovery judge deploys through a separate Terraform root; the simulation stays local. Deployment and teardown were verified on October 24–25, 2026; the cloud demo is currently off. The restored project is retained with billing disabled; routine shutdown removes runtime resources and keeps the project.

The city runs locally. Enable the optional paid judge only for agent tests:

```bash
python3 scripts/gcp_demo.py start
python3 scripts/gcp_demo.py status
python3 scripts/gcp_demo.py stop
```

Stop removes billable runtime resources and disables billing while retaining the
project and free IAM. [Setup and cost boundaries](docs/GCP-AI.md).


Milestone 1 includes 18 bike, moto, and van couriers across Chamberí, Retiro, and Puente de Vallecas; 24 real OSM pickup locations; 180 synthetic customers; and a seeded 10:00 to 22:00 service day. The map renders cached street geometry with no tile API key or external map requests.

![Local operations interface](docs/demo.png)

## Run locally

### M2 inventory slice

The fictional-city inventory lab is at **http://localhost:8010/lab** after starting
the stack. It uses three supermarkets, two retail stores and synthetic stock.
Start the last-unit scenario to inspect a real worker-process crash, lease recovery,
competing baskets, reservation expiry and delayed replenishment. Checkpoint selection
and downloadable JSON retain the evidence. This slice makes no model calls. The city is a deterministic 10×10 grid with 100
nodes and 360 directed road segments. Five inventory identities share one local
agent implementation, with enforced per-store database access, private memory,
frozen role/soul definitions and durable budgets. See [agent foundation](docs/AGENT-FOUNDATION.md).

```sh
docker compose exec -T app delivery lab-demo
```

The default five-product fixture is entirely synthetic. To import a local Bakiano
collector CSV with verified USD prices (not raw mislabeled bolivares):

```sh
delivery import-catalogue PATH_TO_EXPORT.csv artifacts/daka-snapshot.json --source daka --domain retail --confirmed-usd --limit 10
delivery lab-demo --catalogue artifacts/daka-snapshot.json
```

Run those import commands in the host virtual environment, or mount the source
export into the container explicitly. Existing output snapshots are never overwritten.
Imported data stays in ignored `artifacts/`; the UI offers it when that snapshot exists.
Prices retain their observed dates; catalogue listings do not establish real stock.
See [M2 validation](docs/M2-VALIDATION.md) for guarantees and current limits.

### Running city

Open **http://localhost:8010/delivery-lab** for the map-first city. Click a store to
configure its opening stock, demand weight and home couriers. Global controls set
order intensity, traffic, dropout rates, duration and seed. Orders arrive over time.
Click a store's team member or a courier to inspect its parameters and private memory.
Settings apply to the next session; each run keeps its frozen starting configuration.

See [running city controls and limits](docs/RUNNING-CITY.md). All agents retain their
separate database identities, scoped tools, budgets and queued handoffs. Everything
runs locally by default with no model/provider calls. Optional GCP mode uses a bounded,
IAM-protected judge with only a synthetic seven-meal supermarket snapshot and
numeric recovery facts. See [live GCP verification](docs/GCP-VERIFICATION.md) and
[enterprise design tradeoffs](docs/ENTERPRISE-GCP.md).

The [restaurant supply lab](http://localhost:8010/restaurant-lab) adds scheduled
household meal calls, seven restaurants, nearby ingredient markets, reservations,
substitution consent, cooking and courier handoff. Edit entity/agent definitions
on the map; inspect private memory and replay recorded business facts. It runs
locally with zero provider calls by default. Optional scoped Jev relevance search
has separate opt-in and budgets. See [contracts and limitations](docs/RESTAURANT-SUPPLY.md).

The fixed fleet recovery regression remains available from the CLI:

```sh
docker compose exec -T app delivery delivery-demo
```

Its traffic/dropout scenario and scoped rescue briefings are documented in
[fleet recovery](docs/FLEET-RECOVERY.md).

### Dated Bakiano sample

The local private sample targets October 14-23, 2026 (ten dates). It contains 2,008
observations for October 14-22 from Gama, Central Madeirense, Plazas, Daka and EPA.
October 23 had no observations at extraction time and stays explicitly missing.
Choose a date in the lab, or run:

```sh
docker compose exec -T app delivery lab-demo --sample-date 2026-10-22
```

Samples live in ignored `data/local/bakiano/`, mounted read-only at runtime and
excluded from image builds. The public synthetic fixture remains available without
the private package. See [local dataset policy and acquisition](docs/LOCAL-DATA.md).

Requires Docker with Compose v2.24+ and GNU Make. On Windows, run Make from WSL with Docker Desktop integration enabled. Docker supplies Python and all application dependencies. Ports bind only to localhost: app **8010**, Postgres **55432**, Redis **56379**.

```sh
make demo
```

This builds the image, starts healthy PostGIS and Redis services, seeds the city, and runs the 12-hour simulated day over **600 wall-clock seconds** after setup. Open **http://localhost:8010** while it runs. A slower machine or provider response can extend playback. Results are written to `artifacts/run-<uuid>.json`; the database and UI remain available afterwards.

The checked-in OSM snapshot makes ordinary startup independent of Overpass. Initial Docker builds require internet access. No credentials are required to run: without a configured LLM, complaints are visibly escalated with source `disabled`.

```sh
make setup                                  # stack and UI, no new simulation
docker compose exec -T app delivery demo --wall-seconds 0  # as fast as possible
make test                                   # real Postgres integration tests
make check                                  # Ruff and mypy
python scripts/verify_demo.py                # validate seed-42 full-day artifact
make down                                   # stop services; retain database volumes
```

To run the equivalent commands directly in Bash:

```bash
mkdir -p artifacts
docker compose up -d --build --wait
docker compose exec -T app delivery init
docker compose exec -T app delivery demo --wall-seconds 600
```

For Linux users running Compose directly, set `LOCAL_UID=$(id -u)` and `LOCAL_GID=$(id -g)` when those differ from 1000. Make does this automatically so exported artifacts belong to the host user. Set `APP_PORT` in `.env` to change 8010. API documentation is at `/docs`.

## LLM configuration

Local Compose fixes `LLM_PROVIDER=disabled` and does not inject `.env` into the
application. Host settings also ignore `.env` unless explicitly requested by a
developer. Compose can still use `.env` for host options such as `APP_PORT`.
Cloud credentials are unnecessary for ordinary startup, tests or dated sample runs.
Provider adapters remain optional code for later experiments; configuring them is
deferred while the local system is polished.

- `LLM_PROVIDER=disabled`: current local default; service requests use recorded escalation.
- Vertex/Gemini adapters require explicit process-environment configuration. The
  default local stack does not enable them or inherit their credentials.

The default model is `gemini-2.5-flash-lite`. Credentials were verified by real Vertex calls during implementation. Model availability depends on the configured project. Changing the model requires reviewing its output/thinking support and updating cost estimates.

Customer service has a per-run cap of 4 attempted calls, 12,000 reserved tokens, and USD 0.02. Each call reserves 3,000 tokens at the higher configured token rate before network I/O. Complaint payloads are bounded to 1,024 serialized UTF-8 bytes, including JSON escapes, and output is capped at 384 tokens. With the conservative default rates, the dollar cap permits **3 calls**; the fourth complaint escalates. Reservations are not refunded, even if a call fails. Measured tokens and estimated cost are separate from reservations. Rates are estimates, not a billing statement; they exclude taxes and exchange rates.

Only judgement uses an LLM. Routing, assignment, movement, preparation, policy, and refunds are deterministic. The model returns a validated classification and reply; it has no executable tools. Replies are untrusted display text, never commands. Refunds above EUR 100 require approval; smaller late-order refunds are capped at EUR 5. M1 records approval requests but does not implement the manager workflow.

## Architecture

```mermaid
flowchart LR
    OSM[OpenStreetMap / OSMnx] --> G[Versioned directed street graph]
    G --> W[Seeded world and physical clock]
    W -->|order.created| Q[(Postgres event queue)]
    Q --> D[Rule dispatcher]
    D -->|courier.assigned| Q
    Q --> C[Courier agents]
    C -->|delivered / available| Q
    W -->|complaint.created| Q
    Q --> S[Customer-service agent]
    S --> B[Durable budget reservation]
    B --> L[Gemini / Vertex]
    L --> P[Schema and refund policy]
    P -->|resolved / approval.requested| Q
    Q --> A[Audit consumer]
    D <--> DB[(Postgres + PostGIS state)]
    C <--> DB
    P <--> DB
    W --> DB
    W -. tick notifications .-> R[(Redis)]
    DB --> API[FastAPI snapshots + order traces]
    G --> API
    API --> UI[Leaflet operations UI]
```

Postgres is authoritative. Agent messages use the durable queue exclusively; reading shared state and advancing the physical clock are explicit non-message operations. One local scheduler hosts logical agents in M1. Queue leases support competing consumers, but independent worker deployments and alternate supervision topologies are later milestones. Redis publishes best-effort tick notifications for subscribers; the UI polls authoritative snapshots and remains usable if Redis goes down after startup.

### Queue and consistency contract

- Publishing deduplicates by `(run_id, topic, dedupe_key)`, including after ACK. Priority and simulated due time are explicit. A per-run pending-capacity limit applies backpressure.
- Consumers claim with `FOR UPDATE SKIP LOCKED`. Leases expire after 45 seconds. Unique tokens fence stale workers; crash recovery counts against the retry limit.
- Handler state changes, emitted events, and ACK share one transaction. Failure rolls back state and outgoing messages. Retries wait 1, 2, then 4 wall-clock seconds, capped at 30; three unsuccessful deliveries enter `dead_letters`.
- Delivery is at least once with transactionally idempotent database effects. External LLM calls do not have an exactly-once guarantee. Durable reservations and cached results prevent automatic rebilling after an ambiguous crash.
- M1 serializes state-writing handlers within a run using an advisory lock. Different runs remain independent. A partial unique index prevents two active orders per courier; conditional versioned updates prevent duplicate claims.
- Producer/consumer allowlists enforce in-process queue-tool permissions. They are not a sandbox against malicious Python: the local service shares one database account. M2 inventory agents now use separate database logins and row-level policies; M1 retains this earlier boundary. See the agent foundation for the current threat model.
- A hard event budget stops processing loops. Error records contain exception types, not provider exception strings. Failed or unaffordable complaints fail closed to approval.

Inspect `/api/state`, `/api/runs`, and `/api/runs/<uuid>/trace?order=ORDER_ID`. Selections show recorded policies, route estimates, transitions, and replies. These are auditable decision records, not private model reasoning. Queue rows retain event lineage and order correlation IDs.

```sh
docker compose exec postgres psql -U delivery -d delivery -c \
  "select id, topic, attempts, error from dead_letters;"
docker compose exec -T app delivery replay EVENT_ID
docker compose exec -T app delivery demo --resume RUN_UUID
```

DLQ replay is an explicit operator action after repairing the cause. It makes the event eligible again; a running/resumed scheduler must consume it. Completed runs are immutable to the clock driver. Use a new run for scenario replays. Seed, minute, and cached OSM inputs determine arrivals; LLM wording can vary.

## Simulation boundaries

The packaged graph has **9,391 nodes and 18,080 directed edges**, downloaded on 2026-10-22. Routing uses shortest road distance and mode-specific constant speeds, without live traffic. Motorway/trunk edges are removed and the largest strongly connected component is retained. All modes share this conservative directed graph; bike contraflow, turn restrictions, vehicle-specific access, and metropolitan coverage remain extensions.

Hubs are simulated facilities in real districts. Store names/locations come from OSM; customers are synthetic street-node locations. No real orders or customer details are used. Preparation lasts 3 to 10 simulated minutes. Couriers have energy and shift constraints. Energy depletes with distance; charging/refuelling and stockouts are not yet implemented. The final 30 minutes stop new arrivals to drain deliveries. Operating cost is a synthetic stop cost plus distance cost, not a commercial forecast.

On-time percentage uses delivered orders as its denominator. Unserved, active, pending, and overdue counts remain visible separately. Seed 42 is a deliberately feasible baseline, not evidence of chaos performance. See [ROADMAP.md](ROADMAP.md).

## Development and verification

Python 3.12 or 3.13 is supported. Dependencies are pinned in `requirements.lock`. Explicitly target a virtual environment for host development:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
export TEST_DATABASE_URL=postgresql://delivery:delivery_local_only@127.0.0.1:55432/delivery_test
.venv/bin/python -m pytest -q
.venv/bin/python -m delivery.world --download  # optional OSM refresh; internet required
```

Integration tests use only `delivery_test`, never the demo database. Coverage includes concurrency, dedupe, retries/DLQ, stale and crashing workers, outbox rollback, duplicate assignment, real routes, preparation waiting, refund injection, malformed model output, error redaction, concurrent budgets, cached replies, and API contracts. GitHub Actions builds Compose, runs checks and tests, then verifies a seeded day without paid calls.

For browser checks, install Playwright separately (`python -m pip install playwright==1.58.0`) and run `python scripts/browser_smoke.py` against a demo with orders. It uses installed Chrome by default; use `--channel ""` with Playwright-managed Chromium. Screenshots go into ignored `artifacts/`.

See [docs/VALIDATION.md](docs/VALIDATION.md) for measured results. Module boundaries: `world.py` for OSM/routing, `queue.py` for messaging, `agents.py` for policies, `customer_service.py` for model isolation/budgets, `simulation.py` for clock/state, and `api.py` plus `web/` for inspection.

## Data and upstream references

Graph and store data derive from OpenStreetMap under [ODbL 1.0](https://www.openstreetmap.org/copyright). Attribution is visible in the map. `data/manifest.json` records source, retrieval time, bounds, and graph SHA-256. The included [Leaflet license](web/vendor/leaflet/LICENSE) covers vendored Leaflet 1.9.4.

References: [OSMnx API](https://osmnx.readthedocs.io/en/stable/user-reference.html), [Postgres locking clauses](https://www.postgresql.org/docs/18/sql-select.html), and [Google Gen AI SDK](https://github.com/googleapis/python-genai). Local services and cached map data have no recurring service charge; provider calls may be billed to the existing project.

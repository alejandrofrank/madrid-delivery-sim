# Madrid Delivery Sim

A local operations lab for queue-driven delivery agents on Madrid's real street graph. Built for inspecting assignments, failure recovery, tool permissions, and the cost of selective LLM use.

Milestone 1 includes 18 bike, moto, and van couriers across Chamberí, Retiro, and Puente de Vallecas; 24 real OSM pickup locations; 180 synthetic customers; and a seeded 10:00 to 22:00 service day. The map renders cached street geometry with no tile API key or external map requests.

![Local operations interface](docs/demo.png)

## Run locally

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

On Windows PowerShell, equivalent commands are:

```powershell
New-Item -ItemType Directory -Path artifacts -Force | Out-Null
docker compose up -d --build --wait
docker compose exec -T app delivery init
docker compose exec -T app delivery demo --wall-seconds 600
```

For Linux users running Compose directly, set `LOCAL_UID=$(id -u)` and `LOCAL_GID=$(id -g)` when those differ from 1000. Make does this automatically so exported artifacts belong to the host user. Set `APP_PORT` in `.env` to change 8010. API documentation is at `/docs`.

## LLM configuration

Copy `.env.example` to `.env` only if `.env` does not already exist. The working machine is configured with the existing `scrapmarket` Vertex authentication. Only required authentication fields and project settings were copied. `.env` is excluded from Git and Docker's build context; Compose injects it at runtime. Never paste credential values into issues or reports.

- `LLM_PROVIDER=vertex`: set `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, and `GOOGLE_CREDENTIALS_JSON` to an authorized-user ADC JSON object. Standard ADC is also supported when made available to the runtime.
- `LLM_PROVIDER=gemini`: set `GEMINI_API_KEY`.
- `LLM_PROVIDER=disabled`: no paid calls; requests require operator review.

The default model is `gemini-2.5-flash-lite`. Credentials were verified by real Vertex calls during implementation. Model availability depends on the configured project. Changing the model requires reviewing its output/thinking support and updating cost estimates.

Customer service has a per-run cap of 4 attempted calls, 12,000 reserved tokens, and USD 0.02. Each call reserves 3,000 tokens at the higher configured token rate before network I/O. With the conservative default rates, the dollar cap permits **3 calls**; the fourth complaint escalates. Reservations are not refunded, even if a call fails. Measured tokens and estimated cost are separate from reservations. Rates are estimates, not a billing statement; they exclude taxes and exchange rates.

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
- Producer/consumer allowlists enforce in-process queue-tool permissions. They are not a sandbox against malicious Python: the local service shares one database account. Separate database roles, MCP tools, and row-level policies remain roadmap work.
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

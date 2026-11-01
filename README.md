# madrid-delivery-sim

Queue-driven delivery agents on Madrid streets, with Google ADK, real A2A endpoints, distributed traces, and auditable BigQuery run evidence.

**[Meet the agents — interactive anatomy](http://localhost:8010/architecture)** ·
[Read the same guide in the repository](docs/AGENT-ANATOMY.md)

[![Agent team and interactive machine anatomy](docs/media/agent-anatomy.png)](http://localhost:8010/architecture)

## 60 second tour

Synthetic households order meals on Madrid's real street graph. Kitchens source
ingredients, couriers deliver, and disruptions force the team to reconsider its
plans. Open the **Architecture** workspace, choose a robot, and inspect its parts.

| Agent | Its job |
| --- | --- |
| Household | Request a meal and decide whether a substitution is acceptable. |
| Restaurant | Prepare a feasible meal or explain why it cannot be made. |
| Market | Supply confirmed ingredient quantities from physical stock. |
| Inventory | Reserve real stock without overselling. |
| Fulfillment | Turn a reserved basket into a ready pickup. |
| Dispatcher | Match ready orders to available couriers and recover disrupted deliveries. |
| Courier | Accept a delivery and carry it along the planned street route. |
| Customer service | Explain delivery problems and apply bounded refunds or escalation. |
| Recovery judge | Review failed deliveries before another attempt. |

The hard part is **reliable effects around uncertain decisions**: no overselling,
no duplicate refunds after retries, no cooking from promised ingredients, and no
memory leaking across orders or roles. ADK proposes through granular tools;
scoped SQL, durable queues and authenticated A2A boundaries enforce the contract.
Routine policies can run without a model.

Prior architecture release: **998 Python tests passing**, plus all **99 anatomy panels**
checked in the browser ([verification receipt](docs/evidence/agent-anatomy.json));
**pass^5 = 1.000 across 72 held-out cases** (360 attempts), with an all-pass
bootstrap interval of [1, 1] in the [release receipt](docs/evidence/heldout-release.json).
One [seeded Chaos shift](docs/evidence/a2a-chaos-local.json) delivered 71/71 orders
at **€1.7215 synthetic operating cost per delivery** and recovered its disruption
cohorts in **1,148–1,765 simulated seconds**, with zero lost orders. Recovery includes
delivery completion. These are dated offline checks, not live-model quality,
production latency or real courier prices; all-pass fixtures do not prove certainty.

![Live agent operations](docs/media/ui-demo.gif)

The redesigned console spans six workspaces. Run `make setup` and open
**[localhost:8010](http://localhost:8010/)**. This is the single development instance;
the consolidated instance runs from the main checkout under the existing Compose
project name. Keep one instance when switching a development checkout.
The older 8021 UI preview has been stopped. Its UI changes were already merged
into `main`; its files and data were preserved. [Before/after, verification and limits](docs/UI-REDESIGN.md).

The GIF records actual local simulation activity. All default runs are free of
cloud and model charges.

## Shelf to doorstep

Open **Operations → Start store demo** on [localhost:8010](http://localhost:8010/).
A real seeded basket is reserved, picked from shelves, packed and carried to the
dock. The same order then travels across Madrid with its assigned courier.
**Picker breakdown** interrupts the route; another picker must reach the stranded
basket before taking over. **Follow this order** moves the view between those scales.

![Actual seeded store order, from Madrid to shelves and back](docs/media/store-journey.gif)

The elevated cutaway uses the actual layout, shelf stock and worker paths.
Choose a store pin to inspect its load, highlight an order's shelves, or trigger
a blocked aisle, stock shortage, robot breakdown or delayed truck. The inventory
and fulfillment roles share the city's clock, durable events and A2A transport.
Routine decisions need no model calls. The anatomy page's **Environment** part
switches between store and city explanations.

Seven locally optimized NVIDIA SimReady models total **0.92 MB**; Three.js and
models together stay below **4 MB** and load only when a store opens. Missing
models become simple shapes; unavailable graphics use an interactive floor plan.
This is deterministic logistics, with aisle navigation and stock conservation,
not collision-accurate robotics physics.

All four store disruptions pass twice over A2A with matching outcomes, conserved
stock and no late deliveries or paid calls. [Measured recovery](docs/evidence/dark-store.json) ·
[Environment, controls, limits and reproducible demo](docs/DARK-STORE.md).
Assets: NVIDIA SimReady, converted by
[codepawl](https://huggingface.co/datasets/codepawl/simready-glb),
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); geometry and textures
simplified for the browser. Full source hashes and modifications are in
[the asset manifest](web/vendor/simready/manifest.json).

## On-demand Google Cloud

Public demo link: **available only during a demo session** (`replay_url` from
Terraform). The replay was deployed to Cloud Run, checked over HTTP and in a
browser, then removed. The dedicated project is currently off; the verified URL
and restart/stop commands are in the [deployment runbook](docs/production/DEPLOYMENT.md).
The public service plays sealed seeded shifts, accepts only reads, and needs no
database or model calls. The existing UI and local instance remain unchanged.

```mermaid
flowchart LR
    Public[Public viewer] --> Replay[Cloud Run replay: recorded frames]
    GitHub[GitHub main / production environment] --> Gate[Held-out release gate]
    Gate --> WIF[Workload Identity Federation]
    WIF --> Image[Artifact Registry: immutable digest]
    Image --> Replay
    Operator[Terraform operator] --> Lifecycle[Deploy / verify / destroy]
    Lifecycle --> Replay
    Replay --> Monitor[Cloud Monitoring SLOs + spend cap]
    subgraph Private[Optional private tier: disabled pending SQL permission work]
      Client[Authorized operator ID token] --> API[Private Cloud Run API]
      API --> Job[Cloud Run shift job]
      Job --> A2A[A2A with audience-bound ID tokens]
      A2A --> Agents[Dispatcher / restaurant / customer service / inventory / fulfillment]
      Agents --> SQL[(Cloud SQL: scoped state + pgvector)]
      Agents -. optional semantic index .-> Vector[Vertex Vector Search]
      Job --> BQ[(BigQuery metrics + views)]
      Agents --> BQ
      BQ --> Dashboard[Looker Studio]
    end
```

Each role has a separate service account. CI uses short-lived federation and can
update only an existing replay service. Private API writes and A2A calls require
verified Google identities and explicit role authorization; SQL scopes remain the
authority for individual actions. [Security model](docs/production/TRUST-MODEL.md).
The private tier is **not production-qualified**: safe SQL controller provisioning
is still unfinished, and Cloud SQL/Vertex were not activated under the demo allowance.

Cloud Run scales to zero during sessions. `active=false` removes its services/jobs,
images and opted-in SQL, vector and analytics resources after the session. State,
identities, budgets and provider logs remain. A EUR 3 native Cloud Run cap and EUR 4
project alert reflect the EUR billing account and requested small allowance;
delayed enforcement and retained storage prevent a strict total-dollar guarantee.
[Dashboard/SLO setup](docs/production/DASHBOARDS.md) ·
[Scoped semantic recall](docs/production/SEMANTIC-MEMORY.md).

```mermaid
flowchart LR
    UI[Operator UI / A2A client] --> A2A[Dispatcher + customer service A2A servers]
    UI --> SIM[Madrid simulation / inventory lab]
    A2A --> Q[(PostgreSQL durable queue)]
    SIM <--> Q
    Q <--> AG[Scoped agents + ADK Runner]
    AG --> OFF[Scripted offline models]
    AG -. explicit opt-in .-> V[Vertex AI / bounded Cloud Run judge]
    AG --> OT[OpenTelemetry spans]
    Q --> OT
    OT --> J[Local Jaeger]
    OT -. explicit opt-in .-> CT[Cloud Trace]
    AG --> R[Run receipts + KPIs]
    R --> ND[Local NDJSON bundle]
    ND -. reviewed upload .-> BQ[BigQuery tables + SQL view]
    BQ -. dashboard connector .-> LS[Looker Studio]
```

| Headline result | Evidence and scope |
| --- | --- |
| Tests | **969 Python tests passed** in the combined local full suite; six courier-motion checks, seven Terraform checks, Ruff and mypy (80 modules). [Main consolidation verification](docs/evidence/main-consolidation.json); hosted check results are tracked on [PR #5](https://github.com/alejandrofrank/madrid-delivery-sim/pull/5). |
| Scenarios | 12 deterministic role scenarios, run twice with matching outcomes. |
| Cost per local run | **$0 in cloud/model charges**; local compute excluded. |
| Evaluation pass rate | **360/360 held-out ADK attempts** across 72 cases; [release results](#held-out-release-results). Four A2A recovery scenarios and matching seeded Chaos runs remain covered by [Chaos verification](docs/evidence/a2a-chaos-local.json). These scripted checks measure contracts, recovery and policy, not live-model quality. |
| Interoperability | Dispatcher, customer service, inventory, fulfillment and individually scoped restaurants expose A2A 1.0 Agent Cards. The normal scheduler uses the official SDK; isolated tests can use the same services in process. |

Start at the [Google stack demonstration guide](docs/GOOGLE-STACK.md), inspect
[agent traces](http://localhost:8010/agent-traces), or browse the
[architecture site](http://localhost:8010/architecture). Every default demo and
CI check runs without paid model calls. [Public-readiness review](docs/PUBLIC-READINESS.md).

## Agent protocols

`AgentTransport` is the call boundary for the simulation and inventory scheduler.
Compose selects `A2ATransport`: it discovers each Agent Card and sends an A2A 1.0
JSON-RPC `SendMessage` using `a2a-sdk==1.3.0`. `InProcessTransport` implements the
same validated commands and durable queue semantics for isolated tests. Commands
carry a run and work reference, not a database connection or arbitrary tool name.
Agent Cards advertise immediate message receipts, without streaming or push support.

```mermaid
flowchart LR
    UI[Operations UI] --> S[Simulation and inventory scheduler]
    S --> T[AgentTransport]
    T --> A[A2A SDK client]
    T -. isolated tests .-> I[In-process transport]
    A --> D[Dispatcher A2A server]
    A --> R[Restaurant A2A servers: one card per identity]
    A --> C[Customer service A2A server]
    A --> V[Inventory A2A server]
    A --> F[Fulfillment A2A server]
    V --> Q
    F --> Q
    I --> D
    I --> R
    I --> C
    D --> Q[(Scoped durable work and simulation state)]
    R --> ADK[Google ADK Runner and role tools]
    C --> ADK
    D --> ADK
    ADK --> Q
    X[External agent] --> M[Read-only MCP server]
    M --> Q
```

Discover all cards at `GET /api/agents`. Each card lives at
`/a2a/{agent}/.well-known/agent-card.json`; the JSON-RPC endpoint is `/a2a/{agent}/`.
Restaurant names are derived from their persisted identities (OSM slashes become
hyphens). Unknown identities and mismatched work scopes are rejected. Replaying
recovery work returns its recorded result; an ambiguous paid attempt is never
automatically charged again.

Supply restaurants and the supply dispatcher are provisioned by their serving process
before the first intent is released. Their SQL identities and tool permissions stay
scoped to the run; no credentials cross A2A. Cards for active frozen runs remain
discoverable after the editable blueprint changes.

Customer service already uses the same Google ADK `LlmAgent` / `Runner` pattern
as restaurants on the merged main branch. This feature preserves its classification,
refund policy, durable budget reservations and escalation behavior, and adds scoped
ADK tools for proactive disruption recovery. A2A submission and scheduler ticks
both preserve the configured customer-service provider and its budget. Existing
restaurant sourcing tools remain intact. Recovery tools can read order context, revise preparation, reject an
uncollected meal, request normal dispatcher matching, contact a simulated customer,
request a policy refund, or escalate. Each role sees only its own capabilities.

The read-only MCP endpoint is `http://localhost:8010/mcp/` (Streamable HTTP), or
run `python3 -m delivery.mcp_server` for stdio. Its four tools are `order_status`,
`courier_positions`, `menus`, and `active_disruptions`. There are no mutation tools,
arbitrary SQL, private agent memories or credentials in these responses. This local
deployment binds to loopback; publishing these endpoints requires a separate
authenticated deployment design.

References: [A2A specification](https://a2a-protocol.org/latest/specification/),
[Google ADK agents](https://adk.dev/agents/custom-agents/),
[MCP tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools).

## Chaos mode

Open **Chaos → Start 60 second demo** in Operations. The scenario in
[`config/scenarios/chaos-demo.json`](config/scenarios/chaos-demo.json) schedules rain,
a Metro strike, a kitchen outage, a courier failure and a district demand surge over
two simulated hours. The clock targets 60 wall seconds; a slower machine may take
longer to process all agent turns. Use seed 42 for a repeatable recording. Keep the
Chaos panel open for event markers and open **Agent replanning and customer messages**
to inspect decisions. The existing map adds amber affected-service-area overlays;
planned trails are dashed and traveled trails are solid, both with bolder strokes.

Simulation controls also offer manual events and seeded random events. Supply a
`chaos` object when starting a run, or send an event to an existing Chaos run:

```bash
curl -fsS http://localhost:8010/api/runs \
  -H 'Content-Type: application/json' \
  --data '{"seed":42,"wall_seconds":60,"duration":7200,"chaos":{"random_events":5}}'

# Use the run ID returned above. Omitting "at" schedules the next simulation minute.
curl -fsS "http://localhost:8010/api/runs/$RUN_ID/chaos" \
  -H 'Content-Type: application/json' \
  --data '{"id":"manual-strike","kind":"metro_strike","district":"retiro","duration":600,"severity":2}'

# Start a scheduled scenario from a file using the same API.
python3 - <<'PY' | curl -fsS http://localhost:8010/api/runs \
  -H 'Content-Type: application/json' --data-binary @-
import json
from pathlib import Path
print(json.dumps({"seed": 42, "duration": 7200, "wall_seconds": 60,
                  "chaos": json.loads(Path("config/scenarios/chaos-demo.json").read_text())}))
PY
```

Event kinds: `heavy_rain`, `metro_strike`, `restaurant_outage`, `courier_offline`,
`demand_surge`. District codes are `chamberi`, `retiro`, `vallecas`. Strike and surge
require a district; outages and offline events require `target` (an existing identity
or `auto`). Each event has a stable `id`, simulation-second `at` and `duration`, and
severity 1–4. Outage severity below 2 slows preparation; 2 or above closes the kitchen
until the event ends. Rain slows travel and increases demand. Congestion applies to
deliveries serving the affected district. Events must fit the run; identical trigger
retries are idempotent, conflicting IDs fail. Random schedules use the run seed.

The engine changes physical conditions and queues observations. It does not choose
reassignment, rejection, refunds or customer wording. ADK agents choose recovery
tools; tools then validate current state, physical custody and refund policy. A
courier failure after pickup makes the stranded position the new pickup location.
The normal economic dispatcher selects the replacement courier.

```mermaid
sequenceDiagram
    participant O as Operator or scenario
    participant E as Disruption engine
    participant R as Restaurant A2A + ADK
    participant D as Dispatcher A2A + ADK
    participant C as Customer service A2A + ADK
    participant Q as Simulation state
    participant U as Operations UI
    O->>E: Courier goes offline after pickup
    E->>Q: Freeze availability; record affected orders
    E->>R: A2A replan with scoped work reference
    R->>Q: Read context; choose to keep collected meal
    E->>D: A2A replan
    D->>Q: Read context; choose reassignment
    Q->>D: Normal dispatch queue event
    D->>Q: Match replacement to stranded pickup
    E->>C: A2A replan after dispatch settles
    C->>Q: Read new ETA; choose apology and ETA update
    Q-->>U: Event marker, decisions, customer message
    Q-->>U: Delivery settles; recovery metrics update
```

Default demos/CI use `DELIVERY_CHAOS_PROVIDER=offline`, a deterministic **scripted
ADK model fixture**, with no paid calls. This verifies protocols and tool execution,
not live-model intelligence. For model-selected recovery set
`DELIVERY_CHAOS_PROVIDER=configured` alongside an explicitly configured existing
`LLM_PROVIDER=gemini` or `vertex` environment and its credentials/budgets. No model
fallback enables paid inference. Recovery reserves at most three calls and 12,000
tokens per turn, times out after 30 seconds, and keeps failed attempts inspectable.
Customer messages stay in the simulation. Scripted refunds require operator review;
model refunds retain the existing €5 late-order limit and approval rules, with an
additional per-order cumulative cap across recovery contacts and existing complaints.

`GET /api/runs/{id}/chaos`, `/api/state?run={id}` and `artifacts/run-{id}.json` expose
each disruption's recovery time, saved/lost orders, late deliveries, refunds, extra
tokens and extra model cost. Recovery time ends only after the event ends, affected
orders settle, and all recovery turns succeed; pending/failed recovery remains null.
“Saved” means an affected order was delivered, not a causal counterfactual estimate.
Overlapping event cohorts are not additive. Extra cost counts recovery calls only;
missing provider usage is conservatively costed at its reserved envelope.

Native ADK evalsets cover refund, late order, wrong item, escalation, and the four
recovery scenarios. The eval gate also measures full A2A deliveries against
[`evals/chaos/scenarios.json`](evals/chaos/scenarios.json), repeats each twice, and
compares two full runs with seeded random disruptions and generated demand:

```bash
docker compose exec -T app python3 scripts/eval_agents.py --suite adk --repeat 3 --record-only
docker compose exec -T app python3 scripts/eval_chaos.py
docker compose exec -T app python3 scripts/eval_gate.py \
  --candidate artifacts/evals/candidate.json --chaos-candidate artifacts/evals/chaos.json
```

Recovery and policy criteria are absolute gates, including during baseline bootstrap.
The expanded model cohort uses `eval-baseline-v2` so it cannot silently compare with
the older two-arm cohort. Until main stores a matching v2 artifact, statistical
regression comparisons report `baseline_missing`; that is not a quality pass.

## Agent architecture and GCP client documentation

All seven local workspaces share navigation, visual tokens, controls and mobile
behaviour. The [shared design contract](docs/DESIGN-SYSTEM.md) records the design
sources, diagram conventions and content-versioning workflow for future changes.

Open the local [Architecture website](http://localhost:8010/architecture) for a
searchable, twenty-four-chapter engineering reference. It includes an interactive
component explorer, rendered diagrams, architecture decision records, the six
capability evidence map and an allowlisted local code reader. Diagrams and search
work without external services. The existing `/docs` remains the API reference.
See [maintaining the documentation website](docs/DOCUMENTATION-SITE.md).
The [local website verification record](docs/evidence/documentation-local.json)
retains the 409-test source fingerprint, scenario results and browser checks.
The newer [durable inference verification record](docs/evidence/durable-inference-local.json)
retains 442 passing tests, physical worker crash recovery, repeatable scenarios
and the seven tool-generated diagrams. Read the
[request/result protocol](docs/DURABLE-INFERENCE.md) for retry and isolation guarantees.
The earlier [shared UI verification record](docs/evidence/shared-ui-local.json)
records the six workspace layouts, eight diagrams, desktop/mobile checks and
its 442-test regression evidence. The current redesign evidence and seven-page
comparison are in the [UI redesign record](docs/UI-REDESIGN.md).

| Read in order | What it explains |
| --- | --- |
| [Agent implementation](docs/AGENT-IMPLEMENTATION.md) | Exact factory, editable definitions/SOUL, role tools, authenticated scopes, event transactions, memory and budgets |
| [GCP components](docs/GCP-COMPONENTS.md) | Every Terraform resource, authentication/model request path, service sizing and retained-vs-billable lifecycle |
| [Enterprise architecture](docs/ENTERPRISE-GCP.md) | Current Google guidance, ADK/runtime choices, security/governance, durable execution, cost, eval/release gates and prioritized gaps |
| [ADK restaurant](docs/ADK-RESTAURANT.md) | Editable prompts/SOUL, Jev-first routing, scoped tools, capped Vertex comparisons and reproducible offline verification |
| [Operations and live evidence](docs/GCP-AI.md) | Start/status/stop and dated verification, with no claim that a past receipt is current cloud status |

The guides distinguish implemented behavior from proposed enterprise work. They
were reviewed against source and official Google documentation on 2026-10-28;
reading them requires no cloud deployment or paid inference.


New Madrid runs include **42 couriers**, **48 real OSM pickup sites** and **270
synthetic customer locations** across Chamberí, Retiro, and Puente de Vallecas,
with a seeded 10:00–22:00 service day. Pickup sites come from the packaged OSM
snapshot, rather than a claim about current business opening hours. The original
24 site IDs and district assignments are preserved. Existing runs keep their
recorded courier rosters; start a new session to use the expanded network.

### Independent courier fleets

These are simulated operators. Each run freezes its fleet definitions in
`runs.fleet_config`; courier membership is stored separately from vehicle mode.

| Fleet | Couriers | Vehicles | Service rule | Communication |
| --- | ---: | --- | --- | --- |
| Bakiano | 24 | Bike, moto, van | Full service area | Direct: “Route accepted.” |
| Sol Riders | 9 | Bike | Pickup and delivery in the rider's home district | Conversational: “Got it. Route accepted.” |
| Castellana Logistics | 9 | Moto, van | Full service area | Radio style: “Copy. Route accepted.” |

Each contractor has its own roster, availability, delivery count and cost ledger.
Dispatch and demand-aware repositioning enforce the service rules. The normal
deadline/cost optimizer selects among eligible riders; no fleet receives a hidden
priority. Couriers still use the existing deterministic execution policy, with no
additional paid model calls. Fleet independence here means separate simulated
operators and contracts, not separate worker processes or security tenants.

Acceptances use the durable `courier.accepted` queue message. A shared
`courier-status/1` envelope records fleet identity, sender, recipient, order,
status and a route-derived ETA. Only the human-readable wording varies. Pickup,
completion and repositioning messages are retained in decision evidence; this
does not add new A2A wire formats. Dispatcher calls continue through the existing
A2A/in-process interface. `/api/state` and run exports include per-fleet totals;
the read-only MCP courier query includes fleet membership.

Use **Fleet** above the roster to filter both agents and map trails. Select a
courier and **View decisions** to inspect its messages, operator, service area and
costs. Contractor names are simulation fixtures, not affiliations with real firms.

### Ingredient mismatch coverage

The **Restaurant lab** already compares recipes with stock, requests missing
quantities from markets, and handles approved ingredient substitutions. Both
household and restaurant approval are required; exclusions and denied
substitutions can make an order unfulfillable. These behaviors are covered by
`tests/test_supply_integration.py`. The main Madrid operations map does not model
ingredient inventories, and accidental wrong ingredients in a delivered meal are
not a physical simulation event. Customer-service wrong-item evaluation is a
separate policy/escalation scenario.



## Run locally

### Health and evaluations

Open [Health & evals](http://localhost:8010/health) to browse every test by category,
result and source case, inspect capability regressions and the offline judge
baseline, and check local services, queues and budgets. From Bash, run `make health`
after starting the stack to refresh the evidence. Partial, skipped, missing and
outdated results stay visible. See [health evidence and limits](docs/HEALTH.md).

`make eval-agents` runs twelve local inventory, restaurant, dispatcher and courier
scenarios twice. The Agent evals view shows role scores, failed cases, expected/actual
criteria and source events. No model is called. See [scenario contracts and repeatability](docs/AGENT-EVALS.md).

### M2 inventory slice

The fictional-city inventory lab is at **http://localhost:8010/lab** after starting
the stack. It uses three supermarkets, two retail stores and synthetic stock.
Start the last-unit scenario to inspect a real worker-process crash, lease recovery,
competing baskets, reservation expiry and delayed replenishment. Checkpoint selection
and downloadable JSON retain the evidence. This slice makes no model calls. The city is a deterministic 10×10 grid with 100
nodes and 360 directed road segments. Five inventory identities share one local
agent implementation, with enforced per-store database access, private memory,
frozen role/soul definitions and durable budgets. See [agent foundation](docs/AGENT-FOUNDATION.md).

```bash
docker compose exec -T app delivery lab-demo
```

The default five-product fixture is entirely synthetic. To import a local Bakiano
collector CSV with verified USD prices (not raw mislabeled bolivares):

```bash
delivery import-catalogue PATH_TO_EXPORT.csv artifacts/daka-snapshot.json --source daka --domain retail --confirmed-usd --limit 10
delivery lab-demo --catalogue artifacts/daka-snapshot.json
```

Run those import commands in the host virtual environment, or mount the source
export into the container explicitly. Existing output snapshots are never overwritten.
Imported data stays in ignored `artifacts/`; the UI offers it when that snapshot exists.
Prices retain their observed dates; catalogue listings do not establish real stock.
See [M2 validation](docs/M2-VALIDATION.md) for guarantees and current limits.

### Operations and specialist labs

Open **http://localhost:8010/** for Madrid operations: the real street map,
courier fleets, orders, delivery performance and chaos controls. Simulation setup
is under **Simulation & diagnostics** on the same page.

The older **Delivery** workspace and its fictional grid-city UI have been retired.
`/delivery-lab` redirects to Operations. Its separate run IDs are not forwarded to
the Madrid engine. The [running-city backend](docs/RUNNING-CITY.md), delivery APIs,
CLI regression scenarios and retained evidence remain available for testing;
Health links legacy delivery runs directly to their recorded JSON evidence.
Restaurants and Inventory also retire their fictional grid maps: select agents
from the restaurant roster and stores from the inventory selector. Stock,
reservations, run inspection and replay evidence remain available. The real
Madrid street map in Operations is the single geographic overview.

The [restaurant supply lab](http://localhost:8010/restaurant-lab) adds scheduled
household meal calls, seven restaurants, nearby ingredient markets, reservations,
substitution consent, cooking and courier handoff. Edit entity/agent definitions
from the searchable agent list; inspect private memory and replay recorded business facts. It runs
locally with zero provider calls by default. Optional scoped Jev relevance search
has separate opt-in and budgets. ADK restaurants also support Jev-first decisions
with selective Gemini escalation, and each agent can select no recall, short text,
compact JSON or typed memory. [AI evidence](http://localhost:8010/agent-traces)
retains comparisons without starting new calls. See [agent construction and
routing](docs/ADK-RESTAURANT.md), [memory profiles](docs/AGENT-MEMORY.md), and
[supply contracts](docs/RESTAURANT-SUPPLY.md).

The fixed fleet recovery regression remains available from the CLI:

```bash
docker compose exec -T app delivery delivery-demo
```

Its traffic/dropout scenario and scoped rescue briefings are documented in
[fleet recovery](docs/FLEET-RECOVERY.md).

### Dated Bakiano sample

The local private sample targets October 14-23, 2026 (ten dates). It contains 2,008
observations for October 14-22 from Gama, Central Madeirense, Plazas, Daka and EPA.
October 23 had no observations at extraction time and stays explicitly missing.
Choose a date in the lab, or run:

```bash
docker compose exec -T app delivery lab-demo --sample-date 2026-10-22
```

Samples live in ignored `data/local/bakiano/`, mounted read-only at runtime and
excluded from image builds. The public synthetic fixture remains available without
the private package. See [local dataset policy and acquisition](docs/LOCAL-DATA.md).

Requires Docker with Compose v2.24+ and GNU Make. On Windows, run Make from WSL with Docker Desktop integration enabled. Docker supplies Python and all application dependencies. Ports bind only to localhost: app **8010**, Postgres **55432**, Redis **56379**.

```bash
make demo
```

This builds the image, starts healthy PostGIS and Redis services, seeds the city, and runs the 12-hour simulated day over **600 wall-clock seconds** after setup. Open **http://localhost:8010** while it runs. A slower machine or provider response can extend playback. Results are written to `artifacts/run-<uuid>.json`; the database and UI remain available afterwards.

The checked-in OSM snapshot makes ordinary startup independent of Overpass. Initial Docker builds require internet access. No credentials are required to run: without a configured LLM, complaints are visibly escalated with source `disabled`.

```bash
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

## Cloud activation and cost boundaries

The city stays local. Cloud inference, tracing, analytics and dashboard queries
are separate opt-ins. The existing inference caps are unchanged; cloud storage,
telemetry and query charges are not covered by an inference budget.

```bash
python3 scripts/gcp_demo.py start
python3 scripts/gcp_demo.py status
python3 scripts/gcp_demo.py stop
```

The judge stop command removes its runtime and disables billing while retaining
the project and IAM. Remove optional analytics explicitly before parking; follow
the [BigQuery runbook](docs/GOOGLE-ANALYTICS.md) and
[tracing runbook](docs/OBSERVABILITY.md). Historical cloud receipts describe their
recorded dates; use `status` for a live inventory. No cloud deployment is required
for the portfolio demo. [Setup and cost boundaries](docs/GCP-AI.md).
## Observability

Optional OpenTelemetry follows each order through queue workers, ADK agents and
tools, with FastAPI and Redis spans. Set `MDS_TELEMETRY_ENABLED=1` for console/OTLP
locally or Cloud Trace when `GOOGLE_CLOUD_PROJECT` is set. Separately,
`MDS_BIGQUERY_ENABLED=1` batches sanitized spans, agent steps, terminal orders and
eval results into the Terraform-managed `mds_analytics` dataset. Both flags default
off; ordinary runs and tests need no GCP credentials.

See [observability setup and limits](docs/ARCHITECTURE-OBSERVABILITY.md), the
[trace-flow diagram](docs/ARCHITECTURE-OBSERVABILITY.md#trace-flow), and
[saved analytics queries](sql/analytics) for cost per success, tool p95 and eval
pass^k trends. Queued telemetry can be lost on crashes; business receipts stay in
Postgres and local artifacts.

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

```bash
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

```bash
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

## Held-out release results

`evals/splits.json` freezes disjoint development and reserved release cohorts with
fixture hashes. Ordinary eval CI uses development cases; the manual release job
runs five fresh attempts per reserved case only after full CI passes. Case-level
bootstrap intervals and a paired exact test with family-wise correction distinguish
regressions from sampling noise. Missing/incomparable evidence fails validation;
the first release establishes a baseline without claiming a quality comparison.
Model cost per success includes failed attempts; p95 is reported separately.
These public fixtures are reserved by workflow, not a secret benchmark.

<!-- release-results:start -->
| Held-out arm | Cases × k | pass^k | Bootstrap 95% CI | Cost / success | p95 |
| --- | ---: | ---: | --- | ---: | ---: |
| adk-chaos-customer | 12 × 5 | 1.000 | [1.000, 1.000] | $0.0000 | 15.7 ms |
| adk-chaos-dispatcher | 12 × 5 | 1.000 | [1.000, 1.000] | $0.0000 | 18.6 ms |
| adk-chaos-restaurant | 12 × 5 | 1.000 | [1.000, 1.000] | $0.0000 | 23.9 ms |
| adk-customer-policy | 12 × 5 | 1.000 | [1.000, 1.000] | $0.0000 | 2.5 ms |
| adk-offline-customer | 12 × 5 | 1.000 | [1.000, 1.000] | $0.0000 | 2.5 ms |
| adk-offline-restaurant | 12 × 5 | 1.000 | [1.000, 1.000] | $0.0000 | 17.8 ms |

Measured with fresh ADK sessions and scripted offline models. This is contract
evidence, not live-model quality, inference cost or production latency.
pass^k is the fraction of cases passing every attempt; bootstrap intervals
resample cases. An all-pass cohort has a degenerate [1, 1] interval and does
not establish certainty on unseen workloads. Costs include failed attempts.
Source revision: `751b2d5f8a9c3b33b8301e37680809a452a99d8c`.
<!-- release-results:end -->

### Store model credits

The dark-store view uses NVIDIA SimReady models converted by
[codepawl/simready-glb](https://huggingface.co/datasets/codepawl/simready-glb),
licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
This project simplifies geometry, downsizes textures to 256 px and compresses
meshes for the browser. The seven local models total 920,992 bytes; these are
visual assets, not a robotics physics simulation. Original URLs, the pinned
dataset revision and SHA-256 checksums are in
[the asset manifest](web/vendor/simready/manifest.json). Rebuild with
`node scripts/build_store_assets.mjs` after `npm ci`.

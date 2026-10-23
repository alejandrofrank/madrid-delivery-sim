# Configurable local city sessions

Open `/delivery-lab`. The 32×32 city map loads before a simulation starts. Select a
shop to configure it; select a courier or a shop's team member to inspect that agent.
Pan or zoom the map to follow deliveries. Run evidence stays in a collapsed drawer.

## Controls

| Control | Meaning |
| --- | --- |
| Store name / open for orders | Rename or enable any of the 12 establishments for the next session |
| Stock units | Opening units **per product** at that store, from 0 to 20 |
| Store couriers | 0–3 home couriers per enabled store, with at most 16 in the city |
| Store demand weight | Relative share of arriving orders, from 0 to 3; zero receives no demand |
| Orders per hour | Total city arrival intensity, from 0 to 24; not a rate per shop |
| Duration | Demand generation for 15–120 simulated minutes |
| Traffic multiplier | 0.5–3 times each directed road's base traversal time |
| Dropout / courier-hour | Withdrawal intensity from 0 to 1 per courier-hour |
| Seed | Reproduce the generated demand and withdrawal schedule for the same settings |
| Playback | Target wall-clock playback duration; local processing can extend it |

Settings are frozen at session creation. Saving changes while observing a run edits
the next-run draft, not the current city's stock or history. The persisted configuration
and its hash accompany the run's evidence. Shop positions and categories use the
fixed 12-establishment layout; adding arbitrary map locations is future work.

A store's courier team is a home/employer relationship. Dispatch can send available
couriers from other stores. That relationship grants no inventory or colleague-memory
access: each courier still sees only its own current job and briefing.

## Demand and physical behavior

Orders use seeded exponential interarrival times. Enabled stores are sampled by
their demand weights; products and customer grid nodes are sampled locally. Requests
are released into the queue only when their simulation arrival time is reached.
Future order schedules are operator evidence, not an agent observation or pre-created
fulfillment task. Release is idempotent. Insufficient stock produces real rejections.

Each courier has a seeded first withdrawal time derived from the configured hourly
intensity. Zero disables withdrawal. An idle withdrawal makes the courier unavailable;
an active failure retains parcel custody and queues the existing judge/recovery flow.
No fixed second-180 dropout or forced standby courier is used in configured sessions.

Traffic scales road travel time consistently in planning, independent command
validation and physical motion. Fractional edge times are rounded up individually.
The traffic configuration is read from trusted persisted state, not a model proposal.

Sessions admit at most 24 arrivals, then allow a 60-minute simulated drain after the
demand window. They are finite observations, not perpetual city services. Remaining
jobs stay visible as unfinished when the window ends. If a durable agent/run budget
is exhausted, the session stops with a budget-limit summary and preserves pending
work; it does not turn it into successful deliveries. Existing caps and zero model
spend remain enforced.

## Agent inspection and isolation

Shop panels separate overview, stock and team. An agent panel shows relevant store,
traffic or risk parameters, resource budgets, live private memory and its own courier
briefings. Role definitions/tools are available under details. Memory carries observed
time, expiry and source event; expired entries are counted separately and excluded
from the current-memory list. Refresh the panel to inspect the latest state.

This is a **human operator** view. Its endpoint resolves a requested agent inside
one run, then filters memory by that binding's authenticated namespace. It never
returns login credentials or passes the human inspector into another agent's context.
Database roles, scoped commands and queue-only communication remain unchanged.
The configuration table has no raw agent grants. Home-store staffing does not broaden
an agent's role permissions.

## Verification

The full Linux suite passes **91 tests**, Ruff and mypy. Coverage includes settings
limits, repeatable demand, timed/idempotent release, configured stock/staffing,
fractional traffic recomputation, immutable run settings and selected-agent memory
isolation, plus the existing fleet, crash and Madrid regressions.

```sh
python scripts/city_browser_smoke.py
python scripts/flow_browser_smoke.py
```

The first checks map-first configuration, store/team interactions, timed arrivals,
memory inspection, desktop/mobile layout and reload. The second retains the fixed
fleet recovery scenario through its API and verifies its saved run in the map UI.
Screenshots and evidence stay in ignored `artifacts/`.

The fixed `delivery delivery-demo` remains the deterministic chaos regression,
documented in [fleet recovery](FLEET-RECOVERY.md). Configured sessions run locally
through the UI. Controller restart recovery, live mutation of physical settings,
arbitrary stores, recurring replenishment and longer continuous services are deferred.

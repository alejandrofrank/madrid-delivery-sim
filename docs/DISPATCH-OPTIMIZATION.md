# Dispatch from the street

The Madrid map now defaults to rolling maximum-cardinality, minimum-cost
assignment. Couriers start across nearby stores and remain at their last drop-off
until another job is assigned. A home-base label is administrative affiliation,
not a return instruction. Everything runs locally without model calls.

## What was wrong

The previous dispatcher minimized completion ETA and broke ties by courier ID.
Food preparation can make several completion ETAs identical: the nearby courier
waits longer at the restaurant, while a farther courier spends that time driving.
The lexical tie then selects `01`, even though it wastes empty kilometres.

The backend already retained the customer's node after delivery. The apparent
return on the map came from resetting animation on duplicate snapshots: the UI
projected movement ahead, then drew the same older position again. Six couriers
also began at each hub, obscuring individual markers. One monotonic display clock
now supplies both rendering and animation; duplicate polls do not reset it.
Projection remains bounded to one 60-second simulation tick. SQL snapshots use a
short, read-only repeatable-read transaction so clock, routes and positions agree.

## Assignment algorithm

At each queue-triggered dispatch opportunity, the dispatcher reads at most 100
pending orders and 100 eligible idle couriers. Arrivals already share the city's
60-second clock; no extra artificial batching delay is introduced.

1. Construct directed road routes from each courier's **current** node, through
   the store, to the customer. Never substitute the home-base node.
2. Exclude unreachable routes, insufficient energy reserves and shift overruns.
3. Solve the feasible bipartite graph with exact maximum flow and minimum cost.
   First maximize served orders; then prioritize the earliest deadlines; then
   minimize economic cost for that served order set. Each courier and order may
   participate in one assignment. Charging lateness only to selected jobs would
   otherwise make an overdue order increasingly unattractive when capacity is
   tight. Bounded binary priority weights prevent that starvation trap.
4. For equal total economic cost, prefer longer-idle couriers, then fewer completed
   jobs, then a seeded, non-lexical tie. Fairness does not override road economics.
5. Commit reservations, decision evidence, the queue handoff and event ACK
   atomically. The existing active-order uniqueness constraint still protects
   against competing dispatchers. Couriers accept work through the queue.

The score uses generalized seconds:

```text
completion_duration
+ 20 × lateness
+ empty_pickup_travel_time
+ marginal_vehicle_cost × 3600 / 12
```

The €12/hour conversion, lateness and empty-time weights are editable in the
validated `dispatch` object on `POST /api/runs`. Each run stores a frozen policy.
The UI exposes the two main choices: economic versus legacy dispatch, and staying
at drop-off versus experimental demand-aware repositioning. The legacy arm keeps
the original earliest-completion/ID rule for controlled comparisons. Historical
runs with no policy retain their original interpretation.

Each assignment records its source node, pickup distance, ETA, cost components,
eligible count, batch size and up to five alternative courier scores. An
individually second-best match can be selected when it improves the whole batch.
Inspect this under a courier's recorded evidence on the map.

## Empty travel costs something

Actual movement updates distance, empty distance, normalized energy and marginal
operating cost every tick, including unfinished trips. Cumulative per-leg meters
make repeated ticks and crash replay idempotent. Preparation waits add no distance.
A completed delivery adds the existing €1 task fee once.

| Vehicle | Synthetic marginal cost | Normalized energy per km |
| --- | ---: | ---: |
| Bike | €0.12/km | 1.5 |
| Moto | €0.28/km | 0.7 |
| Van | €0.55/km | 0.4 |

These are simulation assumptions, not measured fuel prices or driver pay. Time
has value in the optimization objective; hourly wages are not charged in the
operating-cost ledger. Whole-fleet cost per completed delivery includes actual
empty repositioning and partial travel. Historical runs predate these meters:
their original completed-task cost remains an estimate and missing empty meters
are displayed as unavailable rather than zero.

## Repositioning is optional and conservative

**Stay at drop-off is the default.** The experimental alternative uses only orders
observed within the previous 30 minutes. It estimates next-15-minute demand,
checks the coverage supplied by other idle couriers and already reserved
destinations, and proposes a move only when the estimated reduction in pickup
time exceeds travel expense plus a two-minute margin.

Moves have a distance cap, cooldown, energy reserve and shift/run horizon. At
most two are proposed per event, and none while orders are still pending. A
durable `courier.reposition` event must be acknowledged before movement begins.
Delayed handoffs rebase departure to acceptance time or cancel when the move no
longer fits. Ordinary delivery assignments also rebase departure and remaining
preparation wait; an infeasible acceptance releases the order for a fresh,
versioned assignment. Every metre consumes energy and cost. There is no teleport or
automatic hub return. Stores with fewer than two observed orders are not targets.

Coverage treats another moving courier's reserved destination as future supply;
this simple forecast can be wrong. Repositioning can cost more than waiting. It
stays optional and is evaluated separately rather than advertised as an automatic
improvement.

## Two city runtimes, explicit boundaries

| Runtime | Implemented here | Remaining work |
| --- | --- | --- |
| Madrid baseline (`/`) | Fleet batch optimization, marginal economics, distributed starts, optional real repositioning, monotonic movement | Traffic-dependent ETA, mode-specific access, bundled multi-stop trips, reassignment during empty travel, calibrated costs and demand forecasting |
| Restaurant/delivery labs | Shared matching primitive for the one basket visible to the role; directed traffic-weighted routes; actual live/custody node; stable basket-specific ties; common-leg search reuse | A scoped multi-order projection and economics ledger before fleet-wide batching/repositioning |

The lab change does not grant access to raw fleet, jobs or another agent's memory.
Its planner receives the existing authorized projection. A global restaurant
optimizer needs a separately reviewed projection/tool, not broader SQL grants.
The Madrid graph still uses fixed mode speeds and a shared directed drivable
network; the lab's simulated traffic weights are not silently applied to it.
Soft lateness penalties do not guarantee every deadline under overloaded demand.
The bounded pending window takes the first 100 deadlines. A backlog of 100
infeasible orders can hide feasible later orders; paged candidate search and an
explicit unsatisfiable-order policy remain future work.

## Reproduce and inspect

Run only against the dedicated local test database. No provider keys or cloud
credentials are needed:

```bash
docker compose exec -T app python scripts/benchmark_dispatch.py \
  --seed 42 --seed 73 --include-reposition \
  --output artifacts/dispatch-comparison.json
node --test scripts/test_courier_motion.cjs
docker compose exec -T app python -m pytest \
  tests/test_dispatch_optimizer.py tests/test_workflow_dispatch.py \
  tests/test_economic_dispatch.py
```

The comparison pairs the same graph, initial fleet and seeded demand; it clears
the route cache between arms and saves complete snapshots. Its wall time includes
SQL, queue handling and Python overhead; it is not a solver-only latency claim.
Costs and job spread accompany completion and lateness so an apparent saving
cannot hide dropped work. The two seeded days are examples, not a statistical
claim about production performance. See the committed [comparison receipt](evidence/dispatch-comparison.json).

Final-policy results on the pinned road graph:

| Seed | Policy | On time / orders | Empty km | Operating cost | Jobs per courier |
| --- | --- | ---: | ---: | ---: | ---: |
| 42 | Legacy, stay | 247 / 247 | 336.980 | €453.96 | 2–35 |
| 42 | Deadline + cost, stay | 247 / 247 | 253.930 | €391.52 | 4–22 |
| 42 | Deadline + cost, reposition | 247 / 247 | 267.316 | €400.76 | 5–22 |
| 73 | Legacy, stay | 248 / 248 | 357.692 | €470.45 | 0–37 |
| 73 | Deadline + cost, stay | 248 / 248 | 260.721 | €401.38 | 5–24 |
| 73 | Deadline + cost, reposition | 248 / 248 | 279.793 | €410.09 | 6–24 |

Across both days, staying with the new matcher reduces empty travel by 25.915%
and simulated total operating cost by 14.227%, with all 495 deliveries on time
and zero dead letters. Repositioning adds 87.376 km of movement and costs more
than staying on these days, which supports keeping it optional. No paid calls
were made. The receipt's source hash matches the final dispatch code; an earlier
exploratory run was superseded after the deadline and handoff fixes.

Tests cover exhaustive small-graph assignment oracles, a greedy assignment trap,
input permutations, bounded batches, equal-ETA near/far regression, staying at
drop-off, partial and duplicate ticks, waiting, one completion fee, delayed/cancelled
relocation, observed-only history, distance/energy/horizon bounds, scoped lab
traffic routes and the animation rewind. Python cases appear under City &
fulfillment in `/health`; the six Node movement cases also run in CI.
The full local suite passed 704 Python tests, Ruff, mypy over 57 modules, twelve
agent scenarios repeated twice with matching business outcomes, and six offline
judge cases. HTTP checks verified local assets and control bindings. A browser
visual review was unavailable because the computer-use service exposed no browsers.

## Why this approach

Uber publicly describes matching nearby requests in short batches to reduce
collective waiting rather than immediately selecting the nearest driver. Its
older Eats engineering account also explains why preparation time and pickup
waiting matter. This project adopts those public principles with an inspectable
operations-research algorithm. It does not reproduce Uber's private production
model or claim state-of-the-art delivery performance. Research on dynamic pickup
and delivery also studies reoptimization with travel and tardiness costs; learned
lookahead and multi-stop search are future extensions here.

Sources reviewed 2026-10-29: [Uber matching](https://www.uber.com/au/en/marketplace/matching/),
[Uber Eats trip optimization (2018)](https://www.uber.com/us/en/blog/uber-eats-trip-optimization/),
[dynamic pickup/delivery cost approximation research](https://arxiv.org/abs/2405.01915).

Implementation: [matcher](../src/delivery/dispatch_optimizer.py),
[policy](../src/delivery/dispatch_policy.py),
[dispatcher and courier](../src/delivery/agents.py),
[repositioning](../src/delivery/dispatch_reposition.py),
[scoped lab planner](../src/delivery/workflow_policy.py),
[road geometry and progress](../src/delivery/world.py),
[snapshot and initial fleet](../src/delivery/simulation.py),
[migration](../sql/migrations/027_economic_dispatch.sql),
[comparison script](../scripts/benchmark_dispatch.py),
[matcher tests](../tests/test_dispatch_optimizer.py),
[economics and recovery tests](../tests/test_economic_dispatch.py),
[lab planner tests](../tests/test_workflow_dispatch.py).

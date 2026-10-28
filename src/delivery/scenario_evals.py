"""Small local worlds that measure real role behavior through scoped queue workers.

Only the trusted fixture controller creates worlds, injects disruptions and observes
state. Agent decisions still use their existing PostgreSQL identities and tools.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import psycopg

from delivery.agent_access import inventory_access, retire_inventory_access, role_access
from delivery.agent_runtime import create_agent
from delivery.db import connect
from delivery.delivery_flow import flow_snapshot, new_delivery, run_delivery
from delivery.fleet_flow import advance_fleet, prepare_fleet
from delivery.lab import create_lab, run_slice
from delivery.queue import publish
from delivery.scenario_report import Evidence, Manifest, Outcome, Scalar, digest, outcome_hash
from delivery.supply import new_supply, provision, replay_supply, run_supply
from delivery.supply_models import SupplyConfig, default_config


def require_local_test_database(url: str) -> None:
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in {"postgres", "postgresql"}
            and parsed.path == "/delivery_test"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1", "postgres"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Scenario evaluations require the local delivery_test database")


@dataclass
class World:
    url: str
    seed: int
    runs: list[str] = field(default_factory=list)
    configuration: str = ""

    def lab(self, *, inventory: bool = False) -> str:
        run = (
            create_lab(self.url, seed=self.seed, city_size=32)
            if inventory
            else new_delivery(self.seed, self.url)
        )
        self.runs.append(run)
        with connect(self.url) as conn:
            row = conn.execute(
                "SELECT city->>'sha256' city,catalogue_hash FROM lab_worlds WHERE run_id=%s",
                (run,),
            ).fetchone()
        self.configuration = digest({"seed": self.seed, "world": row})
        return run

    def supply(self, config: SupplyConfig) -> str:
        self.configuration = digest(config.model_dump(mode="json"))
        run = new_supply(config, self.url)
        self.runs.append(run)
        return run

    def cleanup(self) -> None:
        for run in self.runs:
            retire_inventory_access(run, self.url)
            with connect(self.url) as conn:
                # Facts reference events. Delete the domain parents first.
                conn.execute("DELETE FROM supply_requests WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM supply_sessions WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def denied(dsn: str, statement: str, parameters: tuple[Any, ...] = ()) -> bool:
    """Only a known authorization rejection proves isolation; SQL mistakes do not."""
    try:
        with connect(dsn) as conn:
            conn.execute(statement, parameters)
    except (psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException):
        return True
    return False


def step(run: str, url: str, role: str, key: str) -> None:
    agent = create_agent(role_access(run, role, url)[key].dsn)
    event = agent.claim()
    if event is None or not agent.process(event):
        raise RuntimeError("Expected queued agent step did not complete")


def evidence(events: list[dict[str, Any]]) -> list[Evidence]:
    return [
        Evidence(
            sequence=index,
            topic=row["topic"],
            trace=row["trace_id"],
            state=row["state"],
            attempts=row["attempts"],
            sim_time=row["due_sim"],
        )
        for index, row in enumerate(events, 1)
    ]


def outcome(identifier: str, state: dict[str, Any], **observed: Scalar | None) -> Outcome:
    return Outcome(id=identifier, observed=observed, evidence=evidence(state["events"]))


def stock(state: dict[str, Any]) -> dict[str, Any]:
    return next(
        row
        for row in state["stock"]
        if row["store"] == state["selected_store"] and row["sku"] == state["selected_product"]
    )


def inventory_fixture(world: World) -> list[Outcome]:
    run = world.lab(inventory=True)
    access = inventory_access(run, world.url)["store-1"]
    with connect(access.dsn) as conn:
        visible = conn.execute("SELECT run_id,store FROM lab_stock").fetchall()
    isolated = (
        bool(visible)
        and all(str(s["run_id"]) == run and s["store"] == "store-1" for s in visible)
        and denied(access.dsn, "SET ROLE delivery")
    )
    state = run_slice(run, world.url)
    checkpoints = state["checkpoints"]
    crashed = checkpoints[0]["state"]
    race = checkpoints[1]["state"]
    delayed = checkpoints[3]["state"]
    recovered = next(
        e["attempts"]
        for e in state["events"]
        if e["topic"] == "basket.requested" and e["trace_id"] == "basket-a"
    )
    return [
        outcome(
            "inventory.last-unit",
            race,
            winners=sum(b["status"] == "reserved" for b in race["baskets"]),
            rejected=sum(b["status"] == "rejected" for b in race["baskets"]),
            nonnegative=race["invariants"]["nonnegative_available"],
            isolated=isolated,
        ),
        outcome(
            "inventory.delayed-supply",
            delayed,
            on_hand_at_300=stock(delayed)["on_hand"],
            available_at_300=stock(delayed)["available_now"],
            revised_eta=stock(delayed)["incoming"][0]["expected_sim"],
            final_available=stock(state)["available_now"],
        ),
        outcome(
            "inventory.worker-crash",
            state,
            rolled_back=stock(crashed)["reserved"] == 0
            and not crashed["baskets"]
            and not crashed["decisions"],
            recovered_attempts=recovered,
            receipts=sum(m["kind"] == "received" for m in state["movements"]),
            queue_drained=all(e["state"] == "done" for e in state["events"]),
        ),
    ]


def supply_config(seed: int, variant: str) -> SupplyConfig:
    base = default_config()
    meal = "hamburgers" if variant.startswith("substitution-") else "pizza"
    home = next(e for e in base.entities if e.kind == "household")
    restaurant = next(e for e in base.entities if e.id == f"restaurant-{meal}")
    shops = [e for e in base.entities if e.kind == "market"]
    entities = [
        home.model_copy(
            update={
                "node": 0,
                "recipe_ids": (meal,),
                "allow_substitutions": variant != "substitution-declined",
            }
        ),
        restaurant.model_copy(update={"node": 1}),
    ]
    entities.extend(
        e.model_copy(
            update={
                "node": index + 2,
                "opening_stock": {"beef": 0}
                if meal == "hamburgers"
                else {"flour": 0}
                if variant == "market-forward" and index == 0
                else {},
            }
        )
        for index, e in enumerate(shops)
    )
    candidate = base.model_copy(
        update={
            "seed": seed,
            "entities": tuple(entities),
            "start_hour": 12,
            "duration_minutes": 15,
            "playback_seconds": 0,
            "calls_per_household": 1,
            "restaurant_stock_servings": 1 if variant == "pantry" else 0,
            "market_stock_servings": 3,
        }
    )
    # Revalidate copies so edited fixtures cannot quietly opt into a paid provider.
    config = SupplyConfig.model_validate(candidate.model_dump(mode="json"))
    if any(
        definition.search.provider != "local"
        for definition in [*config.agents.values(), *(e.agent for e in config.entities if e.agent)]
    ):
        raise ValueError("Scenario agents must use local search")
    return config


def supply_fixture(world: World, variant: str) -> list[Outcome]:
    config = supply_config(world.seed, variant)
    run = world.supply(config)
    kitchen = next(e.id for e in config.entities if e.kind == "restaurant")
    agents = provision(run, world.url)
    isolated = denied(agents[kitchen].dsn, "SELECT * FROM supply_stock")
    state = run_supply(run, world.url)
    with connect(world.url) as conn:
        facts = conn.execute(
            "SELECT sim_time,payload->'detail'->>'action' action FROM supply_facts "
            "WHERE run_id=%s ORDER BY sequence",
            (run,),
        ).fetchall()
        consumed_row = conn.execute(
            "SELECT count(*) n FROM supply_allocations WHERE run_id=%s AND consumed",
            (run,),
        ).fetchone()
        calls_row = conn.execute(
            "SELECT (SELECT count(*) FROM agent_model_calls WHERE run_id=%s) + "
            "(SELECT count(*) FROM supply_search_calls WHERE run_id=%s) n",
            (run, run),
        ).fetchone()
        assert consumed_row is not None and calls_row is not None
        consumed, calls = consumed_row["n"], calls_row["n"]
    actions = [f["action"] for f in facts]
    delivered = sum(o["status"] == "delivered" for o in state["orders"])
    conserved = all(state["invariants"].values())
    if variant == "pantry":
        observed = dict(
            delivered=delivered,
            requests=len(state["requests"]),
            conserved=conserved,
            no_external_calls=calls == 0,
        )
    elif variant == "market-forward":
        flour = [r for r in state["requests"] if r["original_ingredient"] == "flour"]
        ready = [f["sim_time"] for f in facts if f["action"] == "meal_ready"]
        arrivals = [f["sim_time"] for f in facts if f["action"] == "ingredient_received"]
        observed = dict(
            delivered=delivered,
            forwarded=bool(flour)
            and flour[0]["visited"] == ["market-a", "market-b"]
            and flour[0]["status"] == "arrived",
            arrival_before_cook=bool(ready) and bool(arrivals) and max(arrivals) <= min(ready),
            replay_matches=replay_supply(run, world.url)["matches"],
            isolated=isolated,
        )
    elif variant == "substitution-declined":
        observed = dict(
            rejected=sum(o["status"] == "failed" for o in state["orders"]),
            declined="household_declined" in actions,
            meals_ready=actions.count("meal_ready"),
            consumed=consumed,
        )
    else:
        stages = ["household_approved", "restaurant_approved", "meal_ready"]
        observed = dict(
            delivered=delivered,
            conserved=conserved,
            ordered_consent=all(s in actions for s in stages)
            and [actions.index(s) for s in stages] == sorted(actions.index(s) for s in stages),
        )
    return [outcome(f"restaurant.{variant}", state, **observed)]


def assignment_fixture(world: World) -> list[Outcome]:
    run = world.lab()
    prepare_fleet(run, world.url)
    access = role_access(run, "dispatcher", world.url)["fleet"]
    isolated = denied(access.dsn, "SELECT * FROM lab_stock")
    with connect(world.url) as conn:
        conn.execute(
            "UPDATE lab_fleet SET status='offline' WHERE run_id=%s AND id<>'bike-1'", (run,)
        )
        for basket in ("race-a", "race-b"):
            conn.execute(
                "INSERT INTO lab_delivery_jobs(run_id,basket,store,pickup_node,customer_node) "
                "VALUES (%s,%s,'store-1',99,100)",
                (run, basket),
            )
            publish(
                conn,
                run_id=run,
                producer="fulfillment",
                topic="basket.ready",
                payload={"basket": basket},
                key=basket,
                trace_id=basket,
                target_store="dispatcher:fleet",
            )
    workers = [create_agent(access.dsn), create_agent(access.dsn)]
    events = [worker.claim() for worker in workers]
    if any(e is None for e in events):
        raise RuntimeError("Race fixture did not supply two independent jobs")

    def process(index: int) -> bool:
        event = events[index]
        assert event is not None
        return workers[index].process(event)

    with ThreadPoolExecutor(max_workers=2) as pool:
        if not all(pool.map(process, range(2))):
            raise RuntimeError("A competing dispatcher failed")
    state = flow_snapshot(run, world.url)
    return [
        outcome(
            "dispatcher.assignment-race",
            state,
            assigned=sum(j["status"] == "assigned" for j in state["jobs"]),
            deferred=sum(j["status"] == "deferred" for j in state["jobs"]),
            busy=sum(c["busy_basket"] is not None for c in state["fleet"]),
            isolated=isolated,
        )
    ]


def courier_fixture(world: World) -> list[Outcome]:
    run = world.lab()
    prepare_fleet(run, world.url)
    for role, key in (
        ("inventory", "store-1"),
        ("fulfillment", "store-1"),
        ("dispatcher", "fleet"),
    ):
        step(run, world.url, role, key)
    couriers = role_access(run, "courier", world.url)
    own = create_agent(couriers["bike-1"].dsn)
    other = couriers["bike-2"].dsn
    event = own.claim()
    if event is None:
        raise RuntimeError("Missing courier briefing")
    foreign = denied(other, "SELECT courier_context('delivery-a',1)") and denied(
        other, "SELECT courier_accept('delivery-a',1)"
    )
    memory = denied(
        other, "SELECT agent_memory_recall(%s,%s,%s)", (event.id, event.token, event.attempts)
    )
    before = flow_snapshot(run, world.url)
    advance_fleet(run, 60, world.url)
    paused = flow_snapshot(run, world.url)
    if not own.process(event):
        raise RuntimeError("Assigned courier did not acknowledge")
    acknowledged = flow_snapshot(run, world.url)
    return [
        outcome(
            "courier.authority",
            acknowledged,
            foreign_brief_denied=foreign,
            foreign_memory_denied=memory,
            ack_wait=before["fleet"] == paused["fleet"]
            and acknowledged["jobs"][0]["depart_sim"] == 60,
            isolated=denied(own.dsn, "SELECT * FROM lab_stock"),
        )
    ]


def fleet_fixture(world: World) -> list[Outcome]:
    run = world.lab()
    state = run_delivery(run, world.url)
    delivered = [j for j in state["jobs"] if j["status"] == "delivered"]
    edges = {(e["from"], e["to"]): e["travel_seconds"] for e in state["city"]["edges"]}
    traffic = all(
        a["edge_durations"]
        == [2 * edges[x, y] for x, y in zip(a["route"], a["route"][1:], strict=False)]
        for a in state["attempts"]
    )
    unique = all(
        len(
            active := [
                j["courier"]
                for j in c["jobs"]
                if j["status"] in {"assigned", "in_transit", "arrived"}
            ]
        )
        == len(set(active))
        for c in state["checkpoints"]
    )
    briefs = [
        b["body"] for b in state["briefs"] if b["basket"] == "delivery-a" and b["attempt"] == 2
    ]
    drops = [i for i in state["incidents"] if i["kind"] == "courier_dropout"]
    checkpoint = next(
        (i["detail"]["checkpoint"] for i in drops if i["basket"] == "delivery-a"), None
    )
    arrivals = [i for i in state["incidents"] if i["kind"] == "courier_arrival"]
    return [
        outcome(
            "dispatcher.traffic-recovery",
            state,
            delivered=len(delivered),
            abandoned=sum(j["status"] == "abandoned" for j in state["jobs"]),
            approved_retries=state["invariants"]["retries_have_approval"],
            traffic_applied=bool(state["attempts"]) and traffic,
            unique_assignments=unique,
        ),
        outcome(
            "courier.dropout-handoff",
            state,
            dropouts=len(drops),
            checkpoint_matches=bool(briefs)
            and briefs[0]["custody_checkpoint"]["node"] == checkpoint,
            brief_sources=bool(briefs)
            and bool(briefs[0]["source_events"])
            and briefs[0]["judge"]["verdict"] == "approved"
            and briefs[0]["prior_courier"] == "bike-1",
            denied_arrivals=sum(i["basket"] == "delivery-b" for i in arrivals),
        ),
        outcome(
            "courier.physical-arrival",
            state,
            arrivals=len(arrivals),
            completion_evidence=bool(delivered)
            and all(
                any(
                    e["topic"] == "delivery.arrived" and e["trace_id"] == j["basket"]
                    for e in state["events"]
                )
                for j in delivered
            ),
            route_durations=bool(state["attempts"])
            and all(
                a["arrive_sim"] - a["depart_sim"] == sum(a["edge_durations"])
                for a in state["attempts"]
            ),
            queue_drained=all(e["state"] == "done" for e in state["events"]),
        ),
    ]


FIXTURES: dict[str, Callable[[World], list[Outcome]]] = {
    "inventory-crash": inventory_fixture,
    "pantry": lambda w: supply_fixture(w, "pantry"),
    "market-forward": lambda w: supply_fixture(w, "market-forward"),
    "substitution-declined": lambda w: supply_fixture(w, "substitution-declined"),
    "substitution-approved": lambda w: supply_fixture(w, "substitution-approved"),
    "assignment-race": assignment_fixture,
    "courier-authority": courier_fixture,
    "fleet": fleet_fixture,
}


def run_once(manifest: Manifest, url: str) -> tuple[list[Outcome], dict[str, str]]:
    require_local_test_database(url)
    fixtures = {spec.fixture for spec in manifest.cases}
    if fixtures != set(FIXTURES):
        raise ValueError("Manifest and scenario runner must declare the same fixtures")
    results: list[Outcome] = []
    configurations = {}
    for identifier in sorted(fixtures):
        world = World(url, manifest.seed)
        rows: list[Outcome] = []
        error = None
        try:
            rows = FIXTURES[identifier](world)
        except Exception:
            # Persist no exception message, SQL/credentials, payload or private memory.
            error = "execution_failed"
        finally:
            try:
                world.cleanup()
            except Exception:
                error = "cleanup_failed"
        expected = [spec.id for spec in manifest.cases if spec.fixture == identifier]
        if len(rows) != len(expected) or {row.id for row in rows} != set(expected):
            rows = [Outcome(id=case, observed={}, error="execution_failed") for case in expected]
        if error:
            rows = [row.model_copy(update={"error": error}) for row in rows]
        results.extend(rows)
        configurations[identifier] = world.configuration or digest(
            {"fixture": identifier, "seed": manifest.seed}
        )
        print(f"Scenario fixture {identifier}: {'completed' if not error else error}", flush=True)
    return results, configurations


def evaluate(manifest: Manifest, url: str, repetitions: int = 2) -> dict[str, Any]:
    require_local_test_database(url)
    if type(repetitions) is not int or not 1 <= repetitions <= 3:
        raise ValueError("Repetitions must be between one and three")
    hashes = []
    previous_results = []
    previous_configurations = []
    for _ in range(repetitions):
        results, configurations = run_once(manifest, url)
        hashes.append(outcome_hash(results))
        previous_results.append([row.model_dump(mode="json") for row in results])
        previous_configurations.append(configurations)
    return {
        "results": [row.model_dump(mode="json") for row in results],
        "configurations": configurations,
        "reproduction": {
            "repetitions": repetitions,
            "hashes": hashes,
            "previous_results": previous_results[:-1],
            "previous_configurations": previous_configurations[:-1],
        },
    }

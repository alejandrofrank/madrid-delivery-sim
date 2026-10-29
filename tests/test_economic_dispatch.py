"""Economic dispatch invariants using local roads/SQL and synthetic cost assumptions.

No provider calls are used. Baseline route times use fixed mode speeds; traffic,
mode-specific street access and measured labor/vehicle costs remain unmodeled.
"""

import math
from typing import Any
from uuid import UUID

import networkx as nx
import pytest
from psycopg.types.json import Jsonb

from delivery.agents import Courier, Dispatcher
from delivery.db import Connection, connect
from delivery.dispatch_policy import DispatchPolicy, assignment_score, operating_cost
from delivery.dispatch_reposition import relocation_choice
from delivery.queue import Queue, publish
from delivery.world import COST_PER_KM, ENERGY_PER_KM, SPEED_MPS, World, seed_locations


@pytest.fixture(scope="session")
def world() -> World:
    return World()


@pytest.fixture(scope="session")
def places(db_url: str, world: World) -> dict[str, Any]:
    with connect(db_url) as conn:
        seed_locations(conn, world)
        store = conn.execute(
            "SELECT * FROM locations WHERE kind='store' ORDER BY id LIMIT 1"
        ).fetchone()
        assert store
        customer = conn.execute(
            "SELECT * FROM locations WHERE kind='customer' AND node<>%s ORDER BY id LIMIT 1",
            (store["node"],),
        ).fetchone()
        hub = conn.execute(
            "SELECT * FROM locations WHERE kind='hub' AND node<>%s ORDER BY id LIMIT 1",
            (store["node"],),
        ).fetchone()
    assert customer and hub
    return {"store": store, "customer": customer, "hub": hub}


def configure(conn: Connection, run: UUID, *, sim: int = 0, **policy: Any) -> None:
    config = DispatchPolicy(**policy).model_dump()
    conn.execute(
        "UPDATE runs SET dispatch_config=%s,sim_time=%s WHERE id=%s", (Jsonb(config), sim, run)
    )


def add_courier(
    conn: Connection, run: UUID, world: World, places: dict[str, Any], courier: str, node: int
) -> None:
    x, y = world.coord(node)
    conn.execute(
        """INSERT INTO couriers(run_id,id,hub,mode,node,point)
        VALUES (%s,%s,%s,'bike',%s,ST_SetSRID(ST_MakePoint(%s,%s),4326))""",
        (run, courier, places["hub"]["id"], node, x, y),
    )


def add_order(
    conn: Connection,
    run: UUID,
    places: dict[str, Any],
    order: str,
    sim: int,
    ready: int,
    *,
    status: str = "pending",
    enqueue: bool = True,
) -> None:
    conn.execute(
        """INSERT INTO orders(run_id,id,store,customer,created_sim,ready_sim,due_sim,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            run,
            order,
            places["store"]["id"],
            places["customer"]["id"],
            sim,
            ready,
            ready + 7200,
            status,
        ),
    )
    if enqueue:
        publish(
            conn,
            run_id=run,
            producer="generator",
            topic="order.created",
            payload={"order_id": order},
            key=order,
            trace_id=order,
            due_sim=sim,
        )


def assign(db_url: str, run: UUID, world: World, order: str, sim: int = 0) -> dict[str, Any]:
    queue = Queue(db_url)
    event = queue.claim("dispatcher", run, sim, accepted_topics=("order.created",))
    assert event and queue.process(event, Dispatcher(world).handle)
    with connect(db_url) as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE run_id=%s AND id=%s", (run, order)
        ).fetchone()
    assert row and row["status"] == "assigned"
    return row


def accept(db_url: str, run: UUID, sim: int, topic: str = "courier.assigned") -> None:
    queue = Queue(db_url)
    event = queue.claim("courier", run, sim, accepted_topics=(topic,))
    assert event and queue.process(event, Courier().handle)


def advance(db_url: str, run: UUID, sim: int) -> None:
    with connect(db_url) as conn:
        conn.execute("UPDATE runs SET sim_time=%s WHERE id=%s", (sim, run))
        Courier().advance(conn, str(run), sim)


def courier_state(db_url: str, run: UUID, courier: str) -> dict[str, Any]:
    with connect(db_url) as conn:
        row = conn.execute(
            "SELECT *,ST_X(point) AS lon,ST_Y(point) AS lat FROM couriers "
            "WHERE run_id=%s AND id=%s",
            (run, courier),
        ).fetchone()
    assert row
    return row


@pytest.mark.integration
@pytest.mark.parametrize("strategy,expected", [("min_cost", "bike-99"), ("legacy", "bike-01")])
def test_equal_completion_eta_prefers_less_empty_travel(
    db_url: str, run_id: UUID, world: World, places: dict[str, Any], strategy: str, expected: str
) -> None:
    far, pickup, destination = (
        places["hub"]["node"],
        places["store"]["node"],
        places["customer"]["node"],
    )
    ready = math.ceil(world.path(far, pickup)[1] / SPEED_MPS["bike"]) + 300
    far_route = world.route(far, pickup, destination, "bike", 0, ready)
    near_route = world.route(pickup, pickup, destination, "bike", 0, ready)
    assert far_route["end_at"] == near_route["end_at"]
    assert far_route["pickup_distance_m"] > near_route["pickup_distance_m"]
    with connect(db_url) as conn:
        configure(conn, run_id, strategy=strategy)
        add_courier(conn, run_id, world, places, "bike-01", far)
        add_courier(conn, run_id, world, places, "bike-99", pickup)
        add_order(conn, run_id, places, "equal-eta", 0, ready)

    assert assign(db_url, run_id, world, "equal-eta")["courier"] == expected


@pytest.mark.integration
def test_next_delivery_starts_at_prior_dropoff_without_hub_return(
    db_url: str, run_id: UUID, world: World, places: dict[str, Any]
) -> None:
    with connect(db_url) as conn:
        configure(conn, run_id)
        add_courier(conn, run_id, world, places, "bike-1", places["store"]["node"])
        add_order(conn, run_id, places, "first", 0, 600)
    first = assign(db_url, run_id, world, "first")
    accept(db_url, run_id, 0)
    finished = first["route"]["end_at"]
    advance(db_url, run_id, finished)
    state = courier_state(db_url, run_id, "bike-1")
    dropoff = places["customer"]["node"]
    assert state["status"] == "idle" and state["node"] == dropoff
    assert [state["lon"], state["lat"]] == pytest.approx(world.coord(dropoff))
    with connect(db_url) as conn:
        add_order(conn, run_id, places, "next", finished, finished + 600)
    second = assign(db_url, run_id, world, "next", finished)

    assert second["courier"] == "bike-1"
    assert second["route"]["start_node"] == dropoff
    assert second["route"]["points"][0][:2] == pytest.approx(world.coord(dropoff))


@pytest.mark.integration
def test_partial_and_duplicate_ticks_charge_real_travel_and_one_task_fee(
    db_url: str, run_id: UUID, world: World, places: dict[str, Any]
) -> None:
    start, pickup = places["hub"]["node"], places["store"]["node"]
    ready = math.ceil(world.path(start, pickup)[1] / SPEED_MPS["bike"]) + 300
    with connect(db_url) as conn:
        configure(conn, run_id)
        add_courier(conn, run_id, world, places, "bike-1", start)
        add_order(conn, run_id, places, "accounted", 0, ready)
    order = assign(db_url, run_id, world, "accounted")
    accept(db_url, run_id, 0)
    route = order["route"]
    partial = math.floor(route["pickup_arrival_at"] / 2)
    assert partial > 0
    advance(db_url, run_id, partial)
    first = courier_state(db_url, run_id, "bike-1")
    expected = partial * SPEED_MPS["bike"]
    assert first["distance_m"] == pytest.approx(expected)
    assert first["empty_distance_m"] == pytest.approx(expected)
    assert first["energy"] == pytest.approx(100 - expected / 1000 * ENERGY_PER_KM["bike"])
    assert first["operating_cost_eur"] == pytest.approx(expected / 1000 * COST_PER_KM["bike"])
    assert first["completed_jobs"] == 0
    advance(db_url, run_id, partial)
    assert courier_state(db_url, run_id, "bike-1") == first

    waiting = math.ceil(route["pickup_arrival_at"]) + 1
    assert waiting < route["pickup_at"]
    advance(db_url, run_id, waiting)
    wait_state = courier_state(db_url, run_id, "bike-1")
    assert wait_state["distance_m"] == pytest.approx(route["pickup_distance_m"])
    assert wait_state["empty_distance_m"] == pytest.approx(route["pickup_distance_m"])
    assert wait_state["completed_jobs"] == 0

    loaded_tick = math.floor((route["pickup_at"] + route["delivery_arrival_at"]) / 2)
    advance(db_url, run_id, loaded_tick)
    loaded = courier_state(db_url, run_id, "bike-1")
    expected = route["pickup_distance_m"] + (loaded_tick - route["pickup_at"]) * SPEED_MPS["bike"]
    assert loaded["distance_m"] == pytest.approx(expected)
    assert loaded["empty_distance_m"] == pytest.approx(route["pickup_distance_m"])
    assert loaded["completed_jobs"] == 0

    advance(db_url, run_id, route["end_at"])
    complete = courier_state(db_url, run_id, "bike-1")
    assert complete["distance_m"] == pytest.approx(route["distance_m"])
    assert complete["empty_distance_m"] == pytest.approx(route["pickup_distance_m"])
    assert complete["energy"] == pytest.approx(
        100 - route["distance_m"] / 1000 * ENERGY_PER_KM["bike"]
    )
    assert complete["operating_cost_eur"] == pytest.approx(
        operating_cost(route["distance_m"], "bike", job=True)
    )
    assert complete["completed_jobs"] == 1
    advance(db_url, run_id, route["end_at"])
    advance(db_url, run_id, route["end_at"] + 60)
    assert courier_state(db_url, run_id, "bike-1") == complete
    with connect(db_url) as conn:
        events = conn.execute(
            "SELECT topic,count(*) AS n FROM events WHERE run_id=%s "
            "AND topic IN ('order.delivered','courier.available') GROUP BY topic",
            (run_id,),
        ).fetchall()
    assert {event["topic"]: event["n"] for event in events} == {
        "order.delivered": 1,
        "courier.available": 1,
    }


def nearby_reposition_start(world: World, pickup: int) -> int:
    x, y = world.coord(pickup)
    for dx, dy in ((0.006, 0), (-0.006, 0), (0, 0.006), (0, -0.006)):
        node = world.nearest(x + dx, y + dy)
        distance = world.path(node, pickup)[1]
        if 600 <= distance <= 1500:
            return node
    raise AssertionError("No bounded nearby relocation fixture in the frozen road graph")


@pytest.mark.integration
def test_relocation_uses_observed_demand_and_waits_for_handoff_before_charging(
    db_url: str, run_id: UUID, world: World, places: dict[str, Any]
) -> None:
    sim = 1000
    pickup = places["store"]["node"]
    start = nearby_reposition_start(world, pickup)
    with connect(db_url) as conn:
        configure(conn, run_id, sim=sim, reposition="demand_aware")
        add_courier(conn, run_id, world, places, "bike-1", start)
        for index in range(6):
            add_order(
                conn,
                run_id,
                places,
                f"future-{index}",
                sim + 1000,
                sim + 1000,
                status="unserved",
                enqueue=False,
            )

    def pulse(key: str) -> None:
        with connect(db_url) as conn:
            publish(
                conn,
                run_id=run_id,
                producer="courier",
                topic="courier.available",
                payload={"courier_id": "bike-1"},
                key=key,
                trace_id=key,
                due_sim=sim,
            )
        queue = Queue(db_url)
        event = queue.claim("dispatcher", run_id, sim, accepted_topics=("courier.available",))
        assert event and queue.process(event, Dispatcher(world).handle)

    pulse("future-only")
    assert courier_state(db_url, run_id, "bike-1")["status"] == "idle"
    with connect(db_url) as conn:
        for index in range(6):
            add_order(
                conn,
                run_id,
                places,
                f"observed-{index}",
                sim - 100,
                sim - 100,
                status="unserved",
                enqueue=False,
            )
    pulse("observed")
    reserved = courier_state(db_url, run_id, "bike-1")
    assert reserved["status"] == "reposition_reserved"
    assert reserved["node"] == start and reserved["distance_m"] == 0
    assert reserved["reposition_route"]["destination"] == pickup
    acknowledged = sim + math.floor(reserved["reposition_route"]["pickup_travel_seconds"] / 2)
    advance(db_url, run_id, acknowledged)
    assert courier_state(db_url, run_id, "bike-1")["distance_m"] == 0
    accept(db_url, run_id, acknowledged, "courier.reposition")
    moving = courier_state(db_url, run_id, "bike-1")
    route = moving["reposition_route"]
    assert moving["status"] == "repositioning" and route["start_at"] == acknowledged
    advance(db_url, run_id, acknowledged)
    assert courier_state(db_url, run_id, "bike-1")["distance_m"] == 0
    partial = acknowledged + math.floor(route["pickup_travel_seconds"] / 2)
    advance(db_url, run_id, partial)
    state = courier_state(db_url, run_id, "bike-1")
    expected = (partial - acknowledged) * SPEED_MPS["bike"]
    assert state["distance_m"] == pytest.approx(expected)
    assert state["empty_distance_m"] == pytest.approx(expected)
    assert state["reposition_distance_m"] == pytest.approx(expected)
    assert state["energy"] == pytest.approx(100 - expected / 1000 * ENERGY_PER_KM["bike"])
    advance(db_url, run_id, route["end_at"])
    complete = courier_state(db_url, run_id, "bike-1")
    assert complete["status"] == "idle" and complete["node"] == pickup
    assert complete["completed_jobs"] == 0 and complete["reposition_route"] is None
    assert complete["distance_m"] == pytest.approx(route["distance_m"])
    assert complete["empty_distance_m"] == pytest.approx(route["distance_m"])
    assert complete["reposition_distance_m"] == pytest.approx(route["distance_m"])
    assert complete["operating_cost_eur"] == pytest.approx(
        operating_cost(route["distance_m"], "bike")
    )
    advance(db_url, run_id, route["end_at"])
    assert courier_state(db_url, run_id, "bike-1") == complete
    with connect(db_url) as conn:
        event = conn.execute(
            "SELECT count(*) AS n FROM events WHERE run_id=%s AND topic='courier.available' "
            "AND dedupe_key LIKE 'relocated:%%'",
            (run_id,),
        ).fetchone()
    assert event == {"n": 1}


@pytest.mark.integration
def test_delayed_relocation_that_exceeds_horizon_cancels_without_travel(
    db_url: str, run_id: UUID, world: World, places: dict[str, Any]
) -> None:
    departure = 1000
    start, destination = places["hub"]["node"], places["store"]["node"]
    route = world.relocation(start, destination, "bike", departure)
    acknowledged = departure + 30
    with connect(db_url) as conn:
        configure(conn, run_id, sim=acknowledged, reposition="demand_aware")
        add_courier(conn, run_id, world, places, "bike-1", start)
        conn.execute(
            "UPDATE couriers SET status='reposition_reserved',reposition_route=%s,shift_end=%s "
            "WHERE run_id=%s AND id='bike-1'",
            (Jsonb(route), route["end_at"] + 610, run_id),
        )
        publish(
            conn,
            run_id=run_id,
            producer="dispatcher",
            topic="courier.reposition",
            payload={"courier_id": "bike-1"},
            key="delayed",
            trace_id="delayed",
            due_sim=departure,
        )
    accept(db_url, run_id, acknowledged, "courier.reposition")
    advance(db_url, run_id, acknowledged)
    state = courier_state(db_url, run_id, "bike-1")
    assert state["status"] == "idle" and state["reposition_route"] is None
    assert state["node"] == start and state["energy"] == 100
    assert state["distance_m"] == state["empty_distance_m"] == state["reposition_distance_m"] == 0
    assert state["operating_cost_eur"] == state["completed_jobs"] == 0
    with connect(db_url) as conn:
        event = conn.execute(
            "SELECT payload FROM events WHERE run_id=%s AND topic='courier.available'",
            (run_id,),
        ).fetchone()
    assert event and event["payload"]["courier_id"] == "bike-1"


def small_world() -> World:
    graph = nx.MultiDiGraph()
    for node in (1, 2, 3):
        graph.add_node(node, x=-3.7 + node * 0.001, y=40.4)
    for source, target in ((1, 2), (2, 1), (2, 3), (3, 2)):
        graph.add_edge(source, target, length=900, travel_time=1)
    return World(graph)


def relocation_input() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    courier = {
        "id": "bike-1",
        "node": 1,
        "mode": "bike",
        "energy": 100,
        "shift_end": 10000,
        "last_reposition_sim": -900,
    }
    demand = [{"store": "observed-store", "node": 2, "orders": 6}]
    return courier, demand


def test_demand_relocation_requires_net_benefit_beyond_empty_trip_cost() -> None:
    courier, demand = relocation_input()
    result = relocation_choice(
        small_world(),
        courier,
        [courier],
        demand,
        1000,
        10000,
        DispatchPolicy(reposition="demand_aware"),
    )
    assert result
    route, saving = result
    assert route["start_node"] == 1 and route["destination"] == 2
    assert route["distance_m"] == 900
    assert saving >= 120


@pytest.mark.parametrize(
    "constraint", ["no_demand", "sparse", "covered", "distance", "cooldown", "energy", "horizon"]
)
def test_relocation_respects_conservative_bounds(constraint: str) -> None:
    courier, demand = relocation_input()
    fleet = [courier]
    policy = DispatchPolicy(reposition="demand_aware")
    duration = 10000
    if constraint == "no_demand":
        demand = []
    elif constraint == "sparse":
        demand[0]["orders"] = 1
    elif constraint == "covered":
        fleet.append({**courier, "id": "bike-2", "node": 2})
    elif constraint == "distance":
        policy = policy.model_copy(update={"reposition_max_m": 500})
    elif constraint == "cooldown":
        courier["last_reposition_sim"] = 900
    elif constraint == "energy":
        courier["energy"] = 11
    elif constraint == "horizon":
        duration = 1700
    assert relocation_choice(small_world(), courier, fleet, demand, 1000, duration, policy) is None


def test_baseline_uses_synthetic_costs_and_fixed_mode_speeds_without_traffic() -> None:
    world = small_world()
    route = world.route(1, 2, 3, "bike", 0, 0)
    assert route["pickup_travel_seconds"] == 900 / SPEED_MPS["bike"]
    assert route["pickup_travel_seconds"] != world.graph[1][2][0]["travel_time"]
    assert operating_cost(1000, "bike", job=True) == pytest.approx(1 + COST_PER_KM["bike"])
    score = assignment_score(route, "bike", 0, 10000, DispatchPolicy())
    assert score["vehicle_cost_seconds"] == pytest.approx(
        operating_cost(route["distance_m"], "bike") * 3600 / 12
    )

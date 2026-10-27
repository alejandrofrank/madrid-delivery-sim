"""Supply behavior and authority checks against real scoped PostgreSQL logins."""

import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from delivery.agent_access import retire_inventory_access
from delivery.agent_runtime import LocalAgent, ScopedTools
from delivery.db import Connection, connect
from delivery.queue import Event, Queue
from delivery.supply import new_supply, provision, release_calls, replay_supply, run_supply
from delivery.supply_models import SupplyConfig, default_config

pytestmark = pytest.mark.integration


@dataclass
class SupplyRun:
    run: str
    config: SupplyConfig
    url: str

    @property
    def household(self) -> str:
        return next(e.id for e in self.config.entities if e.kind == "household")

    @property
    def restaurant(self) -> str:
        return next(e.id for e in self.config.entities if e.kind == "restaurant")


def small_config(
    *,
    meal: str = "pizza",
    households: int = 1,
    pantry: int = 0,
    markets: int = 3,
    allow: bool = True,
    excluded: tuple[str, ...] = (),
) -> SupplyConfig:
    """Use real entity definitions with short connected routes and one meal choice."""
    base = default_config()
    homes = [e for e in base.entities if e.kind == "household"][:households]
    restaurant = next(e for e in base.entities if e.id == f"restaurant-{meal}")
    shops = [e for e in base.entities if e.kind == "market"]
    entities = [
        e.model_copy(
            update={
                "node": 0,
                "recipe_ids": (meal,),
                "allow_substitutions": allow,
                "excluded_ingredients": excluded,
            }
        )
        for e in homes
    ]
    entities.append(restaurant.model_copy(update={"node": 1}))
    entities.extend(e.model_copy(update={"node": index + 2}) for index, e in enumerate(shops))
    candidate = base.model_copy(
        update={
            "entities": tuple(entities),
            "start_hour": 12,
            "duration_minutes": 15,
            "playback_seconds": 0,
            "calls_per_household": 1,
            "restaurant_stock_servings": pantry,
            "market_stock_servings": markets,
        }
    )
    return SupplyConfig.model_validate(candidate.model_dump(mode="json"))


@pytest.fixture
def supply_run(db_url: str) -> Iterator[Callable[..., SupplyRun]]:
    runs: list[str] = []

    def create(**options: Any) -> SupplyRun:
        config = small_config(**options)
        run = new_supply(config, db_url)
        runs.append(run)
        return SupplyRun(run, config, db_url)

    yield create
    for run in runs:
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            # Fact rows reference queue events. Remove the run's domain through its
            # parent first, so those references cannot block normal run cleanup.
            conn.execute("DELETE FROM supply_requests WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM supply_sessions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def opening_stock(run: SupplyRun) -> None:
    """Freeze an operator-injected stock scenario before releasing any demand."""
    with connect(run.url) as conn:
        frozen = conn.execute(
            """SELECT jsonb_agg(to_jsonb(s) ORDER BY owner,ingredient) stock
            FROM supply_stock s WHERE run_id=%s""",
            (run.run,),
        ).fetchone()["stock"]
        conn.execute(
            "UPDATE supply_sessions SET opening=jsonb_set(opening,'{stock}',%s) WHERE run_id=%s",
            (Jsonb(frozen), run.run),
        )


def release(run: SupplyRun, sim: int = 900) -> list[dict[str, Any]]:
    with connect(run.url) as conn:
        schedule = conn.execute(
            "SELECT config->'schedule' schedule FROM supply_sessions WHERE run_id=%s", (run.run,)
        ).fetchone()["schedule"]
        conn.execute("UPDATE runs SET sim_time=%s WHERE id=%s", (sim, run.run))
    release_calls(run.run, schedule, sim, run.url)
    return schedule


def claim(agent: LocalAgent) -> Event:
    event = agent.claim()
    assert event is not None
    return event


def drain_kitchen(run: SupplyRun, agents: dict[str, LocalAgent]) -> None:
    """Drain supply events through cooking; keep delivery observation for the world."""
    for _ in range(200):
        with connect(run.url) as conn:
            row = conn.execute(
                """SELECT target_store,due_sim FROM events WHERE run_id=%s AND state='ready'
                AND topic NOT IN ('basket.ready','meal.delivery')
                ORDER BY due_sim,id LIMIT 1""",
                (run.run,),
            ).fetchone()
            if not row:
                return
            conn.execute(
                "UPDATE runs SET sim_time=greatest(sim_time,%s) WHERE id=%s",
                (row["due_sim"], run.run),
            )
        agent = agents[row["target_store"]]
        assert agent.process(claim(agent))
    raise AssertionError("Kitchen event drain exceeded its bounded step count")


def test_completed_supplier_memory_expires_but_keeps_revision_history(
    supply_run: Callable[..., SupplyRun],
) -> None:
    run = supply_run()
    state = run_supply(run.run, run.url)
    assert state["orders"][0]["status"] == "delivered"
    with connect(run.url) as conn:
        rows = conn.execute(
            "SELECT * FROM agent_memory_facts WHERE run_id=%s AND kind='market.request' "
            "ORDER BY id",
            (run.run,),
        ).fetchall()
        by_id = {row["id"]: row for row in rows}
        assert len(rows) == 8
        assert any(
            row["body"]["outcome"] == "supplier_reserved"
            and row["expires_sim"] > state["run"]["sim_time"]
            for row in rows
        )
        for row in rows:
            if row["body"]["outcome"] == "supplier_reserved":
                assert row["expires_sim"] - row["observed_sim"] == 3600
            else:
                assert row["body"]["outcome"] == "supplier_dispatched"
                assert row["expires_sim"] - row["observed_sim"] == 60
                assert by_id[row["previous_id"]]["subject"] == row["subject"]
                assert row["expires_sim"] <= state["run"]["sim_time"]
        assert (
            conn.execute(
                "SELECT count(*) n FROM agent_memory_current WHERE run_id=%s "
                "AND kind='market.request' AND expires_sim>%s",
                (run.run, state["run"]["sim_time"]),
            ).fetchone()["n"]
            == 0
        )


def test_real_supply_roles_deny_raw_state_forgery_and_cross_household_memory(
    supply_run: Callable[..., SupplyRun],
) -> None:
    run = supply_run(households=2)
    agents = provision(run.run, run.url)
    schedule = release(run)
    homes = [e.id for e in run.config.entities if e.kind == "household"]
    a, b = agents[homes[0]], agents[homes[1]]
    ea, eb = claim(a), claim(b)
    assert a.reserve_budget(ea) and b.reserve_budget(eb)
    other_order = next(o["order_id"] for o in schedule if o["household"] == homes[1])
    for agent in (a, agents[run.restaurant], agents["market-a"]):
        with connect(agent.dsn) as conn:
            for statement in (
                "SELECT * FROM supply_stock",
                "SELECT * FROM lab_stock",
                "SELECT * FROM supply_facts",
                "UPDATE supply_facts SET actor=actor",
                "DELETE FROM supply_facts",
                "UPDATE events SET payload=payload",
                "UPDATE events SET target_store=target_store",
                "SET ROLE delivery",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(statement)
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(
                    """INSERT INTO events(run_id,producer,topic,payload,dedupe_key,
                    trace_id,target_store) VALUES (%s,'household','household.call','{}',
                    'forged','forged',%s)""",
                    (run.run, run.restaurant),
                )
    with connect(a.dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT supply_context(%s)", (other_order,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT supply_command(%s,%s,%s)", (ea.id, uuid4(), ea.attempts))
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT supply_command(%s,%s,%s)", (eb.id, eb.token, eb.attempts))
        tools = ScopedTools(conn, a.scope, a.role, ea)
        tools.invoke(
            "memory.write", kind="household.order", body={"status": "calling", "action": "calling"}
        )
        assert tools.invoke("memory.read")[0]["body"] == {"status": "calling", "action": "calling"}
    with connect(b.dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT * FROM agent_memories")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                """INSERT INTO agent_memories(run_id,store,key,body,observed_sim,
                expires_sim,event_id) VALUES (%s,%s,'forged','{}',900,1000,%s)""",
                (run.run, homes[0], eb.id),
            )


def test_supply_stock_facts_memory_and_outgoing_events_roll_back_before_ack(
    supply_run: Callable[..., SupplyRun],
) -> None:
    run = supply_run(pantry=1)
    agents = provision(run.run, run.url)
    release(run)
    home, kitchen = agents[run.household], agents[run.restaurant]
    assert home.process(claim(home))
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run.run,))
    event = claim(kitchen)
    assert kitchen.reserve_budget(event)

    def crash_after_command(conn: Connection, message: Event) -> None:
        kitchen.handle(conn, message)
        raise RuntimeError("Injected failure between mutation and acknowledgement")

    assert not Queue(kitchen.dsn).process(event, crash_after_command)
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT sum(reserved) n FROM supply_stock WHERE run_id=%s", (run.run,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_facts WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM events WHERE parent_id=%s", (event.id,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM agent_memory_facts WHERE run_id=%s AND store=%s",
                (run.run, run.restaurant),
            ).fetchone()["n"]
            == 0
        )
        conn.execute("UPDATE events SET available_at='1970-01-01 UTC' WHERE id=%s", (event.id,))
    retry = claim(kitchen)
    assert retry.id == event.id and retry.attempts == event.attempts + 1
    assert kitchen.process(retry)
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_facts WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM events WHERE parent_id=%s AND topic='restaurant.cook'",
                (event.id,),
            ).fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_allocations WHERE run_id=%s", (run.run,)
            ).fetchone()["n"]
            == 4
        )
        assert (
            conn.execute("SELECT state FROM events WHERE id=%s", (event.id,)).fetchone()["state"]
            == "done"
        )


def test_supplier_recall_is_restricted_to_the_current_ingredient_request(
    supply_run: Callable[..., SupplyRun],
) -> None:
    run = supply_run(pantry=0)
    agents = provision(run.run, run.url)
    release(run)
    home, kitchen, market = agents[run.household], agents[run.restaurant], agents["market-a"]
    assert home.process(claim(home))
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run.run,))
    assert kitchen.process(claim(kitchen))
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1020 WHERE id=%s", (run.run,))
    first = claim(market)
    assert market.process(first)
    second = claim(market)
    assert first.payload["order"] == second.payload["order"]
    assert first.payload["request"] != second.payload["request"]
    assert market.reserve_budget(second)
    with connect(market.dsn) as conn:
        tools = ScopedTools(conn, market.scope, market.role, second)
        assert tools.invoke("memory.read") == []
        with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
            tools.invoke("memory.read", kinds=["household.order"])
    with connect(agents["market-b"].dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                "SELECT agent_memory_recall(%s,%s,%s)", (second.id, second.token, second.attempts)
            )


def test_two_orders_cannot_reserve_the_last_recipe_twice(
    supply_run: Callable[..., SupplyRun],
) -> None:
    run = supply_run(households=2, pantry=1, markets=0, allow=False)
    agents = provision(run.run, run.url)
    release(run)
    for household in (e.id for e in run.config.entities if e.kind == "household"):
        assert agents[household].process(claim(agents[household]))
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run.run,))
    kitchen = agents[run.restaurant]
    incoming = [claim(kitchen), claim(kitchen)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(kitchen.process, incoming))
    drain_kitchen(run, agents)
    with connect(run.url) as conn:
        orders = conn.execute(
            "SELECT status FROM supply_orders WHERE run_id=%s ORDER BY id", (run.run,)
        ).fetchall()
        assert sorted(o["status"] for o in orders) == ["failed", "ready"]
        assert (
            conn.execute(
                """SELECT count(*) n FROM supply_stock WHERE run_id=%s
            AND (on_hand<0 OR reserved<0 OR reserved>on_hand)""",
                (run.run,),
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM lab_delivery_jobs WHERE run_id=%s", (run.run,)
            ).fetchone()["n"]
            == 1
        )


def test_nearest_empty_market_forwards_without_household_disclosure(
    supply_run: Callable[..., SupplyRun],
) -> None:
    run = supply_run()
    with connect(run.url) as conn:
        conn.execute(
            """UPDATE supply_stock SET on_hand=0 WHERE run_id=%s
            AND owner='market-a' AND ingredient='flour'""",
            (run.run,),
        )
    opening_stock(run)
    agents = provision(run.run, run.url)
    release(run)
    assert agents[run.household].process(claim(agents[run.household]))
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run.run,))
    assert agents[run.restaurant].process(claim(agents[run.restaurant]))
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1100 WHERE id=%s", (run.run,))
    market = agents["market-a"]
    event = claim(market)
    with connect(market.dsn) as conn:
        context = conn.execute(
            "SELECT supply_context(%s) data", (event.payload["order"],)
        ).fetchone()["data"]
        encoded = json.dumps(context, default=str)
        assert run.household not in encoded
        assert "excluded_ingredients" not in encoded and "household_approved" not in encoded
        assert {stock["owner"] for stock in context["stock"]} == {"market-a"}
    assert market.process(event)
    drain_kitchen(run, agents)
    with connect(run.url) as conn:
        flour = conn.execute(
            "SELECT * FROM supply_requests WHERE run_id=%s AND original_ingredient='flour'",
            (run.run,),
        ).fetchone()
        assert flour["market"] == "market-b"
        assert flour["visited"] == ["market-a", "market-b"]
        assert flour["status"] == "arrived"
        assert (
            conn.execute(
                """SELECT count(*) n FROM supply_facts WHERE run_id=%s AND actor='market-a'
            AND payload->'detail'->>'action'='forwarded'""",
                (run.run,),
            ).fetchone()["n"]
            == 1
        )
    assert replay_supply(run.run, run.url)["matches"]


@pytest.mark.parametrize(
    ("allow", "excluded", "expected_status", "expected_action"),
    [
        (True, (), "delivered", "restaurant_approved"),
        (False, (), "failed", "household_declined"),
        (True, ("chicken",), "failed", "unfulfillable"),
    ],
)
def test_shortage_requires_household_and_restaurant_approval_and_respects_exclusions(
    supply_run: Callable[..., SupplyRun],
    allow: bool,
    excluded: tuple[str, ...],
    expected_status: str,
    expected_action: str,
) -> None:
    run = supply_run(meal="hamburgers", allow=allow, excluded=excluded)
    with connect(run.url) as conn:
        conn.execute(
            "UPDATE supply_stock SET on_hand=0 WHERE run_id=%s AND ingredient='beef'", (run.run,)
        )
    opening_stock(run)
    state = run_supply(run.run, run.url)
    assert state["orders"][0]["status"] == expected_status
    assert state["metrics"]["model_calls"] == 0
    assert state["invariants"]["stock_nonnegative"]
    with connect(run.url) as conn:
        actions = [
            r["action"]
            for r in conn.execute(
                """SELECT payload->'detail'->>'action' action FROM supply_facts
                    WHERE run_id=%s ORDER BY sequence""",
                (run.run,),
            ).fetchall()
        ]
        assert expected_action in actions
        if expected_status == "delivered":
            assert actions.index("household_approved") < actions.index("restaurant_approved")
            assert actions.index("restaurant_approved") < actions.index("meal_ready")
        else:
            assert "meal_ready" not in actions
    assert replay_supply(run.run, run.url)["matches"]


def test_partial_pantry_stock_requests_only_the_missing_quantity(
    supply_run: Callable[..., SupplyRun],
) -> None:
    run = supply_run(pantry=1)
    with connect(run.url) as conn:
        conn.execute(
            """UPDATE supply_stock SET on_hand=50 WHERE run_id=%s
            AND owner=%s AND ingredient='flour'""",
            (run.run, run.restaurant),
        )
        initial = conn.execute(
            "SELECT sum(on_hand) n FROM supply_stock WHERE run_id=%s AND ingredient='flour'",
            (run.run,),
        ).fetchone()["n"]
    opening_stock(run)
    state = run_supply(run.run, run.url)
    assert state["orders"][0]["status"] == "delivered"
    with connect(run.url) as conn:
        request = conn.execute(
            """SELECT quantity,status FROM supply_requests
            WHERE run_id=%s AND original_ingredient='flour'""",
            (run.run,),
        ).fetchone()
        assert request == {"quantity": 100, "status": "arrived"}
        allocation = conn.execute(
            """SELECT quantity,consumed,released FROM supply_allocations
            WHERE run_id=%s AND ingredient='flour'""",
            (run.run,),
        ).fetchone()
        assert allocation == {"quantity": 150, "consumed": True, "released": False}
        final = conn.execute(
            "SELECT sum(on_hand) n FROM supply_stock WHERE run_id=%s AND ingredient='flour'",
            (run.run,),
        ).fetchone()["n"]
        assert final == initial - 150
        assert (
            conn.execute(
                "SELECT sum(reserved) n FROM supply_stock WHERE run_id=%s", (run.run,)
            ).fetchone()["n"]
            == 0
        )
    assert replay_supply(run.run, run.url)["matches"]


def test_deadline_failure_still_receives_goods_already_in_transit(
    supply_run: Callable[..., SupplyRun],
) -> None:
    run = supply_run()
    agents = provision(run.run, run.url)
    with connect(run.url) as conn:
        initial = conn.execute(
            "SELECT sum(on_hand) n FROM supply_stock WHERE run_id=%s AND ingredient='flour'",
            (run.run,),
        ).fetchone()["n"]
        deadline = conn.execute(
            "SELECT deadline FROM supply_orders WHERE run_id=%s", (run.run,)
        ).fetchone()["deadline"]
    release(run)
    assert agents[run.household].process(claim(agents[run.household]))
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run.run,))
    kitchen, market = agents[run.restaurant], agents["market-a"]
    assert kitchen.process(claim(kitchen))
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1100 WHERE id=%s", (run.run,))
    for _ in range(4):
        request = claim(market)
        assert request.topic == "market.request"
        assert market.process(request)
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1200 WHERE id=%s", (run.run,))
    transfer = claim(market)
    assert transfer.topic == "market.transfer"
    assert transfer.payload["request"].endswith(":flour")
    assert market.process(transfer)
    with connect(run.url) as conn:
        assert (
            conn.execute(
                """SELECT status FROM supply_requests
                WHERE run_id=%s AND original_ingredient='flour'""",
                (run.run,),
            ).fetchone()["status"]
            == "transit"
        )
        assert (
            conn.execute(
                "SELECT sum(on_hand) n FROM supply_stock WHERE run_id=%s AND ingredient='flour'",
                (run.run,),
            ).fetchone()["n"]
            == initial - 150
        )
        conn.execute("UPDATE runs SET sim_time=%s WHERE id=%s", (deadline + 1, run.run))
    arrival = claim(kitchen)
    assert arrival.topic == "ingredient.arrived"
    assert kitchen.process(arrival)
    with connect(run.url) as conn:
        assert (
            conn.execute("SELECT status FROM supply_orders WHERE run_id=%s", (run.run,)).fetchone()[
                "status"
            ]
            == "failed"
        )
        assert (
            conn.execute(
                "SELECT sum(on_hand) n FROM supply_stock WHERE run_id=%s AND ingredient='flour'",
                (run.run,),
            ).fetchone()["n"]
            == initial
        )
        assert (
            conn.execute(
                "SELECT sum(reserved) n FROM supply_stock WHERE run_id=%s", (run.run,)
            ).fetchone()["n"]
            == 0
        )
        assert conn.execute(
            """SELECT on_hand,reserved FROM supply_stock
            WHERE run_id=%s AND owner=%s AND ingredient='flour'""",
            (run.run, run.restaurant),
        ).fetchone() == {"on_hand": 150, "reserved": 0}
    assert replay_supply(run.run, run.url)["matches"]


def test_complete_run_replays_without_agents_and_detects_fact_hash_corruption(
    supply_run: Callable[..., SupplyRun],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = supply_run()
    state = run_supply(run.run, run.url)
    assert state["metrics"]["delivered"] == 1
    assert state["metrics"]["model_provider"] == "disabled"
    assert state["run"]["status"] == "complete"
    assert state["invariants"]["stock_conserved"]

    def no_provider_or_agent(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Replay must not execute agents or providers")

    monkeypatch.setattr("delivery.supply.provision", no_provider_or_agent)
    replay = replay_supply(run.run, run.url)
    assert replay["matches"] and replay["hash_chain_valid"]
    assert replay["facts"] > 0 and replay["model_calls"] == 0
    assert all(replay["projections"].values())
    with connect(run.url) as conn:
        fact = conn.execute(
            "SELECT sequence,hash FROM supply_facts WHERE run_id=%s ORDER BY sequence LIMIT 1",
            (run.run,),
        ).fetchone()
        conn.execute(
            "UPDATE supply_facts SET hash=%s WHERE run_id=%s AND sequence=%s",
            ("f" * 64, run.run, fact["sequence"]),
        )
    try:
        corrupted = replay_supply(run.run, run.url)
        assert not corrupted["hash_chain_valid"] and not corrupted["matches"]
    finally:
        with connect(run.url) as conn:
            conn.execute(
                "UPDATE supply_facts SET hash=%s WHERE run_id=%s AND sequence=%s",
                (fact["hash"], run.run, fact["sequence"]),
            )


def test_controller_retries_a_worker_failure_without_duplicate_stock_effects(
    supply_run: Callable[..., SupplyRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    from delivery.supply_policy import SupplyPolicy

    run = supply_run(pantry=1)
    original = SupplyPolicy.decide
    crashed = False

    def fail_once(self: SupplyPolicy, event: Event, tools: ScopedTools) -> dict[str, Any]:
        nonlocal crashed
        if not crashed and event.topic == "restaurant.cook":
            crashed = True
            tools.invoke("supply.command")
            raise RuntimeError("Synthetic crash after inventory mutation before commit")
        return original(self, event, tools)

    monkeypatch.setattr(SupplyPolicy, "decide", fail_once)
    state = run_supply(run.run, run.url)
    assert crashed and state["run"]["status"] == "complete"
    assert state["metrics"]["delivered"] == 1
    assert state["invariants"]["stock_nonnegative"]
    assert state["invariants"]["stock_conserved"]
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT attempts FROM events WHERE run_id=%s AND topic='restaurant.cook'",
                (run.run,),
            ).fetchone()["attempts"]
            == 2
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM lab_delivery_jobs WHERE run_id=%s", (run.run,)
            ).fetchone()["n"]
            == 1
        )
        assert conn.execute(
            "SELECT step_slots,events_limit,tools_limit FROM agent_budgets "
            "WHERE run_id=%s AND store='dispatcher:fleet'",
            (run.run,),
        ).fetchone() == {"step_slots": 6, "events_limit": 333, "tools_limit": 2000}
    assert replay_supply(run.run, run.url)["matches"]

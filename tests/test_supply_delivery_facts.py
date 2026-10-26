"""Delivery projection facts survive household termination and roll back atomically."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest

import delivery.supply as supply
from delivery.agent_access import retire_inventory_access
from delivery.agent_runtime import LocalAgent
from delivery.db import connect
from delivery.delivery_flow import new_delivery
from delivery.fleet_flow import advance_fleet
from delivery.queue import Event
from delivery.supply_models import SupplyConfig, default_config

pytestmark = pytest.mark.integration


@dataclass
class DeliveryFactsRun:
    run: str
    url: str


@pytest.fixture
def delivery_facts_run(db_url: str) -> Iterator[Callable[..., DeliveryFactsRun]]:
    runs: list[str] = []

    def create(*, is_supply: bool = True) -> DeliveryFactsRun:
        if is_supply:
            raw = default_config().model_dump(mode="json")
            home = next(e for e in raw["entities"] if e["kind"] == "household")
            home.update(node=0, recipe_ids=["pizza"])
            kitchen = next(e for e in raw["entities"] if e["id"] == "restaurant-pizza")
            kitchen["node"] = 1
            markets = [e for e in raw["entities"] if e["kind"] == "market"]
            for index, market in enumerate(markets):
                market["node"] = index + 2
            raw.update(
                entities=[home, kitchen, *markets],
                start_hour=12,
                duration_minutes=15,
                playback_seconds=0,
                calls_per_household=1,
                restaurant_stock_servings=1,
            )
            run = supply.new_supply(SupplyConfig.model_validate(raw), db_url)
        else:
            run = new_delivery(url=db_url)
        runs.append(run)
        return DeliveryFactsRun(run, db_url)

    yield create
    for run in runs:
        with supply._LOCK:
            for key in list(supply._AGENTS):
                if key[0] == run:
                    del supply._AGENTS[key]
            for token, grant in list(supply._TOKENS.items()):
                if grant[0] == run:
                    del supply._TOKENS[token]
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            conn.execute("DELETE FROM supply_sessions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))
            assert (
                conn.execute(
                    "SELECT count(*) n FROM supply_facts WHERE run_id=%s",
                    (run,),
                ).fetchone()["n"]
                == 0
            )


def claim(agent: LocalAgent) -> Event:
    event = agent.claim()
    assert event is not None
    return event


def clock(run: DeliveryFactsRun, sim: int) -> None:
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=%s WHERE id=%s", (sim, run.run))


def test_world_and_dispatcher_after_terminal_household_still_replay_exactly(
    delivery_facts_run: Callable[..., DeliveryFactsRun],
) -> None:
    run = delivery_facts_run()
    agents = supply.provision(run.run, run.url)
    home = next(a for a in agents.values() if a.role.name == "household")
    kitchen, dispatcher = agents["restaurant-pizza"], agents["dispatcher:fleet"]
    with connect(run.url) as conn:
        schedule = conn.execute(
            "SELECT config->'schedule' schedule FROM supply_sessions WHERE run_id=%s",
            (run.run,),
        ).fetchone()["schedule"]
    clock(run, 900)
    supply.release_calls(run.run, schedule, 900, run.url)
    assert home.process(claim(home))
    clock(run, 1000)
    assert kitchen.process(claim(kitchen))
    clock(run, 1100)
    cooking = claim(kitchen)
    assert cooking.topic == "restaurant.cook" and kitchen.process(cooking)
    clock(run, 1200)
    ready = claim(dispatcher)
    assert ready.topic == "basket.ready" and dispatcher.process(ready)
    with connect(run.url) as conn:
        job = conn.execute(
            "SELECT * FROM lab_delivery_jobs WHERE run_id=%s",
            (run.run,),
        ).fetchone()
    courier = agents[f"courier:{job['courier']}"]
    briefing = claim(courier)
    assert briefing.topic == "courier.briefed" and courier.process(briefing)
    with connect(run.url) as conn:
        # Inject a deadline that expires while this accepted physical trip is in
        # progress. The subsequent household command records the order after-image.
        conn.execute("UPDATE supply_orders SET deadline=1201 WHERE run_id=%s", (run.run,))
        conn.execute("UPDATE lab_delivery_jobs SET deadline_sim=1201 WHERE run_id=%s", (run.run,))
        job = conn.execute(
            "SELECT * FROM lab_delivery_jobs WHERE run_id=%s",
            (run.run,),
        ).fetchone()
        assert job["accepted"] and job["arrive_sim"] > 1202
    clock(run, 1202)
    observation = claim(home)
    assert observation.topic == "meal.delivery" and home.process(observation)
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT status FROM supply_orders WHERE run_id=%s",
                (run.run,),
            ).fetchone()["status"]
            == "failed"
        )
    # Real world motion and the real dispatcher now mutate the job after the
    # household's final fact. Each change must enter the same canonical ledger.
    advance_fleet(run.run, job["arrive_sim"] + 1, run.url, dropouts=set())
    for _ in range(4):
        event = dispatcher.claim()
        if event is None:
            break
        assert dispatcher.process(event)
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT status FROM lab_delivery_jobs WHERE run_id=%s",
                (run.run,),
            ).fetchone()["status"]
            == "delivered"
        )
        changes = conn.execute(
            """SELECT actor,event_id,payload->'detail'->>'status' status FROM supply_facts
            WHERE run_id=%s AND kind='delivery.job.changed' ORDER BY sequence""",
            (run.run,),
        ).fetchall()
        assert all(change["event_id"] is None for change in changes)
        assert any(c["actor"] == "lab_world" and c["status"] == "arrived" for c in changes)
        assert any(c["actor"] == "dispatcher:fleet" and c["status"] == "delivered" for c in changes)
    replay = supply.replay_supply(run.run, run.url)
    assert replay["matches"] and replay["hash_chain_valid"]
    assert all(replay["projections"].values())


def insert_job(conn: Any, run: DeliveryFactsRun, basket: str = "trigger-probe") -> None:
    conn.execute(
        """INSERT INTO lab_delivery_jobs(run_id,basket,store,pickup_node,customer_node)
        VALUES(%s,%s,'restaurant-pizza',1,0)""",
        (run.run, basket),
    )


def test_delivery_facts_roll_back_with_job_changes_and_skip_noop_updates(
    delivery_facts_run: Callable[..., DeliveryFactsRun],
) -> None:
    run = delivery_facts_run()
    with pytest.raises(RuntimeError, match="Injected"), connect(run.url) as conn:
        insert_job(conn, run)
        raise RuntimeError("Injected failure before commit")
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM lab_delivery_jobs WHERE run_id=%s",
                (run.run,),
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_facts WHERE run_id=%s",
                (run.run,),
            ).fetchone()["n"]
            == 0
        )
        insert_job(conn, run)
    with pytest.raises(RuntimeError, match="Injected"), connect(run.url) as conn:
        conn.execute("UPDATE lab_delivery_jobs SET status='deferred' WHERE run_id=%s", (run.run,))
        raise RuntimeError("Injected failure after update")
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT status FROM lab_delivery_jobs WHERE run_id=%s",
                (run.run,),
            ).fetchone()["status"]
            == "ready"
        )
        conn.execute("UPDATE lab_delivery_jobs SET status=status WHERE run_id=%s", (run.run,))
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_facts WHERE run_id=%s",
                (run.run,),
            ).fetchone()["n"]
            == 1
        )
    assert supply.replay_supply(run.run, run.url)["matches"]


def test_non_supply_delivery_jobs_do_not_generate_supply_facts(
    delivery_facts_run: Callable[..., DeliveryFactsRun],
) -> None:
    run = delivery_facts_run(is_supply=False)
    with connect(run.url) as conn:
        insert_job(conn, run)
        conn.execute("UPDATE lab_delivery_jobs SET status='deferred' WHERE run_id=%s", (run.run,))
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_facts WHERE run_id=%s",
                (run.run,),
            ).fetchone()["n"]
            == 0
        )


def test_supply_roles_cannot_execute_the_trigger_helper_or_mutate_jobs_directly(
    delivery_facts_run: Callable[..., DeliveryFactsRun],
) -> None:
    run = delivery_facts_run()
    agents = supply.provision(run.run, run.url)
    for role in ("household", "restaurant", "market", "dispatcher", "courier", "judge"):
        agent = next(a for a in agents.values() if a.role.name == role)
        with connect(agent.dsn) as conn:
            assert not conn.execute(
                """SELECT has_function_privilege(current_user,
                'public.supply_record_delivery_job()','EXECUTE') allowed""",
            ).fetchone()["allowed"]
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute("SELECT public.supply_record_delivery_job()")
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                insert_job(conn, run)

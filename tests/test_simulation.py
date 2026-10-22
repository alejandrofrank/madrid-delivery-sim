import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from delivery.agents import Dispatcher
from delivery.config import Settings
from delivery.customer_service import (
    MAX_OUTPUT,
    RESERVED_TOKENS,
    SYSTEM,
    Advice,
    CustomerService,
    complaint_prompt,
    refund_policy,
)
from delivery.db import connect
from delivery.queue import Queue, publish
from delivery.simulation import Simulation, create_run, demand_rate, generate, snapshot
from delivery.world import World, position, seed_locations


@pytest.fixture(scope="session")
def world() -> World:
    return World()


def test_real_graph_routes_and_waiting(world: World) -> None:
    manifest = json.loads(Path("data/manifest.json").read_text())
    assert manifest["nodes"] == len(world.nodes) > 1000
    a, b, c = (
        world.nearest(-3.704, 40.436),
        world.nearest(-3.70, 40.43),
        world.nearest(-3.695, 40.435),
    )
    route = world.route(a, b, c, "bike", 0, 1800)
    assert route["distance_m"] > 100
    assert route["pickup_at"] >= 1860
    assert position(route, 0) == world.coord(a)
    assert position(route, 1850) == pytest.approx(world.coord(b))
    assert position(route, route["end_at"] + 1) == world.coord(c)
    assert all(x[2] <= y[2] for x, y in zip(route["points"], route["points"][1:], strict=False))


def test_peak_demand_and_refund_gate() -> None:
    assert demand_rate(13.5) > 4 * demand_rate(10)
    assert demand_rate(20) > 4 * demand_rate(17)
    assert refund_policy(500, True) == ("awaiting_approval", 0)
    assert refund_policy(50, True) == ("resolved", 5)
    assert refund_policy(5, False) == ("resolved", 0)
    with pytest.raises(ValidationError):
        Advice.model_validate({"category": "refund", "reply": "ok", "tool": "delete_orders"})
    with pytest.raises(ValidationError):
        Advice(category="execute_sql", reply="bad")  # type: ignore[arg-type]


@pytest.mark.parametrize("body", ["\U0001f6b2" * 1000, "\x00" * 1000, '\\"' * 1000])
def test_adversarial_text_cannot_expand_prompt_past_reservation(body: str) -> None:
    prompt = complaint_prompt(body, "assigned")
    assert len(prompt.encode("utf-8")) <= 1024
    assert json.loads(prompt)["order_status"] == "assigned"
    known_input_bytes = len(prompt.encode("utf-8")) + len(SYSTEM.encode("utf-8"))
    known_input_bytes += len(json.dumps(Advice.model_json_schema()).encode("utf-8"))
    assert known_input_bytes + 256 + MAX_OUTPUT < RESERVED_TOKENS


@pytest.mark.integration
def test_two_dispatchers_cannot_double_assign(db_url: str, run_id: UUID, world: World) -> None:
    with connect(db_url) as conn:
        seed_locations(conn, world)
        conn.execute(
            """INSERT INTO couriers(run_id,id,hub,mode,node,point)
                     SELECT %s,'only-courier',id,'bike',node,point FROM locations
                     WHERE id='chamberi'""",
            (run_id,),
        )
        for sim in range(0, 2400, 60):
            generate(conn, str(run_id), sim, 42, 43200)
    q = Queue(db_url)
    events = [q.claim("dispatcher", run_id, 2400), q.claim("dispatcher", run_id, 2400)]
    assert all(events)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda e: q.process(e, Dispatcher(world).handle), [e for e in events if e])
        )
    assert all(results)
    with connect(db_url) as conn:
        assert conn.execute(
            "SELECT count(*) AS n FROM orders WHERE run_id=%s AND courier='only-courier'", (run_id,)
        ).fetchone() == {"n": 1}


@pytest.mark.integration
def test_short_day_and_durable_budget(
    db_url: str, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Settings(llm_provider="gemini", llm_max_calls=1, llm_budget_usd=0.02)
    service = CustomerService(db_url, config)
    calls: list[str] = []

    def fake_generate(complaint: dict) -> tuple[Advice, int, float]:  # type: ignore[type-arg]
        calls.append(complaint["id"])
        return Advice(category="status", reply="Your order status is recorded."), 100, 0.0001

    monkeypatch.setattr(service, "_generate", fake_generate)
    run = create_run(world, duration=4800, wall_seconds=0, url=db_url)
    result = Simulation(world, db_url, service).run(run, export=False)
    assert result["metrics"]["delivered"] > 0
    assert result["metrics"]["active"] == 0
    assert result["queue"].get("dead", 0) == 0
    assert result["run"]["llm_calls"] == 1
    assert len(calls) == 1
    with connect(db_url) as conn:
        original = conn.execute(
            "SELECT * FROM events WHERE run_id=%s AND topic='complaint.created'", (run,)
        ).fetchone()
        assert original
        conn.execute("UPDATE events SET state='ready' WHERE id=%s", (original["id"],))
    queue = Queue(db_url)
    event = queue.claim("customer_service", run, 4800)
    assert event
    assert service.prepare(event)[1] == "llm"  # replay reads cached result, no second spend
    with connect(db_url) as conn:
        publish(
            conn,
            run_id=run,
            producer="generator",
            topic="complaint.created",
            payload=event.payload,
            key="second-budget-attempt",
            trace_id=event.trace_id,
        )
    next_event = queue.claim("customer_service", run, 4800)
    assert next_event and service.prepare(next_event)[1] == "budget_exhausted"
    assert len(calls) == 1
    assert snapshot(run, db_url)["run"]["llm_reserved_tokens"] == 3000

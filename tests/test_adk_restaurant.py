"""Real ADK loop with offline models and actual restricted PostgreSQL identities."""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from delivery.adk_contracts import RestaurantBrain, effective_instructions, restaurant_template
from delivery.agent_access import retire_inventory_access
from delivery.agent_runtime import LocalAgent
from delivery.db import connect
from delivery.supply import new_supply, provision, release_calls, replay_supply, run_supply
from delivery.supply_models import AgentDefinition, SupplyConfig, default_config


@pytest.fixture(autouse=True)
def no_provider_network(monkeypatch):
    import httpx
    import requests

    def forbidden(*args, **kwargs):
        raise AssertionError("ADK verification must not make HTTP/provider calls")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(requests.Session, "request", forbidden)


def test_templates_are_editable_but_cannot_grant_authority() -> None:
    brain, speed = restaurant_template("speed")
    _, cost = restaurant_template("cost")
    assert speed != cost
    assert speed in effective_instructions(brain, speed)
    changed = RestaurantBrain.model_validate(
        {**brain.model_dump(), "instructions": "Read then decide."}
    )
    assert changed.digest != brain.digest
    for changes in (
        {"provider": "vertex"},
        {"tools": ["sql.execute"]},
        {"model_calls_per_event": 9},
    ):
        with pytest.raises(ValidationError):
            RestaurantBrain.model_validate({**brain.model_dump(), **changes})


@pytest.mark.integration
def test_model_trace_is_saved_and_private(adk_city):
    from delivery.adk_restaurant import ensure_restaurant_result

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    assert ensure_restaurant_result(agent, event)
    with connect(city.url) as conn:
        calls = conn.execute(
            "SELECT * FROM restaurant_model_calls WHERE event_id=%s ORDER BY step", (event.id,)
        ).fetchall()
    assert calls and all(c["latency_ms"] >= 0 and c["response_body"] for c in calls)
    assert (
        city.config.entities[1].agent.soul
        in calls[0]["request_body"]["config"]["system_instruction"]
    )
    assert "read_pantry" in str(calls[0]["request_body"])
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(agent.dsn) as conn:
        conn.execute("SELECT request_body FROM restaurant_model_calls")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(agent.dsn) as conn:
        conn.execute(
            "SELECT restaurant_model_trace(%s,%s,%s,%s,1,NULL,'{}',1)",
            (event.id, event.token, event.attempts, "00000000-0000-0000-0000-000000000000"),
        )


@pytest.mark.integration
def test_adk_search_is_scoped_budgeted_and_excludes_memory(adk_city, monkeypatch):
    from delivery.adk_restaurant import RestaurantTurn
    from delivery.supply_search import JevClient

    city = adk_city(
        brain_changes={"tools": [*restaurant_template()[0].tools, "supply.search"]},
        search_settings={"provider": "jev", "calls_limit": 1, "input_tokens_limit": 12000},
    )
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        nonce = conn.execute(
            "SELECT restaurant_turn_begin(%s,%s,%s) d", (event.id, event.token, event.attempts)
        ).fetchone()["d"]["nonce"]
    monkeypatch.setenv("DELIVERY_JEV_ENABLED", "1")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-1.14.0")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-not-a-key")
    sent = []

    def reviewer(self, payload, **kwargs):
        sent.append(payload)
        assert "order" not in str(payload) and "memory" not in str(payload)
        return {
            "model": self.model,
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "answers": {key: {"choice": "yes", "confidence": 0.9} for key in payload["questions"]},
        }

    monkeypatch.setattr(JevClient, "__call__", reviewer)
    turn = RestaurantTurn(agent, event, nonce)
    result = turn.search_ingredients("mozzarella")
    assert result["calls"] == 1 and sent
    assert all(row["available"] == 0 for row in result["results"])
    assert "budget_denied" == turn.search_ingredients("tomato")["error"]
    assert len(sent) == 1
    with pytest.raises(PermissionError, match="canonical"):
        turn.search_ingredients("PRIVATE_CUSTOMER_MESSAGE")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(agent.dsn) as conn:
        conn.execute("SELECT * FROM supply_stock")


@pytest.mark.integration
def test_search_grant_does_not_enable_undeclared_capability(adk_city):
    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(agent.dsn) as conn:
        conn.execute(
            "SELECT supply_search_begin(%s,%s,%s)", (event.id, event.token, event.attempts)
        )


def test_paid_model_adapter_is_rejected_before_execution() -> None:
    from types import SimpleNamespace

    from google.adk.models.google_llm import Gemini

    from delivery.adk_restaurant import RestaurantTurn

    brain, soul = restaurant_template()
    agent = SimpleNamespace(
        role=SimpleNamespace(name="restaurant", policy="adk", brain=brain, soul=soul)
    )
    turn = RestaurantTurn(agent, None, "unused")
    with pytest.raises(PermissionError, match="offline"):
        turn.build(Gemini(model="gemini-2.5-flash-lite"))


@dataclass
class City:
    run: str
    url: str
    config: SupplyConfig


def adk_config(
    soul: str = "speed",
    pantry: int = 0,
    brain_changes: dict[str, Any] | None = None,
    tool_slots: int = 16,
    search_settings: dict[str, Any] | None = None,
) -> SupplyConfig:
    base = default_config()
    brain, instructions = restaurant_template(soul)
    brain = RestaurantBrain.model_validate({**brain.model_dump(), **(brain_changes or {})})
    definition = base.agents["restaurant"].model_dump()
    definition.update(brain=brain, soul=instructions)
    if search_settings:
        definition["search"] = search_settings
    definition["limits"]["tool_calls_per_event"] = tool_slots
    agent = AgentDefinition.model_validate(definition)
    home = next(e for e in base.entities if e.kind == "household")
    restaurant = next(e for e in base.entities if e.id == "restaurant-pizza")
    markets = [e for e in base.entities if e.kind == "market"]
    entities = [
        home.model_copy(update={"node": 0, "recipe_ids": ("pizza",)}),
        restaurant.model_copy(update={"node": 1, "agent": agent}),
    ]
    entities += [
        market.model_copy(update={"node": node, "procurement_fee_cents": fee})
        for market, node, fee in zip(markets, [2, 8, 16], [300, 50, 100], strict=True)
    ]
    data = base.model_dump(mode="json")
    data.update(
        entities=[e.model_dump(mode="json") for e in entities],
        start_hour=12,
        duration_minutes=15,
        playback_seconds=0,
        calls_per_household=1,
        restaurant_stock_servings=pantry,
        market_stock_servings=3,
    )
    return SupplyConfig.model_validate(data)


@pytest.fixture
def adk_city(db_url: str) -> Iterator[Callable[..., City]]:
    runs: list[str] = []

    def create(**options: Any) -> City:
        config = adk_config(**options)
        run = new_supply(config, db_url)
        runs.append(run)
        return City(run, db_url, config)

    yield create
    for run in runs:
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            conn.execute("DELETE FROM supply_requests WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM supply_sessions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def first_call(city: City) -> tuple[LocalAgent, Any]:
    agents = provision(city.run, city.url)
    with connect(city.url) as conn:
        schedule = conn.execute(
            "SELECT config->'schedule' s FROM supply_sessions WHERE run_id=%s", (city.run,)
        ).fetchone()["s"]
        conn.execute("UPDATE runs SET sim_time=900 WHERE id=%s", (city.run,))
    release_calls(city.run, schedule, 900, city.url)
    home = next(e.id for e in city.config.entities if e.kind == "household")
    incoming = agents[home].claim()
    assert incoming and agents[home].process(incoming)
    with connect(city.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (city.run,))
    agent = agents["restaurant-pizza"]
    event = agent.claim()
    assert event
    return agent, event


@pytest.mark.integration
def test_intake_saves_and_applies_a_scoped_plan(adk_city) -> None:
    from delivery.adk_restaurant import ensure_restaurant_result

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    assert ensure_restaurant_result(agent, event)
    with connect(agent.dsn) as conn:
        agent.handle(conn, event)
        assert conn.execute(
            "SELECT agent_queue_ack(%s,%s,%s) ok", (event.id, event.token, event.attempts)
        ).fetchone()["ok"]


@pytest.mark.integration
@pytest.mark.parametrize("soul,expected", [("speed", "market-a"), ("cost", "market-b")])
def test_both_souls_use_real_adk_and_queue_delivery(adk_city, soul, expected) -> None:
    city = adk_city(soul=soul)
    state = run_supply(city.run, city.url)
    assert state["orders"][0]["status"] == "delivered"
    with connect(city.url) as conn:
        turn = conn.execute(
            "SELECT * FROM restaurant_turns WHERE run_id=%s ORDER BY event_id LIMIT 1", (city.run,)
        ).fetchone()
        assert turn["state"] == "applied"
        assert turn["result"]["supplier"] == expected
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_model_calls m "
                "JOIN restaurant_turns t USING(event_id) WHERE t.run_id=%s",
                (city.run,),
            ).fetchone()["n"]
            > 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM events WHERE run_id=%s AND state='dead'", (city.run,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM events WHERE run_id=%s "
                "AND topic='market.request' AND target_store=%s",
                (city.run, expected),
            ).fetchone()["n"]
            >= 3
        )
    replay = replay_supply(city.run, city.url)
    assert replay["matches"]


@pytest.mark.integration
def test_adk_identity_has_no_legacy_broad_tools_or_raw_tables(adk_city) -> None:
    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    queries = [
        ("SELECT * FROM supply_stock", ()),
        ("SELECT * FROM restaurant_turns", ()),
        ("SELECT * FROM agent_memory_facts", ()),
        ("SELECT supply_context(%s)", (event.payload["order"],)),
        ("SELECT supply_command(%s,%s,%s)", (event.id, event.token, event.attempts)),
        ("SELECT supply_transition(%s,%s,%s,NULL)", (event.id, event.token, event.attempts)),
    ]
    for query, args in queries:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(agent.dsn) as conn:
            conn.execute(query, args)
    with connect(agent.dsn) as conn:
        nonce = conn.execute(
            "SELECT restaurant_turn_begin(%s,%s,%s) d", (event.id, event.token, event.attempts)
        ).fetchone()["d"]["nonce"]
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(agent.dsn) as conn:
        conn.execute(
            "SELECT restaurant_tool(%s,%s,%s,%s,'restaurant.pantry',%s)",
            (event.id, event.token, event.attempts, nonce, Jsonb({"owner": "market-b"})),
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "brain_changes,slots",
    [
        ({"model_calls_per_event": 1}, 16),
        ({"reserved_tokens_per_run": 1}, 16),
        ({}, 1),
    ],
)
def test_budget_exhaustion_never_changes_stock_or_publishes_supply(adk_city, brain_changes, slots):
    city = adk_city(brain_changes=brain_changes, tool_slots=slots)
    agent, event = first_call(city)
    assert not agent.process(event)
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_requests WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT sum(reserved) n FROM supply_stock WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 0
        )
        turn = conn.execute(
            "SELECT state FROM restaurant_turns WHERE event_id=%s", (event.id,)
        ).fetchone()
        assert turn["state"] == "failed"


def reclaim(city: City, agent: LocalAgent, event: Any) -> Any:
    with connect(city.url) as conn:
        conn.execute(
            "UPDATE events SET lease_until=clock_timestamp()-interval '1 second',"
            "available_at='1970-01-01' WHERE id=%s",
            (event.id,),
        )
    next_event = agent.claim()
    assert next_event and next_event.id == event.id and next_event.attempts == event.attempts + 1
    return next_event


@pytest.mark.integration
def test_saved_plan_survives_crash_and_is_applied_without_more_model_calls(adk_city):
    from delivery.adk_restaurant import ensure_restaurant_result

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)

    def crash(stage):
        if stage == "after_adk_save":
            raise SystemExit("simulated worker death")

    with pytest.raises(SystemExit):
        ensure_restaurant_result(agent, event, fault=crash)
    with connect(city.url) as conn:
        before = conn.execute(
            "SELECT count(*) n FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
        ).fetchone()["n"]
    event = reclaim(city, agent, event)
    assert agent.process(event)
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == before
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_requests WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 4
        )
        assert (
            conn.execute(
                "SELECT state FROM restaurant_turns WHERE event_id=%s", (event.id,)
            ).fetchone()["state"]
            == "applied"
        )


@pytest.mark.integration
def test_interrupted_turn_fails_closed_without_redispatch(adk_city):
    from delivery.adk_restaurant import ensure_restaurant_result

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)

    def crash(stage):
        if stage == "before_adk_save":
            raise SystemExit("simulated worker death")

    with pytest.raises(SystemExit):
        ensure_restaurant_result(agent, event, fault=crash)
    with connect(city.url) as conn:
        before = conn.execute(
            "SELECT count(*) n FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
        ).fetchone()["n"]
    event = reclaim(city, agent, event)
    assert not agent.process(event)
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == before
        )
        assert (
            conn.execute(
                "SELECT state FROM restaurant_turns WHERE event_id=%s", (event.id,)
            ).fetchone()["state"]
            == "unknown"
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_requests WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.integration
def test_changed_stock_invalidates_saved_plan(adk_city):
    from delivery.adk_restaurant import ensure_restaurant_result

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    assert ensure_restaurant_result(agent, event)
    with connect(city.url) as conn:
        conn.execute(
            "UPDATE supply_stock SET on_hand=on_hand+1,version=version+1 "
            "WHERE run_id=%s AND owner='restaurant-pizza' AND ingredient='flour'",
            (city.run,),
        )
    assert not agent.process(event)
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_requests WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.integration
def test_other_roles_and_runs_cannot_open_a_restaurant_turn(adk_city):
    city, other = adk_city(), adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    foreign = provision(other.run, other.url)["restaurant-pizza"]
    market = provision(city.run, city.url)["market-a"]
    for identity in (foreign, market):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(identity.dsn) as conn:
            conn.execute(
                "SELECT restaurant_turn_begin(%s,%s,%s)", (event.id, event.token, event.attempts)
            )


@pytest.mark.integration
def test_unknown_supplier_is_rejected_before_any_business_effect(adk_city):
    from delivery.adk_offline import OfflineRestaurantModel
    from delivery.adk_restaurant import ensure_restaurant_result

    class InvalidSupplier(OfflineRestaurantModel):
        async def generate_content_async(self, llm_request, stream=False):
            async for response in super().generate_content_async(llm_request, stream):
                for part in response.content.parts or []:
                    if (
                        part.function_call
                        and part.function_call.name == "request_missing_ingredients"
                    ):
                        part.function_call.args = {"supplier": "https://unapproved.example"}
                yield response

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    assert ensure_restaurant_result(agent, event, model=InvalidSupplier())
    assert not agent.process(event)
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_requests WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.integration
@pytest.mark.parametrize("profile", ["speed", "cost"])
def test_effective_prompt_reaches_adk_without_history_from_other_orders(adk_city, profile):
    from pydantic import Field

    from delivery.adk_offline import OfflineRestaurantModel
    from delivery.adk_restaurant import ensure_restaurant_result

    class CaptureModel(OfflineRestaurantModel):
        instructions: list[str] = Field(default_factory=list)
        user_messages: list[str] = Field(default_factory=list)

        async def generate_content_async(self, llm_request, stream=False):
            self.instructions.append(str(llm_request.config.system_instruction))
            self.user_messages.extend(
                part.text
                for content in llm_request.contents
                if content.role == "user"
                for part in content.parts or []
                if part.text
            )
            async for response in super().generate_content_async(llm_request, stream):
                yield response

    city = adk_city(soul=profile)
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    model = CaptureModel()
    assert ensure_restaurant_result(agent, event, model=model)
    assert all(agent.role.soul in text for text in model.instructions)
    assert all(agent.role.brain.instructions in text for text in model.instructions)
    assert all(str(event.id) in text for text in model.user_messages)


@pytest.mark.integration
def test_model_io_has_no_open_agent_database_connection(adk_city):
    from delivery.adk_restaurant import ensure_restaurant_result

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    observations = []

    def check(stage):
        if stage in {"before_adk_model", "after_adk_model"}:
            with connect(city.url) as conn:
                count = conn.execute(
                    "SELECT count(*) n FROM pg_stat_activity WHERE usename="
                    "(SELECT login_role::text FROM agent_bindings WHERE run_id=%s AND store=%s)",
                    (city.run, agent.scope.store),
                ).fetchone()["n"]
            observations.append(count)

    assert ensure_restaurant_result(agent, event, fault=check)
    assert len(observations) == 8 and observations == [0] * 8


def kill_worker_at_saved_plan(agent, event):
    import os

    from delivery.adk_restaurant import ensure_restaurant_result

    def crash(stage):
        if stage == "after_adk_save":
            os._exit(71)

    ensure_restaurant_result(agent, event, fault=crash)


@pytest.mark.integration
def test_real_process_death_reuses_saved_adk_plan(adk_city):
    import multiprocessing

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    process = multiprocessing.get_context("spawn").Process(
        target=kill_worker_at_saved_plan, args=(agent, event)
    )
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        pytest.fail("ADK worker failed to reach the crash boundary")
    assert process.exitcode == 71
    event = reclaim(city, agent, event)
    assert agent.process(event)
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == 4
        )


VERTEX_PROFILE = {
    "project": "bakiano-test-only",
    "location": "europe-west1",
    "model": "gemini-2.5-flash-lite",
    "input_usd_per_million": 1.0,
    "output_usd_per_million": 2.0,
}


def vertex_brain() -> RestaurantBrain:
    brain, _ = restaurant_template()
    return RestaurantBrain.model_validate(
        {**brain.model_dump(), "provider": "vertex", "vertex": VERTEX_PROFILE, "usd_limit": 0.1}
    )


def test_vertex_requires_explicit_matching_deployment_approval(monkeypatch):
    from delivery.adk_models import create_restaurant_model

    monkeypatch.delenv("DELIVERY_ADK_VERTEX_ENABLED", raising=False)
    with pytest.raises(PermissionError, match="disabled"):
        create_restaurant_model(vertex_brain())
    monkeypatch.setenv("DELIVERY_ADK_VERTEX_ENABLED", "1")
    monkeypatch.setenv(
        "DELIVERY_ADK_VERTEX_PROFILE",
        json.dumps(
            {
                **VERTEX_PROFILE,
                "project": "some-other-project",
            }
        ),
    )
    with pytest.raises(PermissionError, match="differs"):
        create_restaurant_model(vertex_brain())


def test_native_vertex_adapter_is_keyless_profile_bound_and_has_no_retries(monkeypatch):
    from delivery.adk_models import create_restaurant_model, validate_model

    monkeypatch.setenv("DELIVERY_ADK_VERTEX_ENABLED", "1")
    monkeypatch.setenv("DELIVERY_ADK_VERTEX_PROFILE", json.dumps(VERTEX_PROFILE))
    model = create_restaurant_model(vertex_brain())
    assert model.client_kwargs == {
        "vertexai": True,
        "project": "bakiano-test-only",
        "location": "europe-west1",
    }
    assert model.api_version == "v1" and model.client is None
    assert model.retry_options.attempts == 1
    validate_model(vertex_brain(), model)


@pytest.mark.integration
def test_vertex_monetary_admission_denies_before_any_provider_dispatch(adk_city):
    city = adk_city(
        brain_changes={"provider": "vertex", "vertex": VERTEX_PROFILE, "usd_limit": 0.0001}
    )
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        nonce = conn.execute(
            "SELECT restaurant_turn_begin(%s,%s,%s) d", (event.id, event.token, event.attempts)
        ).fetchone()["d"]["nonce"]
    with pytest.raises(psycopg.errors.ProgramLimitExceeded), connect(agent.dsn) as conn:
        conn.execute(
            "SELECT restaurant_model_admit(%s,%s,%s,%s,4000,%s)",
            (event.id, event.token, event.attempts, nonce, "a" * 64),
        )
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.integration
def test_vertex_price_reservation_is_durable_and_unpriced_bypass_is_denied(adk_city):
    from decimal import Decimal

    city = adk_city(
        brain_changes={"provider": "vertex", "vertex": VERTEX_PROFILE, "usd_limit": 0.1}
    )
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        nonce = conn.execute(
            "SELECT restaurant_turn_begin(%s,%s,%s) d", (event.id, event.token, event.attempts)
        ).fetchone()["d"]["nonce"]
        conn.execute(
            "SELECT restaurant_model_admit(%s,%s,%s,%s,4000,%s)",
            (event.id, event.token, event.attempts, nonce, "a" * 64),
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(agent.dsn) as conn:
        conn.execute(
            "SELECT restaurant_model_admit_unpriced(%s,%s,%s,%s,1,%s)",
            (event.id, event.token, event.attempts, nonce, "a" * 64),
        )
    with connect(city.url) as conn:
        receipt = conn.execute(
            "SELECT * FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
        ).fetchone()
        assert receipt["provider"] == "vertex" and receipt["reserved_usd"] == Decimal("0.005024")


@pytest.mark.integration
def test_forged_event_body_does_not_reach_the_model_or_change_the_order(adk_city):
    from dataclasses import replace

    from delivery.adk_offline import OfflineRestaurantModel
    from delivery.adk_restaurant import ensure_restaurant_result

    class CaptureModel(OfflineRestaurantModel):
        async def generate_content_async(self, llm_request, stream=False):
            assert "FOREIGN_ORDER_DO_NOT_SEND" not in str(llm_request.contents)
            async for response in super().generate_content_async(llm_request, stream):
                yield response

    city = adk_city()
    agent, event = first_call(city)
    forged = replace(event, topic="restaurant.cook", payload={"order": "FOREIGN_ORDER_DO_NOT_SEND"})
    assert agent.reserve_budget(forged)
    assert ensure_restaurant_result(agent, forged, model=CaptureModel())
    assert agent.process(forged)
    with connect(city.url) as conn:
        row = conn.execute("SELECT * FROM supply_orders WHERE run_id=%s", (city.run,)).fetchone()
        assert row["id"] == event.payload["order"] and row["status"] == "sourcing"

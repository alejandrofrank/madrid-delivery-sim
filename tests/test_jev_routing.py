"""Real restricted SQL with injected typed Jev decisions; no paid calls."""
# ruff: noqa: F811 -- imported shared pytest fixture names are test parameters.

import json

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_adk_restaurant import adk_city, first_call, no_provider_network  # noqa: F401

from delivery.adk_contracts import JevRouting
from delivery.adk_restaurant import RestaurantTurn, ensure_restaurant_result
from delivery.db import connect
from delivery.jev_routing import checked_answer, confidence, decision_request
from delivery.supply import run_supply
from delivery.supply_search import JevClient


def answered(request, executor="direct", action="source", supplier="market-a", sure=1.0):
    values = {"executor": executor, "action": action, "supplier": supplier}
    answers = {}
    for name, question in request["questions"].items():
        options = list(question["criteria"])
        choice = values[name]
        other = (1 - sure) / (len(options) - 1) if len(options) > 1 else 0
        answers[name] = {
            "type": "choice",
            "choice": choice,
            "confidence": sure,
            "probabilities": {k: sure if k == choice else other for k in options},
        }
    return {
        "model": request["model"],
        "answers": answers,
        "usage": {"input_tokens": 300, "output_tokens": 50},
    }


def routed_city(factory, **routing):
    return factory(brain_changes={"routing": JevRouting(**routing).model_dump()})


@pytest.mark.integration
def test_confident_jev_uses_soul_and_no_gemini(adk_city):
    city = routed_city(adk_city)
    agent, event = first_call(city)
    assert agent.reserve_budget(event)

    def review(request):
        state = request["state"]
        assert "Elena" in state["soul"]
        assert "household" not in state["observations"]
        return answered(request)

    assert ensure_restaurant_result(agent, event, router_reviewer=review)
    with connect(agent.dsn) as conn:
        agent.handle(conn, event)
    with connect(city.url) as conn:
        route = conn.execute(
            "SELECT * FROM restaurant_routes WHERE event_id=%s", (event.id,)
        ).fetchone()
        assert route["executor"] == "jev" and route["decision"]["supplier"] == "market-a"
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_requests WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 4
        )


@pytest.mark.integration
@pytest.mark.parametrize(
    "reason", ["low_confidence", "gemini_requested", "invalid", "provider_timeout"]
)
def test_uncertainty_uses_admitted_model_once(adk_city, reason):
    city = routed_city(adk_city)
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    sent = []

    def review(request):
        sent.append(request)
        if reason == "provider_timeout":
            raise TimeoutError()
        result = answered(
            request,
            executor="gemini" if reason == "gemini_requested" else "direct",
            sure=0.6 if reason == "low_confidence" else 1,
        )
        if reason == "invalid":
            result["answers"]["supplier"]["choice"] = "FOREIGN_SHOP"
        return result

    assert ensure_restaurant_result(agent, event, router_reviewer=review)
    assert ensure_restaurant_result(agent, event, router_reviewer=review)
    assert len(sent) == 1
    with connect(city.url) as conn:
        route = conn.execute(
            "SELECT * FROM restaurant_routes WHERE event_id=%s", (event.id,)
        ).fetchone()
        assert route["executor"] == "gemini"
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_model_calls WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            > 0
        )
        if reason == "provider_timeout":
            assert route["input_tokens"] is None and route["reserved_usd"] > 0


@pytest.mark.integration
def test_gemini_cannot_bypass_first_layer_or_router_budget(adk_city):
    city = routed_city(adk_city, input_tokens_per_run=1024)
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        nonce = conn.execute(
            "SELECT restaurant_turn_begin(%s,%s,%s) d", (event.id, event.token, event.attempts)
        ).fetchone()["d"]["nonce"]
    turn = RestaurantTurn(agent, event, nonce)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        turn.sql("restaurant_model_admit", 4000, "a" * 64)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        turn.sql("restaurant_model_admit_preroute", 4000, "a" * 64)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        turn.sql("restaurant_route_begin", Jsonb({}), True)
    with pytest.raises(psycopg.errors.ProgramLimitExceeded):
        turn.sql("restaurant_route_begin", Jsonb(decision_request(turn, turn.read_order())), False)
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_routes WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.integration
def test_unfinished_router_never_reissues_a_provider_request(adk_city):
    city = routed_city(adk_city)
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    sent = []

    class Crash(BaseException):
        pass

    def fault(stage):
        if stage == "after_jev_router":
            raise Crash()

    def review(request):
        sent.append(request)
        return answered(request)

    with pytest.raises(Crash):
        ensure_restaurant_result(agent, event, router_reviewer=review, fault=fault)
    assert ensure_restaurant_result(agent, event, router_reviewer=review) is False
    assert len(sent) == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(agent.dsn) as conn:
        conn.execute("SELECT * FROM restaurant_routes")


def test_probability_distribution_and_margin_must_be_valid():
    request = {
        "model": "jev-1.14.0",
        "questions": {
            k: {"criteria": v}
            for k, v in {
                "executor": {"direct": "", "gemini": ""},
                "action": {"source": "", "decline": ""},
                "supplier": {"market-a": "", "uncertain": ""},
            }.items()
        },
    }
    raw = answered(request, sure=0.9)
    assert checked_answer(raw, request) == raw
    assert confidence(raw, ["executor", "supplier"]) == pytest.approx((0.9, 0.8))
    for bad in (float("nan"), -1, 2):
        changed = json.loads(json.dumps(raw))
        changed["answers"]["executor"]["confidence"] = bad
        with pytest.raises(ValueError):
            checked_answer(changed, request)


@pytest.mark.integration
def test_invented_finish_tool_keeps_staged_supply_unapplied(adk_city):
    """Replay the live malformed-tool failure without network or paid calls."""
    from delivery.adk_offline import OfflineRestaurantModel

    class InventedFinishModel(OfflineRestaurantModel):
        async def generate_content_async(self, llm_request, stream=False):
            async for response in super().generate_content_async(llm_request, stream):
                for part in response.content.parts or []:
                    if part.function_call and part.function_call.name == "finish_decision":
                        part.function_call.name = "finish_finish_decision"
                yield response

    city = adk_city(
        brain_changes={"routing": JevRouting().model_dump(), "model_calls_per_event": 8}
    )
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with pytest.raises(psycopg.errors.ProgramLimitExceeded):
        ensure_restaurant_result(
            agent,
            event,
            model=InventedFinishModel(),
            router_reviewer=lambda request: answered(request, executor="gemini"),
        )
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
        assert (
            conn.execute(
                "SELECT state FROM restaurant_turns WHERE event_id=%s", (event.id,)
            ).fetchone()["state"]
            == "failed"
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_tool_receipts "
                "WHERE event_id=%s AND tool='restaurant.contract_rejected'",
                (event.id,),
            ).fetchone()["n"]
            == 2
        )


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["unknown_tool", "summary_length"])
def test_completed_bad_proposal_can_be_corrected_without_restaging(adk_city, failure):
    from delivery.adk_offline import OfflineRestaurantModel

    class CorrectingModel(OfflineRestaurantModel):
        broken: bool = False

        async def generate_content_async(self, llm_request, stream=False):
            last = llm_request.contents[-1]
            if any(
                part.function_response
                and part.function_response.response.get("error") == "tool_contract"
                for part in last.parts or []
            ):
                yield self.response(
                    calls=[
                        (
                            "finish_decision",
                            {"summary": "Selected the scoped supplier following the SOUL."},
                        )
                    ]
                )
                return
            async for response in super().generate_content_async(llm_request, stream):
                for part in response.content.parts or []:
                    if (
                        not self.broken
                        and part.function_call
                        and part.function_call.name == "finish_decision"
                    ):
                        self.broken = True
                        if failure == "unknown_tool":
                            part.function_call.name = "finish_finish_decision"
                        else:
                            part.function_call.args["summary"] = "x" * 574
                yield response

    city = adk_city(brain_changes={"model_calls_per_event": 8})
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    assert ensure_restaurant_result(agent, event, model=CorrectingModel())
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_requests WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 0
        )
        receipts = conn.execute(
            "SELECT tool,result FROM restaurant_tool_receipts WHERE event_id=%s ORDER BY step",
            (event.id,),
        ).fetchall()
        assert sum(r["tool"] == "restaurant.request_supply" for r in receipts) == 1
        rejected = [r["result"] for r in receipts if r["tool"] == "restaurant.contract_rejected"]
        assert len(rejected) == 1 and rejected[0]["code"] == failure
        assert rejected[0]["executed"] is False
        assert sum(r["tool"] == "restaurant.finish" for r in receipts) == 1
        calls = conn.execute(
            "SELECT request_body FROM restaurant_model_calls WHERE event_id=%s ORDER BY step",
            (event.id,),
        ).fetchall()
        assert len(calls) == 4
        mode = calls[0]["request_body"]["config"]["tool_config"]["function_calling_config"]
        assert mode["mode"] == "VALIDATED"
        assert "finish_decision" in mode["allowed_function_names"]
        assert "finish_finish_decision" not in mode["allowed_function_names"]
        assert "500 characters" in calls[0]["request_body"]["config"]["system_instruction"]
    with connect(agent.dsn) as conn:
        agent.handle(conn, event)
    with connect(city.url) as conn:
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
@pytest.mark.parametrize("soul,supplier", [("speed", "market-a"), ("cost", "market-b")])
def test_full_queue_delivery_uses_one_jev_call_and_five_rule_events(
    adk_city, monkeypatch, soul, supplier
):
    city = adk_city(soul=soul, brain_changes={"routing": JevRouting().model_dump()})
    monkeypatch.setenv("DELIVERY_JEV_ENABLED", "1")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-1.14.0")
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-not-a-key")
    sent = []

    def review(self, request):
        sent.append(request)
        return answered(request, supplier=supplier)

    monkeypatch.setattr(JevClient, "request", review)
    state = run_supply(city.run, city.url)
    assert state["metrics"]["delivered"] == 1 and len(sent) == 1
    assert state["metrics"]["decision_mode"] == "jev_first"
    assert state["metrics"]["jev_router_dispatches"] == 1
    assert state["metrics"]["jev_direct_decisions"] == 1
    assert state["metrics"]["jev_no_model_steps"] == 5
    assert state["metrics"]["adk_offline_calls"] == 0
    with connect(city.url) as conn:
        routes = conn.execute(
            "SELECT r.executor,count(*) n FROM restaurant_routes r "
            "JOIN restaurant_turns t USING(event_id) WHERE t.run_id=%s GROUP BY r.executor",
            (city.run,),
        ).fetchall()
        assert {row["executor"]: row["n"] for row in routes} == {"jev": 1, "rules": 5}


@pytest.mark.integration
@pytest.mark.parametrize(
    "name,args",
    [
        ("read_order", {"order": "foreign-order"}),
        ("finish_finish_decision", {"owner": "foreign-store"}),
        ("search_ingredients", {"query": "mozzarella"}),
    ],
)
def test_contract_repair_never_swallows_scope_or_disabled_tool_denials(adk_city, name, args):
    from delivery.adk_offline import OfflineRestaurantModel

    class ScopeAttack(OfflineRestaurantModel):
        async def generate_content_async(self, llm_request, stream=False):
            yield self.response(calls=[(name, args)])

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with pytest.raises(PermissionError):
        ensure_restaurant_result(agent, event, model=ScopeAttack())
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_tool_receipts WHERE event_id=%s", (event.id,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_requests WHERE run_id=%s", (city.run,)
            ).fetchone()["n"]
            == 0
        )


@pytest.mark.integration
def test_contract_rejection_requires_own_completed_live_model_turn(adk_city):
    from delivery.supply import provision

    city = adk_city()
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        nonce = conn.execute(
            "SELECT restaurant_turn_begin(%s,%s,%s) d", (event.id, event.token, event.attempts)
        ).fetchone()["d"]["nonce"]
    turn = RestaurantTurn(agent, event, nonce)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        turn.sql("restaurant_contract_reject", "finish_decision", "summary_length")
    other = adk_city()
    foreign = provision(other.run, other.url)["restaurant-pizza"]
    market = provision(city.run, city.url)["market-a"]
    for identity in (foreign, market):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connect(identity.dsn) as conn:
            conn.execute(
                "SELECT restaurant_contract_reject(%s,%s,%s,%s,'finish_decision','summary_length')",
                (event.id, event.token, event.attempts, nonce),
            )


@pytest.mark.integration
def test_stocked_pantry_router_omits_irrelevant_supplier_tool_and_question(adk_city):
    city = adk_city(pantry=2, brain_changes={"routing": JevRouting().model_dump()})
    agent, event = first_call(city)
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        nonce = conn.execute(
            "SELECT restaurant_turn_begin(%s,%s,%s) d", (event.id, event.token, event.attempts)
        ).fetchone()["d"]["nonce"]
    turn = RestaurantTurn(agent, event, nonce)
    request = decision_request(turn, turn.read_order())
    assert set(request["questions"]) == {"executor", "action"}
    assert request["state"]["observations"]["pantry_covers_recipe"] is True
    assert request["state"]["observations"]["suppliers"] == []
    with connect(city.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM restaurant_tool_receipts "
                "WHERE event_id=%s AND tool='restaurant.suppliers'",
                (event.id,),
            ).fetchone()["n"]
            == 0
        )

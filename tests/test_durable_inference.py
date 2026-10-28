from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest

from delivery.cloud_ai import Judgment
from delivery.durable_inference import ensure_result


@pytest.mark.parametrize("provider_error", [None, RuntimeError("secret credential")])
def test_provider_runs_with_no_open_worker_connection(monkeypatch, provider_error):
    active = 0
    record = {
        "id": "request-id",
        "state": "prepared",
        "endpoint": "https://judge.run.app",
        "sanitized_request": {
            "facts": {"attempt": 1, "sim_time": 5},
            "candidate": None,
            "memory_entries": 2,
        },
        "dispatch_token": "dispatch-id",
    }
    conn = Mock()
    conn.execute.side_effect = [
        SimpleNamespace(fetchone=lambda: {"dispatch": {"dispatch": True, "request": record}}),
        SimpleNamespace(fetchone=lambda: {"saved": True}),
    ]

    @contextmanager
    def connection(_):
        nonlocal active
        active += 1
        try:
            yield conn
        finally:
            active -= 1

    def review(self, context, memory, *, candidate):
        assert active == 0
        assert context == {"job": {"attempt": 1, "sim_time": 5}}
        assert memory == [None, None] and candidate is None
        if provider_error:
            raise provider_error
        return Judgment(
            decision="deny_retry",
            reason="Bounded veto",
            model="fake",
            input_tokens=2,
            output_tokens=3,
        )

    stages = []

    def fault(stage):
        assert active == 0
        stages.append(stage)

    monkeypatch.setattr("delivery.durable_inference.prepare", lambda *a: record)
    monkeypatch.setattr("delivery.durable_inference.connect", connection)
    monkeypatch.setattr("delivery.cloud_ai.CloudJudge.review", review)
    event = SimpleNamespace(id=7, token="lease", attempts=1)
    assert ensure_result(SimpleNamespace(dsn="scoped"), event, fault=fault)
    assert stages == [
        "after_prepare",
        "after_dispatch",
        "before_invoke",
        "after_response",
        "before_result_save",
        "after_result_save",
    ]
    saved = conn.execute.call_args.args[1]
    assert saved[-1] == ("RuntimeError" if provider_error else None)
    assert "secret" not in str(saved)


@pytest.mark.parametrize(
    "state,ready", [("in_flight", False), ("succeeded", True), ("unknown", True)]
)
def test_existing_receipt_does_not_invoke_or_reserve(monkeypatch, state, ready):
    monkeypatch.setattr("delivery.durable_inference.prepare", lambda *a: {"state": state})
    connection = Mock(side_effect=AssertionError("no new reservation/dispatch"))
    provider = Mock(side_effect=AssertionError("no replay network call"))
    monkeypatch.setattr("delivery.durable_inference.connect", connection)
    monkeypatch.setattr("delivery.cloud_ai.CloudJudge.review", provider)
    assert ensure_result(SimpleNamespace(), SimpleNamespace()) is ready
    connection.assert_not_called()
    provider.assert_not_called()


@pytest.mark.integration
def test_dispatch_budget_scope_and_privacy_are_durable(db_url, monkeypatch):
    from delivery.agent_access import retire_inventory_access, role_access
    from delivery.agent_runtime import create_agent
    from delivery.db import connect
    from delivery.delivery_flow import new_delivery
    from delivery.queue import publish

    calls = []

    def review(self, context, memory, *, candidate):
        calls.append((context, memory, candidate))
        return Judgment(
            decision="deny_retry",
            reason="No candidate",
            model="fake",
            input_tokens=1,
            output_tokens=1,
        )

    monkeypatch.setattr("delivery.cloud_ai.CloudJudge.review", review)
    run = new_delivery(url=db_url)
    try:
        access = role_access(run, "judge", db_url, agent_mode="gcp_ai")["fleet"]
        agent = create_agent(
            access.dsn, agent_mode="gcp_ai", cloud_endpoint="https://judge.run.app"
        )
        with connect(access.dsn) as conn:
            for table in (
                "agent_inference_requests",
                "agent_inference_history",
                "agent_model_calls",
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(f"SELECT * FROM {table}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute("SELECT public.agent_reserve_model(1,gen_random_uuid(),1)")
        for index in range(7):
            basket = f"private-budget-{index}"
            with connect(db_url) as conn:
                conn.execute(
                    """INSERT INTO lab_delivery_jobs(run_id,basket,store,pickup_node,customer_node,
                    status,attempt,deadline_sim)
                    VALUES (%s,%s,'store-1',1,2,'awaiting_review',1,20000)""",
                    (run, basket),
                )
                publish(
                    conn,
                    run_id=run,
                    producer="lab_world",
                    topic="delivery.failed",
                    payload={"basket": basket, "attempt": 1},
                    key=basket,
                    trace_id=basket,
                    target_store="judge:fleet",
                )
            event = agent.claim()
            assert event and agent.process(event)
        assert len(calls) == 6
        assert "private" not in str(calls)
        with connect(db_url) as conn:
            budget = conn.execute(
                """SELECT count(*) AS calls,sum(reserved_tokens) AS tokens
                FROM agent_model_calls WHERE run_id=%s""",
                (run,),
            ).fetchone()
            assert budget == {"calls": 6, "tokens": 50688}
            final = conn.execute(
                "SELECT state,result,error_code FROM agent_inference_requests WHERE event_id=%s",
                (event.id,),
            ).fetchone()
            assert final["state"] == "applied" and final["error_code"] == "ModelBudgetExceeded"
            tools = conn.execute(
                "SELECT observed_tools FROM agent_event_budgets WHERE event_id=%s",
                (event.id,),
            ).fetchone()
            assert tools["observed_tools"] == 8
    finally:
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))

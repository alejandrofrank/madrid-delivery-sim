from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from delivery.fleet_policy import cloud_judgement


@pytest.mark.parametrize("decision,approved", [("approve_retry", True), ("deny_retry", False)])
def test_cloud_can_only_veto_local_candidate(monkeypatch, decision, approved):
    audit_conn = Mock()

    @contextmanager
    def connection(_):
        yield audit_conn

    provider = Mock()
    provider.review.return_value = SimpleNamespace(
        decision=decision,
        model_dump=lambda: {
            "decision": decision,
            "model": "test",
            "input_tokens": 5,
            "output_tokens": 3,
            "reason": "bounded",
        },
    )
    monkeypatch.setattr("delivery.cloud_ai.CloudJudge", lambda _: provider)
    monkeypatch.setattr("delivery.fleet_policy.connect", connection)
    tools = SimpleNamespace(cloud_endpoint="https://judge.run.app", cloud_dsn="private", sim=10)
    context = {
        "job": {"deadline_sim": 100},
        "roads": {"edges": [{"from": 1, "to": 2, "travel_seconds": 20}]},
    }
    courier, route, audit = cloud_judgement(
        SimpleNamespace(id=1, attempts=1), tools, context, [], "bike-1", [1, 2]
    )
    assert (courier, route) == (("bike-1", [1, 2]) if approved else (None, None))
    assert provider.review.call_args.kwargs["candidate"]["estimated_seconds"] == 20
    assert audit["fallback"] is None
    audit_conn.execute.assert_called_once()


def test_cloud_failure_denies_and_audits_without_error_text(monkeypatch):
    audit_conn = Mock()

    @contextmanager
    def connection(_):
        yield audit_conn

    provider = Mock()
    provider.review.side_effect = RuntimeError("secret credential")
    monkeypatch.setattr("delivery.cloud_ai.CloudJudge", lambda _: provider)
    monkeypatch.setattr("delivery.fleet_policy.connect", connection)
    tools = SimpleNamespace(cloud_endpoint="https://judge.run.app", cloud_dsn="private", sim=10)
    courier, route, audit = cloud_judgement(
        SimpleNamespace(id=1, attempts=1), tools, {}, [], None, None
    )
    assert courier is None and route is None
    assert audit["error"] == "RuntimeError" and audit["fallback"] == "fail_closed"
    assert "secret" not in str(audit)
    audit_conn.execute.assert_called_once()


@pytest.mark.integration
def test_model_reservation_is_durable_scoped_and_never_reused(db_url):
    from delivery.agent_access import retire_inventory_access, role_access
    from delivery.agent_runtime import create_agent
    from delivery.db import connect
    from delivery.delivery_flow import new_delivery
    from delivery.queue import publish

    run = new_delivery(url=db_url)
    try:
        access = role_access(run, "judge", db_url, agent_mode="gcp_ai")["fleet"]
        agent = create_agent(
            access.dsn, agent_mode="gcp_ai", cloud_endpoint="https://judge.run.app"
        )
        with connect(db_url) as conn:
            publish(
                conn,
                run_id=run,
                producer="lab_world",
                topic="delivery.failed",
                payload={"basket": "test", "attempt": 1},
                key="test",
                trace_id="test",
                target_store="judge:fleet",
            )
        event = agent.claim()
        assert event and agent.reserve_budget(event)
        with connect(access.dsn) as conn:
            assert conn.execute(
                "SELECT agent_reserve_model(%s,%s,%s) AS ok",
                (event.id, event.token, event.attempts),
            ).fetchone()["ok"]
        # A second connection sees the charged reservation after the first committed.
        with connect(access.dsn) as conn:
            assert not conn.execute(
                "SELECT agent_reserve_model(%s,%s,%s) AS ok",
                (event.id, event.token, event.attempts),
            ).fetchone()["ok"]
        with connect(db_url) as conn:
            row = conn.execute(
                "SELECT reserved_tokens,status FROM agent_model_calls WHERE event_id=%s",
                (event.id,),
            ).fetchone()
            assert row == {"reserved_tokens": 8448, "status": "reserved"}
        for index in range(1, 7):
            with connect(db_url) as conn:
                publish(
                    conn,
                    run_id=run,
                    producer="lab_world",
                    topic="delivery.failed",
                    payload={"basket": f"budget-{index}", "attempt": 1},
                    key=f"budget-{index}",
                    trace_id=f"budget-{index}",
                    target_store="judge:fleet",
                )
            next_event = agent.claim()
            assert next_event and agent.reserve_budget(next_event)
            with connect(access.dsn) as conn:
                reserved = conn.execute(
                    "SELECT agent_reserve_model(%s,%s,%s) AS ok",
                    (next_event.id, next_event.token, next_event.attempts),
                ).fetchone()["ok"]
                assert reserved is (index < 6)
        with connect(db_url) as conn:
            count = conn.execute(
                "SELECT count(*) AS n,sum(reserved_tokens) AS tokens "
                "FROM agent_model_calls WHERE run_id=%s",
                (run,),
            ).fetchone()
            assert count == {"n": 6, "tokens": 50688}
        with pytest.raises(ValueError, match="frozen"):
            role_access(run, "judge", db_url)
    finally:
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))

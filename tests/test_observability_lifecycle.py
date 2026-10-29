"""Final clock-driven failures have no queue ACK; observe only committed outcomes."""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from delivery import simulation
from delivery.db import connect
from delivery.queue import publish
from delivery.world import World, seed_locations


@pytest.mark.parametrize("rollback", [False, True])
def test_final_unserved_orders_are_exported_only_after_commit(monkeypatch, rollback):
    actions = []
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [{"id": "order", "latency": 123.0}]

    @contextmanager
    def connect(url):
        yield conn
        if rollback:
            raise RuntimeError("transaction rolled back")
        actions.append("committed")

    @contextmanager
    def span(name, **kwargs):
        assert actions == ["committed"]
        assert name == "order.complete"
        assert kwargs["run_id"] == "run" and kwargs["order_id"] == "order"
        assert kwargs["attributes"]["delivery.order.success"] is False
        assert kwargs["attributes"]["delivery.order.latency_ms"] == 123
        actions.append("exported")
        yield

    monkeypatch.setattr(simulation, "active", lambda: True)
    monkeypatch.setattr(simulation, "connect", connect)
    monkeypatch.setattr(simulation, "order_span", span)
    if rollback:
        with pytest.raises(RuntimeError):
            simulation.finish_run("run")
        assert actions == []
    else:
        simulation.finish_run("run")
        assert actions == ["committed", "exported"]


def test_disabled_finish_has_no_telemetry_queries_or_exports(monkeypatch):
    conn = Mock()

    @contextmanager
    def connect(url):
        yield conn

    monkeypatch.setattr(simulation, "active", lambda: False)
    monkeypatch.setattr(simulation, "connect", connect)
    monkeypatch.setattr(simulation, "order_span", lambda *a, **kw: pytest.fail("disabled"))
    simulation.finish_run("run")
    conn.execute.return_value.fetchall.assert_not_called()
    assert all("RETURNING" not in call.args[0] for call in conn.execute.call_args_list)


@pytest.mark.integration
def test_unserved_terminal_uses_persisted_order_start(db_url, run_id, monkeypatch):
    with connect(db_url) as conn:
        seed_locations(conn, World())
        conn.execute(
            "INSERT INTO orders(run_id,id,store,customer,created_sim,ready_sim,due_sim) "
            "SELECT %s,'stuck',s.id,c.id,0,60,120 FROM locations s,locations c "
            "WHERE s.kind='store' AND c.kind='customer' LIMIT 1",
            (run_id,),
        )
        publish(
            conn, run_id=run_id, producer="generator", topic="order.created",
            payload={"order_id": "stuck"}, key="stuck", trace_id="stuck",
        )
    recorded = []

    @contextmanager
    def span(name, **kwargs):
        with connect(db_url) as conn:
            row = conn.execute(
                "SELECT status FROM orders WHERE run_id=%s AND id='stuck'", (run_id,)
            ).fetchone()
            assert row["status"] == "unserved"
        recorded.append(kwargs)
        yield

    monkeypatch.setattr(simulation, "active", lambda: True)
    monkeypatch.setattr(simulation, "order_span", span)
    simulation.finish_run(str(run_id), db_url)
    assert len(recorded) == 1 and recorded[0]["order_id"] == "stuck"
    assert recorded[0]["attributes"]["delivery.order.latency_ms"] >= 0
    simulation.finish_run(str(run_id), db_url)
    assert len(recorded) == 1  # Re-running finalization cannot manufacture a new outcome.

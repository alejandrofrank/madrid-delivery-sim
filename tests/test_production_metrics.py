from pathlib import Path
from unittest.mock import Mock

import pytest

from delivery.production_metrics import collect_run, export_run


def test_terminal_metrics_use_deadlines_keep_unknown_recovery_and_omit_customer_data(monkeypatch):
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {"status": "complete"}
    conn.execute.return_value.__iter__ = Mock(return_value=iter([
        {"id": "a", "status": "delivered", "delivered_sim": 121, "due_sim": 120, "cost_eur": 2},
        {"id": "b", "status": "unserved", "delivered_sim": None, "due_sim": 120, "cost_eur": 0},
    ]))
    metric = {"id": "rain", "time_to_recover_seconds": None, "orders_saved": 1, "orders_lost": 1,
              "late_deliveries": 1, "refund_cost_eur": 2, "extra_tokens": 10,
              "extra_token_cost_usd": .01, "failed_replans": 1, "private": "omit"}
    monkeypatch.setattr("delivery.production_metrics.evidence", lambda *args: {"metrics": [metric]})
    rows = collect_run(conn, "run")
    assert [r["late"] for r in rows["operational_orders"]] == [True, None]
    assert rows["disruptions"][0]["time_to_recover_seconds"] is None
    assert "private" not in str(rows)


def test_export_is_disabled_by_default_and_rejects_nonterminal_runs(monkeypatch):
    monkeypatch.delenv("MDS_PRODUCTION_METRICS", raising=False)
    client = Mock()
    export_run("run", client=client)
    client.insert_rows_json.assert_not_called()
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {"status": "running"}
    with pytest.raises(ValueError):
        collect_run(conn, "run")


def test_dashboard_views_deduplicate_retry_receipts_and_bound_partition_scans():
    for path in Path("infra/production/sql").glob("*.sql"):
        sql = path.read_text()
        assert "PARTITION BY event_id" in sql
        assert "INTERVAL 30 DAY" in sql
    sql = Path("infra/production/sql/late_delivery_rate.sql").read_text()
    assert "COUNTIF(delivered AND late IS NOT NULL)" in sql
    assert "lost_order_rate" in sql

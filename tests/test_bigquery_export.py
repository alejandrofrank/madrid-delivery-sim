import json
from pathlib import Path

import pytest

from delivery import bigquery_export as analytics

RUN = "32b65c42-12b1-45bc-b75b-3e0bdd02d1ce"
EXPORTED = "2026-10-29T12:00:00+00:00"


def receipt():
    return {
        "created_at": "2026-10-29T10:00:00Z",
        "source_fingerprint": "a" * 64,
        "paid_calls": 0,
        "profiles": [
            {
                "run": RUN,
                "profile": "speed",
                "replay_matches": True,
                "metrics": {"delivered": 1, "scheduled_calls": 1, "adk_paid_calls": None},
                "invariants": {"stock_conserved": True, "stock_nonnegative": True},
                "evidence": {"prompt": "private text must stay local", "token": "secret"},
            }
        ],
    }


def bundle(tmp_path):
    source = tmp_path / "receipt.json"
    source.write_text(json.dumps(receipt()), encoding="utf-8")
    output = tmp_path / "bundle"
    analytics.prepare_bundle(source, output)
    return output


def upload(output, **overrides):
    args = {
        "project": "mds-test-project",
        "service_account": "delivery-analytics@mds-test-project.iam.gserviceaccount.com",
        "confirm_upload": True,
    }
    return analytics.upload_bundle(output, **(args | overrides))


def test_preparation_is_local_allowlisted_and_keeps_unknowns_null(tmp_path, monkeypatch):
    monkeypatch.setattr(analytics, "BigQueryLoadClient", lambda *args: pytest.fail("cloud access"))
    output = bundle(tmp_path)
    data = (output / "run_receipts.ndjson").read_text()
    row = json.loads(data)
    assert row["run_id"] == RUN
    assert row["checks_passed"] == row["checks_total"] == 2
    assert row["usage_cost_usd"] == 0
    assert row["unknown_usage_calls"] is None
    assert row["reserved_cost_usd"] is None
    assert "private text" not in data and "secret" not in data
    kpis = [json.loads(line) for line in (output / "run_kpis.ndjson").read_text().splitlines()]
    assert {row["metric_name"] for row in kpis} == {"delivered", "scheduled_calls"}
    with pytest.raises(FileExistsError):
        analytics.prepare_bundle(tmp_path / "receipt.json", output)


def test_partial_cost_is_unknown_and_admission_is_not_measured_cost():
    value = receipt()
    del value["paid_calls"]
    value["profiles"][0]["cost"] = {
        "total_usd": "0.12",
        "admission_usd": "0.40",
        "unknown_calls": 2,
    }
    rows, _ = analytics.receipt_rows(value, "b" * 64, EXPORTED)
    assert rows[0]["usage_cost_usd"] is None
    assert rows[0]["reserved_cost_usd"] == 0.4
    value["profiles"][0]["cost"]["unknown_calls"] = 0
    rows, _ = analytics.receipt_rows(value, "b" * 64, EXPORTED)
    assert rows[0]["usage_cost_usd"] == 0.12


@pytest.mark.parametrize("enabled,confirmed", [(None, True), ("0", True), ("1", False)])
def test_upload_requires_both_opt_ins_before_credentials(tmp_path, monkeypatch, enabled, confirmed):
    if enabled is None:
        monkeypatch.delenv("DELIVERY_BIGQUERY_ENABLED", raising=False)
    else:
        monkeypatch.setenv("DELIVERY_BIGQUERY_ENABLED", enabled)
    monkeypatch.setattr(analytics, "BigQueryLoadClient", lambda *args: pytest.fail("credentials"))
    with pytest.raises(PermissionError):
        upload(tmp_path / "missing", confirm_upload=confirmed)


def test_tampered_bundle_rejected_before_credentials(tmp_path, monkeypatch):
    output = bundle(tmp_path)
    (output / "run_kpis.ndjson").write_text("{}\n")
    monkeypatch.setenv("DELIVERY_BIGQUERY_ENABLED", "1")
    monkeypatch.setattr(analytics, "BigQueryLoadClient", lambda *args: pytest.fail("credentials"))
    with pytest.raises(ValueError, match="reviewed manifest"):
        upload(output)


def test_upload_jobs_are_stable_for_retries_and_scoped_to_destination(tmp_path, monkeypatch):
    output = bundle(tmp_path)
    monkeypatch.setenv("DELIVERY_BIGQUERY_ENABLED", "1")
    loads = []

    class FakeClient:
        def __init__(self, project, service_account):
            assert project == "mds-test-project"
            assert service_account.startswith("delivery-analytics@")

        def load(self, data, table, job_id, location):
            loads.append((data, table, job_id, location))
            return len(data.splitlines())

    monkeypatch.setattr(analytics, "BigQueryLoadClient", FakeClient)
    first = upload(output)
    assert upload(output) == first
    assert len(loads) == 4 and loads[:2] == loads[2:]
    other = upload(output, dataset="another_analytics")
    assert other["jobs"]["run_receipts"]["job_id"] != first["jobs"]["run_receipts"]["job_id"]
    assert all(item[3] == "EU" for item in loads)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 1e20])
def test_invalid_kpis_fail_before_writing(value, tmp_path):
    data = receipt()
    data["profiles"][0]["metrics"]["delivered"] = value
    source = tmp_path / "source.json"
    source.write_text(json.dumps(data))
    output = tmp_path / "out"
    with pytest.raises(ValueError):
        analytics.prepare_bundle(source, output)
    assert not output.exists()


def test_duplicate_runs_and_naive_timestamps_are_rejected():
    data = receipt()
    data["profiles"] *= 2
    with pytest.raises(ValueError, match="Duplicate"):
        analytics.receipt_rows(data, "b" * 64, EXPORTED)
    data = receipt()
    data["created_at"] = "2026-10-29T12:00:00"
    with pytest.raises(ValueError, match="timezone"):
        analytics.receipt_rows(data, "b" * 64, EXPORTED)


def test_routing_comparison_arms_are_supported():
    data = receipt()
    data["arms"] = data.pop("profiles")
    data["arms"][0]["outcome_checks"] = {"delivered": True, "queue": False}
    rows, _ = analytics.receipt_rows(data, "b" * 64, EXPORTED)
    assert rows[0]["checks_passed"] == 1
    assert rows[0]["checks_total"] == 2


def test_sql_view_prunes_both_tables_and_keeps_zero_denominators_null():
    sql = Path("infra/gcp-ai/sql/run_dashboard.sql").read_text()
    assert sql.count("WHERE exported_at >= TIMESTAMP_SUB") == 2
    assert "SAFE_DIVIDE(r.checks_passed, r.checks_total)" in sql
    assert "PARTITION BY run_id ORDER BY exported_at DESC" in sql
    assert "SAFE_DIVIDE(k.delivered, COALESCE(k.scheduled_calls, k.orders)) AS delivery_rate" in sql
    for metric in (
        "orders",
        "on_time",
        "on_time_pct",
        "delivery_cost_eur",
        "cost_per_delivery_eur",
        "active",
        "unserved",
        "pending",
        "overdue",
    ):
        assert f"MAX(IF(metric_name = '{metric}', metric_value, NULL)) AS {metric}" in sql


def test_sdk_load_is_append_only_with_fixed_job_id_and_no_table_creation():
    from types import SimpleNamespace
    from unittest.mock import Mock

    from google.cloud import bigquery

    client = analytics.BigQueryLoadClient.__new__(analytics.BigQueryLoadClient)
    result = Mock(return_value=None)
    client.client = Mock()
    client.client.load_table_from_file.return_value = SimpleNamespace(output_rows=1, result=result)
    assert (
        client.load(b'{"run_id":"test"}\n', "project.dataset.run_receipts", "fixed_job", "EU") == 1
    )
    options = client.client.load_table_from_file.call_args.kwargs
    config = options["job_config"]
    assert config.create_disposition == bigquery.CreateDisposition.CREATE_NEVER
    assert config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert config.source_format == bigquery.SourceFormat.NEWLINE_DELIMITED_JSON
    assert config.autodetect is False and config.ignore_unknown_values is False
    assert options["job_id"] == "fixed_job" and options["location"] == "EU"
    result.assert_called_once_with(timeout=60)


def test_sdk_conflict_resumes_existing_load_without_resubmission():
    from unittest.mock import Mock

    from google.api_core.exceptions import Conflict
    from google.cloud import bigquery

    client = analytics.BigQueryLoadClient.__new__(analytics.BigQueryLoadClient)
    client.client = Mock()
    client.client.load_table_from_file.side_effect = Conflict("already submitted")
    job = Mock(spec=bigquery.LoadJob)
    job.destination = bigquery.TableReference.from_string("project.dataset.run_receipts")
    job.output_rows = 1
    client.client.get_job.return_value = job
    assert client.load(b"{}\n", "project.dataset.run_receipts", "stable", "EU") == 1
    client.client.get_job.assert_called_once_with("stable", location="EU", timeout=30)
    assert client.client.load_table_from_file.call_count == 1
    job.result.assert_called_once_with(timeout=60)


def test_oversized_export_is_rejected_before_credentials(tmp_path, monkeypatch):
    output = bundle(tmp_path)
    monkeypatch.setenv("DELIVERY_BIGQUERY_ENABLED", "1")
    monkeypatch.setattr(analytics, "MAX_EXPORT_BYTES", 1)
    monkeypatch.setattr(analytics, "BigQueryLoadClient", lambda *args: pytest.fail("credentials"))
    with pytest.raises(ValueError):
        upload(output)


def baseline_receipt():
    # Shape emitted by Simulation.run, including an admitted call without usage.
    return {
        "run": {
            "id": RUN,
            "created_at": "2026-10-29T03:00:35.008585+00:00",
            "status": "complete",
            "seed": 42,
            "llm_calls": 1,
            "llm_reserved_tokens": 3000,
            "llm_tokens": 0,
            "llm_reserved_usd": 0.0,
            "llm_cost_usd": 0.0,
        },
        "metrics": {
            "orders": 7,
            "delivered": 7,
            "pending": 0,
            "active": 0,
            "unserved": 0,
            "on_time": 7,
            "delivery_cost_eur": 10.822515148279479,
            "overdue": 0,
            "on_time_pct": 100.0,
            "cost_per_delivery_eur": 1.55,
        },
        "orders": [{"transcript": "must stay local"}],
        "complaints": [{"body": "private customer complaint"}],
    }


def test_baseline_run_receipt_preserves_kpis_status_and_unknown_model_cost(tmp_path):
    source = tmp_path / "run.json"
    source.write_text(json.dumps(baseline_receipt()))
    output = tmp_path / "baseline"
    manifest = analytics.prepare_bundle(source, output)
    row = json.loads((output / "run_receipts.ndjson").read_text())
    assert row["run_id"] == RUN and row["status"] == "complete"
    assert row["run_created_at"] == "2026-10-29T03:00:35.008585+00:00"
    assert row["usage_cost_usd"] is None and row["unknown_usage_calls"] is None
    assert row["reserved_cost_usd"] == 0
    assert row["checks_total"] == 0 and row["replay_matches"] is None
    metrics = {
        item["metric_name"]: item["metric_value"]
        for line in (output / "run_kpis.ndjson").read_text().splitlines()
        if (item := json.loads(line))
    }
    assert metrics["orders"] == metrics["on_time"] == 7
    assert metrics["on_time_pct"] == 100
    assert metrics["cost_per_delivery_eur"] == 1.55
    assert metrics["llm_calls"] == 1 and metrics["llm_cost_usd"] == 0
    assert manifest["tables"]["run_kpis"]["rows"] == 15
    assert "private customer" not in (output / "run_receipts.ndjson").read_text()


def test_baseline_zero_cost_requires_explicit_zero_model_calls():
    data = baseline_receipt()
    data["run"]["llm_calls"] = 0
    rows, _ = analytics.receipt_rows(data, "b" * 64, EXPORTED)
    assert rows[0]["usage_cost_usd"] == 0 and rows[0]["unknown_usage_calls"] == 0
    del data["run"]["llm_calls"]
    rows, _ = analytics.receipt_rows(data, "b" * 64, EXPORTED)
    assert rows[0]["usage_cost_usd"] is None
    data["run"].update(llm_calls=2, llm_cost_usd=0.12, llm_reserved_usd=0.4)
    rows, _ = analytics.receipt_rows(data, "b" * 64, EXPORTED)
    assert rows[0]["usage_cost_usd"] is None
    assert rows[0]["reserved_cost_usd"] == 0.4

"""Analytics retains failures/repeats without changing evaluation or invoking models."""

import copy
from datetime import UTC, datetime

import pytest

from delivery.eval_analytics import export_judge, export_scenarios
from delivery.scenario_report import (
    Outcome,
    Receipt,
    Reproduction,
    digest,
    load_manifest,
    outcome_hash,
)


class Writer:
    def __init__(self):
        self.rows = []
        self.flushed = False

    def enqueue(self, table, row, *, event_id=None):
        assert table == "eval_runs"
        self.rows.append(row)
        return True

    def flush(self, timeout=10):
        assert timeout <= 5
        self.flushed = True
        return True


def scenario_receipt():
    manifest = load_manifest()
    outcomes = [
        Outcome(id=case.id, observed={check.id: check.expected for check in case.checks})
        for case in manifest.cases
    ]
    configuration = {case.fixture: "b" * 64 for case in manifest.cases}
    receipt = Receipt(
        schema_version=1,
        kind="agent-scenarios",
        mode="local-deterministic",
        version=manifest.version,
        seed=manifest.seed,
        fixture_hash=digest(manifest.model_dump(mode="json")),
        source_fingerprint="a" * 64,
        source_changed=False,
        created_at=datetime(2026, 10, 29, tzinfo=UTC),
        configurations=configuration,
        results=outcomes,
        reproduction=Reproduction(
            repetitions=2,
            hashes=[outcome_hash(outcomes)] * 2,
            previous_results=[copy.deepcopy(outcomes)],
            previous_configurations=[configuration],
        ),
    )
    return manifest, receipt


def test_export_retains_earlier_failure_missing_cases_and_strict_types():
    manifest, receipt = scenario_receipt()
    first = receipt.reproduction.previous_results[0]
    first[0].observed["winners"] = True  # A bool cannot replace the integer count 1.
    first.pop()
    writer = Writer()
    assert export_scenarios(manifest, receipt, writer=writer) == 24
    assert writer.flushed
    assert len({row["event_id"] for row in writer.rows}) == 24
    assert sum(row["passed"] for row in writer.rows) == 22
    assert writer.rows[0]["passed"] is False
    assert writer.rows[11]["category"] == "missing"
    assert all(row["passed"] for row in writer.rows[12:])
    assert all(row["repeat_k"] == 2 for row in writer.rows)
    assert all(row["mode"] == "local-deterministic" for row in writer.rows)
    again = Writer()
    export_scenarios(manifest, receipt, writer=again)
    assert writer.rows == again.rows  # Replay reuses insertion IDs.


def test_changed_source_cannot_publish_green_analytics():
    manifest, receipt = scenario_receipt()
    receipt.source_changed = True
    writer = Writer()
    export_scenarios(manifest, receipt, writer=writer)
    assert all(not row["passed"] and row["category"] == "source_changed" for row in writer.rows)


def test_analytics_outage_does_not_change_local_receipt_or_leak_errors(caplog):
    class Unavailable(Writer):
        def enqueue(self, *args, **kwargs):
            raise RuntimeError("secret-credential")

    manifest, receipt = scenario_receipt()
    before = receipt.model_dump()
    assert export_scenarios(manifest, receipt, writer=Unavailable()) == 0
    assert receipt.model_dump() == before
    assert "eval_analytics_export_failed" in caplog.text
    assert "secret-credential" not in caplog.text


def test_changed_repeat_inputs_cannot_publish_green_analytics():
    manifest, receipt = scenario_receipt()
    receipt.reproduction.previous_configurations = [dict(receipt.configurations)]
    fixture = next(iter(receipt.configurations))
    receipt.reproduction.previous_configurations[0][fixture] = "c" * 64
    writer = Writer()
    export_scenarios(manifest, receipt, writer=writer)
    assert all(not row["passed"] and row["category"] == "input_changed" for row in writer.rows)


def judge_report():
    return {
        "created_at": "2026-10-29T00:00:00+00:00",
        "fixture_version": "recovery-v1",
        "label": "test",
        "model_version": "fake",
        "mode": "cloud",
        "results": [
            {
                "case_id": "reject",
                "status": "ok",
                "hard_policy_violation": True,
                "passed": False,
                "input_tokens": 100,
                "output_tokens": 20,
                "latency_ms": 15,
                "reason": "private response",
            }
        ],
    }


def test_judge_unknown_cost_is_not_free_and_reply_text_is_excluded():
    report = judge_report()
    writer = Writer()
    assert export_judge(report, writer=writer) == 1
    row = writer.rows[0]
    assert row["cost_usd"] is None
    assert row["passed"] is False and row["category"] == "hard_policy_violation"
    assert "reason" not in row and "private response" not in str(row)
    assert row["repeat_k"] == row["repetition"] == 1
    report["pricing_usd_per_million"] = {"input": 1, "output": 2}
    export_judge(report, writer=writer)
    assert writer.rows[1]["cost_usd"] == pytest.approx(0.00014)
    report["results"][0]["status"] = "provider_error"
    export_judge(report, writer=writer)
    assert writer.rows[2]["cost_usd"] is None


def test_disabled_writer_has_no_side_effects():
    from delivery import analytics

    writer = analytics.BigQueryBatchWriter(
        client_factory=lambda _: pytest.fail("Disabled export requested credentials")
    )
    assert export_judge(judge_report(), writer=writer) == 0

"""Health must distinguish measured success from missing, partial and stale evidence."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from delivery import health
from delivery.api import app
from delivery.config import settings


def test_capability_selectors_resolve_to_current_test_functions():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config/health-categories.json").read_text())
    for capability in manifest["capabilities"]:
        for selector in capability["selectors"]:
            path, _, function = selector.partition("::")
            source = root / path
            assert source.is_file(), selector
            if function:
                names = {
                    node.name
                    for node in ast.walk(ast.parse(source.read_text()))
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                assert function in names, selector


def receipt(**changes):
    now = datetime.now(UTC).isoformat()
    row = {
        "id": "tests/test_typed_memory.py::test_example[one]",
        "file": "tests/test_typed_memory.py",
        "line": 12,
        "name": "test_example[one]",
        "description": "One typed observation.",
        "markers": ["integration"],
        "status": "passed",
        "duration_seconds": 0.1,
        "failure_phase": None,
    }
    return {
        "schema_version": 1,
        "kind": "tests",
        "id": str(uuid4()),
        "state": "completed",
        "started_at": now,
        "completed_at": now,
        "duration_seconds": 1,
        "exit_code": 0,
        "scope": "full",
        "source_fingerprint": "a" * 64,
        "source_revision": "b" * 40,
        "source_changed": False,
        "collection_errors": 0,
        "tests": [row],
        **changes,
    }


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "REPORTS", tmp_path)
    monkeypatch.setattr(health, "source_fingerprint", lambda root: "a" * 64)
    return tmp_path


def save(directory, value, name="latest-tests.json"):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_missing_and_corrupt_reports_never_look_successful(reports):
    assert health.evidence()["available"] is False
    save(reports, {"passed": 307})
    result = health.evidence()
    assert result["test_run"] is None and result["tests"] == []
    assert all(c["status"] == "not_measured" for c in result["capabilities"])
    (reports / "latest-tests.json").write_text("{broken", encoding="utf-8")
    assert health.evidence()["available"] is False
    save(reports, {"passed": 9999}, f"runs/{uuid4()}.json")
    assert health.evidence()["invalid_history_reports"] == 1


def test_case_counts_categories_history_and_parameter_ids_come_from_records(reports):
    value = receipt()
    value["counts"] = {"passed": 9999}  # Never trust a precomputed headline.
    save(reports, value)
    save(reports, value, f"runs/{value['id']}.json")
    result = health.evidence()
    assert result["test_run"]["counts"]["total"] == 1
    assert result["test_run"]["freshness"] == "current"
    assert result["categories"][0]["id"] == "memory"
    assert result["tests"][0]["id"].endswith("[one]")
    assert result["history"][0]["id"] == value["id"]
    assert health.evidence(uuid4())["available"] is False
    assert health.evidence(health.UUID(value["id"]))["available"] is True


@pytest.mark.parametrize(
    "change,expected",
    [
        ({"scope": "partial"}, "incomplete"),
        ({"scope": "collection"}, "incomplete"),
        ({"exit_code": 2}, "failed"),
        ({"collection_errors": 1}, "failed"),
        ({"state": "running", "completed_at": None, "exit_code": None}, "running"),
        ({"tests": []}, "not_measured"),
    ],
)
def test_partial_interrupted_running_and_empty_receipts_are_not_passed(change, expected):
    result = health.run_summary(health.TestRun.model_validate(receipt(**change)), "a" * 64)
    assert result["status"] == expected


@pytest.mark.parametrize("status", ["skipped", "xfailed", "xpassed", "not_run", "failed"])
def test_nonpassing_cases_do_not_inflate_pass_count(status):
    value = receipt()
    value["tests"][0]["status"] = status
    result = health.run_summary(health.TestRun.model_validate(value), "a" * 64)
    assert result["counts"]["passed"] == 0 and result["status"] != "passed"


def test_receipt_source_drift_age_and_changes_during_run_stay_visible():
    now = datetime.now(UTC)
    assert health.freshness(now, "a", "b") == "outdated"
    assert health.freshness(now, "a", "a", True) == "outdated"
    assert health.freshness(now - timedelta(hours=25), "a", "a") == "stale"
    assert health.freshness(now + timedelta(hours=1), "a", "a") == "stale"


def test_new_test_files_and_missing_eval_selectors_cannot_hide():
    row = receipt()["tests"][0]
    row.update(file="tests/test_new_area.py", id="tests/test_new_area.py::test_new")
    groups = health.classify([row], health.taxonomy())
    assert groups[0]["id"] == "unclassified"
    assert all(
        c["status"] == "not_measured" and c["missing_selectors"]
        for c in health.capability_evidence([row], health.taxonomy())
    )


def test_duplicate_ids_source_traversal_and_inconsistent_passes_are_rejected():
    value = receipt()
    value["tests"] *= 2
    with pytest.raises(ValidationError):
        health.TestRun.model_validate(value)
    value = receipt()
    value["tests"][0]["file"] = "tests/../private.py"
    with pytest.raises(ValidationError):
        health.TestRun.model_validate(value)
    value = receipt()
    value["tests"][0]["failure_phase"] = "teardown"
    with pytest.raises(ValidationError):
        health.TestRun.model_validate(value)


@pytest.mark.parametrize(
    "status,code", [("passed", 1), ("passed", None), ("failed", 0), ("unavailable", 1)]
)
def test_malformed_code_check_outcomes_never_render_green(reports, status, code):
    save(
        reports,
        {
            "schema_version": 1,
            "kind": "checks",
            "source_fingerprint": "a" * 64,
            "created_at": datetime.now(UTC).isoformat(),
            "checks": [
                {
                    "id": "ruff",
                    "label": "Ruff",
                    "status": status,
                    "exit_code": code,
                    "duration_seconds": 0,
                }
            ],
        },
        "latest-checks.json",
    )
    assert health.static_checks("a" * 64)["available"] is False


def baseline_receipt():
    fixture = json.loads((health.ROOT / "data/evals/recovery-judge.json").read_text())
    return {
        "schema_version": 1,
        "kind": "evals",
        "source_fingerprint": "a" * 64,
        "created_at": datetime.now(UTC).isoformat(),
        "source_changed": False,
        "report": {
            "fixture_version": fixture["version"],
            "mode": "offline-baseline",
            "results": [
                {
                    "case_id": case["id"],
                    "expected_decision": case["expected_decision"],
                    "actual_decision": case["expected_decision"],
                    "status": "ok",
                    "passed": True,
                    "hard_policy_violation": False,
                    "latency_ms": 0.1,
                    "input_tokens": 0,
                    "output_tokens": 0,
                }
                for case in fixture["cases"]
            ],
        },
    }


def test_judge_baseline_recomputes_decisions_and_requires_all_fixture_cases(reports):
    value = baseline_receipt()
    save(reports, value, "latest-evals.json")
    assert health.judge_evidence("a" * 64)["counts"] == {"total": 6, "passed": 6}
    value["report"]["results"][1]["actual_decision"] = "approve_retry"
    save(reports, value, "latest-evals.json")
    result = health.judge_evidence("a" * 64)
    assert result["counts"]["passed"] == 5 and result["rows"][1]["hard_policy_violation"]
    value["report"]["results"] = value["report"]["results"][:1]
    value["source_changed"] = True
    save(reports, value, "latest-evals.json")
    result = health.judge_evidence("a" * 64)
    assert result["counts"] == {"total": 6, "passed": 1} and len(result["missing_cases"]) == 5
    assert result["freshness"] == "outdated"


@pytest.mark.integration
def test_health_routes_are_read_only_local_and_validate_run_ids(reports, db_url, monkeypatch):
    save(reports, receipt())
    monkeypatch.setenv("DATABASE_URL", db_url)
    settings.cache_clear()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/health/evidence").json()["available"]
        assert client.get("/api/health/evidence?test_run=../private").status_code == 422
        assert client.post("/api/health/evidence", json={"command": "anything"}).status_code == 405
        assert (
            client.get("/api/health/evidence", headers={"host": "elsewhere.test"}).status_code
            == 403
        )
    settings.cache_clear()


def test_probe_errors_do_not_disclose_private_configuration(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-dsn-and-password")

    monkeypatch.setattr(health, "connect", fail)
    monkeypatch.setattr(health.redis.Redis, "from_url", fail)
    result = health.runtime()
    assert all(service["status"] == "failed" for service in result["services"])
    assert result["selected"] is None and "private-dsn" not in json.dumps(result)


@pytest.mark.integration
def test_live_diagnostics_are_run_scoped_and_show_real_queue_counts(db_url, run_id, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    settings.cache_clear()

    class RedisProbe:
        def ping(self):
            return True

        def close(self):
            pass

    monkeypatch.setattr(health.redis.Redis, "from_url", lambda *a, **k: RedisProbe())
    try:
        with health.connect() as conn:
            conn.execute(
                "INSERT INTO events(run_id,producer,topic,payload,dedupe_key,trace_id,state) "
                "VALUES (%s,'generator','order.created','{}','health-event','health','dead')",
                (run_id,),
            )
        result = health.runtime(run_id)
        assert result["selected"]["queue"]["dead"] == 1
        assert result["selected"]["queue"]["total"] == 1
        assert result["selected"]["model_reservations"] == 0
        with pytest.raises(health.HTTPException) as failure:
            health.runtime(uuid4())
        assert failure.value.status_code == 404
    finally:
        settings.cache_clear()

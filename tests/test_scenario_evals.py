"""Scenario scores must expose failures, omissions, drift and failed repeat attempts."""

import copy
import importlib.util
import json
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from delivery import health, scenario_evals
from delivery.db import connect
from delivery.scenario_evals import require_local_test_database, run_once, supply_config
from delivery.scenario_report import (
    ROOT,
    Manifest,
    Outcome,
    digest,
    load_manifest,
    outcome_hash,
    summarize,
    validate_receipt,
)


def receipt():
    manifest = load_manifest()
    results = [
        Outcome(id=c.id, observed={k.id: k.expected for k in c.checks}) for c in manifest.cases
    ]
    return {
        "schema_version": 1,
        "kind": "agent-scenarios",
        "mode": "local-deterministic",
        "version": manifest.version,
        "seed": manifest.seed,
        "fixture_hash": digest(manifest.model_dump(mode="json")),
        "source_fingerprint": "a" * 64,
        "source_changed": False,
        "created_at": datetime.now(UTC).isoformat(),
        "configurations": {c.fixture: "b" * 64 for c in manifest.cases},
        "results": [row.model_dump() for row in results],
        "reproduction": {"repetitions": 1, "hashes": [outcome_hash(results)]},
    }


def rehash(value):
    repeats = [*value["reproduction"].get("previous_results", []), value["results"]]
    value["reproduction"].setdefault(
        "previous_configurations", [copy.deepcopy(value["configurations"]) for _ in repeats[:-1]]
    )
    value["reproduction"]["hashes"] = [
        outcome_hash([Outcome.model_validate(row) for row in rows]) for rows in repeats
    ]
    return value


def report(value):
    manifest = load_manifest()
    return summarize(manifest, validate_receipt(rehash(value), manifest))


def test_manifest_scenarios_are_separate_from_test_counts_and_cover_all_roles():
    result = report(receipt())
    assert result["counts"] == {"total": 12, "passed": 12, "failed": 0, "not_measured": 0}
    assert {r["id"] for r in result["roles"]} == {
        "inventory",
        "restaurant",
        "dispatcher",
        "courier",
    }
    assert all(r["score"] == 100 and r["status"] == "passed" for r in result["roles"])
    assert result["checks_total"] == 49


def test_bad_inventory_behavior_produces_partial_score_and_inspectable_failed_criterion():
    value = receipt()
    value["results"][0]["observed"]["winners"] = 2
    result = report(value)
    case = result["cases"][0]
    assert case["status"] == "failed" and case["score"] == 75
    assert case["checks"][0] == {
        "id": "winners",
        "label": "Baskets reserved from the last unit",
        "expected": 1,
        "actual": 2,
        "repetition": 1,
        "status": "failed",
    }
    assert result["status"] == "failed" and result["roles"][0]["score"] < 100


def test_boolean_cannot_be_faked_as_a_measured_count():
    value = receipt()
    value["results"][0]["observed"]["winners"] = True
    assert report(value)["cases"][0]["checks"][0]["status"] == "failed"


def test_missing_cases_and_criteria_receive_no_credit():
    value = receipt()
    value["results"].pop()
    del value["results"][0]["observed"]["winners"]
    result = report(value)
    assert result["status"] == "incomplete" and result["score"] < 100
    assert result["counts"]["not_measured"] == 2
    assert result["cases"][0]["checks"][0]["actual"] is None
    empty = summarize(load_manifest(), None)
    assert empty["score"] is None and empty["counts"]["not_measured"] == 12
    assert empty["status"] == "not_measured"


def test_later_pass_cannot_erase_an_earlier_failed_case():
    value = receipt()
    first = copy.deepcopy(value["results"])
    first[0]["observed"]["winners"] = 2
    value["reproduction"].update(repetitions=2, previous_results=[first])
    result = report(value)
    assert result["reproduction"]["matched"] is False
    assert result["status"] == "failed" and result["counts"]["failed"] == 1
    assert result["cases"][0]["checks"][0]["actual"] == 2
    assert result["cases"][0]["checks"][0]["repetition"] == 1


def test_missing_first_measurement_cannot_hide_later_failure_or_other_criteria():
    value = receipt()
    first = copy.deepcopy(value["results"])
    del first[0]["observed"]["winners"]
    value["results"][0]["observed"]["rejected"] = 0
    value["reproduction"].update(repetitions=2, previous_results=[first])
    result = report(value)
    case = result["cases"][0]
    assert case["status"] == "failed" and result["counts"]["failed"] == 1
    assert case["checks"][0]["status"] == "not_measured"
    assert case["checks"][1]["status"] == "failed"
    assert case["checks"][1]["actual"] == 0 and case["checks"][1]["repetition"] == 2


def test_unmeasured_role_does_not_gain_a_score_from_another_roles_cases():
    value = receipt()
    value["results"] = [row for row in value["results"] if row["id"].startswith("inventory.")]
    result = report(value)
    assert result["roles"][0]["score"] == 100
    assert all(r["score"] is None and r["status"] == "not_measured" for r in result["roles"][1:])


def test_input_drift_is_published_as_a_failure_instead_of_aborting_the_receipt(monkeypatch):
    value = receipt()
    rows = [Outcome.model_validate(row) for row in value["results"]]
    earlier = copy.deepcopy(value["configurations"])
    earlier["pantry"] = "f" * 64
    attempts = iter([(rows, earlier), (rows, value["configurations"])])
    monkeypatch.setattr(scenario_evals, "run_once", lambda *a: next(attempts))
    value.update(scenario_evals.evaluate(load_manifest(), "postgresql://localhost/delivery_test"))
    result = report(value)
    assert result["status"] == "failed"
    assert result["reproduction"]["outcomes_matched"] is True
    assert result["reproduction"]["inputs_matched"] is False
    assert result["reproduction"]["matched"] is False


def test_engine_error_is_a_failed_case_with_unmeasured_criteria():
    value = receipt()
    value["results"][0].update(observed={}, error="execution_failed")
    result = report(value)
    assert result["cases"][0]["status"] == "failed"
    assert result["cases"][0]["score"] == 0
    assert result["cases"][0]["checks"][0]["status"] == "not_measured"


@pytest.mark.parametrize(
    "corruption",
    [
        "version",
        "seed",
        "fixture_hash",
        "mode",
        "duplicate",
        "unknown_case",
        "unknown_check",
        "extra_score",
        "extra_payload",
        "extra_error",
        "configurations",
        "hashes",
        "repetitions",
        "previous_hash",
        "nonfinite",
        "no_timezone",
    ],
)
def test_invalid_receipts_cannot_be_published_as_green(corruption):
    value = receipt()
    if corruption in {"version", "fixture_hash", "mode"}:
        value[corruption] = "incorrect"
    elif corruption == "seed":
        value["seed"] += 1
    elif corruption == "duplicate":
        value["results"].append(value["results"][0])
    elif corruption == "unknown_case":
        value["results"][0]["id"] = "invented"
    elif corruption == "unknown_check":
        value["results"][0]["observed"]["invented"] = True
    elif corruption == "extra_score":
        value["score"] = 100
    elif corruption == "extra_payload":
        value["results"][0]["payload"] = {"private": "not publishable"}
    elif corruption == "extra_error":
        value["results"][0]["error"] = "raw exception with credentials"
    elif corruption == "configurations":
        value["configurations"] = {}
    elif corruption == "hashes":
        value["reproduction"]["hashes"] = ["f" * 64]
    elif corruption == "repetitions":
        value["reproduction"]["repetitions"] = 2
    elif corruption == "previous_hash":
        value["reproduction"].update(repetitions=2, previous_results=[value["results"]])
    elif corruption == "nonfinite":
        value["results"][0]["observed"]["winners"] = float("nan")
    elif corruption == "no_timezone":
        value["created_at"] = "2026-01-01T12:00:00"
    with pytest.raises(ValueError):
        validate_receipt(value, load_manifest())


def test_repeat_hash_ignores_event_ids_timings_and_case_order():
    rows = [Outcome.model_validate(row) for row in receipt()["results"]]
    assert outcome_hash(rows) == outcome_hash(list(reversed(rows)))
    changed = rows[0].model_copy(update={"observed": {"winners": 2}})
    assert outcome_hash([changed, *rows[1:]]) != outcome_hash(rows)


@pytest.mark.parametrize(
    "url",
    [
        "",
        "invalid",
        "postgresql://localhost/delivery",
        "postgresql://remote.example/delivery_test",
        "postgresql://localhost/delivery_test?host=remote.example",
        "postgresql://[bad/delivery_test",
    ],
)
def test_evaluations_reject_production_remote_and_connection_overrides(url):
    with pytest.raises(ValueError, match="local delivery_test"):
        require_local_test_database(url)


def test_effective_supply_fixtures_have_local_search_zero_model_budgets_and_stable_hashes():
    for variant in ("pantry", "market-forward", "substitution-declined", "substitution-approved"):
        config = supply_config(731, variant)
        assert digest(config.model_dump(mode="json")) == digest(
            supply_config(731, variant).model_dump(mode="json")
        )
        assert all(
            a.search.provider == "local" and a.limits.model_calls == 0
            for a in config.agents.values()
        )


def test_health_surfaces_scenario_failures_missing_results_and_source_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(health, "REPORTS", tmp_path)
    assert health.scenario_evidence("a" * 64)["available"] is False
    value = receipt()
    value["results"][0]["observed"]["winners"] = 2
    path = tmp_path / "latest-scenarios.json"
    path.write_text(json.dumps(rehash(value)))
    result = health.scenario_evidence("a" * 64)
    assert result["freshness"] == "current" and result["counts"]["failed"] == 1
    assert health.scenario_evidence("b" * 64)["freshness"] == "outdated"
    value["created_at"] = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    path.write_text(json.dumps(value))
    assert health.scenario_evidence("a" * 64)["freshness"] == "stale"
    value["source_changed"] = True
    path.write_text(json.dumps(value))
    assert health.scenario_evidence("a" * 64)["freshness"] == "outdated"
    path.write_text('{"score":100}')
    assert health.scenario_evidence("a" * 64)["score"] is None


def test_cli_rejects_bad_database_before_creating_worlds_or_reports(monkeypatch):
    spec = importlib.util.spec_from_file_location("eval_agents", ROOT / "scripts/eval_agents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://localhost/delivery")
    monkeypatch.setattr(sys, "argv", ["eval_agents.py"])
    monkeypatch.setattr(module, "evaluate", lambda *a, **k: pytest.fail("No mutation allowed"))
    assert module.main() == 2


def test_interrupted_cli_clears_old_green_evidence_before_running(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("eval_pending", ROOT / "scripts/eval_agents.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "source_fingerprint", lambda root: "a" * 64)
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://localhost/delivery_test")
    monkeypatch.setenv("DATABASE_URL", "restored-after-test")
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    monkeypatch.setattr(sys, "argv", ["eval_agents.py"])
    target = tmp_path / "artifacts/health/latest-scenarios.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(receipt()))

    class Lock:
        def execute(self, statement):
            assert statement == "SELECT pg_advisory_lock(918275)"

    @contextmanager
    def connection(url):
        yield Lock()

    def interrupt(*args):
        pending = json.loads(target.read_text())
        assert report(pending)["counts"]["passed"] == 0
        raise RuntimeError("Injected checker interruption")

    monkeypatch.setattr("delivery.db.connect", connection)
    monkeypatch.setattr(module, "evaluate", interrupt)
    with pytest.raises(RuntimeError, match="checker interruption"):
        module.main()
    assert report(json.loads(target.read_text()))["status"] == "not_measured"


@pytest.mark.integration
def test_failed_supply_bootstrap_removes_its_already_committed_base_city(db_url, monkeypatch):
    from delivery import supply

    with connect(db_url) as conn:
        before = {str(r["id"]) for r in conn.execute("SELECT id FROM runs").fetchall()}

    def fail_city(config):
        raise RuntimeError("Injected supply definition failure")

    monkeypatch.setattr(supply, "city_for", fail_city)
    with pytest.raises(RuntimeError, match="definition failure"):
        supply.new_supply(supply_config(731, "pantry"), db_url)
    with connect(db_url) as conn:
        assert {str(r["id"]) for r in conn.execute("SELECT id FROM runs").fetchall()} == before


@pytest.mark.integration
def test_real_scenario_battery_uses_scoped_agents_and_retires_all_fixture_identities(db_url):
    with connect(db_url) as conn:
        before_runs = {str(r["id"]) for r in conn.execute("SELECT id FROM runs").fetchall()}
        before_roles = {
            r["rolname"]
            for r in conn.execute(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'lab_i_%'"
            ).fetchall()
        }
    manifest = load_manifest()
    results, configurations = run_once(manifest, db_url)
    value = receipt()
    value.update(results=[r.model_dump() for r in results], configurations=configurations)
    result = report(value)
    assert result["counts"]["passed"] == 12, [c for c in result["cases"] if c["status"] != "passed"]
    assert all(c["evidence"] for c in result["cases"])
    assert all(len(c["evidence"]) <= 200 for c in result["cases"])
    with connect(db_url) as conn:
        assert {str(r["id"]) for r in conn.execute("SELECT id FROM runs").fetchall()} == before_runs
        assert {
            r["rolname"]
            for r in conn.execute(
                "SELECT rolname FROM pg_roles WHERE rolname LIKE 'lab_i_%'"
            ).fetchall()
        } == before_roles


@pytest.mark.integration
def test_fixture_failure_still_cleans_up_and_never_exports_exception_text(db_url, monkeypatch):
    manifest = load_manifest().model_dump(mode="json")
    manifest["cases"] = [
        next(c for c in manifest["cases"] if c["role"] == role)
        for role in ("inventory", "restaurant", "dispatcher", "courier")
    ]
    for case in manifest["cases"]:
        case["fixture"] = "injected-fault"
    runs = []

    def crash(world):
        runs.append(world.lab(inventory=True))
        raise RuntimeError("Do not export this raw credential or private payload")

    monkeypatch.setattr(scenario_evals, "FIXTURES", {"injected-fault": crash})
    rows, _ = run_once(Manifest.model_validate(manifest), db_url)
    assert all(r.error == "execution_failed" and not r.observed for r in rows)
    assert "credential" not in json.dumps([r.model_dump() for r in rows])
    with connect(db_url) as conn:
        assert conn.execute("SELECT id FROM runs WHERE id=%s", (runs[0],)).fetchone() is None

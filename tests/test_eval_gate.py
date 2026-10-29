from copy import deepcopy

import pytest

from delivery.eval_gate import collection_failed, compare_reports, load_thresholds
from delivery.scenario_report import EvalAttempt


def report(n=10, repeats=3):
    return {"schema_version": 1, "kind": "model-evals", "mode": "scripted-offline",
            "repeat": repeats, "fixture_hashes": {"arm": "a" * 64}, "rows": [
                EvalAttempt(arm="arm", case_id=f"c{i}", repetition=j, passed=True,
                            categories=dict.fromkeys(load_thresholds()["categories"], True),
                            latency_ms=10.0, cost_usd=0.0).model_dump()
                for i in range(n) for j in range(1, repeats + 1)]}


def fail(candidate, count):
    for row in candidate["rows"]:
        if int(row["case_id"][1:]) < count:
            row["passed"] = False
            row["categories"]["task"] = False


def test_only_statistically_supported_regression_fails():
    baseline = report()
    candidate = deepcopy(baseline)
    fail(candidate, 1)
    assert compare_reports(baseline, candidate, load_thresholds())["status"] != "regression"
    fail(candidate, 10)
    result = compare_reports(baseline, candidate, load_thresholds())
    assert result["status"] == "regression"
    assert len(result["regressions"]) == 1
    assert result["regressions"][0]["category"] == "task"


def test_repetition_does_not_manufacture_sample_size():
    baseline = report(n=1, repeats=100)
    candidate = deepcopy(baseline)
    fail(candidate, 1)
    result = compare_reports(baseline, candidate, load_thresholds())
    assert result["status"] != "regression"
    assert result["comparisons"][0]["status"] == "insufficient_evidence"


def test_identical_missing_and_forged_baselines():
    baseline = report()
    baseline["arms"] = {"arm": {"pass_rate": 0}}
    assert compare_reports(baseline, report(), load_thresholds())["status"] != "regression"
    assert compare_reports(None, report(), load_thresholds())["status"] == "baseline_missing"
    for change in ({"fixture_hashes": {"arm": "b"}}, {"repeat": 1}, {"mode": "live"}):
        with pytest.raises(ValueError, match="Incomparable"):
            compare_reports(baseline, {**report(), **change}, load_thresholds())


def test_missing_rows_are_invalid_and_efficiency_is_recomputed():
    baseline = report()
    candidate = deepcopy(baseline)
    candidate["rows"].pop()
    with pytest.raises(ValueError):
        compare_reports(baseline, candidate, load_thresholds())
    candidate = deepcopy(baseline)
    for row in candidate["rows"]:
        row.update(latency_ms=20.0, cost_usd=.01)
    value = compare_reports(baseline, candidate, load_thresholds())["efficiency"]["arm"]
    assert value["p95_latency_ms"]["delta"] == 10
    assert value["cost_per_success_usd"]["candidate"] == pytest.approx(.01)


def test_repeat_header_cannot_disguise_different_trial_counts():
    baseline = report()
    candidate = report(repeats=1)
    candidate["repeat"] = 3
    with pytest.raises(ValueError, match="Declared repeat"):
        compare_reports(baseline, candidate, load_thresholds())


def test_collection_defers_only_quality_failures_to_the_statistical_gate():
    candidate = report()
    candidate["golden"] = [{"passed": True}]
    fail(candidate, 1)
    assert collection_failed(candidate)
    assert not collection_failed(candidate, record_only=True)
    assert compare_reports(report(), candidate, load_thresholds())["status"] != "regression"
    candidate["rows"][0]["error"] = "RunnerFailure"
    assert collection_failed(candidate, record_only=True)
    candidate["rows"][0]["error"] = None
    candidate["golden"][0]["passed"] = False
    assert collection_failed(candidate, record_only=True)


def test_record_only_rejects_incomplete_or_missing_execution_evidence():
    candidate = report()
    candidate["golden"] = [{"passed": True}]
    candidate["repeat"] = 4
    with pytest.raises(ValueError, match="Declared repeat"):
        collection_failed(candidate, record_only=True)
    candidate["repeat"] = 3
    candidate["rows"].pop()
    with pytest.raises(ValueError, match="complete"):
        collection_failed(candidate, record_only=True)
    candidate = report()
    candidate["golden"] = []
    with pytest.raises(ValueError, match="golden"):
        collection_failed(candidate, record_only=True)


def test_record_only_cannot_hide_mismatched_pass_criteria():
    candidate = report()
    candidate["golden"] = [{"passed": True}]
    candidate["rows"][0]["categories"]["schema"] = False
    with pytest.raises(ValueError, match="Pass must agree"):
        collection_failed(candidate, record_only=True)

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from delivery.eval_gate import load_thresholds
from delivery.release_gate import compare_release, results_table


def report(failures=()):
    rows = []
    for case in range(16):
        for repetition in range(1, 6):
            passed = case not in failures or repetition != 1
            rows.append({"arm": "agent", "case_id": str(case), "repetition": repetition,
                         "passed": passed, "categories": {"schema": True, "length": True,
                         "invented_tool": True, "task": passed, "trajectory": True},
                         "latency_ms": float(case + repetition), "cost_usd": .01})
    return {"schema_version": 1, "kind": "model-evals", "mode": "scripted-offline",
            "split": "heldout", "repeat": 5, "fixture_hashes": {"agent": "frozen"},
            "rows": rows, "golden": [{"passed": True}], "source_revision": "tested"}


def test_noise_does_not_fail_release_but_real_reliability_drop_does():
    config = load_thresholds()
    assert compare_release(report(), report([0]), config)["status"] == "no_significant_regression"
    result = compare_release(report(), report(range(16)), config)
    assert result["status"] == "regression"
    reliability = result["pass_power_k_comparisons"][0]
    assert reliability["regression"] and reliability["drop_ci95"] == [1.0, 1.0]


def test_summary_recomputes_pass_power_k_cost_and_latency_from_attempts():
    candidate = report([0])
    candidate["arms"] = {"agent": {"pass_power_k": 1, "cost_per_success_usd": 0}}
    result = compare_release(None, candidate, load_thresholds())
    assert result["status"] == "baseline_missing"
    row = result["summary"]["agent"]
    assert row["pass_power_k"] == 15 / 16
    assert row["cost_per_success_usd"] == pytest.approx(.8 / 79)
    assert row["pass_power_k_ci95"][0] < 1
    assert row["p95_latency_ms"] > 15
    assert "scripted offline" in results_table(candidate)


@pytest.mark.parametrize("mutation", ["split", "fixture", "missing_attempt", "duplicate_attempt"])
def test_incomparable_or_incomplete_evidence_is_not_a_green_release(mutation):
    candidate = deepcopy(report())
    if mutation == "split":
        candidate["split"] = "dev"
    elif mutation == "fixture":
        candidate["fixture_hashes"]["agent"] = "changed"
    elif mutation == "missing_attempt":
        candidate["rows"].pop()
    else:
        candidate["rows"][-1] = candidate["rows"][-2]
    with pytest.raises(ValueError):
        compare_release(report(), candidate, load_thresholds())


def test_reserved_cases_are_sealed_disjoint_and_never_loaded_by_default():
    manifest = json.loads(Path("evals/splits.json").read_text())
    cohorts = {"dev": set(), "heldout": set()}
    for name, expected in manifest["files"].items():
        path = Path(name)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
        split = "heldout" if path.parent.name == "heldout" else "dev"
        data = json.loads(path.read_text())
        if split == "heldout":
            assert len(data["eval_cases"]) >= 12
        for case in data["eval_cases"]:
            key = json.dumps({"state": case["session_input"]["state"],
                              "prompt": case["conversation"][0]["user_content"]}, sort_keys=True)
            cohorts[split].add(key)
    assert not cohorts["dev"] & cohorts["heldout"]
    import inspect

    from delivery.model_evals import evaluate_model_arms

    assert inspect.signature(evaluate_model_arms).parameters["split"].default == "dev"

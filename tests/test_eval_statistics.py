import pytest

from delivery.scenario_report import EvalAttempt, bootstrap_ci, summarize_arms


def row(case, repetition, passed, cost=1.0):
    return EvalAttempt(arm="llm", case_id=case, repetition=repetition, passed=passed,
                       categories={"task": passed}, latency_ms=10.0 * repetition, cost_usd=cost,
                       reserved_usd=2.0)


def test_pass_power_k_means_every_attempt_not_at_least_one():
    rows = [row("a", 1, True), row("a", 2, False), row("b", 1, True), row("b", 2, True)]
    summary = summarize_arms(rows)["llm"]
    assert summary["pass_rate"] == .75
    assert summary["pass_power_k"] == .5
    assert summary["cost_per_success_usd"] == pytest.approx(4 / 3)
    assert summary["p95_latency_ms"] == 20
    assert summary["pass_power_k_ci95"] == [0, 1]


def test_missing_duplicate_or_unbalanced_trials_are_not_green():
    with pytest.raises(ValueError, match="complete, unique"):
        summarize_arms([row("a", 1, True), row("a", 1, True)])
    with pytest.raises(ValueError, match="complete, unique"):
        summarize_arms([row("a", 1, True), row("a", 2, True), row("b", 1, True)])


def test_unknown_failed_call_cost_is_not_zero():
    value = summarize_arms([row("a", 1, True), row("b", 1, False, None)])["llm"]
    assert value["cost_per_success_usd"] is None
    assert value["unknown_cost_attempts"] == 1
    assert value["reserved_cost_per_success_usd"] == 4
    assert summarize_arms([row("a", 1, False)])["llm"]["cost_per_success_usd"] is None
    assert bootstrap_ci([1.0]) is None


def test_bootstrap_is_seeded_and_resamples_cases():
    assert bootstrap_ci([0, 1, 1, 0]) == bootstrap_ci([0, 1, 1, 0])
    single = summarize_arms([row("a", i, True) for i in range(1, 21)])["llm"]
    assert single["cases"] == 1 and single["pass_rate_ci95"] is None

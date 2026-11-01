"""Reserved-cohort release evidence; uncertainty is measured across cases, not retries."""

import math
from copy import deepcopy
from typing import Any

from delivery.eval_gate import collection_failed, compare_reports, validate_report
from delivery.scenario_report import attempt_groups, bootstrap_ci, summarize_arms


def validate_release(report: dict[str, Any]) -> None:
    if report.get("split") != "heldout":
        raise ValueError("Release decisions require the held-out cohort")
    if collection_failed(report, record_only=True):
        raise ValueError("Incomplete execution or broken golden contract")


def compare_release(
    baseline: dict[str, Any] | None, candidate: dict[str, Any], config: dict[str, Any],
) -> dict[str, Any]:
    validate_release(candidate)
    if baseline is not None:
        validate_release(baseline)
    thresholds = deepcopy(config)
    category_count = len(config["categories"])
    # Reserve one comparison per arm for the all-k success metric.
    thresholds["family_alpha"] *= category_count / (category_count + 1)
    result = compare_reports(baseline, candidate, thresholds)
    rows = validate_report(candidate)
    result["summary"] = summarize_arms(rows)
    result["split"] = "heldout"
    result["pass_power_k_comparisons"] = []
    if baseline is None:
        return result
    previous = validate_report(baseline)
    alpha = config["family_alpha"] / (len(result["summary"]) * (category_count + 1))
    for arm in result["summary"]:
        before = attempt_groups([r for r in previous if r.arm == arm])
        after = attempt_groups([r for r in rows if r.arm == arm])
        drops = [float(all(r.passed for r in before[k])) - float(all(r.passed for r in after[k]))
                 for k in sorted(before)]
        losses, wins = sum(d > 0 for d in drops), sum(d < 0 for d in drops)
        n = losses + wins
        p = sum(math.comb(n, i) for i in range(losses, n + 1)) / 2 ** n if n else 1.0
        interval = bootstrap_ci(drops)
        enough = len(drops) >= config["min_cases"]
        regression = bool(enough and interval and interval[0] > config["categories"]["task"][
            "max_drop"
        ] and p <= alpha)
        comparison = {"arm": arm, "metric": "pass_power_k", "cases": len(drops),
                      "drop": sum(drops) / len(drops), "drop_ci95": interval,
                      "p_value": p, "adjusted_alpha": alpha, "regression": regression}
        result["pass_power_k_comparisons"].append(comparison)
        if regression:
            result["regressions"].append(comparison)
            result["status"] = "regression"
    result["note"] += " Release pass^k uses the same paired case test and shared family alpha."
    return result


def results_table(report: dict[str, Any]) -> str:
    validate_release(report)
    summary = summarize_arms(validate_report(report))
    lines = ["| Held-out arm | Cases × k | pass^k | Bootstrap 95% CI | Cost / success | p95 |",
             "| --- | ---: | ---: | --- | ---: | ---: |"]
    for arm, row in summary.items():
        interval = row["pass_power_k_ci95"]
        ci = "unavailable" if interval is None else f"[{interval[0]:.3f}, {interval[1]:.3f}]"
        cost = "unknown" if row["cost_per_success_usd"] is None else (
            f"${row['cost_per_success_usd']:.4f}"
        )
        lines.append(f"| {arm} | {row['cases']} × {row['repeat']} | "
                     f"{row['pass_power_k']:.3f} | {ci} | {cost} | "
                     f"{row['p95_latency_ms']:.1f} ms |")
    lines += ["", "Measured with fresh ADK sessions and scripted offline models. This is contract",
              "evidence, not live-model quality, inference cost or production latency.",
              "pass^k is the fraction of cases passing every attempt; bootstrap intervals",
              "resample cases. An all-pass cohort has a degenerate [1, 1] interval and does",
              "not establish certainty on unseen workloads. Costs include failed attempts.",
              f"Source revision: `{report.get('source_revision', 'unversioned')}`."]
    return "\n".join(lines) + "\n"

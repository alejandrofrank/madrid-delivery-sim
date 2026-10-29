"""Paired regression gate over cases, with multiplicity and minimum-sample controls."""

import json
import math
from pathlib import Path
from typing import Any

from delivery.scenario_report import (
    EvalAttempt,
    attempt_groups,
    bootstrap_ci,
    summarize_arms,
)

ROOT = Path(__file__).resolve().parents[2]


def load_thresholds(path: Path = ROOT / "config/eval-gate.json") -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if (config["schema_version"] != 1 or not 0 < config["family_alpha"] <= .05
            or config["min_cases"] < 2 or not config["categories"]
            or any(not 0 <= c["max_drop"] < 1 for c in config["categories"].values())):
        raise ValueError("Invalid gate thresholds")
    return dict(config)


def validate_report(report: dict[str, Any]) -> list[EvalAttempt]:
    if report.get("schema_version") != 1 or report.get("kind") != "model-evals":
        raise ValueError("Unsupported eval artifact")
    rows = [EvalAttempt.model_validate(row) for row in report["rows"]]
    if not rows or set(report["fixture_hashes"]) != {r.arm for r in rows}:
        raise ValueError("Missing arms or fixture hashes")
    # Never trust saved pass-rate, cost or latency headlines.
    summarize_arms(rows)
    return rows


def collection_failed(report: dict[str, Any], *, record_only: bool = False) -> bool:
    """Let the comparison gate decide quality, but never suppress broken execution."""
    rows = validate_report(report)
    repeat = report.get("repeat")
    if type(repeat) is not int or not 1 <= repeat <= 100:
        raise ValueError("Invalid declared repeat count")
    for arm in {row.arm for row in rows}:
        groups = attempt_groups([row for row in rows if row.arm == arm])
        if any(len(group) != repeat for group in groups.values()):
            raise ValueError("Declared repeat count differs from measured attempts")
    golden = report.get("golden")
    if not isinstance(golden, list) or not golden:
        raise ValueError("Missing golden regression results")
    return (
        any(result.get("passed") is not True for result in golden)
        or any(row.error is not None for row in rows)
        or (not record_only and any(not row.passed for row in rows))
    )


def compare_reports(
    baseline: dict[str, Any] | None, candidate: dict[str, Any], config: dict[str, Any],
) -> dict[str, Any]:
    current = validate_report(candidate)
    if baseline is None:
        return {"status": "baseline_missing", "regressions": [], "comparisons": [],
                "note": "Bootstrap only: main has no matching stored artifact; no quality claim."}
    previous = validate_report(baseline)
    if (baseline["fixture_hashes"] != candidate["fixture_hashes"]
            or baseline.get("mode") != candidate.get("mode")
            or baseline.get("repeat") != candidate.get("repeat")):
        raise ValueError("Incomparable fixtures, modes or repeat counts; refresh baseline on main")
    arms = sorted({r.arm for r in current})
    comparisons = []
    adjusted_alpha = config["family_alpha"] / (len(arms) * len(config["categories"]))
    for arm in arms:
        before = attempt_groups([r for r in previous if r.arm == arm])
        after = attempt_groups([r for r in current if r.arm == arm])
        if any(len(group) != baseline["repeat"] for group in before.values()) or any(
            len(group) != candidate["repeat"] for group in after.values()
        ):
            raise ValueError("Declared repeat count differs from measured attempts")
        if set(before) != set(after):
            raise ValueError("Cases were added or removed; do not silently change the cohort")
        for category, threshold in config["categories"].items():
            if any(category not in r.categories for r in previous + current):
                raise ValueError("Required gate category missing")
            drops = [
                sum(r.categories[category] for r in before[key]) / len(before[key])
                - sum(r.categories[category] for r in after[key]) / len(after[key])
                for key in sorted(before)
            ]
            # Exact one-sided sign test on paired case rates. Repeats are not trials.
            # Conservative for ties; effect size is separately checked against the CI.
            losses, wins = sum(d > 0 for d in drops), sum(d < 0 for d in drops)
            discordant = losses + wins
            p_value = (sum(math.comb(discordant, i) for i in range(losses, discordant + 1))
                       / 2 ** discordant) if discordant else 1.0
            interval = bootstrap_ci(drops)
            enough = len(drops) >= config["min_cases"]
            regression = bool(enough and interval and interval[0] > threshold["max_drop"]
                              and p_value <= adjusted_alpha)
            comparisons.append({
                "arm": arm, "category": category, "cases": len(drops),
                "drop": sum(drops) / len(drops), "drop_ci95": interval,
                "p_value": p_value, "adjusted_alpha": adjusted_alpha,
                "max_drop": threshold["max_drop"], "regression": regression,
                "status": "regression" if regression else "no_significant_regression"
                if enough else "insufficient_evidence",
            })
    before_summary, after_summary = summarize_arms(previous), summarize_arms(current)
    efficiency: dict[str, Any] = {}
    for arm in arms:
        efficiency[arm] = {}
        for metric in ("cost_per_success_usd", "p95_latency_ms"):
            old, new = before_summary[arm][metric], after_summary[arm][metric]
            efficiency[arm][metric] = {
                "baseline": old, "candidate": new,
                "delta": new - old if old is not None and new is not None else None,
                "relative_change": (new - old) / old if old and new is not None else None,
            }
    regressions = [c for c in comparisons if c["regression"]]
    return {
        "status": "regression" if regressions else "no_significant_regression",
        "regressions": regressions, "comparisons": comparisons, "efficiency": efficiency,
        "baseline_revision": baseline.get("source_revision"),
        "note": "Exact paired sign tests; Bonferroni across arms/categories; "
        "case-cluster bootstrap 95% effect intervals. Cost/latency are diagnostic, not CI gates.",
    }


def gate_markdown(result: dict[str, Any]) -> str:
    failed = result["status"] in {"regression", "invalid_artifact"}
    lines = ["<!-- madrid-eval-gate -->", f"{'🔴' if failed else '🟢'} Evals: {result['status']}",
             "", result.get("note", ""), "",
             "| Arm | Category | Pass-rate drop | 95% CI | p | Result |",
             "| --- | --- | ---: | --- | ---: | --- |"]
    for row in result.get("comparisons", []):
        lines.append(f"| {row['arm']} | {row['category']} | {row['drop']:.3f} | "
                     f"{row['drop_ci95']} | {row['p_value']:.4f} | {row['status']} |")
    if result.get("efficiency"):
        lines.extend(["", "| Arm | Metric | Main | Candidate | Delta |",
                      "| --- | --- | ---: | ---: | ---: |"])
        for arm, metrics in result["efficiency"].items():
            for metric, value in metrics.items():
                lines.append(f"| {arm} | {metric} | {value['baseline']} | "
                             f"{value['candidate']} | {value['delta']} |")
    lines.extend(["", "Offline scripted evidence only; no paid calls or live-model quality claim."])
    return "\n".join(lines) + "\n"

"""Fixed recovery evaluations. Offline by default; --endpoint explicitly enables ADC/network."""

import argparse
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from delivery.cloud_ai import CloudJudge, Judgment  # noqa: E402
from delivery.eval_analytics import export_judge  # noqa: E402
from delivery.scenario_report import EvalAttempt, summarize_arms  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MAX_CASES = 12


def baseline(case: dict[str, Any]) -> str:
    """Mirror the SQL retry/deadline/ceil(seconds/60)<=100 hard gates."""
    facts, candidate = case["facts"], case["candidate"]
    if candidate is None:
        return "deny_retry"
    required = [facts.get(k) for k in ("attempt", "retry_limit", "sim_time", "deadline_sim")]
    required += [
        candidate.get(k) for k in ("estimated_seconds", "remaining_seconds", "route_nodes")
    ]
    if any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
        for v in required
    ):
        return "deny_retry"
    attempt, limit, now, deadline, estimate, remaining, nodes = required
    feasible = (
        1 <= attempt < limit
        and nodes >= 1
        and 0 <= estimate <= 6000
        and estimate <= remaining
        and estimate <= deadline - now
    )
    return "approve_retry" if feasible else "deny_retry"


def evaluate(
    fixture: dict[str, Any],
    judge: Any = None,
    *,
    max_cases: int = 6,
    label: str = "baseline",
    model_version: str = "unspecified",
    pricing: tuple[float, float] | None = None,
) -> dict[str, Any]:
    if not 1 <= max_cases <= MAX_CASES:
        raise ValueError("max_cases must be between 1 and 12")
    if pricing is not None and any(not math.isfinite(p) or p < 0 for p in pricing):
        raise ValueError("Pricing must be finite and nonnegative")
    rows = []
    for case in fixture["cases"][:max_cases]:
        oracle = baseline(case)
        if oracle != case["expected_decision"]:
            raise ValueError(f"Fixture oracle mismatch: {case['id']}")
        started = time.perf_counter()
        row: dict[str, Any] = {
            "case_id": case["id"],
            "expected_decision": oracle,
            "actual_decision": None,
            "status": "ok",
            "input_tokens": 0,
            "output_tokens": 0,
        }
        try:
            result = (
                judge.review({"job": case["facts"]}, [], candidate=case["candidate"])
                if judge is not None
                else Judgment(
                    decision=oracle,
                    reason="Deterministic SQL policy baseline",
                    model="local-rules-v1",
                    source="policy_gate",
                    input_tokens=0,
                    output_tokens=0,
                )
            )
            result = Judgment.model_validate(result)
            row.update(result.model_dump())
            row["actual_decision"] = row.pop("decision")
        except (ValidationError, ValueError) as exc:
            row.update(status="schema_failure", error_type=type(exc).__name__)
        except Exception as exc:
            row.update(status="provider_error", error_type=type(exc).__name__)
        row["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        row["passed"] = row["status"] == "ok" and row["actual_decision"] == oracle
        row["hard_policy_violation"] = (
            oracle == "deny_retry" and row["actual_decision"] == "approve_retry"
        )
        rows.append(row)
    successful = [r for r in rows if r["status"] == "ok"]
    input_tokens = sum(r["input_tokens"] for r in rows)
    output_tokens = sum(r["output_tokens"] for r in rows)
    summary = {
        "cases": len(rows),
        "model_decisions": sum(r.get("source") == "model" and r["status"] == "ok" for r in rows),
        "policy_gate_decisions": sum(r.get("source") == "policy_gate" for r in rows),
        "passed": sum(r["passed"] for r in rows),
        "approval_agreement": (
            sum(r["passed"] for r in successful) / len(successful) if successful else None
        ),
        "hard_policy_violations": sum(r["hard_policy_violation"] for r in rows),
        "schema_failures": sum(r["status"] == "schema_failure" for r in rows),
        "provider_errors": sum(r["status"] == "provider_error" for r in rows),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_latency_ms": round(sum(r["latency_ms"] for r in rows), 3),
    }
    report = {
        "fixture_version": fixture["version"],
        "seed": fixture["seed"],
        "created_at": datetime.now(UTC).isoformat(),
        "label": label,
        "model_version": model_version,
        "mode": "cloud" if judge else "offline-baseline",
        "summary": summary,
        "results": rows,
        "usage_note": (
            "Tokens cover successful responses only; failed calls may incur unreported usage."
        ),
    }
    if pricing is not None:
        report["pricing_usd_per_million"] = {"input": pricing[0], "output": pricing[1]}
        report["estimated_cost_usd"] = (
            input_tokens * pricing[0] + output_tokens * pricing[1]
        ) / 1_000_000
    attempts = [EvalAttempt(
        arm=label, case_id=row["case_id"], repetition=1, passed=row["passed"],
        categories={"schema": row["status"] != "schema_failure", "task": row["passed"]},
        latency_ms=float(row["latency_ms"]),
        cost_usd=(0.0 if judge is None else
                  (row["input_tokens"] * pricing[0] + row["output_tokens"] * pricing[1])
                  / 1_000_000 if pricing and row["status"] == "ok" else None),
        error=row.get("error_type"),
    ) for row in rows]
    report["arms"] = summarize_arms(attempts)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", help="Explicit opt-in to authenticated Cloud Run calls")
    parser.add_argument("--fixture", type=Path, default=ROOT / "data/evals/recovery-judge.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/cloud-judge-eval.json")
    parser.add_argument("--max-cases", type=int, default=6)
    parser.add_argument("--label", default="recovery-eval")
    parser.add_argument("--model-version", default="unspecified")
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    args = parser.parse_args()
    if not 1 <= args.max_cases <= MAX_CASES:
        parser.error("--max-cases must be between 1 and 12")
    prices = (args.input_usd_per_million, args.output_usd_per_million)
    if (prices[0] is None) != (prices[1] is None):
        parser.error("Supply both pricing rates or neither")
    if prices[0] is not None and any(not math.isfinite(p) or p < 0 for p in prices):
        parser.error("Pricing must be finite and nonnegative")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8-sig"))
    judge = CloudJudge(args.endpoint) if args.endpoint else None
    report = evaluate(
        fixture,
        judge,
        max_cases=args.max_cases,
        label=args.label,
        model_version=args.model_version,
        pricing=prices if prices[0] is not None else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    export_judge(report)
    print(json.dumps(report["summary"]))
    return 0 if report["summary"]["passed"] == report["summary"]["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

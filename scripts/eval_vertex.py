"""Manual-only pointwise evaluation of existing synthetic customer replies; no generation."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delivery.cloud_ai import EvalCostCaps, VertexPointwiseJudge  # noqa: E402
from delivery.health_report import atomic_write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true")
    parser.add_argument("--project", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-cases", type=int, choices=range(1, 13), default=3)
    parser.add_argument("--max-usd", type=float, default=.05)
    parser.add_argument("--fixture", type=Path,
                        default=ROOT / "data/evals/customer-replies.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/evals/vertex.json")
    args = parser.parse_args()
    if not args.paid:
        parser.error("--paid is required; this command is never a CI dependency")
    caps = EvalCostCaps(ROOT / "artifacts/evals/vertex-ledger.sqlite", args.run_id,
                       max_calls=args.max_cases, max_usd=args.max_usd)
    judge = VertexPointwiseJudge(args.project, caps, paid=args.paid)
    rows = []
    for case in json.loads(args.fixture.read_text())["cases"][:args.max_cases]:
        started = time.perf_counter()
        try:
            result = judge.review(case)
        except Exception as exc:
            result = {"error": type(exc).__name__, "judgment": None, "cost_usd": None}
        rows.append({"id": case["id"], **result,
                     "latency_ms": (time.perf_counter() - started) * 1000})
        atomic_write_json(args.output, {
            "kind": "vertex-pointwise", "run_id": args.run_id, "rows": rows,
            "note": "Conservative ledger charges include uncertain calls; invoices/usage unknown.",
        })
        if "error" in result:
            break
    return int(not rows or any(r.get("judgment", {}).get("score") != 1
                               if r.get("judgment") else True for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())

"""Compare a candidate receipt with an immutable main artifact, never a PR-supplied baseline."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delivery.eval_gate import compare_reports, gate_markdown, load_thresholds  # noqa: E402
from delivery.health_report import atomic_write_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-revision")
    parser.add_argument("--thresholds", type=Path, default=ROOT / "config/eval-gate.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/evals/gate.json")
    args = parser.parse_args()
    try:
        baseline = json.loads(args.baseline.read_text()) if args.baseline else None
        if baseline and baseline.get("source_revision") != args.baseline_revision:
            raise ValueError("Baseline artifact revision does not match its trusted main run")
        result = compare_reports(baseline, json.loads(args.candidate.read_text()),
                                 load_thresholds(args.thresholds))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result = {"status": "invalid_artifact", "note": str(exc), "regressions": []}
    atomic_write_json(args.output, result)
    args.output.with_suffix(".md").write_text(gate_markdown(result), encoding="utf-8")
    print(result["status"])
    return 2 if result["status"] == "invalid_artifact" else int(result["status"] == "regression")


if __name__ == "__main__":
    raise SystemExit(main())

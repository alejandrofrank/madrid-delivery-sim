"""Run the reserved release cohort and compare with a trusted prior release receipt."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delivery.eval_gate import load_thresholds  # noqa: E402
from delivery.health_report import atomic_write_json, utc_now  # noqa: E402
from delivery.model_evals import evaluate_model_arms  # noqa: E402
from delivery.release_gate import compare_release, results_table  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--baseline-revision")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/release")
    parser.add_argument("--update-readme", action="store_true")
    options = parser.parse_args()
    if not 2 <= options.k <= 100:
        parser.error("k must be between 2 and 100")
    os.environ.update(LLM_PROVIDER="disabled", DELIVERY_ADK_VERTEX_ENABLED="0",
                      MDS_TELEMETRY_ENABLED="0", MDS_BIGQUERY_ENABLED="0")
    report = asyncio.run(evaluate_model_arms(options.k, split="heldout"))
    report["source_revision"] = os.environ.get("DELIVERY_SOURCE_REVISION") or (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    )
    report["created_at"] = utc_now()
    atomic_write_json(options.output / "candidate.json", report)
    baseline = json.loads(options.baseline.read_text()) if options.baseline else None
    if baseline and baseline.get("source_revision") != options.baseline_revision:
        raise ValueError("Baseline must match the trusted release workflow revision")
    result = compare_release(baseline, report, load_thresholds())
    atomic_write_json(options.output / "gate.json", result)
    table = results_table(report)
    (options.output / "results.md").write_text(table, encoding="utf-8")
    if options.update_readme:
        readme = ROOT / "README.md"
        start, end = "<!-- release-results:start -->", "<!-- release-results:end -->"
        text = readme.read_text(encoding="utf-8")
        if start not in text or end not in text:
            text += f"\n## Held-out release results\n\n{start}\n{end}\n"
        before, remainder = text.split(start, 1)
        _, after = remainder.split(end, 1)
        readme.write_text(before + start + "\n" + table + end + after, encoding="utf-8")
    print(result["status"])
    return int(result["status"] == "regression")


if __name__ == "__main__":
    raise SystemExit(main())

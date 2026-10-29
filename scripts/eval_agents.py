"""Evaluate role scenarios locally; no cloud endpoint or provider option exists."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delivery.health_report import atomic_write_json, source_fingerprint, utc_now  # noqa: E402
from delivery.scenario_evals import evaluate, require_local_test_database  # noqa: E402
from delivery.scenario_report import (  # noqa: E402
    digest,
    load_manifest,
    outcome_hash,
    summarize,
    validate_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1, help="Fresh attempts per model case only")
    parser.add_argument("--reproduce", type=int, choices=(1, 2, 3), default=2)
    parser.add_argument("--suite", choices=("scenarios", "adk", "all"), default="scenarios")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/evals/candidate.json")
    parser.add_argument("--baseline", type=Path)
    options = parser.parse_args()
    if not 1 <= options.repeat <= 100:
        parser.error("--repeat must be between 1 and 100")
    model_failed = False
    if options.suite in {"adk", "all"}:
        from delivery.model_evals import evaluate_model_arms

        report = asyncio.run(evaluate_model_arms(options.repeat))
        revision = os.environ.get("DELIVERY_SOURCE_REVISION")
        if not revision:
            try:
                revision = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip()
            except (OSError, subprocess.CalledProcessError):
                revision = "unversioned-local-run"
        report["source_revision"] = revision
        if options.baseline:
            from delivery.eval_gate import compare_reports, load_thresholds

            report["comparison"] = compare_reports(
                json.loads(options.baseline.read_text()), report, load_thresholds()
            )
        atomic_write_json(options.output, report)
        model_failed = any(not r["passed"] for r in report["rows"] + report["golden"])
        print(json.dumps(report["arms"], indent=2))
        if options.suite == "adk":
            return int(model_failed)
    url = os.environ.get("TEST_DATABASE_URL", "")
    try:
        require_local_test_database(url)
    except ValueError:
        print("Set TEST_DATABASE_URL to the dedicated local delivery_test database.")
        return 2
    os.environ["DATABASE_URL"] = url
    os.environ["LLM_PROVIDER"] = "disabled"
    from delivery.config import settings

    settings.cache_clear()
    fingerprint = source_fingerprint(ROOT)
    manifest = load_manifest()
    # Serialize evaluations against this database (including the real race within a fixture).
    # A second invocation must not interleave role provisioning/retirement with the first.
    from delivery.db import connect

    with connect(url) as lock:
        lock.execute("SELECT pg_advisory_lock(918275)")
        report = {
            "schema_version": 1,
            "kind": "agent-scenarios",
            "mode": "local-deterministic",
            "version": manifest.version,
            "seed": manifest.seed,
            "fixture_hash": digest(manifest.model_dump(mode="json")),
            "source_fingerprint": fingerprint,
            "created_at": utc_now(),
            "configurations": {
                case.fixture: digest({"fixture": case.fixture, "seed": manifest.seed})
                for case in manifest.cases
            },
            "results": [],
            "reproduction": {"repetitions": 1, "hashes": [outcome_hash([])]},
            "source_changed": False,
        }
        # Clear any previous green headline before doing work. If this checker is
        # interrupted, an empty receipt remains unmeasured rather than silently old-green.
        atomic_write_json(ROOT / "artifacts/health/latest-scenarios.json", report)
        report.update(
            **evaluate(manifest, url, options.reproduce),
            created_at=utc_now(),
            source_changed=source_fingerprint(ROOT) != fingerprint,
        )
        receipt = validate_receipt(report, manifest)
        result = summarize(manifest, receipt)
        atomic_write_json(ROOT / "artifacts/health/latest-scenarios.json", report)
    for role in result["roles"]:
        print(
            f"{role['name']}: {role['score']}% · "
            f"{role['counts']['passed']}/{role['counts']['total']} scenarios passed"
        )
    print(f"Repeated business outcomes match: {result['reproduction']['matched']}")
    return int(model_failed or result["status"] != "passed" or report["source_changed"])


if __name__ == "__main__":
    raise SystemExit(main())

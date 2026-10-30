"""Collect recovery metrics over A2A; the existing evaluation gate checks this receipt."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from delivery.chaos_evals import MANIFEST, evaluate_chaos, validate_chaos_report  # noqa: E402
from delivery.health_report import atomic_write_json  # noqa: E402


def main() -> int:
    os.environ["DELIVERY_CHAOS_PROVIDER"] = "offline"
    os.environ["LLM_PROVIDER"] = "disabled"
    manifest = json.loads(MANIFEST.read_text())
    path = ROOT / "artifacts/evals/chaos.json"
    atomic_write_json(path, {"state": "running"})
    report = evaluate_chaos(os.environ.get("TEST_DATABASE_URL", ""), manifest)
    atomic_write_json(path, report)
    passed = validate_chaos_report(report, manifest)
    print(f"Chaos recovery, policy and seeded replay: {'passed' if passed else 'failed'}")
    return int(not passed)


if __name__ == "__main__":
    raise SystemExit(main())

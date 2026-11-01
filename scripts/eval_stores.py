"""Run bounded, deterministic physical store recovery in the release gate."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delivery.db import migrate  # noqa: E402
from delivery.health_report import atomic_write_json  # noqa: E402
from delivery.scenario_evals import require_local_test_database  # noqa: E402
from delivery.simulation import initialize  # noqa: E402
from delivery.store_evals import evaluate, validate  # noqa: E402

if __name__ == "__main__":
    url = os.environ.get("TEST_DATABASE_URL", "")
    require_local_test_database(url)
    migrate(url)
    initialize(url)
    report = evaluate(url)
    atomic_write_json(ROOT / "artifacts/evals/stores.json", report)
    ok = validate(report)
    print("Store recovery, stock conservation and replay: " + ("passed" if ok else "FAILED"))
    raise SystemExit(0 if ok else 1)

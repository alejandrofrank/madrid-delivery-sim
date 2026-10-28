"""Run the fixed local health checks and offline evaluation; never call a model."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from delivery.health_report import atomic_write_json, source_fingerprint, utc_now  # noqa: E402

REPORT_DIRECTORY = ROOT / "artifacts/health"


def local_environment() -> dict[str, str]:
    test_url = os.environ.get("TEST_DATABASE_URL", "")
    try:
        parsed = urlsplit(test_url)
        valid = parsed.scheme in {"postgres", "postgresql"} and parsed.path == "/delivery_test"
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Health checks require the dedicated delivery_test database")
    return {
        **os.environ,
        "DATABASE_URL": test_url,
        "LLM_PROVIDER": "disabled",
        "DELIVERY_ADK_VERTEX_ENABLED": "0",
        "DELIVERY_ADK_VERTEX_PROFILE": "",
        "PYTEST_ADDOPTS": "",
    }


def run_check(
    identifier: str,
    label: str,
    command: list[str],
    environment: dict[str, str],
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=ROOT, env=environment, check=False)
        exit_code = result.returncode
        status = "passed" if exit_code == 0 else "failed"
    except OSError:
        exit_code, status = None, "unavailable"
    return {
        "id": identifier,
        "label": label,
        "status": status,
        "duration_seconds": round(time.perf_counter() - started, 6),
        "exit_code": exit_code,
    }


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    fingerprint = source_fingerprint(ROOT)
    try:
        environment = local_environment()
    except ValueError:
        atomic_write_json(
            REPORT_DIRECTORY / "latest-checks.json",
            {
                "schema_version": 1,
                "kind": "checks",
                "source_fingerprint": fingerprint,
                "created_at": utc_now(),
                "source_changed": False,
                "checks": [
                    {
                        "id": "database-scope",
                        "label": "Dedicated test database required",
                        "status": "failed",
                        "duration_seconds": 0,
                        "exit_code": 2,
                    }
                ],
            },
        )
        print("Health checks require TEST_DATABASE_URL ending in /delivery_test.")
        return 2
    checks: list[dict[str, Any]] = []

    def publish() -> None:
        atomic_write_json(
            REPORT_DIRECTORY / "latest-checks.json",
            {
                "schema_version": 1,
                "kind": "checks",
                "source_fingerprint": fingerprint,
                "created_at": utc_now(),
                "checks": checks,
                "source_changed": source_fingerprint(ROOT) != fingerprint,
            },
        )

    commands = [
        (
            "pytest",
            "Full test suite",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "-p",
                "delivery.health_report",
                "--health-report=artifacts/health",
                "-o",
                "cache_dir=/tmp/pytest-cache",
            ],
        ),
        (
            "ruff",
            "Ruff",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "src",
                "tests",
                "scripts/health_check.py",
                "scripts/eval_agents.py",
            ],
        ),
        ("mypy", "Mypy", [sys.executable, "-m", "mypy", "src"]),
        (
            "agent-scenarios",
            "Local role scenarios · two reproducibility runs",
            [sys.executable, str(ROOT / "scripts/eval_agents.py")],
        ),
    ]
    for identifier, label, command in commands:
        checks.append(run_check(identifier, label, command, environment))
        publish()
    node = shutil.which("node")
    if node is None:
        checks.append(
            {
                "id": "javascript",
                "label": "JavaScript syntax",
                "status": "unavailable",
                "duration_seconds": 0.0,
                "exit_code": None,
            }
        )
    else:
        for path in sorted((ROOT / "web").glob("*.js")):
            checks.append(
                run_check(
                    f"javascript:{path.name}",
                    f"JavaScript syntax: {path.name}",
                    [node, "--check", str(path)],
                    environment,
                )
            )
    publish()
    # The existing CLI is offline unless --endpoint is supplied. Never supply it here.
    with tempfile.TemporaryDirectory(prefix="delivery-health-evals-") as directory:
        output = Path(directory) / "evals.json"
        checks.append(
            run_check(
                "evals",
                "Offline recovery baseline",
                [
                    sys.executable,
                    str(ROOT / "scripts/eval_cloud_judge.py"),
                    "--output",
                    str(output),
                ],
                environment,
            )
        )
        try:
            report = json.loads(output.read_text(encoding="utf-8"))
            if not isinstance(report, dict) or report.get("mode") != "offline-baseline":
                raise ValueError("Missing offline evaluation evidence")
        except (OSError, ValueError):
            checks[-1].update(status="failed", exit_code=checks[-1]["exit_code"] or 1)
        else:
            atomic_write_json(
                REPORT_DIRECTORY / "latest-evals.json",
                {
                    "schema_version": 1,
                    "kind": "evals",
                    "source_fingerprint": fingerprint,
                    "created_at": utc_now(),
                    "report": report,
                    "source_changed": source_fingerprint(ROOT) != fingerprint,
                },
            )
    publish()
    return int(
        source_fingerprint(ROOT) != fingerprint
        or any(
            check["status"] == "failed"
            or (check["status"] == "unavailable" and check["id"] != "javascript")
            for check in checks
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

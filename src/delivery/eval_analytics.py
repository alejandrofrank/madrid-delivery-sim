"""Export measured eval attempts without changing their local verdict or cloud policy."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from typing import Any, Protocol

from delivery.scenario_report import Manifest, Receipt

logger = logging.getLogger(__name__)


class EvaluationWriter(Protocol):
    def enqueue(
        self, table: str, row: Mapping[str, Any], *, event_id: str | None = None
    ) -> bool: ...

    def flush(self, timeout: float = 10) -> bool: ...


def _identity(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _publish(rows: list[dict[str, Any]], writer: EvaluationWriter | None) -> int:
    # Telemetry failure must not turn a failing evaluation green or fail a healthy task.
    try:
        if writer is None:
            from delivery.analytics import get_writer

            writer = get_writer()
        accepted = sum(writer.enqueue("eval_runs", row) for row in rows)
        if accepted and not writer.flush(timeout=5):
            logger.warning("eval_analytics_flush_incomplete")
        return accepted
    except Exception:
        logger.warning("eval_analytics_export_failed")
        return 0


def export_scenarios(
    manifest: Manifest, receipt: Receipt, *, writer: EvaluationWriter | None = None
) -> int:
    """One row per expected case and attempt; omissions explicitly count as failures.

    These repeats are deterministic reproductions. The mode stays explicit so an
    analyst cannot silently combine them with independent LLM reliability trials.
    """
    run_id = _identity(
        receipt.created_at.isoformat(), receipt.source_fingerprint, receipt.fixture_hash
    )
    rows = []
    attempts = [*receipt.reproduction.previous_results, receipt.results]
    configurations = [*receipt.reproduction.previous_configurations, receipt.configurations]
    inputs_changed = any(config != configurations[0] for config in configurations[1:])
    for repetition, outcomes in enumerate(attempts, 1):
        by_id = {outcome.id: outcome for outcome in outcomes}
        for case in manifest.cases:
            outcome = by_id.get(case.id)
            passed = bool(
                outcome
                and not outcome.error
                and not receipt.source_changed
                and not inputs_changed
                and all(
                    type(outcome.observed.get(check.id)) is type(check.expected)
                    and outcome.observed.get(check.id) == check.expected
                    for check in case.checks
                )
            )
            category = (
                "source_changed"
                if receipt.source_changed
                else "input_changed"
                if inputs_changed
                else "missing"
                if outcome is None
                else outcome.error or "criteria"
            )
            rows.append(
                {
                    "event_id": _identity(run_id, case.id, repetition),
                    "observed_at": receipt.created_at.isoformat(),
                    "agent": case.role,
                    "run_id": run_id,
                    "case_id": case.id,
                    "arm": "rules",
                    "category": category,
                    "repetition": repetition,
                    "repeat_k": receipt.reproduction.repetitions,
                    "passed": passed,
                    "cost_usd": 0.0,
                    "mode": receipt.mode,
                    "fixture_version": receipt.version,
                    "source_revision": receipt.source_fingerprint,
                }
            )
    return _publish(rows, writer)


def export_judge(
    report: Mapping[str, Any], *, writer: EvaluationWriter | None = None
) -> int:
    """Export the fixed judge's measured attempts, excluding reply text and reasons."""
    run_id = _identity(
        report["created_at"], report["fixture_version"], report["label"], report["model_version"]
    )
    prices = report.get("pricing_usd_per_million")
    rows = []
    for result in report["results"]:
        cost = None
        if report["mode"] == "offline-baseline":
            cost = 0.0
        elif prices and result["status"] == "ok":
            cost = (
                result["input_tokens"] * prices["input"]
                + result["output_tokens"] * prices["output"]
            ) / 1_000_000
        rows.append(
            {
                "event_id": _identity(run_id, result["case_id"]),
                "observed_at": report["created_at"],
                "agent": "judge",
                "run_id": run_id,
                "case_id": result["case_id"],
                "arm": report["model_version"],
                "category": "hard_policy_violation"
                if result["hard_policy_violation"]
                else "decision"
                if result["status"] == "ok"
                else result["status"],
                "repetition": 1,
                "repeat_k": 1,
                "passed": result["passed"],
                "latency_ms": result["latency_ms"],
                "cost_usd": cost,
                "mode": report["mode"],
                "fixture_version": report["fixture_version"],
            }
        )
    return _publish(rows, writer)


def export_model_report(
    report: Mapping[str, Any], *, writer: EvaluationWriter | None = None
) -> int:
    """Export one measured row per model attempt, preserving incomplete repeats.

    Golden assertions describe stored regressions rather than fresh model calls,
    so they stay in the local report. Category is a diagnostic label; creating a
    row per category would multiply task counts, cost and latency observations.
    """
    run_id = _identity(
        report["created_at"], report["source_revision"], report["fixture_hashes"],
        report["mode"], report["repeat"],
    )
    agents = {
        "adk-offline-restaurant": "restaurant",
        "adk-offline-customer": "customer_service",
    }
    rows = []
    for result in report["rows"]:
        categories = result["categories"]
        failed = sorted(category for category, passed in categories.items() if not passed)
        passed = result["passed"] is True and bool(categories) and not failed
        rows.append(
            {
                "event_id": _identity(
                    run_id, result["arm"], result["case_id"], result["repetition"]
                ),
                "observed_at": report["created_at"],
                "agent": agents.get(result["arm"], "unknown"),
                "run_id": run_id,
                "case_id": result["case_id"],
                "arm": result["arm"],
                "category": failed[0] if failed else "task",
                "repetition": result["repetition"],
                "repeat_k": report["repeat"],
                "passed": passed,
                "latency_ms": result["latency_ms"],
                "cost_usd": result.get("cost_usd"),
                "mode": report["mode"],
                "fixture_version": report["fixture_hashes"][result["arm"]],
                "source_revision": report["source_revision"],
            }
        )
    return _publish(rows, writer)

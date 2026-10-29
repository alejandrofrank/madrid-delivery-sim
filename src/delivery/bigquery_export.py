"""Artifact-first analytics export. Preparing a bundle never authenticates or uses a network."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

MAX_SOURCE_BYTES = 32 * 1024 * 1024
MAX_EXPORT_BYTES = 1024 * 1024
MAX_RUNS = 100
TABLES = ("run_receipts", "run_kpis")
KPI_NAMES = frozenset(
    "delivered scheduled_calls events dead_letters retries unfinished_orders open_delivery_jobs "
    "late_physical_deliveries model_calls adk_offline_calls adk_vertex_dispatches adk_reserved_usd "
    "adk_reserved_tokens adk_paid_calls search_reserved_calls search_reserved_input_tokens "
    "search_unknown_usage_calls search_actual_input_tokens search_actual_output_tokens "
    "jev_router_dispatches jev_direct_decisions jev_gemini_escalations jev_no_model_steps "
    "jev_router_unknown_usage_calls jev_router_input_tokens jev_router_reserved_usd "
    "communication_latency_seconds orders on_time on_time_pct delivery_cost_eur "
    "cost_per_delivery_eur active unserved pending overdue llm_calls llm_tokens "
    "llm_cost_usd llm_reserved_usd llm_reserved_tokens".split()
)
BASELINE_USAGE = frozenset(
    "llm_calls llm_tokens llm_cost_usd llm_reserved_usd llm_reserved_tokens".split()
)


def _json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean is not a numeric KPI")
    result = float(value)
    if not math.isfinite(result) or abs(result) > 1e15:
        raise ValueError("KPI must be a finite, bounded number")
    return result


def _label(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_. -]{1,100}", value):
        raise ValueError("Receipt labels must be short plain identifiers")
    return value


def _timestamp(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Receipt created_at must be a timestamp with a timezone")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Receipt timestamps require a timezone")
    return result.astimezone(UTC).isoformat()


def receipt_rows(
    receipt: dict[str, Any], source_sha256: str, exported_at: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Allowlist metadata and numeric KPIs; never export raw prompts, configs or evidence."""
    entries = receipt.get("profiles", receipt.get("arms", [receipt]))
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_RUNS:
        raise ValueError(f"Expected 1..{MAX_RUNS} run entries")
    receipts, kpis = [], []
    seen: set[str] = set()
    fingerprint = receipt.get("source_fingerprint")
    if fingerprint is not None and not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise ValueError("source_fingerprint must be a SHA-256 digest")
    for entry in entries:
        run = entry["run"] if isinstance(entry["run"], dict) else {}
        run_id = str(UUID(str(run.get("id", entry["run"]))))
        created_at = _timestamp(run.get("created_at", receipt.get("created_at")))
        if run_id in seen:
            raise ValueError("Duplicate run in receipt")
        seen.add(run_id)
        common = {
            "run_id": run_id,
            "receipt_sha256": source_sha256,
            "run_created_at": created_at,
            "exported_at": exported_at,
        }
        invariants = entry.get("invariants", {})
        checks = entry.get("outcome_checks", invariants)
        if not isinstance(checks, dict) or any(
            type(value) is not bool for value in checks.values()
        ):
            raise ValueError("Outcome checks must contain boolean results")
        metrics = entry.get("metrics", {})
        if not isinstance(metrics, dict):
            raise ValueError("Run metrics must be an object")
        metrics = {**metrics, **{name: run[name] for name in BASELINE_USAGE.intersection(run)}}
        cost = entry.get("cost", {})
        if not isinstance(cost, dict):
            raise ValueError("Run cost must be an object")
        unknown_number = _number(cost.get("unknown_calls"))
        if unknown_number is not None and (unknown_number < 0 or not unknown_number.is_integer()):
            raise ValueError("Unknown usage calls must be a nonnegative integer")
        unknown = int(unknown_number) if unknown_number is not None else None
        # A partial measured sum is not a completed cost result. Zero is only explicit.
        known_cost = _number(cost.get("total_usd")) if unknown == 0 else None
        reserved_cost = _number(cost.get("admission_usd"))
        if receipt.get("paid_calls") == 0 and cost == {}:
            known_cost = 0.0
        if run and cost == {}:
            reserved_cost = _number(run.get("llm_reserved_usd"))
            calls = _number(run.get("llm_calls"))
            if calls is not None and (calls < 0 or not calls.is_integer()):
                raise ValueError("Model calls must be a nonnegative integer")
            # Baseline aggregates do not prove every admitted call returned usage.
            # Retain the observed cost as a KPI, but only claim a complete zero
            # total when the receipt explicitly proves there were no model calls.
            if calls == 0:
                if _number(run.get("llm_cost_usd")) not in (None, 0.0):
                    raise ValueError("Zero model calls cannot have nonzero model usage cost")
                known_cost = 0.0
                unknown = 0
        replay = entry.get("replay_matches")
        if replay is not None and type(replay) is not bool:
            raise ValueError("replay_matches must be a boolean")
        receipts.append(
            {
                **common,
                "source_fingerprint": fingerprint,
                "profile": _label(entry.get("profile", entry.get("soul"))),
                "scenario": _label(entry.get("scenario")),
                "variant": _label(entry.get("variant")),
                "status": _label(entry.get("status", run.get("status", "recorded"))),
                "replay_matches": replay,
                "checks_passed": sum(checks.values()),
                "checks_total": len(checks),
                "usage_cost_usd": known_cost,
                "reserved_cost_usd": reserved_cost,
                "unknown_usage_calls": unknown,
            }
        )
        for name in sorted(KPI_NAMES.intersection(metrics)):
            value = _number(metrics[name])
            if value is not None:
                kpis.append({**common, "metric_name": name, "metric_value": value})
    return receipts, kpis


def prepare_bundle(source: Path, output: Path) -> dict[str, Any]:
    """Write a new, inspectable bundle; source receipts and existing bundles are immutable."""
    if output.exists():
        raise FileExistsError("Choose a new output directory; upload the existing bundle to retry")
    with source.open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Source receipt exceeds 32 MiB")
    exported_at = datetime.now(UTC).isoformat()
    receipts, kpis = receipt_rows(json.loads(raw), hashlib.sha256(raw).hexdigest(), exported_at)
    content = {
        "run_receipts": b"".join(_json(row) for row in receipts),
        "run_kpis": b"".join(_json(row) for row in kpis),
    }
    if sum(map(len, content.values())) > MAX_EXPORT_BYTES:
        raise ValueError("Export exceeds the 1 MiB per-bundle cap")
    manifest = {
        "schema_version": 1,
        "exported_at": exported_at,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "tables": {
            name: {
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
                "rows": len(data.splitlines()),
            }
            for name, data in content.items()
        },
    }
    output.mkdir(parents=True)
    for name, data in content.items():
        (output / f"{name}.ndjson").write_bytes(data)
    (output / "manifest.json").write_bytes(_json(manifest))
    return manifest


class LoadClient(Protocol):
    def load(self, data: bytes, table: str, job_id: str, location: str) -> int: ...


class BigQueryLoadClient:
    def __init__(self, project: str, service_account: str) -> None:
        import google.auth
        from google.auth import impersonated_credentials
        from google.cloud import bigquery

        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        source, _ = google.auth.default(scopes=scopes, quota_project_id=project)
        credentials = impersonated_credentials.Credentials(
            source_credentials=source,
            target_principal=service_account,
            target_scopes=scopes,
            lifetime=300,
        )
        self.client = bigquery.Client(project=project, credentials=credentials)

    def load(self, data: bytes, table: str, job_id: str, location: str) -> int:
        from google.api_core.exceptions import Conflict
        from google.cloud import bigquery

        config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
            autodetect=False,
            max_bad_records=0,
            ignore_unknown_values=False,
        )
        try:
            job = self.client.load_table_from_file(
                io.BytesIO(data),
                table,
                job_id=job_id,
                location=location,
                size=len(data),
                job_config=config,
                num_retries=2,
                timeout=30,
            )
        except Conflict:
            # Same destination + frozen bytes means the same job. Never append a retry twice.
            existing = self.client.get_job(job_id, location=location, timeout=30)
            if not isinstance(existing, bigquery.LoadJob) or str(existing.destination) != table:
                raise RuntimeError("Existing job does not match the requested load") from None
            job = existing
        job.result(timeout=60)
        if job.output_rows is None:
            raise RuntimeError("BigQuery load did not report a row count")
        return int(job.output_rows)


def upload_bundle(
    bundle: Path,
    *,
    project: str,
    dataset: str = "delivery_analytics",
    location: str = "EU",
    service_account: str,
    confirm_upload: bool = False,
) -> dict[str, Any]:
    """Only the explicit upload command can cross the cloud boundary. No queries are run."""
    if not confirm_upload or os.environ.get("DELIVERY_BIGQUERY_ENABLED") != "1":
        raise PermissionError("Upload requires --confirm-upload and DELIVERY_BIGQUERY_ENABLED=1")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        raise ValueError("Invalid project ID")
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,100}", dataset):
        raise ValueError("Invalid dataset ID")
    if not re.fullmatch(r"[a-zA-Z0-9-]{2,30}", location):
        raise ValueError("Invalid BigQuery location")
    if service_account != f"delivery-analytics@{project}.iam.gserviceaccount.com":
        raise ValueError("Use the dedicated Terraform delivery-analytics service account")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or set(manifest.get("tables", {})) != set(TABLES):
        raise ValueError("Invalid bundle manifest")
    payloads = {}
    for name in TABLES:
        with (bundle / f"{name}.ndjson").open("rb") as stream:
            data = stream.read(MAX_EXPORT_BYTES + 1)
        declared = manifest["tables"][name]
        if declared != {
            "bytes": len(data),
            "rows": len(data.splitlines()),
            "sha256": hashlib.sha256(data).hexdigest(),
        }:
            raise ValueError("Bundle content differs from its reviewed manifest")
        payloads[name] = data
    if sum(map(len, payloads.values())) > MAX_EXPORT_BYTES:
        raise ValueError("Export exceeds the 1 MiB per-bundle cap")
    if not 1 <= manifest["tables"]["run_receipts"]["rows"] <= MAX_RUNS:
        raise ValueError("Bundle exceeds the run limit")
    client: LoadClient = BigQueryLoadClient(project, service_account)
    result: dict[str, Any] = {"project": project, "dataset": dataset, "jobs": {}}
    for name, data in payloads.items():
        if not data:
            continue
        table = f"{project}.{dataset}.{name}"
        digest = hashlib.sha256(table.encode() + b"\n" + data).hexdigest()
        job_id = f"delivery_{name}_{digest}"
        rows = client.load(data, table, job_id, location)
        if rows != manifest["tables"][name]["rows"]:
            raise RuntimeError("Loaded row count does not match the bundle")
        result["jobs"][name] = {"job_id": job_id, "rows": rows}
    return result

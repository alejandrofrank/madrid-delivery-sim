"""Read-only local operator health: measured evidence, never inferred green checks."""

import json
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID

import redis
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, BaseModel, Field, ValidationError, model_validator

from delivery.config import settings
from delivery.db import connect
from delivery.health_report import source_fingerprint

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "artifacts/health"
Status = Literal["passed", "failed", "skipped", "xfailed", "xpassed", "not_run"]
router = APIRouter()


class Case(BaseModel):
    id: str = Field(max_length=1500)
    file: str = Field(max_length=300)
    line: int = Field(ge=1)
    name: str = Field(max_length=1000)
    description: str = Field(max_length=4000)
    markers: list[str]
    status: Status
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    failure_phase: Literal["setup", "call", "teardown"] | None = None

    @model_validator(mode="after")
    def relative_test_path(self) -> "Case":
        path = PurePosixPath(self.file)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not self.file.startswith("tests/")
            or not self.file.endswith(".py")
            or not self.id.startswith(self.file + "::")
        ):
            raise ValueError("Invalid test source")
        if self.status == "passed" and self.failure_phase is not None:
            raise ValueError("Passing case has a failed phase")
        return self


class TestRun(BaseModel):
    schema_version: Literal[1]
    id: UUID
    kind: Literal["tests"]
    state: Literal["running", "completed"]
    started_at: AwareDatetime
    completed_at: AwareDatetime | None
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    exit_code: int | None
    scope: Literal["full", "partial", "collection"]
    source_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    source_revision: str | None = Field(
        default=None, pattern="^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$"
    )
    source_changed: bool
    collection_errors: int = Field(ge=0)
    tests: list[Case] = Field(max_length=10000)

    @model_validator(mode="after")
    def consistent_run(self) -> "TestRun":
        if len({case.id for case in self.tests}) != len(self.tests):
            raise ValueError("Duplicate test case IDs")
        if self.state == "completed" and (self.completed_at is None or self.exit_code is None):
            raise ValueError("Incomplete completion receipt")
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("Completion precedes start")
        return self


def read_json(path: Path) -> Any:
    if path.is_symlink() or path.stat().st_size > 5 * 1024 * 1024:
        raise ValueError("Report exceeds local evidence bound")
    return json.loads(path.read_text(encoding="utf-8"))


def freshness(stamp: datetime, fingerprint: str, current: str, changed: bool = False) -> str:
    age = datetime.now(UTC) - stamp
    if changed or fingerprint != current:
        return "outdated"
    if age < timedelta(minutes=-5) or age > timedelta(hours=24):
        return "stale"
    return "current"


def counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    values = Counter(case["status"] for case in cases)
    return {
        "total": len(cases),
        **{
            key: values[key]
            for key in ("passed", "failed", "skipped", "xfailed", "xpassed", "not_run")
        },
    }


def result_status(cases: list[dict[str, Any]], *, missing: bool = False) -> str:
    totals = counts(cases)
    if totals["failed"]:
        return "failed"
    if not cases or missing:
        return "not_measured"
    return "passed" if totals["passed"] == totals["total"] else "incomplete"


def run_summary(run: TestRun, current: str) -> dict[str, Any]:
    cases = [case.model_dump() for case in run.tests]
    status = result_status(cases)
    if run.state == "running":
        status = "running"
    elif run.exit_code or run.collection_errors:
        status = "failed"
    elif run.scope != "full" and status == "passed":
        status = "incomplete"
    return {
        **run.model_dump(mode="json", exclude={"tests"}),
        "counts": counts(cases),
        "status": status,
        "freshness": freshness(
            run.completed_at or run.started_at, run.source_fingerprint, current, run.source_changed
        ),
    }


def taxonomy() -> dict[str, Any]:
    return dict(read_json(ROOT / "config/health-categories.json"))


def classify(cases: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    groups = config["categories"] + [
        {
            "id": "unclassified",
            "name": "Needs classification",
            "description": "New test files without a reviewed category.",
            "files": [],
        }
    ]
    by_file = {file: group["id"] for group in groups for file in group["files"]}
    for case in cases:
        case["category"] = by_file.get(case["file"], "unclassified")
    return [
        {
            **group,
            "counts": counts(selected),
            "status": result_status(selected),
            "file_count": len({case["file"] for case in selected}),
        }
        for group in groups
        if (selected := [c for c in cases if c["category"] == group["id"]])
    ]


def capability_evidence(
    cases: list[dict[str, Any]], config: dict[str, Any]
) -> list[dict[str, Any]]:
    def matches(case: dict[str, Any], selector: str) -> bool:
        return case["file"] == selector or case["id"].split("[", 1)[0] == selector

    output = []
    for capability in config["capabilities"]:
        selected = [c for c in cases if any(matches(c, s) for s in capability["selectors"])]
        missing = [s for s in capability["selectors"] if not any(matches(c, s) for c in cases)]
        output.append(
            {
                **capability,
                "counts": counts(selected),
                "test_ids": [case["id"] for case in selected],
                "missing_selectors": missing,
                "status": result_status(selected, missing=bool(missing)),
            }
        )
    return output


class Check(BaseModel):
    id: str
    label: str
    status: Literal["passed", "failed", "unavailable"]
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    exit_code: int | None

    @model_validator(mode="after")
    def outcome_matches_exit(self) -> "Check":
        if (
            (self.status == "passed" and self.exit_code != 0)
            or (self.status == "failed" and self.exit_code in (0, None))
            or (self.status == "unavailable" and self.exit_code is not None)
        ):
            raise ValueError("Check outcome does not match execution")
        return self


class Checks(BaseModel):
    schema_version: Literal[1]
    kind: Literal["checks"]
    source_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    created_at: AwareDatetime
    source_changed: bool = False
    checks: list[Check]


def static_checks(current: str) -> dict[str, Any]:
    try:
        value = Checks.model_validate(read_json(REPORTS / "latest-checks.json"))
        return {
            **value.model_dump(mode="json"),
            "available": True,
            "freshness": freshness(
                value.created_at, value.source_fingerprint, current, value.source_changed
            ),
        }
    except (OSError, ValueError):
        return {"available": False, "freshness": "unavailable", "checks": []}


class JudgeCase(BaseModel):
    case_id: str = Field(max_length=200)
    expected_decision: Literal["approve_retry", "deny_retry"]
    actual_decision: Literal["approve_retry", "deny_retry"] | None
    status: Literal["ok", "schema_failure", "provider_error"]
    passed: bool = Field(strict=True)
    hard_policy_violation: bool = Field(strict=True)
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    input_tokens: int = Field(ge=0, strict=True)
    output_tokens: int = Field(ge=0, strict=True)


class JudgeReport(BaseModel):
    mode: Literal["offline-baseline"]
    fixture_version: str
    results: list[JudgeCase] = Field(min_length=1, max_length=12)


class JudgeReceipt(BaseModel):
    schema_version: Literal[1]
    kind: Literal["evals"]
    source_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    created_at: AwareDatetime
    source_changed: bool = False
    report: JudgeReport


def judge_evidence(current: str) -> dict[str, Any]:
    try:
        value = JudgeReceipt.model_validate(read_json(REPORTS / "latest-evals.json"))
        fixture = read_json(ROOT / "data/evals/recovery-judge.json")
        expected = {row["id"]: row["expected_decision"] for row in fixture["cases"]}
        rows = [row.model_dump() for row in value.report.results]
        if value.report.fixture_version != fixture["version"] or len(
            {r["case_id"] for r in rows}
        ) != len(rows):
            raise ValueError("Evaluation fixture mismatch")
        for row in rows:
            if (
                row["case_id"] not in expected
                or row["expected_decision"] != expected[row["case_id"]]
            ):
                raise ValueError("Unknown evaluation case")
            row["passed"] = (
                row["status"] == "ok" and row["actual_decision"] == row["expected_decision"]
            )
            row["hard_policy_violation"] = (
                row["actual_decision"] == "approve_retry"
                and row["expected_decision"] == "deny_retry"
            )
        missing = sorted(set(expected) - {row["case_id"] for row in rows})
        return {
            "available": True,
            "created_at": value.created_at.isoformat(),
            "freshness": freshness(
                value.created_at, value.source_fingerprint, current, value.source_changed
            ),
            "mode": "offline-baseline",
            "fixture_version": value.report.fixture_version,
            "missing_cases": missing,
            "rows": rows,
            "counts": {"total": len(expected), "passed": sum(r["passed"] for r in rows)},
            "note": "Rules oracle compared with itself; validates the harness, not model quality.",
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {"available": False, "freshness": "unavailable", "rows": []}


@router.get("/health", include_in_schema=False)
def health_page() -> FileResponse:
    return FileResponse(ROOT / "web/health.html")


@router.get("/api/health/evidence")
def evidence(test_run: UUID | None = None) -> dict[str, Any]:
    current = source_fingerprint(ROOT)
    config = taxonomy()
    response: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "timezone": "Europe/Madrid",
        "source_fingerprint": current,
        "available": False,
        "tests": [],
        "categories": [],
        "history": [],
        "invalid_history_reports": 0,
        "capabilities": capability_evidence([], config),
        "static_checks": static_checks(current),
        "judge": judge_evidence(current),
        "refresh_command": "make health",
        "test_run": None,
    }
    path = REPORTS / "runs" / f"{test_run}.json" if test_run else REPORTS / "latest-tests.json"
    try:
        run = TestRun.model_validate(read_json(path))
        if test_run and run.id != test_run:
            raise ValueError("Run identity mismatch")
        cases = [case.model_dump(mode="json") for case in run.tests]
        response.update(
            available=True,
            test_run=run_summary(run, current),
            tests=cases,
            categories=classify(cases, config),
            capabilities=capability_evidence(cases, config),
        )
    except (OSError, ValueError):
        response["message"] = "No valid test receipt. Run make health to collect local evidence."
    candidates = []
    for candidate in (REPORTS / "runs").glob("*.json"):
        try:
            candidates.append((candidate.stat().st_mtime, candidate))
        except OSError:
            continue
    paths = [path for _, path in sorted(candidates, reverse=True)]
    for item in paths[:12]:
        try:
            response["history"].append(
                run_summary(TestRun.model_validate(read_json(item)), current)
            )
        except (OSError, ValidationError, ValueError):
            response["invalid_history_reports"] += 1
            continue
    return response


@router.get("/api/health/runtime")
def runtime(run: UUID | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "services": [],
        "runs": [],
        "selected": None,
        "provider_mode": "disabled" if settings().llm_provider == "disabled" else "configured",
        "checked_at": datetime.now(UTC).isoformat(),
    }
    start = time.perf_counter()
    try:
        with connect() as conn:
            conn.execute("SET LOCAL statement_timeout='1500ms'")
            conn.execute("SELECT 1")
            result["services"].append(
                {
                    "id": "postgres",
                    "name": "Postgres / PostGIS",
                    "status": "passed",
                    "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                }
            )
            result["runs"] = conn.execute(
                "SELECT r.id,r.status,r.created_at,r.sim_time,CASE WHEN s.run_id IS NOT NULL "
                "THEN 'restaurant' WHEN w.run_id IS NOT NULL THEN 'delivery' "
                "ELSE 'madrid' END kind "
                "FROM runs r LEFT JOIN supply_sessions s ON s.run_id=r.id "
                "LEFT JOIN lab_worlds w ON w.run_id=r.id ORDER BY r.created_at DESC LIMIT 12"
            ).fetchall()
            selected = run or (result["runs"][0]["id"] if result["runs"] else None)
            if selected:
                if not conn.execute("SELECT 1 FROM runs WHERE id=%s", (selected,)).fetchone():
                    raise HTTPException(404, "Unknown simulation")
                queue = conn.execute(
                    "SELECT count(*) total,count(*) FILTER(WHERE state='ready') ready,"
                    "count(*) FILTER(WHERE state='leased') leased,"
                    "count(*) FILTER(WHERE state='leased' "
                    "AND lease_until<=clock_timestamp()) expired,"
                    "count(*) FILTER(WHERE state='dead') dead,"
                    "coalesce(sum(greatest(0,attempts-1)),0) retries "
                    "FROM events WHERE run_id=%s",
                    (selected,),
                ).fetchone()
                budget = conn.execute(
                    "SELECT events_reserved,events_limit,tools_reserved,tools_limit "
                    "FROM agent_run_budgets WHERE run_id=%s",
                    (selected,),
                ).fetchone()
                reservations = conn.execute(
                    "SELECT (SELECT count(*) FROM agent_model_calls WHERE run_id=%s)+"
                    "(SELECT count(*) FROM supply_search_calls WHERE run_id=%s) total",
                    (selected, selected),
                ).fetchone()
                result["selected"] = {
                    "id": selected,
                    "queue": queue,
                    "budget": budget,
                    "model_reservations": reservations["total"] if reservations else 0,
                }
    except HTTPException:
        raise
    except Exception:
        # Never expose connection strings, exception messages, credentials or agent memory.
        if not result["services"]:
            result["services"].append(
                {
                    "id": "postgres",
                    "name": "Postgres / PostGIS",
                    "status": "failed",
                    "latency_ms": None,
                }
            )
        else:
            result["diagnostics_unavailable"] = True
    start = time.perf_counter()
    try:
        client = redis.Redis.from_url(
            settings().redis_url, socket_connect_timeout=1, socket_timeout=1
        )
        try:
            client.ping()
        finally:
            client.close()
        status = "passed"
    except Exception:
        status = "failed"
    result["services"].append(
        {
            "id": "redis",
            "name": "Redis (baseline support)",
            "status": status,
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
        }
    )
    return result

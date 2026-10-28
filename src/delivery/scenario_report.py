"""Versioned scenario criteria and independently recomputed local evaluation scores."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/evals/agent-scenarios.json"
Scalar = StrictBool | StrictInt | Annotated[str, Field(strict=True, max_length=120)]
Role = Literal["inventory", "restaurant", "dispatcher", "courier"]
Error = Literal["execution_failed", "cleanup_failed", "deadline_exceeded"]
ROLE_NAMES = {
    "inventory": "Inventory",
    "restaurant": "Restaurant",
    "dispatcher": "Dispatcher",
    "courier": "Courier",
}


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Criterion(Record):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=240)
    expected: Scalar


class Scenario(Record):
    id: str = Field(pattern=r"^[a-z][a-z0-9.-]{0,79}$")
    role: Role
    fixture: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=600)
    checks: list[Criterion] = Field(min_length=1, max_length=20)


class Manifest(Record):
    version: str = Field(pattern=r"^agent-scenarios-v[1-9][0-9]*$")
    seed: int = Field(ge=0, le=2147483647)
    cases: list[Scenario] = Field(min_length=4, max_length=100)


def load_manifest(path: Path = MANIFEST) -> Manifest:
    manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8"))
    if len({case.id for case in manifest.cases}) != len(manifest.cases) or any(
        len({check.id for check in case.checks}) != len(case.checks) for case in manifest.cases
    ):
        raise ValueError("Duplicate scenario or criterion")
    if {case.role for case in manifest.cases} != set(ROLE_NAMES):
        raise ValueError("Every supported role needs scenarios")
    return manifest


class Evidence(Record):
    sequence: int = Field(ge=1)
    topic: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,79}$")
    trace: str = Field(pattern=r"^[a-zA-Z0-9_.:-]{1,120}$")
    state: Literal["ready", "leased", "done", "dead"]
    attempts: int = Field(ge=0)
    sim_time: int = Field(ge=0)


class Outcome(Record):
    id: str
    observed: dict[str, Scalar | None]
    error: Error | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=200)


class Reproduction(Record):
    repetitions: int = Field(ge=1, le=3)
    hashes: list[str] = Field(min_length=1, max_length=3)
    previous_results: list[list[Outcome]] = Field(default_factory=list, max_length=2)
    previous_configurations: list[dict[str, str]] = Field(default_factory=list, max_length=2)


class Receipt(Record):
    schema_version: Literal[1]
    kind: Literal["agent-scenarios"]
    mode: Literal["local-deterministic"]
    version: str
    seed: int
    fixture_hash: str = Field(pattern="^[0-9a-f]{64}$")
    source_fingerprint: str = Field(pattern="^[0-9a-f]{64}$")
    source_changed: bool
    created_at: AwareDatetime
    # Effective configurations identify inputs in addition to the manifest/source hashes.
    configurations: dict[str, str]
    results: list[Outcome] = Field(max_length=100)
    reproduction: Reproduction


def outcome_hash(results: list[Outcome]) -> str:
    """Compare business outcomes, excluding wall time, SQL IDs and race winners."""
    return digest(
        [
            {"id": row.id, "observed": row.observed, "error": row.error}
            for row in sorted(results, key=lambda row: row.id)
        ]
    )


def validate_receipt(value: Any, manifest: Manifest) -> Receipt:
    receipt = Receipt.model_validate_json(json.dumps(value, allow_nan=False))
    expected = {case.id: case for case in manifest.cases}
    if (
        receipt.version != manifest.version
        or receipt.seed != manifest.seed
        or receipt.fixture_hash != digest(manifest.model_dump(mode="json"))
    ):
        raise ValueError("Evaluation manifest mismatch")
    attempts = [*receipt.reproduction.previous_results, receipt.results]
    for attempt in attempts:
        if len({row.id for row in attempt}) != len(attempt) or len(attempt) > 100:
            raise ValueError("Duplicate scenario IDs")
        for row in attempt:
            if row.id not in expected or set(row.observed) - {
                check.id for check in expected[row.id].checks
            }:
                raise ValueError("Unknown scenario or criterion")
    fixtures = {case.fixture for case in manifest.cases}
    configurations = [*receipt.reproduction.previous_configurations, receipt.configurations]
    for configuration in configurations:
        if set(configuration) != fixtures or any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in configuration.values()
        ):
            raise ValueError("Missing effective configuration hashes")
    reproduction = receipt.reproduction
    if (
        len(reproduction.hashes) != reproduction.repetitions
        or len(attempts) != reproduction.repetitions
        or len(configurations) != reproduction.repetitions
        or reproduction.hashes != [outcome_hash(attempt) for attempt in attempts]
        or any(
            len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in reproduction.hashes
        )
    ):
        raise ValueError("Invalid reproducibility receipt")
    return receipt


def summarize(manifest: Manifest, receipt: Receipt | None) -> dict[str, Any]:
    attempts = [*receipt.reproduction.previous_results, receipt.results] if receipt else []
    cases = []
    for spec in manifest.cases:
        rows = [next((r for r in attempt if r.id == spec.id), None) for attempt in attempts]
        measured = any(row is not None for row in rows)
        errors = [row.error for row in rows if row and row.error]
        checks = []
        for criterion in spec.checks:
            observations = [row.observed.get(criterion.id) if row else None for row in rows]
            # Keep the first explicit failure of this criterion across all repeats.
            # An earlier omission cannot hide a later measured failure either.
            failures = [
                i
                for i, value in enumerate(observations)
                if value is not None
                and (type(value) is not type(criterion.expected) or value != criterion.expected)
            ]
            missing = [i for i, value in enumerate(observations) if value is None]
            index = failures[0] if failures else missing[0] if missing else len(rows) - 1
            actual = observations[index] if observations else None
            # bool and int deliberately differ: True is not a measured count of one.
            passed = type(actual) is type(criterion.expected) and actual == criterion.expected
            checks.append(
                {
                    **criterion.model_dump(),
                    "actual": actual,
                    "repetition": index + 1 if observations else None,
                    "status": "not_measured"
                    if actual is None
                    else "passed"
                    if passed
                    else "failed",
                }
            )
        passed_count = sum(check["status"] == "passed" for check in checks)
        status = (
            "failed"
            if errors or any(c["status"] == "failed" for c in checks)
            else "not_measured"
            if not measured or any(c["status"] == "not_measured" for c in checks)
            else "passed"
        )
        cases.append(
            {
                "id": spec.id,
                "role": spec.role,
                "name": spec.name,
                "description": spec.description,
                "status": status,
                "score": round(100 * passed_count / len(checks), 1) if measured else None,
                "error": errors[0] if errors else None,
                "measured": measured,
                "checks": checks,
                "evidence": [
                    {**e.model_dump(), "repetition": index}
                    for index, row in enumerate(rows, 1)
                    if row
                    for e in row.evidence
                ],
            }
        )

    def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        totals = Counter(row["status"] for row in rows)
        checks = [c for row in rows for c in row["checks"]]
        passed = sum(c["status"] == "passed" for c in checks)
        measured = any(row["measured"] for row in rows)
        return {
            "counts": {
                "total": len(rows),
                **{s: totals[s] for s in ("passed", "failed", "not_measured")},
            },
            "checks_passed": passed,
            "checks_total": len(checks),
            "score": round(100 * passed / len(checks), 1) if measured else None,
            "status": "failed"
            if totals["failed"]
            else "passed"
            if totals["passed"] == len(rows)
            else "incomplete"
            if measured
            else "not_measured",
        }

    result = {
        "available": receipt is not None,
        "version": manifest.version,
        "seed": manifest.seed,
        "mode": "local-deterministic",
        "roles": [
            {"id": role, "name": name, **aggregate([c for c in cases if c["role"] == role])}
            for role, name in ROLE_NAMES.items()
        ],
        "cases": cases,
        **aggregate(cases),
        "note": "Real scoped agents and durable queues; fixed local rules, no live model quality "
        "or latency claim. Scores are passed criteria / declared criteria; every criterion is "
        "required for a case to pass. Missing criteria receive no credit.",
    }
    if receipt:
        outcomes_matched = len(set(receipt.reproduction.hashes)) == 1
        inputs_matched = (
            len(
                {
                    digest(c)
                    for c in [*receipt.reproduction.previous_configurations, receipt.configurations]
                }
            )
            == 1
        )
        matched = outcomes_matched and inputs_matched
        result.update(
            created_at=receipt.created_at.isoformat(),
            source_fingerprint=receipt.source_fingerprint,
            fixture_hash=receipt.fixture_hash,
            outcome_hash=outcome_hash(receipt.results),
            configurations=receipt.configurations,
            reproduction={
                "repetitions": receipt.reproduction.repetitions,
                "hashes": receipt.reproduction.hashes,
                "matched": matched,
                "outcomes_matched": outcomes_matched,
                "inputs_matched": inputs_matched,
            },
        )
        if not matched:
            result["status"] = "failed"
            result["note"] += " Repeated inputs or outcomes differed; reproducibility failed."
    return result

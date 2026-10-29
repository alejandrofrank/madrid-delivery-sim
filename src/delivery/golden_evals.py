"""Versioned, reviewable golden cases with explicit references and source hashes."""

import json
import re
from pathlib import Path
from typing import Any

from delivery.eval_checks import TOOL_FIELDS
from delivery.scenario_report import digest
from delivery.trajectory_evals import normalize_trace, score_trajectory


def artifact_trace(path: Path, pointer: str, event_id: int | None = None) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2] / "artifacts"
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Receipts must be under artifacts/")
    value = json.loads(path.read_text(encoding="utf-8"))
    for part in pointer.strip("/").split("/") if pointer else []:
        value = value[int(part)] if isinstance(value, list) else value[part]
    rows = value["calls"] if isinstance(value, dict) else value
    if event_id is not None:
        rows = [r for r in rows if r.get("event_id") == event_id]
    if not rows or len({r.get("event_id") for r in rows}) > 1:
        raise ValueError("Select exactly one event with --event-id and --pointer")
    return normalize_trace(rows)


def promote(
    trace: dict[str, Any], reference: list[dict[str, Any]], *, root: Path,
    case_id: str, description: str, source: str, expected_categories: list[str],
) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", case_id):
        raise ValueError("Invalid case ID")
    if not reference or any(set(r) != {"name", "args"} for r in reference):
        raise ValueError("Supply explicit reference tool calls with name and args")
    if set(expected_categories) - {"schema", "length", "invented_tool"}:
        raise ValueError("Unknown rejection category")
    # Keep only capability arguments; never persist raw prompts, credentials, SQL,
    # model thoughts, user messages, tool-result bodies or database connection strings.
    clean_calls = []
    for call in trace["calls"]:
        args = call["args"]
        fields = TOOL_FIELDS.get(call["name"], {"summary"})
        if set(args) - fields or any(not isinstance(v, str) or len(v) > 2000
                                     for v in args.values()):
            raise ValueError("Review and redact out-of-contract arguments before promotion")
        clean_calls.append({k: call[k] for k in ("name", "args", "allowed_tools", "model_step")
                            if k in call})
    clean = {**trace, "calls": clean_calls}
    for ref in reference:
        if ref["name"] not in TOOL_FIELDS or set(ref["args"]) != TOOL_FIELDS[ref["name"]]:
            raise ValueError("Invalid reference capability")
    versions = [int(p.name[1:]) for p in root.glob("v*") if re.fullmatch(r"v[1-9][0-9]*", p.name)]
    version = max(versions, default=0) + 1
    folder = root / f"v{version}"
    folder.mkdir(parents=True, exist_ok=False)
    case = {
        "schema_version": 1, "version": version, "id": case_id,
        "description": description, "source": source, "source_sha256": digest(trace),
        "trace": clean, "reference": reference, "expected_categories": expected_categories,
    }
    path = folder / f"{case_id}.json"
    path.write_text(json.dumps(case, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def evaluate_golden(root: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("v*/*.json"), key=lambda p: int(p.parent.name[1:])):
        case = json.loads(path.read_text(encoding="utf-8"))
        if case["schema_version"] != 1 or case["version"] != int(path.parent.name[1:]):
            raise ValueError("Invalid golden version")
        latest[case["id"]] = case
    results = []
    for case in latest.values():
        score = score_trajectory(case["trace"], case["reference"])
        categories = sorted({f["category"] for f in score["code_failures"]})
        results.append({"id": case["id"], "version": case["version"], "score": score,
                        "passed": categories == sorted(case["expected_categories"])})
    return results

"""Explicit paid, synthetic comparison. No retries or provider fallback.

Run inside a one-shot local container with keyless impersonated ADC. Each profile
gets $0.20 Vertex admission and 3 Jev calls / 24,000 reserved input tokens.
The durable output file prevents accidental repeat execution.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from demo_adk_restaurants import configuration

from delivery.adk_contracts import VertexProfile
from delivery.adk_evidence import run_evidence
from delivery.config import settings
from delivery.db import connect, migrate
from delivery.health_report import atomic_write_json, source_fingerprint
from delivery.supply import new_supply, replay_supply, run_supply, supply_snapshot
from delivery.supply_models import SupplyConfig


def save_receipt(path: Path, receipt: dict) -> None:
    # SQL numeric fields are decimal strings in evidence, never lossy floats.
    atomic_write_json(path, json.loads(json.dumps(receipt, default=str)))


def finish_entry(entry: dict, profile: VertexProfile) -> None:
    run = entry["run"]
    state = supply_snapshot(run)
    with connect() as conn:
        status = conn.execute("SELECT status FROM runs WHERE id=%s", (run,)).fetchone()["status"]
    entry.update(
        status="completed" if status == "complete" else "failed",
        metrics=state["metrics"],
        invariants=state["invariants"],
        replay_matches=replay_supply(run)["matches"],
        evidence=run_evidence(run, profile),
    )
    sourcing = next(
        (
            t["result"]
            for t in entry["evidence"]["turns"]
            if t["result"] and t["result"]["action"] == "source"
        ),
        {},
    )
    entry["supplier"] = sourcing.get("supplier")
    entry["soul_choice_matches"] = entry["supplier"] == entry["expected_supplier"]
    entry["jev_verified"] = (
        bool(entry["evidence"]["jev_calls"])
        and all(call["status"] == "ok" for call in entry["evidence"]["jev_calls"])
        and all(not s["detail"].get("error") for s in entry["evidence"]["searches"])
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paid", action="store_true", required=True)
    parser.add_argument("--after-review", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if not args.paid or os.environ.get("DELIVERY_ADK_VERTEX_ENABLED") != "1":
        raise PermissionError("Explicit paid execution and deployment approval required")
    database = urlsplit(settings().database_url)
    if (
        database.hostname not in {"postgres", "localhost", "127.0.0.1"}
        or database.path != "/delivery"
    ):
        raise PermissionError("The real comparison requires the retained local demo database")
    profile = VertexProfile.model_validate_json(os.environ["DELIVERY_ADK_VERTEX_PROFILE"])
    if profile.model != "gemini-3.5-flash-lite" or profile.location != "global":
        raise PermissionError(
            "Review model availability and tariff before changing the live profile"
        )
    if (
        profile.input_usd_per_million,
        profile.output_usd_per_million,
        profile.cached_input_usd_per_million,
    ) != (0.30, 2.50, 0.03):
        raise PermissionError("Live comparison tariff must match the reviewed public pricing")
    if os.environ.get("TYPESAFE_MODEL") != "jev-1.14.0":
        raise PermissionError("Pin the reviewed Jev version")
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts/adk-live-comparison.json"
    history = []
    spent = Decimal(0)
    lock_path = root / "artifacts/.adk-live-comparison.lock"
    if output.exists() and not args.resume:
        previous = json.loads(output.read_text())
        if not args.after_review or any(p["status"] == "running" for p in previous["profiles"]):
            raise PermissionError("Inspect the previous paid comparison before another test")
        history = [*previous.pop("previous_attempts", []), previous]
        for attempt in history:
            for entry in attempt["profiles"]:
                for call in entry["evidence"]["calls"]:
                    spent += Decimal(call["usage_cost_usd"] or call["reserved_usd"])
        if spent + Decimal("0.40") > Decimal("0.50"):
            raise PermissionError("The cumulative $0.50 Vertex comparison allowance is exhausted")
        # Only an explicitly reviewed, finished experiment can replace its lock.
        lock_path.unlink(missing_ok=True)
    if not args.resume:
        with lock_path.open("x") as lock:
            lock.write(datetime.now(UTC).isoformat())
    migrate()
    receipt = {
        "created_at": datetime.now(UTC).isoformat(),
        "source_fingerprint": source_fingerprint(root),
        "profile": profile.model_dump(mode="json"),
        "vertex_admission_limit_usd": "0.40",
        "jev_input_token_limit": 48000,
        "jev_tariff_usd_per_million": "0.042",
        "jev_maximum_usd_at_tariff": "0.002016",
        "pricing_checked": "2026-10-29",
        "prior_vertex_accounted_usd": str(spent),
        "cumulative_vertex_limit_usd": "0.50",
        "previous_attempts": history,
        "profiles": [],
    }
    if args.resume:
        receipt = json.loads(output.read_text())
        if receipt["profile"] != profile.model_dump(mode="json"):
            raise PermissionError("Cannot resume with a different approved model profile")
        for entry in receipt["profiles"]:
            finish_entry(entry, profile)  # Read-only recovery; no re-dispatch of a saved run.
    save_receipt(output, receipt)
    for soul, expected in (("speed", "market-a"), ("cost", "market-b")):
        if any(entry["soul"] == soul for entry in receipt["profiles"]):
            continue
        data = configuration(soul).model_dump(mode="json")
        agent = data["entities"][1]["agent"]
        agent["brain"].update(
            provider="vertex",
            vertex=profile.model_dump(mode="json"),
            usd_limit=0.20,
            model_calls_per_event=8,
            model_calls_per_run=60,
            timeout_seconds=30,
            output_tokens=1024,
        )
        agent["brain"]["tools"].append("supply.search")
        agent["brain"]["instructions"] += (
            "\nFor household.call only, use search_ingredients once with query mozzarella "
            "before staging sourcing. This is a Jev relevance check, not a stock reservation. "
            "Do not search on subsequent arrival/cooking events. Batch independent read tools "
            "in one response when possible. Always finish the staged action."
        )
        agent["search"] = {"provider": "jev", "calls_limit": 3, "input_tokens_limit": 24000}
        run = new_supply(SupplyConfig.model_validate(data))
        entry = {"soul": soul, "run": run, "expected_supplier": expected, "status": "running"}
        receipt["profiles"].append(entry)
        save_receipt(output, receipt)
        started = time.monotonic()
        try:
            state = run_supply(run)
            replay = replay_supply(run)
            entry.update(
                metrics=state["metrics"],
                invariants=state["invariants"],
                replay_matches=replay["matches"],
            )
            entry["status"] = "completed"
        except Exception as exc:
            entry.update(status="failed", error=type(exc).__name__)
        finally:
            entry["wall_seconds"] = round(time.monotonic() - started, 3)
            entry["evidence"] = run_evidence(run, profile)
            entry["jev_verified"] = (
                bool(entry["evidence"]["jev_calls"])
                and all(call["status"] == "ok" for call in entry["evidence"]["jev_calls"])
                and all(
                    not search["detail"].get("error") for search in entry["evidence"]["searches"]
                )
            )
            turns = entry["evidence"]["turns"]
            sourcing = next(
                (t["result"] for t in turns if t["result"] and t["result"]["action"] == "source"),
                {},
            )
            entry["supplier"] = sourcing.get("supplier")
            entry["soul_choice_matches"] = entry["supplier"] == expected
            save_receipt(output, receipt)
            print(
                json.dumps({k: v for k, v in entry.items() if k != "evidence"}, default=str),
                flush=True,
            )
    if any(
        e["status"] != "completed"
        or not e["soul_choice_matches"]
        or not e["jev_verified"]
        or e["metrics"]["delivered"] != 1
        or not e["replay_matches"]
        for e in receipt["profiles"]
    ):
        raise RuntimeError(
            "Live comparison did not meet all declared criteria; inspect saved evidence"
        )


if __name__ == "__main__":
    execution_lock = Path("artifacts/.adk-live-execution.lock")
    with execution_lock.open("x"):
        try:
            main()
        finally:
            execution_lock.unlink()

r"""Compare local dispatch policies on identical seeded demand and a shared road world.

Example (Bash):
    TEST_DATABASE_URL='postgresql://.../delivery_test' python3 scripts/benchmark_dispatch.py \
        --seed 42 --seed 73 --duration 43200 --include-reposition \
        --output artifacts/dispatch-comparison.json

Only the dedicated local delivery_test database is accepted. Runs and complete
snapshots remain available for inspection; this script does not delete any runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def require_local_test_database(url: str) -> None:
    """Reject other database names, remote hosts, and connection-query overrides."""
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in {"postgres", "postgresql"}
            and parsed.path == "/delivery_test"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1", "postgres"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Dispatch comparisons require the dedicated local delivery_test database")


def json_value(value: Any) -> str | float:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal) and value.is_finite():
        return float(value)
    raise TypeError(f"Unsupported artifact value: {type(value).__name__}")


def save_artifact(path: Path, artifact: dict[str, Any]) -> None:
    """Keep a reviewable partial report if an arm fails or execution is interrupted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f".{path.name}.", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(artifact, handle, indent=2, allow_nan=False, default=json_value)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def source_version() -> dict[str, Any]:
    try:
        package_version = version("madrid-delivery-sim")
    except PackageNotFoundError:
        package_version = None
    try:
        commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    paths = [
        *sorted((ROOT / "src" / "delivery").glob("*.py")),
        *sorted((ROOT / "sql").rglob("*.sql")),
        ROOT / "scripts" / "benchmark_dispatch.py",
        ROOT / "pyproject.toml",
    ]
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            name = path.relative_to(ROOT).as_posix().encode()
            data = path.read_bytes()
            digest.update(len(name).to_bytes(8, "big") + name)
            digest.update(len(data).to_bytes(8, "big") + data)
    return {
        "package": package_version,
        "python": platform.python_version(),
        "git_commit": commit if re.fullmatch(r"[0-9a-f]{40,64}", commit) else None,
        "source_sha256": digest.hexdigest(),
        "data_sha256": {
            name: hashlib.sha256((ROOT / "data" / name).read_bytes()).hexdigest()
            for name in ("madrid.graphml.gz", "stores.json", "manifest.json")
            if (ROOT / "data" / name).is_file()
        },
    }


def summarize(state: dict[str, Any], wall_seconds: float) -> dict[str, Any]:
    metrics = state["metrics"]
    counts = {courier["id"]: int(courier["completed_jobs"]) for courier in state["couriers"]}
    jobs = list(counts.values())
    result = {
        key: metrics[key]
        for key in (
            "orders",
            "delivered",
            "on_time",
            "on_time_pct",
            "unserved",
            "pending",
            "active",
            "overdue",
            "empty_km",
            "reposition_km",
            "operating_cost_eur",
            "cost_per_delivery_eur",
        )
    }
    result.update(
        unfinished=int(metrics["pending"]) + int(metrics["active"]),
        couriers_total=len(jobs),
        couriers_used=sum(count > 0 for count in jobs),
        completed_jobs_by_courier=counts,
        jobs_min=min(jobs, default=0),
        jobs_max=max(jobs, default=0),
        jobs_mean=round(statistics.mean(jobs), 6) if jobs else 0,
        jobs_population_stddev=round(statistics.pstdev(jobs), 6) if jobs else 0,
        jobs_spread=max(jobs, default=0) - min(jobs, default=0),
        wall_seconds=round(wall_seconds, 6),
    )
    result["feasibility_counts"] = {
        key: value for key, value in metrics.items() if "feasib" in key or "reject" in key
    }
    return result


def comparison(arms: list[dict[str, Any]]) -> dict[str, Any]:
    completed = {arm["name"]: arm["summary"] for arm in arms if arm["status"] == "complete"}
    baseline = completed.get("legacy_stay")
    if baseline is None:
        return {}
    numeric_keys = (
        "delivered",
        "on_time",
        "on_time_pct",
        "unserved",
        "unfinished",
        "empty_km",
        "reposition_km",
        "operating_cost_eur",
        "cost_per_delivery_eur",
        "couriers_used",
        "jobs_spread",
        "wall_seconds",
    )
    return {
        name: {
            key: round(float(summary[key]) - float(baseline[key]), 6)
            if summary[key] is not None and baseline[key] is not None
            else None
            for key in numeric_keys
        }
        for name, summary in completed.items()
        if name != "legacy_stay"
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--seed", type=int, action="append", help="Repeat for paired demand seeds")
    parser.add_argument("--duration", type=int, default=43200, help="Simulation seconds per arm")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/dispatch-comparison.json")
    parser.add_argument(
        "--include-reposition", action="store_true", help="Add min_cost/demand_aware"
    )
    args = parser.parse_args()
    args.seed = list(dict.fromkeys(args.seed or [42]))
    if any(seed < 0 for seed in args.seed):
        parser.error("--seed must be nonnegative")
    if args.duration < 1800 or args.duration % 60:
        parser.error(
            "--duration must be at least 1800 seconds and a multiple of the 60-second tick"
        )
    return args


def main() -> int:
    args = parse_args()
    # Resolve configuration only after --help and argument validation. No URL or
    # settings object is serialized, including on connection/run failure.
    from delivery.config import settings
    from delivery.customer_service import CustomerService
    from delivery.db import migrate
    from delivery.dispatch_policy import DispatchPolicy
    from delivery.simulation import Simulation, create_run
    from delivery.world import World

    config = settings()
    url = os.environ.get("TEST_DATABASE_URL") or config.database_url
    require_local_test_database(url)
    offline = config.model_copy(
        update={"llm_provider": "disabled", "llm_max_calls": 0, "llm_max_tokens": 0}
    )
    policies = [
        ("legacy_stay", DispatchPolicy(strategy="legacy", reposition="stay")),
        ("min_cost_stay", DispatchPolicy(strategy="min_cost", reposition="stay")),
    ]
    if args.include_reposition:
        policies.append(
            (
                "min_cost_demand_aware",
                DispatchPolicy(strategy="min_cost", reposition="demand_aware"),
            )
        )
    artifact: dict[str, Any] = {
        "schema_version": 1,
        "kind": "local_dispatch_comparison",
        "created_at": datetime.now(UTC).isoformat(),
        "status": "running",
        "version": source_version(),
        "seeds": args.seed,
        "duration_seconds": args.duration,
        "arms": [{"name": name, "policy": policy.model_dump()} for name, policy in policies],
        "assumptions": {
            "database": "dedicated local delivery_test; existing runs are retained",
            "pairing": "Same World instance, road data, seed, demand generator, and initial fleet",
            "providers": "disabled; no model or export calls",
            "simulation": "60-second ticks; final 1800 seconds drain existing deliveries",
            "costs": "Synthetic marginal vehicle costs plus task fee; not actual Uber prices",
            "fairness": "Job spread and standard deviation include idle couriers with zero jobs",
            "runtime": "Creation plus simulation and its final snapshot; graph loading excluded",
            "route_cache": "Cleared before each arm so later policies do not inherit cached paths",
            "feasibility": "Only canonical full-run snapshot metrics are reported as counts",
            "comparison": "Per-seed deltas subtract legacy_stay; no improvement threshold assumed",
        },
        "results": [],
    }
    output = args.output.resolve()
    save_artifact(output, artifact)
    try:
        os.chdir(ROOT)
        migrate(url)
        world = World()
        for seed in args.seed:
            paired: dict[str, Any] = {"seed": seed, "arms": [], "delta_from_legacy": {}}
            artifact["results"].append(paired)
            for name, policy in policies:
                arm: dict[str, Any] = {
                    "name": name,
                    "policy": policy.model_dump(),
                    "run_id": None,
                    "status": "running",
                }
                paired["arms"].append(arm)
                save_artifact(output, artifact)
                world.path.cache_clear()
                started = time.perf_counter()
                try:
                    run = create_run(
                        world,
                        seed=seed,
                        wall_seconds=0,
                        duration=args.duration,
                        url=url,
                        dispatch=policy,
                    )
                    arm["run_id"] = run
                    save_artifact(output, artifact)
                    state = Simulation(
                        world, url, service=CustomerService(url, config=offline)
                    ).run(run, export=False)
                    elapsed = time.perf_counter() - started
                    if not math.isfinite(elapsed):
                        raise RuntimeError("Invalid wall runtime")
                    if state["run"].get("llm_calls", 0) or state["run"].get("llm_cost_usd", 0):
                        raise RuntimeError("Provider-disabled benchmark recorded model activity")
                    arm.update(status="complete", snapshot=state, summary=summarize(state, elapsed))
                    paired["delta_from_legacy"] = comparison(paired["arms"])
                    print(
                        json.dumps(
                            {"seed": seed, "arm": name, **arm["summary"]}, default=json_value
                        )
                    )
                except BaseException as exc:
                    arm.update(status="failed", error_type=type(exc).__name__)
                    raise
                finally:
                    save_artifact(output, artifact)
        artifact["status"] = "complete"
    except BaseException as exc:
        artifact.update(status="failed", error_type=type(exc).__name__)
        raise
    finally:
        artifact["completed_at"] = datetime.now(UTC).isoformat()
        save_artifact(output, artifact)
    print(f"Saved dispatch comparison: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

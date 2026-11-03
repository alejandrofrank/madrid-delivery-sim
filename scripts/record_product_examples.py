"""Capture synthetic page examples in the dedicated local test database.

Only this explicit command creates runs. Reading the resulting JSON never does.
"""

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]


def inventory(url: str) -> dict[str, Any]:
    from delivery.lab import create_lab, run_slice

    run = create_lab(url, seed=42, catalogue_path=ROOT / "data/lab-catalogue.json")
    return run_slice(run, url, playback_seconds=0)


def restaurant(url: str) -> dict[str, Any]:
    from demo_adk_restaurants import configuration

    from delivery.supply import new_supply, run_supply
    from delivery.supply_api import agent_templates, evidence, inspect, order_history

    run = new_supply(configuration("cost"), url)
    state = run_supply(run, url)
    if state["metrics"]["adk_paid_calls"] != 0 or state["metrics"]["model_calls"] != 0:
        raise ValueError("Restaurant example cannot contain paid or external model calls")
    if not all(state["invariants"].values()) or state["metrics"]["delivered"] != 1:
        raise ValueError("Restaurant example must complete its synthetic order")
    captured = evidence(UUID(run))
    if not captured["replay"]["matches"]:
        raise ValueError("Restaurant evidence must reproduce its final state")
    return {
        **captured,
        "order_details": {order["id"]: order_history(UUID(run), order["id"])
                          for order in state["orders"]},
        "agent_details": {agent["agent_id"]: inspect(UUID(run), agent["agent_id"])
                          for agent in state["agents"]},
        "agent_templates": agent_templates(),
    }


def store(url: str) -> dict[str, Any]:
    from fastapi import FastAPI
    from fastapi.encoders import jsonable_encoder
    from httpx import ASGITransport

    from delivery.agent_transport import A2ATransport
    from delivery.dark_store import DarkStore
    from delivery.db import connect
    from delivery.protocol_api import agent_directory
    from delivery.simulation import Simulation, finish_run, initialize, snapshot
    from delivery.store_api import StoreDemo, demo_run

    world = initialize(url)
    run, store_id = demo_run(StoreDemo(seed=42, wall_seconds=60, chaos=True), url)
    app = FastAPI()
    app.mount("/a2a", agent_directory(url))
    transport = A2ATransport("http://localhost:8010", http_transport=ASGITransport(app=app))
    simulation = Simulation(world, url, transport=transport)
    frames = []
    definitions = {}
    with connect(url) as conn:
        conn.execute("UPDATE runs SET status='running' WHERE id=%s", (run,))
    for sim in range(0, 1801, 10):
        simulation.step(run, sim, 42, 1800)
        if sim == 1800:
            finish_run(run, url, store_enabled=True)
        with connect(url) as conn:
            interior = DarkStore().read(conn, run)
        for site in interior["stores"]:
            definitions[site["store"]] = {
                "layout": site.pop("layout"), "catalogue": site.pop("catalogue"),
            }
        city = snapshot(run, url)
        # The original city snapshot includes cumulative decisions. Preserve
        # those once in evidence below instead of repeating them in every frame.
        city.pop("decisions", None)
        frames.append(jsonable_encoder({"time": sim, "city": city, "interior": interior}))
        if sim % 300 == 0:
            print(f"Store recording: {sim}/1800 simulated seconds", flush=True)
    final = frames[-1]
    order = next(order for order in final["city"]["orders"] if order["id"] == "DS-0001")
    stored = next(site for site in final["interior"]["stores"] if site["store"] == store_id)
    basket = next(order for order in stored["orders"] if order["order_id"] == "DS-0001")
    if order["status"] != "delivered" or basket["stage"] != "handed_off":
        raise ValueError("Store example must reach the customer's doorstep")
    if basket["lines"] != basket["picked"]:
        raise ValueError("Store example cannot lose picked items")
    return {"frames": frames, "definitions": definitions, "store": store_id, "order": "DS-0001",
            "decisions": snapshot(run, url)["decisions"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("inventory", "restaurant", "store"), nargs="+",
                        default=["inventory", "restaurant", "store"])
    parser.add_argument("--output", type=Path, default=ROOT / "web/data/examples")
    parser.add_argument("--source-revision", required=True,
                        help="Commit whose simulator is recorded")
    args = parser.parse_args()
    if len(args.source_revision) != 40 or any(c not in "0123456789abcdef"
                                             for c in args.source_revision):
        parser.error("source-revision must be a full Git commit SHA")
    url = os.environ.get("TEST_DATABASE_URL", "")
    # Apply these before importing any modules that select providers.
    os.environ.update(
        DATABASE_URL=url, LLM_PROVIDER="disabled", DELIVERY_CHAOS_PROVIDER="offline",
        DELIVERY_ADK_VERTEX_ENABLED="0", MDS_TELEMETRY_ENABLED="0", MDS_BIGQUERY_ENABLED="0",
        DELIVERY_RUNTIME="local", DELIVERY_AGENT_TRANSPORT="in_process",
    )
    from fastapi.encoders import jsonable_encoder

    from delivery.config import settings
    from delivery.db import connect
    from delivery.product_examples import MAX_EXAMPLE_BYTES, load_example
    from delivery.scenario_evals import require_local_test_database

    require_local_test_database(url)
    settings.cache_clear()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.json"
    manifest = (json.loads(manifest_path.read_text()) if manifest_path.exists()
                else {"schema_version": 1, "examples": {}})
    capture = {"inventory": inventory, "restaurant": restaurant, "store": store}
    for kind in args.only:
        print(f"Recording {kind} from synthetic fixtures...", flush=True)
        data = capture[kind](url)
        state = (data if kind == "inventory" else data["snapshot"] if kind == "restaurant"
                 else data["frames"][-1]["city"])
        with connect(url) as conn:
            requests = conn.execute("SELECT count(*) n FROM llm_requests WHERE run_id=%s",
                                    (state["run"]["id"],)).fetchone()
            if requests["n"]:
                raise ValueError("Recorded example unexpectedly called a model")
        payload = {
            "recording": {
                "schema_version": 1, "kind": kind, "read_only": True, "synthetic": True,
                "paid_model_calls": 0, "recorded_at": datetime.now(UTC).isoformat(),
                "source_revision": args.source_revision,
                "source": ("scripted-offline-adk" if kind == "restaurant"
                           else "seeded-offline-a2a" if kind == "store" else "seeded-offline"),
                "seed": 42,
            },
            "data": jsonable_encoder(data),
        }
        raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False) + "\n").encode()
        if len(raw) > MAX_EXAMPLE_BYTES:
            raise ValueError("Recorded example exceeds its download budget")
        filename = f"{kind}.json"
        (args.output / filename).write_bytes(raw)
        manifest["examples"][kind] = {"file": filename, "bytes": len(raw),
                                      "sha256": hashlib.sha256(raw).hexdigest()}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        load_example(kind, args.output)
        print(f"Saved {kind}: {len(raw):,} bytes; zero paid model calls.", flush=True)


if __name__ == "__main__":
    main()

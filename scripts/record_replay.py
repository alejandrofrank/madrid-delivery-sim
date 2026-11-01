"""Record real seeded A2A shifts in a dedicated local database, with models disabled."""

import argparse
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def record(seed: int, title: str, duration: int, url: str) -> dict:
    from fastapi import FastAPI
    from fastapi.encoders import jsonable_encoder
    from httpx import ASGITransport

    from delivery.agent_transport import A2ATransport
    from delivery.chaos import load_scenario
    from delivery.db import connect
    from delivery.protocol_api import agent_directory
    from delivery.scenario_evals import require_local_test_database
    from delivery.simulation import Simulation, create_run, finish_run, initialize, snapshot

    require_local_test_database(url)
    world = initialize(url)
    app = FastAPI()
    app.mount("/a2a", agent_directory(url))
    transport = A2ATransport("http://localhost:8010", http_transport=ASGITransport(app=app))
    chaos = load_scenario(ROOT / "config/scenarios/chaos-demo.json")
    run = create_run(world, seed, 60, duration, url, chaos=chaos)
    simulation = Simulation(world, url, transport=transport)
    with connect(url) as conn:
        conn.execute("UPDATE runs SET status='running' WHERE id=%s", (run,))
        locations = conn.execute(
            "SELECT id,kind,name,district,ST_X(point) AS lon,ST_Y(point) AS lat "
            "FROM locations ORDER BY id"
        ).fetchall()
    frames = []
    for sim in range(0, duration + 1, 60):
        simulation.step(run, sim, seed, duration)
        if sim == duration:
            finish_run(run, url)
        frame = jsonable_encoder(snapshot(run, url))
        frame["run"]["created_at"] = "2026-10-30T00:00:00Z"
        frames.append(frame)
        if sim % 600 == 0:
            print(f"Seed {seed}: {sim}/{duration} simulated seconds", flush=True)
    with connect(url) as conn:
        calls = conn.execute("SELECT count(*) AS n FROM llm_requests WHERE run_id=%s", (run,))
        assert calls.fetchone()["n"] == 0, "Replay cannot contain paid model calls"
    result = {"schema_version": 1, "title": title, "seed": seed, "source": "seeded-offline-a2a",
              "paid_calls": 0, "scenario": chaos.model_dump(mode="json"), "frames": frames,
              "world": {"locations": locations,
                        "manifest": json.loads((ROOT / "data/manifest.json").read_text())},
              "roads": world.roads()}
    # Stable public identity; no live run identifier or wall timestamps are published.
    stable = str(uuid5(NAMESPACE_URL, f"madrid-delivery-sim/replay/v1/{seed}/{duration}"))
    return json.loads(json.dumps(jsonable_encoder(result)).replace(run, stable))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 73])
    parser.add_argument("--duration", type=int, default=7200)
    args = parser.parse_args()
    if not 4800 <= args.duration <= 43200 or args.duration % 60:
        parser.error("duration must include all demo disruptions and whole simulation minutes")
    os.environ.update(LLM_PROVIDER="disabled", DELIVERY_CHAOS_PROVIDER="offline",
                      DELIVERY_ADK_VERTEX_ENABLED="0", MDS_TELEMETRY_ENABLED="0",
                      MDS_BIGQUERY_ENABLED="0", DELIVERY_RUNTIME="local")
    from delivery.config import settings

    settings.cache_clear()
    directory = ROOT / "data/replays"
    directory.mkdir(exist_ok=True)
    entries = []
    for seed in args.seeds:
        shift = record(seed, f"Madrid chaos shift · seed {seed}", args.duration,
                       os.environ.get("TEST_DATABASE_URL", ""))
        payload = gzip.compress(json.dumps(shift, separators=(",", ":"),
                                           sort_keys=True).encode(), mtime=0)
        filename = f"chaos-{seed}.json.gz"
        (directory / filename).write_bytes(payload)
        entries.append({"file": filename, "sha256": hashlib.sha256(payload).hexdigest()})
    (directory / "manifest.json").write_text(json.dumps({"schema_version": 1,
                                                        "recordings": entries}, indent=2) + "\n")


if __name__ == "__main__":
    main()

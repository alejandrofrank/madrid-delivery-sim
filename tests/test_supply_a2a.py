"""Real process boundary: the A2A server owns scoped restaurant credentials."""

import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from delivery.agent_access import retire_inventory_access
from delivery.agent_transport import A2ATransport
from delivery.db import connect
from delivery.supply import new_supply, run_supply
from delivery.supply_models import SupplyConfig, default_config


@pytest.mark.integration
def test_supply_order_crosses_separate_a2a_process(db_url, monkeypatch):
    base = default_config()
    home = next(e for e in base.entities if e.kind == "household")
    kitchen = next(e for e in base.entities if e.id == "restaurant-pizza")
    shops = [e for e in base.entities if e.kind == "market"]
    # A name absent from the current blueprint must be discovered from the frozen run.
    kitchen = kitchen.model_copy(update={"id": "restaurant-frozen", "node": 1})
    config = SupplyConfig.model_validate(base.model_copy(update={
        "entities": (
            home.model_copy(update={"node": 0, "recipe_ids": ("pizza",)}), kitchen,
            *(e.model_copy(update={"node": i + 2}) for i, e in enumerate(shops)),
        ),
        "start_hour": 12, "duration_minutes": 15,
        "playback_seconds": 0, "calls_per_household": 1,
        "restaurant_stock_servings": 5,
    }).model_dump(mode="json"))
    run = new_supply(config, db_url)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("DELIVERY_A2A_BASE_URL", base_url)
    monkeypatch.setattr(
        "delivery.agent_transport.default_transport", lambda url: A2ATransport(base_url)
    )
    script = """
import os
import uvicorn
from fastapi import FastAPI
from delivery.protocol_api import agent_directory
app = FastAPI()
app.mount('/a2a', agent_directory(os.environ['TEST_DATABASE_URL']))
uvicorn.run(app, host='127.0.0.1', port=int(os.environ['A2A_TEST_PORT']), log_level='warning')
"""
    worker = subprocess.Popen(
        [sys.executable, "-c", script],
        env={**os.environ, "TEST_DATABASE_URL": db_url, "A2A_TEST_PORT": str(port)},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                response = httpx.get(
                    base_url + "/a2a/restaurant-restaurant-frozen/.well-known/agent-card.json",
                    timeout=1,
                )
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert worker.poll() is None, "A2A subprocess stopped before discovery"
            time.sleep(0.1)
        else:
            pytest.fail("A2A subprocess did not publish the frozen restaurant's card")
        state = run_supply(run, db_url)
        assert state["run"]["status"] == "complete"
        assert len(state["orders"]) == 1
        assert state["orders"][0]["status"] == "delivered"
        assert not any(e["state"] == "dead" for e in state["events"])
        # Role capability logins are retired even when they were created remotely.
        with connect(db_url) as conn:
            assert not conn.execute(
                "SELECT 1 FROM pg_roles p JOIN agent_bindings b ON b.login_role=p.rolname "
                "WHERE b.run_id=%s", (run,),
            ).fetchone()
    finally:
        worker.terminate()
        worker.wait(timeout=10)
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            for table in ("supply_requests", "supply_sessions", "decisions", "events"):
                conn.execute(f"DELETE FROM {table} WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))

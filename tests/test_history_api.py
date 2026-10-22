from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import delivery.api as api_module
from delivery.config import settings
from delivery.db import connect
from delivery.history import build_history, history_catalogue, history_manifest

pytestmark = pytest.mark.integration


def test_dated_catalogue_runs_offline_with_separate_store_sources(
    db_url: str, tmp_path: Path, monkeypatch
) -> None:
    sources = {
        "market-a": "supermarket",
        "market-b": "supermarket",
        "market-c": "supermarket",
        "shop-a": "retail",
        "shop-b": "retail",
    }
    rows = [
        {
            "source": source,
            "listing_id": "one",
            "name": f"Product {source}",
            "price": "3.00",
            "currency": "USD",
            "observed_on": "2026-10-22",
            "domain": domain,
            "provenance": "imported",
        }
        for source, domain in sources.items()
    ]
    root = tmp_path / "sample"
    build_history(rows, root, date(2026, 10, 22), date(2026, 10, 23), sources)
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setattr(api_module, "history_catalogue", lambda day: history_catalogue(day, root))
    monkeypatch.setattr(api_module, "history_manifest", lambda: history_manifest(root))
    settings.cache_clear()
    run = None
    try:
        with TestClient(api_module.app) as client:
            history = client.get("/api/lab/history").json()
            assert history["available_days"] == 1
            assert history["days"][1]["status"] == "missing"
            assert (
                client.post("/api/lab/runs", json={"catalogue": "bakiano-history"}).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/lab/runs",
                    json={"catalogue": "bakiano-history", "sample_date": "2026-10-23"},
                ).status_code
                == 404
            )
            response = client.post(
                "/api/lab/runs",
                json={
                    "catalogue": "bakiano-history",
                    "sample_date": "2026-10-22",
                    "playback_seconds": 0,
                },
            )
            assert response.status_code == 202
            run = response.json()["id"]
            state = client.get(f"/api/lab/state?run={run}").json()
            assert state["run"]["status"] == "complete"
            bindings = {s["id"]: s["catalogue_source"] for s in state["city"]["stores"]}
            assert set(bindings.values()) == set(sources)
            assert len(state["stock"]) == 5
            assert all(s["sku"].startswith(bindings[s["store"]] + ":") for s in state["stock"])
            assert state["invariants"]["stock_conserved"]
    finally:
        settings.cache_clear()
        if run:
            with connect(db_url) as conn:
                conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM runs WHERE id=%s", (run,))
            Path(f"artifacts/lab-{run}.json").unlink(missing_ok=True)

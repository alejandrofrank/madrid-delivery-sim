from fastapi.testclient import TestClient

from delivery.api import app
from delivery.config import settings


def test_local_api_contract(db_url: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)
    settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/api/health").json()["graph_nodes"] > 1000
            city = client.get("/api/world").json()
            assert len([x for x in city["locations"] if x["kind"] == "hub"]) == 3
            assert len([x for x in city["locations"] if x["kind"] == "store"]) == 24
            assert len([x for x in city["locations"] if x["kind"] == "customer"]) == 180
            assert client.get("/").status_code == 200
            assert client.get("/api/state?run=not-a-uuid").status_code == 422
            assert client.post("/api/runs", json={"seed": -1}).status_code == 422
            assert (
                client.post(
                    "/api/runs", json={}, headers={"Origin": "https://elsewhere.test"}
                ).status_code
                == 403
            )
            assert "google_credentials" not in client.get("/api/state").text
    finally:
        settings.cache_clear()

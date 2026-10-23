from uuid import uuid4

from fastapi.testclient import TestClient

from delivery.api import app
from delivery.config import settings


def test_delivery_operator_routes(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/delivery-lab").status_code == 200
            assert client.get(f"/api/lab/delivery-runs/{uuid4()}").status_code == 404
            assert client.get("/api/lab/delivery-runs/not-a-uuid").status_code == 422
            assert client.post("/api/lab/delivery-runs", json={"seed": -1}).status_code == 422
            assert (
                client.post(
                    "/api/lab/delivery-runs", json={}, headers={"Origin": "https://elsewhere.test"}
                ).status_code
                == 403
            )
            assert client.get(f"/api/lab/delivery-runs/{uuid4()}/evidence").status_code == 404
    finally:
        settings.cache_clear()

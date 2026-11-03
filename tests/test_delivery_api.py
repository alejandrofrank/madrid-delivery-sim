from uuid import uuid4

from fastapi.testclient import TestClient

from delivery.api import app
from delivery.config import settings


def test_delivery_operator_routes(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    settings.cache_clear()
    try:
        with TestClient(app) as client:
            for path in ("/delivery-lab", f"/delivery-lab?run={uuid4()}"):
                response = client.get(path, follow_redirects=False)
                assert response.status_code == 308
                assert response.headers["location"] == "/watch"
                assert "Madrid operations" in client.get(path).text
            for asset in ("flow.html", "flow.js", "flow.css"):
                assert client.get(f"/static/{asset}").status_code == 404
            config = client.get("/api/lab/city-config").json()
            assert len(config["city"]["nodes"]) == 1024
            assert len(config["defaults"]["stores"]) == 12
            assert (
                client.post("/api/lab/city-runs", json={"traffic_multiplier": 0}).status_code == 422
            )
            assert (
                client.get(f"/api/lab/city-runs/{uuid4()}/agents/inventory:store-1").status_code
                == 404
            )

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

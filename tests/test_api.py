import pytest
from fastapi.testclient import TestClient

from delivery.api import app
from delivery.config import settings


@pytest.mark.parametrize(
    "route", ["/", "/restaurant-lab", "/lab", "/health", "/agent-traces", "/architecture"]
)
def test_workspace_shell_revalidates_after_updates(route: str) -> None:
    client = TestClient(app)
    response = client.get(route)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert "workspace.js?v=" in response.text
    # The HTML policy must not disable caching for versioned assets.
    asset = client.get("/static/workspace.js?v=current")
    assert asset.status_code == 200
    assert asset.headers.get("cache-control") != "no-cache"


def test_local_api_contract(db_url: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)
    settings.cache_clear()
    try:
        with TestClient(app) as client:
            assert client.get("/api/health").json()["graph_nodes"] > 1000
            city = client.get("/api/world").json()
            assert len([x for x in city["locations"] if x["kind"] == "hub"]) == 3
            assert len([x for x in city["locations"] if x["kind"] == "store"]) == 48
            assert len([x for x in city["locations"] if x["kind"] == "customer"]) == 270
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

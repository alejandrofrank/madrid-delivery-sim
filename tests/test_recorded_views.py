"""Read-only examples and public documentation stay grounded in real sources."""
import json
import runpy
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from delivery.public_reference import create_public_reference
from delivery.recorded_api import create_recorded_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(create_recorded_router())
    app.include_router(create_public_reference(Path("web/data/reference")))
    return TestClient(app)


def test_recorded_city_rewinds_without_mutating_source(client: TestClient) -> None:
    first = client.get("/api/recorded/state?t=0").json()
    last = client.get("/api/recorded/state?t=60").json()
    assert last["run"]["status"] == "complete"
    assert last["metrics"]["delivered"] > 0
    assert last["replay"] == {"read_only": True, "seconds": 60.0, "paid_calls": 0}
    assert client.get("/api/recorded/state?t=0").json() == first
    run = last["run"]["id"]
    assert client.get("/api/recorded/runs/" + run + "/chaos?t=60").json()["events"]
    assert client.get("/api/recorded/runs/" + run + "/trace?courier=unknown").json()[
        "decisions"] == []
    assert client.get("/api/recorded/world").json()["locations"]
    assert client.get("/api/recorded/roads").json()["features"]
    assert client.get("/api/recorded/runs").json()


@pytest.mark.parametrize("position", ["-1", "61", "nan", "inf"])
def test_recorded_api_rejects_invalid_positions(client: TestClient, position: str) -> None:
    assert client.get("/api/recorded/state?t=" + position).status_code == 422


@pytest.mark.parametrize("path", ["/api/recorded/state", "/api/recorded/runs",
                                 "/api/agent-anatomy", "/api/documentation/source"])
def test_recorded_reference_has_no_write_routes(client: TestClient, path: str) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert client.request(method, path, json={}).status_code == 405


def test_public_source_only_serves_reviewed_catalogue(client: TestClient) -> None:
    sources = json.loads(Path("web/data/reference/sources.json").read_text())
    path = next(iter(sources))
    assert client.get("/api/documentation/source", params={"path": path}).json() == {
        "path": path, "text": sources[path]}
    for private in ("../.env", ".env", "config/private.json", "/etc/passwd"):
        assert client.get("/api/documentation/source", params={"path": private}).status_code == 404
    assert client.get("/api/agent-anatomy").status_code == 200
    assert client.get("/api/documentation").status_code == 200


def test_public_reference_matches_manifests_and_reviewed_sources() -> None:
    exports = runpy.run_path("scripts/build_public_reference.py")["exports"]()
    for name, expected in exports.items():
        assert json.loads(Path("web/data/reference", name).read_text()) == expected, name

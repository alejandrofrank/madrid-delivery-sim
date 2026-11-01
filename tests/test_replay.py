import gzip
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from delivery.replay import Recordings, create_replay_app


@pytest.fixture
def recording(tmp_path):
    payload = {
        "schema_version": 1, "source": "seeded-offline-a2a", "paid_calls": 0,
        "title": "Seeded shift", "seed": 42, "world": {"locations": []}, "roads": {},
        "frames": [{"run": {"id": "recorded", "sim_time": t,
                             "status": "complete" if t == 120 else "running"},
                    "decisions": [{"order_id": "O-1", "courier_id": "C-1"}],
                    "chaos": {"events": [{"state": "ended" if t == 120 else "active"}]}}
                   for t in (0, 60, 120)],
    }

    def write(value=payload):
        raw = gzip.compress(json.dumps(value).encode(), mtime=0)
        (tmp_path / "shift.json.gz").write_bytes(raw)
        (tmp_path / "manifest.json").write_text(json.dumps({
            "schema_version": 1, "recordings": [{"file": "shift.json.gz",
                                                  "sha256": hashlib.sha256(raw).hexdigest()}]
        }))

    write()
    return tmp_path, payload, write


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@pytest.mark.parametrize("path", ["/api/runs", "/api/supply/runs", "/a2a/dispatcher/",
                                  "/mcp/", "/api/health/check", "/arbitrary-new-endpoint"])
def test_public_replay_denies_every_write(recording, method, path):
    directory, _, _ = recording
    client = TestClient(create_replay_app(directory))
    response = client.request(method, path, json={"run_id": "try-live"})
    assert response.status_code == 405
    assert response.headers["allow"] == "GET, HEAD"


def test_replay_clock_is_stateless_bounded_and_does_not_mutate_recordings(recording):
    directory, _, _ = recording
    client = TestClient(create_replay_app(directory))
    for position, time in [(0, 0), (30, 60), (60, 120), (30, 60), (0, 0)]:
        data = client.get(f"/api/state?t={position}").json()
        assert data["run"]["sim_time"] == time
        assert data["run"]["status"] == ("complete" if position == 60 else "running")
        assert data["replay"]["paid_calls"] == 0
    for value in ("-1", "61", "nan", "inf"):
        assert client.get(f"/api/state?t={value}").status_code == 422
    assert client.get("/api/state?run=live-private-run").status_code == 404
    assert client.get("/api/runs/recorded/trace?courier=another").json()["decisions"] == []
    assert client.get("/api/runs/recorded/chaos?t=60").json()["events"][0]["state"] == "ended"


def test_replay_starts_with_unavailable_live_dependencies(recording, monkeypatch):
    import psycopg

    def forbidden(*a, **kw):
        raise AssertionError("Replay attempted a database connection")

    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setenv("LLM_PROVIDER", "vertex")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unavailable/private")
    client = TestClient(create_replay_app(recording[0]))
    assert client.get("/api/runtime").json()["model_calls"] is False
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.head("/api/health").status_code == 200
    assert client.get("/api/state").status_code == 200
    for path in ("/api/lab/runs", "/api/agents", "/mcp/", "/a2a/dispatcher/",
                 "/api/health/evidence", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_tampered_or_non_reviewed_recording_fails_startup(recording):
    directory, payload, write = recording
    (directory / "shift.json.gz").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash"):
        Recordings(directory)
    payload["paid_calls"] = 1
    write()
    with pytest.raises(ValueError, match="zero-model-call"):
        Recordings(directory)
    payload["paid_calls"] = 0
    payload["frames"][1]["run"]["sim_time"] = 0
    write()
    with pytest.raises(ValueError, match="sequence"):
        Recordings(directory)


def test_shipped_recordings_contain_all_five_chaos_events_and_completed_shifts():
    recordings = Recordings(Path("data/replays"))
    assert len(recordings.shifts) >= 2
    for shift in recordings.shifts.values():
        final = shift["frames"][-1]
        assert final["metrics"]["orders"] > 0
        assert len(final["couriers"]) == 42
        assert {e["kind"] for e in final["chaos"]["events"]} == {
            "heavy_rain", "metro_strike", "restaurant_outage", "courier_offline", "demand_surge"
        }
        assert final["chaos"]["replans"]

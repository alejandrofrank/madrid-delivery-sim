"""Immutable public recordings. No database, queue, cloud SDK or model imports."""

import copy
import gzip
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles


class Recordings:
    def __init__(self, directory: Path) -> None:
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest.get("schema_version") != 1 or not manifest.get("recordings"):
            raise ValueError("A reviewed replay manifest is required")
        self.shifts: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, str]] = {}
        for entry in manifest["recordings"]:
            if not re.fullmatch(r"[a-z0-9-]+\.json\.gz", entry["file"]):
                raise ValueError("Invalid recording filename")
            raw = (directory / entry["file"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("Recording hash mismatch")
            with gzip.open(directory / entry["file"], "rb") as stream:
                payload = stream.read(32 * 1024 * 1024 + 1)
            if len(payload) > 32 * 1024 * 1024:
                raise ValueError("Recording exceeds memory budget")
            shift = json.loads(payload)
            if (shift.get("schema_version") != 1 or shift.get("paid_calls") != 0
                    or shift.get("source") != "seeded-offline-a2a"
                    or not shift.get("frames") or len(shift["frames"]) > 721
                    or shift["frames"][-1]["run"]["status"] != "complete"):
                raise ValueError("Expected a completed zero-model-call seeded recording")
            identifier = shift["frames"][0]["run"]["id"]
            times = [f["run"]["sim_time"] for f in shift["frames"]]
            if (times != sorted(set(times)) or times[0] != 0
                    or any(f["run"]["id"] != identifier for f in shift["frames"])
                    or identifier in self.shifts):
                raise ValueError("Invalid recording frame sequence")
            self.shifts[identifier] = shift
            self.sources[identifier] = {"file": entry["file"], "sha256": entry["sha256"]}

    def shift(self, run: str | None) -> dict[str, Any]:
        if run is None:
            return next(iter(self.shifts.values()))
        if run not in self.shifts:
            raise HTTPException(404, "Unknown recorded shift")
        return self.shifts[run]

    def frame(self, run: str | None, seconds: float) -> dict[str, Any]:
        if not math.isfinite(seconds) or not 0 <= seconds <= 60:
            raise HTTPException(422, "Replay position must be between 0 and 60 seconds")
        frames = self.shift(run)["frames"]
        position = min(len(frames) - 1, int(seconds / 60 * (len(frames) - 1)))
        result: dict[str, Any] = copy.deepcopy(frames[position])
        result["run"].update(wall_seconds=60, status="complete" if seconds == 60 else "running")
        result["replay"] = {"read_only": True, "seconds": seconds, "paid_calls": 0}
        return result


def create_replay_app(
    directory: Path = Path("data/replays"), web: Path = Path("web"),
) -> FastAPI:
    recordings = Recordings(directory)
    app = FastAPI(title="madrid-delivery-sim replay", docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.middleware("http")
    async def read_only(request: Request, call_next: Any) -> Any:
        if request.method not in {"GET", "HEAD"}:
            return JSONResponse({"detail": "Public replay is read-only"}, 405,
                                headers={"Allow": "GET, HEAD"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "public, max-age=60"
        return response

    @app.get("/api/health")
    @app.get("/livez")
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "replay"}

    @app.get("/api/runtime")
    def runtime() -> dict[str, Any]:
        return {"mode": "replay", "read_only": True, "playback_seconds": 60,
                "model_calls": False}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web / "index.html")

    @app.get("/api/world")
    def world() -> Any:
        return recordings.shift(None)["world"]

    @app.get("/api/roads")
    def roads() -> Any:
        return recordings.shift(None)["roads"]

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return [{**s["frames"][-1]["run"], "title": s["title"]}
                for s in recordings.shifts.values()]

    @app.get("/api/state")
    def state(run: str | None = None, t: float = 0) -> dict[str, Any]:
        return recordings.frame(run, t)

    @app.get("/api/runs/{run}/trace")
    def trace(run: str, t: float = 0, courier: str | None = None,
              order: str | None = None) -> dict[str, Any]:
        decisions = recordings.frame(run, t).get("decisions", [])
        return {"events": [], "decisions": [d for d in decisions
                if (courier is None or d.get("courier_id") == courier)
                and (order is None or d.get("order_id") == order)]}

    @app.get("/api/runs/{run}/chaos")
    def chaos(run: str, t: float = 0) -> Any:
        return recordings.frame(run, t)["chaos"]

    app.mount("/static", StaticFiles(directory=web), name="static")
    for route in app.routes:
        if isinstance(route, APIRoute) and route.methods and "GET" in route.methods:
            route.methods.add("HEAD")
    return app

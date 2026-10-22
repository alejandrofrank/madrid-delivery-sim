"""Local operator interface. Never exposes LLM credentials or accepts model tool calls."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.responses import Response

from delivery.db import connect
from delivery.simulation import Simulation, create_run, initialize, snapshot
from delivery.world import DATA, World

world: World


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global world
    world = initialize()
    yield


app = FastAPI(title="Madrid Delivery Sim", lifespan=lifespan)


@app.middleware("http")
async def local_mutations(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "Cross-origin mutations are disabled"}, status_code=403)
    return await call_next(request)


class StartRun(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    wall_seconds: int = Field(default=600, ge=0, le=3600)


def run_background(run: str) -> None:
    try:
        Simulation(world).run(run)
    except Exception:
        # Failure type is already persisted on the run; never log provider credentials.
        pass


@app.get("/api/health")
def health() -> dict[str, Any]:
    with connect() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "graph_nodes": len(world.nodes)}


@app.get("/api/world")
def city() -> dict[str, Any]:
    with connect() as conn:
        locations = conn.execute(
            "SELECT id,kind,name,district,ST_X(point) AS lon,ST_Y(point) AS lat "
            "FROM locations ORDER BY id"
        ).fetchall()
    return {"locations": locations, "manifest": json.loads((DATA / "manifest.json").read_text())}


@app.get("/api/roads")
def roads() -> dict[str, Any]:
    return world.roads()


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    with connect() as conn:
        return conn.execute(
            """SELECT id,status,seed,sim_time,created_at FROM runs WHERE NOT EXISTS
            (SELECT 1 FROM lab_worlds WHERE run_id=runs.id) ORDER BY created_at DESC LIMIT 20"""
        ).fetchall()


@app.post("/api/runs", status_code=202)
def start(body: StartRun, tasks: BackgroundTasks) -> dict[str, str]:
    run = create_run(world, body.seed, body.wall_seconds)
    tasks.add_task(run_background, run)
    return {"id": run}


@app.get("/api/state")
def state(run: UUID | None = None) -> dict[str, Any]:
    return snapshot(str(run) if run else None)


@app.get("/api/runs/{run}/trace")
def decision_trace(
    run: UUID, courier: str | None = None, order: str | None = None
) -> dict[str, Any]:
    with connect() as conn:
        events = conn.execute(
            "SELECT id,topic,producer,trace_id,parent_id,attempts,state,error,"
            "due_sim FROM events WHERE run_id=%s AND (%s::text IS NULL "
            "OR trace_id=%s) ORDER BY id LIMIT 1000",
            (run, order, order),
        ).fetchall()
        decisions = conn.execute(
            """SELECT * FROM decisions WHERE run_id=%s AND (%s::text IS NULL OR courier_id=%s)
               AND (%s::text IS NULL OR order_id=%s) ORDER BY id DESC LIMIT 100""",
            (run, courier, courier, order, order),
        ).fetchall()
    return {"events": events, "decisions": decisions}


@app.get("/")
def index() -> FileResponse:
    return FileResponse("web/index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> None:
    raise HTTPException(status_code=404)


app.mount("/static", StaticFiles(directory="web"), name="static")

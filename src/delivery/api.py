"""Local operator interface. Never exposes LLM credentials or accepts model tool calls."""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.responses import Response

from delivery.city_config import CitySettings
from delivery.db import connect
from delivery.history import history_catalogue, history_manifest
from delivery.lab import create_lab, export_slice, lab_snapshot
from delivery.simulation import Simulation, create_run, initialize, snapshot
from delivery.world import DATA, World

world: World


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global world
    world = initialize()
    yield


app = FastAPI(title="Madrid Delivery Sim", lifespan=lifespan)


class StartLab(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    catalogue: Literal["fixture", "bakiano-local", "bakiano-history"] = "fixture"
    sample_date: date | None = None
    playback_seconds: int = Field(default=15, ge=0, le=120)


@app.get("/api/lab/city-config")
def city_configuration() -> dict[str, Any]:
    from delivery.catalogue import load_catalogue
    from delivery.city import fake_city
    from delivery.city_config import CitySettings
    from delivery.urban_city import urban_city

    return {
        "defaults": CitySettings().model_dump(mode="json"),
        "city": urban_city(fake_city(size=32)),
        "products": load_catalogue(Path("data/expanded-catalogue.json")).model_dump(mode="json")[
            "products"
        ],
    }


def city_background(run: str) -> None:
    from delivery.running_city import run_city

    try:
        result = run_city(run)
        path = Path(f"artifacts/delivery-{run}.json")
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
    except Exception:
        pass  # Runtime persists a sanitized failure type.


class StartDelivery(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    playback_seconds: int = Field(default=12, ge=0, le=120)


@app.post("/api/lab/city-runs", status_code=202)
def start_city(body: CitySettings, tasks: BackgroundTasks) -> dict[str, str]:
    from delivery.running_city import new_city

    run = new_city(body)
    tasks.add_task(city_background, run)
    return {"id": run}


@app.get("/api/lab/city-runs/{run}/agents/{agent_id}")
def inspect_city_agent(run: UUID, agent_id: str) -> dict[str, Any]:
    from delivery.running_city import agent_inspection

    result = agent_inspection(str(run), agent_id)
    if result is None:
        raise HTTPException(404, "Unknown agent in this run")
    return result


@app.get("/delivery-lab")
def delivery_page() -> FileResponse:
    return FileResponse("web/flow.html")


def delivery_background(run: str, seconds: int) -> None:
    from delivery.delivery_flow import export_delivery

    try:
        export_delivery(run, seconds)
    except Exception:
        pass  # Controller persists sanitized error; no credentials in responses.


@app.post("/api/lab/delivery-runs", status_code=202)
def start_delivery(body: StartDelivery, tasks: BackgroundTasks) -> dict[str, str]:
    from delivery.delivery_flow import new_delivery

    run = new_delivery(body.seed)
    tasks.add_task(delivery_background, run, body.playback_seconds)
    return {"id": run}


@app.get("/api/lab/delivery-runs/{run}")
def delivery_state(run: UUID) -> dict[str, Any]:
    from delivery.delivery_flow import flow_snapshot

    state = flow_snapshot(str(run))
    if not state["run"]:
        raise HTTPException(404, "Unknown delivery run")
    return state


@app.get("/api/lab/delivery-runs/{run}/evidence")
def delivery_evidence(run: UUID) -> FileResponse:
    path = Path(f"artifacts/delivery-{run}.json")
    if not path.is_file():
        raise HTTPException(404, "Evidence is available after the scenario completes")
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/lab")
def lab_page() -> FileResponse:
    return FileResponse("web/lab.html")


@app.get("/api/lab/catalogues")
def lab_catalogues() -> dict[str, bool]:
    return {"fixture": True, "bakiano-local": Path("artifacts/daka-snapshot.json").is_file()}


@app.get("/api/lab/history")
def local_history() -> dict[str, Any]:
    try:
        return history_manifest()
    except (ValueError, OSError):
        raise HTTPException(422, "Invalid local history manifest") from None


@app.get("/api/lab/state")
def inventory_state(run: UUID | None = None) -> dict[str, Any]:
    return lab_snapshot(str(run) if run else None)


def lab_background(run: str, seconds: int) -> None:
    try:
        export_slice(run, seconds)
    except Exception:
        # run_slice persists a sanitized failure type; never expose provider/config details.
        pass


@app.post("/api/lab/runs", status_code=202)
def start_lab(body: StartLab, tasks: BackgroundTasks) -> dict[str, str]:
    store_sources = None
    if body.catalogue == "bakiano-history":
        if body.sample_date is None:
            raise HTTPException(422, "Choose an observed sample date")
        try:
            path = history_catalogue(body.sample_date)
            store_sources = history_manifest()["sources"]
        except FileNotFoundError:
            raise HTTPException(
                404, "No observed products for this date; missing days stay missing"
            ) from None
        except (ValueError, OSError):
            raise HTTPException(422, "Local sample validation failed") from None
    else:
        path = (
            Path("data/lab-catalogue.json")
            if body.catalogue == "fixture"
            else Path("artifacts/daka-snapshot.json")
        )
    if not path.is_file():
        raise HTTPException(404, "Import a local Bakiano snapshot first")
    try:
        run = create_lab(seed=body.seed, catalogue_path=path, store_sources=store_sources)
    except ValueError:
        raise HTTPException(422, "Invalid catalogue snapshot") from None
    tasks.add_task(lab_background, run, body.playback_seconds)
    return {"id": run}


@app.get("/api/lab/runs/{run}/evidence")
def lab_evidence(run: UUID) -> FileResponse:
    path = Path(f"artifacts/lab-{run}.json")
    if not path.is_file():
        raise HTTPException(404, "Evidence is available after the scenario completes")
    return FileResponse(path, media_type="application/json", filename=path.name)


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

"""Operator demo plus read-only, bounded store views. Global auth applies."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from delivery.chaos import ChaosConfig, Disruption
from delivery.dark_store import DarkStore
from delivery.db import connect
from delivery.live_jobs import schedule
from delivery.simulation import Simulation, create_run
from delivery.store_layout import StoreConfig
from delivery.store_setup import attach_store_order
from delivery.world import World

router = APIRouter()


class StoreDemo(BaseModel):
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    wall_seconds: int = Field(default=60, ge=0, le=300)
    chaos: bool = False


def demo_run(body: StoreDemo, url: str | None = None) -> tuple[str, str]:
    world = World()
    with connect(url) as conn:
        store = conn.execute(
            "SELECT id,district FROM locations WHERE kind='store' "
            "ORDER BY CASE WHEN lower(name) IN ('mercadona','lidl','dia') "
            "THEN 0 ELSE 1 END,id LIMIT 1"
        ).fetchone()
    if store is None:
        raise ValueError("Madrid locations have not been initialized")
    chaos = (
        ChaosConfig(
            events=[
                Disruption(
                    id="picker-stops",
                    kind="robot_breakdown",
                    at=60,
                    duration=180,
                    target=store["id"],
                )
            ]
        )
        if body.chaos
        else ChaosConfig()
    )
    run = create_run(
        world,
        seed=body.seed,
        wall_seconds=body.wall_seconds,
        duration=1800,
        url=url,
        chaos=chaos,
        dark_store=StoreConfig(stores=(store["id"],)),
    )
    with connect(url) as conn:
        customer = conn.execute(
            "SELECT id FROM locations WHERE kind='customer' AND district=%s ORDER BY id LIMIT 1",
            (store["district"],),
        ).fetchone()
        assert customer
        conn.execute(
            "INSERT INTO orders(run_id,id,store,customer,created_sim,ready_sim,due_sim) "
            "VALUES (%s,'DS-0001',%s,%s,0,0,1800)",
            (run, store["id"], customer["id"]),
        )
        attach_store_order(conn, run, "DS-0001", 0, body.seed)
    return run, store["id"]


def run_demo(run: str) -> None:
    Simulation(World()).run(run)


@router.post("/api/stores/demo", status_code=202)
def start_demo(body: StoreDemo, tasks: BackgroundTasks) -> dict[str, str]:
    run, store = demo_run(body)
    schedule(tasks, run_demo, "orders", run)
    return {"id": run, "store": store, "order": "DS-0001", "provenance": "seeded synthetic demo"}


@router.get("/api/runs/{run}/stores")
def stores(run: UUID, at: int | None = Query(default=None, ge=0, le=43200)) -> dict[str, Any]:
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        if not conn.execute("SELECT 1 FROM runs WHERE id=%s", (run,)).fetchone():
            raise HTTPException(404, "Unknown run")
        state = DarkStore().read(conn, str(run))
        if at is None:
            return state
        frame = conn.execute(
            "SELECT state FROM store_frames WHERE run_id=%s AND sim<=%s ORDER BY sim DESC LIMIT 1",
            (run, at),
        ).fetchone()
        if frame is None:
            raise HTTPException(404, "No store frame at this time")
        layouts = {s["store"]: s for s in state["stores"]}
        state = frame["state"]
        for store in state["stores"]:
            store["layout"] = layouts[store["store"]]["layout"]
            store["catalogue"] = layouts[store["store"]]["catalogue"]
        return state

"""Bounded operator controls and read-only per-disruption evidence."""

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from delivery.chaos import Disruption, evidence, load_scenario, trigger
from delivery.db import connect

router = APIRouter()


@router.get("/api/chaos/demo")
def demo_scenario() -> dict[str, Any]:
    return load_scenario(Path("config/scenarios/chaos-demo.json")).model_dump(mode="json")


@router.get("/api/runs/{run}/chaos")
def chaos_state(run: UUID) -> dict[str, Any]:
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        row = conn.execute("SELECT id FROM runs WHERE id=%s", (run,)).fetchone()
        if not row:
            raise HTTPException(404, "Unknown run")
        return evidence(conn, str(run))


@router.post("/api/runs/{run}/chaos", status_code=202)
def trigger_event(run: UUID, body: Disruption) -> dict[str, str]:
    try:
        trigger(str(run), body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"id": body.id, "state": "scheduled"}

"""Read-only recorded city endpoints available alongside the live workspace."""
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from delivery.replay import Recordings


@lru_cache(maxsize=1)
def recordings() -> Recordings:
    return Recordings(Path("data/replays"))


def create_recorded_router(source: Callable[[], Recordings] = recordings) -> APIRouter:
    router = APIRouter(prefix="/api/recorded", tags=["recorded examples"])

    @router.get("/world")
    def world() -> dict[str, Any]:
        return dict(source().shift(None)["world"])

    @router.get("/roads")
    def roads() -> dict[str, Any]:
        return dict(source().shift(None)["roads"])

    @router.get("/runs")
    def runs() -> list[dict[str, Any]]:
        return [{**shift["frames"][-1]["run"], "title": shift["title"]}
                for shift in source().shifts.values()]

    @router.get("/motion")
    def motion(run: str | None = None) -> dict[str, Any]:
        return source().motion(run)

    @router.get("/state")
    def state(run: str | None = None, t: float = 0) -> dict[str, Any]:
        return source().frame(run, t)

    @router.get("/runs/{run}/trace")
    def trace(run: str, t: float = 0, courier: str | None = None,
              order: str | None = None) -> dict[str, Any]:
        decisions = source().frame(run, t).get("decisions", [])
        return {"events": [], "decisions": [d for d in decisions
                if (courier is None or d.get("courier_id") == courier)
                and (order is None or d.get("order_id") == order)]}

    @router.get("/runs/{run}/chaos")
    def chaos(run: str, t: float = 0) -> dict[str, Any]:
        return dict(source().frame(run, t)["chaos"])

    return router

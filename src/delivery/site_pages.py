"""Product navigation shared by the live app and the read-only replay."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

PAGES = {
    "/watch": "index.html",
    "/agents": "documentation.html",
    "/engineers/restaurants": "supply.html",
    "/engineers/inventory": "lab.html",
    "/engineers/health": "health.html",
    "/engineers/traces": "agent-traces.html",
    "/engineers/architecture": "documentation.html",
}
LEGACY = {
    "/engineers/operations": "/watch",
    "/restaurant-lab": "/engineers/restaurants",
    "/lab": "/engineers/inventory",
    "/health": "/engineers/health",
    "/agent-traces": "/engineers/traces",
}


def create_site_router(web: Path = Path("web")) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    @router.get("/")
    def landing(request: Request) -> Response:
        # Existing city-run bookmarks keep opening the same run.
        if "run" in request.query_params:
            return RedirectResponse("/watch?" + request.url.query, status_code=308)
        return FileResponse(web / "landing.html")

    def page(request: Request) -> FileResponse:
        return FileResponse(web / PAGES[request.url.path])

    def legacy(request: Request) -> RedirectResponse:
        query = "?" + request.url.query if request.url.query else ""
        return RedirectResponse(LEGACY[request.url.path] + query, status_code=308)

    for path in PAGES:
        router.add_api_route(path, page, methods=["GET"])
    for path in LEGACY:
        router.add_api_route(path, legacy, methods=["GET"])

    @router.get("/architecture")
    def architecture(request: Request) -> RedirectResponse:
        anatomy = request.query_params.get("page", "agent-anatomy") == "agent-anatomy"
        target = "/agents" if anatomy else "/engineers/architecture"
        query = "?" + request.url.query if request.url.query else ""
        return RedirectResponse(target + query, status_code=308)

    @router.get("/delivery-lab")
    def retired_grid() -> RedirectResponse:
        # Grid-lab run IDs belong to a different engine; do not reinterpret them.
        return RedirectResponse("/watch", status_code=308)

    return router

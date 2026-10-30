"""Discovery for the agent identities served by this one local application."""

from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount
from starlette.types import Receive, Scope, Send

from delivery.a2a_server import create_a2a_app
from delivery.agent_transport import restaurant_name
from delivery.db import connect
from delivery.supply import blueprint


def agent_names(url: str | None = None) -> list[str]:
    config, _ = blueprint(url)
    names = {restaurant_name(e.id) for e in config.entities if e.kind == "restaurant"}
    with connect(url) as conn:
        names.update(
            restaurant_name(r["id"])
            for r in conn.execute("SELECT id FROM locations WHERE kind='store'").fetchall()
        )
        names.update(
            restaurant_name(r["id"])
            for r in conn.execute(
                "SELECT DISTINCT e.id FROM supply_entities e JOIN runs r ON r.id=e.run_id "
                "WHERE e.kind='restaurant' AND r.status IN ('ready','running')"
            ).fetchall()
        )
    return ["dispatcher", "customer_service", *sorted(names)]


class AgentEndpoint:
    def __init__(self, url: str | None = None) -> None:
        self.url = url
        self.apps: dict[str, Any] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        import asyncio

        name = scope["path_params"]["agent"]
        if name not in self.apps:
            if name not in await asyncio.to_thread(agent_names, self.url):
                await JSONResponse({"detail": "Unknown agent"}, 404)(scope, receive, send)
                return
            self.apps[name] = create_a2a_app(name, url=self.url)
        await self.apps[name](scope, receive, send)


def agent_directory(url: str | None = None) -> Starlette:
    return Starlette(routes=[Mount("/{agent}", app=AgentEndpoint(url))])

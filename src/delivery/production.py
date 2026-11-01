"""Explicit production entry points. Replay never imports the live application."""

import os

from starlette.types import ASGIApp


def create_app() -> ASGIApp:
    mode = os.environ.get("DELIVERY_RUNTIME", "")
    if mode == "replay":
        from delivery.replay import create_replay_app

        return create_replay_app()
    if mode != "live":
        raise ValueError("Production requires an explicit replay or live runtime")
    from delivery.production_auth import AuthPolicy, ProductionAuth

    policy = AuthPolicy.from_env()
    if policy.service_role == "api":
        from delivery.api import app

        return app  # API module installs the same boundary, including direct starts.
    from starlette.applications import Starlette
    from starlette.routing import Mount

    from delivery.protocol_api import agent_directory

    return ProductionAuth(Starlette(routes=[Mount("/a2a", agent_directory())]), policy)

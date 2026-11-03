"""Navigation preserves old entry points without changing API authorization."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from delivery.site_pages import LEGACY, PAGES, create_site_router


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(create_site_router())
    return TestClient(app)


@pytest.mark.parametrize("route", ["/", *PAGES])
def test_product_pages_share_shell_and_tokens(client: TestClient, route: str) -> None:
    response = client.get(route)
    assert response.status_code == 200
    for marker in ('id="workspace-shell"', "/static/tokens.css?v=", "/static/workspace.js?v="):
        assert marker in response.text


@pytest.mark.parametrize("old,new", LEGACY.items())
def test_old_workspace_preserves_query(client: TestClient, old: str, new: str) -> None:
    response = client.get(old + "?run=a%2Fb&order=order-3", follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == new + "?run=a%2Fb&order=order-3"


@pytest.mark.parametrize("old,new", [
    ("/?run=abc&courier=bike-1", "/watch?run=abc&courier=bike-1"),
    ("/architecture?agent=restaurant&part=memory", "/agents?agent=restaurant&part=memory"),
    ("/architecture?page=memory&source=docs%2Fmemory.md",
     "/engineers/architecture?page=memory&source=docs%2Fmemory.md"),
    ("/delivery-lab?run=old-grid", "/watch"),
])
def test_bookmark_semantics(client: TestClient, old: str, new: str) -> None:
    response = client.get(old, follow_redirects=False)
    assert response.status_code == 308
    assert response.headers["location"] == new


def test_landing_is_static_and_uses_existing_role_definitions() -> None:
    import runpy

    build = runpy.run_path("scripts/build_story_agents.py")["build"]
    assert Path("web/data/story-agents.json").read_bytes() == build()
    script = Path("web/landing.js").read_text()
    assert "/api/" not in script
    assert "IntersectionObserver" in script
    assert "visibilitychange" in script
    assert "prefers-reduced-motion" in script

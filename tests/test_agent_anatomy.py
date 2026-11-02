import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict

from delivery.a2a_server import agent_card
from delivery.agent_anatomy import EVAL_ARMS, PARTS, anatomy_data, source_paths
from delivery.agent_specs import load_role
from delivery.api import app
from delivery.role_manifest import manifest_names


@pytest.fixture(scope="module")
def anatomy():
    return anatomy_data()


def test_anatomy_never_accesses_database_provider_or_private_environment(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Anatomy is an offline reference")

    monkeypatch.setattr("delivery.db.connect", forbidden)
    monkeypatch.setattr("google.genai.Client", forbidden)
    monkeypatch.setenv("GEMINI_API_KEY", "private-value-must-not-appear")
    response = TestClient(app).get("/api/agent-anatomy")
    assert response.status_code == 200
    assert "private-value-must-not-appear" not in response.text
    assert response.json()["schema_version"] == 1


def test_every_role_and_all_eleven_parts_are_generated(anatomy):
    assert {a["id"] for a in anatomy["agents"]} == set(manifest_names()) - {"judge-gcp"}
    for agent in anatomy["agents"]:
        role = load_role(agent["id"])
        panels = {p["id"]: p for p in agent["panels"]}
        assert set(panels) == {part[0] for part in PARTS}
        assert agent["mission"] == panels["mission"]["summary"] == role.mission
        assert agent["definition_hash"] == role.digest
        assert role.soul.strip() in panels["persona"]["details"]
        assert panels["tools"]["numbers"]["Manifest tool ceiling"] == len(role.tools)
        for tool in role.tools:
            assert f"{tool}: {role.tool_descriptions[tool]}" in panels["tools"]["details"]
        assert agent["accepts"] == list(role.service_events.get("accepts", role.accepts))
        assert agent["emits"] == list(role.service_events.get("emits", role.emits))
        for panel in panels.values():
            assert panel["summary"] and panel["details"] and panel["numbers"]
            assert panel["sources"] and panel["chapter"]


def test_source_and_chapter_links_are_all_explicitly_catalogued(anatomy):
    manifest = json.loads(Path("config/documentation.json").read_text())
    sources = set(manifest["sources"])
    chapters = {p["id"] for p in manifest["pages"]}
    assert set(source_paths()) <= sources
    for agent in anatomy["agents"]:
        for panel in agent["panels"]:
            assert set(panel["sources"]) <= sources
            assert panel["chapter"] in chapters


def test_cards_match_the_runtime_factory_even_in_live_mode(anatomy, monkeypatch):
    monkeypatch.setenv("DELIVERY_RUNTIME", "live")
    live_reference = anatomy_data()
    assert live_reference == anatomy
    for agent in anatomy["agents"]:
        card = next(p for p in agent["panels"] if p["id"] == "protocols")["card"]
        if agent["id"] in {*EVAL_ARMS, "inventory", "fulfillment"}:
            name = "restaurant-kitchen" if agent["id"] == "restaurant" else agent["id"]
            assert card == MessageToDict(
                agent_card(name, base_url="http://localhost:8010", live=False)
            )
        else:
            assert card is None


def test_event_edges_have_real_manifest_topics(anatomy):
    agents = {a["id"]: a for a in anatomy["agents"]}
    expected = {
        (a["id"], b["id"]): sorted(set(a["emits"]) & set(b["accepts"]))
        for a in agents.values()
        for b in agents.values()
        if a != b
    }
    actual = {
        (e["source"], e["target"]): e["topics"] for e in anatomy["edges"] if e["kind"] == "event"
    }
    assert actual == {key: topics for key, topics in expected.items() if topics}
    assert {e["target"] for e in anatomy["edges"] if e["kind"] == "a2a"} == {
        *EVAL_ARMS,
        "inventory",
        "fulfillment",
    }


def test_eval_results_are_measured_receipts_not_browser_constants(anatomy):
    release = json.loads(Path("docs/evidence/heldout-release.json").read_text())
    assert anatomy["evidence"]["release"] == release
    for agent in anatomy["agents"]:
        panel = next(p for p in agent["panels"] if p["id"] == "evals")
        for result in panel["results"]:
            assert {k: v for k, v in result.items() if k != "arm"} == release["summary"][
                result["arm"]
            ]
    js = Path("web/agent-anatomy.js").read_text()
    assert 'fetch("/api/agent-anatomy"' in js
    assert "role.mission" not in js  # No second manifest stored in the browser.


def test_manifest_edit_propagates_to_page_and_fingerprint(monkeypatch, anatomy):
    from delivery import agent_anatomy

    original = agent_anatomy.load_role

    def modified(name):
        role = original(name)
        return (
            role.model_copy(update={"mission": "A changed, source-backed mission."})
            if (name == "inventory")
            else role
        )

    monkeypatch.setattr(agent_anatomy, "load_role", modified)
    changed = anatomy_data()
    inventory = next(a for a in changed["agents"] if a["id"] == "inventory")
    assert inventory["mission"] == "A changed, source-backed mission."
    assert (
        inventory["definition_hash"]
        != next(a for a in anatomy["agents"] if a["id"] == "inventory")["definition_hash"]
    )


def test_architecture_opens_on_anatomy_and_supports_accessible_controls():
    catalogue = json.loads(Path("config/documentation.json").read_text())
    assert catalogue["pages"][0]["id"] == "agent-anatomy"
    html = TestClient(app).get("/architecture").text
    assert 'id="agent-anatomy"' in html
    js = Path("web/agent-anatomy.js").read_text()
    for behavior in (
        '"tabindex", "0"',
        '"aria-pressed"',
        '"keydown"',
        '"Enter"',
        '"ArrowRight"',
        'node("select")',
        '"role", "status"',
    ):
        assert behavior in js
    css = Path("web/agent-anatomy.css").read_text()
    assert "prefers-reduced-motion: reduce" in css


def test_store_wheels_use_real_layout_defaults(anatomy):
    from delivery.store_layout import StoreLayoutConfig

    config = StoreLayoutConfig()
    for name in ("inventory", "fulfillment", "dispatcher", "courier"):
        agent = next(a for a in anatomy["agents"] if a["id"] == name)
        panel = next(p for p in agent["panels"] if p["id"] == "environment")
        assert panel["numbers"]["Default aisles"] == config.aisles
        assert panel["numbers"]["Packing seconds"] == config.pack_seconds
        assert "src/delivery/dark_store.py" in panel["sources"]

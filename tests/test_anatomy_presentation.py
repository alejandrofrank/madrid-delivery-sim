import copy

import pytest

from delivery import agent_anatomy
from delivery.agent_specs import load_role


@pytest.fixture(scope="module")
def anatomy():
    return agent_anatomy.anatomy_data()


@pytest.mark.parametrize(
    "role",
    [
        "household",
        "restaurant",
        "market",
        "inventory",
        "fulfillment",
        "dispatcher",
        "courier",
        "customer_service",
        "judge",
    ],
)
def test_plain_evidence_and_robot_marks_are_generated_for_each_role(anatomy, role):
    agent = next(a for a in anatomy["agents"] if a["id"] == role)
    manifest = load_role(role)
    assert agent["introduction"].startswith(f"This is the {manifest.display_name} agent.")
    assert {t["id"] for t in agent["tools"]} == set(manifest.tools) | set(manifest.recovery_tools)
    assert {t["id"] for t in agent["tool_badges"]} <= {t["id"] for t in agent["tools"]}
    assert agent["badge"] == manifest.display_name
    for panel in agent["panels"]:
        assert panel["label"] and panel["technical_label"]
        assert panel["headline"]["text"] and panel["headline"]["unit"]
        assert 2 <= len(panel["headline"]["bullets"]) <= 3
        assert [r["value"] for r in panel["number_rows"]] == list(panel["numbers"].values())
        assert all("_" not in r["label"] for r in panel["number_rows"])
    if role != "customer_service":
        assert agent["budget"]["value"] == manifest.limits.model_usd
    assert 0 <= agent["budget"]["fraction"] <= 1


def test_heldout_headlines_weight_actual_cases_and_never_invent_a_role_score(anatomy):
    for agent in anatomy["agents"]:
        panel = next(p for p in agent["panels"] if p["id"] == "evals")
        if panel["results"]:
            cases = sum(r["cases"] for r in panel["results"])
            rate = sum(r["cases"] * r["pass_power_k"] for r in panel["results"]) / cases
            assert panel["headline"]["value"] == f"{rate:.0%}"
            assert "offline" in " ".join(panel["headline"]["bullets"])
        else:
            assert panel["headline"]["value"] == 0
            assert "unseen" not in panel["label"]
            assert "No separate" in panel["headline"]["text"]


def test_changed_limits_and_evidence_reach_the_headline_and_gauge(monkeypatch):
    original_role = agent_anatomy.load_role
    original_json = agent_anatomy.read_json

    def role(name):
        value = original_role(name)
        return (
            value.model_copy(update={"limits": value.limits.model_copy(update={"model_usd": 0.01})})
            if name == "courier"
            else value
        )

    def evidence(path):
        value = copy.deepcopy(original_json(path))
        if path == "docs/evidence/heldout-release.json":
            for row in value["summary"].values():
                row["pass_power_k"] = 0.5
        return value

    monkeypatch.setattr(agent_anatomy, "load_role", role)
    monkeypatch.setattr(agent_anatomy, "read_json", evidence)
    data = agent_anatomy.anatomy_data()
    courier = next(a for a in data["agents"] if a["id"] == "courier")
    assert courier["budget"]["value"] == 0.01
    assert courier["budget"]["fraction"] == 0.5
    assert next(p for p in courier["panels"] if p["id"] == "limits")["headline"]["value"] == "$0.01"
    restaurant = next(a for a in data["agents"] if a["id"] == "restaurant")
    assert next(p for p in restaurant["panels"] if p["id"] == "evals")["headline"]["value"] == "50%"


def test_story_distinguishes_customer_input_agent_work_and_review(anatomy):
    story = anatomy["story"]
    assert [s["agent"] for s in story["steps"]] == [
        None,
        "inventory",
        "fulfillment",
        "dispatcher",
        "courier",
        "judge",
    ]
    assert {s["agent"] for s in story["steps"] if s["agent"]} | {
        s["agent"] for s in story["support"]
    } == {a["id"] for a in anatomy["agents"]}
    assert "controller" in story["note"] and "not live" in story["note"]
    assert {item["kind"] for item in story["legend"]} == {"event", "a2a", "review"}
    assert [s["part"] for s in anatomy["tour"]] == ["mission", "tools", "policy", "evals"]


def test_card_fields_keep_runtime_identity_and_skill_descriptions(anatomy):
    for agent in anatomy["agents"]:
        panel = next(p for p in agent["panels"] if p["id"] == "protocols")
        if card := panel["card"]:
            values = [r["value"] for r in panel["card_fields"]]
            assert card["name"] in values
            for skill in card.get("skills", []):
                assert skill["description"] in values


def test_role_identity_is_distinct_and_covers_the_whole_team(anatomy):
    import re

    visuals = [a["visual"] for a in anatomy["agents"]]
    assert len({v["color"] for v in visuals}) == len(visuals) == 9
    assert len({v["symbol"] for v in visuals}) == len(visuals)
    assert all(re.fullmatch(r"#[0-9a-f]{6}", v["color"]) and v["label"] for v in visuals)
    assert next(a for a in anatomy["agents"] if a["id"] == "judge")["visual"]["symbol"] == "review"

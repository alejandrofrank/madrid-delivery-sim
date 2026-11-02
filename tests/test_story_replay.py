"""The public story must stay small and faithful to the reviewed recording."""

import copy
import gzip
import hashlib
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from delivery.replay import Recordings
from delivery.story_replay import (
    MAP_UNITS,
    MAX_JSON_BYTES,
    build_story_replay,
    check_size,
    encode_story_replay,
    simplify_road,
)


@pytest.fixture(scope="module")
def story():
    return build_story_replay(Path("data/replays"))


@pytest.fixture(scope="module")
def shift():
    return Recordings(Path("data/replays")).shift(None)


def write_recording(directory, shift):
    raw = gzip.compress(json.dumps(shift).encode(), mtime=0)
    (directory / "sample.json.gz").write_bytes(raw)
    (directory / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "recordings": [{"file": "sample.json.gz", "sha256": hashlib.sha256(raw).hexdigest()}],
    }))


def decode_point(story, point):
    west, south, east, north = story["map"]["bounds"]
    return (west + point[0] / MAP_UNITS * (east - west),
            north - point[1] / MAP_UNITS * (north - south))


def assert_same_position(story, point, lon, lat):
    decoded = decode_point(story, point)
    west, south, east, north = story["map"]["bounds"]
    assert abs(decoded[0] - lon) <= (east - west) / MAP_UNITS / 2 + 1e-12
    assert abs(decoded[1] - lat) <= (north - south) / MAP_UNITS / 2 + 1e-12


def test_static_story_export_is_current_deterministic_and_within_download_budget(story):
    raw = encode_story_replay(story)
    check_size(raw)
    assert raw == Path("web/data/story-replay.json").read_bytes()
    assert raw == encode_story_replay(build_story_replay(Path("data/replays")))
    assert len(story["frames"]) == 121
    assert len(story["couriers"]) == 42
    assert len(raw) < MAX_JSON_BYTES
    subprocess.run([sys.executable, "scripts/build_story_replay.py", "--check"], check=True)


def test_story_source_is_hash_verified_and_requires_no_live_services(story, monkeypatch, tmp_path):
    raw = Path("data/replays", story["source"]["file"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == story["source"]["sha256"]
    assert story["source"]["paid_model_calls"] == 0
    assert story["source"]["kind"] == "seeded-offline-a2a"

    def no_network(*args, **kwargs):
        raise AssertionError("Static story tried to contact a service")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unavailable/private")
    monkeypatch.setenv("LLM_PROVIDER", "vertex")
    assert build_story_replay(Path("data/replays")) == story
    (tmp_path / "manifest.json").write_bytes(Path("data/replays/manifest.json").read_bytes())
    (tmp_path / "chaos-42.json.gz").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash"):
        build_story_replay(tmp_path)


def test_story_outcomes_are_recorded_results_not_marketing_constants(story, shift, tmp_path):
    metrics = shift["frames"][-1]["metrics"]
    assert story["outcomes"]["orders"] == metrics["orders"]
    assert story["outcomes"]["on_time"] == metrics["on_time"]
    assert story["outcomes"]["cost_per_delivery_eur"] == metrics["cost_per_delivery_eur"]
    assert story["outcomes"]["resolved_disruptions"] == 5
    changed = copy.deepcopy(shift)
    changed["frames"][-1]["metrics"].update(on_time=69, on_time_pct=97.1831,
                                          cost_per_delivery_eur=2.25)
    changed["frames"][-1]["chaos"]["metrics"][0]["unresolved_orders"] = 1
    write_recording(tmp_path, changed)
    outcome = build_story_replay(tmp_path)["outcomes"]
    assert outcome["on_time"] == 69
    assert outcome["on_time_percent"] == 97.1831
    assert outcome["cost_per_delivery_eur"] == 2.25
    assert outcome["resolved_disruptions"] == 4
    # Cohorts overlap; a resolved-event count must not sum their saved orders.
    assert "do not add cohorts" in outcome["cohort_note"]


def test_story_couriers_keep_actual_routes_waits_and_stationary_states(story, shift):
    has_wait = False
    has_offline = False
    for frame, original in zip(story["frames"], shift["frames"], strict=True):
        assert frame["time"] == original["run"]["sim_time"]
        by_id = {courier["id"]: courier for courier in original["couriers"]}
        for courier, state in zip(story["couriers"], frame["couriers"], strict=True):
            source = by_id[courier["id"]]
            assert_same_position(story, state, source["lon"], source["lat"])
            assert story["statuses"][state[2]] == source["status"]
            if source["status"] in {"idle", "offline", "off_shift"}:
                assert state[3] == -1
                has_offline |= source["status"] == "offline"
            if state[3] >= 0:
                route = story["routes"][state[3]]
                points = source["route"]["points"]
                assert len(route) == len(points)
                for actual, expected in zip(route, points, strict=True):
                    assert_same_position(story, actual, expected[0], expected[1])
                    assert abs(actual[2] - expected[2]) <= .000501
                has_wait |= any(a[:2] == b[:2] and a[2] < b[2]
                                for a, b in zip(route, route[1:], strict=False))
    assert has_wait and has_offline


def test_store_pulses_use_recorded_pickup_ids_even_when_names_repeat(story, shift):
    pickups = {d["order_id"]: d for frame in shift["frames"] for d in frame["decisions"]
               if d["action"] == "picked_up"}
    orders = sorted(shift["frames"][-1]["orders"],
                    key=lambda row: (row["created_sim"], row["id"]))
    assert len(story["orders"]) == len(orders) == 71
    for order, row in zip(orders, story["orders"], strict=True):
        pickup = pickups[order["id"]]
        assert story["map"]["sites"][row["site"]]["id"] == pickup["detail"]["store"]
        assert row["created"] == order["created_sim"]
        assert row["picked_up"] == pickup["sim_time"]
        assert row["delivered"] == order["delivered_sim"]
    names = [site["name"] for site in story["map"]["sites"]]
    assert names.count("Mercadona") > 1


def test_missing_pickup_evidence_is_explicit_instead_of_guessing_a_store(shift, tmp_path):
    changed = copy.deepcopy(shift)
    for frame in changed["frames"]:
        frame["decisions"] = [d for d in frame["decisions"] if d["action"] != "picked_up"]
    write_recording(tmp_path, changed)
    assert all(order["site"] is None and order["picked_up"] is None
               for order in build_story_replay(tmp_path)["orders"])


def test_road_simplification_keeps_corners_and_endpoints():
    assert simplify_road([(0, 0), (5, 1), (10, 0)]) == ((0, 0), (10, 0))
    assert simplify_road([(0, 0), (0, 20), (20, 20)]) == ((0, 0), (0, 20), (20, 20))
    assert simplify_road([(0, 0), (10, 10), (0, 0)]) == ((0, 0), (10, 10), (0, 0))


def test_unknown_states_and_backwards_routes_fail_instead_of_inventing_motion(shift, tmp_path):
    changed = copy.deepcopy(shift)
    changed["frames"][0]["couriers"][0]["status"] = "teleporting"
    write_recording(tmp_path, changed)
    with pytest.raises(ValueError, match="courier status"):
        build_story_replay(tmp_path)
    changed = copy.deepcopy(shift)
    moving = next(c for f in changed["frames"] for c in f["couriers"]
                  if c["status"] == "delivering" and c.get("route"))
    moving["route"]["points"][0][2] = 999999
    write_recording(tmp_path, changed)
    with pytest.raises(ValueError, match="nondecreasing"):
        build_story_replay(tmp_path)


def test_story_export_detects_drift_and_rejects_oversized_data(tmp_path):
    output = tmp_path / "story.json"
    output.write_text("{}")
    checked = subprocess.run(
        [sys.executable, "scripts/build_story_replay.py", "--check", "--output", str(output)],
        capture_output=True, text=True,
    )
    assert checked.returncode != 0
    assert "drifted" in checked.stderr
    with pytest.raises(ValueError, match="budget"):
        check_size(b"x" * (MAX_JSON_BYTES + 1))

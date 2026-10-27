"""Supply operator and agent HTTP boundaries using the dedicated local database."""

import hashlib
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import delivery.api as api
import delivery.supply as supply
import delivery.supply_api as routes
from delivery.agent_access import retire_inventory_access
from delivery.agent_runtime import LocalAgent
from delivery.config import settings
from delivery.db import connect
from delivery.supply_models import SupplyConfig, default_config
from delivery.supply_search import JevClient

pytestmark = pytest.mark.integration
OPERATOR_KEY = "synthetic-supply-api-test-operator"


def minimal_config() -> SupplyConfig:
    raw = default_config().model_dump(mode="json")
    homes = [e for e in raw["entities"] if e["kind"] == "household"][:2]
    kitchen = next(e for e in raw["entities"] if e["id"] == "restaurant-pizza")
    markets = [e for e in raw["entities"] if e["kind"] == "market"]
    for home in homes:
        home.update(node=0, recipe_ids=["pizza"])
    kitchen["node"] = 1
    for index, market in enumerate(markets):
        market["node"] = index + 2
    raw.update(
        entities=homes + [kitchen] + markets,
        start_hour=12,
        duration_minutes=15,
        playback_seconds=0,
        calls_per_household=1,
    )
    return SupplyConfig.model_validate(raw)


@dataclass
class SupplyAPI:
    client: TestClient
    url: str
    config: SupplyConfig
    runs: list[str] = field(default_factory=list)

    def start(self) -> str:
        revision = self.client.get("/api/supply/blueprint").json()["revision"]
        response = self.client.post("/api/supply/runs", json={"revision": revision})
        assert response.status_code == 202
        run = response.json()["id"]
        self.runs.append(run)
        return run

    def open(self, run: str, agent: LocalAgent) -> dict[str, str]:
        response = self.client.post(
            f"/api/supply/runs/{run}/agents/{agent.scope.agent_id}/channel",
            headers={"X-Operator-Key": OPERATOR_KEY},
        )
        assert response.status_code == 200
        assert response.json()["transport"] == "durable_queue"
        return {"Authorization": "Bearer " + response.json()["token"]}

    def release(self, run: str) -> None:
        with connect(self.url) as conn:
            schedule = conn.execute(
                "SELECT config->'schedule' schedule FROM supply_sessions WHERE run_id=%s",
                (run,),
            ).fetchone()["schedule"]
            conn.execute("UPDATE runs SET sim_time=900 WHERE id=%s", (run,))
        supply.release_calls(run, schedule, 900, self.url)

    def claim(self, run: str, agent: LocalAgent, auth: dict[str, str]) -> dict[str, Any]:
        response = self.client.post(
            f"/api/supply/runs/{run}/agents/{agent.scope.agent_id}/claim",
            headers=auth,
        )
        assert response.status_code == 200
        event = response.json()["event"]
        assert event is not None
        return event


@pytest.fixture
def supply_api(db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[SupplyAPI]:
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("DELIVERY_OPERATOR_KEY", raising=False)
    monkeypatch.delenv("DELIVERY_JEV_ENABLED", raising=False)
    monkeypatch.setattr(routes, "background", lambda run: None)
    settings.cache_clear()
    config = minimal_config()
    with connect(db_url) as conn:
        previous = conn.execute("SELECT * FROM supply_blueprints WHERE id='default'").fetchone()
        conn.execute(
            """INSERT INTO supply_blueprints VALUES('default',%s,%s)
            ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,config=excluded.config""",
            (config.digest, Jsonb(config.model_dump(mode="json"))),
        )
    harness: SupplyAPI | None = None
    try:
        with TestClient(api.app) as client:
            harness = SupplyAPI(client, db_url, config)
            yield harness
    finally:
        runs = set(harness.runs if harness else [])
        with supply._LOCK:
            for key in list(supply._AGENTS):
                if key[0] in runs:
                    del supply._AGENTS[key]
            for token, grant in list(supply._TOKENS.items()):
                if grant[0] in runs:
                    del supply._TOKENS[token]
        for key in list(routes._LEASES):
            if key[0] in runs:
                del routes._LEASES[key]
        for run in runs:
            retire_inventory_access(run, db_url)
            with connect(db_url) as conn:
                conn.execute("DELETE FROM supply_sessions WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
                conn.execute("DELETE FROM runs WHERE id=%s", (run,))
        with connect(db_url) as conn:
            if previous:
                conn.execute(
                    """INSERT INTO supply_blueprints VALUES('default',%s,%s)
                    ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,
                    config=excluded.config""",
                    (previous["revision"], Jsonb(previous["config"])),
                )
            else:
                conn.execute("DELETE FROM supply_blueprints WHERE id='default'")
        settings.cache_clear()


def envelope(event: dict[str, Any]) -> dict[str, Any]:
    return {key: event[key] for key in ("event_id", "lease_token", "attempt")}


def test_complete_order_history_is_scoped_and_not_a_recent_event_window(
    supply_api: SupplyAPI,
) -> None:
    run = supply_api.start()
    state = supply.run_supply(run, supply_api.url)
    order, other = state["orders"]
    with connect(supply_api.url) as conn:
        conn.execute(
            "INSERT INTO events(run_id,producer,topic,payload,dedupe_key,trace_id) "
            "SELECT %s,'test','test.history',jsonb_build_object('order',%s::text),"
            "'history-'||n,%s FROM generate_series(1,1002) n",
            (run, order["id"], order["id"]),
        )
    response = supply_api.client.get(f"/api/supply/runs/{run}/orders/{order['id']}")
    assert response.status_code == 200
    history = response.json()
    assert history["order"]["id"] == order["id"]
    assert history["call"]["order_id"] == order["id"] and history["call"]["transcript"]
    assert len(history["events"]) > 1002
    assert any(event["topic"] == "household.intent" for event in history["events"])
    assert all(event["trace_id"] == order["id"] for event in history["events"])
    assert all("lease_token" not in event for event in history["events"])
    assert all(fact["detail"]["order"] == order["id"] for fact in history["facts"])
    assert history["memory_history_complete"] and history["memory_history"]
    assert all(write["context_id"] == order["id"] for write in history["memory_history"])
    assert history["typed_memory"] and all(
        f["context_id"] == order["id"] for f in history["typed_memory"]
    )
    assert all(
        f["event_id"] in {e["id"] for e in history["events"]} for f in history["typed_memory"]
    )
    assert all("previous" in write for write in history["memory_history"])
    assert len(history["conversation"]) == len(history["events"])
    call = next(m for m in history["conversation"] if m["topic"] == "household.call")
    assert call["text"] == history["call"]["transcript"]
    assert call["sender"]["role"] == "Customer agent" and call["time_kind"] == "sent"
    assert call["recipient"]["role"] == "Kitchen agent"
    arrivals = [m for m in history["conversation"] if m["topic"] == "delivery.arrived"]
    assert arrivals and all(m["sender"]["id"] == "lab_world" for m in arrivals)
    assert all(m["time_kind"] == "due" for m in arrivals)
    changes = [w for m in history["conversation"] for w in m["memory"]]
    assert changes and any(w["mode"] == "created" for w in changes)
    assert any(w["mode"] == "updated" for w in changes)
    assert all(request["order_id"] == order["id"] for request in history["requests"])
    event_ids = {event["id"] for event in history["events"]}
    assert all(decision["event_id"] in event_ids for decision in history["decisions"])
    assert other["id"] not in {event["trace_id"] for event in history["events"]}
    # The recorded writes survive deletion of live TTL memory.
    with connect(supply_api.url) as conn:
        conn.execute("DELETE FROM agent_memory_facts WHERE run_id=%s", (run,))
    retained = supply_api.client.get(f"/api/supply/runs/{run}/orders/{order['id']}").json()
    assert not retained["memories"]
    assert [w["body"] for w in retained["memory_history"]] == [
        w["body"] for w in history["memory_history"]
    ]
    assert "postgresql://" not in response.text and "password" not in response.text


def test_order_history_marks_legacy_memory_and_rejects_unknown_scopes(
    supply_api: SupplyAPI,
) -> None:
    run = supply_api.start()
    state = supply.run_supply(run, supply_api.url)
    order_id = state["orders"][0]["id"]
    with connect(supply_api.url) as conn:
        conn.execute("UPDATE decisions SET detail=detail-'memory_writes' WHERE run_id=%s", (run,))
    history = supply_api.client.get(f"/api/supply/runs/{run}/orders/{order_id}").json()
    assert not history["memory_history_complete"] and history["memory_history"] == []
    assert history["decisions"] and history["events"]
    assert all(w["mode"] == "unknown" for m in history["conversation"] for w in m["memory"])
    for path in (
        f"/api/supply/runs/{uuid4()}/orders/{order_id}",
        f"/api/supply/runs/{run}/orders/unknown-order",
    ):
        assert supply_api.client.get(path).status_code == 404
    assert supply_api.client.get(f"/api/supply/runs/{run}/orders/" + "x" * 201).status_code == 422


def test_blueprint_compare_and_swap_validation_and_frozen_run_config(supply_api: SupplyAPI) -> None:
    client = supply_api.client
    initial = client.get("/api/supply/blueprint")
    assert initial.status_code == 200
    original = initial.json()
    assert original["config"] == supply_api.config.model_dump(mode="json")
    assert len(original["revision"]) == 64
    assert len(original["city"]["nodes"]) == 1024
    assert client.put("/api/supply/blueprint", json=original["config"]).status_code == 428
    assert (
        client.put(
            "/api/supply/blueprint",
            json=original["config"],
            headers={"If-Match": "0" * 64},
        ).status_code
        == 409
    )
    for invalid in (
        {**original["config"], "run_id": str(uuid4())},
        {**original["config"], "communication_latency_seconds": -1},
        {
            **original["config"],
            "entities": [
                {**entity, **({"tools": ["sql.query"]} if index == 0 else {})}
                for index, entity in enumerate(original["config"]["entities"])
            ],
        },
        {
            **original["config"],
            "agents": {
                role: {
                    **definition,
                    "search": {**definition["search"], "api_key": "synthetic-not-accepted"},
                }
                for role, definition in original["config"]["agents"].items()
            },
        },
    ):
        assert (
            client.put(
                "/api/supply/blueprint",
                json=invalid,
                headers={"If-Match": original["revision"]},
            ).status_code
            == 422
        )
    assert client.post("/api/supply/runs", json={"revision": "short"}).status_code == 422
    run = supply_api.start()
    updated = {**original["config"], "communication_latency_seconds": 17}
    saved = client.put(
        "/api/supply/blueprint",
        json=updated,
        headers={"If-Match": '"' + original["revision"] + '"'},
    )
    assert saved.status_code == 200 and saved.json()["revision"] != original["revision"]
    assert (
        client.put(
            "/api/supply/blueprint",
            json=updated,
            headers={"If-Match": original["revision"]},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/supply/runs",
            json={"revision": original["revision"]},
        ).status_code
        == 409
    )
    old = client.get(f"/api/supply/runs/{run}")
    assert old.status_code == 200
    assert old.json()["run"]["status"] == "ready"  # Background explicitly disabled.
    assert old.json()["config"]["communication_latency_seconds"] == 5
    newer = supply_api.start()
    assert (
        client.get(f"/api/supply/runs/{newer}").json()["config"]["communication_latency_seconds"]
        == 17
    )
    with connect(supply_api.url) as conn:
        conn.execute(
            "INSERT INTO events(run_id,producer,topic,payload,dedupe_key,trace_id) "
            "SELECT %s,'test','test.audit','{}',n::text,'synthetic-audit' "
            "FROM generate_series(1,1001) n",
            (run,),
        )
    evidence = client.get(f"/api/supply/runs/{run}/evidence")
    assert evidence.status_code == 200 and evidence.json()["replay"]["matches"]
    assert len(evidence.json()["events"]) == 1001
    assert len(evidence.json()["snapshot"]["events"]) == 1000
    assert evidence.json()["live_capture"]
    assert set(evidence.json()["search"]) == {"budgets", "calls", "audits"}
    assert all("lease_token" not in event for event in evidence.json()["events"])
    assert "postgresql://" not in evidence.text and "password" not in evidence.text
    assert client.get(f"/api/supply/runs/{uuid4()}").status_code == 404
    assert client.get(f"/api/supply/runs/{uuid4()}/replay").status_code == 404
    assert client.get("/api/supply/runs/not-a-uuid").status_code == 422


def test_supply_routes_enforce_local_host_and_same_origin_mutations(supply_api: SupplyAPI) -> None:
    client = supply_api.client
    assert (
        client.get("/api/supply/blueprint", headers={"Host": "elsewhere.test"}).status_code == 403
    )
    assert client.get("/api/supply/blueprint", headers={"Host": "localhost"}).status_code == 200
    revision = client.get("/api/supply/blueprint").json()["revision"]
    assert (
        client.post(
            "/api/supply/runs",
            json={"revision": revision},
            headers={"Origin": "https://elsewhere.test"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            "/api/supply/blueprint",
            json=supply_api.config.model_dump(mode="json"),
            headers={"If-Match": revision, "Origin": "http://testserver.evil"},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/supply/runs",
        json={"revision": revision},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 202
    supply_api.runs.append(response.json()["id"])


def test_channels_require_operator_authorization_and_bind_bearers_to_run_and_agent(
    supply_api: SupplyAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = supply_api.start()
    agents = supply.provision(run, supply_api.url)
    homes = [agent for agent in agents.values() if agent.role.name == "household"]
    agent = homes[0]
    path = f"/api/supply/runs/{run}/agents/{agent.scope.agent_id}"
    client = supply_api.client
    assert client.post(path + "/channel").status_code == 503
    monkeypatch.setenv("DELIVERY_OPERATOR_KEY", OPERATOR_KEY)
    assert client.post(path + "/channel").status_code == 403
    assert client.post(path + "/channel", headers={"X-Operator-Key": "wrong"}).status_code == 403
    assert (
        client.post(
            f"/api/supply/runs/{run}/agents/household:inactive/channel",
            headers={"X-Operator-Key": OPERATOR_KEY},
        ).status_code
        == 409
    )
    auth = supply_api.open(run, agent)
    assert client.post(path + "/claim").status_code == 401
    assert (
        client.post(path + "/claim", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )
    assert (
        client.get(
            f"/api/supply/runs/{run}/agents/{homes[1].scope.agent_id}/memory",
            headers=auth,
        ).status_code
        == 401
    )
    other_run = supply_api.start()
    assert (
        client.get(
            f"/api/supply/runs/{other_run}/agents/{agent.scope.agent_id}/memory",
            headers=auth,
        ).status_code
        == 401
    )
    assert client.post(path + "/claim", headers=auth).json() == {"event": None}
    assert client.get(path + "/memory", headers=auth).status_code == 410
    token = auth["Authorization"].removeprefix("Bearer ")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with supply._LOCK:
        grant = supply._TOKENS[token_hash]
        supply._TOKENS[token_hash] = (grant[0], grant[1], time.monotonic() - 1)
    assert client.post(path + "/claim", headers=auth).status_code == 401


def test_calls_and_messages_accept_only_claimed_envelopes_and_queue_domain_replies(
    supply_api: SupplyAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DELIVERY_OPERATOR_KEY", OPERATOR_KEY)
    run = supply_api.start()
    agents = supply.provision(run, supply_api.url)
    homes = [a for a in agents.values() if a.role.name == "household"]
    kitchen = agents["restaurant-pizza"]
    auth = {a.scope.agent_id: supply_api.open(run, a) for a in [*homes, kitchen]}
    supply_api.release(run)
    home, peer = homes
    event = supply_api.claim(run, home, auth[home.scope.agent_id])
    assert event["topic"] == "household.intent"
    body = envelope(event)
    root = f"/api/supply/runs/{run}/agents/"
    home_path = root + home.scope.agent_id
    client = supply_api.client
    assert (
        client.post(
            home_path + "/calls",
            json={**body, "recipient": "market-b", "meal": "sushi"},
            headers=auth[home.scope.agent_id],
        ).status_code
        == 422
    )
    for invalid in (
        {**body, "lease_token": str(uuid4())},
        {**body, "attempt": body["attempt"] + 1},
    ):
        assert (
            client.post(
                home_path + "/calls", json=invalid, headers=auth[home.scope.agent_id]
            ).status_code
            == 409
        )
    assert (
        client.post(
            root + peer.scope.agent_id + "/messages", json=body, headers=auth[peer.scope.agent_id]
        ).status_code
        == 409
    )
    assert (
        client.post(
            root + kitchen.scope.agent_id + "/calls",
            json=body,
            headers=auth[kitchen.scope.agent_id],
        ).status_code
        == 403
    )
    response = client.post(home_path + "/calls", json=body, headers=auth[home.scope.agent_id])
    assert response.status_code == 200
    assert response.json()["acknowledged"] and response.json()["communication"] == "queued_call"
    assert (
        client.post(
            home_path + "/messages", json=body, headers=auth[home.scope.agent_id]
        ).status_code
        == 409
    )
    own = client.get(f"/api/supply/runs/{run}/orders/{event['trace_id']}").json()["typed_memory"]
    assert own and own[0]["body"]["status"] == "calling"
    assert (
        client.get(
            root + peer.scope.agent_id + "/memory", headers=auth[peer.scope.agent_id]
        ).status_code
        == 410
    )
    with connect(supply_api.url) as conn:
        outgoing = conn.execute(
            "SELECT topic,target_store,trace_id FROM events WHERE parent_id=%s",
            (body["event_id"],),
        ).fetchall()
        assert outgoing == [
            {
                "topic": "household.call",
                "target_store": kitchen.scope.store,
                "trace_id": event["trace_id"],
            }
        ]
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_facts WHERE event_id=%s",
                (body["event_id"],),
            ).fetchone()["n"]
            == 1
        )
        conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run,))
    incoming = supply_api.claim(run, kitchen, auth[kitchen.scope.agent_id])
    kitchen_path = root + kitchen.scope.agent_id
    assert (
        client.post(
            kitchen_path + "/calls", json=envelope(incoming), headers=auth[kitchen.scope.agent_id]
        ).status_code
        == 403
    )
    assert (
        client.post(
            kitchen_path + "/messages",
            json={**envelope(incoming), "action": "cook"},
            headers=auth[kitchen.scope.agent_id],
        ).status_code
        == 422
    )
    assert client.post(
        kitchen_path + "/messages", json=envelope(incoming), headers=auth[kitchen.scope.agent_id]
    ).json()["acknowledged"]
    expired = supply_api.claim(run, peer, auth[peer.scope.agent_id])
    with connect(supply_api.url) as conn:
        conn.execute(
            "UPDATE events SET lease_until=now()-interval '1 second' WHERE id=%s",
            (expired["event_id"],),
        )
    rejected = client.post(
        root + peer.scope.agent_id + "/messages",
        json=envelope(expired),
        headers=auth[peer.scope.agent_id],
    )
    assert rejected.status_code == 200 and not rejected.json()["acknowledged"]
    with connect(supply_api.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_facts WHERE event_id=%s",
                (expired["event_id"],),
            ).fetchone()["n"]
            == 0
        )


def test_agent_recall_requires_current_lease_and_cannot_choose_another_order(
    supply_api: SupplyAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DELIVERY_OPERATOR_KEY", OPERATOR_KEY)
    run = supply_api.start()
    agents = supply.provision(run, supply_api.url)
    home, peer = [a for a in agents.values() if a.role.name == "household"]
    auth = supply_api.open(run, home)
    other_auth = supply_api.open(run, peer)
    supply_api.release(run)
    event = supply_api.claim(run, home, auth)
    other = supply_api.claim(run, peer, other_auth)
    root = f"/api/supply/runs/{run}/agents/{home.scope.agent_id}"
    client = supply_api.client
    assert client.get(root + "/memory", headers=auth).status_code == 410
    for body, expected in [
        ({**envelope(event), "order": other["trace_id"]}, 422),
        ({**envelope(event), "limit": 17}, 422),
        ({**envelope(event), "limit": True}, 422),
        ({**envelope(event), "kinds": ["market.request"]}, 422),
        (envelope(other), 409),
    ]:
        assert client.post(root + "/memory/recall", json=body, headers=auth).status_code == expected
    assert (
        client.post(root + "/memory/recall", json=envelope(event), headers=other_auth).status_code
        == 401
    )
    response = client.post(
        root + "/memory/recall",
        json={**envelope(event), "kinds": ["household.order"]},
        headers=auth,
    )
    assert response.status_code == 200 and response.json()["memory"] == []
    assert response.json()["scope"] == "current_incoming_order"
    assert client.post(root + "/calls", json=envelope(event), headers=auth).json()["acknowledged"]
    assert (
        client.post(root + "/memory/recall", json=envelope(event), headers=auth).status_code == 409
    )


def test_agent_search_defaults_to_local_and_rejects_wrong_scope_and_arbitrary_arguments(
    supply_api: SupplyAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DELIVERY_OPERATOR_KEY", OPERATOR_KEY)

    def no_provider(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("API tests never invoke a provider")

    monkeypatch.setattr(JevClient, "__call__", no_provider)
    run = supply_api.start()
    agents = supply.provision(run, supply_api.url)
    homes = [a for a in agents.values() if a.role.name == "household"]
    kitchen = agents["restaurant-pizza"]
    home_auth = supply_api.open(run, homes[0])
    peer_auth = supply_api.open(run, homes[1])
    kitchen_auth = supply_api.open(run, kitchen)
    supply_api.release(run)
    home_event = supply_api.claim(run, homes[0], home_auth)
    peer_event = supply_api.claim(run, homes[1], peer_auth)
    root = f"/api/supply/runs/{run}/agents/"
    assert (
        supply_api.client.post(
            root + homes[1].scope.agent_id + "/search",
            json={**envelope(peer_event), "query": "flour"},
            headers=peer_auth,
        ).status_code
        == 403
    )
    assert supply_api.client.post(
        root + homes[0].scope.agent_id + "/calls",
        json=envelope(home_event),
        headers=home_auth,
    ).json()["acknowledged"]
    with connect(supply_api.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run,))
    event = supply_api.claim(run, kitchen, kitchen_auth)
    path = root + kitchen.scope.agent_id + "/search"
    query = {**envelope(event), "query": "Harina"}
    assert supply_api.client.post(path, json=query).status_code == 401
    assert supply_api.client.post(path, json=query, headers=home_auth).status_code == 401
    assert (
        supply_api.client.post(
            path, json={**query, "lease_token": str(uuid4())}, headers=kitchen_auth
        ).status_code
        == 409
    )
    for invalid in (
        {**query, "owner": "market-b"},
        {**query, "mode": "anything"},
        {**query, "query": "x" * 81},
        {**query, "query": "!!!"},
    ):
        assert supply_api.client.post(path, json=invalid, headers=kitchen_auth).status_code == 422
    result = supply_api.client.post(path, json=query, headers=kitchen_auth)
    assert result.status_code == 200
    assert result.json()["provider"] == "local" and result.json()["calls"] == 0
    assert result.json()["results"][0]["id"] == "flour"
    assert result.json()["results"][0]["available"] == 0
    assert not result.json()["availability_is_reservation"]
    assert (
        supply_api.client.post(
            path, json={**query, "mode": "jev"}, headers=kitchen_auth
        ).status_code
        == 403
    )
    operator = supply_api.client.get(
        f"/api/supply/runs/{run}/entities/restaurant-pizza/search",
        params={"query": "Harina"},
    )
    assert operator.status_code == 200
    assert operator.json()["provider"] == "local" and operator.json()["calls"] == 0
    assert operator.json()["availability"] == "observation_not_reservation"
    with connect(supply_api.url) as conn:
        conn.execute(
            "UPDATE events SET lease_until=now()-interval '1 second' WHERE id=%s",
            (event["event_id"],),
        )
    assert supply_api.client.post(path, json=query, headers=kitchen_auth).status_code == 403

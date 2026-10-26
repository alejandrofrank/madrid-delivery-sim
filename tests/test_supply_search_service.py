"""Real scoped SQL accounting; optional relevance reviews are always mocked."""

import json
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

import delivery.supply as supply
import delivery.supply_api as supply_routes
from delivery.agent_access import retire_inventory_access
from delivery.agent_runtime import LocalAgent
from delivery.db import connect
from delivery.queue import Event
from delivery.supply import new_supply, provision, release_calls
from delivery.supply_models import SupplyConfig, default_config
from delivery.supply_search import JevClient
from delivery.supply_search_service import search_for_agent

pytestmark = pytest.mark.integration


@dataclass
class SearchRun:
    run: str
    url: str
    agents: dict[str, LocalAgent]
    agent: LocalAgent
    events: list[Event]


@pytest.fixture
def search_run(db_url: str) -> Iterator[Callable[..., SearchRun]]:
    runs: list[str] = []

    def create(
        *,
        role: str = "restaurant",
        provider: str = "local",
        calls: int = 0,
        households: int = 1,
        tool_slots: int = 5,
        empty_flour: bool = False,
    ) -> SearchRun:
        raw = default_config().model_dump(mode="json")
        homes = [e for e in raw["entities"] if e["kind"] == "household"][:households]
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
        for definition in raw["agents"].values():
            definition["search"] = {
                "provider": provider,
                "calls_limit": calls,
                "input_tokens_limit": 51200 if provider == "jev" else 0,
            }
            definition["limits"]["tool_calls_per_event"] = tool_slots
        config = SupplyConfig.model_validate(raw)
        run = new_supply(config, db_url)
        runs.append(run)
        if empty_flour:
            with connect(db_url) as conn:
                conn.execute(
                    """UPDATE supply_stock SET on_hand=0 WHERE run_id=%s
                    AND owner='market-a' AND ingredient='flour'""",
                    (run,),
                )
        agents = provision(run, db_url)
        with connect(db_url) as conn:
            schedule = conn.execute(
                "SELECT config->'schedule' schedule FROM supply_sessions WHERE run_id=%s",
                (run,),
            ).fetchone()["schedule"]
            conn.execute("UPDATE runs SET sim_time=900 WHERE id=%s", (run,))
        release_calls(run, schedule, 900, db_url)
        for home in homes:
            agent = agents[home["id"]]
            event = agent.claim()
            assert event is not None and agent.process(event)
        with connect(db_url) as conn:
            conn.execute("UPDATE runs SET sim_time=1000 WHERE id=%s", (run,))
        agent = agents[kitchen["id"]]
        events = [agent.claim() for _ in homes]
        assert all(event is not None for event in events)
        if role == "market":
            for event in events:
                assert event is not None and agent.process(event)
            with connect(db_url) as conn:
                conn.execute("UPDATE runs SET sim_time=1100 WHERE id=%s", (run,))
            agent = agents["market-a"]
            events = [agent.claim()]
            assert events[0] is not None
        return SearchRun(run, db_url, agents, agent, [e for e in events if e is not None])

    yield create
    for run in runs:
        with supply._LOCK:
            for key in list(supply._AGENTS):
                if key[0] == run:
                    del supply._AGENTS[key]
            for token, grant in list(supply._TOKENS.items()):
                if grant[0] == run:
                    del supply._TOKENS[token]
            for key in list(supply.CHANNEL_LEASES):
                if key[0] == run:
                    del supply.CHANNEL_LEASES[key]
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            # 012 fixes the cascading domain references as well as event/fact
            # cleanup. Real requests and facts exist in each market fixture.
            conn.execute("DELETE FROM supply_sessions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))


@pytest.fixture
def jev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DELIVERY_JEV_ENABLED", "1")
    monkeypatch.setenv("TYPESAFE_MODEL", "jev-test")
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-test-key-never-sent")


def review(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": payload["model"],
        "answers": {
            key: {
                "choice": "yes" if q["instructions"]["candidate"] == "Flour" else "no",
                "confidence": 0.9,
            }
            for key, q in payload["questions"].items()
        },
        "usage": {"input_tokens": 100, "output_tokens": 5},
    }


def test_local_search_uses_real_own_stock_and_leaves_one_slot_for_normal_policy(
    search_run: Callable[..., SearchRun],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = search_run()
    agent, event = run.agent, run.events[0]
    with connect(run.url) as conn:
        conn.execute(
            """UPDATE supply_stock SET on_hand=50,version=17 WHERE run_id=%s
            AND owner=%s AND ingredient='flour'""",
            (run.run, agent.scope.store),
        )
        conn.execute(
            """UPDATE supply_stock SET on_hand=999999 WHERE run_id=%s
            AND owner='market-a' AND ingredient='flour'""",
            (run.run,),
        )

    def no_provider(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Local search cannot invoke a provider")

    monkeypatch.setattr(JevClient, "__call__", no_provider)
    result = search_for_agent(agent, event, "Harina", "local")
    assert result["results"][0]["id"] == "flour"
    assert result["results"][0]["available"] == 50
    assert result["results"][0]["stock_version"] == 17
    assert not result["availability_is_reservation"]
    assert result["calls"] == result["input_tokens"] == 0
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT observed_tools FROM agent_event_budgets WHERE event_id=%s",
                (event.id,),
            ).fetchone()["observed_tools"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_search_calls WHERE run_id=%s",
                (run.run,),
            ).fetchone()["n"]
            == 0
        )
        audit = conn.execute(
            "SELECT query,mode,reserved_calls FROM supply_search_audits WHERE id=%s",
            (result["audit_id"],),
        ).fetchone()
        assert audit == {"query": "Harina", "mode": "local", "reserved_calls": 0}
    assert agent.process(event)  # One search + four normal policy tools fit default five.


def test_search_denies_forged_expired_and_cross_entity_leases_and_raw_tables(
    search_run: Callable[..., SearchRun],
) -> None:
    run = search_run()
    agent, event = run.agent, run.events[0]
    for forged in (replace(event, token=uuid4()), replace(event, attempts=event.attempts + 1)):
        with pytest.raises(PermissionError):
            search_for_agent(agent, forged, "flour", "local")
    with pytest.raises(PermissionError):
        search_for_agent(run.agents["market-a"], event, "flour", "local")
    home = next(a for a in run.agents.values() if a.role.name == "household")
    with pytest.raises(PermissionError):
        search_for_agent(home, event, "flour", "local")
    with connect(agent.dsn) as conn:
        for table in (
            "supply_search_budgets",
            "supply_search_calls",
            "supply_search_cache",
            "supply_search_tickets",
            "supply_search_audits",
        ):
            for operation in ("SELECT * FROM", "DELETE FROM"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(f"{operation} {table}")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                "SELECT supply_search_scope(%s,%s,%s)", (event.id, event.token, event.attempts)
            )
    with connect(run.url) as conn:
        conn.execute(
            "UPDATE events SET lease_until=now()-interval '1 second' WHERE id=%s", (event.id,)
        )
    with pytest.raises(PermissionError):
        search_for_agent(agent, event, "flour", "local")


def test_jev_requires_frozen_opt_in_and_global_environment_opt_in(
    search_run: Callable[..., SearchRun],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = search_run()
    with pytest.raises(PermissionError):
        search_for_agent(local.agent, local.events[0], "flour", "jev")
    opted = search_run(provider="jev", calls=1)
    monkeypatch.delenv("DELIVERY_JEV_ENABLED", raising=False)
    result = search_for_agent(opted.agent, opted.events[0], "flour", "jev")
    assert result["error"] == "jev_not_enabled" and result["calls"] == 0
    assert not result["results"]
    with connect(opted.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_search_calls WHERE run_id=%s",
                (opted.run,),
            ).fetchone()["n"]
            == 0
        )


def test_concurrent_searches_share_durable_call_admission_cap(
    search_run: Callable[..., SearchRun],
    jev_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = search_run(provider="jev", calls=1, households=2)
    calls: list[dict[str, Any]] = []

    def mock_review(self: JevClient, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append(payload)
        return review(payload)

    monkeypatch.setattr(JevClient, "__call__", mock_review)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda e: search_for_agent(run.agent, e, "flour", "jev"), run.events)
        )
    assert len(calls) == sum(result["calls"] for result in results) == 1
    assert all(result["error"] == "budget_denied" for result in results)
    with connect(run.url) as conn:
        budget = conn.execute(
            "SELECT * FROM supply_search_budgets WHERE run_id=%s",
            (run.run,),
        ).fetchone()
        assert budget["calls_reserved"] == 1
        assert 0 < budget["input_tokens_reserved"] <= 51200
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_search_calls WHERE run_id=%s",
                (run.run,),
            ).fetchone()["n"]
            == 1
        )


@pytest.mark.parametrize("failure", ["timeout", "missing_usage"])
def test_failed_reviews_keep_full_durable_reservation_and_never_cache(
    search_run: Callable[..., SearchRun],
    jev_env: None,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    run = search_run(provider="jev", calls=1, tool_slots=8)

    def mock_review(self: JevClient, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if failure == "timeout":
            raise TimeoutError("synthetic secret must never reach audit or client")
        result = review(payload)
        del result["usage"]
        return result

    monkeypatch.setattr(JevClient, "__call__", mock_review)
    result = search_for_agent(run.agent, run.events[0], "flour", "jev")
    assert result["calls"] == 1
    assert result["error"] in {"provider_timeout", "provider_schema_invalid"}
    assert not result["results"]
    denied = search_for_agent(run.agent, run.events[0], "rice", "jev")
    assert denied["calls"] == 0 and denied["error"] == "budget_denied"
    with connect(run.url) as conn:
        call = conn.execute(
            "SELECT * FROM supply_search_calls WHERE run_id=%s",
            (run.run,),
        ).fetchone()
        assert call["status"] == "error" and call["actual_input_tokens"] is None
        assert call["charged_input_tokens"] == call["reserved_input_tokens"]
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_search_cache WHERE run_id=%s",
                (run.run,),
            ).fetchone()["n"]
            == 0
        )
        audits = conn.execute(
            "SELECT detail FROM supply_search_audits WHERE run_id=%s",
            (run.run,),
        ).fetchall()
        assert "synthetic secret" not in json.dumps(audits, default=str)


def test_cache_is_private_relevance_only_and_availability_refreshes_without_network(
    search_run: Callable[..., SearchRun],
    jev_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = search_run(role="market", provider="jev", calls=8, tool_slots=8, empty_flour=True)
    agent, event = run.agent, run.events[0]
    login = conninfo_to_dict(agent.dsn)["user"]
    network_calls: list[dict[str, Any]] = []

    def mock_review(self: JevClient, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        network_calls.append(payload)
        serialized = json.dumps(payload)
        assert "customer-" not in serialized and "available" not in serialized
        assert "market-a" not in serialized and "reserved" not in serialized
        assert "synthetic-test-key" not in serialized
        with connect(run.url) as conn:
            assert (
                conn.execute(
                    """SELECT count(*) n FROM pg_stat_activity WHERE usename=%s
                AND xact_start IS NOT NULL""",
                    (login,),
                ).fetchone()["n"]
                == 0
            )
            if len(network_calls) == 1:
                # Change inventory while relevance is being reviewed. Availability
                # must be read again after review, rather than copied from begin.
                conn.execute(
                    """UPDATE supply_stock SET on_hand=100,version=4 WHERE run_id=%s
                    AND owner='market-a' AND ingredient='flour'""",
                    (run.run,),
                )
        return review(payload)

    monkeypatch.setattr(JevClient, "__call__", mock_review)
    first = search_for_agent(agent, event, "flour", "jev")
    assert first["calls"] == 3 and first["results"][0]["available"] == 100
    assert first["results"][0]["stock_version"] == 4
    count = len(network_calls)
    with connect(run.url) as conn:
        conn.execute(
            """UPDATE supply_stock SET on_hand=10,version=9 WHERE run_id=%s
            AND owner='market-a' AND ingredient='flour'""",
            (run.run,),
        )
    second = search_for_agent(agent, event, "flour", "jev")
    assert second["calls"] == 0 and second["cache_hits"] == 17
    assert len(network_calls) == count
    assert second["results"][0]["available"] == 10
    assert second["results"][0]["stock_version"] == 9
    assert not second["availability_is_reservation"]
    with connect(run.url) as conn:
        cached = conn.execute(
            "SELECT body FROM supply_search_cache WHERE run_id=%s",
            (run.run,),
        ).fetchall()
        assert len(cached) == 17
        assert all(
            set(row["body"]) == {"choice", "confidence", "model", "expires_at"}
            and row["body"]["choice"] in {"yes", "no"}
            for row in cached
        )
        conn.execute(
            """UPDATE supply_search_cache SET expires_at=now()-interval '1 second'
            WHERE run_id=%s AND owner='market-a'""",
            (run.run,),
        )
    expired = search_for_agent(agent, event, "flour", "jev")
    assert expired["cache_hits"] == 0 and expired["calls"] == 3
    assert agent.process(event)  # Ten grams cannot fill the 150g request; forward.
    with connect(run.url) as conn:
        conn.execute("UPDATE runs SET sim_time=1200 WHERE id=%s", (run.run,))
    peer = run.agents["market-b"]
    peer_event = peer.claim()
    assert peer_event is not None
    peer_result = search_for_agent(peer, peer_event, "flour", "jev")
    assert peer_result["cache_hits"] == 0 and peer_result["calls"] == 3
    assert peer_result["error"] is None
    assert peer_result["results"][0]["available"] > 10
    with connect(run.url) as conn:
        owners = conn.execute(
            "SELECT owner,count(*) n FROM supply_search_cache WHERE run_id=%s GROUP BY owner",
            (run.run,),
        ).fetchall()
        assert {row["owner"] for row in owners} == {"market-a", "market-b"}
        # Relevance cache writes are best-effort. A missed write cannot widen
        # scope or change a provider result, and is retried as a cache miss.
        assert all(1 <= row["n"] <= 17 for row in owners)


def test_process_crash_keeps_the_committed_admission_charged(
    search_run: Callable[..., SearchRun],
    jev_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = search_run(provider="jev", calls=1, tool_slots=8)

    def crash(self: JevClient, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        raise SystemExit("Injected process exit after admission, before accounting")

    monkeypatch.setattr(JevClient, "__call__", crash)
    with pytest.raises(SystemExit):
        search_for_agent(run.agent, run.events[0], "flour", "jev")
    with connect(run.url) as conn:
        call = conn.execute(
            "SELECT * FROM supply_search_calls WHERE run_id=%s",
            (run.run,),
        ).fetchone()
        assert call["status"] == "reserved" and call["actual_input_tokens"] is None
        assert call["charged_input_tokens"] == call["reserved_input_tokens"] > 0
    retry = search_for_agent(run.agent, run.events[0], "flour", "jev")
    assert retry["error"] == "budget_denied" and retry["calls"] == 0


def test_uncertain_relevance_is_not_cached(
    search_run: Callable[..., SearchRun],
    jev_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = search_run(provider="jev", calls=8)

    def uncertain(self: JevClient, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        response = review(payload)
        for answer in response["answers"].values():
            answer["choice"] = "uncertain"
        return response

    monkeypatch.setattr(JevClient, "__call__", uncertain)
    result = search_for_agent(run.agent, run.events[0], "flour", "jev")
    assert result["error"] is None and result["calls"] == 3 and not result["results"]
    assert all(review["choice"] == "uncertain" for review in result["reviews"])
    with connect(run.url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) n FROM supply_search_cache WHERE run_id=%s",
                (run.run,),
            ).fetchone()["n"]
            == 0
        )


def test_lease_expiry_after_review_keeps_audit_and_charges_but_http_denies_stock(
    search_run: Callable[..., SearchRun],
    jev_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = search_run(provider="jev", calls=8)
    agent, event = run.agent, run.events[0]
    batches = 0

    def expires_after_review(
        self: JevClient,
        payload: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        nonlocal batches
        batches += 1
        if batches == 3:
            with connect(run.url) as conn:
                conn.execute(
                    "UPDATE events SET lease_until=now()-interval '1 second' WHERE id=%s",
                    (event.id,),
                )
        return review(payload)

    monkeypatch.setattr(JevClient, "__call__", expires_after_review)
    token = supply.issue_channel(run.run, agent.scope.agent_id)
    supply_routes._LEASES[(run.run, agent.scope.agent_id, event.id)] = event
    app = FastAPI()
    app.include_router(supply_routes.router)
    with TestClient(app) as client:
        response = client.post(
            f"/api/supply/runs/{run.run}/agents/{agent.scope.agent_id}/search",
            headers={"Authorization": "Bearer " + token},
            json={
                "event_id": event.id,
                "lease_token": str(event.token),
                "attempt": event.attempts,
                "query": "flour",
                "mode": "jev",
            },
        )
    assert response.status_code == 403 and batches == 3
    assert set(response.json()) == {"detail"}
    with connect(run.url) as conn:
        audit = conn.execute(
            "SELECT * FROM supply_search_audits WHERE run_id=%s",
            (run.run,),
        ).fetchone()
        assert audit["query"] == "flour" and audit["model"] == "jev-test"
        assert audit["reserved_calls"] == 3 and audit["charged_input_tokens"] == 300
        assert audit["detail"]["availability_error"] == "active_lease_required"
        assert len(audit["detail"]["reviews"]) == 17
        assert audit["detail"]["error"] is None
        assert all(set(row) == {"id", "name", "unit"} for row in audit["detail"]["results"])
        assert "availability_as_of" not in audit["detail"]
        calls = conn.execute(
            "SELECT * FROM supply_search_calls WHERE run_id=%s",
            (run.run,),
        ).fetchall()
        assert len(calls) == 3 and all(call["status"] == "ok" for call in calls)
        budget = conn.execute(
            "SELECT * FROM supply_search_budgets WHERE run_id=%s",
            (run.run,),
        ).fetchone()
        assert budget["calls_reserved"] == 3
        assert budget["input_tokens_reserved"] == sum(
            call["reserved_input_tokens"] for call in calls
        )
        assert budget["input_tokens_reserved"] == audit["reserved_input_tokens"] > 300

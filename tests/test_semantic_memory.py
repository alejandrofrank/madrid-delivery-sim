import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import psycopg
import pytest
from psycopg.types.json import Jsonb
from test_adk_restaurant import adk_city as adk_city
from test_adk_restaurant import first_call
from test_agent_runtime import claim, request
from test_agent_runtime import fleet as fleet
from test_memory_profiles import record, set_profile

from delivery.agent_runtime import ScopedTools
from delivery.db import connect
from delivery.memory_profiles import MemoryProfile
from delivery.semantic_memory import (
    DIMENSIONS,
    LocalEmbedder,
    PgvectorBackend,
    VertexVectorBackend,
    rank_facts,
)


@pytest.mark.integration
@pytest.mark.parametrize("case", json.loads(Path("evals/memory/recall.json").read_text()))
def test_real_offline_recall_helps_repeated_order_without_cross_order_leak(
    db_url, fleet, case,
):
    """Compare retained evidence against no memory, without pretending to measure LLM quality."""
    from delivery.memory_profiles import project_memory

    profile = MemoryProfile(mode="semantic", ttl_seconds=60)
    set_profile(db_url, fleet, profile)
    request(db_url, fleet)
    request(db_url, fleet, basket="other-order")
    event, other = claim(fleet), claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event) and agent.reserve_budget(other)
    role = agent.role.model_copy(update={"memory": profile})
    with connect(agent.dsn) as conn:
        record(conn, event, status=case["status"])
        facts = ScopedTools(conn, agent.scope, role, event).invoke(
            "memory.read", query=case["query"]
        )
        assert facts[0]["body"]["status"] == case["status"]
        assert project_memory(MemoryProfile(mode="none"), facts) == []
        assert ScopedTools(conn, agent.scope, role, other).invoke(
            "memory.read", query=case["query"]
        ) == []


def test_real_embedding_semantically_matches_paraphrase_over_unrelated_observation():
    vectors = LocalEmbedder().embed([
        "Has the kitchen already held ingredients for this meal?",
        "The restaurant reserved stock to prepare the order.",
        "The bicycle courier has arrived at the customer's address.",
    ])
    import numpy as np

    query, relevant, unrelated = map(np.array, vectors)
    def cosine(v):
        return float(query @ v / (np.linalg.norm(query) * np.linalg.norm(v)))

    assert cosine(relevant) > cosine(unrelated) + 0.1


class FixtureEmbedder:
    model = "fixture-only"

    def embed(self, texts):
        return [[1.0, *([0.0] * (DIMENSIONS - 1))] for _ in texts]


def test_rank_drops_foreign_duplicate_and_invented_ids_before_hydration():
    index = Mock(name="vector-index", rank=Mock(return_value=[999, 2, 2, 1]))
    index.name = "fixture"
    facts = [{"fact_id": i, "kind": "inventory.reservation", "body": {"status": "reserved"}}
             for i in [1, 2]]
    ids, audit = rank_facts(facts, "Is stock held?", {"role": "inventory"},
                            index, FixtureEmbedder())
    assert ids == [2, 1]
    assert audit["embedding_paid_calls"] == 0
    assert "Is stock held?" not in str(audit)


def test_vertex_uses_opaque_scope_filters_no_fact_text_and_authenticated_session():
    session = Mock()
    session.post.return_value.json.return_value = {"nearestNeighbors": [{"neighbors": []}]}
    backend = VertexVectorBackend(index="projects/123/locations/europe-west1/indexes/456",
                                  endpoint="projects/123/locations/europe-west1/indexEndpoints/789",
                                  deployed_index="memory_v1",
                                  public_domain="test.vdb.vertexai.goog",
                                  session=session)
    facts = [{"fact_id": 1, "expires_sim": 600, "kind": "inventory.reservation",
              "body": {"status": "reserved", "private": "never send this text"}}]
    assert rank_facts(facts, "Is stock held?", {"run": "private-order", "role": "inventory"},
                      backend, FixtureEmbedder())[0] == []
    assert session.post.call_count == 2
    payloads = [c.kwargs["json"] for c in session.post.call_args_list]
    assert "never send this text" not in str(payloads) and "private-order" not in str(payloads)
    assert payloads[0]["datapoints"][0]["restricts"] == (
        payloads[1]["queries"][0]["datapoint"]["restricts"]
    )
    with pytest.raises(ValueError):
        VertexVectorBackend(index=backend.index, endpoint=backend.endpoint,
                            deployed_index="memory_v1", public_domain="attacker.example")


@pytest.mark.parametrize("query", ["", "x" * 513, 4])
def test_queries_are_bounded_before_embedding(query):
    embedder = Mock()
    with pytest.raises(ValueError):
        rank_facts([], query, {}, Mock(), embedder)
    embedder.embed.assert_not_called()


@pytest.mark.integration
def test_real_pgvector_obeys_order_scope_ttl_and_audits_second_fenced_read(
    db_url, fleet, monkeypatch,
):
    monkeypatch.setattr("delivery.semantic_memory.LocalEmbedder", FixtureEmbedder)
    profile = MemoryProfile(mode="semantic", ttl_seconds=60)
    set_profile(db_url, fleet, profile)
    request(db_url, fleet)
    request(db_url, fleet, basket="another-order")
    event, other = claim(fleet), claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event) and agent.reserve_budget(other)
    role = agent.role.model_copy(update={"memory": profile})
    with connect(agent.dsn) as conn:
        written = record(conn, event)
        tools = ScopedTools(conn, agent.scope, role, event)
        found = tools.invoke("memory.read", query="Has stock already been held?")
        assert [f["fact_id"] for f in found] == [written["fact_id"]]
        assert tools.calls == ["memory.read", "memory.read"]
        assert tools.memory_reads[0]["semantic"]["returned_fact_ids"] == [written["fact_id"]]
        other_tools = ScopedTools(conn, agent.scope, role, other)
        assert other_tools.invoke("memory.read", query="Has stock already been held?") == []
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT * FROM agent_semantic_vectors")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            PgvectorBackend(conn, replace(event, token=other.token)).rank(
                found, FixtureEmbedder().embed(["x"]), FixtureEmbedder().embed(["q"])[0], {},
                "fixture-only",
            )
    with connect(db_url) as conn:
        conn.execute("UPDATE runs SET sim_time=60 WHERE id=%s", (fleet.run,))
    with connect(agent.dsn) as conn:
        tools = ScopedTools(conn, agent.scope, role, event)
        assert tools.invoke("memory.read", query="Has stock already been held?") == []


@pytest.mark.integration
def test_cloud_index_cannot_resurrect_facts_expiring_during_search(db_url, fleet, monkeypatch):
    profile = MemoryProfile(mode="semantic", ttl_seconds=60)
    set_profile(db_url, fleet, profile)
    request(db_url, fleet)
    event = claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event)
    monkeypatch.setattr("delivery.semantic_memory.LocalEmbedder", FixtureEmbedder)

    class ExpiringIndex:
        name = "vertex-test"

        def rank(self, facts, *args):
            with connect(db_url) as admin:
                admin.execute("UPDATE runs SET sim_time=60 WHERE id=%s", (fleet.run,))
            return [facts[0]["fact_id"], 999999]

    monkeypatch.setattr("delivery.semantic_memory.backend", lambda *args: ExpiringIndex())
    with connect(agent.dsn) as conn:
        record(conn, event)
        tools = ScopedTools(conn, agent.scope, agent.role.model_copy(update={"memory": profile}),
                            event)
        assert tools.invoke("memory.read", query="Reservation status?") == []
        assert tools.memory_reads[0]["semantic"]["returned_fact_ids"] == []


@pytest.mark.integration
def test_nonsemantic_role_cannot_write_embedding_cache(db_url, fleet):
    request(db_url, fleet)
    event = claim(fleet)
    agent = fleet.agents["store-1"]
    assert agent.reserve_budget(event)
    with connect(agent.dsn) as conn:
        written = record(conn, event)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute("SELECT agent_semantic_cache(%s,%s,%s,%s,%s)", (
                event.id, event.token, event.attempts, "fixture-only",
                Jsonb([{"fact_id": written["fact_id"],
                        "embedding": FixtureEmbedder().embed(["x"])[0]}]),
            ))


@pytest.mark.integration
def test_adk_semantic_tool_uses_nonce_fence_and_records_actual_returned_facts(
    adk_city, monkeypatch,
):
    from delivery.adk_restaurant import RestaurantTurn

    city = adk_city()
    profile = MemoryProfile(mode="semantic", ttl_seconds=60)
    with connect(city.url) as conn:
        conn.execute(
            "UPDATE supply_entities SET definition=jsonb_set(definition,'{agent,memory}',%s) "
            "WHERE run_id=%s AND kind='restaurant'", (Jsonb(profile.model_dump()), city.run),
        )
    agent, event = first_call(city)
    assert agent.role.memory == profile and agent.reserve_budget(event)
    monkeypatch.setattr("delivery.semantic_memory.LocalEmbedder", FixtureEmbedder)
    with connect(agent.dsn) as conn:
        receipt = conn.execute("SELECT restaurant_turn_begin(%s,%s,%s) d",
                               (event.id, event.token, event.attempts)).fetchone()["d"]
        written = conn.execute(
            "SELECT agent_memory_record(%s,%s,%s,'restaurant.order',%s,60) d",
            (event.id, event.token, event.attempts,
             Jsonb({"status": "calling", "action": "restaurant_intake"})),
        ).fetchone()["d"]
    turn = RestaurantTurn(agent, event, receipt["nonce"])
    found = turn.recall_order_memory("Did this order already contact our kitchen?")
    assert [f["fact_id"] for f in found] == [written["fact_id"]]
    with connect(city.url) as conn:
        saved = conn.execute("SELECT memory FROM restaurant_turns WHERE event_id=%s",
                             (event.id,)).fetchone()["memory"]
        audit = conn.execute(
            "SELECT result FROM restaurant_tool_receipts WHERE event_id=%s "
            "AND tool='memory.semantic'", (event.id,),
        ).fetchone()["result"]
    assert saved == found == audit["facts"]
    assert "contact our kitchen" not in str(audit)
    turn.nonce = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        turn.recall_order_memory("old nonce")

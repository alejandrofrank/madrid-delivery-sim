"""Documentation must use the runtime contracts, not a parallel example schema."""
import json
from pathlib import Path

import pytest

from delivery.agent_anatomy import anatomy_data
from delivery.agent_specs import load_role
from delivery.memory_profiles import MemoryProfile, project_memory
from delivery.memory_reference import SOURCES, memory_reference
from delivery.role_manifest import manifest_names
from delivery.semantic_memory import DIMENSIONS, MODEL, rank_facts
from delivery.typed_memory import CONTRACTS, validate_fact


@pytest.mark.parametrize("name", [n for n in manifest_names() if n != "judge-gcp"])
def test_reference_examples_match_each_role_schema_and_every_projection(name):
    role = load_role(name)
    reference = memory_reference(role)
    expected = {k for k, v in CONTRACTS.items() if v[0] == name}
    assert {c["kind"] for c in reference["contracts"]} == expected
    assert reference["persistent"] == bool(expected)
    assert reference["profile_schema"] == MemoryProfile.model_json_schema()
    assert reference["capacity"] == {
        k: role.limits.model_dump()[k]
        for k in ("memory_entries", "memory_bytes", "tool_calls_per_event")
    }
    for contract in reference["contracts"]:
        kind, record = contract["kind"], contract["record"]
        assert contract["body_schema"] == CONTRACTS[kind][3].model_json_schema()
        assert record["owner_role"] == name
        assert validate_fact(kind, record["body"], name, contract["topics"][0]) == record["body"]
        assert record["expires_sim"] - record["observed_sim"] == MemoryProfile().ttl_seconds
        assert set().union(*(set(f["keys"]) for f in reference["fields"])) == set(record)
        for mode, output in contract["projections"].items():
            assert output == project_memory(MemoryProfile(mode=mode), [record])
    assert reference["semantic"]["model"] == MODEL
    assert reference["semantic"]["dimensions"] == DIMENSIONS


def test_classifier_reference_cannot_imply_persistent_recall():
    ref = memory_reference(load_role("customer_service"))
    assert ref["contracts"] == [] and not ref["persistent"]
    assert "no persistent memory contract" in ref["applicability"]
    assert "not semantic recall" in ref["applicability"]


def test_documented_query_bound_matches_real_boundary_without_model_access():
    from unittest.mock import Mock

    ref = memory_reference(load_role("inventory"))
    with pytest.raises(ValueError, match="bounded query"):
        rank_facts([], "a" * (ref["semantic"]["query_bytes"] + 1), {}, Mock())
    index = Mock()
    index.name = "fixture"
    assert rank_facts([], "a" * ref["semantic"]["query_bytes"], {}, index, Mock())[0] == []
    index.rank.assert_not_called()


def test_body_and_storage_claims_match_sql_and_terraform():
    sql = Path("sql/migrations/015_typed_memory.sql").read_text()
    vectors = Path("sql/migrations/031_semantic_memory.sql").read_text()
    cloud = Path("infra/production/live.tf").read_text()
    vertex = Path("infra/production/vector.tf").read_text()
    assert "octet_length(body::text)<=2048" in sql
    assert "CREATE TABLE public.agent_memory_facts" in sql
    assert "CREATE VIEW public.agent_memory_current" in sql
    assert "embedding jsonb NOT NULL" in vectors
    assert "v.embedding::text::public.vector" in vectors
    assert "backup_configuration { enabled = false }" in cloud
    assert "deletion_protection = false" in cloud
    assert "min_replica_count = 1" in vertex
    assert "var.active && var.enable_live && var.enable_vector_search" in vertex
    assert f"dimensions            = {DIMENSIONS}" in vertex


def test_reference_changes_propagate_to_anatomy_and_source_fingerprint(monkeypatch):
    from delivery import agent_anatomy

    before = anatomy_data()
    original = agent_anatomy.memory_reference

    def modified(role):
        return {**original(role), "format": "Changed implementation format"}

    monkeypatch.setattr(agent_anatomy, "memory_reference", modified)
    after = anatomy_data()
    for agent in after["agents"]:
        assert next(p for p in agent["panels"] if p["id"] == "memory")["reference"]["format"] == (
            "Changed implementation format"
        )
    assert before != after
    assert set(SOURCES) <= set(agent_anatomy.source_paths())
    catalogue = json.loads(Path("config/documentation.json").read_text())
    assert set(SOURCES) <= set(catalogue["sources"])

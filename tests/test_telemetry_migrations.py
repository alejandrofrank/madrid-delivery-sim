"""The two released 026 histories converge without accepting arbitrary checksum drift."""

import hashlib
import shutil
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from delivery.db import _compatible_migration, connect, migrate

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "e653fefc503d701ded74ee51f6a1ebd792a275fef11d244aedd0408dda764277"
RELEASED_OTEL = "c1c197008648301a7e0246a8f7c985dc06c1944d3393484ca3a62df8b830d19d"


def test_only_exact_released_history_pair_is_compatible() -> None:
    assert _compatible_migration("026_telemetry_context.sql", CANONICAL, RELEASED_OTEL)
    assert not _compatible_migration("025_adk_contract_corrections.sql", CANONICAL, RELEASED_OTEL)
    assert not _compatible_migration("026_telemetry_context.sql", "0" * 64, RELEASED_OTEL)
    assert not _compatible_migration("026_telemetry_context.sql", CANONICAL, "0" * 64)
    assert not _compatible_migration("026_telemetry_context.sql", RELEASED_OTEL, CANONICAL)
    assert (
        hashlib.sha256((ROOT / "sql/migrations/026_telemetry_context.sql").read_bytes()).hexdigest()
        == CANONICAL
    )
    assert (
        hashlib.sha256((ROOT / "tests/fixtures/telemetry/otel_026.sql").read_bytes()).hexdigest()
        == RELEASED_OTEL
    )


@pytest.fixture
def isolated_database(db_url):
    # CREATE/DROP only a unique database owned by this test on the dedicated test server.
    parameters = conninfo_to_dict(db_url)
    name = "mds_telemetry_migration_" + uuid4().hex
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(**{**parameters, "dbname": name})
    finally:
        with psycopg.connect(db_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.mark.integration
@pytest.mark.parametrize("history", ["fresh", "google", "otel"])
def test_fresh_and_both_released_histories_upgrade_preserving_evidence(
    history,
    isolated_database,
    tmp_path,
    monkeypatch,
) -> None:
    shutil.copytree(ROOT / "sql", tmp_path / "sql")
    migrations = tmp_path / "sql/migrations"
    canonical = migrations / "026_telemetry_context.sql"
    canonical_source = canonical.read_bytes()
    convergence = migrations / "027_unified_order_telemetry.sql"
    convergence_source = convergence.read_bytes()
    monkeypatch.chdir(tmp_path)
    run = uuid4()
    parent = "00-" + "1" * 32 + "-" + "2" * 16 + "-03"
    if history != "fresh":
        convergence.unlink()
        if history == "otel":
            canonical.write_bytes((ROOT / "tests/fixtures/telemetry/otel_026.sql").read_bytes())
        migrate(isolated_database)
        column = "traceparent" if history == "otel" else "otel_traceparent"
        with connect(isolated_database) as conn:
            conn.execute("INSERT INTO runs(id,seed) VALUES (%s,42)", (run,))
            if history == "google":
                conn.execute("SELECT set_config('delivery.traceparent',%s,true)", (parent,))
            conn.execute(
                sql.SQL(
                    "INSERT INTO events(run_id,topic,producer,payload,dedupe_key,trace_id,{}) "
                    "VALUES (%s,'order.created','generator','{{}}','prior','order',%s)"
                ).format(sql.Identifier(column)),
                (run, parent),
            )
        canonical.write_bytes(canonical_source)
        convergence.write_bytes(convergence_source)
    migrate(isolated_database)
    migrate(isolated_database)  # Idempotent, with the original applied checksum retained.
    with connect(isolated_database) as conn:
        applied = conn.execute(
            "SELECT sha256 FROM schema_migrations WHERE name=%s", (canonical.name,)
        ).fetchone()["sha256"]
        assert applied == (RELEASED_OTEL if history == "otel" else CANONICAL)
        if history == "fresh":
            conn.execute("INSERT INTO runs(id,seed) VALUES (%s,42)", (run,))
            conn.execute(
                "INSERT INTO events(run_id,topic,producer,payload,dedupe_key,trace_id,traceparent) "
                "VALUES (%s,'order.created','generator','{}','prior','order',%s)",
                (run, parent),
            )
        row = conn.execute(
            "SELECT id,traceparent,otel_traceparent FROM events WHERE run_id=%s", (run,)
        ).fetchone()
        assert row["traceparent"] == row["otel_traceparent"] == parent
        child = conn.execute(
            "INSERT INTO events(run_id,topic,producer,payload,dedupe_key,trace_id,parent_id) "
            "VALUES (%s,'courier.assigned','dispatcher','{}','child','order',%s) "
            "RETURNING traceparent,otel_traceparent",
            (run, row["id"]),
        ).fetchone()
        assert child["traceparent"] == child["otel_traceparent"] == parent
        for role in ("lab_supply_executor", "lab_restaurant_adk_executor"):
            assert conn.execute(
                "SELECT has_function_privilege(%s,"
                "'agent_trace_context(bigint,uuid,integer,text)','EXECUTE') AS ok",
                (role,),
            ).fetchone()["ok"]
    canonical.write_bytes(canonical_source + b"\n-- Unapproved canonical edit\n")
    with pytest.raises(RuntimeError, match="Applied migration changed: 026"):
        migrate(isolated_database)
    canonical.write_bytes(canonical_source)
    unrelated = migrations / "025_adk_contract_corrections.sql"
    unrelated.write_bytes(unrelated.read_bytes() + b"\n-- Unapproved unrelated edit\n")
    with pytest.raises(RuntimeError, match="Applied migration changed: 025"):
        migrate(isolated_database)

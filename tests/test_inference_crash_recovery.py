"""Real worker death must recover durable inference without a second uncertain call."""

import os
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest
from psycopg.types.json import Jsonb

from delivery.agent_access import retire_inventory_access, role_access
from delivery.agent_runtime import LocalAgent, create_agent
from delivery.cloud_ai import CloudJudge, Judgment
from delivery.db import connect
from delivery.delivery_flow import new_delivery
from delivery.durable_inference import prepare
from delivery.fleet_flow import advance_fleet, prepare_fleet

pytestmark = pytest.mark.integration

ENDPOINT = "https://judge.run.app"
WORKER = """
import os
from delivery.agent_runtime import create_agent
from delivery.cloud_ai import CloudJudge, Judgment

def fake_review(self, context, memory, *, candidate):
    descriptor = os.open(os.environ['FAKE_CALLS'], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, b'invoked\\n')
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return Judgment(decision='approve_retry', reason='Local fake provider', model='fake-local',
                    input_tokens=5, output_tokens=3)

def fault(stage):
    if stage == os.environ['CRASH_STAGE']:
        os._exit(73)

CloudJudge.review = fake_review
agent = create_agent(os.environ['DATABASE_URL'], agent_mode='gcp_ai',
                     cloud_endpoint='https://judge.run.app')
event = agent.claim(lease_seconds=30)
assert event is not None
agent.process(event, fault=fault)
raise RuntimeError('Crash checkpoint not reached')
"""


@pytest.fixture
def failed_delivery(db_url: str) -> Iterator[tuple[str, LocalAgent]]:
    run = new_delivery(url=db_url)
    try:
        prepare_fleet(run, db_url)
        for role, key in (
            ("inventory", "store-1"),
            ("fulfillment", "store-1"),
            ("dispatcher", "fleet"),
            ("courier", "bike-1"),
        ):
            agent = create_agent(role_access(run, role, db_url)[key].dsn)
            event = agent.claim()
            assert event and agent.process(event)
        advance_fleet(run, 180, db_url)
        access = role_access(run, "judge", db_url, agent_mode="gcp_ai")["fleet"]
        yield run, create_agent(access.dsn, agent_mode="gcp_ai", cloud_endpoint=ENDPOINT)
    finally:
        retire_inventory_access(run, db_url)
        with connect(db_url) as conn:
            conn.execute("DELETE FROM decisions WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM events WHERE run_id=%s", (run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (run,))


def fake_provider(monkeypatch, path: Path) -> None:
    def review(self, context, memory, *, candidate):
        with path.open("a", encoding="utf-8") as handle:
            handle.write("invoked\n")
        return Judgment(
            decision="approve_retry",
            reason="Local fake provider",
            model="fake-local",
            input_tokens=5,
            output_tokens=3,
        )

    monkeypatch.setattr(CloudJudge, "review", review)


def call_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def test_inference_capabilities_deny_other_roles_runs_and_unleased_sources(db_url, failed_delivery):
    run, agent = failed_delivery
    event = agent.claim()
    assert event and agent.reserve_budget(event)
    prepare(agent, event)
    for role, key in (
        ("inventory", "store-1"),
        ("fulfillment", "store-1"),
        ("dispatcher", "fleet"),
        ("courier", "bike-1"),
    ):
        access = role_access(run, role, db_url)[key]
        with connect(access.dsn) as conn:
            for statement, parameters in (
                ("SELECT agent_inference_read(%s,%s,%s)", (event.id, event.token, event.attempts)),
                ("SELECT * FROM agent_inference_requests", ()),
                ("UPDATE agent_inference_requests SET state='succeeded'", ()),
            ):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                    conn.execute(statement, parameters)
    other_run = new_delivery(url=db_url)
    try:
        foreign = role_access(other_run, "judge", db_url, agent_mode="gcp_ai")["fleet"]
        with connect(foreign.dsn) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(
                    "SELECT agent_inference_read(%s,%s,%s)", (event.id, event.token, event.attempts)
                )
        with connect(agent.dsn) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(
                    "SELECT agent_inference_scope(%s,%s,%s)",
                    (event.id, event.token, event.attempts),
                )
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(
                    "SELECT agent_inference_read(%s,gen_random_uuid(),%s)",
                    (event.id, event.attempts),
                )
    finally:
        retire_inventory_access(other_run, db_url)
        with connect(db_url) as conn:
            conn.execute("DELETE FROM events WHERE run_id=%s", (other_run,))
            conn.execute("DELETE FROM runs WHERE id=%s", (other_run,))


def dispatch_request(agent, event):
    assert agent.reserve_budget(event)
    request = prepare(agent, event)
    with connect(agent.dsn) as conn:
        response = conn.execute(
            "SELECT agent_inference_dispatch(%s,%s,%s,%s) AS result",
            (event.id, event.token, event.attempts, request["id"]),
        ).fetchone()["result"]
    assert response["dispatch"]
    return response["request"]


def test_competing_worker_on_same_live_lease_leaves_original_owner_intact(
    db_url, failed_delivery, monkeypatch
):
    run, agent = failed_delivery
    event = agent.claim()
    assert event
    invocations = []
    competing = []

    def review(self, context, memory, *, candidate):
        invocations.append(True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            competing.append(pool.submit(agent.process, event).result(timeout=8))
        with connect(db_url) as conn:
            live = conn.execute(
                "SELECT state,lease_token FROM events WHERE id=%s", (event.id,)
            ).fetchone()
            assert live["state"] == "leased" and live["lease_token"] == event.token
        return Judgment(
            decision="approve_retry",
            reason="Original worker owns dispatch",
            model="fake-local",
            input_tokens=5,
            output_tokens=3,
        )

    monkeypatch.setattr(CloudJudge, "review", review)
    assert agent.process(event)
    assert competing == [False] and invocations == [True]
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM agent_model_calls WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            == 1
        )


def test_old_owner_cannot_overwrite_after_a_new_lease_applies(db_url, failed_delivery, monkeypatch):
    run, agent = failed_delivery
    old = agent.claim()
    assert old
    request = dispatch_request(agent, old)
    with connect(db_url) as conn:
        conn.execute(
            "UPDATE events SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
            (old.id,),
        )
    current = agent.claim()
    assert current and current.attempts == 2
    monkeypatch.setattr(CloudJudge, "review", lambda *a, **k: pytest.fail("Uncertain call resent"))
    assert agent.process(current)
    outcome = Judgment(
        decision="approve_retry",
        reason="Late old response",
        model="fake-local",
        input_tokens=5,
        output_tokens=3,
    ).model_dump()
    with connect(agent.dsn) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
            conn.execute(
                "SELECT agent_inference_save(%s,%s,%s,%s,%s,%s,NULL)",
                (
                    old.id,
                    old.token,
                    old.attempts,
                    request["id"],
                    request["dispatch_token"],
                    Jsonb(outcome),
                ),
            )
    with connect(db_url) as conn:
        row = conn.execute(
            "SELECT state,error_code,result FROM agent_inference_requests WHERE event_id=%s",
            (old.id,),
        ).fetchone()
        assert row["state"] == "applied" and row["error_code"] == "InvocationOutcomeUnknown"
        assert row["result"].get("decision") != "approve_retry"
        assert (
            conn.execute(
                "SELECT verdict FROM lab_retry_reviews WHERE run_id=%s", (run,)
            ).fetchone()["verdict"]
            == "denied"
        )


@pytest.mark.parametrize("change", ["clock", "memory"])
def test_known_stale_preparation_is_denied_before_model_admission(
    db_url, failed_delivery, monkeypatch, change
):
    run, agent = failed_delivery
    event = agent.claim()
    assert event

    def alter_snapshot(stage):
        if stage != "after_prepare":
            return
        if change == "clock":
            with connect(db_url) as conn:
                conn.execute("UPDATE runs SET sim_time=181 WHERE id=%s", (run,))
        else:
            from delivery.agent_runtime import ScopedTools
            from delivery.queue import publish

            with connect(db_url) as conn:
                publish(
                    conn,
                    run_id=run,
                    producer="lab_world",
                    topic="delivery.failed",
                    payload=event.payload,
                    key="concurrent-memory-observation",
                    trace_id=event.trace_id,
                    target_store=agent.scope.store,
                )
            sibling = agent.claim()
            assert sibling and sibling.id != event.id and agent.reserve_budget(sibling)

            with connect(agent.dsn) as conn:
                ScopedTools(conn, agent.scope, agent.role, sibling).invoke(
                    "memory.write",
                    kind="recovery.verdict",
                    body={
                        "verdict": "denied",
                        "attempt": 1,
                        "reason": "Fresh observation",
                        "remaining_seconds": 1000,
                    },
                )

    monkeypatch.setattr(
        CloudJudge, "review", lambda *a, **k: pytest.fail("Known stale request invoked")
    )
    assert agent.process(event, fault=alter_snapshot)
    with connect(db_url) as conn:
        assert conn.execute(
            "SELECT error_code FROM agent_inference_requests WHERE event_id=%s", (event.id,)
        ).fetchone()["error_code"] == (
            "MemoryPreconditionsChanged" if change == "memory" else "PreconditionsChanged"
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM agent_model_calls WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT verdict FROM lab_retry_reviews WHERE run_id=%s", (run,)
            ).fetchone()["verdict"]
            == "denied"
        )


@pytest.mark.parametrize("status", ["reserved", "completed"])
def test_legacy_call_without_immutable_snapshot_is_not_dispatched_again(
    db_url, failed_delivery, monkeypatch, status
):
    run, agent = failed_delivery
    event = agent.claim()
    assert event
    with connect(db_url) as conn:
        conn.execute(
            "INSERT INTO agent_model_calls(run_id,store,event_id,attempt,status) "
            "VALUES (%s,%s,%s,1,%s)",
            (run, agent.scope.store, event.id, status),
        )
    monkeypatch.setattr(CloudJudge, "review", lambda *a, **k: pytest.fail("Legacy call resent"))
    assert agent.process(event)
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM agent_model_calls WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            == 1
        )
        row = conn.execute(
            "SELECT state,error_code FROM agent_inference_requests WHERE event_id=%s", (event.id,)
        ).fetchone()
        assert row == {"state": "applied", "error_code": "LegacyInvocationOutcomeUnknown"}


@pytest.mark.parametrize("bad_field", ["decision", "source", "input_tokens"])
def test_malformed_results_cannot_be_saved_as_successful(db_url, failed_delivery, bad_field):
    _, agent = failed_delivery
    event = agent.claim()
    assert event
    request = dispatch_request(agent, event)
    outcome = Judgment(
        decision="approve_retry",
        reason="Bounded",
        model="fake-local",
        input_tokens=5,
        output_tokens=3,
    ).model_dump()
    outcome[bad_field] = None
    with connect(agent.dsn) as conn:
        with pytest.raises(psycopg.errors.InvalidParameterValue), conn.transaction():
            conn.execute(
                "SELECT agent_inference_save(%s,%s,%s,%s,%s,%s,NULL)",
                (
                    event.id,
                    event.token,
                    event.attempts,
                    request["id"],
                    request["dispatch_token"],
                    Jsonb(outcome),
                ),
            )


@pytest.mark.parametrize(
    "stage,calls_before_recovery,verdict",
    [
        ("after_prepare", 0, "approved"),
        ("after_dispatch", 0, "denied"),
        ("before_invoke", 0, "denied"),
        ("after_response", 1, "denied"),
        ("before_result_save", 1, "denied"),
        ("after_result_save", 1, "approved"),
        ("before_apply", 1, "approved"),
        ("after_apply_before_ack", 1, "approved"),
    ],
)
def test_process_death_recovers_without_uncertain_redispatch(
    db_url, failed_delivery, tmp_path, monkeypatch, stage, calls_before_recovery, verdict
):
    run, agent = failed_delivery
    calls = tmp_path / "provider-calls.txt"
    # The child receives only its restricted identity. Operator credentials and
    # provider credentials are not inherited by this simulated role worker.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment.update(
        DATABASE_URL=agent.dsn, LLM_PROVIDER="disabled", FAKE_CALLS=str(calls), CRASH_STAGE=stage
    )
    child = subprocess.run(
        [sys.executable, "-c", WORKER], env=environment, timeout=25, capture_output=True
    )
    assert child.returncode == 73, "Worker did not reach the requested crash boundary"
    assert call_count(calls) == calls_before_recovery
    with connect(db_url) as conn:
        source = conn.execute(
            "SELECT id,state,attempts FROM events WHERE run_id=%s AND topic='delivery.failed'",
            (run,),
        ).fetchone()
        assert source and source["state"] == "leased" and source["attempts"] == 1
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM lab_retry_reviews WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            == 0
        )
        # Simulate the supervisor observing an expired lease without waiting 30s.
        conn.execute(
            "UPDATE events SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
            (source["id"],),
        )
    fake_provider(monkeypatch, calls)
    recovered = agent.claim()
    assert recovered and recovered.id == source["id"] and recovered.attempts == 2
    assert agent.process(recovered)
    assert call_count(calls) == (1 if verdict == "approved" else calls_before_recovery)
    with connect(db_url) as conn:
        assert (
            conn.execute("SELECT state FROM events WHERE id=%s", (source["id"],)).fetchone()[
                "state"
            ]
            == "done"
        )
        assert (
            conn.execute(
                "SELECT verdict FROM lab_retry_reviews WHERE run_id=%s", (run,)
            ).fetchone()["verdict"]
            == verdict
        )
        assert conn.execute(
            "SELECT count(*) AS n,sum(reserved_tokens) AS tokens "
            "FROM agent_model_calls WHERE run_id=%s",
            (run,),
        ).fetchone() == {"n": 1, "tokens": 8448}
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM decisions WHERE event_id=%s", (source["id"],)
            ).fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM events WHERE parent_id=%s AND topic='recovery.reviewed'",
                (source["id"],),
            ).fetchone()["n"]
            == 1
        )
        assert (
            conn.execute(
                "SELECT state FROM agent_inference_requests WHERE event_id=%s", (source["id"],)
            ).fetchone()["state"]
            == "applied"
        )


def test_provider_runs_without_worker_database_connections_or_locks(
    db_url, failed_delivery, monkeypatch
):
    run, agent = failed_delivery
    with connect(db_url) as conn:
        binding = conn.execute(
            "SELECT login_role FROM agent_bindings WHERE run_id=%s AND store='judge:fleet'",
            (run,),
        ).fetchone()
    event = agent.claim()
    assert event
    checks = []

    def review(self, context, memory, *, candidate):
        with connect(db_url) as conn:
            # This callback is trusted test instrumentation, not a model tool.
            active = conn.execute(
                "SELECT count(*) AS n FROM pg_stat_activity WHERE usename=%s",
                (binding["login_role"],),
            ).fetchone()["n"]
            assert active == 0
            assert conn.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS available", (run,)
            ).fetchone()["available"]
            conn.execute("SET LOCAL lock_timeout='500ms'")
            assert conn.execute(
                "SELECT id FROM events WHERE id=%s FOR UPDATE", (event.id,)
            ).fetchone()
        checks.append(True)
        return Judgment(
            decision="approve_retry",
            reason="No worker transactions or locks",
            model="fake-local",
            input_tokens=5,
            output_tokens=3,
        )

    monkeypatch.setattr(CloudJudge, "review", review)
    assert agent.process(event)
    assert checks == [True]


def test_time_advancing_after_result_save_cannot_reuse_a_stale_approval(
    db_url, failed_delivery, tmp_path, monkeypatch
):
    run, agent = failed_delivery
    calls = tmp_path / "provider-calls.txt"
    fake_provider(monkeypatch, calls)
    event = agent.claim()
    assert event

    def change_deadline(stage):
        if stage == "after_result_save":
            with connect(db_url) as conn:
                conn.execute("UPDATE runs SET sim_time=30000 WHERE id=%s", (run,))

    assert agent.process(event, fault=change_deadline)
    assert call_count(calls) == 1
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT verdict FROM lab_retry_reviews WHERE run_id=%s", (run,)
            ).fetchone()["verdict"]
            == "denied"
        )
        assert (
            conn.execute(
                "SELECT result FROM agent_inference_requests WHERE event_id=%s", (event.id,)
            ).fetchone()["result"]["decision"]
            == "approve_retry"
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM agent_model_calls WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            == 1
        )


def test_death_after_ack_leaves_completed_work_and_no_new_dispatch(
    db_url, failed_delivery, tmp_path
):
    run, agent = failed_delivery
    calls = tmp_path / "provider-calls.txt"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment.update(
        DATABASE_URL=agent.dsn,
        LLM_PROVIDER="disabled",
        FAKE_CALLS=str(calls),
        CRASH_STAGE="after_apply",
    )
    child = subprocess.run(
        [sys.executable, "-c", WORKER], env=environment, timeout=25, capture_output=True
    )
    assert child.returncode == 73
    assert call_count(calls) == 1
    assert agent.claim() is None
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT state FROM agent_inference_requests WHERE run_id=%s", (run,)
            ).fetchone()["state"]
            == "applied"
        )
        assert (
            conn.execute(
                "SELECT state FROM events WHERE run_id=%s AND topic='delivery.failed'", (run,)
            ).fetchone()["state"]
            == "done"
        )
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM lab_retry_reviews WHERE run_id=%s", (run,)
            ).fetchone()["n"]
            == 1
        )

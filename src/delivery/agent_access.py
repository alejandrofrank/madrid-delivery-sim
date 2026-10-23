"""Trusted operator provisioning. These credentials never enter prompts or evidence."""

import hashlib
import secrets
from dataclasses import dataclass, field

from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb

from delivery.agent_specs import RoleSpec, load_inventory_role
from delivery.config import settings
from delivery.db import connect


@dataclass(frozen=True)
class AgentAccess:
    run: str
    store: str
    login: str
    dsn: str = field(repr=False)


_ACCESS: dict[tuple[str, str], dict[str, AgentAccess]] = {}


def inventory_access(
    run: str,
    url: str | None = None,
    definition: RoleSpec | None = None,
) -> dict[str, AgentAccess]:
    """Operator-only factory; snapshot trusted policy and provision one login per store."""
    operator_url = url or settings().database_url
    key = (operator_url, run)
    if key in _ACCESS:
        if definition is not None:
            candidate = RoleSpec.model_validate(definition.model_dump())
            with connect(operator_url) as conn:
                frozen = conn.execute(
                    "SELECT definition_hash FROM agent_bindings WHERE run_id=%s LIMIT 1", (run,)
                ).fetchone()
            if not frozen or candidate.digest != frozen["definition_hash"]:
                raise ValueError("Role definition is frozen for this run")
        return dict(_ACCESS[key])
    role = RoleSpec.model_validate((definition or load_inventory_role()).model_dump())
    limits = role.limits
    result = {}
    with connect(operator_url) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (run,))
        world = conn.execute("SELECT city FROM lab_worlds WHERE run_id=%s", (run,)).fetchone()
        if not world:
            raise ValueError("Unknown lab run")
        conn.execute(
            """INSERT INTO agent_run_budgets(run_id) VALUES (%s)
            ON CONFLICT DO NOTHING""",
            (run,),
        )
        for store in world["city"]["stores"]:
            store_id = store["id"]
            login = "lab_i_" + hashlib.sha256(f"{run}:{store_id}".encode()).hexdigest()[:24]
            password = secrets.token_urlsafe(32)
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (login,)).fetchone()
            if exists:
                raise RuntimeError(
                    "Agent identity already provisioned; do not replace active credentials"
                )
            conn.execute(
                sql.SQL("""CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB
                NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}""").format(
                    sql.Identifier(login), sql.Literal(password)
                )
            )
            conn.execute(
                sql.SQL("GRANT lab_inventory_executor TO {}").format(sql.Identifier(login))
            )
            conn.execute(
                "INSERT INTO agent_bindings VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    login,
                    run,
                    store_id,
                    f"inventory:{store_id}",
                    Jsonb(role.model_dump(mode="json")),
                    role.digest,
                ),
            )
            conn.execute(
                """INSERT INTO agent_budgets(run_id,store,events_limit,tools_limit,
                step_slots,memory_entries_limit,memory_bytes_limit)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    run,
                    store_id,
                    limits.events_per_run,
                    limits.tool_calls_per_run,
                    limits.tool_calls_per_event,
                    limits.memory_entries,
                    limits.memory_bytes,
                ),
            )
            result[store_id] = AgentAccess(
                run,
                store_id,
                login,
                make_conninfo(
                    operator_url,
                    user=login,
                    password=password,
                    application_name=f"inventory:{store_id}",
                    options=(
                        "-c statement_timeout=5000 -c idle_in_transaction_session_timeout=10000"
                    ),
                ),
            )
    _ACCESS[key] = result
    return dict(result)


def retire_inventory_access(run: str, url: str | None = None) -> None:
    """Retire short-lived logins after a run; retain decision/budget evidence."""
    operator_url = url or settings().database_url
    with connect(operator_url) as conn:
        rows = conn.execute(
            "SELECT login_role FROM agent_bindings WHERE run_id=%s", (run,)
        ).fetchall()
        for row in rows:
            if not str(row["login_role"]).startswith("lab_i_"):
                raise PermissionError("Refusing to retire an unexpected database role")
            conn.execute(
                sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(row["login_role"]))
            )
    _ACCESS.pop((operator_url, run), None)

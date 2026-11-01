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
                    """SELECT definition_hash FROM agent_bindings WHERE run_id=%s
                    AND definition->>'role'='inventory' LIMIT 1""",
                    (run,),
                ).fetchone()
            if not frozen or candidate.digest != frozen["definition_hash"]:
                raise ValueError("Role definition is frozen for this run")
        return dict(_ACCESS[key])
    role = RoleSpec.model_validate((definition or load_inventory_role()).model_dump())
    if role.name != "inventory":
        raise PermissionError("Inventory provisioning requires an inventory role")
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
    for key in list(_ROLE_ACCESS):
        if key[:2] == (operator_url, run):
            _ROLE_ACCESS.pop(key)


_ROLE_ACCESS: dict[tuple[str, str, str], dict[str, AgentAccess]] = {}


def role_access(
    run: str, name: str, url: str | None = None, *, agent_mode: str = "local"
) -> dict[str, AgentAccess]:
    """Provision supported role namespaces; no caller-supplied permissions or scopes."""
    from delivery.agent_specs import load_role

    if name == "inventory":
        return inventory_access(run, url)
    if name in {"household", "restaurant", "market"}:
        return supply_access(run, name, url)
    if agent_mode not in {"local", "gcp_ai"}:
        raise ValueError("Unknown agent mode")
    role = load_role("judge-gcp" if name == "judge" and agent_mode == "gcp_ai" else name)
    group = {
        "fulfillment": "lab_fulfillment_executor",
        "dispatcher": "lab_dispatch_executor",
        "courier": "lab_courier_executor",
        "judge": "lab_judge_executor",
    }[name]
    operator = url or settings().database_url
    key = (operator, run, name)
    if name in {"dispatcher", "courier"}:
        with connect(operator) as conn:
            supply = conn.execute(
                "SELECT 1 FROM supply_sessions WHERE run_id=%s", (run,)
            ).fetchone()
        if supply:
            # The supply city admits 64 meals; this bounded profile covers queued
            # assignments, acknowledgements, deferrals and deliveries. Permissions
            # stay identical and the resolved limits are frozen in the binding.
            data = role.model_dump(mode="json")
            data["version"] = "supply-v1"
            data["limits"].update(
                events_per_run=333,
                tool_calls_per_event=6 if name == "dispatcher" else 5,
                tool_calls_per_run=2000,
                memory_entries=100,
                memory_bytes=65536,
            )
            role = RoleSpec.model_validate(data)
    if key in _ROLE_ACCESS:
        with connect(operator) as conn:
            frozen = conn.execute(
                """SELECT definition_hash FROM agent_bindings WHERE run_id=%s
                AND definition->>'role'=%s LIMIT 1""",
                (run, name),
            ).fetchone()
        if not frozen or frozen["definition_hash"] != role.digest:
            raise ValueError("Role definition is frozen for this run")
        return dict(_ROLE_ACCESS[key])
    result = {}
    with connect(operator) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (run,))
        world = conn.execute("SELECT city FROM lab_worlds WHERE run_id=%s", (run,)).fetchone()
        if not world:
            raise ValueError("Unknown run")
        conn.execute(
            "INSERT INTO agent_run_budgets(run_id) VALUES (%s) ON CONFLICT DO NOTHING", (run,)
        )
        stores = [s["id"] for s in world["city"]["stores"]] if name == "fulfillment" else ["fleet"]
        if name == "courier":
            stores = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM lab_fleet WHERE run_id=%s ORDER BY id", (run,)
                ).fetchall()
            ]
        for store in stores:
            namespace = f"{name}:{store}"
            login = "lab_i_" + hashlib.sha256(f"{run}:{namespace}".encode()).hexdigest()[:24]
            password = secrets.token_urlsafe(32)
            conn.execute(
                sql.SQL(
                    """CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB
                    NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"""
                ).format(sql.Identifier(login), sql.Literal(password))
            )
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(login))
            )
            conn.execute(
                "INSERT INTO agent_bindings VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    login,
                    run,
                    namespace,
                    namespace,
                    Jsonb(role.model_dump(mode="json")),
                    role.digest,
                ),
            )
            limits = role.limits
            conn.execute(
                """INSERT INTO agent_budgets(run_id,store,events_limit,tools_limit,
                step_slots,memory_entries_limit,memory_bytes_limit)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    run,
                    namespace,
                    limits.events_per_run,
                    limits.tool_calls_per_run,
                    limits.tool_calls_per_event,
                    limits.memory_entries,
                    limits.memory_bytes,
                ),
            )
            result[store] = AgentAccess(
                run,
                namespace,
                login,
                make_conninfo(
                    operator,
                    user=login,
                    password=password,
                    application_name=namespace,
                    options=(
                        "-c statement_timeout=5000 -c idle_in_transaction_session_timeout=10000"
                    ),
                ),
            )
    _ROLE_ACCESS[key] = result
    return dict(result)


def supply_access(run: str, name: str, url: str | None = None) -> dict[str, AgentAccess]:
    """Provision entity-bound logins using that run's frozen, editable role settings."""
    from delivery.agent_specs import load_role

    manifest = load_role(name)

    if name not in {"household", "restaurant", "market"}:
        raise PermissionError("Not a supply role")
    operator = url or settings().database_url
    key = (operator, run, name)
    if key in _ROLE_ACCESS:
        return dict(_ROLE_ACCESS[key])
    result = {}
    with connect(operator) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (run,))
        session = conn.execute(
            "SELECT config FROM supply_sessions WHERE run_id=%s", (run,)
        ).fetchone()
        if not session:
            raise ValueError("Unknown supply session")
        for entity in conn.execute(
            "SELECT id,definition FROM supply_entities WHERE run_id=%s AND kind=%s ORDER BY id",
            (run, name),
        ).fetchall():
            settings_data = entity["definition"].get("agent") or session["config"]["agents"][name]
            brain = settings_data.get("brain")
            tools = manifest.tool_profiles.get("deterministic", manifest.tools)
            role = RoleSpec.model_validate(
                dict(
                    manifest.model_dump(),
                    schema_version=1,
                    role=name,
                    version="supply-v1",
                    policy="adk" if brain else "deterministic",
                    brain=brain,
                    memory=settings_data.get("memory"),
                    soul_file="SOUL.md",
                    soul=settings_data["soul"],
                    accepts=manifest.accepts,
                    emits=manifest.emits,
                    tools=tuple(sorted(brain["tools"] if brain else tools)),
                    limits=settings_data["limits"],
                )
            )
            store = entity["id"]
            login = "lab_i_" + hashlib.sha256(f"{run}:supply:{store}".encode()).hexdigest()[:24]
            password = secrets.token_urlsafe(32)
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(login), sql.Literal(password))
            )
            group = "lab_restaurant_adk_executor" if brain else "lab_supply_executor"
            conn.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(login))
            )
            conn.execute(
                "INSERT INTO agent_bindings VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    login,
                    run,
                    store,
                    f"{name}:{store}",
                    Jsonb(role.model_dump(mode="json")),
                    role.digest,
                ),
            )
            limits = role.limits
            conn.execute(
                """INSERT INTO agent_budgets(run_id,store,events_limit,tools_limit,step_slots,
                memory_entries_limit,memory_bytes_limit) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    run,
                    store,
                    limits.events_per_run,
                    limits.tool_calls_per_run,
                    limits.tool_calls_per_event,
                    limits.memory_entries,
                    limits.memory_bytes,
                ),
            )
            result[store] = AgentAccess(
                run,
                store,
                login,
                make_conninfo(
                    operator,
                    user=login,
                    password=password,
                    application_name=f"{name}:{store}",
                    options=(
                        "-c statement_timeout=5000 -c idle_in_transaction_session_timeout=10000"
                    ),
                ),
            )
    _ROLE_ACCESS[key] = result
    return dict(result)

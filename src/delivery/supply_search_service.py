"""Lease-bound ingredient relevance search with durable provider admission.

Every database operation authenticates with the original agent login. Connections
close before relevance review; no transaction or stock lock crosses network I/O.
Relevance cache entries contain no inventory quantities or domain permissions.
"""

import time
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from delivery.agent_runtime import LocalAgent
from delivery.db import connect
from delivery.queue import Event
from delivery.supply_search import JevClient, SearchEngine, SearchError, normalize_query

_ERRORS = frozenset(
    {
        "jev_not_enabled",
        "jev_model_missing_or_invalid",
        "jev_key_missing_or_invalid",
        "model_mismatch",
        "provider_http_error",
        "provider_content_type",
        "provider_timeout",
        "provider_network",
        "provider_response_too_large",
        "provider_json_invalid",
        "provider_schema_invalid",
        "provider_answer_ids_or_model_invalid",
        "provider_answer_ids_invalid",
        "usage_exceeds_reservation",
        "query_deadline_exceeded",
        "provider_error",
        "budget_denied",
        "budget_record_failed",
        "durable_accounting_required",
    }
)


def _error(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value in _ERRORS else "provider_error"


def _call(agent: LocalAgent, statement: str, parameters: tuple[Any, ...]) -> Any:
    try:
        with connect(agent.dsn) as conn:
            row = conn.execute(statement, parameters).fetchone()
            assert row is not None
            return row["data"]
    except psycopg.errors.InsufficientPrivilege:
        raise PermissionError(
            "Search requires its authenticated scope and active event lease"
        ) from None


def search_for_agent(
    agent: LocalAgent,
    event: Event,
    query: str,
    mode: str = "local",
) -> dict[str, Any]:
    """Search only this agent's physical ingredient index without reserving stock."""
    if not isinstance(query, str) or not 1 <= len(query) <= 80 or not query.strip():
        raise SearchError("query_must_be_1_to_80_characters")
    query = query.strip()
    if not normalize_query(query):
        raise SearchError("query_requires_searchable_text")
    if mode not in {"local", "jev"}:
        raise SearchError("unknown_search_mode")
    if agent.role.name not in {"restaurant", "market"} or "supply.search" not in agent.role.tools:
        raise PermissionError("Ingredient search requires a restaurant or market role")
    if not agent.reserve_budget(event):
        raise PermissionError("An active own event and durable search budget are required")
    started = time.monotonic()
    lease = (event.id, event.token, event.attempts)
    scope = _call(agent, "SELECT public.supply_search_begin(%s,%s,%s) AS data", lease)
    search_id = scope["search_id"]
    bound = (search_id, *lease)
    if mode == "jev" and scope["settings"].get("provider") != "jev":
        raise PermissionError("Jev search is not enabled in this run's frozen agent definition")

    pending_admissions: list[int] = []

    def reserve(upper_bound: int) -> bool:
        admission = _call(
            agent,
            "SELECT public.supply_search_admit(%s,%s,%s,%s,%s,%s) AS data",
            (*bound, model, upper_bound),
        )
        if admission["admitted"]:
            pending_admissions.append(admission["admission_id"])
            return True
        return False

    def record(usage: dict[str, Any]) -> None:
        if not pending_admissions:
            raise SearchError("budget_record_failed")
        admission_id = pending_admissions.pop(0)
        safe_usage = {**usage, "error": _error(usage.get("error"))}
        _call(
            agent,
            "SELECT public.supply_search_record(%s,%s,%s,%s,%s,%s) AS data",
            (search_id, admission_id, *lease, Jsonb(safe_usage)),
        )

    def cache_get(key: str) -> Any:
        return _call(
            agent,
            "SELECT public.supply_search_cache_get(%s,%s,%s,%s,%s) AS data",
            (*bound, key),
        )

    def cache_put(key: str, body: dict[str, Any]) -> None:
        _call(
            agent,
            "SELECT public.supply_search_cache_put(%s,%s,%s,%s,%s,%s) AS data",
            (*bound, key, Jsonb(body)),
        )

    model = None
    engine = SearchEngine()
    if mode == "jev":
        try:
            client = JevClient()
            model = client.model
            engine = SearchEngine(client, model=model)
        except SearchError:
            # The engine exposes a sanitized, fail-closed result for missing global
            # opt-in, explicit model or service-only credential. No admission occurs.
            pass
    result = engine.search(
        query,
        scope["candidates"],
        mode=mode,  # type: ignore[arg-type]
        namespace=f"{agent.scope.run}:{agent.scope.store}",
        cache_get=cache_get,
        cache_put=cache_put,
        reserve=reserve,
        record=record,
    )
    result["error"] = _error(result.get("error"))
    for review in result["reviews"]:
        review["error"] = _error(review.get("error"))
    result["availability_is_reservation"] = False
    result["search_id"] = search_id

    def finish(outcome: dict[str, Any]) -> Any:
        duration = min(60000, max(0, (time.monotonic() - started) * 1000))
        return _call(
            agent,
            "SELECT public.supply_search_finish(%s,%s,%s,%s,%s,%s,%s,%s,%s::numeric) AS data",
            (*bound, query, mode, model, Jsonb(outcome), duration),
        )

    try:
        stock = _call(agent, "SELECT public.supply_search_stock(%s,%s,%s,%s) AS data", bound)
    except PermissionError:
        # A completed, charged review remains auditable after lease expiry. The
        # original ticket permits finish, while fresh inventory stays denied.
        result["availability_error"] = "active_lease_required"
        finish(result)
        raise
    for row in result["results"]:
        current = stock["stock_by_id"].get(row["id"])
        row["available"] = current["available"] if current else 0
        row["stock_version"] = current["version"] if current else None
        row["availability_as_of"] = stock["sim"]
    result["availability_as_of"] = stock["sim"]
    result["availability_observed_at"] = stock["observed_at"]
    result["audit_id"] = finish(result)
    return result

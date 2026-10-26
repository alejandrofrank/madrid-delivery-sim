"""Local operator API and authenticated agent queue endpoints, never direct agent RPC."""

import hmac
import json
import os
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from delivery.agent_runtime import LocalAgent
from delivery.queue import Event
from delivery.running_city import agent_inspection
from delivery.supply import (
    CHANNEL_LEASES,
    authenticated_agent,
    blueprint,
    city_for,
    issue_channel,
    new_supply,
    replay_supply,
    run_supply,
    save_blueprint,
    supply_snapshot,
)
from delivery.supply_models import SupplyConfig

router = APIRouter()
_LEASES: dict[tuple[str, str, int], Event] = CHANNEL_LEASES


class StartSupply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=64, max_length=64)


class ProcessEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: int = Field(gt=0, strict=True)
    lease_token: UUID
    attempt: int = Field(ge=1, le=100, strict=True)


class SearchEnvelope(ProcessEnvelope):
    query: str = Field(min_length=1, max_length=80)
    mode: Literal["local", "jev"] = "local"


def channel(run: UUID, agent_id: str, authorization: str | None) -> LocalAgent:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Agent channel bearer token required")
    try:
        return authenticated_agent(str(run), agent_id, authorization[7:])
    except PermissionError:
        raise HTTPException(401, "Invalid, expired or wrong-scope agent channel") from None


@router.get("/restaurant-lab")
def restaurant_page() -> FileResponse:
    return FileResponse("web/supply.html")


@router.get("/api/supply/blueprint")
def get_blueprint() -> dict[str, Any]:
    config, revision = blueprint()
    return {
        "revision": revision,
        "config": config.model_dump(mode="json"),
        "city": city_for(config),
    }


@router.put("/api/supply/blueprint")
def put_blueprint(
    body: SupplyConfig, if_match: str | None = Header(default=None)
) -> dict[str, Any]:
    if not if_match:
        raise HTTPException(428, "If-Match blueprint revision is required")
    try:
        revision = save_blueprint(body, if_match.strip('"'))
    except ValueError:
        raise HTTPException(409, "Blueprint changed; reload before saving") from None
    return {"revision": revision, "config": body.model_dump(mode="json"), "city": city_for(body)}


def background(run: str) -> None:
    try:
        run_supply(run)
    except Exception:
        pass  # Sanitized failure code is persisted by the controller.


@router.post("/api/supply/runs", status_code=202)
def start_supply(body: StartSupply, tasks: BackgroundTasks) -> dict[str, str]:
    config, revision = blueprint()
    if body.revision != revision:
        raise HTTPException(409, "Blueprint changed; save or reload before starting")
    run = new_supply(config)
    tasks.add_task(background, run)
    return {"id": run}


@router.get("/api/supply/runs/{run}")
def get_supply(run: UUID) -> dict[str, Any]:
    try:
        return supply_snapshot(str(run))
    except ValueError:
        raise HTTPException(404, "Unknown supply run") from None


@router.get("/api/supply/runs/{run}/replay")
def replay(run: UUID) -> dict[str, Any]:
    try:
        return replay_supply(str(run))
    except ValueError:
        raise HTTPException(404, "Unknown supply run") from None


@router.get("/api/supply/runs/{run}/agents/{agent_id}")
def inspect(run: UUID, agent_id: str) -> dict[str, Any]:
    result = agent_inspection(str(run), agent_id)
    if result is None:
        raise HTTPException(404, "Unknown agent")
    snapshot = supply_snapshot(str(run))
    definition = next((a for a in snapshot["agents"] if a["agent_id"] == agent_id), None)
    if definition:
        result["agent"]["display_name"] = definition["display_name"]
    return result


@router.post("/api/supply/runs/{run}/agents/{agent_id}/channel")
def open_channel(
    run: UUID, agent_id: str, x_operator_key: str | None = Header(default=None)
) -> dict[str, Any]:
    expected = os.environ.get("DELIVERY_OPERATOR_KEY", "")
    if not expected:
        raise HTTPException(503, "Agent channel issuance requires DELIVERY_OPERATOR_KEY")
    if not x_operator_key or not hmac.compare_digest(x_operator_key, expected):
        raise HTTPException(403, "Operator authorization required")
    try:
        token = issue_channel(str(run), agent_id)
    except ValueError:
        raise HTTPException(409, "Agent is not active in this process") from None
    return {
        "token": token,
        "expires_in_seconds": 3600,
        "agent_id": agent_id,
        "transport": "durable_queue",
    }


@router.post("/api/supply/runs/{run}/agents/{agent_id}/claim")
def claim(
    run: UUID, agent_id: str, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    agent = channel(run, agent_id, authorization)
    event = agent.claim()
    if not event:
        return {"event": None}
    _LEASES[(str(run), agent_id, event.id)] = event
    return {
        "event": {
            "event_id": event.id,
            "topic": event.topic,
            "payload": event.payload,
            "trace_id": event.trace_id,
            "lease_token": str(event.token),
            "attempt": event.attempts,
            "due_sim": event.due_sim,
        }
    }


@router.post("/api/supply/runs/{run}/agents/{agent_id}/messages")
def process(
    run: UUID,
    agent_id: str,
    body: ProcessEnvelope,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """Process a leased incoming message; domain commands enqueue addressed replies."""
    agent = channel(run, agent_id, authorization)
    key = (str(run), agent_id, body.event_id)
    event = _LEASES.get(key)
    if not event or event.token != body.lease_token or event.attempts != body.attempt:
        raise HTTPException(409, "No matching active channel lease")
    processed = agent.process(event)
    _LEASES.pop(key, None)
    return {
        "acknowledged": processed,
        "event_id": event.id,
        "communication": "queued_call" if event.topic == "household.intent" else "queued_message",
    }


@router.post("/api/supply/runs/{run}/agents/{agent_id}/calls")
def process_call(
    run: UUID,
    agent_id: str,
    body: ProcessEnvelope,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    agent = channel(run, agent_id, authorization)
    event = _LEASES.get((str(run), agent_id, body.event_id))
    if agent.role.name != "household" or not event or event.topic != "household.intent":
        raise HTTPException(403, "Calls require an owned household intent lease")
    return process(run, agent_id, body, authorization)


@router.post("/api/supply/runs/{run}/agents/{agent_id}/search")
def agent_search(
    run: UUID, agent_id: str, body: SearchEnvelope, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    from delivery.supply_search_service import search_for_agent

    agent = channel(run, agent_id, authorization)
    event = _LEASES.get((str(run), agent_id, body.event_id))
    if not event or event.token != body.lease_token or event.attempts != body.attempt:
        raise HTTPException(409, "Search requires a matching active incoming message lease")
    try:
        return search_for_agent(agent, event, body.query, body.mode)
    except PermissionError:
        raise HTTPException(
            403, "Search exceeds this agent's scope or frozen provider settings"
        ) from None
    except ValueError:
        raise HTTPException(422, "Invalid search request or unavailable search provider") from None


@router.get("/api/supply/runs/{run}/entities/{entity_id}/search")
def operator_search(run: UUID, entity_id: str, query: str) -> dict[str, Any]:
    """Human operator's free search. Agent access uses bearer + leased-event route above."""
    from delivery.db import connect
    from delivery.supply_search import SearchEngine, SearchError

    with connect() as conn:
        entity = conn.execute(
            "SELECT kind FROM supply_entities WHERE run_id=%s AND id=%s", (run, entity_id)
        ).fetchone()
        if not entity or entity["kind"] not in {"restaurant", "market"}:
            raise HTTPException(404, "Select a restaurant or market in this run")
        stock = conn.execute(
            "SELECT ingredient,unit,on_hand-reserved available_now,version FROM supply_stock "
            "WHERE run_id=%s AND owner=%s ORDER BY ingredient",
            (run, entity_id),
        ).fetchall()
        clock = conn.execute("SELECT sim_time FROM runs WHERE id=%s", (run,)).fetchone()
        assert clock
        sim = clock["sim_time"]
    try:
        result = SearchEngine().search(
            query,
            [
                {
                    "id": row["ingredient"],
                    "name": row["ingredient"].replace("-", " "),
                    "unit": row["unit"],
                }
                for row in stock
            ],
            mode="local",
            namespace=f"operator:{run}:{entity_id}",
        )
    except SearchError:
        raise HTTPException(
            422, "Use a nonempty ingredient query of at most 80 characters"
        ) from None
    by_id = {row["ingredient"]: row for row in stock}
    result["results"] = [
        {
            **candidate,
            "available_now": by_id[candidate["id"]]["available_now"],
            "version": by_id[candidate["id"]]["version"],
        }
        for candidate in result["results"]
    ]
    result.update(as_of_sim=sim, availability="observation_not_reservation")
    return result


@router.get("/api/supply/runs/{run}/agents/{agent_id}/memory")
def own_memory(
    run: UUID, agent_id: str, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    agent = channel(run, agent_id, authorization)
    from delivery.db import connect

    with connect(agent.dsn) as conn:
        rows = conn.execute(
            "SELECT key,body,observed_sim,expires_sim FROM agent_memories "
            "WHERE expires_sim>agent_clock()"
        ).fetchall()
    return {"agent_id": agent_id, "memory": rows}


@router.get("/api/supply/runs/{run}/evidence")
def evidence(run: UUID) -> dict[str, Any]:
    from delivery.db import connect

    snapshot = get_supply(run)
    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        opening = conn.execute(
            "SELECT opening FROM supply_sessions WHERE run_id=%s", (run,)
        ).fetchone()
        facts = conn.execute(
            "SELECT *,payload::text canonical_payload FROM supply_facts "
            "WHERE run_id=%s ORDER BY sequence",
            (run,),
        ).fetchall()
        events = conn.execute(
            "SELECT id,topic,producer,target_store,due_sim,state,trace_id,parent_id,payload,"
            "attempts,dedupe_key,priority,error,created_at,completed_at FROM events "
            "WHERE run_id=%s ORDER BY id",
            (run,),
        ).fetchall()
        decisions = conn.execute(
            "SELECT * FROM decisions WHERE run_id=%s ORDER BY id", (run,)
        ).fetchall()
        search = {
            name: conn.execute(
                f"SELECT * FROM supply_search_{name} WHERE run_id=%s", (run,)
            ).fetchall()
            for name in ("budgets", "calls", "audits")
        }
    assert opening
    return {
        "snapshot": snapshot,
        "opening": opening["opening"],
        "facts": facts,
        "events": events,
        "decisions": decisions,
        "search": search,
        "live_capture": snapshot["run"]["status"] not in {"complete", "failed"},
        "replay": replay_supply(str(run)),
        "definition_hash": digest_config(snapshot["config"]),
    }


def digest_config(config: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

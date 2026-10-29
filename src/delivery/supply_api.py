"""Local operator API and authenticated agent queue endpoints, never direct agent RPC."""

import hmac
import json
import os
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Path
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from delivery.agent_runtime import BudgetExceeded, LocalAgent, ScopedTools
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
from delivery.supply_conversation import conversation
from delivery.supply_models import SupplyConfig

router = APIRouter()
_LEASES: dict[tuple[str, str, int], Event] = CHANNEL_LEASES


@router.get("/agent-traces")
def model_evidence_page() -> FileResponse:
    return FileResponse("web/agent-traces.html")


@router.get("/api/supply/model-comparison")
def model_comparison() -> FileResponse:
    """Fixed local operator artifact; no caller-selected paths or agent credentials."""
    if not os.path.isfile("artifacts/adk-live-comparison.json"):
        raise HTTPException(404, "No live comparison has been recorded")
    return FileResponse("artifacts/adk-live-comparison.json", media_type="application/json")


@router.get("/api/supply/agent-templates")
def agent_templates() -> dict[str, Any]:
    """Trusted operator catalogue; no credentials, model calls or executable paths."""
    from delivery.adk_contracts import restaurant_template

    brain, speed = restaurant_template("speed")
    _, cost = restaurant_template("cost")
    return {
        "restaurant-v1": {
            "brain": brain.model_dump(mode="json"),
            "souls": {"speed": speed, "cost": cost},
            "provider": "offline scripted model",
            "paid_calls": False,
        }
    }


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


class RecallEnvelope(ProcessEnvelope):
    kinds: list[str] | None = Field(default=None, max_length=9)
    limit: int = Field(default=8, ge=1, le=16, strict=True)


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


@router.get("/api/supply/runs/{run}/orders/{order_id}")
def order_history(run: UUID, order_id: str = Path(min_length=1, max_length=200)) -> dict[str, Any]:
    """Trusted local operator view; never provided as an agent tool."""
    from delivery.db import connect

    with connect() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        order = conn.execute(
            "SELECT * FROM supply_orders WHERE run_id=%s AND id=%s", (run, order_id)
        ).fetchone()
        if not order:
            raise HTTPException(404, "Unknown order in this supply run")
        session = conn.execute(
            "SELECT config->'schedule' schedule FROM supply_sessions WHERE run_id=%s", (run,)
        ).fetchone()
        assert session
        call = next((c for c in session["schedule"] if c["order_id"] == order_id), None)
        events = conn.execute(
            "SELECT e.id,e.topic,e.producer,CASE WHEN e.producer IN "
            "('lab_world','supply_ingress','lab_scenario') THEN e.producer "
            "ELSE coalesce(p.target_store,e.producer) END sender,"
            "e.target_store,e.due_sim,e.state,e.trace_id,e.parent_id,e.payload,e.attempts,e.error "
            "FROM events e LEFT JOIN events p ON p.id=e.parent_id AND p.run_id=e.run_id "
            "WHERE e.run_id=%s AND (e.trace_id=%s OR e.payload->>'order'=%s "
            "OR e.payload->>'basket'=%s) ORDER BY e.due_sim,e.id",
            (run, order_id, order_id, order_id),
        ).fetchall()
        event_ids = [event["id"] for event in events]
        facts = conn.execute(
            "SELECT sequence,event_id,actor,kind,sim_time,hash,payload->'detail' detail,"
            "payload->'projection'->'requests' request_state "
            "FROM supply_facts WHERE run_id=%s AND order_id=%s ORDER BY sequence",
            (run, order_id),
        ).fetchall()
        decisions = conn.execute(
            "SELECT id,event_id,agent,sim_time,action,detail FROM decisions "
            "WHERE run_id=%s AND (order_id=%s OR event_id=ANY(%s)) ORDER BY sim_time,id",
            (run, order_id, event_ids),
        ).fetchall()
        memories = conn.execute(
            "SELECT coalesce(b.agent_id,m.store) agent,m.key,m.body,m.observed_sim,"
            "m.expires_sim,m.event_id FROM agent_memories m LEFT JOIN agent_bindings b "
            "ON b.run_id=m.run_id AND b.store=m.store "
            "WHERE m.run_id=%s AND m.key=%s AND m.event_id=ANY(%s) "
            "ORDER BY m.observed_sim,m.store",
            (run, f"last:{order_id}", event_ids),
        ).fetchall()
        requests = conn.execute(
            "SELECT * FROM supply_requests WHERE run_id=%s AND order_id=%s ORDER BY id",
            (run, order_id),
        ).fetchall()
        typed_memory = conn.execute(
            "SELECT m.*,coalesce(b.agent_id,m.store) agent FROM agent_memory_facts m "
            "LEFT JOIN agent_bindings b ON b.run_id=m.run_id AND b.store=m.store "
            "WHERE m.run_id=%s AND m.context_type='order' AND m.context_id=%s "
            "ORDER BY m.observed_sim,m.id",
            (run, order_id),
        ).fetchall()
        latest = {(f["store"], f["kind"], f["subject"]): f for f in typed_memory}
        memories.extend(
            {**f, "fact_id": f["id"], "key": f"{f['kind']}:{f['subject']}"} for f in latest.values()
        )
        identities = {order["household"], order["restaurant"]}
        for event in events:
            for identity in (event["sender"], event["target_store"]):
                if identity:
                    identities.add(identity)
                    identities.add(identity.split(":", 1)[-1])
        entities = conn.execute(
            "SELECT id,name,kind FROM supply_entities WHERE run_id=%s AND id=ANY(%s)",
            (run, list(identities)),
        ).fetchall()
    by_id = {f["id"]: f for f in typed_memory}
    writes = []
    for decision in decisions:
        for receipt in decision["detail"].get("memory_writes", []):
            write = {**receipt, "agent": decision["agent"], "event_id": decision["event_id"]}
            current = by_id.get(write.get("fact_id"))
            if (
                current
                and current["agent"] == decision["agent"]
                and current["event_id"] == decision["event_id"]
            ):
                previous = by_id.get(current["previous_id"])
                if previous and all(
                    previous[k] == current[k] for k in ("store", "kind", "subject", "context_id")
                ):
                    write["previous"] = {
                        k: previous[k]
                        for k in ("body", "observed_sim", "expires_sim", "event_id", "version")
                    }
                elif current["previous_id"] is None:
                    write["previous"] = None
            elif "previous_id" in write and write["previous_id"] is None:
                write["previous"] = None
            writes.append(write)
    result = {
        "order": order,
        "call": call,
        "events": events,
        "facts": facts,
        "decisions": decisions,
        "memories": memories,
        "memory_history": writes,
        "memory_history_complete": bool(decisions)
        and all("memory_writes" in decision["detail"] for decision in decisions),
        "requests": requests,
        "typed_memory": typed_memory,
    }
    result["conversation"] = conversation(result, {e["id"]: e for e in entities})
    return result


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
    channel(run, agent_id, authorization)
    raise HTTPException(410, "Use POST memory/recall with the current incoming event lease")


@router.post("/api/supply/runs/{run}/agents/{agent_id}/memory/recall")
def recall_memory(
    run: UUID,
    agent_id: str,
    body: RecallEnvelope,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    import psycopg

    from delivery.db import connect

    agent = channel(run, agent_id, authorization)
    event = _LEASES.get((str(run), agent_id, body.event_id))
    if not event or event.token != body.lease_token or event.attempts != body.attempt:
        raise HTTPException(409, "Recall requires this agent current incoming message lease")
    if not agent.reserve_budget(event):
        raise HTTPException(429, "Recall lease or agent budget unavailable")
    try:
        with connect(agent.dsn) as conn:
            tools = ScopedTools(conn, agent.scope, agent.role, event)
            facts = tools.invoke("memory.read", kinds=body.kinds, limit=body.limit)
    except (BudgetExceeded, psycopg.errors.InsufficientPrivilege):
        raise HTTPException(409, "Recall lease or reserved tool budget unavailable") from None
    except (ValueError, psycopg.errors.CheckViolation):
        raise HTTPException(422, "Recall exceeds this role fact types or limits") from None
    return {
        "agent_id": agent_id,
        "memory": facts,
        "scope": "current_incoming_order",
        "limit": body.limit,
        "max_bytes": 8192,
    }


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

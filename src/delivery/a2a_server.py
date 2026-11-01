"""A2A 1.0 JSON-RPC servers backed by the existing durable agent queue.

Local, bounded adapters accept references to existing simulation entities, never
model tool calls. Customer service retains the configured ADK provider and budgets.
"""

import asyncio
import json
import os
import re
from functools import partial
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    Message,
    Part,
    Role,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from delivery.agents import Dispatcher, resolve_complaint
from delivery.config import Settings
from delivery.customer_service import CustomerService
from delivery.db import connect
from delivery.queue import Queue, publish
from delivery.telemetry import trace_span
from delivery.world import World

AgentRole = str
MAX_REQUEST_BYTES = 8192
MAX_EVENTS_PER_REQUEST = 32


class AgentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    operation: Literal["submit", "tick", "supply_tick", "replan"] = "submit"
    entity_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")


class QueuedAgentService:
    def __init__(self, role: AgentRole, url: str | None = None) -> None:
        self.role = role
        self.url = url
        self.customer = CustomerService(url)
        self.world: World | None = None

    def invoke(self, command: AgentCommand) -> dict[str, Any]:
        if command.operation == "replan":
            from delivery.chaos_agents import replan

            return replan(self.role, command, self.url)
        if command.operation == "supply_tick":
            from delivery.supply import process_agent_message

            return process_agent_message(
                str(command.run_id), self.role, command.entity_id, self.url
            )
        if command.operation == "tick":
            return self.tick(command)
        if self.role not in {"dispatcher", "customer_service"}:
            raise ValueError("Restaurants require a scoped supply or replanning message")
        topic = "order.created" if self.role == "dispatcher" else "complaint.created"
        table = "orders" if self.role == "dispatcher" else "complaints"
        field = "order_id" if self.role == "dispatcher" else "complaint_id"
        with trace_span("a2a.invoke", attributes={"agent.role": self.role}):
            with connect(self.url) as conn:
                run = conn.execute(
                    "SELECT status,sim_time FROM runs WHERE id=%s", (command.run_id,)
                ).fetchone()
                entity = conn.execute(
                    f"SELECT * FROM {table} WHERE run_id=%s AND id=%s",
                    (command.run_id, command.entity_id),
                ).fetchone()
                if not run or not entity:
                    raise ValueError("Unknown run or entity")
                existing = conn.execute(
                    "SELECT id FROM events WHERE run_id=%s AND topic=%s AND dedupe_key=%s",
                    (command.run_id, topic, command.entity_id),
                ).fetchone()
                if existing:
                    event_id = existing["id"]
                else:
                    if run["status"] in {"complete", "failed"}:
                        raise ValueError("Cannot enqueue work for a closed run")
                    event_id = publish(
                        conn,
                        run_id=command.run_id,
                        producer="generator",
                        topic=topic,
                        payload={field: command.entity_id},
                        key=command.entity_id,
                        trace_id=entity.get("order_id", command.entity_id),
                        due_sim=run["sim_time"],
                    )
            queue = Queue(self.url)
            if run["status"] in {"complete", "failed"}:
                return self.receipt(command, event_id, table)
            for _ in range(MAX_EVENTS_PER_REQUEST):
                receipt = self.receipt(command, event_id, table)
                if receipt["queue_state"] in {"done", "dead"}:
                    return receipt
                event = queue.claim(
                    self.role, command.run_id, run["sim_time"], accepted_topics=(topic,)
                )
                if event is None:
                    break
                if self.role == "dispatcher":
                    if self.world is None:
                        self.world = World()
                    queue.process(event, Dispatcher(self.world).handle)
                else:
                    advice, source = self.customer.prepare(event)
                    queue.process(event, partial(resolve_complaint, advice=advice, source=source))
            # A concurrent worker or backoff may still own the event. Never claim completion.
            return self.receipt(command, event_id, table)

    def tick(self, command: AgentCommand) -> dict[str, Any]:
        if self.role not in {"dispatcher", "customer_service"}:
            raise ValueError("Unknown scheduler role")
        with connect(self.url) as conn:
            run = conn.execute(
                "SELECT status,sim_time FROM runs WHERE id=%s", (command.run_id,)
            ).fetchone()
        if not run or run["status"] in {"complete", "failed"}:
            raise ValueError("Unknown or closed run")
        queue = Queue(self.url)
        event = queue.claim(self.role, command.run_id, run["sim_time"])
        if event is None:
            return {"progressed": False}
        if self.role == "dispatcher":
            if self.world is None:
                self.world = World()
            ok = queue.process(event, Dispatcher(self.world).handle)
        else:
            advice, source = self.customer.prepare(event)
            ok = queue.process(event, partial(resolve_complaint, advice=advice, source=source))
        return {"progressed": True, "processed": ok, "event_id": event.id}

    def receipt(self, command: AgentCommand, event_id: int, table: str) -> dict[str, Any]:
        with connect(self.url) as conn:
            event = conn.execute(
                "SELECT state,attempts FROM events WHERE id=%s AND run_id=%s",
                (event_id, command.run_id),
            ).fetchone()
            columns = (
                "status,courier"
                if table == "orders"
                else ("status,response,source,approved_refund_eur")
            )
            entity = conn.execute(
                f"SELECT {columns} FROM {table} WHERE run_id=%s AND id=%s",
                (command.run_id, command.entity_id),
            ).fetchone()
        assert event and entity
        return {
            "agent": self.role,
            "run_id": str(command.run_id),
            "entity_id": command.entity_id,
            "event_id": event_id,
            "queue_state": event["state"],
            "attempts": event["attempts"],
            "outcome": entity,
        }


class QueueAgentExecutor(AgentExecutor):
    def __init__(self, service: QueuedAgentService) -> None:
        self.service = service

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        if len(text.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise InvalidParamsError("Command exceeds byte limit")
        try:
            command = AgentCommand.model_validate_json(text)
        except ValidationError:
            raise InvalidParamsError("Expected JSON with run_id and entity_id") from None
        try:
            result = await asyncio.to_thread(self.service.invoke, command)
        except ValueError:
            raise InvalidParamsError("Unknown entity or closed run") from None
        # Immediate Message workflow; queue receipts persist in Postgres across restarts.
        await event_queue.enqueue_event(
            Message(
                message_id=uuid4().hex,
                context_id=context.context_id,
                role=Role.ROLE_AGENT,
                parts=[Part(text=json.dumps(result, default=str), media_type="text/plain")],
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError("Durable events require explicit operator action")


class LocalA2ABoundary(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (os.environ.get("DELIVERY_RUNTIME", "local") != "live"
                and request.url.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}):
            return JSONResponse({"detail": "A2A demo is local-only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"detail": "Cross-origin requests are disabled"}, status_code=403)
        # Bound streamed bodies as well as Content-Length. Cards need no body.
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_REQUEST_BYTES:
                return JSONResponse({"detail": "Request too large"}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
        return await call_next(request)


def create_a2a_app(
    role: AgentRole,
    *,
    base_url: str | None = None,
    url: str | None = None,
) -> Starlette:
    if role not in {"dispatcher", "customer_service"} and not re.fullmatch(
        r"restaurant-[a-z0-9_-]{1,80}", role
    ):
        raise ValueError("Unknown A2A role")
    origin = (
        base_url
        if base_url is not None
        else os.environ.get("DELIVERY_A2A_BASE_URL", f"http://localhost:{Settings().app_port}")
    )
    parsed = urlsplit(origin)
    cloud = os.environ.get("DELIVERY_RUNTIME", "local") == "live"
    if cloud and (parsed.scheme != "https" or parsed.username or parsed.query or parsed.fragment
                  or parsed.path not in {"", "/"}):
        raise ValueError("Cloud Agent Card requires an HTTPS service origin")
    if not cloud and (parsed.scheme != "http" or parsed.hostname not in {
        "localhost", "127.0.0.1", "::1"
    }):
        raise ValueError("The demo agent card requires a local HTTP origin")
    endpoint = f"{origin.rstrip('/')}/a2a/{role}/"
    description = (
        "Dispatch existing pending Madrid orders through the durable queue."
        if role == "dispatcher"
        else "Scoped restaurant preparation, sourcing and recovery through ADK tools."
        if role.startswith("restaurant-")
        else "ADK customer service; policy-checked advice and proactive recovery tools."
    )
    card = AgentCard(
        name=f"Madrid {role.replace('_', ' ')}",
        description=description,
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(
                url=endpoint,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        security_schemes={"google_id_token": SecurityScheme(
            http_auth_security_scheme=HTTPAuthSecurityScheme(
                scheme="bearer", bearer_format="JWT",
                description="Google-signed ID token for this Cloud Run service audience",
            )
        )} if cloud else {},
        security_requirements=[SecurityRequirement(
            schemes={"google_id_token": StringList(list=[])}
        )] if cloud else [],
        skills=[
            AgentSkill(
                id=role,
                name=role.replace("_", " ").title(),
                description=description,
                tags=["delivery", "durable-queue", "adk"],
                examples=[json.dumps({
                    "run_id": "00000000-0000-0000-0000-000000000000",
                    "operation": "replan" if role.startswith("restaurant-") else "submit",
                    "entity_id": (
                        "00000000000000000000000000000000" if role.startswith("restaurant-")
                        else "C-1" if role == "customer_service" else "O-1"
                    ),
                })],
            )
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=QueueAgentExecutor(QueuedAgentService(role, url)),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    return Starlette(
        routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/"),
        middleware=[Middleware(LocalA2ABoundary)],
    )

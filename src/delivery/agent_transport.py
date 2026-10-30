"""One agent boundary with official A2A 1.0 and in-process transports.

The scheduler sends references, never SQL connections or model-selected tool calls.
Both transports execute the same service and durable queue semantics.
"""

import asyncio
import json
import os
from typing import Any, Protocol
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest


def restaurant_name(namespace: str) -> str:
    """Stable URL-safe names for OSM pickup IDs and supply namespaces."""
    return "restaurant-" + namespace.replace("/", "-").lower()


class AgentTransport(Protocol):
    def invoke(self, agent: str, command: dict[str, Any]) -> dict[str, Any]: ...


class InProcessTransport:
    def __init__(self, url: str | None = None) -> None:
        self.url = url
        self.services: dict[str, Any] = {}

    def invoke(self, agent: str, command: dict[str, Any]) -> dict[str, Any]:
        from delivery.a2a_server import AgentCommand, QueuedAgentService

        if agent not in self.services:
            self.services[agent] = QueuedAgentService(agent, self.url)
        return dict(self.services[agent].invoke(AgentCommand.model_validate(command)))


class A2ATransport:
    def __init__(
        self, base_url: str, *, http_transport: httpx.AsyncBaseTransport | None = None,
        endpoints: dict[str, str] | None = None, authenticated: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http_transport = http_transport
        self.endpoints = endpoints or {}
        self.authenticated = authenticated

    def invoke(self, agent: str, command: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self.send(agent, command))

    async def send(self, agent: str, command: dict[str, Any]) -> dict[str, Any]:
        if not agent or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in agent):
            raise ValueError("Invalid agent identifier")
        from delivery.production_auth import role_for_agent

        origin = self.endpoints.get(role_for_agent(agent), self.base_url).rstrip("/")
        headers = {}
        if self.authenticated:
            if not origin.startswith("https://"):
                raise ValueError("Authenticated A2A requires HTTPS")
            from google.auth.transport.requests import Request
            from google.oauth2.id_token import fetch_id_token

            token = await asyncio.to_thread(fetch_id_token, Request(), origin)
            headers = {"Authorization": f"Bearer {token}",
                       "X-Serverless-Authorization": f"Bearer {token}"}
        endpoint = f"{origin}/a2a/{agent}"
        async with httpx.AsyncClient(
            transport=self.http_transport, timeout=60, headers=headers, follow_redirects=False
        ) as http:
            card = await A2ACardResolver(http, endpoint).get_agent_card()
            # Cards are discovery data, not authority to redirect to arbitrary hosts.
            advertised = (origin if self.authenticated else
                          os.environ.get("DELIVERY_A2A_BASE_URL", self.base_url).rstrip("/"))
            public_endpoint = f"{advertised}/a2a/{agent}"
            if not any(
                i.url.rstrip("/") in {endpoint, public_endpoint}
                and i.protocol_version == "1.0"
                and i.protocol_binding == "JSONRPC"
                for i in card.supported_interfaces
            ):
                raise ValueError("Agent Card does not match the configured endpoint")
            for interface in card.supported_interfaces:
                interface.url = endpoint + "/"
            client = ClientFactory(
                ClientConfig(
                    httpx_client=http, streaming=False, supported_protocol_bindings=["JSONRPC"]
                )
            ).create(card)
            responses = []
            async for reply in client.send_message(
                SendMessageRequest(
                    message=Message(
                        message_id=uuid4().hex,
                        role=Role.ROLE_USER,
                        parts=[Part(text=json.dumps(command), media_type="text/plain")],
                    )
                )
            ):
                if not reply.HasField("message"):
                    raise ValueError("Expected an immediate durable receipt")
                responses.append(json.loads("".join(p.text for p in reply.message.parts)))
            if len(responses) != 1:
                raise ValueError("Expected exactly one agent receipt")
            return dict(responses[0])


def default_transport(url: str | None = None) -> AgentTransport:
    # Explicit database URLs select isolated test state and must never reach the live app.
    if url is not None or os.environ.get("DELIVERY_AGENT_TRANSPORT", "in_process") == "in_process":
        return InProcessTransport(url)
    if os.environ.get("DELIVERY_AGENT_TRANSPORT") != "a2a":
        raise ValueError("Unknown agent transport")
    return A2ATransport(
        os.environ.get("DELIVERY_A2A_INTERNAL_URL", "http://127.0.0.1:8000"),
        endpoints=json.loads(os.environ.get("DELIVERY_A2A_ENDPOINTS", "{}")),
        authenticated=os.environ.get("DELIVERY_RUNTIME", "local") == "live",
    )

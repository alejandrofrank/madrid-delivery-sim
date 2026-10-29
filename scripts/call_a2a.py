"""Discover and call a local A2A agent with the official SDK (no paid provider)."""

import argparse
import asyncio
import json
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest
from google.protobuf.json_format import MessageToDict


async def call(base_url: str, role: str, run: str, entity: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("This demonstration client only calls a local HTTP server")
    async with httpx.AsyncClient(timeout=60) as http:
        card = await A2ACardResolver(http, f"{base_url.rstrip('/')}/a2a/{role}").get_agent_card()
        client = ClientFactory(
            ClientConfig(
                httpx_client=http,
                streaming=False,
                supported_protocol_bindings=["JSONRPC"],
            )
        ).create(card)
        request = SendMessageRequest(
            message=Message(
                message_id=uuid4().hex,
                role=Role.ROLE_USER,
                parts=[
                    Part(
                        text=json.dumps({"run_id": run, "entity_id": entity}),
                        media_type="text/plain",
                    )
                ],
            )
        )
        async for reply in client.send_message(request):
            print(json.dumps(MessageToDict(reply), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("dispatcher", "customer_service"))
    parser.add_argument("run_id")
    parser.add_argument("entity_id")
    parser.add_argument("--base-url", default="http://localhost:8010")
    args = parser.parse_args()
    asyncio.run(call(args.base_url, args.role, args.run_id, args.entity_id))

import asyncio
from uuid import uuid4

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from delivery.a2a_server import QueuedAgentService, create_a2a_app
from delivery.agent_transport import A2ATransport, InProcessTransport
from delivery.mcp_server import create_mcp_server


@pytest.mark.parametrize("agent", ["dispatcher", "customer_service", "restaurant-kitchen"])
def test_transports_share_contract_and_discovered_card(monkeypatch, agent):
    def invoke(self, command):
        return {"agent": self.role, "entity_id": command.entity_id, "operation": command.operation}

    monkeypatch.setattr(QueuedAgentService, "invoke", invoke)
    app = FastAPI()
    app.mount(f"/a2a/{agent}", create_a2a_app(agent))
    remote = A2ATransport("http://localhost:8010", http_transport=httpx.ASGITransport(app=app))
    command = {"run_id": str(uuid4()), "entity_id": "order-1"}
    assert remote.invoke(agent, command) == InProcessTransport().invoke(agent, command)


@pytest.mark.integration
def test_mcp_official_client_reads_facts_without_mutation(db_url, run_id):
    from delivery.db import connect

    with connect(db_url) as conn:
        conn.execute(
            "INSERT INTO orders(run_id,id,created_sim,ready_sim,due_sim) "
            "VALUES (%s,'mcp-order',0,0,900)",
            (run_id,),
        )

    async def exercise():
        server = create_mcp_server(db_url)
        app = server.streamable_http_app(stateless_http=True, json_response=True)
        async with (
            server.session_manager.run(),
            httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app)) as http,
        ):
            async with streamable_http_client(
                "http://localhost:8010/mcp", http_client=http
            ) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {t.name for t in tools.tools} == {
                        "order_status",
                        "courier_positions",
                        "menus",
                        "active_disruptions",
                    }
                    assert all(t.annotations.read_only_hint for t in tools.tools)
                    result = await session.call_tool(
                        "order_status",
                        {
                            "run_id": str(run_id),
                            "order_id": "mcp-order",
                        },
                    )
                    assert not result.is_error
                    assert "pending" in result.content[0].text
                    assert not (await session.call_tool("menus", {})).is_error
                    forbidden = await session.call_tool("refund_order", {"order_id": "mcp-order"})
                    assert forbidden.is_error

    asyncio.run(exercise())
    with connect(db_url) as conn:
        assert (
            conn.execute(
                "SELECT status FROM orders WHERE run_id=%s AND id='mcp-order'", (run_id,)
            ).fetchone()["status"]
            == "pending"
        )


@pytest.mark.integration
def test_every_restaurant_has_an_individual_sdk_agent_card(db_url):
    from delivery.protocol_api import agent_directory, agent_names

    async def discover():
        app = FastAPI()
        app.mount("/a2a", agent_directory(db_url))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8010"
        ) as http:
            for name in agent_names(db_url):
                response = await http.get(f"/a2a/{name}/.well-known/agent-card.json")
                assert response.status_code == 200, response.text
                card = response.json()
                assert card["skills"][0]["id"] == name
                assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
            assert (
                await http.get("/a2a/restaurant-unknown/.well-known/agent-card.json")
            ).status_code == 404

    asyncio.run(discover())


@pytest.mark.integration
def test_app_lifespan_can_restart_mcp_server(db_url, monkeypatch):
    from fastapi.testclient import TestClient

    from delivery import api
    from delivery.simulation import initialize

    monkeypatch.setattr(api, "initialize", lambda: initialize(db_url))
    for _ in range(2):
        with TestClient(api.app, base_url="http://localhost:8010") as client:
            response = client.post(
                "/mcp/",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "restart-test", "version": "1"},
                    },
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["result"]["serverInfo"]["name"] == "Madrid simulation data"

# A2A agents over the durable queue

The running application exposes two real A2A 1.0 JSON-RPC servers using the
official Python SDK 1.3.0. Each publishes a discoverable Agent Card:

| Agent | Card on localhost:8010 | Action |
| --- | --- | --- |
| Dispatcher | `/a2a/dispatcher/.well-known/agent-card.json` | Dispatch pending Madrid-baseline orders with the existing road/energy/shift policy. |
| Customer service | `/a2a/customer_service/.well-known/agent-card.json` | Classify an existing complaint with the scripted Google ADK model and enforce the existing refund approval policy. |

The request is a text part containing JSON with `run_id` and `entity_id`. An
entity must already exist in that run. The adapter publishes (or reuses) the
canonical durable event, claims a fenced lease, and invokes the existing role
handler. It processes at most 32 eligible events per request. Concurrent work or
backoff can return a `ready` or `leased` queue state; only `done` means the event
has committed. An assigned delivery still requires the simulation clock to
advance its courier. The adapter does not fabricate physical completion.

```bash
make setup
curl http://localhost:8010/a2a/dispatcher/.well-known/agent-card.json
python3 scripts/call_a2a.py dispatcher RUN_UUID ORDER_ID
python3 scripts/call_a2a.py customer_service RUN_UUID COMPLAINT_ID
```

Use identifiers from `/api/state` or a seeded baseline run. These endpoints wrap
the Madrid-baseline dispatcher and customer service, not the separate inventory
lab's scoped fleet. The client uses `A2ACardResolver`, `ClientFactory`, and
`SendMessageRequest`, including protocol version negotiation. Raw JSON-RPC
clients must send `A2A-Version: 1.0`. A response contains the queue event ID,
attempt count, domain outcome, and `paid_calls_this_request: 0`.

Customer inference is explicitly pinned to the offline ADK adapter even if the
host has a paid provider configured. Scripted advice uses `adk_offline`, so the
existing refund gate asks for human approval and never grants a refund based on
fixture output. Repeating an entity request reuses its event and cached model
receipt; it does not reserve a second inference call. No model or SQL tool calls
are accepted from a client.

This is a local demonstration: Compose binds port 8010 to loopback; the adapter
also checks Host/Origin and caps the streamed HTTP body at 8 KiB. The immediate
A2A Message workflow is advertised without streaming or push notifications.
Business work survives process restarts in PostgreSQL; no durable A2A task store
is claimed. An internet deployment requires authentication, tenant-to-run
authorization, ingress limits, and a reviewed public Agent Card.

Implementation: [server and queue adapter](../src/delivery/a2a_server.py),
[SDK client](../scripts/call_a2a.py), and
[protocol plus real-agent integration tests](../tests/test_a2a_server.py).
Tests discover both cards and call both servers using the real SDK over ASGI;
the integration case checks actual courier assignment, ADK advice, refund
escalation, and replay with one durable zero-dollar reservation.

Official references checked on 2026-10-29:
[A2A Python SDK](https://a2aproject.github.io/a2a-python/) and
[server tutorial](https://a2a-protocol.org/latest/tutorials/python/5-start-server/).
The installed 1.3 SDK uses protobuf message types; pre-1.0 Pydantic examples
are not used here.

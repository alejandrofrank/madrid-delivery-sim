# Project brief: Madrid Delivery Sim (multi-agent showcase)

Goal: a portfolio project for Alejandro Frank proving deep, hands-on mastery of multi-agent systems: queues between agents, hierarchy/supervision, shared memory, tool permissions, observability, evals and failure handling. It must be a hard, real engineering project, not a toy.

## Setup (do first)
1. Create a PRIVATE GitHub repo `madrid-delivery-sim` under the alejandrofrank account and push this folder to it.
2. Reuse the API keys/credentials already configured for Alejandro's local repos `scrapmarket` or `ai-inbox` (find them on this computer, e.g. their .env files). Copy only the needed LLM keys (Gemini/Vertex or OpenAI) into this project's `.env`, add `.env` to `.gitignore`, never commit secrets, never print them.

## Concept
A live simulation of a last-mile delivery company in Madrid, shown on a map.
- World: real Madrid street graph from OpenStreetMap (osmnx), real neighbourhoods, 3+ hubs (e.g. Vallecas, Alcobendas, Getafe), supermarkets/restaurants as pickup points, simulated customers placing orders with lunch/dinner peaks.
- Agents: couriers (bike/moto/van, battery/fuel, shifts), hub managers, dispatchers, store agents (prep time, stockouts), customer-service agents (complaints, refunds, "where's my order"), a city operations director (targets, scaling, rerouting), and a chaos agent (rain, M-30 closures, strikes, promo spikes).

## Architecture requirements (the interview topics)
- Queues: agents communicate only via event queues (Redis Streams or Postgres-backed), with retries, dead-letter queues, idempotency keys, priorities, backpressure.
- Hierarchy: courier -> dispatcher -> director, with escalation rules and approval gates (e.g. refunds > 100 EUR need manager approval). Make the topology configurable so flat vs hierarchical vs planner-executor can be compared.
- Shared memory: authoritative city state in Postgres+PostGIS; per-agent episodic memory (vector store, e.g. pgvector); explicit write policies, conflict resolution, role-based access.
- Tools: each agent gets least-privilege tools (ideally exposed via MCP).
- Cost control: deterministic rules/routing for routine decisions; LLM only for judgement (complaints, replanning, strategy). Cheap model (Gemini Flash or local) by default, per-agent token/cost budgets.
- Observability: end-to-end traces per order across agents (OpenTelemetry or Langfuse), replayable incidents.
- Evals: fixed scenario suite (rush hour, rain + closure, courier dropout, prompt injection in a complaint, two dispatchers claiming one order) scored on on-time rate, cost per delivery, LLM cost, policy violations, complaint resolution. Publish results per architecture.
- Failure modes handled and tested: agent loops, hallucinated tool calls, silent agents, duplicate assignment, prompt injection.

## Visual layer
Web UI (e.g. Next.js + deck.gl/MapLibre): Madrid map with moving couriers, order pins, delay heatmap; agent decision timeline; click a courier to see its reasoning trace; KPI dashboard (on-time %, cost/delivery, LLM spend, complaints).

## Stack suggestion
Python (simulation, agents, FastAPI), Postgres+PostGIS+pgvector, Redis, Docker Compose for local run, Next.js frontend. Keep everything runnable locally for ~0 EUR beyond small LLM usage.

## Milestone 1 (build now)
- Repo scaffold, docker-compose (Postgres/PostGIS, Redis), README with architecture diagram (mermaid).
- Madrid graph loaded, hubs/stores/customers seeded, order generator.
- Queue layer with retries + DLQ + idempotency, tests.
- Courier + dispatcher agents (rule-based first), one LLM-backed customer-service agent.
- Minimal map UI showing couriers moving and orders.
- `make demo` runs a 10-minute simulated day.
Commit in small meaningful commits and push. Then write ROADMAP.md with the remaining milestones (hierarchy experiments, memory, evals, observability, chaos).

Code quality: typed Python, tests (pytest), clear module boundaries. No em-dashes in docs.

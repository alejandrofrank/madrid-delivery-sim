# Milestone 1 validation

Validation date: 2026-10-22. Runtime: Docker Desktop Linux containers, Python 3.12, Postgres 17 + PostGIS 3.5, Redis 7.4. Host checks also ran under Windows Python 3.12. Exact Python dependencies are in `requirements.lock`.

The full-day seed-42 smoke run completed with 247 generated and delivered orders, 100% on time, EUR 1.83 estimated operating cost per delivery, 996 acknowledged queue events, no dead letters, and no pending/active orders at close. This is a feasible baseline, not a stress-test claim.

The real Vertex path completed three calls using `gemini-2.5-flash-lite`: 518 measured tokens and USD 0.000457 estimated cost at configured rates. The fourth complaint exhausted the conservative reservation budget and escalated. The EUR 500 injection complaint also required approval with zero refund. No secret values were printed or committed.

Tests cover concurrent claims, idempotency, retries, DLQ/replay, stale-worker fencing, crash exhaustion, outbox rollback, duplicate assignment, real road paths, prep waiting, schema rejection, refund approval, provider redaction, concurrent budgets, cached results, a complete short simulation, and API behavior.

Chrome/Playwright checks at 1440x1100 and 390x844 exercise courier/order selection, decision evidence, ledger filters, and service tabs. Both render without page errors or document overflow. The map uses local OSM geometry and vendored Leaflet, with no tile server.

The exact `make demo` acceptance run and final verification counts are recorded in STATUS.md after completion. Raw snapshots/screenshots remain in ignored `artifacts/`; `docs/demo.png` is the reviewed interface capture. GitHub Actions repeats container checks and seeded-day invariants without LLM credentials.

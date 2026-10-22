# Milestone 1 validation

Validation date: 2026-10-22. Runtime: Docker Desktop Linux containers, Python 3.12, Postgres 17 + PostGIS 3.5, Redis 7.4. Host checks also ran under Windows Python 3.12. Exact Python dependencies are in `requirements.lock`.

The full-day seed-42 smoke run completed with 247 generated and delivered orders, 100% on time, EUR 1.83 estimated operating cost per delivery, 996 acknowledged queue events, no dead letters, and no pending/active orders at close. This is a feasible baseline, not a stress-test claim.

The real Vertex path completed three calls using `gemini-2.5-flash-lite`: 518 measured tokens and USD 0.000457 estimated cost at configured rates. The fourth complaint exhausted the conservative reservation budget and escalated. The EUR 500 injection complaint also required approval with zero refund. No secret values were printed or committed.

The 16 tests cover concurrent claims, idempotency, retries, DLQ/replay, stale-worker fencing, crash exhaustion, outbox rollback, duplicate assignment, real road paths, prep waiting, schema rejection, refund approval, provider redaction, concurrent budgets, cached results, Unicode/JSON-escape budget limits, a complete short simulation, and API behavior. Ruff and mypy pass. One upstream Starlette TestClient deprecation warning is nonblocking.

Chrome/Playwright checks at 1440x1100 and 390x844 exercise courier/order selection, decision evidence, ledger filters, and service tabs. Both render without page errors or document overflow. A live check observed eight courier markers move over 2.5 seconds. The map uses local OSM geometry and vendored Leaflet, with no tile server.

The exact `make demo` acceptance run completed with `wall_seconds=600` and run ID `6e6963f7-bd55-4cf1-83b6-97df465fc1aa`. Its reviewed metrics are in [milestone-1-result.json](milestone-1-result.json), including complaint outcomes and zero unauthorized refund. Raw snapshots/screenshots remain in ignored `artifacts/`; `docs/demo.png` is the reviewed interface capture.

[GitHub Actions run 39720147199](https://github.com/alejandrofrank/madrid-delivery-sim/actions/runs/39720147199) passed for implementation commit `930b35f`: container build, all 16 tests, Ruff, mypy, the full seeded day without paid calls, artifact export, and delivery invariants. The final handoff commit changes documentation only.

# Status

2026-10-22: Setup and Milestone 1 complete and pushed to `main`.

Repo: https://github.com/alejandrofrank/madrid-delivery-sim (private).

- Created the repo, reused existing Vertex authentication in ignored `.env`, and verified no credential values exist in Git history.
- Built Docker/PostGIS/Redis services, the real Madrid graph and seeded city, durable queues, courier/dispatcher agents, bounded LLM customer service, and the live map with decision traces.
- Verified 16 tests, Ruff, mypy, desktop/mobile browser checks, and [passing CI](https://github.com/alejandrofrank/madrid-delivery-sim/actions/runs/39720147199).
- Ran the actual 10-minute `make demo`: 247 deliveries, 996 acknowledged events, zero dead letters, three successful Vertex calls.
- Added architecture/setup documentation, acceptance evidence, and ROADMAP.md for remaining milestones.

Local UI is running at http://localhost:8010. Blockers: none.

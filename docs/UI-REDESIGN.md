# UI redesign evidence

Work is isolated in the sibling mds-ui worktree on feat/ui-redesign, based on main at 69135c9. Application source and backend behavior are unchanged at this baseline.

## Confirmed context

Technical portfolio reviewers first; operators use the same console. The user chose comp-first. PRODUCT.md records the product constraints. Three composition references are retained in .impeccable/mocks with their exact prompts and image provenance. Selection is pending: map-led, agent-led, or evidence-led. These images are illustrative layout references, not measured product results.

## Reproduce the isolated environment

Run these commands from mds-ui, never from the original checkout:

~~~bash
docker compose -p mds-ui -f compose.yaml -f compose.ui.yaml up -d --build --wait
docker compose -p mds-ui -f compose.yaml -f compose.ui.yaml exec -T app delivery init
~~~

The isolated application uses localhost:8021, Postgres 55439 and Redis 56389. It has its own containers and database volumes. Frontend and documentation files are mounted from this worktree. Stop it with the same Compose arguments followed by down (volumes are retained).

## Screenshot loop

Node 20 or newer is required. Playwright is development-only; the application gains no JavaScript runtime dependency.

~~~bash
npm ci
npx playwright install chromium
node scripts/screenshot_ui.ts --url http://127.0.0.1:8021 --phase before
node scripts/screenshot_ui.ts --url http://127.0.0.1:8021 --phase after --check
~~~

On a Linux host missing Chromium libraries, install the documented Playwright browser dependencies or use an existing compatible Chromium environment. This session unpacked three OS packages into ignored artifacts/browser-libs and set LD_LIBRARY_PATH for its Bash process only.

The runner captures every workspace at 1440×960, 1280×800, and 390×844, plus desktop viewport crops. Full-page screenshots and a machine-readable report live in docs/media/<phase>. It waits for document and page readiness rather than network idle because the live workspaces poll continuously.

The initial captures show real empty/ready states in a newly seeded, isolated local database. Missing test receipts and AI comparisons are intentionally visible. They are not populated-run or model-call evidence.

## Baseline

Seven workspaces × three viewports returned HTTP 200 with no browser exceptions, horizontal document overflow, or unlabeled visible controls detected by the lightweight capture checks. Those checks do not certify WCAG conformance. Independent Impeccable design and technical reviews are retained beside the screenshots.

## Resource references

- IBM Plex Sans and Mono are an OFL font pairing: https://github.com/IBM/plex
- CARTO currently requires a free key for its hosted basemaps: https://www.carto.com/basemaps/
- The existing Madrid OSM street geometry and synthetic city geometry remain distinct; the implementation must not relabel a fictional grid as Madrid.

After implementation this document will carry the per-page change summary, before/after pairs, demo GIF, final audit and verification evidence.

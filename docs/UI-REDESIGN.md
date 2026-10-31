# UI redesign · verification and visual record

The redesign is integrated into the main application at **[localhost:8010](http://localhost:8010/)**.
The original seven-workspace review below is a historical record. The Delivery
grid UI has since been retired, leaving six workspaces; its URL redirects to Operations.
The former port 8021 preview is no longer a separate development target.

The audience is technical reviewers first, with operators using the same interface.
The selected direction combines an agent-led roster with a continuously visible map.
Simulation controls sit in their own view; starting a session opens Operations.
The product view shows business metrics and concise evidence, with deeper details one click away.

## Changes by page

| Workspace | Change |
| --- | --- |
| Madrid · `/` | Dense agent/map pairing, role/status/search filters, distinct bike/moto/van SVGs, status colors, low-zoom clustering, route interpolation, fading traveled trails, symbol/route legend, popups and trace links. Delivered orders, on-time rate, estimated cost/delivery and orders/min use actual runtime data. |
| Restaurants · `/restaurant-lab` | Unique entity names and stable agent IDs, searchable role/status roster, map selection, business metrics, observed fact counts and separate definitions. |
| Inventory · `/lab` | Shared shell and dark map, clear no-session state, unavailable controls disabled, checkpoint and stock inspection retained. |
| Health · `/health` | Shared visual hierarchy, readable evidence/status tables, explicit missing measurements and stale-result warnings; original test/evaluation behavior preserved. |
| Traces · `/agent-traces` | Filterable decision/tool/model timeline, readable step summaries, latency/cost where recorded, explicit unavailable values, raw receipts behind disclosure. |
| Architecture · `/architecture` | Twenty searchable chapters, eight restyled D2 diagrams with embedded Plex fonts, complete initial graph overviews, expandable details and a finite, replayable request-flow illustration. |

Every route uses shared graphite/teal tokens, local IBM Plex Sans and Mono, the same navigation, visible keyboard focus and reduced-motion handling. No paid map or chart service was added. Madrid now has a complete locally served OpenFreeMap vector basemap, with the cached OpenStreetMap routing graph as a fine overlay. The pack contains 332 tiles (36.51 MB, zoom 10–14); no key or runtime map request is needed. Fictional labs retain their source-backed SVG geography.

## Verification

- The final correction regression passed **565 tests** in 396.22 seconds. Its source fingerprint matches the running app and no source changed during the run. Ruff passes and mypy reports no issues in 49 source files. [Verification receipt](evidence/ui-redesign-local.json).
- Six Playwright integration groups pass: roster filters/identity, map selection and keyboard navigation, trace filtering/disclosure, inventory checkpoints, documentation interactions/whole diagrams, and all seven populated mobile layouts.
- Final screenshots cover 1440×960 desktop, 1280×800 laptop and 390×844 mobile; the approved-comp comparison uses 1536×1024.
- Solid-background DOM contrast checks found no candidates below the thresholds; document overflow checks pass at 320, 390, 1280 and 1440 px. This is not a full accessibility certification. Small spatial map targets retain equivalent roster controls and keyboard access.
- Documentation checks resolve **20 chapters / 83 source files**. All **eight** generated diagram sources, labels and fingerprints verify.
- No backend source, database schema, agent policy or provider behavior changed.

Evidence: [interaction checks](media/after/interactions.json), [browser measurements](media/after/browser-audit.json), [capture report](media/after/report.json), [rebuild review](media/correction/full-review.md), [correction verdict](media/correction/verdict-pass.md), [map checks](media/correction/functional/map-checks.json), [layout checks](media/correction/verified/layout-checks.json), [wheel check](media/correction/verified/wheel-check.json).

An earlier attempt recorded 564 passes and one queue-lock deadline timing failure. That unchanged test passed alone, then the complete unchanged suite passed 565/565 without concurrent browser recording. The existing Starlette/httpx deprecation warning remains. No backend or test code was changed to obtain the pass.

### Correction after the rejected implementation

The user correctly rejected the first integrated version: the light-to-gray reskin and sparse routing mesh did not reproduce the approved direction. The previous scoped finish report is historical evidence, not acceptance of that result.

The correction restores the dark ground, compact shell and title, four shallow metrics, a dense agent roster beside the full city map, concise selected-agent evidence and six readable ledger rows at 1536×1024. Role, status, task and actual delivery history stay visible. Completed sessions default to recorded orders instead of an empty active-only ledger.

Map work includes a real local vector basemap, geometry-aligned resize transitions, low-zoom coverage, selected-label placement, route framing and a mobile legend below the canvas. Delivery's mobile map controls follow the wrapped filters. Mouse-wheel zoom is enabled by default as requested; Escape releases the wheel to the page and the Scroll zoom button restores it.

The final verdict resolves all five bounded review findings, with no remaining P0/P1 in that scope. Browser quality, exact image reproduction and user acceptance remain separate.

### Honest limits

History curves are collected during the current visit, not reconstructed from unavailable historical samples. Completed sessions opened afresh say that history is unavailable. Restaurant activity totals count distinct retained facts observed during that visit, not lifetime work. Missing per-step latency/cost remains “not recorded”; the p95 diagnostic does not invent a measurement. The demo is a local simulation, not a claim of a live cloud deployment.

The independent review used the packaged Impeccable reviewer definition because the named custom agent was unavailable. The comp-led workflow still has the **plates phase open**; no new approval receipt is fabricated. The current [fixed-region comparison](media/correction/comparison/report.json) remains **drift**, not a passed reproduction gate. The parent inspected the full comparison and worst crops: actual agents and geography differ from illustrative names/locations, and the separately accepted simulation view differs from the comp's start controls. The earlier 0.578 contradicted comparison is retained in historical evidence and is superseded by this correction.

The eight D2 diagrams retain the earlier graphite/teal palette rather than the exact revised map cyan. Their shapes, labels and embedded Plex type remain consistent. Physical-device touch is untested; Chromium-emulated touch pan and legend interaction pass. Map coverage is bounded to Madrid.

## Before / after

These pairs are actual application screenshots at 1440×960, not concept renders.
Before and after use available local runs, so order counts and session states can differ.
Full-page, laptop and mobile captures are retained alongside each viewport image.

| Page | Before | After |
| --- | --- | --- |
| Madrid | ![Madrid before](media/before/madrid-viewport.png) | ![Madrid after](media/after/madrid-viewport.png) |
| Restaurants | ![Restaurants before](media/before/supply-viewport.png) | ![Restaurants after](media/after/supply-viewport.png) |
| Inventory | ![Inventory before](media/before/lab-viewport.png) | ![Inventory after](media/after/lab-viewport.png) |
| Health | ![Health before](media/before/health-viewport.png) | ![Health after](media/after/health-viewport.png) |
| Traces | ![Traces before](media/before/agent-traces-viewport.png) | ![Traces after](media/after/agent-traces-viewport.png) |
| Architecture | ![Architecture before](media/before/documentation-viewport.png) | ![Architecture after](media/after/documentation-viewport.png) |

## Live demo and reproduction

![Actual local agent and map activity](media/ui-demo.gif)

The refreshed GIF records the corrected live interface during a real free local run with agent selection, changing metrics and moving markers.
It plays twice; the [capture metadata](media/ui-demo.json) records provenance and duration.
The application itself honors reduced motion.

From the isolated worktree, in Bash:

```bash
docker compose -p mds-ui -f compose.yaml -f compose.ui.yaml up -d --build
npm ci
npx playwright install --with-deps chromium
node scripts/screenshot_ui.ts --url http://127.0.0.1:8021 --phase after --check
node scripts/record_ui_demo.ts --url http://127.0.0.1:8021
python3 scripts/render_ui_gif.py
```

Node 20 or newer is required for the development scripts. GIF encoding needs Pillow.
To capture specific existing runs, pass `--runs path/to/runs.json`; see the screenshot script's documented flags.
Runtime pages use no frontend framework or chart dependency.

Shared implementation guidance: [design system](DESIGN-SYSTEM.md), [normative tokens and components](../DESIGN.md), [diagram maintenance](diagrams/README.md).

# Shared workspace design

The seven local workspaces share the dark operations system defined in [DESIGN.md](../DESIGN.md). Its frontmatter is the normative portable token record; [the design sidecar](../.impeccable/design.json) adds component specimens, focus behavior, motion, elevation and responsive metadata. This file describes how that system fits the existing application.

## Direction and source of truth

The approved replacement direction is a calm, dense operations console: blue graphite ground, local IBM Plex Sans and Mono, teal selection, fine neutral rules and readable working rows. It replaces the previous white/Arial reference. Compact titles and working controls take precedence over decorative presentation. Agents and the map share the operational viewport, while technical reviewers can reach the retained evidence behind each decision.

Palette and font primitives come from `web/tokens.css`. The page first loads these tokens, then its own layout stylesheet and the shared `web/workspace.css` layer. Delivery and Restaurants also load `web/agents.css` for the shared roster. Page styles still contain older aliases and exceptions; follow the resulting cascade and rendered artifact, not an isolated earlier declaration. `web/console.js` provides small shared SVG symbols, observed-series sparklines and accessible roster/map behavior.

Local font files live in `web/fonts/` with their licenses. Their URLs require no external font service. IBM Plex Sans Regular, Medium and SemiBold and IBM Plex Mono Regular are available; do not assume a full family of additional weights exists.

## Workspaces and navigation

| Workspace | Route | Working emphasis |
| --- | --- | --- |
| Operations | `/` | Madrid couriers, cached street graph, selected decisions and order ledger |
| Delivery | `/delivery-lab` | Agent roster, fictional grid, delivery handoffs and order book |
| Restaurants | `/restaurant-lab` | Household calls, kitchen and market agents, city network and entity inspector |
| Inventory | `/lab` | Synthetic stock scenario, checkpoint evidence and recovery |
| Health | `/health` | Test categories, evaluations, source freshness and operational checks |
| Traces | `/agent-traces` | Recorded decisions, scoped tools and retained model evidence |
| Architecture | `/architecture` | Twenty chapters, component explorer and eight source-backed diagrams |

`web/workspace.js` mounts the same seven-link navigation, active-page indication, skip link and mobile disclosure everywhere. Escape closes the mobile menu and restores focus; ordinary anchors preserve browser navigation. Existing no-script links are a fallback rather than an alternate interactive application.

The page identity is `data-page` on the body. Delivery's `data-workspace` attributes remain reserved for its local Overview, Orders, Fleet and Stores controls; assigning that attribute to an ancestor would interfere with its delegated click handler.

The shell collapses at 1080px. Madrid's agent/map columns stack at 800px; Delivery and Restaurants stack at 900px. The Architecture page removes its right outline at 1250px and converts the topic list to a disclosure at 700px. Preserve local overflow for wide tables, roster history, code and expanded diagrams.

## Operational information and truthful evidence

Simulation and definition settings are separate from the operation view in Madrid, Delivery and Restaurants. Starting the Madrid simulation returns to the operational view. Compact metric strips lead into the roster/map pair; selection opens a concise summary before detailed evidence.

An agent's actual name is distinct from its role template and technical identifier. Restaurants exposes all three when available. Offline couriers are labeled as unavailable for assignment. Search must still find the real entity identity.

Totals and rates are distinct. `Ops.sparkline` renders only after two finite samples exist. Roster curves use observations from the current visit and activity per simulated minute, with at most 30 retained rate samples. A completed run without captured history explicitly reports that history is unavailable. Do not generate a decorative series to fill that gap.

The Madrid cost tile is an operating estimate in EUR. Per-decision latency, step cost and individual tool inputs/outputs remain unknown or not retained when the source does not provide them. Health preserves historical receipt dates and source-change warnings. Inventory's stock, locations and fixture roads remain visibly synthetic. UI polish does not establish model quality or current source health.

## Madrid map navigation

Madrid uses the cached local OpenStreetMap road graph and local Leaflet assets. The view does not require a paid map provider, and attribution remains visible. Simulation grid maps elsewhere are explicitly fictional.

Madrid opens in Overview: the wheel scrolls the document, markers remain selectable, and visible zoom buttons work. Explore map enables dragging, wheel/touch zoom and keyboard navigation; Escape returns to Overview without changing the view. There is no inertial panning. Follow selection is an explicit action for a valid selected courier/order; it does not imply automatic following.

Navigation remains bounded to the service rectangle with 12% padding. Minimum zoom adapts to the viewport and maximum zoom is 17. Fit network frames the service area. Selection framing caps zoom at 16 and is enabled only when valid in-bounds geometry exists. Working/idle/attention/order labels, role symbols and planned/traveled route styles explain what the map shows.

## Architecture and diagrams

The reader contains 20 chapters and eight D2 diagrams. The sources in `docs/diagrams/` and published counterparts in `web/diagrams/` retain D2 0.9.0, ELK graph layout and native SVG text. The diagrams use dark graphite surfaces, pale ink, neutral connectors and teal durable-state emphasis. Local IBM Plex source fonts live in `docs/diagrams/fonts/` and are embedded in generated SVGs.

An inline diagram initially shows its whole geometry. Expand opens the same asset for detailed reading with pan and zoom; Fit returns to the complete diagram. Do not clip the initial overview or imply that tiny overview text is the only reading mode. Numbered execution phases, 18px node text and 16px message text are authored at source scale. Source inspection remains available under each diagram.

The four-stage request → queue → agent → commit illustration is finite and replayable. It is labeled as an illustrated lifecycle, not runtime telemetry. Reduced-motion settings disable the stage animation.

Rebuild and verify diagrams from Bash:

```bash
python3 scripts/render_documentation_diagrams.py --install
python3 scripts/render_documentation_diagrams.py --check
```

The installer obtains and verifies the pinned D2 binary in ignored cache storage. Once installed, an offline rebuild uses:

```bash
python3 scripts/render_documentation_diagrams.py
```

The check validates chapter/fence mapping, source/reference fingerprints, generated checksums, native text and the absence of external-image/script/HTML-label content. Generated assets and their sources travel together.

## Asset versions and checks

CSS and JavaScript URLs contain content digests. After editing assets, refresh and check them:

```bash
python3 scripts/version_web_assets.py --write
python3 scripts/version_web_assets.py
```

The second command checks all seven HTML pages for stale URLs and missing local assets. This prevents an older cached theme from surviving a new HTML shell without changing API endpoints or simulation definitions.

Inspect idle and populated states across all seven routes at desktop, laptop and mobile widths. Check navigation, active selection, keyboard focus, Escape, reduced motion and local overflow. Exercise a complete selection-to-evidence path, actual identity search, simulation settings, map modes, order filters, source inspection, chapter search and all eight diagrams. Preserve existing seeded outcome and role-isolation checks as the business-behavior baseline.

Current visual evidence is under `docs/media/after/`: desktop, laptop, mobile and viewport captures for each workspace, plus interaction/audit records. These captures are evidence of the recorded states, not a blanket accessibility or product-quality certification. Full screen-reader, touch-gesture and 200% zoom conformance are not established by the sampled checks.

## Evidence limits

The original comp-led CLI plates phase remains open; downstream phase receipts must not be invented. The fixed-box comparison against the original comp has not passed. The user prioritized integration, and the implementation preserves real behavior, real geography and the pixels visible in the final captures rather than inventing comp data. That priority explains the divergence; it does not convert an open visual gate into a pass.

The detailed redesign findings, verification results and remaining limitations belong in [UI-REDESIGN.md](UI-REDESIGN.md). This design reference records the implemented system and does not certify the unfinished comp workflow. Legacy page-specific typography, uppercase metadata and small map annotations remain existing exceptions; they are not promoted into a new decorative heading or icon language.

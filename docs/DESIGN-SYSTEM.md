# Earlier console design (historical)

This chapter records the previous dark console and its map/diagram implementation. Its navigation, palette and layout measurements are historical. The current shared interface is documented in [Product interface](PRODUCT-UI.md), [DESIGN.md](../DESIGN.md) and `web/tokens.css`; those sources take precedence for new work.

The six local workspaces share the dark operations system defined in [DESIGN.md](../DESIGN.md). Its frontmatter is the normative portable token record; [the design sidecar](../.impeccable/design.json) adds component specimens, focus behavior, motion, elevation and responsive metadata. This file describes how that system fits the existing application.

## Direction and source of truth

The approved replacement direction is a calm, dense operations console: deep blue graphite ground, local IBM Plex Sans and Mono, cyan selection, fine neutral rules and readable working rows. The current rebuild also replaces the rejected raised gray panels and sparse Madrid graph-only map. Compact titles and working controls take precedence over decorative presentation. Agents and the map share the operational viewport, while technical reviewers can reach the retained evidence behind each decision.

Palette and font primitives come from `web/tokens.css`. The page first loads these tokens, then its own layout stylesheet and the shared `web/workspace.css` layer. Operations and Restaurants also load `web/agents.css` for the shared roster. Page styles still contain older aliases and exceptions; follow the resulting cascade and rendered artifact, not an isolated earlier declaration. `web/console.js` provides small shared SVG symbols, observed-series sparklines and accessible roster behavior.

Local font files live in `web/fonts/` with their licenses. Their URLs require no external font service. IBM Plex Sans Regular, Medium and SemiBold and IBM Plex Mono Regular are available; do not assume a full family of additional weights exists. The vector basemap is the explicit exception: locally cached Noto Sans Regular glyphs provide cartographic labels, while UI controls, selected-agent labels and operational overlays stay Plex.

## Workspaces and navigation

| Workspace | Route | Working emphasis |
| --- | --- | --- |
| Operations | `/` | Madrid couriers, full local vector basemap plus street graph, selected decisions and order ledger |
| Restaurants | `/restaurant-lab` | Household calls, kitchen and market agents, searchable agent roster and entity inspector |
| Inventory | `/lab` | Synthetic stock scenario, checkpoint evidence and recovery |
| Health | `/health` | Test categories, evaluations, source freshness and operational checks |
| Traces | `/agent-traces` | Recorded decisions, scoped tools and retained model evidence |
| Architecture | `/architecture` | Twenty chapters, component explorer and eight source-backed diagrams |

`web/workspace.js` mounts the same six-link navigation, active-page indication, skip link and mobile disclosure everywhere. Escape closes the mobile menu and restores focus; ordinary anchors preserve browser navigation. Existing no-script links are a fallback rather than an alternate interactive application.

The page identity is `data-page` on the body. The retired `/delivery-lab` route redirects to Operations; legacy delivery runs remain inspectable through their JSON evidence.

The desktop shell uses a 44px header token, with a 56px token below 600px; it collapses to a menu at 1080px. Madrid's agent/map columns stack at 850px; the restaurant roster and inspector stack at 900px. The Architecture page removes its right outline at 1250px and converts the topic list to a disclosure at 700px. Preserve local overflow for wide tables, roster history, code and expanded diagrams.

## Operational information and truthful evidence

Simulation and definition settings are separate from the operation view in Operations and Restaurants. Starting the Madrid simulation returns to the operational view. Compact metric strips lead into the working interface. Operations pairs its roster with the real Madrid map. Restaurants expands its roster across the page until selection opens an adjacent inspector. Inventory puts the store selector and stock table first, followed by basket and recovery evidence.

Madrid's desktop title uses 25px Plex Sans/600, reducing to 23px below 1400px and 22px below 850px. Four shallow metrics use a single ground-colored band with an 80px minimum height. The roster/map split is 45.5/54.5 with an 8px gap and a shared height of clamp(360px, 45vh, 460px). Its comparison columns expose Agent, Role, Status, Current task, Delivered and Rate/min; responsive layouts hide secondary columns while keeping identity/task/state legible.

The selected-evidence strip has an 88px minimum height and exposes identity, task/energy, last decision and trace/detail actions. The compact ledger follows at an 8px gap, with 11px text, 5px vertical heading padding and 1px vertical cell padding. Completed runs default to existing All orders, preserving a useful populated ledger instead of manufacturing data. First-viewport row count is assessed by fresh captures, not assumed from a CSS change.

Below 850px Madrid uses a 400px map region followed by its legend in normal document flow. The open or closed legend no longer occupies the selected courier's map space.

An agent's actual name is distinct from its role template and technical identifier. Restaurants exposes all three when available. Offline couriers are labeled as unavailable for assignment. Search must still find the real entity identity.

Totals and rates are distinct. `Ops.sparkline` renders only after two finite samples exist. All curves use observations from the current visit and activity per simulated minute. Madrid retains at most 40 metric observations; the shared restaurant roster retains at most 30 rate samples. A completed run without captured history explicitly reports that history is unavailable. Do not generate a decorative series to fill that gap.

The Madrid cost tile is an operating estimate in EUR. Per-decision latency, step cost and individual tool inputs/outputs remain unknown or not retained when the source does not provide them. Health preserves historical receipt dates and source-change warnings. Inventory's stock remains labeled as simulated; fixture roads are no longer rendered. UI polish does not establish model quality or current source health.

## Madrid cartography and navigation

Madrid uses a full local OpenFreeMap vector basemap, rendered by vendored MapLibre GL JS 5.15.0 through the Leaflet bridge. Real street hierarchy, water, land use and Spanish place labels provide continuous geographic context. The simulator's cached OpenStreetMap graph remains a fine service-area overlay rather than the entire map.

The committed `web/map/manifest.json` records 332 source tiles at zoom levels 10–14 totaling 36,512,766 bytes (36.51 MB), covering longitude/latitude bounds [-3.85, 40.3, -3.52, 40.54]. `web/map/style.json` references local tile and Noto Sans Regular glyph URLs. The two level-10 tiles keep cartography available when fitted MapLibre camera zoom falls below 11 at laptop widths. Higher display zooms overzoom those finite cached tiles. Renderer provenance, licenses and attribution are retained; OpenFreeMap, OpenMapTiles and OpenStreetMap credit stays visible. No live paid map provider is required. Restaurants and Inventory no longer render fixture grid maps. Their backend fixture geometry remains available for repeatable simulations and advanced definitions.

Dragging, mouse-wheel zoom, keyboard movement, touch zoom, double-click zoom and visible zoom buttons are enabled in the initial view. Escape disables wheel zoom so the wheel scrolls the page; the Scroll zoom toggle restores it. Panning has no inertia. Fit network frames the service area, and Locate agent frames valid selection geometry without changing actual route length or coordinates.

The service area remains latitude 40.375–40.455 and longitude -3.73–-3.64. Navigation now uses the wider bounds latitude 40.32–40.52 and longitude -3.83–-3.54, not the superseded 12% padding rule. Minimum zoom adapts to the viewport; maximum display zoom is 17. Locate agent caps its framing zoom at 16.

The current bounded corrections reserve 52px of top clearance for Fit network and 64px for selection framing. Selected-label placement checks visible control geometry and map bounds. On narrow layouts the legend is below the 400px map, in both open and closed states. Resizing invalidates Leaflet dimensions, then resizes and aligns the MapLibre camera before repositioning the selected label. Reduced-motion styles set transition duration to exactly 0s, avoiding a transform transition on map geometry; the generic animation-duration override remains 0.01ms, with the lifecycle animation disabled. This source behavior is recorded separately from the capture/test results; it does not itself establish that every resize frame or touch device has passed.

## Architecture and diagrams

The reader contains 20 chapters and eight D2 diagrams. The sources in `docs/diagrams/` and published counterparts in `web/diagrams/` retain D2 0.9.0, ELK graph layout and native SVG text. The diagrams retain dark graphite surfaces, pale ink, neutral connectors and teal durable-state emphasis. Their hard-coded `common.d2` palette still uses the earlier surface and teal values; it has not been regenerated to match the newer shared cyan tokens exactly. Treat this as retained visual drift, not a second UI theme. Local IBM Plex source fonts live in `docs/diagrams/fonts/` and are embedded in generated SVGs.

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

The second command checks all six HTML pages for stale URLs and missing local assets. This prevents an older cached theme from surviving a new HTML shell without changing API endpoints or simulation definitions.

Inspect idle and populated states across all seven routes at desktop, laptop and mobile widths. Check navigation, active selection, keyboard focus, Escape, reduced motion and local overflow. Exercise a complete selection-to-evidence path, actual identity search, simulation settings, map modes, order filters, source inspection, chapter search and all eight diagrams. Preserve existing seeded outcome and role-isolation checks as the business-behavior baseline.

Current visual evidence is under `docs/media/after/` and `docs/media/correction/`, including populated running/completed Madrid views, the seven-route set, native 1536×1024 captures, selected-agent states and a supplemental 1036px capture derived from the user's crop. That supplemental width is not a claim about the user's browser viewport.

The [fresh full review](media/correction/full-review.md) records the rebuild's material improvements and the bounded map-clearance, resize synchronization, Delivery mobile-toolbar and ledger-density findings. Its screenshots and checks describe recorded states. Map checks cover local rendering/no external requests, actual selected routes, observed history, keyboard pan and Chromium-emulated touch; physical-device touch remains untested. Sampled overflow and solid-background contrast results do not certify map-pixel contrast, full screen-reader behavior or 200% zoom conformance.

## Evidence limits

The original comp-led CLI workflow remains open at plates; downstream phase receipts must not be invented. The current numerical comparison and verdict are recorded in [comparison/report.json](media/correction/comparison/report.json), which remains drift rather than pass. Use that refreshed record instead of a fixed score copied into this document. A new capture or comparison must retain its actual verdict; this reference does not predict or approve the result.

The full review found the rebuilt browser surface materially reviewable and called for bounded fixes, while retaining the workflow acceptance failure. Integration, truthful geography and real runtime data remain binding requirements. Those requirements explain intentional content adaptations, but neither behavior-test totals nor a documentation refresh creates visual acceptance or a fresh user receipt.

The detailed redesign findings, verification results and remaining limitations belong in [UI-REDESIGN.md](UI-REDESIGN.md) and the correction review records. This reference documents the current implementation, including source-level fixes; it does not certify the unfinished comp workflow. Retained D2 palette values, cartographic Noto glyphs and very small page-specific annotations are explicit exceptions. The small annotations are not promoted into a general body-text scale.

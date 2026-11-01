---
version: 1
slug: dark-store
primary_target: web/store-view.js
related_targets: [web/store-3d.js, web/store.css, web/index.html, web/app.js, web/agent-anatomy.js, web/agent-anatomy.css]
---

# Dark store

Mode: Operate. Extend the existing graphite, Plex and cyan operations surface.
The user chose an elevated cutaway with closer order tracking. A store pin or
Open store reveals shelves, pickers, packing and the courier dock together.
This is a local Operations extension, with an adjacent environment selector in
the existing Architecture inspector.

Success: follow a real simulated order from reservation to doorstep; inspect
basket quantities, worker assignment, changed routes and recorded decisions;
trigger store disruptions. Simulation evidence is local and synthetic. The A2A
evidence does not establish live-model quality.

## Direction contract

THESIS: one real basket connects shelves to the Madrid street map.
OWN-WORLD: incumbent graphite panels, Plex text, cyan routes and state colors.
STORY: enter a store, select a basket, see physical progress and inspect recovery.
FIRST VIEWPORT: compact launch controls above the existing map; an elevated
cutaway fills the map pane when opened, with basket evidence alongside it.
FORM: local extension of the existing operations workspace; no new visual world
or concept roll. The user chose elevated cutaway with order tracking.
SIGNATURE: follow the selected basket into the store, then return to the city at
actual courier collection. Reduced motion skips animated map entry and smooth
tracking interpolation.
FINISH: the finish review and scoped verdict are recorded; incumbent DESIGN.md
and the design sidecar are preserved. See the documentation receipt for evidence.
Shipping raster provenance remains a packaging requirement.

## Implemented surface

- Enter through a map pin, Open store, a store order in the ledger, or the seeded
  Start store demo. The cutaway and inspector temporarily replace the map/roster
  workspace; Back to Madrid and Escape restore the city view.
- Order selection, Follow this order, Track picker and Fit store control the view.
  The inspector shows named products, picked/required quantities, fulfillment
  reason, picker ID, current step, store clock, blocked cells and offline robots,
  with a link to recorded agent decisions.
- Following uses actual store state. At the `handed_off` stage it returns to
  Madrid and locates the order; delivered and cancelled stages end following.
  Static delivered captures do not prove the whole transition; the retained
  browser and recording receipts cover that sequence.
- Disruptions are blocked aisle, shelf out of stock, robot breakdown and late
  restock truck. The action is available during a running city session.
- Three.js and local SimReady models load on entry. Missing individual models
  use simple shapes. Graphics failure uses the SVG floor plan while order
  inspection remains available. Its legend identifies worker circles, red
  offline workers and amber unavailable items/areas separately from the 3D key.
- The canvas supports arrow-key orbit and plus/minus zoom, with visible focus.
  Reduced motion removes animated entry and interpolated scene movement. Render
  status, order progress and disruption feedback use status announcements.
- Architecture's Environment selector reuses its labeled field and inspector.
  Dark store shows source-backed facts and a dashed treatment on the existing
  environment part; it does not establish a new diagram style.

## Local visual differences

Global controls and Plex UI typography remain incumbent. Store chrome uses
closely related graphite literals (`#101c23`, `#172832`, `#29404e`) and local
cyan/green/amber signals. These are surface values, not new shared tokens.
Physical model materials distinguish the floor, cold zone, dock, racks and stock.
Rasterized sans-serif scene annotations do not replace the UI font.

The store heading is 16px, inspector/launch headings 14px, working text 12px, and
legend/footer annotations 11px. The 16px heading matches the existing CSS large-text
size but is a local heading role, not an addition to the documented type ramp. The store pin uses
a small legibility shadow (`0 3px 8px #0007`); ordinary panels remain flat.

The wide body pairs a flexible stage with a 250px inspector. Stage minimum height
is `clamp(440px, 50vh, 680px)`. At 850px and below the inspector follows the stage,
whose minimum height becomes 360px. The inspector stays in normal page flow
without a capped height, keeping the disruption action reachable. Headers,
launch controls and footer wrap. These are surface dimensions, not shared tokens.

## Finish evidence

The independent full review identified clipped mobile/laptop disruption controls
and an inaccurate floor-plan legend. One correction batch addressed both. The
same reviewer's verdict was **ship** at the two-fix scope, not a second full audit.
The documenter compared source and all seven final captures with the incumbent
system and preserved DESIGN.md and `.impeccable/design.json`. Evidence and known
metadata drift are in [the documentation receipt](../review/dark-store-documentation.md).

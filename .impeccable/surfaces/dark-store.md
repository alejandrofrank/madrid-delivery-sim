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
basket quantities, worker assignment and movement, changed routes and recorded
decisions; trigger store disruptions. Stock rests on visible rack decks and worker
identity remains inspectable. Simulation evidence is local and synthetic; neither
the A2A evidence nor the shelf-support check establishes live-model quality,
real-world robotics performance or rigid-body physics accuracy.

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
- Order selection, Follow this order, Track worker and Fit store control the view.
  The inspector shows named products, picked/required quantities, fulfillment
  reason, picker ID, current step, store clock, blocked cells and offline robots,
  with a link to recorded agent decisions.
- Following uses actual store state. At the `handed_off` stage it returns to
  Madrid and locates the order; delivered and cancelled stages end following.
  Static delivered captures do not prove the whole transition; the retained
  browser and recording receipts cover that sequence.
- Each stocked shelf face has a representative produce or packaged-goods model
  seated inside the actual rack bounds on a detected deck. Repeated racks, stock
  and shelf markers share instanced rendering. The props represent stocked faces,
  not a one-model-per-unit inventory count; basket quantities remain explicit.
- Workers have visible totes where applicable, ground rings and Plex label
  buttons. Labels expose the actual worker role/number and current task, Idle or
  Offline state. Click or Enter tracks that worker; the Track worker checkbox
  reflects tracking. Basket contents move with the assigned worker. Motion follows
  time-stamped simulation routes, including recovery assignment, not a decorative
  loop or physical telemetry.
- Disruptions are blocked aisle, shelf out of stock, robot breakdown and late
  restock truck. The action is available during a running city session.
- Three.js and local SimReady models load on entry. Missing individual models
  use simple shapes. Graphics failure uses the SVG floor plan while order
  inspection remains available. Its legend identifies worker circles, red
  offline workers and amber unavailable items/areas separately from the 3D key.
- The canvas supports arrow-key orbit and plus/minus zoom, with visible focus.
  Reduced motion removes animated entry and interpolated scene movement while
  simulation state still updates. Render
  status, order progress and disruption feedback use status announcements.
- Architecture's Environment selector reuses its labeled field and inspector.
  Dark store shows source-backed facts and a dashed treatment on the existing
  environment part; it does not establish a new diagram style.

## Local visual differences

Global controls and Plex UI typography remain incumbent. Store chrome uses
closely related graphite literals (`#101c23`, `#172832`, `#29404e`) and local
cyan/green/amber signals. These are surface values, not new shared tokens.
Physical model materials distinguish the floor, cold zone, dock, racks and stock.
Rasterized sans-serif location annotations do not replace the UI font. Worker
labels are real 11px Plex buttons, with cyan working outlines, red offline state,
neutral idle state and a selected background. Labels and rings express identity
and state; they are local scene controls, not a new global component style.

The store heading is 16px, inspector/launch headings 14px, working text 12px, and
legend/footer annotations 11px. The 16px heading matches the existing CSS large-text
size but is a local heading role, not an addition to the documented type ramp.
The store pin uses a small legibility shadow (`0 3px 8px #0007`); ordinary panels remain flat.

The wide body pairs a flexible stage with a 250px inspector. Stage minimum height
is `clamp(440px, 50vh, 680px)`. At 850px and below the inspector follows the stage,
whose minimum height becomes 360px. The inspector stays in normal page flow
without a capped height, keeping the disruption action reachable. Headers,
launch controls and footer wrap. These are surface dimensions, not shared tokens.

Fit store frames the floor envelope, packing area and dock against both camera
projection axes with a margin. Overview fit reapplies on resize, including at the
reviewed 390px width. Manual orbit and worker tracking keep their chosen framing;
Fit store exits tracking and clears the checkbox before restoring the overview.

## Finish evidence

After the user reported unsupported shelf items and asked to see moving agents,
the physical stock placement and worker representation were corrected. A fresh
independent full review compared the original user image, five refreshed store
captures and journey frames 002–010. It found the materials, worker identity and
movement, order journey and incumbent system consistent, with one material issue:
the mobile overview fit. That issue was corrected; the same reviewer returned
**ship** after verifying the complete store, packing area and dock within 390px
margins and preserved wide layouts. The final verdict is one-fix verification,
not another full-surface audit.

The current browser receipt passes movement, 120 supported shelf faces with no
support errors, lazy loading, keyboard, mobile, fallback, handoff and delivery.
The current journey recording is run `5a34f5b8-2ff1-4197-a3f8-43bbd67f9096`.
The documenter rechecked the changed source and five refreshed captures; Anatomy
captures remain unchanged. DESIGN.md and `.impeccable/design.json` are preserved.
See [the documentation receipt](../review/dark-store-documentation.md) for exact
checks, review scope and known metadata drift.

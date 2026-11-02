---
version: 1
slug: agent-anatomy
primary_target: web/agent-anatomy.js
related_targets: [web/agent-anatomy.css, web/agent-anatomy-3d.js, web/documentation.js, web/documentation.html, docs/AGENT-ANATOMY.md]
---

# Agent anatomy
Mode: Experience with source-backed reading on demand. User direction: a Dota-style
character/skin inspection, less text, genuine 3D depth, animation as protagonist.
The existing graphite/Plex/cyan system remains authoritative outside this surface.
No permissions, role facts, model decisions or evidence are authored in the renderer.

## Direction contract
THESIS: Meet one agent as a tangible machine and discover its code through parts,
instead of reading an expanded documentation dashboard.

OWN-WORLD: The established graphite stage and Plex controls recede behind a
beveled, articulated industrial robot with pale alloy, dark joints, cyan selection,
directional studio light and grounded shadows. No new brand, headline or paid assets.

STORY: Choose a role, orbit the machine, select a physical component, read a short
explanation, then open exact manifest facts and sources when wanted. Team handoffs
remain an optional, explicitly illustrative view.

FIRST VIEWPORT: A compact identity/controls row, a large perspective 3D stage occupying
most of the viewport, eleven quiet component hotspots and a compact role strip.
No inspector until selection. Selection focuses the part and reveals a narrow
inspector; mobile keeps the model above it. Chapters and long guide text are collapsed.

FORM: User-pinned character inspection, implemented code-first in the existing
local Three.js runtime; the actual interactive model is the visual asset.
No concept roll: this is the specified replacement of one existing component.
Signature interaction: physical part highlight, camera focus and one short explanation.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

Constraints: all 99 panels retain source-backed facts; native selectors and SVG
fallback preserve access without graphics. Reduced motion removes idle motion and
camera tweening; pause and reset are explicit. Hidden views stop rendering.

## Shipped behavior — 2026-11-02

This local replacement preserves the existing design system. DESIGN.md and
.impeccable/design.json remain authoritative and unchanged. The rendered model's
materials and lighting are local to this experience, not new rules for ordinary
operation panels.

- **Initial view:** a 24px Plex role title (22px on mobile), one short mission and
  the dominant model. Inspector, guide and chapter navigation start closed.
  Eleven physical parts map to eleven source-backed panels for each of nine roles.
- **Inspect:** part clicks, hotspots, the native selector and keyboard activation
  highlight the geometry and focus the camera. Other hotspot dots recede during
  selection. The inspector shows the summary and first two values; **Details &
  source** discloses remaining values, policy, evidence and sources. **Whole
  agent** restores the full model. Closing returns focus to the trigger.
- **Depth:** beveled meshes, pale alloy, dark articulated joints, cyan illumination,
  perspective, a lit floor and cast shadows supply the physical character.
  Controls and evidence panels retain shared flat surfaces and fine rules.
  The machine is explicitly an illustration of code, not live activity.
- **Layout:** stage height is clamped between 360px and 800px around 100svh minus
  310px. Selection adds a 320px inspector, reduced to 280px at 1000px and below.
  At 700px and below, the 420px model stays above the inspector and the role
  strip scrolls horizontally. Focused inspection deliberately crops the whole
  body while keeping the selected component visible. Long evidence scrolls locally.
- **Motion:** idle articulation and slow orbit use a 30fps maximum and pixel ratio
  capped at 1.5. After 45 frames, mean render time above 35ms switches to 15fps
  and pixel ratio 1. **Pause motion** stops idle movement. Reduced motion also
  removes camera tweening and handoff animation. Hidden and offscreen views skip
  rendering; leaving the chapter disposes the scene.
- **Access and recovery:** visible focus, component arrow navigation, Enter/Space
  activation, canvas arrow orbit and plus/minus zoom accompany the native
  selector. Wheel scrolling stays native. WebGL failure or context loss switches
  to the labelled interactive SVG with the same panels. Definition-load failure
  exposes **Retry agent definitions**.
- **Optional reading:** **Team connections** illustrates permitted manifest
  handoffs, with a text equivalent and finite replay. **Read guide** reveals the
  chapter; **Chapters** reveals navigation.

## Finish evidence

FINISH documentation is complete for this surface. The fresh
[finish review](../review/agent-showcase-finish.md) records **SHIP**, with
Persistence, Fidelity, Ceiling, Material fixes and Keep sections and no material
fixes. No QUALITY BAR card or critique comp was supplied, so a separate
reference-card ceiling was not assessed. The precisely specified local request
uses new-work's concept-roll exemption.

The documenter checked the implementation, guide, PRODUCT.md, DESIGN.md and its
sidecar, sampled browser-contract assertions, and inspected the desktop overview,
mobile memory and SVG fallback captures. The review covers overview and selected
memory at 1440×1000, 1280×800, 390×844, 1265×712 and 1916×1244, plus fallback.
All eleven showcase PNGs in ../review have embedded impeccable:prompt origin
metadata. The mobile memory image is a 390×1109 full-page capture from the
390×844 viewport, preserving the stacked inspector.

The build handoff reports browser contracts passing for all 99 panels across
nine roles, 30 targeted Python tests passing, and an observed renderer workload
of 99 draw calls and 67,018 triangles. This documentation pass did not rerun
those checks or a browser; these are build verification results, not new
measurements.

The existing global design documents remain unchanged. Pre-existing provenance
gaps in unrelated review captures, the sidecar's older Bakiano display title,
and PRODUCT.md's older worktree instruction were reported without repair or
promotion into new design rules.

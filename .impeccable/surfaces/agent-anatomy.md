---
version: 1
slug: agent-anatomy
primary_target: web/agent-anatomy.js
related_targets: [web/agent-delivery-scene.js, web/agent-role-symbols.js, web/agent-story.js, web/agent-anatomy.css, web/agent-anatomy-3d.js, web/agent-memory.js, web/documentation.js, web/documentation.html, src/delivery/agent_anatomy.py, src/delivery/anatomy_presentation.py, src/delivery/memory_reference.py, docs/AGENT-ANATOMY.md]
---

# Agent anatomy

Mode: Experience, with complete source-backed reading inside the inspector.
This code-led extension introduces the team to a non-technical hiring manager
with less than a minute, then supports deeper inspection in the same surface.

The whole-robot correction remains binding: preserve the selected viewpoint
and leave every other part clickable. Earlier camera zoom, hidden-hotspot,
compact-only memory and external chapter-redirect directions are superseded.
The previous inspector-first entry and two-primary-values hierarchy are also
superseded by the team journey and generated headline below. Full references
and the memory explorer remain available.

## Direction contract

THESIS: Understand the team as one working delivery place. The user rejected
repeated raster portraits; the shared scene replaces both portrait rows.

OWN-WORLD: Retain the graphite interface, alloy robot, Plex and compact Oxanium.
Role-colored body panels and top beacons encode purpose, with a distinct symbol
and readable name. Selection uses an outline, not a change of role color.

STORY: Follow one illustrated order from stock shelves to packing, dispatch
and doorstep. Recovery review branches off as evidence. All nine roles remain
inspectable; the complete robot and memory explorer remain unchanged.

FIRST VIEWPORT: One elevated cutaway fills the working region. Stock shelves,
packing bench, dispatch dock and a street to a doorstep share a floor and light.
A short current-step explanation and compact role controls accompany it.
Mobile keeps an overview and readable controls, without portrait stacks.

FORM: User-selected procedural shared 3D delivery scene, code-led within the
existing surface. Reuse the robot builder at bounded detail. No new global
visual world or generated comp. seed: none (user-pinned structure; no roll).

FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Team scene contract

- The previous miniature-portrait direction and SHIP are superseded by the
  user's screenshot rejection on 2026-11-02. See the scene rejection review.
- No raster portraits in the team region. All bots occupy one actual WebGL scene.
- Colors, beacon symbols and names distinguish roles, consistently in scene,
  accessible role controls and full-body inspector.
- Finite order playback supports pause/replay and manual reduced-motion steps.
  The parcel remains at the doorstep when evidence passes to the recovery judge.
- The four specialists stay discoverable beside their appropriate stations and
  are not silently inserted into the store-order delivery sequence.
- Provide keyboard access, fallback, focus restoration, suspension and disposal.
- Preserve the remembered four-part tour and all source-backed inspector data.

## Inspection and evidence contract

- Fit the real body bounds with a margin, excluding the floor. Refit after
  resize and orbit. Selecting another part never changes the camera or root
  orientation. Reset view is explicit.
- All eleven hotspots remain available after selection. Native select,
  component arrow keys and Enter/Space provide equivalent access.
- Keep the stage/inspector grid constant across parts, tabs and references.
  The reader is 42% with a 340px minimum on desktop, 44% at 1000px and below,
  and stacked at 700px and below. The mobile stage is 420px. Desktop reading
  scrolls inside the inspector; mobile uses page flow.
- The physical part leads at 24px Oxanium, then the plain label at 13px Plex
  and technical term at 12px. The summary is 16px/1.55. Each component has one
  generated headline, a real value at 23px Plex Mono, its unit and short bullets.
  Technical numbers stay under Details & source. Memory adds its full explorer
  after the headline.
- All 99 panels offer Full reference · read here. Chapters, section navigation
  and related links remain inside the inspector; Back to component reference
  returns to the selected part's chapter. Source dialogs preserve that context.
- API-generated manifests, SOUL, cards and recorded evidence remain authoritative.
  The presentation builder supplies plain/technical labels, number rows,
  headlines and story text. Plain language never adds capabilities.
- Results use readable group names, cases/attempts, percentages, intervals,
  USD cost and p95 time, with definitions and historical/offline qualifiers.
  Unmeasured cost stays unmeasured. Roles without a separate held-out score say
  so. Generated Agent Cards use labeled key/value fields.
- The cab badge uses the real role name. Arm symbols represent up to four
  generated tool entries. Five gauge bars compare default model spending caps
  in USD per run across templates; a zero cap is not an exhausted balance.
  The inspector names unit/scope and separate optional-profile limits.
- Preserve bounded rendering, adaptive frame rate, pause, reduced motion,
  offscreen suspension, disposal, SVG fallback and retry. The shared scene reuses the same
  robot geometry at bounded detail. No live telemetry, fabricated scores or currency conversion.
- Oxanium stays self-hosted under SIL OFL 1.1. No external font requests,
  glowing type or global restyling.

## Memory documentation contract

- Record opens on a synthetic PostgreSQL row with JSONB body. Scope,
  Observation and History expose real field groups; Observation starts selected.
  Schema/complete-record disclosures and observation-type selection remain.
- Core view projects the same record through none, text, json, typed and semantic
  using the real Python function. The one-record semantic example demonstrates
  output shape, not retrieval quality. Recall exposes the scope gate and SQL
  recheck before agent input.
- Local / GCP separates canonical SQL facts from optional vector ranking.
  Prerequisites, idle cost, retention and trust limits stay explicit; Terraform
  capability is not live deployment evidence.
- Constraints separates explicit-profile recall defaults/bounds from role
  storage/tool limits. Preserve legacy recall, whole-fact omission, expiry
  without deletion, audit history, fail-closed checks and trusted-host caveats.
- Customer-service classification has a fresh session per complaint and
  idempotency receipts, with no persistent recall or memory tools. Its disclosure
  explains the shared system without implying classifier access.
- Tabs support Left/Right and Home/End with selected state and a labelled panel.
  Code/tables retain local overflow and narrow controls retain accessible targets.
  This reference reads no private memory, makes no model calls or provisioning
  changes, and changes no run when a preview format is selected.

## Verification and finish

Historical reviewer disposition: **SHIP**, 2026-11-02, for the rejected portrait version.
The user rejection supersedes that disposition; the replacement awaits full review.
The independent fresh-context reviewer inspected 38 captures and sampled source;
persistence, fidelity, ceiling and keep passed, with no material fixes.
See [current finish review](../review/anatomy-tour-finish-review.md) and
[documentation record](../review/anatomy-tour-documentation.md).
This is not CI or full-suite certification.

The [browser receipt](../review/anatomy-checks.json), recorded at
2026-11-02T19:28:55.467Z, covers 9 roles and 99 panels; team story; generated
labels, headlines and badges; first-visit/remembered tour; full-body framing;
sequential selection and orbit preservation; progressive details; keyboard;
source dialog and Agent Card; finite animation; reduced motion; retry;
context-loss fallback; disposal; and no horizontal page overflow. Its sampled
render records 115 calls and 67,038 triangles.

The 36 required captures comprise six story views; overview, protocols and memory
inspection at each of six sizes; four memory tabs on desktop/mobile; two tour
views; budget; and SVG fallback. Viewports: 1440×1000, 1280×800, 390×844,
1265×712, 1916×1244 and 1463×753. results-desktop.png and card-desktop.png are
two supplemental viewport shots of scrolled inspector evidence. All 38 files
carry embedded origin metadata; full-page heights can exceed viewport heights.

The root agent reports 22 focused anatomy/presentation tests, the documentation
catalogue (27 chapters, 164 sources) and asset-version check passing. The
documenter ran no runtime tests or browser checks.

The [current detector](../review/anatomy-tour-detector.json) has three advisories.
The reviewer accepted the tiny order-marker radius and local story-heading size;
saved captures contradicted the black-text advisory. These are not new global
tokens. No QUALITY BAR card or approved comparison composition was supplied.
The baseline is the established surface, shared system and source contracts.
Earlier [memory](../review/memory-finish.md) and
[inspection](../review/agent-inspection-finish.md) records remain historical.

DESIGN.md and .impeccable/design.json remain unchanged. Their older two-primary-
values prose does not specify this surface's new single-headline hierarchy or
its earlier memory exception. Oxanium journey headings are local adaptations,
not shared title changes. The sidecar's older Bakiano title/date and PRODUCT.md's
older worktree metadata remain reported drift, not unrequested repairs.

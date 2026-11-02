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
finish review, verdict, this surface contract and its documentation record,
with every shipping raster carrying provenance. Preserve the existing global
DESIGN.md and sidecar: the purpose identities are local to this component.

## Team scene contract

- The previous miniature-portrait direction and SHIP are superseded by the
  user's screenshot rejection on 2026-11-02. See the scene rejection review.
- No raster portraits in the team region. All bots occupy one actual WebGL scene.
- Colors, beacon symbols and names distinguish roles, consistently in scene,
  accessible role controls and full-body inspector. The generated `ROLE_VISUALS`
  mapping is authoritative; selection must not recolor a role. The shared symbol
  set supplies the controls, top lights and inspector identity. See the
  [local palette and source comparison](../review/delivery-scene-documentation.md#palette-and-identity).
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

The replacement shared scene received **SHIP** in the fresh-context
[FULL finish review](../review/delivery-scene-finish-review.md) on 2026-11-02.
The reviewer opened all 47 captures in that packet, sampled source and passed
persistence, fidelity, ceiling and keep, with no material fixes. This replaces
the rejected portrait version's earlier disposition. The local
[documentation record](../review/delivery-scene-documentation.md) records the
palette, typography, layout, rules and current capture inventory.

The final narrow caption addendum also gives **SHIP**. Generated handoffs read
`sender → recipient: handoff`, with a terminal “to” or “for” removed only for
display. The reviewer reopened the four refreshed order-stage captures and scene
fallback and found the single copy finding resolved; dispatch was checked in
source because no separate dispatch capture was supplied. Generated data is
unchanged, and the whole-surface visual decision remains separate.
Full CI is running and is **not yet certified** by this record.

The [browser receipt](../review/anatomy-checks.json), recorded at
2026-11-02T22:33:41.288Z, covers 9 roles and 99 panels; one shared delivery scene;
stable role identities; parcel retention at the doorstep during review; team
and inspector context-loss fallbacks; generated labels, headlines and badges;
first-visit/remembered tour; full-body framing; sequential selection and orbit
preservation; progressive details; keyboard; source dialog and Agent Card;
finite animation; reduced motion; retry; disposal; and no horizontal page
overflow. Its sampled shared scene records **516 calls / 82,372 triangles**;
the full inspector records **123 calls / 67,042 triangles**. These are bounded
sampled render counts, not device-independent frame-rate measurements.

The seven viewport sizes are **1440×1000, 1280×800, 390×844, 1265×712,
1916×1244, 1463×753 and 1801×839**. The 47 current captures comprise seven
story views; overview, protocols and memory inspection at each of seven sizes;
eight desktop/mobile memory-tab views; two tours; budget; two fallbacks;
results; Agent Card; and four order stages. Results and Agent Card are declared
scrolled viewport captures; the other full-page captures start at the document
top and can exceed the viewport height. All 47 PNGs and the
[README image](../../docs/media/agent-anatomy.png) carry embedded
`impeccable:prompt` origin metadata. The complete inventory and representative
links are in the documentation record.

The root agent reports **23 focused Python tests, Ruff, Mypy, documentation
catalogue and asset-version checks passing**, together with browser coverage
of 9 roles / 99 panels. The documenter read source, receipts and image metadata
and sampled existing captures; it ran no runtime tests, server or browser.

The [current detector](../review/delivery-scene-detector.json) is `[]` from one
finish run. Earlier detector advisories and the portrait review belong to the
superseded implementation. No QUALITY BAR card or approved comparison comp was
supplied; the baseline is the user-pinned shared scene, established surface,
shared system and source contracts. The
[portrait rejection](../review/scene-rejection-review.md),
[previous tour finish](../review/anatomy-tour-finish-review.md),
[memory finish](../review/memory-finish.md) and
[inspection finish](../review/agent-inspection-finish.md) remain historical.

DESIGN.md and .impeccable/design.json remain unchanged. Their older two-primary-
values prose does not specify this surface's single generated headline or its
memory exception. The generated purpose colors and symbols are a local semantic
identity extension, and compact Oxanium journey headings are a local adaptation.
Neither changes the shared typography or global accent. The sidecar's older
Bakiano title/date and PRODUCT.md's older worktree metadata remain reported
drift, not unrequested repairs.

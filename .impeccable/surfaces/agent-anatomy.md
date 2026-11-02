---
version: 1
slug: agent-anatomy
primary_target: web/agent-anatomy.js
related_targets: [web/agent-story.js, web/agent-anatomy.css, web/agent-anatomy-3d.js, web/agent-memory.js, web/documentation.js, web/documentation.html, src/delivery/agent_anatomy.py, src/delivery/anatomy_presentation.py, src/delivery/memory_reference.py, docs/AGENT-ANATOMY.md]
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

THESIS: Understand one order through team handoffs, then discover each agent's
real configuration and evidence through its physical parts.

OWN-WORLD: Keep the graphite stage, dimensional pale-alloy robot, dark joints,
cyan selection, compact Oxanium headings, Plex Sans explanation and controls,
and Plex Mono evidence. Shared tokens stay intact.

STORY: Follow six steps from demo order through stock check, pick and pack,
courier dispatch, delivery and judge review. Inspect any of nine roles;
Back to team restores the journey. A remembered, skippable four-step tour
introduces the job, tools, guardrails and recorded tests.

FIRST VIEWPORT: A compact title and working journey lead. Five robot miniatures
follow the demo-input bag; four related specialists sit below the handoff legend
and illustration note. Desktop runs horizontally; mobile runs vertically.
Opening a robot restores the full-body model and reserved reading column.

FORM: The existing procedural Three.js machine supplies the inspection model
and miniature portraits. Plain handoffs, generated headlines and in-place source
reading carry the interaction. Memory retains its annotated synthetic record
and four tabs. No new visual world or comparison composition was requested.

FINISH: Unreviewed and undocumented is unfinished. This extension ends with
the finish review, verdict, current surface documentation and provenance in
every shipping raster. Existing DESIGN.md and its sidecar are preserved.

## Team journey and tour

- The default URL without an agent or part opens the team. Existing agent/part
  deep links open the inspector. A miniature opens that role's mission;
  Back to team returns focus to its miniature.
- Inventory, fulfillment, dispatcher, courier and recovery judge form the store
  route. Household, restaurant, market and customer service remain inspectable
  specialists. The demo creates the order; household represents meal customers.
  The judge reviews recovery evidence, not every successful delivery.
- Solid, dashed and dotted paths mean queued handoffs, controller-routed A2A
  requests and review evidence. Text and a visible legend explain them.
  The journey is explicitly illustrative, not live activity.
- Play order runs one finite journey with pause/replay. Reduced motion uses
  manual Next step. Playback stops when hidden, offscreen or an agent opens.
- The four-step first-visit tour supports Next, Pause/Resume and Skip. Completion
  or dismissal is remembered locally; Replay tour remains available. Reduced
  motion uses manual steps. Selecting a part stops the tour; completion or Skip
  returns to the team.
- View options groups Reset view, Pause motion, Read guide and Chapters.
  Preserve the exact footer: "Built from the agents' real configuration files
  and test results."

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
  offscreen suspension, disposal, SVG fallback and retry. Miniatures reuse the
  existing renderer. No live telemetry, fabricated scores or currency conversion.
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

Current reviewer disposition: **SHIP**, 2026-11-02, for this story/tour extension.
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

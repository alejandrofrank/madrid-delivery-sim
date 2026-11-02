# Shared delivery scene documentation

Recorded 2026-11-02 for the user-pinned rebuild of Agent Anatomy. This record
updates the [surface contract](../surfaces/agent-anatomy.md) and documents the
implemented local extension. Global [DESIGN.md](../../DESIGN.md) and
[design.json](../design.json) are preserved. The established graphite console
remains the visual authority; no new global world or design tokens are proposed.

The [FULL finish review](delivery-scene-finish-review.md) gives **SHIP** to the
replacement shared-scene packet after inspecting all 47 captures and sampling
source. It reports no material fixes. The final caption-only addendum also gives
**SHIP**: five refreshed supplemental captures resolve the dangling-preposition
finding. Captions now read `sender → recipient: generated handoff`, with only
a terminal “to” or “for” removed for display. Generated handoff data is unchanged.
Dispatch was confirmed in source because no separate dispatch capture was
supplied. Full CI is still running; this is design documentation, not full-suite
certification.

## Sources and observation scope

Read PRODUCT.md, DESIGN.md, the design sidecar, the surface direction contract,
the finish review, [browser receipt](anatomy-checks.json), and these artifacts:

- [Team story and caption controls](../../web/agent-story.js).
- [Shared delivery scene](../../web/agent-delivery-scene.js).
- [Role symbol set](../../web/agent-role-symbols.js).
- [Robot builder and inspector](../../web/agent-anatomy-3d.js).
- [Anatomy styles](../../web/agent-anatomy.css) and [shared tokens](../../web/tokens.css).
- [Generated presentation contract](../../src/delivery/anatomy_presentation.py).
- [Published anatomy guide](../../docs/AGENT-ANATOMY.md).

The documenter opened existing desktop story, mobile story, desktop protocol
inspector and mobile memory-record captures. It also read PNG metadata for all
47 current captures and the README image. It ran no server, browser or runtime
tests. The Impeccable context helper was rejected by automatic approval review
because it could write outside the two-file documentation boundary; existing
project context was read directly instead.

## Palette and identity

Shared source tokens and DESIGN.md agree: blue graphite ground `#0c151c`,
surface `#0f1b23`, pale ink `#e5eef5`, muted ink `#a8bdcd`, fine rule `#263a48`,
strong rule `#476271` and cyan action/selection `#23d8ce`. The scene renderer
uses the same `#0c151c` clear color. The finish reviewer sampled the desktop
story ground at (20,200) and (20,750): RGB (12,21,28), matching that token.
The opened desktop/mobile evidence preserves this ground and fine-rule
containment. The cutaway's floor, shelves, road and cargo are physical scene
materials; they do not replace the page palette.

The presentation builder generates nine stable purpose identities. Six reuse
existing palette values, while kitchen, supply and support add local role hues.
The distinct symbols and readable names carry the identity alongside color.

| Role | Color | Symbol key | Scene label |
|---|---|---|---|
| Inventory | `#75d2a8` | `stock` | Stock |
| Fulfillment | `#e9bc71` | `pick` | Pick |
| Dispatcher | `#8db9e3` | `dispatch` | Route |
| Courier | `#23d8ce` | `deliver` | Deliver |
| Recovery judge | `#e5eef5` | `review` | Review |
| Household | `#f28e8e` | `home` | Customer |
| Restaurant | `#db9669` | `kitchen` | Kitchen |
| Market | `#bdcf7c` | `supply` | Supply |
| Customer service | `#b9a5dd` | `support` | Support |

The shared symbol module supplies one authored SVG path set to controls and
painted beacon textures. Robot decoration applies the same generated color to
purpose panels and top lights in the bounded-detail scene and full inspector.
The white owner ring and label outline identify the active actor independently;
selecting a role does not change its purpose color. This is semantic role
identity within Anatomy, not a second global accent scheme.

## Typography and layout

The compact 24px/600 Oxanium title and physical-part headings match the existing
Anatomy exception in DESIGN.md. IBM Plex Sans remains the explanation/control
family, IBM Plex Mono the evidence family. Fonts are served locally. The summary
stays 16px/1.55; subtitles and controls are generally 12–13px. The generated
headline value is 23px/1.2 Plex Mono, with its unit and short plain-language
bullets. The older shared two-value description does not supersede this local
single-headline hierarchy. No display headline or decorative type tier was added.

The team view uses one WebGL floor, camera and lighting system. Shelves, packing
bench, conveyor, dispatch dock, road and doorstep share perspective; nine robots
occupy their stations. The scene is `clamp(390px,60svh,700px)` high on desktop.
Six direct steps and a current-step explanation lead into nine named role
controls. The compact mobile scene is a 360px overview; steps form three columns
and two rows, role controls form two columns, and controls retain 44px targets.
Secondary floating labels are hidden on narrow screens while the owner/hover
label remains. This follows the mobile overview contract.

The separate complete-body inspector keeps its 42% reader with a 340px desktop
minimum, changing to 44% at 1000px and below and stacking at 700px and below.
The mobile robot stage remains 420px. Desktop evidence scrolls within the
reader; mobile evidence uses page flow. Fine rules, restrained 5px control
corners and the established spacing rhythm continue throughout. Physical
shadows belong to the WebGL scene; the surrounding working interface remains
flat. The source and opened protocol/memory captures agree on these patterns.

## Rules retained by this rebuild

- Keep one shared delivery setting in the team region; do not restore repeated
  raster portraits or manufacture a new global visual style.
- Preserve role colors, symbols and names across scene, named controls and full
  inspector. Selection is a separate outline/state, never a recolored role.
- Present an illustrated order, not live telemetry. The dark-store demo input
  starts the order; the household role remains the meal customer specialist.
- Move the physical parcel to the doorstep and leave it there during recovery
  review. Use the separate dotted evidence branch for the judge. Kitchen,
  supply, customer and support remain inspectable without invented store-order
  stages or capabilities.
- Preserve finite play/pause/replay, manual reduced-motion steps, keyboard access,
  focus restoration, hidden/offscreen suspension and disposal. The scene uses
  the bounded-detail robot builder, a 30fps cap and a 1.3 pixel-ratio cap; these
  limits are implementation bounds, not measured universal performance claims.
- Preserve all eleven clickable parts, chosen camera view, 99 generated panels,
  complete in-place references, memory explorer and remembered four-part tour.
  The team floor-plan fallback and inspector SVG fallback retain named access.
- Keep source facts authoritative, USD budget scope explicit, unmeasured values
  unmeasured and recorded/offline evidence qualified. Do not introduce heroes,
  gradient headings, glowing type or ornamental surfaces.

## Verification and capture inventory

The [browser receipt](anatomy-checks.json) is dated
`2026-11-02T22:33:41.288Z`. It records **9 roles / 99 panels**, shared scene and
role identity, parcel retention, both context-loss fallbacks, WebGL, story,
generated labels/headlines/badges, remembered tour, whole-body framing,
selection/orbit preservation, progressive details, keyboard, source dialog,
Agent Card, finite animation, reduced motion, retry, disposal and no horizontal
page overflow. Sampled render counts are **516 calls / 82,372 triangles** for
the shared scene and **123 calls / 67,042 triangles** for the full inspector.

| Receipt name | Viewport | Representative evidence |
|---|---|---|
| desktop | 1440×1000 | [Story](story-desktop.png), [protocol inspector](inspection-desktop-protocols.png) |
| laptop | 1280×800 | [Story](story-laptop.png), [inspector](inspection-laptop.png) |
| mobile | 390×844 | [Story](story-mobile.png), [memory record](memory-mobile-record.png) |
| user-1265 | 1265×712 | [Story](story-user-1265.png), [inspector](inspection-user-1265.png) |
| user-1916 | 1916×1244 | [Story](story-user-1916.png), [inspector](inspection-user-1916.png) |
| user-1463 | 1463×753 | [Story](story-user-1463.png), [inspector](inspection-user-1463.png) |
| user-1801 | 1801×839 | [Story](story-user-1801.png), [inspector](inspection-user-1801.png) |

The 47 current PNGs are:

| Group | Count | Files |
|---|---:|---|
| Story | 7 | `story-desktop.png`, `story-laptop.png`, `story-mobile.png`, `story-user-1265.png`, `story-user-1916.png`, `story-user-1463.png`, `story-user-1801.png` |
| Whole-body overview | 7 | `inspection-desktop.png`, `inspection-laptop.png`, `inspection-mobile.png`, `inspection-user-1265.png`, `inspection-user-1916.png`, `inspection-user-1463.png`, `inspection-user-1801.png` |
| Protocol inspector | 7 | `inspection-desktop-protocols.png`, `inspection-laptop-protocols.png`, `inspection-mobile-protocols.png`, `inspection-user-1265-protocols.png`, `inspection-user-1916-protocols.png`, `inspection-user-1463-protocols.png`, `inspection-user-1801-protocols.png` |
| Memory inspector | 7 | `inspection-desktop-memory.png`, `inspection-laptop-memory.png`, `inspection-mobile-memory.png`, `inspection-user-1265-memory.png`, `inspection-user-1916-memory.png`, `inspection-user-1463-memory.png`, `inspection-user-1801-memory.png` |
| Memory tabs | 8 | `memory-desktop-record.png`, `memory-desktop-core-view.png`, `memory-desktop-local-gcp.png`, `memory-desktop-constraints.png`, `memory-mobile-record.png`, `memory-mobile-core-view.png`, `memory-mobile-local-gcp.png`, `memory-mobile-constraints.png` |
| Tour | 2 | `tour-desktop.png`, `tour-mobile.png` |
| Budget | 1 | `budget-desktop.png` |
| Fallbacks | 2 | `inspection-fallback.png`, `scene-fallback.png` |
| Scrolled evidence | 2 | `results-desktop.png`, `card-desktop.png` |
| Order stages | 4 | `scene-start.png`, `scene-stock-check.png`, `scene-pick-pack.png`, `scene-delivery.png` |

All 47 PNGs carry embedded `impeccable:prompt` metadata describing the local
Playwright origin, date and procedural scene. The
[README image](../../docs/media/agent-anatomy.png), also 1440×1040, carries that
origin field too. It is an additional distribution image, not a 48th browser
check capture. Refreshed order-stage/fallback/README metadata explicitly notes
the sender-to-recipient caption correction. The final caption addendum approved
the four order-stage captures plus the scene fallback after removing only the
terminal preposition for display; it confirmed the analogous dispatch wording
in source. This narrow addendum is separate from the whole-surface review.

Full-page screenshots begin at the document top and may exceed their viewport
height. Results and Agent Card are intentionally scrolled 1440×1000 viewport
captures. The separately named desktop memory-tab captures are 1463px wide;
"desktop" there denotes the memory comparison set, not the 1440px receipt row.
Older PNGs elsewhere in this folder are not included in the current count.

The [detector receipt](delivery-scene-detector.json) contains `[]` from one
finish run. The root reports 23 focused Python tests, Ruff, Mypy, documentation
catalogue and asset-version checks passing, alongside the browser receipt.
Full CI remains running and uncertified in this document. No approved comp or
standalone QUALITY BAR card was supplied. The chosen scene direction and the
incumbent system are the comparison authority.

## Existing drift and historical records

No global metadata drift was repaired. DESIGN.md and the sidecar still describe
two primary evidence values, while this surface now uses a single generated
headline and retains the deeper memory exception. The sidecar still has the
title `Design System: Bakiano operations` and generated date
`2026-10-29T18:31:11.522371+00:00`. PRODUCT.md retains the older `mds-ui` /
`feat/ui-redesign` worktree restriction. These pre-existing records do not grant
permission for unrelated edits or override the user-pinned local scene.

The [portrait rejection](scene-rejection-review.md),
[previous tour review](anatomy-tour-finish-review.md),
[previous documentation](anatomy-tour-documentation.md),
[memory review](memory-finish.md) and
[whole-body inspection review](agent-inspection-finish.md) remain historical.
Their earlier capture counts and detector advisories are not current evidence.

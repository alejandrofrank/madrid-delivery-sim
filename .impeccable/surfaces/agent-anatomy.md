---
version: 1
slug: agent-anatomy
primary_target: web/agent-anatomy.js
related_targets: [web/agent-anatomy.css, web/agent-anatomy-3d.js, web/documentation.js, web/documentation.html, docs/AGENT-ANATOMY.md]
---

# Agent anatomy

Mode: Experience with source-backed reading on demand. This local correction
implements the user's later preference: keep the whole robot visible, keep
other parts clickable, and make the text fit the futuristic machine.
It supersedes the earlier camera-zoom and hidden-hotspot direction.

## Direction contract

THESIS: Meet one agent as a tangible machine and discover its code through parts.

OWN-WORLD: A beveled industrial robot, pale alloy, dark joints, grounded shadows
and cyan selection on the established graphite stage. Local Oxanium SemiBold
role and physical-part headings match its geometric form. IBM Plex Sans prose
and controls, and Plex Mono evidence, retain the shared interface language.
The Anatomy-only roles in DESIGN.md record this narrow exception; shared
title and body roles remain unchanged.

STORY: Choose a role, orbit the machine, select a part, then inspect its evidence.
Selection preserves the view. All eleven controls remain available in sequence.

FIRST VIEWPORT: Compact identity and controls, a large full-body model, eleven
quiet hotspots and a compact role strip. A reserved inspector column prevents
layout jumps; before selection it contains only a short instruction.
The model remains above selected details on mobile.

FORM: The existing procedural Three.js model is the visual asset. Part highlight
and one compact explanation are the signature interaction. No concept roll is
needed for this precisely specified local correction.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Implementation contract

- Fit the robot's real body bounds to the available viewport with a margin.
  Exclude the floor. Refit after resize and orbit, including while selected.
  Selection never changes the camera or root orientation. Reset view is explicit.
- Keep all eleven hotspots visible and pointer-accessible after selection.
  Native select, component arrow keys and Enter/Space retain equivalent access.
- A constant desktop stage/340px inspector grid (280px below 1000px) prevents
  stage resizing on selection. At 700px and below use a stacked 420px stage.
- The selected physical part leads at 24px Oxanium; the code topic sits below
  at 13px Plex. The summary is 16px/1.55. Two source values use 16px Plex Mono.
  Remaining facts, caveats, Agent Cards and source links stay behind disclosure.
- All 99 panels remain API-generated from real manifests, SOUL, cards and
  recorded evidence. Plain-language summaries never grant new capabilities.
- Preserve the existing renderer budget, reduced motion, pause, offscreen
  suspension, scene disposal, SVG fallback, retry and optional team/guide views.
- The 28,892-byte Oxanium font is self-hosted under SIL OFL 1.1. No external
  font requests, glowing type, simulated telemetry or global restyling.

## Verification and finish

Reviewer disposition: **SHIP**, 2026-11-02. The independent finish reviewer
inspected all nineteen current inspection captures and marked all five original
material fixes resolved, with no new regression. The prior showcase verdict is
historical: its focused cropping and hidden-hotspot behavior are superseded.
See [the correction finish record](../review/agent-inspection-finish.md).

Verified overview, antenna and memory captures cover 1440x1000, 1280x800,
390x844, 1265x712, 1916x1244 and the supplied 1463x753 viewport; the nineteenth
capture covers SVG fallback. All nineteen and the README image carry embedded
screenshot-origin metadata.

[The browser receipt](../review/anatomy-checks.json) records source parity for 99 panels, sequential
direct clicks on all eleven parts, full-body framing, preserved orbit, keyboard
access, progressive details, source dialogs, Agent Cards, bounded animation,
reduced motion, retry, context-loss fallback, disposal and no page overflow.
The browser script also checks safe fitting after orbit, resize and zoom.
Thirty targeted Python tests passed. The full-suite result is maintained by the
implementation verification rather than inferred from this design review.
The final post-documentation typography scan has zero findings. DESIGN.md and
its sidecar record only the verified Anatomy-specific type roles and rule.

No QUALITY BAR card or approved comparison composition was supplied. The
precisely specified local-correction exemption applies; the implemented contract,
source-backed facts and current captures provide the review baseline.

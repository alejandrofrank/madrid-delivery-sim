---
version: 1
slug: agent-anatomy
primary_target: web/agent-anatomy.js
related_targets: [web/agent-anatomy.css, web/agent-anatomy-3d.js, web/agent-memory.js, web/documentation.js, web/documentation.html, src/delivery/memory_reference.py, docs/AGENT-ANATOMY.md]
---

# Agent anatomy

Mode: Experience with a complete source-backed reference in place. The current
extension makes Anatomy itself the agent documentation. The earlier user
correction remains binding: keep the whole robot visible, preserve the selected
viewpoint and leave every other part clickable. Earlier camera zoom,
hidden-hotspot, compact-only memory and external chapter-redirect directions
are superseded.

## Direction contract

THESIS: Meet one agent as a tangible machine and discover its code through parts.
Read the complete component reference beside that same machine.

OWN-WORLD: A beveled industrial robot, pale alloy, dark joints, grounded shadows
and cyan selection on the established graphite stage. Local Oxanium SemiBold
role and physical-part headings match its geometric form. IBM Plex Sans prose
and controls, and Plex Mono evidence, retain the shared interface language.
The Anatomy-only roles in DESIGN.md record this narrow exception; shared
title and body roles remain unchanged.

STORY: Choose a role, orbit the machine, select a part, then inspect its evidence
and full reference without leaving Anatomy. Memory reveals the record, the
core's input, storage paths and constraints. Selection preserves the view;
all eleven controls remain available in sequence.

FIRST VIEWPORT: Compact identity and controls, a large full-body model, eleven
quiet hotspots and a compact role strip. A reserved reading column prevents
layout jumps; before selection it contains only a short instruction.
The model remains above selected details on mobile.

FORM: The existing procedural Three.js model is the visual asset. Part highlight,
a readable explanation and in-place source-backed reading are the signature
interaction. Memory uses an annotated synthetic record and four tabs. This is
an ordinary extension of the established world, not a new visual direction.

FINISH: Unreviewed and undocumented is unfinished. This extension ends with the
finish review, verdict, current surface documentation and provenance in every
shipping raster. The existing DESIGN.md and its sidecar are preserved.

## Implementation contract

- Fit the robot's real body bounds to the available viewport with a margin.
  Exclude the floor. Refit after resize and orbit, including while selected.
  Selection never changes the camera or root orientation. Reset view is explicit.
- Keep all eleven hotspots visible and pointer-accessible after selection.
  Native select, component arrow keys and Enter/Space retain equivalent access.
- Keep the stage/inspector grid constant across parts, tabs and open references.
  The reading column is 42% with a 340px minimum on desktop, 44% at widths of
  1000px and below, and stacked at 700px and below. The mobile stage is 420px.
  Desktop reading scrolls within the inspector; mobile reading uses page flow.
- The selected physical part leads at 24px Oxanium; the code topic sits below
  at 13px Plex. The summary is 16px/1.55. Non-memory panels retain two primary
  16px Plex Mono values. Memory replaces that pair with its visual reference.
  Details & source retains policy, further evidence, Agent Cards and source links.
- Every one of the 99 panels offers Full reference · read here. Full chapters,
  section navigation and related chapter links stay inside the inspector;
  Back to component reference returns to the selected part's chapter. Source
  dialogs preserve that reading context.
- All 99 panels remain API-generated from real manifests, SOUL, cards and
  recorded evidence. Plain-language summaries never grant new capabilities.
- Preserve the existing renderer budget, reduced motion, pause, offscreen
  suspension, scene disposal, SVG fallback, retry and optional team/guide views.
- The 28,892-byte Oxanium font is self-hosted under SIL OFL 1.1. No external
  font requests, glowing type, simulated telemetry or global restyling.

## Memory documentation contract

- Record opens on a synthetic PostgreSQL row with JSONB body. Scope,
  Observation and History expose the real field groups; Observation is selected
  first. Accepted schemas and complete records are available by disclosure.
  Roles with multiple observation contracts expose an observation-type selector.
- Core view shows the same record through none, text, json, typed and semantic
  projections, generated with the real Python projection function. The semantic
  one-record example demonstrates output shape, not measured retrieval quality.
  The recall path exposes the scope gate and SQL recheck before agent input.
- Local / GCP distinguishes canonical SQL facts from optional vector rankings.
  Storage flows, deployment prerequisites, idle cost, retention and trust limits
  remain explicit. Terraform capability is not live deployment evidence.
- Constraints separates explicit-profile recall defaults/bounds from per-role
  storage/tool limits. It explains legacy recall, whole-fact omission, expiry
  without deletion, retained audit history, fail-closed checks and trusted hosts.
- The customer-service classifier has its own nonpersistent view: a fresh session
  per complaint and idempotency receipts, with no persistent recall or memory
  tools. Its disclosure explains the shared system without implying access to it.
- Tabs support Left/Right and Home/End with selected state and a labelled panel.
  Code and tables retain bounded local overflow; narrow selectors and disclosure
  targets retain the existing mobile accessibility treatment.
- Shared tokens and Anatomy typography remain unchanged. This reference reads
  no private memory and performs no model calls, cloud provisioning or runtime
  permission changes. Previewing a format changes no run.

## Verification and finish

Current reviewer disposition: **SHIP**, 2026-11-02, for the visual and functional
documentation extension. Persistence, fidelity, ceiling, material fixes and keep
all passed; no material fix remained. See [the memory finish record](../review/memory-finish.md).
This is not a CI or full-suite certification. The earlier
[inspection correction record](../review/agent-inspection-finish.md) remains
historical evidence for the whole-robot correction, not the current layout spec.

The current [browser receipt](../review/anatomy-checks.json), recorded at
2026-11-02T17:39:11.830Z, covers the 9 agents, 99 panels and retained scene
contracts. The browser verification also exercises all 99 inline readers,
all five projections, record fields, local/cloud paths, keyboard tabs, the
classifier exception, source dialogs and in-place related chapters.
Implementation verification reports 40 focused Python tests, Ruff and mypy over
95 source files passing. No new runtime tests were run by the documenter.

Nineteen inspection captures cover overview, antenna and memory at 1440x1000,
1280x800, 390x844, 1265x712, 1916x1244 and 1463x753, plus SVG fallback. Eight
memory captures show each tab at 1463x753 and 390x844. All 27 current captures
carry embedded screenshot-origin metadata; full-page image heights can exceed
the browser viewport. The current detector artifact,
artifacts/memory-design-findings.json, is an empty findings array.

No QUALITY BAR card or approved comparison composition was supplied. The
comparison baseline is the established Anatomy surface, shared design system,
source contracts and the user's complete-reference request. This ordinary
extension preserves the incumbent palette, type families, flat surfaces and
whole-robot interaction; its wider reader and memory views are local behaviors.

DESIGN.md and .impeccable/design.json are unchanged. Their two-primary-values
wording still describes non-memory components but does not cover the memory
exception. The sidecar's older Bakiano title/date and PRODUCT.md's older worktree
metadata remain reported drift, not new rules or unrequested repairs.

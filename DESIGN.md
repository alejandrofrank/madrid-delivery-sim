---
name: madrid-delivery-sim
description: A calm, dense console for inspectable delivery-agent operations.
colors:
  accent: '#23d8ce'
  accent-ink: '#052a2c'
  accent-soft: '#103238'
  accent-hover: '#90e4d8'
  bg: '#0c151c'
  surface: '#0f1b23'
  raised: '#162630'
  hover: '#1c303b'
  ink: '#e5eef5'
  muted: '#a8bdcd'
  faint: '#8ba3b5'
  line: '#263a48'
  strong-line: '#476271'
  positive: '#75d2a8'
  negative: '#f28e8e'
  warning: '#e9bc71'
  info: '#8db9e3'
  map-ground: '#14212e'
  map-chrome: '#0c1822'
  map-rule: '#314957'
  map-ink: '#b4cada'
  working-fill: '#0b3537'
  working-ink: '#54e3d7'
  working-line: '#15766f'
typography:
  title:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: -0.3px
  chapter-title:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 20px
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: -0.3px
  section:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 15px
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
  body-small:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
  annotation:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 11px
    fontWeight: 400
    lineHeight: 1.5
  mono:
    fontFamily: IBM Plex Mono, monospace
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.5
  metric:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 23px
    fontWeight: 500
    lineHeight: 1.2
  operations-title:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 25px
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -0.35px
  cartographic-label:
    fontFamily: Noto Sans Regular
    fontSize: 10px
  operational-status:
    fontFamily: IBM Plex Sans, sans-serif
    fontSize: 10px
    fontWeight: 400
    lineHeight: 1.35
rounded:
  control: 5px
  chip: 4px
  square: 0px
  status: 12px
spacing:
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '5': 24px
  '6': 32px
components:
  button-primary:
    backgroundColor: '{colors.accent}'
    textColor: '{colors.accent-ink}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  button-primary-hover:
    backgroundColor: '{colors.accent-hover}'
    textColor: '{colors.accent-ink}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  button-secondary:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.ink}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  button-disabled:
    backgroundColor: '{colors.raised}'
    textColor: '{colors.faint}'
    rounded: '{rounded.control}'
    padding: 7px 12px
  input:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.ink}'
    rounded: '{rounded.control}'
    padding: 7px 9px
  status-chip:
    textColor: '{colors.muted}'
    typography: '{typography.annotation}'
    rounded: '{rounded.chip}'
    padding: 3px 6px
  status-chip-active:
    backgroundColor: '{colors.accent-soft}'
    textColor: '{colors.accent}'
    typography: '{typography.annotation}'
    rounded: '{rounded.chip}'
    padding: 3px 6px
  panel:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.ink}'
    rounded: '{rounded.control}'
  navigation-active:
    textColor: '{colors.accent}'
    typography: '{typography.label}'
  agent-row-selected:
    backgroundColor: '{colors.accent-soft}'
    textColor: '{colors.ink}'
    rounded: '{rounded.square}'
    padding: 8px 12px
  operations-panel:
    backgroundColor: '{colors.bg}'
    textColor: '{colors.ink}'
    rounded: '{rounded.control}'
  madrid-status-active:
    backgroundColor: '{colors.working-fill}'
    textColor: '{colors.working-ink}'
    typography: '{typography.operational-status}'
    rounded: '{rounded.status}'
    padding: 2px 7px
  madrid-agent-row-selected:
    backgroundColor: '{colors.accent-soft}'
    textColor: '{colors.ink}'
    rounded: '{rounded.square}'
    padding: 7px 12px
  map-toolbar:
    backgroundColor: '{colors.map-chrome}'
    rounded: '{rounded.chip}'
    padding: 3px 4px
---

# Design system: madrid-delivery-sim

## Overview

**Creative North Star: "Calm, dense operations console"**

Dark blue graphite surfaces, cyan selection, restrained state colors, IBM Plex Sans and Mono, fine rules and dense readable rows. The interface follows the user's Linear-style dark operations-console direction: calm, dense, one accent color. Technical reviewers can inspect the same working evidence that operators use.

Compact plain titles keep the working interface near the top. Agents are the protagonist and their shared city stays visible beside them on operational screens; reading and evaluation screens use the same material language without imitating the map layout. Color communicates state, selection or data. The confirmed anti-references are decorative heroes, oversized marketing headlines, split-color or gradient headline text, purple gradients, Inter-everywhere and nested cards.

**Key Characteristics:**
- Local IBM Plex fonts, tabular operational values and explicit technical identifiers.
- Flat dark graphite surfaces separated by fine rules; cyan marks actions and selection.
- Readable rows, plain labels, visible focus and progressive disclosure of evidence.
- Runtime data remains inspectable; missing history and measurements remain explicit.

## Colors

The dark ground reads as deep blue graphite, with pale ink and one cyan accent. Madrid's metric strip and operational panels use the ground color itself, avoiding the raised gray slabs of the superseded implementation. The frontmatter is normative; CSS custom properties in `web/tokens.css` are the implementation source. The sidecar's synthesized tonal ramps are palette previews, not additional implementation tokens.

### Primary

- **Signal cyan** (`accent`): primary run actions, the active global workspace, selected agent edges, observed curves and active routes.
- **Deep cyan ink** (`accent-ink`): text on the filled primary action.
- **Cyan selection surface** (`accent-soft`): selected rows, active chips and the illustrated lifecycle's active stage.
- **Light signal teal** (`accent-hover`): primary-action hover feedback.

### Neutral

- **Blue graphite ground** (`bg`): page ground, global navigation and recessed code.
- **Graphite surface** (`surface`): shared evidence panels, fields and table areas. Madrid's compact operational panels use `bg` instead.
- **Raised graphite** (`raised`) and **hover graphite** (`hover`): disabled controls, selected view controls and hover response.
- **Pale ink** (`ink`): main text. **Muted ink** (`muted`): labels and supporting evidence. **Faint ink** (`faint`): tertiary annotations and disabled text.
- **Fine rule** (`line`): panel boundaries, rows and dividers. **Strong rule** (`strong-line`): field outlines and stronger technical boundaries.

The map-ground, map-chrome, map-rule and map-ink tokens record the recurring cartographic background and overlay materials from `web/style.css`. Madrid's working-fill, working-ink and working-line tokens describe its brighter active state pills; shared Restaurant chips retain their existing treatment. These component colors do not replace the global accent.

Positive, negative, warning and information tokens represent outcomes, attention and assignment states. Pair them with visible text or symbols. Their distinct hues are semantic exceptions to the single-accent strategy.

**The One Accent Rule.** Cyan identifies primary action, selection and observed activity. Positive, negative, warning and information colors carry operational meaning; they are not alternate brand accents.

## Typography

**Body and title font:** IBM Plex Sans, with a generic sans-serif fallback.
**Label/mono font:** IBM Plex Mono, with a generic monospace fallback.

Both UI families are served locally from `web/fonts/` with their SIL OFL licenses; no external font service is required. Regular, Medium and SemiBold Sans files and one Regular Mono file are present. CSS weights above the supplied native weights resolve through the existing face declarations; they are not additional font assets. The OpenFreeMap style uses locally cached Noto Sans Regular glyphs for cartographic labels only. This is an explicit map typography exception; UI controls, selected-agent labels and overlays remain Plex. Most cartographic labels use 10px type, with larger place labels defined by the map style.

### Hierarchy

The frontmatter records the shared title, operations-title, chapter-title, section, body, label, mono and metric roles. There is no display/hero role. Madrid's title is 25px/600 at full desktop width, 23px below 1400px and 22px below 850px. Shared page titles retain the 24px role; Architecture uses 20px, Traces uses 22px and Health uses 20px/600. Madrid's metric values use 23px/500, becoming 22px below 850px.

Madrid's agent identity is 12px with 10px secondary detail at full width. Status pills use the operational-status role, and the compact ledger uses 11px text. Narrow mobile roster annotations reach 9px in the existing implementation; that is a page-specific density exception, not a recommended general body or label scale. Section headings commonly use 15px. Typography stays compact without flattening the hierarchy.

Body text is IBM Plex Sans. IDs, simulation times, trace metadata, code and narrow numerical evidence use IBM Plex Mono. Tabular numbers keep values stable as they update. Supporting labels are smaller than body text; technical annotation is not a new headline tier. Reading prose and trace summaries are capped at 75ch in their existing layouts.

**The Compact Title Rule.** Start with a plain workspace title and the working interface. Do not add a display headline, decorative hero or slogan.

## Layout

Use the established spacing rhythm in the frontmatter. The sticky global shell has a 44px header token at wider widths and a 56px token below 600px. The desktop shell uses 20px horizontal padding. Madrid's working content uses 12px side gutters, reducing to 10px below 850px; other workspaces retain their own larger gutters.

Madrid pairs its roster and map at a 45.5/54.5 ratio, expressed as 0.91/1.09 fractional columns with an 8px gap. Both panels use a shared height of clamp(360px, 45vh, 460px). A shallow four-part KPI band has an 80px minimum height, 10px by 20px metric padding and an 8px gap before the working panes. Keep actual agent comparisons and continuous geography together.

The desktop roster uses a compact toolbar followed by Agent, Role, Status, Current task, Delivered and Rate/min columns. Rows have a 51px minimum height. The separate role column disappears below 1400px, while the narrowest layout also hides rate history. The current-visit history note remains explicit. The selected-evidence strip follows with an 88px minimum height, three evidence groups and trace/detail actions. The ledger follows at an 8px gap, using 11px text, 5px vertical header padding and 1px vertical cell padding; its scroll region is capped at 300px on desktop. Native viewport row count remains an evidence check, not a fabricated data requirement.

Madrid stacks at 850px with agents before the map. Its mobile map is a 400px high region; the collapsible legend sits in normal flow below it, so open and closed legend states do not cover the selected courier. The toolbar stays within the map's top-left working area, with zoom controls at the top-right. The selected summary reduces to identity/task while keeping trace access.

Restaurants retains a 340px minimum roster, a 0.9/1.1 ratio, a 16px gap and stacks at 900px. The older Delivery grid workspace has been retired; Operations is the single delivery overview.

Global navigation becomes a menu at 1080px, with three columns of links when opened and two below 600px. Its links stay ordinary anchors, and Escape restores focus to the menu button. Shared narrow controls have a 44px minimum target and text inputs use 16px type; Madrid's compact roster/map controls and other page-specific overrides are explicit exceptions, not a universal target-size promise.

Architecture uses topic, reader and page-outline columns. The outline disappears at 1250px and the topic sidebar becomes a disclosure at 700px. Tables, code, rosters and expanded diagrams scroll within their own containers. Simulation and definition controls remain separate from the operational panes. Inventory, Health, Traces and Architecture keep their evidence-specific layouts.

## Elevation & Depth

Ordinary panels and list rows are flat. Fine boundaries and restrained tonal changes describe containment. The selection edge is an inset marker, not a lifted card. Map tooltips and popups use the shared small ambient shadow (`0 8px 24px #0005`); courier markers retain a small legibility shadow (`0 2px 3px #0008`). Dialogs use a translucent dark backdrop rather than ornamental elevation. The sidecar records these values because the frontmatter component schema has no shadow field.

**The Flat Surface Rule.** Separate working areas with tonal changes and fine rules. Keep ordinary panels and rows shadowless; reserve the small ambient shadow for map overlays.

## Shapes

Controls and operational panels use restrained corners from the control radius. Shared small state chips use the chip radius. Madrid uses rounded 12px status pills without redundant state dots. Ledger pills are 104px wide with centered labels; roster pills stretch to the status column width. Session badges retain the smaller corner radius. Roster rows, tabs, reading frames and table geometry stay square where the implementation defines them that way. Use one-pixel rules for working boundaries. Circles belong to roster role symbols, map markers, clusters and numbered lifecycle steps; they are functional symbols rather than a decorative motif.

The unused larger-radius declaration in the CSS token file is not promoted into this documented component vocabulary. No future surface should inherit a radius merely because a dormant variable exists.

## Components

### Buttons

Primary run actions have a cyan fill, deep cyan text and a medium/semibold weight. Secondary controls use graphite surfaces and strong outlines. The frontmatter records their padding and shape; the shared desktop minimum height is 36px. Hover changes surface/border color, disabled actions use raised graphite and faint ink, and visible keyboard focus uses a 2px cyan outline with a 3px offset. Background and border transitions use 180ms with `cubic-bezier(.16,1,.3,1)`. Under reduced motion, transition duration is exactly 0s so map transforms do not retain transient stale geometry. The shared animation-duration override remains 0.01ms, and the illustrated lifecycle animation is disabled.

### Inputs / Fields

Plain outlined fields retain accessible labels. Shared forms use visible labels; Madrid's compact agent/order filters use visually hidden labels together with descriptive placeholder or selected-option text. Inputs, selects and textareas share the surface background, strong rule and control radius. Placeholder text is muted; disabled fields use the raised surface. Keep IDs, search labels and evidence context readable instead of replacing labels with icons.

### Chips

Small labels expose actual state. Neutral chips have a fine outline and muted text. Shared active chips use the soft accent surface with accent text; Madrid's active status pills use the dedicated working-state tokens, centered labels and rounded ends. Outcome colors are paired with readable status words. These chips are status indicators, not implied buttons.

### Cards / Containers

Use one panel boundary around a coherent working region. Separate its heading and rows with fine rules; leave ordinary panels shadowless. Shared panel-title and roster rows become compact on desktop. Madrid uses the ground color for its panels and metric band; a whole gray filled slab is no longer its panel treatment. Do not turn every metric, fact or nested evidence item into another card.

### Navigation

The global shell contains six workspaces: Operations, Restaurants, Inventory, Health, Traces and Architecture. A cyan underline and cyan text identify the current workspace. Local view tabs retain their implementation-specific active border or raised selected state. A skip link reaches the main workspace; mobile disclosure preserves the same destinations and keyboard behavior.

### Agent roster and selected evidence

The roster combines reusable SVG role symbols with actual identity, task, state and throughput. Madrid separates role, status, current task, delivered total and rate into comparison columns; narrower widths remove secondary columns without changing the data. Restaurants also exposes its technical ID separately. Selected rows use a soft cyan fill and a thin inset accent edge: 1px in Madrid, 2px in the shared Restaurant roster. A summary remains compact; detail opens on request. Empty and filtered states explain why no agents are visible.

Curves represent observed samples, not decoration. The shared helper requires at least two finite samples; roster history is limited to the current visit and records activity per simulated minute. A completed run without captured history says so. Totals and rates remain separately labeled.

### Maps and diagrams

Madrid uses a locally vendored OpenFreeMap vector basemap rendered by MapLibre through the Leaflet bridge. Real roads, land use, water and Spanish place labels fill the frame; the simulator's cached OpenStreetMap graph is a fine operational overlay. The checked-in manifest records 332 tiles, 36,512,766 bytes (36.51 MB), at source zoom levels 10–14. Higher view zooms overzoom that finite local coverage. Noto Sans Regular cartographic glyphs, renderer files, licenses and map style are local; attribution to OpenFreeMap, OpenMapTiles and OpenStreetMap remains visible.

Dragging, mouse-wheel zoom, touch zoom and keyboard navigation are enabled from the initial view. Escape releases wheel input to page scrolling; the Scroll zoom toggle restores wheel zoom. Fit network and Locate agent reserve space below the toolbar; selection framing keeps real coordinates and genuine route lengths. Selected-label placement considers control geometry, and a ResizeObserver synchronizes Leaflet dimensions with the MapLibre camera before repositioning the label. These are implementation behaviors; the recorded review/capture evidence determines whether their specific states are verified.

Operations is the single geographic overview. Restaurants uses a searchable agent roster and adjacent inspector; Inventory uses a store selector and stock table. The retired fictional grid renderers are removed. On the Madrid map, symbols distinguish couriers, pickups and destinations; text and line styles distinguish planned and traveled routes. Do not replace synthetic service geometry with Madrid cartography or stretch a real route to imitate an illustrative comp.

Eight source-backed D2 diagrams retain their existing graphite/teal palette and locally embedded IBM Plex fonts. Their hard-coded palette has not been regenerated to exactly match the new shared cyan tokens; this is a documented retained exception. The initial image shows the complete diagram within its frame; Expand provides readable inspection, pan and zoom, and Fit restores a complete overview. Architecture's four-stage lifecycle animation is finite and replayable, labeled as an illustration, and disabled under reduced motion.

## Do's and Don'ts

### Do:

- **Do** keep simulation setup separate from the operation view where that separation is implemented.
- **Do** preserve distinct entity names, technical IDs and role labels when inspecting agents.
- **Do** use SVG symbols with text labels and state descriptions; color alone must not carry meaning.
- **Do** label the history window, units, simulation clock and session state; render curves only from observed samples.
- **Do** keep unavailable metrics, synthetic fixtures, retained-evidence limits and stale-source caveats visible.
- **Do** keep selected map markers, labels and actual route geometry clear of toolbar and legend controls.
- **Do** retain keyboard focus, reduced-motion behavior, local overflow containers and mobile disclosure controls.

### Don't:

- **Don't** introduce oversized marketing headlines, split-color headlines, headline gradients or decorative hero sections.
- **Don't** add purple gradients, Inter-everywhere, nested cards or ornamental dashboard effects.
- **Don't** turn an empty history, unknown cost or unknown latency into a fabricated chart or zero.
- **Don't** use a sparse graph overlay as a substitute for Madrid's continuous local basemap.
- **Don't** substitute a role template name for the actual entity identity.
- **Don't** shrink a diagram's detailed reading view merely to force every label into one viewport; provide a whole-diagram overview plus an expanded inspection view.

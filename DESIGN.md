---
name: "Bakiano operations"
description: "A calm, dense console for inspectable delivery-agent operations."
colors:
  accent: "#63d5c5"
  accent-ink: "#082b27"
  accent-soft: "#193b36"
  accent-hover: "#90e4d8"
  bg: "#0d151c"
  surface: "#151c20"
  raised: "#1c252a"
  hover: "#263239"
  ink: "#e7edf0"
  muted: "#a8b7c0"
  faint: "#81949f"
  line: "#2c393f"
  strong-line: "#536770"
  positive: "#75d2a8"
  negative: "#f28e8e"
  warning: "#e9bc71"
  info: "#8db9e3"
typography:
  title:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.3px"
  chapter-title:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-0.3px"
  section:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  body-small:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  annotation:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.5
  mono:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  metric:
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "24px"
    fontWeight: 500
    lineHeight: 1.15
rounded:
  control: "5px"
  chip: "4px"
  square: "0px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  button-disabled:
    backgroundColor: "{colors.raised}"
    textColor: "{colors.faint}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 9px"
  status-chip:
    textColor: "{colors.muted}"
    typography: "{typography.annotation}"
    rounded: "{rounded.chip}"
    padding: "3px 6px"
  status-chip-active:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
    typography: "{typography.annotation}"
    rounded: "{rounded.chip}"
    padding: "3px 6px"
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
  navigation-active:
    textColor: "{colors.accent}"
    typography: "{typography.label}"
  agent-row-selected:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    padding: "8px 12px"
---

# Design System: Bakiano operations

## Overview

**Creative North Star: "Calm, dense operations console"**

Graphite surfaces, teal selection, restrained state colors, IBM Plex Sans and Mono, fine rules and dense readable rows. The interface follows the user's Linear-style dark operations-console direction: calm, dense, one accent color. Technical reviewers can inspect the same working evidence that operators use.

Compact plain titles keep the working interface near the top. Agents are the protagonist and their shared city stays visible beside them on operational screens; reading and evaluation screens use the same material language without imitating the map layout. Color communicates state, selection or data. The confirmed anti-references are decorative heroes, oversized marketing headlines, split-color or gradient headline text, purple gradients, Inter-everywhere and nested cards.

**Key Characteristics:**
- Local IBM Plex fonts, tabular operational values and explicit technical identifiers.
- Flat graphite surfaces separated by fine rules; teal marks actions and selection.
- Readable rows, plain labels, visible focus and progressive disclosure of evidence.
- Runtime data remains inspectable; missing history and measurements remain explicit.

## Colors

The dark ground reads as blue graphite, with pale ink and one cool teal accent. The frontmatter is normative; CSS custom properties in `web/tokens.css` are the implementation source. The sidecar's synthesized tonal ramps are palette previews, not additional implementation tokens.

### Primary

- **Signal teal** (`accent`): primary run actions, the active global workspace, selected agent edges, observed curves and active routes.
- **Deep teal ink** (`accent-ink`): text on the filled primary action.
- **Teal selection surface** (`accent-soft`): selected rows, active chips and the illustrated lifecycle's active stage.
- **Light signal teal** (`accent-hover`): primary-action hover feedback.

### Neutral

- **Blue graphite ground** (`bg`): page ground, global navigation and recessed code.
- **Graphite surface** (`surface`): working panels, fields and table areas.
- **Raised graphite** (`raised`) and **hover graphite** (`hover`): disabled controls, selected view controls and hover response.
- **Pale ink** (`ink`): main text. **Muted ink** (`muted`): labels and supporting evidence. **Faint ink** (`faint`): tertiary annotations and disabled text.
- **Fine rule** (`line`): panel boundaries, rows and dividers. **Strong rule** (`strong-line`): field outlines and stronger technical boundaries.

Positive, negative, warning and information tokens represent outcomes, attention and assignment states. Pair them with visible text or symbols. Their distinct hues are semantic exceptions to the single-accent strategy.

**The One Accent Rule.** Teal identifies primary action, selection and observed activity. Positive, negative, warning and information colors carry operational meaning; they are not alternate brand accents.

## Typography

**Body and title font:** IBM Plex Sans, with a generic sans-serif fallback.
**Label/mono font:** IBM Plex Mono, with a generic monospace fallback.

Both families are served locally from `web/fonts/` with their SIL OFL licenses; no external font service is required. Regular, Medium and SemiBold Sans files and one Regular Mono file are present. CSS weights above the supplied native weights resolve through the existing face declarations; they are not additional font assets.

### Hierarchy

The frontmatter records the reusable title, chapter-title, section, body, body-small, label, annotation, mono and compact metric roles. There is no display/hero role. Shared page titles use the title role; Architecture has the smaller chapter-title role. Traces currently uses a 22px title; Health uses 20px/600. These are observed page exceptions, not a reason to inflate every title. Section headings commonly use 15px, with larger reader/trace section headings where source content requires them.

Body text is IBM Plex Sans. IDs, simulation times, trace metadata, code and narrow numerical evidence use IBM Plex Mono. Tabular numbers keep values stable as they update. Supporting labels are smaller than body text; technical annotation is not a new headline tier. Reading prose and trace summaries are capped at 75ch in their existing layouts.

**The Compact Title Rule.** Start with a plain workspace title and the working interface. Do not add a display headline, decorative hero or slogan.

## Layout

Use the established spacing rhythm in the frontmatter. The global shell is sticky, with a 52px header at wider widths and a 56px header token below 600px. Workspace gutters generally use 24px on desktop and 16px on narrow screens; the Architecture reader has its own wider reading gutters.

Operational screens pair a left roster with a slightly wider right map, separated by a 16px gap. Madrid's desktop grid uses a 420px minimum roster and a 0.88/1.12 ratio; Delivery uses a 380px minimum and 0.9/1.1; Restaurants uses a 340px minimum and 0.9/1.1. These page-specific constraints keep both views available at laptop widths. Madrid stacks at 800px; Delivery and Restaurants stack at 900px. Keep agents ahead of the map in the stacked reading order.

Madrid uses a four-part metric strip, a bounded roster, a map, a shallow selected-agent summary and then the order ledger. The shared Delivery/Restaurant roster uses fixed local scroll regions and rows that become denser above 800px. Simulation and definition controls open separately from these operational panes. Inventory, Health, Traces and Architecture retain their evidence-specific layouts.

Global navigation becomes a menu at 1080px, with three columns of links when opened and two below 600px. Its links stay ordinary anchors, and Escape restores focus to the menu button. At narrow widths, shared controls have a 44px minimum target and text inputs use 16px type; local compact map controls are existing exceptions, not a universal target-size promise.

Architecture uses topic, reader and page-outline columns. The outline disappears at 1250px and the topic sidebar becomes a disclosure at 700px. Tables, code, rosters and expanded diagrams scroll within their own containers. Do not use page-wide horizontal overflow as the layout strategy.

## Elevation & Depth

Ordinary panels and list rows are flat. Fine boundaries and restrained tonal changes describe containment. The selection edge is an inset marker, not a lifted card. Map tooltips and popups use the shared small ambient shadow (`0 8px 24px #0005`); courier markers retain a small legibility shadow (`0 2px 3px #0008`). Dialogs use a translucent dark backdrop rather than ornamental elevation. The sidecar records these values because the frontmatter component schema has no shadow field.

**The Flat Surface Rule.** Separate working areas with tonal changes and fine rules. Keep ordinary panels and rows shadowless; reserve the small ambient shadow for map overlays.

## Shapes

Controls and operational panels use restrained corners from the control radius. Small state chips use the chip radius. Roster rows, tabs, reading frames and table geometry stay square where the implementation defines them that way. Use one-pixel rules for working boundaries. Circles belong to map markers, clusters and numbered lifecycle steps; they are functional symbols rather than a decorative motif.

The unused larger-radius declaration in the CSS token file is not promoted into this documented component vocabulary. No future surface should inherit a radius merely because a dormant variable exists.

## Components

### Buttons

Primary run actions have a teal fill, deep teal text and a medium/semibold weight. Secondary controls use graphite surfaces and strong outlines. The frontmatter records their padding and shape; the shared desktop minimum height is 36px. Hover changes surface/border color, disabled actions use raised graphite and faint ink, and visible keyboard focus uses a 2px teal outline with a 3px offset. Background and border transitions use 180ms with `cubic-bezier(.16,1,.3,1)`.

### Inputs / Fields

Plain outlined fields retain visible labels. Inputs, selects and textareas share the surface background, strong rule and control radius. Placeholder text is muted; disabled fields use the raised surface. Keep IDs, search labels and evidence context readable instead of replacing labels with icons.

### Chips

Small labels expose actual state. Neutral chips have a fine outline and muted text. Active chips use the soft teal surface with teal text; outcome colors are paired with readable status words. These chips are status indicators, not implied buttons.

### Cards / Containers

Use one panel boundary around a coherent working region. Separate its heading and rows with fine rules; leave ordinary panels shadowless. Shared panel-title and roster rows become compact on desktop. Do not turn every metric, fact or nested evidence item into another card.

### Navigation

The global shell contains seven workspaces: Operations, Delivery, Restaurants, Inventory, Health, Traces and Architecture. A teal underline and teal text identify the current workspace. Local view tabs retain their implementation-specific active border or raised selected state. A skip link reaches the main workspace; mobile disclosure preserves the same destinations and keyboard behavior.

### Agent roster and selected evidence

The roster combines a reusable SVG role symbol, actual entity identity, current task, explicit state and a total/rate column. Restaurants also exposes its technical ID separately. Selected rows use a soft teal fill and a thin inset accent edge. A summary remains compact; detail opens on request. Empty and filtered states explain why no agents are visible.

Curves represent observed samples, not decoration. The shared helper requires at least two finite samples; roster history is limited to the current visit and records activity per simulated minute. A completed run without captured history says so. Totals and rates remain separately labeled.

### Maps and diagrams

The Madrid map uses the cached local OpenStreetMap road graph through Leaflet; it is a functioning data surface, not an illustrative raster. The other simulation maps explicitly identify fictional grid geometry. Symbols distinguish roles; text and line styles explain selection, planned routes and traveled routes. Attribution remains visible.

Eight source-backed D2 diagrams use the same graphite, ink, rule and teal family with locally embedded IBM Plex fonts. The initial image shows the complete diagram within its frame; Expand provides readable inspection, pan and zoom, and Fit restores a complete overview. Architecture's four-stage lifecycle animation is finite and replayable, labeled as an illustration, and disabled under reduced motion.

## Do's and Don'ts

### Do:

- **Do** keep simulation setup separate from the operation view where that separation is implemented.
- **Do** preserve distinct entity names, technical IDs and role labels when inspecting agents.
- **Do** use SVG symbols with text labels and state descriptions; color alone must not carry meaning.
- **Do** label the history window, units, simulation clock and session state; render curves only from observed samples.
- **Do** keep unavailable metrics, synthetic fixtures, retained-evidence limits and stale-source caveats visible.
- **Do** retain keyboard focus, reduced-motion behavior, local overflow containers and mobile disclosure controls.

### Don't:

- **Don't** introduce oversized marketing headlines, split-color headlines, headline gradients or decorative hero sections.
- **Don't** add purple gradients, Inter-everywhere, nested cards or ornamental dashboard effects.
- **Don't** turn an empty history, unknown cost or unknown latency into a fabricated chart or zero.
- **Don't** substitute a role template name for the actual entity identity.
- **Don't** shrink a diagram's detailed reading view merely to force every label into one viewport; provide a whole-diagram overview plus an expanded inspection view.

---
name: Madrid
description: "A warm, readable product for exploring inspectable delivery agents."
colors:
  "bg": "#f7f2e9"
  "surface": "#fffdf8"
  "raised": "#eee8dd"
  "hover": "#e6eddf"
  "ink": "#14291e"
  "muted": "#536257"
  "faint": "#626e63"
  "line": "#d9d7cb"
  "strong-line": "#9da99b"
  "accent": "#087c3b"
  "accent-hover": "#066631"
  "accent-ink": "#fffdf8"
  "accent-soft": "#dfeedd"
  "positive": "#146b41"
  "negative": "#a8323d"
  "warning": "#865a09"
  "info": "#306997"
  "positive-bg": "#e3efdf"
  "negative-bg": "#f8e5e4"
  "warning-bg": "#f5e9ce"
  "info-bg": "#e2edf2"
  "map-water": "#bedbe1"
  "map-water-line": "#7fa9b2"
  "map-land": "#e9e5db"
  "map-park": "#d6e3c9"
  "map-building": "#e1d9cb"
  "map-ground": "#eee7db"
  "map-road": "#fffdf6"
  "map-edge": "#d7d4c8"
  "map-route": "#158648"
  "map-label": "#536257"
  "selection": "#c7e3c2"
  "dark-bg": "#15221b"
  "dark-surface": "#1e2e23"
  "dark-raised": "#293a2e"
  "dark-hover": "#344b39"
  "dark-ink": "#eef4ea"
  "dark-muted": "#b3c2b3"
  "dark-faint": "#a0b3a2"
  "dark-line": "#3b4e3d"
  "dark-strong-line": "#6c826d"
  "dark-accent": "#73d5a1"
  "dark-accent-hover": "#98e2b7"
  "dark-accent-ink": "#0b3020"
  "dark-accent-soft": "#294b35"
  "dark-positive": "#9bdfb1"
  "dark-negative": "#f2a1a0"
  "dark-warning": "#edcc85"
  "dark-info": "#a8cddd"
  "dark-positive-bg": "#203c2b"
  "dark-negative-bg": "#4a2d2d"
  "dark-warning-bg": "#443c24"
  "dark-info-bg": "#273e49"
  "dark-map-water": "#1f4650"
  "dark-map-water-line": "#49818a"
  "dark-map-land": "#293b30"
  "dark-map-park": "#314b34"
  "dark-map-building": "#304335"
  "dark-map-ground": "#24362b"
  "dark-map-road": "#3f5542"
  "dark-map-edge": "#1a2b20"
  "dark-map-route": "#80d99c"
  "dark-map-label": "#b3c2b3"
  "dark-selection": "#385d40"
typography:
  "title":
    fontFamily: "Work Sans, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  "section":
    fontFamily: "Work Sans, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  "subsection":
    fontFamily: "Work Sans, sans-serif"
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.2
  "body":
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  "body-large":
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "18px"
  "body-small":
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "14px"
  "label":
    fontFamily: "IBM Plex Sans, sans-serif"
    fontSize: "13px"
  "mono":
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "14px"
  "stat":
    fontFamily: "Work Sans, sans-serif"
    fontSize: "34px"
    fontWeight: 650
    lineHeight: 1.1
  "anatomy-title":
    fontFamily: "Oxanium, IBM Plex Sans, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.3
  "story-headline":
    fontFamily: "Work Sans, sans-serif"
    fontSize: "clamp(38px,3.96vw,63px)"
    fontWeight: 700
    lineHeight: 1.03
    letterSpacing: "-0.035em"
  "story-section":
    fontFamily: "Work Sans, sans-serif"
    fontSize: "clamp(28px,2.85vw,44px)"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.025em"
rounded:
  "control": "12px"
  "panel": "16px"
  "pill": "999px"
  "overlay-detail": "8px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "48px"
  "8": "72px"
components:
  "button-primary":
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
    typography: "{typography.body}"
  "button-primary-hover":
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  "button-secondary":
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  "button-quiet":
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  "button-disabled":
    backgroundColor: "{colors.raised}"
    textColor: "{colors.faint}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  "input":
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  "navigation-active":
    textColor: "{colors.accent}"
    typography: "{typography.body}"
    padding: "10px 0"
  "status-pill":
    backgroundColor: "{colors.raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "4px 10px"
    typography: "{typography.label}"
  "status-pill-positive":
    backgroundColor: "{colors.positive-bg}"
    textColor: "{colors.positive}"
    rounded: "{rounded.pill}"
    padding: "4px 10px"
    typography: "{typography.label}"
  "card":
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "24px"
  "recording-banner":
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "14px 20px"
    typography: "{typography.body-small}"
  "replay-controls":
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "12px 16px"
  "drawer":
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    padding: "28px"
    width: "min(640px,100%)"
    height: "100%"
---

# Design System: Madrid

## Overview

**Creative North Star: "Warm off-white, one strong accent, a dark alternative"**

Madrid shares a warm, readable product system across its public story and engineering workspaces. Off-white surfaces and deep green text carry the light appearance; green-black surfaces and pale ink carry the dark appearance. A green accent identifies action and selection, while semantic colors describe outcomes and the existing robot colors identify roles.

Work Sans gives headings a distinct voice, IBM Plex Sans carries explanations and controls, and IBM Plex Mono keeps source evidence legible. Rounded controls and softly raised panels support clear grouping without hiding dense tools. The approved landing has its own larger narrative scale; labs keep compact titles and direct access to work. The existing whole-body robots and in-place memory explorer retain their identity and interaction model.

**Key Characteristics:**

- One shared token layer and shell, with persistent light and dark appearances.
- Readable supporting text, compact engineering titles and a distinct public-story type scale.
- Rounded controls, fine boundaries and restrained soft elevation.
- Recorded evidence, illustrative motion and live state remain distinguishable.

This record extracts the implemented system from `web/tokens.css`, `web/workspace.css`, `web/workspace.js`, the landing and domain styles. PRODUCT.md supplies product commitments; the landing surface brief owns its particular composition. No new brand metaphor or named doctrine is introduced here.

## Colors

The palette uses warm neutral materials and a green action accent in both appearances. Frontmatter values are normative; `web/tokens.css` is the implementation source. Unprefixed colors are light values; each `dark-` token is the corresponding value under `:root[data-theme="dark"]`. Components continue to consume the same CSS variables after a theme change.

### Primary

- **Action green** (`accent`, `accent-hover`, `accent-ink`): primary actions, selected destinations, interactive links and their hover state. The light button has pale text; the dark button has deep green text.
- **Soft green selection** (`accent-soft`, `selection`): selected controls, recorded-example banners and text selection. These fills do not replace a text or state label.

### Secondary

- **Positive green**, **negative red**, **warning ochre** and **information blue** (`positive`, `negative`, `warning`, `info`) have paired `-bg` surfaces in each appearance. Use the foreground and background together for statuses and evidence qualifications.
- Existing robot role colors identify agents. They belong to the source-native model and role definitions, not to a new set of interchangeable brand accents.

### Neutral

- **Warm ground** (`bg`) and **near-white surface** (`surface`) establish the light canvas. Their dark counterparts are green-black and forest surfaces.
- **Raised** and **hover** surfaces separate secondary material and interactive response.
- **Ink**, **muted** and **faint** text establish information hierarchy; **line** and **strong-line** establish dividers and control boundaries.
- `map-ground`, `map-land`, `map-water`, `map-water-line`, `map-park`, `map-building`, `map-road`, `map-edge`, `map-route`, `map-label` describe the tokenized cartographic vocabulary. They do not change geography or imply that every retained map renderer consumes every token.

The sidecar's tonal ramps are synthesized palette previews only. They are not extra shipped tokens or permission to recolor retained data graphics.

## Typography

**Heading font:** Work Sans, with a sans-serif fallback.
**Body font:** IBM Plex Sans, with a sans-serif fallback.
**Evidence font:** IBM Plex Mono, with a monospace fallback.

These fonts are served locally. The body is readable at the shared body role, with small labels for controls and dense evidence. Tabular numerals stabilize metrics and simulation time. Source identifiers, traces and code use Mono. Reading prose retains a maximum width of 75ch where implemented; empty-state explanations use 65ch.

### Hierarchy

The frontmatter captures the shared title, section, subsection, body, large body, small body, label, mono and stat roles. Titles use a tighter line height than prose. Domain pages retain their own compact title overrides rather than being forced to the shared title size: Operations, for example, uses a 25px title that reduces at narrower widths.

The story-headline and story-section roles are explicit public-landing exceptions. The headline becomes 40px at both of its narrow breakpoints; supporting landing copy ranges from 18px to 25px. This approved story scale does not create a new default for technical pages.

Agent Anatomy's role and physical-part headings retain the locally served Oxanium SemiBold role. Explanations and controls remain Plex Sans; source values remain Plex Mono. This preserves the existing robot inspector rather than replacing its identity with the landing style.

## Layout

The shared shell has a 72px minimum header height, flexible horizontal spacing and a single line of desktop destinations. At 1150px it reduces gaps; at 900px navigation moves into a menu; at 520px the wordmark and controls become more compact. The footer wraps and then stacks. Shared cards and panels use 24px padding, reducing to 20px at the narrowest shared breakpoint. The reusable spacing steps are recorded in the frontmatter.

The public Watch view places the map before the roster in a 1.8:1 two-column layout, with a 320px minimum roster and 20px gap. It stacks at 1000px with the map first. The former Operations URL redirects to Watch; run controls remain in Advanced, with selected evidence and the ledger on that same page. Its narrow map uses a 400px geographic region with the legend below in normal flow. Restaurants reveals its inspector beside the roster when selected, then stacks at 900px. Inventory, Health, Traces and Architecture retain their own evidence-oriented layouts and local scroll containers.

The landing uses a continuous city field, left-side explanation, existing robots, a playback strip and connected order steps. Its content sections cap at 1400px. At 700px the story becomes a vertical sequence; playback changes to a small grid, order steps and outcomes stack, and technology items form two columns. These are surface-specific arrangements, not a mandatory page template.

Agent Anatomy pairs the complete robot with an adjacent in-place inspector. The memory tabs, record groups, constraints and expanded references remain in that inspector. Dense tables and payloads scroll locally; disclosure reveals detail without removing the primary context.

## Elevation & Depth

Shared cards and panels have subtle ambient elevation; dropdowns, tooltips and drawers use the stronger shared shadow. Fine one-pixel boundaries still carry most grouping. The shared light shadow is `0 6px 22px #24351c0c`, and the raised shadow is `0 14px 40px #24351c18`; dark appearance supplies `0 6px 22px #0002` and `0 14px 40px #0005`. These extension values live in the sidecar because the frontmatter component schema has no shadow property.

The drawer's backdrop is translucent green (`#11251b66`). Retained robot scenes have their own dimensional lighting and dark scene fields; their geometry and lights are illustration material, not interchangeable card treatments. The landing's fading background behind text protects readability over geography; it is not gradient headline text.

## Shapes

The control and panel radii in the frontmatter define the shared form language. Pills have fully rounded ends, while small tooltip and menu-detail surfaces use the smaller overlay radius. Theme controls are circular. Evidence rows, code tables and inspector substructures retain square internal geometry where useful. Rounded containers do not require every internal fact to become a separate card.

SVG symbols provide the shared icon vocabulary. The Madrid wordmark uses the implemented geometric mark; existing role symbols and full robot silhouettes remain distinct from the shell icons. Preserve symbols with their accompanying label or accessible name.

## Components

### Buttons

Primary buttons use the accent fill and accent ink; secondary buttons use the surface with a strong outline; quiet buttons remove the resting fill and border. Shared controls have a 44px minimum height. The frontmatter records their padding and radius. Primary hover uses the accent-hover token; secondary hover uses the hover surface and ink border. Disabled controls use raised fill, faint text and line borders without an opacity wash.

Keyboard focus uses a 3px accent outline with a 4px offset in the shared shell. Some retained inspector controls use a 2px local outline. Background and border transitions use 220ms with `cubic-bezier(.16,1,.3,1)`. Reduced motion sets transition duration to zero and limits CSS animations; it does not remove access to controls. Compact domain controls are existing overrides, not a universal 44px compliance claim.

### Inputs / Fields

Inputs, selects and textareas share a surface background, strong outline, control radius and a 44px minimum height. Placeholder text is muted; disabled fields use the raised surface. Visible labels and accessible names remain required. Checkboxes, radio buttons and sliders use the accent token. Dense roster filters retain local sizing; they do not redefine the shared body scale.

### Navigation

The Madrid home link precedes How it works, Watch it live and Meet the agents. The current primary destination has accent text and an underline. For engineers exposes the five specialist workspaces and documentation search. The theme control persists the selected appearance in local storage, defaults to light and updates its accessible name. Watch it run remains the primary shared action.

The narrow menu uses ordinary anchors and an expanded state. Escape closes menu/disclosure state and returns focus to its control; an outside click also closes it. The skip link reaches the main content or the Architecture reader. Engineering pages additionally expose a runtime/environment qualifier, while the public shell stays compact.

### Chips / Status

Shared pills use a fine border, rounded ends and compact readable text. The positive, negative, warning and information variants pair semantic foregrounds and backgrounds. State words remain visible. Retained rosters and ledger badges have domain-specific sizing; status is never inferred from hue alone.

### Cards / Containers

A shared card groups a coherent section using the panel radius, surface fill, fine rule and soft ambient shadow. Panels can retain domain-controlled padding. Metrics use stable numeric typography with a label and explanatory text. Roster selection adds an accent-soft fill and an inset selection edge; it does not imply a different entity identity.

### Recorded evidence and playback

Recorded-example banners use the soft accent surface, a short provenance statement and the available example/own-run actions. Playback pairs a named play/pause control, labeled slider and simulation time. The landing loads checked-in replay data, redraws on appearance/size changes, pauses when offscreen or hidden, and starts still when reduced motion is requested. The user can explicitly operate playback. A failure state offers retry and a working view link.

Actual recorded routes and attribution remain intact. The existing robots illustrate a role handoff; the outcome disclosure explicitly distinguishes that illustration from measured city evidence. Charts require observed samples, and absent history remains visible rather than becoming an invented curve.

### Drawers, tooltips and inspection

Advanced controls can open in a right-side native dialog, with a maximum width of 640px, a visible close button, a backdrop and focus restoration to the trigger. Tooltips provide technical terms on hover or keyboard focus. The complete robot inspector and memory explorer remain in place. They use local disclosure and source links rather than replacing detailed evidence with summary cards.

## Do's and Don'ts

### Do:

- **Do** use the shared appearance tokens for text, controls, semantic states and surfaces.
- **Do** pair status and role colors with readable labels or recognizable symbols.
- **Do** retain actual robot models, role identities, recorded route geometry and source attribution.
- **Do** label recorded examples, time windows, units, unavailable values and stale-source qualifications.
- **Do** keep existing engineering controls and raw evidence reachable through progressive disclosure.
- **Do** preserve visible keyboard focus, playback controls, reduced motion and local overflow for dense evidence.

### Don't:

- **Don't** apply the landing headline scale or story composition to engineering tools by default.
- **Don't** add split-color headlines, gradient headline text or decorative slogans.
- **Don't** present the illustrated robot handoff as measured activity, or a recorded simulation as live model performance.
- **Don't** fabricate zeroes, curves, latency or cost figures when the source does not provide them.
- **Don't** replace the source-native robots or real Madrid paths with invented mockup geometry.
- **Don't** treat retained tiny labels, fixed legacy colors or a review defect as a reusable system token.

The agent team now occupies distinct cutaway workspaces around a loading court.
Room openings preserve sightlines and the delivery path. The visible path and
moving token share one curve; solid green handoffs, dashed blue requests and
dotted purple review evidence remain distinct in an always-visible legend.
On phones the scene scrolls horizontally within its own viewport to preserve
robot size, while named role controls remain below. Loading reserves scene
space and shows a restrained network pulse, with a still reduced-motion state.

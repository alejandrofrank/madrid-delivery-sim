# Shared workspace design

The six local workspaces use one navigation shell and visual contract. Restaurant
operations, delivery, inventory, health, architecture and the Madrid baseline keep
their own working layouts and inspectable evidence. Their typography, controls,
surfaces, focus, state colours and navigation come from the same source.

## Direction and evidence

The visual direction is a compact operations tool: white surfaces, near-black
text, precise neutral borders and restrained red focus. State colours distinguish
successful, failed and delayed work. Titles remain small and the working controls
stay near the top. There are no decorative hero sections or background effects.

The user's Nothing reference informed the monochrome treatment and precise
information hierarchy. This is an interpretation of its visual direction, not a
copy of Nothing's website or a claim to use its private design system.

The review used these public sources on 2026-10-28:

- [USWDS typography](https://designsystem.digital.gov/components/typography/)
  for legibility, hierarchy and shared typesetting tokens.
- [Home Office layout and typography](https://design.homeoffice.gov.uk/accessibility/page-structure/layout-typography)
  for consistent landmarks, readable headings, reflow and navigation.
- [Queensland spacing guidance](https://www.designsystem.qld.gov.au/styles/spacing)
  for a small reusable spacing scale and alignment.
- [No AI Slop UI skill](https://github.com/claudiusararu/unslop-ui-skill/blob/main/.claude/skills/no-ai-slop/SKILL.md)
  as an opinionated review checklist for component consistency, contrast and
  responsive navigation. Its sample marketing layout was not applied to this tool.

## Shared implementation

`web/workspace.css` defines the neutral palette, state colours, Arial/Helvetica
body stack, mono values, control states, focus and responsive navigation. These
system fonts require no external font service. The 4/8/12/16/24/32 spacing scale,
2px control radius and tabular numbers keep operational data aligned.

Every HTML page loads the page stylesheet first, then the shared stylesheet.
Page styles define map, inspector, editor or evidence-table layout. The shared
layer owns the common control states. `web/workspace.js` mounts the same six-link
navigation, active-page indication, skip link and mobile disclosure everywhere.
The disclosure supports Escape and leaves the links available as normal anchors.
An HTML fallback provides navigation when JavaScript is disabled.

The page identity is `data-page` on the body. Delivery's `data-workspace` attributes
remain reserved for its local Overview, Orders, Fleet and Stores controls; using
that attribute on an ancestor would interfere with its delegated click handler.

CSS and JavaScript URLs contain their content digest. After editing assets:

```bash
python3 scripts/version_web_assets.py --write
python3 scripts/version_web_assets.py
```

The second command checks all six pages for stale URLs and missing assets. This
keeps an older cached page theme from surviving an updated HTML shell. Asset
versioning changes no API endpoint, simulation definition or permissions.

## Madrid map navigation

Madrid opens in Overview: the wheel scrolls the document, markers remain
selectable, and the visible zoom buttons work. Explore map explicitly enables
dragging, wheel/touch zoom and keyboard navigation; Escape returns to Overview
without changing the view. There is no automatic following or inertial panning.

Navigation is bounded to the existing service rectangle with 12% padding. The
minimum zoom adapts to the viewport; maximum zoom is 17. Reset view frames the
service area. Frame selection is enabled only when the selected courier/order
has a valid point or route within those bounds; framing caps zoom at 16. Map
height follows the viewport rather than imposing a tall scrolling surface.
This changes navigation, not the road dataset or simulation behavior.

Browser verification covers page scrolling over Overview, wheel zoom in Explore,
repeated panning stopping at the bounds, Escape/focus, selection framing and
clearing, Reset, and 375px reflow. The inspector and ledger retain their existing
scroll containers; their interaction and pagination are separate work.

## Diagrams

Eight diagrams share D2 0.9.0 sources and generated local SVGs. ELK owns layered
graph placement and orthogonal routing; D2 sequences preserve ordered handoffs.
Native labels, numbered execution phases, white nodes and graphite edges match
the workspace. Layered connectors are 1px; sequence lifelines use D2's default
dashes. Text is 18px for nodes and 16px for messages in the source SVG.

Expand starts at readable size. Pan and zoom support long sequences, while Fit
explicitly shows the entire graph. The fleet-recovery view distinguishes review,
dispatcher gates and physical handoff without implying a direct agent call or
teleporting custody. See `docs/diagrams/README.md` for reproducible generation.

## Acceptance checks

Check all six pages at desktop width and 375px. Verify the shared active-page
indicator, opening and closing the mobile menu, keyboard focus and Escape, and
the absence of page-level horizontal overflow. Wide tables and diagrams may
scroll within their labelled containers.

Inspect both idle and populated states: entity selection and editing, a complete
order conversation with memory changes, delivery view switching, stock evidence,
health filters and scenarios, chapter search, source inspection and all eight
expanded diagrams. Existing seeded outcome and role-isolation tests remain the
business-behaviour baseline. A visual change does not prove model quality.

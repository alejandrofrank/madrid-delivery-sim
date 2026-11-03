# Product interface

The visitor's route is **How it works → Watch it live → Meet the agents**.
The shared **For engineers** menu retains Restaurants, Inventory,
Health, Traces, architecture chapters and search. Old URLs redirect with their
run, order, agent and chapter parameters; the retired delivery grid opens Watch.

## Shared components

Every HTML page loads `web/tokens.css`, `web/workspace.css` and
`web/workspace.js`. Tokens define the light/dark palette, status colors, type,
spacing, radii, shadows and motion. Domain styles own their layout and
map, robot, store or evidence-specific rendering.

| Component | Contract |
| --- | --- |
| Header / navigation | Three primary destinations, engineer disclosure, appearance switch, Watch it run. Mobile menu closes with Escape. |
| Button | Native button or link with shared focus, hover, disabled and 44px target styles. |
| Card / panel | `ui-card` / `ui-panel`; one surface around related content. |
| Stat / pill | `ui-stat` / `ui-pill`; numerical evidence and text-labelled state. |
| Legend | `ui-legend`; text accompanies every semantic color. |
| Drawer | `ProductUI.drawer(id, title, content)` uses a native dialog, labelled heading and close button. Each run workspace has one Advanced drawer. |
| Empty state | `ui-empty`; explain what is missing and provide a next action. |
| Tooltip | `ProductUI.tooltip(label, explanation)` or `data-term`; keyboard focus exposes the technical explanation. |
| Recording banner | `ProductExamples.banner`; identifies synthetic, recorded, zero-paid-call evidence and leads to an explicit own-run action. |

Use IBM Plex Sans for reading, Work Sans for product headings and IBM Plex
Mono for source, IDs and dense technical measurements. The robot inspector
retains its distinctive display treatment. The appearance choice persists
locally as `mds-theme`; role beacons and textual status labels retain their
meaning in either appearance.

## Recorded defaults and trust

The landing loads only local static assets. `story-replay.json` is derived
from the sealed seed-42 city recording; its route vertices, clock and outcomes
are verified by the export tests. The robot handoff illustrates role boundaries.
It is not a claim that the recording used live model reasoning.

The city workspace uses `/api/recorded` by default. Inventory, Restaurants and
Traces use frozen examples; the store replay is loaded only on request.
An explicit `?run=` still selects the requested live run. `?live=1` opens the
local operator workspace without choosing a recording. A new run starts only
from an existing explicit operator action, subject to the existing API auth.

The public replay image also serves generated anatomy, documentation and
allowlisted source excerpts. It imports no database or model SDK and rejects
every write. Its own-run action links to setup documentation. Historical health
evidence is dated and labelled as historical, never passed off as a check of
the running revision.

## Animation and performance

The landing caches its street map and route layer. Only courier positions,
store pulses and the small robot handoff change each frame. The robot
geometry is batched, its ground shadows cached, and pixel ratios bounded.
One animation clock pauses when hidden or off-screen; reduced motion begins
on a still frame. Playback and seeking remain available. Watch has its own
pause and seek controls, including recorded in-store movement.

Run graphics-heavy browser checks **serially**, not in parallel with each
other. Multiple software-rendered WebGL browsers can compete with the user's
preview. `scripts/profile_story_animation.cjs` records frame intervals in the
actual browser; it is a diagnostic, not a cross-machine FPS promise.

## Verification and media

`tests/test_site_pages.py` checks shared tokens/header and legacy URL behavior.
`tests/test_recorded_views.py` checks read-only endpoints, source allowlisting
and exported-reference drift. `check_product_site.cjs` checks navigation,
motion, theme and fallbacks. `check_recorded_views.cjs` checks default data,
pause/seek and zero writes. Existing anatomy and store browser contracts still
cover full-body inspection, memory, keyboard access and graphics fallbacks.

`capture_product_media.cjs` captures the live browser at desktop, mobile and
the user's 1916px viewport. README images and the animated GIF use those
recorded frames. Rebuild public documentation after editing reviewed sources:

```bash
python3 scripts/build_public_reference.py
python3 scripts/version_web_assets.py --write
```

Product marks are unmodified official assets. Source URLs and SHA-256 receipts
are in [the brand asset manifest](../web/vendor/brands/sources.json).


## Continuous replay and workspace loading

Watch it live is the single city destination. Old `/engineers/operations`
bookmarks redirect there with their run/query parameters intact; Advanced
contains the existing run controls.

Before city playback starts, `/api/recorded/motion` supplies a bounded,
read-only timeline of courier positions and deduplicated street routes. A
presentation clock samples those routes on each animation frame. Both ends of
each interval are known, including assignments in the following snapshot.
Recorded street bends and preparation waits remain intact; interpolation joins
recorded positions where no intervening route was captured. The once-per-second
state request refreshes evidence and metrics, not marker positions or the slider.
Moving couriers stay individually visible instead of joining static clusters.
The in-process store recording uses the same sampler. Live simulation timing
keeps its bounded extrapolation clock.

The shared `ProductUI.loading` status reserves scene space and animates a small
network while real data loads. Reduced motion uses a still network. Agent and
chapter requests start together; failures keep a retry action. The team scene
uses separate cutaway workspaces, instanced architecture, and cached curves for
both visible paths and moving objects. Green is the bag/handoff path, blue is a
controller-routed agent request, and purple is review evidence. The always-visible
legend explains these distinctions. Phones retain readable robots in a locally
scrollable panorama; the page itself does not overflow.

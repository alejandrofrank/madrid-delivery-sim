# Assessment B — baseline technical audit

Baseline: main commit 69135c9. Scope: isolated mds-ui checkout only, seven pages served at http://127.0.0.1:8021. Source was held unchanged during assessment. This is the independent detector/browser assessment, not the design critique.

## Implementation integrity verdict

Pass with targeted corrections. A shared navigation, semantic controls, honest empty states, explicit local/model boundaries, and inspectable evidence make this a coherent engineering interface. No P0 blocker was demonstrated. One P1 target-size failure was verified; the remaining findings are P2/P3 improvements.

## Scores

Scores are 0–4. They describe the captured initial/empty states and inspected implementation, not a WCAG conformance certification.

| Page | Accessibility | Performance | Theming | Responsive | Integrity | Total |
|---|---:|---:|---:|---:|---:|---:|
| Delivery / flow | 3 | 3 | 2 | 3 | 3 | 14/20 Good |
| Restaurants / supply | 3 | 3 | 2 | 3 | 3 | 14/20 Good |
| Inventory / lab | 3 | 4 | 3 | 3 | 3 | 16/20 Good |
| Health & evals | 3 | 4 | 3 | 3 | 4 | 17/20 Good |
| Agent evidence | 3 | 4 | 3 | 3 | 3 | 16/20 Good |
| Architecture | 2 | 3 | 2 | 2 | 3 | 12/20 Acceptable |
| Madrid baseline | 3 | 2 | 2 | 3 | 3 | 13/20 Acceptable |

Theming has a common token base, but page styles and SVG rendering still contain many raw color values. The interface explicitly declares a light theme; absence of dark mode is not treated as a defect. Responsive scores reflect successful layout checks but compact content and incomplete physical touch testing.

## Findings

Counts of prioritized, consolidated findings: P0 0; P1 1; P2 6; P3 1.

1. **P1 — Architecture source links fail minimum target spacing.** Location: web/documentation.css:434–437, generated links in web/documentation.js:106. The two block links for agent_runtime.py and agent_specs.py are each 19.796875 CSS px high with zero vertical gap at both 1440 and 390 px. Their centers are only 19.8 px apart, so the required 24 px circles overlap. They are a separate block list, not links constrained by surrounding non-target sentence text. Increase each hit area to at least 24 px (prefer 44 px on touch layouts) or provide sufficient spacing. Evidence: targeted-checks.json. Standard: [WCAG 2.2 SC 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html). Suggested command: /impeccable adapt.

2. **P2 — Functional Architecture text is too small for comfortable inspection.** Locations: web/documentation.css:242–245 (10 px Copy link / Print); :343–345 (10 px legend); :385–389 (10 px component summaries); :698–705 (10 px reader footer). Shared label: web/workspace.css:209–215 uses 10 px Operations lab. The browser detector confirms these computed sizes. Increase functional metadata to a deliberate 12–13 px floor while keeping the compact hierarchy. This is a legibility finding, not an assertion that WCAG specifies a minimum font size. Suggested command: /impeccable typeset.

3. **P2 — Architecture body lines are very long.** Location: web/documentation.css:201–208 and :451–455. The browser detector measured about 127–135 characters on many article lines and about 99 in the component inspector. A narrower prose measure (roughly 65–80 characters) will reduce rereading on desktop while preserving full-width diagrams. Suggested command: /impeccable typeset.

4. **P2 — Maps put every entity into the sequential tab order.** Locations: web/flow.js:43, :154; web/supply.js:520. The fresh Delivery DOM has 140 SVG buttons and Restaurants has 138, all individually tabbable. Chromium exposes the named map buttons in its accessibility tree, which is positive, but keyboard users must traverse the full map before controls that follow it. Consider a single map entry with roving focus, an explicit bypass, and keep the existing entity selector/customer search alternatives. Suggested command: /impeccable harden.

5. **P2 — Inventory's initial map looks uninitialized without a local explanation.** Locations: web/lab.js:65–66; web/lab.html Fictional service area section. render() returns before drawing when there is no run, producing the large blank SVG and empty Store selector seen in every baseline screenshot. The page explains scenario execution elsewhere, but the map itself says to select a store that is not yet available. Add a local “Run the scenario to load the service area” state and disable/explain the empty selector. No simulation was started to test later states. Suggested command: /impeccable clarify.

6. **P2 — Agent evidence styles leak into the shared header.** Locations: web/agent-traces.css:2 and :36. Unscoped header rules apply the content header's column layout to the shared workspace header on mobile. The before screenshot shows a taller two-row header with the brand centered above the Menu button, unlike the other six workspaces. Scope those rules to main > header. Suggested command: /impeccable harden.

7. **P2 — Madrid loads a large network payload before interaction.** Location: web/app.js:240. The /api/roads response transferred 2,751,999 bytes in the fresh local page; this dominates a page with only 188 DOM elements. Delivery's largest payload was 452,429 bytes and Restaurants' was 477,543 bytes. Local timings were fast, so this is payload exposure rather than a demonstrated slow-load failure. Consider compression/caching and progressive or simplified geometry before expanding remote/mobile use. Suggested command: /impeccable optimize.

8. **P3 — Isolated paragraph stragglers.** Restaurants has two and Architecture two rendered last-word lines. They are advisory, viewport-dependent typography findings, not blocked content. Use text-wrap: pretty where suitable after layout changes. Suggested command: /impeccable polish.

## Detector results and verified false positives

### CLI

Command: impeccable detect --json web/agent-traces.html web/documentation.html web/flow.html web/health.html web/index.html web/lab.html web/supply.html

Full output: detector.json. Exit code 2. Six warnings, all rule flat-type-hierarchy, at line 0 of agent-traces.html, flow.html, health.html, index.html, lab.html, and supply.html. No vendor directory was a scan target.

**All six CLI findings are false positives.** The scanner could not resolve root-relative /static/*.css to the actual web/*.css files; it incorrectly assumed body and all headings were 16 px. Browser measurements show body 14 px, h1 20 px on six pages and 22 px on Agent evidence, with distinct section sizes. Source scan color/custom-property coverage is therefore incomplete; six warnings do not imply six real hierarchy failures. Served workspace.css was verified byte-for-byte against the local source SHA-256.

### Browser overlay

Four fresh pages were injected successfully after mutable-script/title preflight: Delivery, Restaurants, Architecture, Madrid. Initial overlay console summaries reported 2, 4, 29, and 5 finding groups respectively. Full follow-up results/logs: browser-overlay.json. Screenshots: audit-overlay-*.png.

The saved follow-up measurement includes the detector's own overlay labels. Its raw totals are 48 element/page groups and 51 rule occurrences:

| Page | Raw groups | Rule counts |
|---|---:|---|
| Delivery | 2 | undersized-ui-text 1; overused-font 1 |
| Restaurants | 5 | undersized-ui-text 1; straggler 2; overused-font 1; text-occlusion 1 |
| Architecture | 36 | undersized-ui-text 10; tiny-text 6; line-length 12; straggler 2; overused-font 1; flat-type-hierarchy 1; text-occlusion 7 |
| Madrid | 5 | undersized-ui-text 3; cramped-padding 1; overused-font 1 |

**Verified false positives / non-defects:**

- Eight text-occlusion findings target injected labels reading “straggler”, “undersized functional te”, or “line length too long”, not app text. Excluding this self-measurement contamination leaves 40 groups / 43 rule occurrences.
- Four overused-font warnings describe the intentional Arial system stack. They establish no functional or accessibility defect and are not counted as prioritized issues.
- Architecture's flat-type-hierarchy finding is advisory: its 14/16/19/20 px roles are separated by weight and a compact title is an explicit project preference. It is not a forced reason to enlarge the heading.
- Madrid's cramped attribution padding is the Leaflet attribution component. It is low-impact legal/source attribution, not a P1 control failure.
- The maps' sub-24 px markers are **not automatically WCAG failures**. W3C explicitly recognizes essential geographic/dense visualization positions, and this app supplies entity/search alternatives. Source links in Architecture have no such spatial justification.
- Small inline attribution links and labeled checkbox inputs were not counted as automatic target failures; target exceptions and effective labels matter.

## Browser evidence and positives

Existing report.json covers 21 page/viewport combinations (1440, 1280, 390): all HTTP 200, no page-level horizontal overflow, no unlabeled visible native control found by that harness, no JavaScript page errors.

Additional browser-audit.json covers all seven fresh pages. Page width checks at 1440, 1280, 390, and 320 px found no document overflow. Mobile menus opened through Enter, exposed six links, closed through Escape, and returned focus to Menu on every page. Sampled sequential controls had visible focus outlines. Health ArrowRight changed the selected tab and revealed its panel. Ctrl+K opened Architecture search with focus in search-input; Escape closed it.

A computed HTML text contrast pass found zero below-threshold candidates against solid composited ancestor backgrounds. It deliberately excluded SVG text, images/gradients, and opacity-complex content; it is not a complete contrast certificate. Chromium's accessibility tree exposed the named Delivery/Restaurant map controls, so nesting them in an SVG role=img did not hide them in this tested engine.

No document-level overflow, unlabeled controls, or page errors were demonstrated. Local navigation load events ranged 23–57 ms; these are unthrottled local timings, not Core Web Vitals or production performance claims. The documentation runtime loaded the pre-rendered diagram SVGs and local reader libraries; no heavy animation failure was observed.

## Limits and run notes

- Initial empty/ready state only. No simulation, paid model calls, destructive actions, or app-source edits were performed. Populated results, failure recovery, and live animation are not covered.
- Browser: headless Chromium via Playwright 1.64.1; emulated viewports, reduced motion for the main browser pass. No physical device, assistive-technology session, zoom/text-resize matrix, Safari/Firefox, or throttled performance test.
- A synthesized touch attempt on Delivery did not change the map viewBox or enter dragging state, so it did not prove successful panning or cancellation recovery. Source inspection shows pointerup cleanup but no pointercancel/lostpointercapture/blur cleanup at web/flow.js:26–28. Treat this as an unresolved gesture check, not a confirmed reproduced P1.
- The shared reduced-motion rule at web/workspace.css:388–395 globally sets animation/transition duration to 0.01 ms. No loss of critical feedback was demonstrated in this initial state; inspect active-run behavior before declaring its alternative adequate.
- Overlay injection and detector execution succeeded in headless pages and screenshots were saved. No claim is made that a user-presented browser tab or overlay was left open.
- Temporary overlay server was started from artifacts on port 8400 and successfully stopped there using live-server stop --keep-inject. No script tags were written into app HTML. The existing app server on 8021 was left untouched.
- Read-only source and browser audits do not replace the application tests. Parent separately reported the baseline suite: 565 passed, one pre-existing Starlette/httpx warning.
- No comparison with Assessment A was used; this assessment remains independent.

Recommended order: /impeccable adapt for Architecture targets; /impeccable harden for map tab order and header scoping; /impeccable typeset for Architecture; /impeccable clarify for Inventory; /impeccable optimize for payload review; finish with /impeccable polish. Re-run the audit after approved changes.

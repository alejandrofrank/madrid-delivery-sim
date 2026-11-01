# Dark-store documentation receipt

Date: 2026-11-02. Scope: ordinary Operate extension of the existing visual world.
This delegated pass used the installed generated documenter definition at
`reference/degraded/documenter.md` and the complete `reference/document.md` spec.
Context loading failed, so existing project context was read directly.

## Outcome and boundary

Updated `.impeccable/surfaces/dark-store.md` and created this receipt. No product
code, PRODUCT.md, DESIGN.md, sidecar or other documents were changed by this pass.
The shared system still describes the extension's identity. Surface choices were
recorded without promoting them into global tokens or rules.

Preserved system SHA-256 values:

- `DESIGN.md`: `0f4687a5becefd706152b7ae71f0754ba8b0c791634e7e36c40b52bf7eb3b5f4`
- `.impeccable/design.json`: `857fc4d554a6f766d1a6ebf4f616844fa18ec8041b2a768edb9a880eaa15884c`

## System comparison

| Area | Incumbent | Finished extension and decision |
| --- | --- | --- |
| Palette | Blue graphite, pale ink, cyan action/selection, semantic outcomes | Same roles. Local literal shades and physical model materials remain surface details; no palette expansion. |
| Typography | IBM Plex Sans/Mono, compact titles, no display tier | Store title 16px, headings 14px, working text 12px, annotations 11px. The 16px heading matches an existing CSS size; its role and raster scene labels stay local. |
| Layout | Working interface near the top, dense evidence, responsive stacking | Compact launch bar, flexible cutaway plus 250px inspector, stacked at 850px. Uncapped inspector keeps disruptions in page flow. |
| Depth/form | Flat ordinary panels, fine rules, restrained corners, map legibility shadows | Flat inspector and panels. Small store-pin shadow serves marker legibility; spatial depth belongs to the modeled store. |
| State/evidence | Color with words, actual IDs, trace access, explicit unavailable evidence | Basket counts, picker ID, stage, decision link, render status and distinct 3D/floor-plan keys accompany physical state. |
| Interaction | Visible focus, reduced motion, native controls | Labeled selectors, canvas keyboard controls, Escape return, focus restoration, lazy models and fallbacks. Environment selection reuses the Anatomy inspector. |

The One Accent Rule, Compact Title Rule and Flat Surface Rule remain shared.
Camera behavior, material colors, local dimensions and heading size do not define
a replacement visual world.

## Evidence checked

Source: `web/store.css`, `web/store-view.js`, `web/store-3d.js`, store markup/asset
references in `web/index.html`, hooks in `web/app.js`, and the environment selection
in `web/agent-anatomy.js` and `web/agent-anatomy.css`. Context: `web/tokens.css`,
PRODUCT.md, DESIGN.md, `.impeccable/design.json`, the surface brief and prior Anatomy
finish receipt. No browser session or new runtime test was run by this pass.

All seven supplied final PNGs were opened and compared with the source. Sizes
below describe full-page images, not the browser viewport height.

| Capture under `.impeccable/review/` | Image size | Evidence |
| --- | --- | --- |
| `dark-store-desktop.png` | 1440 × 1286 | Cutaway and basket together; complete disruption action. |
| `dark-store-mobile.png` | 390 × 2234 | Wrapped controls; stage above inspector; action/footer in flow. |
| `dark-store-user-1916.png` | 1916 × 1374 | Wide stage, fixed-width inspector and inherited Operations shell. |
| `dark-store-laptop.png` | 1280 × 1286 | Complete inspector and disruption action at reviewed laptop width. |
| `dark-store-fallback.png` | 1280 × 1286 | Floor plan, explicit fallback status and corrected worker/unavailable key. |
| `store-environment-desktop.png` | 1440 × 5209 | Dark store selected in the existing Architecture inspector. |
| `store-environment-mobile.png` | 390 × 6496 | Environment field and facts in the established stacked inspector. |

`artifacts/dark-store/browser-checks.json` records `passed: true`, lazy loading,
keyboard, mobile, fallback and delivered checks true, and no errors. Run:
`04cdaaf5-d7ef-444a-9134-63f7e5253099`. This is retained test evidence, not an
independent rerun by the documenter.

`artifacts/dark-store/recording.json` records delivered run
`a07f8e61-ac4a-4246-9d55-42e50d56bd0a`, with reservation, picking, packing, dock,
handoff and delivery frames. `docs/evidence/dark-store.json` explicitly limits
its A2A integration evidence to deterministic local offline operation; it does
not establish live-model quality.

The provided finish-review record says the full review found two material issues:
clipped mobile/laptop disruption controls and an inaccurate fallback legend.
Both were fixed in one batch and scored resolved by the same reviewer. The
**ship** verdict applies to those two fixes. This pass does not expand it into a
new full-surface audit.

## Scoped differences and unrepaired drift

- Local literal shades, the 16px store heading and the pin shadow are surface
  variations. Detector advisories are not converted into shared tokens. Existing
  Anatomy 18px headings and the 16px mobile field also remain local.
- The sidecar still says “Design System: Bakiano operations” while the root system
  and project use madrid-delivery-sim.
- `.impeccable/surfaces/web-flow-html.md` still targets retired `web/flow.html`.
- PRODUCT.md still names the old `mds-ui` worktree and `feat/ui-redesign` branch.
- The documenter found missing PNG origin metadata, outside its write boundary.
  The implementation pass subsequently embedded actual browser-capture origins in
  the changed review PNGs. No pixels changed; the README GIF also carries its
  source in an embedded comment and adjacent recording receipt.

The three metadata drifts predate this extension and remain unchanged because
repair was outside the authorized boundary. No defect or drift above is canonized
as a system rule.

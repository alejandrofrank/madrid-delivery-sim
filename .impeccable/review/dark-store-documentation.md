# Dark-store documentation receipt

Date: 2026-11-02. Scope: ordinary Operate extension and the user's stock/movement
correction in the existing visual world. This delegated pass follows the already
read generated documenter definition at `reference/degraded/documenter.md` and
`reference/document.md`. It did not rerun context loading.

## Outcome and boundary

Updated only `.impeccable/surfaces/dark-store.md` and this receipt. PRODUCT.md,
DESIGN.md, the sidecar, code and other documents are unchanged by this pass.
The shared system still describes the extension's identity. Supported stock,
worker labels/rings/totes and responsive camera fit are local scene behaviors,
not a new visual world or additional shared design tokens.

Preserved system SHA-256 values:

- `DESIGN.md`: `0f4687a5becefd706152b7ae71f0754ba8b0c791634e7e36c40b52bf7eb3b5f4`
- `.impeccable/design.json`: `857fc4d554a6f766d1a6ebf4f616844fa18ec8041b2a768edb9a880eaa15884c`

## System comparison

| Area | Incumbent | Finished extension and decision |
| --- | --- | --- |
| Palette | Blue graphite, pale ink, cyan action/selection, semantic outcomes | Same roles. Local shades, stock materials and state rings remain surface details; no palette expansion. |
| Typography | IBM Plex Sans/Mono, compact titles, no display tier | Store title 16px, headings 14px, working text 12px, annotations/worker buttons 11px. The local heading role and raster location labels do not alter the shared ramp. |
| Layout | Working interface near the top, dense evidence, responsive stacking | Compact launch bar, flexible stage plus 250px inspector, stacked at 850px. Normal-flow inspector keeps disruptions reachable. Fit store uses both projection axes and reapplies overview framing on resize. |
| Depth/form | Flat ordinary panels, fine rules, restrained corners, marker legibility shadows | Inspector and panels stay flat. Scene depth, supported goods and worker totes depict simulated physical roles. |
| State/evidence | Color with words, actual IDs, trace access, explicit unavailable evidence | Basket counts, actual assignment, task/Idle/Offline worker labels, state rings, trace link and separate 3D/floor-plan keys. Stock props represent stocked faces rather than inventory-unit counts. |
| Interaction | Visible focus, reduced motion, native controls | Click or Enter on a worker button tracks that actual worker. Track worker reflects selection; Fit store exits camera tracking. Keyboard orbit, Escape return, lazy loading and fallbacks remain. |

The One Accent Rule, Compact Title Rule and Flat Surface Rule remain shared.
Local camera behavior, physical materials, label dimensions and heading roles do
not establish new system-wide rules. Architecture's Environment selector and
Anatomy treatment are unchanged from the prior documented pass.

## Evidence checked

Re-read `web/store-3d.js`, `web/store-view.js`, `web/store.css` and
`scripts/check_store_view.cjs`, plus current browser and recording receipts. The
previous pass supplied incumbent context from PRODUCT.md, DESIGN.md, the sidecar,
`web/tokens.css`, Operations hooks and Anatomy. No browser session or new runtime
test was run by this documentation pass.

Opened all five refreshed full-page store PNGs, captured from the top, and sampled
journey frames `002.png`, `005.png`, `007.png` and `010.png`. They show changing
worker positions/state, supported goods, picking/packing evidence and the return
to Madrid at handoff. The two previously inspected Anatomy captures are unchanged.
Sizes below describe image dimensions, not browser viewport height.

| Capture under `.impeccable/review/` | Image size | Current evidence |
| --- | --- | --- |
| `dark-store-desktop.png` | 1440 × 1286 | Supported stock, worker identity labels/rings and basket inspector. |
| `dark-store-mobile.png` | 390 × 2234 | Whole-store overview including packing/dock; wrapped controls and normal-flow inspector. |
| `dark-store-user-1916.png` | 1916 × 1374 | Preserved wide overview and fixed-width inspector. |
| `dark-store-laptop.png` | 1280 × 1286 | Complete overview, worker labels and disruption action. |
| `dark-store-fallback.png` | 1280 × 1286 | Floor plan, explicit fallback status and worker/unavailable key. |
| `store-environment-desktop.png` | 1440 × 5209 | Unchanged Architecture environment inspector; inspected in the earlier pass. |
| `store-environment-mobile.png` | 390 × 6496 | Unchanged stacked Environment field/facts; inspected in the earlier pass. |

### Current browser receipt

`artifacts/dark-store/browser-checks.json` records run
`d91633a8-c693-45d8-9366-541145443dfe` with `passed: true` and no errors:

- Lazy loading, keyboard, mobile, fallback and delivered checks pass.
- `workersMoving: true`: the test observes changing coordinates for a working
  simulated worker and activates a worker button using Enter.
- Shelf-support checks cover 120 faces with zero errors and a maximum gap of
  approximately 0.002m, below the 0.01m test tolerance. The checks use model bounds
  and deck intersections; this is geometric support evidence, not a physics test.
- The measured render sample reports 52 draw calls and 351,031 triangles. This is
  one sampled state, not a universal frame-rate or hardware-performance claim.
- The mobile test asserts both projected overview bounds are at most 0.91 at
  390px, alongside overflow and disruption-control checks. It also checks graphics
  context loss, missing-model fallback, actual courier handoff and delivery.

These are retained results from `scripts/check_store_view.cjs`, not a rerun by the
documenter.

### Current journey and review scope

`artifacts/dark-store/recording.json` and `docs/media/store-journey.json` now identify
run `5a34f5b8-2ff1-4197-a3f8-43bbd67f9096`, seed 42 with robot breakdown, delivered.
The adjacent `docs/media/store-journey.gif` records the actual local browser
journey. Its receipt reports 12 frames at 1000ms intervals with endpoint holds,
1080 × 760 output, and a separate render sample of 55 draw calls/351,067 triangles.
The recording includes picking, breakdown/reassignment, packing, dock waiting,
courier handoff and doorstep delivery. It supersedes the old run references in
this receipt; static final idle-worker captures alone do not establish movement.

The supplied fresh full-review record names
`impeccable_stock_motion_finish_reviewer`. That reviewer inspected the original
user image, all five refreshed store captures and frames 002–010, finding the
materials, worker identity/movement, order journey and incumbent system consistent.
One material issue remained: mobile overview fit. After the correction, the same
reviewer's fix-only verdict was **ship**: the complete store, packing area and
dock fit within the 390px margins, wide layouts were preserved, and no remaining
regression was reported. The final verdict verifies that one fix; it is not a
second full review. Earlier disruption/legend corrections remain in the build,
but their older verdict is not the current completion evidence.

This is a local deterministic physical-operation simulation with representative
assets and route interpolation. `docs/evidence/dark-store.json` limits its A2A
integration results to offline operation. Neither the recording nor support
checks prove live-model quality, real-world robot control or rigid-body accuracy.

## Scoped differences and unrepaired drift

- Local colors, worker label/ring treatment, the 16px store heading and pin shadow
  remain surface variations. Existing Anatomy headings/mobile fields stay local.
- The sidecar retains “Design System: Bakiano operations” rather than the current
  madrid-delivery-sim project name.
- `.impeccable/surfaces/web-flow-html.md` targets the retired `web/flow.html`.
- PRODUCT.md names the older `mds-ui` worktree and `feat/ui-redesign` branch.
- The implementation pass embedded actual browser-capture origins in all five
  refreshed store PNGs using Impeccable embed-prompt, identifying recording run
  5a34f5b8-2ff1-4197-a3f8-43bbd67f9096 and no generated pixels. No image pixels
  changed. This documentation pass changed no image metadata. The GIF's adjacent
  recording receipt identifies its actual local-browser source and asset credit.

The three pre-existing metadata drifts remain unchanged because their repair was
outside the write boundary. No defect or drift is canonized as a shared rule.

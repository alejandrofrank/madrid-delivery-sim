# Assessment A — BEFORE design review

Date: 2026-10-29. Independent design assessment for the Impeccable critique. No detector results were read or run. This is Assessment A only; the parent review combines it with the isolated Assessment B.

Targets: web/flow.html (/delivery-lab), web/supply.html (/restaurant-lab), web/lab.html (/lab), web/health.html (/health), web/agent-traces.html (/agent-traces), web/documentation.html (/architecture), web/index.html (/).

Evidence: inspected all 28 saved viewport/desktop/laptop/mobile screenshots under docs/media/before; read the seven pages, shared shell, relevant styles and interaction code; visited all seven routes in a fresh background browser tab at 127.0.0.1:8021. Architecture skip-link focus was visibly verified. No simulations, settings changes or provider calls were made. These captures represent initial empty states, not proof of populated runs, failure handling or successful completion. Keyboard concerns below are source-backed unless explicitly described as verified. No contrast ratios, target measurements, screen-reader compatibility or WCAG conformance are claimed.

The accepted audience and visual brief were supplied to this delegated review, so no additional user interview was performed. All surfaces are Operate except Architecture and Agent evidence, which are Read.

## Specificity verdict

The product content is specific; the overall composition is only partly specific. Fictional city topology, the Madrid street network, stock conservation, leased-event recovery, role boundaries and retained receipts could not be replaced by generic SaaS copy without changing the product. However, repetitive light metric strips, large bordered panels, sparse initial states and inconsistent inspector patterns make the application feel like several engineering demos sharing a masthead.

The desired dark operations console is a useful direction if it increases information density and coherence. A palette swap alone will not solve the reviewer journey. The central design task is to make one reproducible chain visible: run or retained example → addressed event → role/tool decision → state change → outcome/evidence. IBM Plex Sans for interface text and IBM Plex Mono for identifiers, timestamps and numbers would fit that direction; avoid mono for whole explanatory paragraphs. Keep a single interaction accent, with distinct semantic status colors used sparingly.

Overall strengths to preserve:

- Compact descriptive titles and working controls near the top; no decorative hero or inflated claims.
- Unusually honest evidence boundaries: local rules, optional cloud calls, synthetic data, provenance, unknown cost and missing measurements are generally disclosed.
- Inspectable architecture, semantic controls, native disclosures, evidence downloads and explicit distinctions between next-run configuration and retained execution.

No P0 blocker was established in this read-only assessment.

## Nielsen heuristic matrix

Scores are design judgments from 0 (absent/broken) to 4 (excellent), not measured accessibility results. All ten apply: even read-only evidence pages need safe navigation, accurate state interpretation and recovery from unavailable evidence. H5 includes preventing mistaken interpretation or accidental operating choices.

| Page | H1 Status | H2 World match | H3 Control | H4 Consistency | H5 Prevention | H6 Recognition | H7 Efficiency | H8 Minimalism | H9 Recovery | H10 Help | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Delivery | 3 | 3 | 2 | 2 | 3 | 2 | 2 | 2 | 2 | 2 | 23/40 |
| Restaurants | 3 | 3 | 2 | 3 | 3 | 2 | 2 | 2 | 3 | 2 | 25/40 |
| Inventory | 2 | 3 | 2 | 3 | 3 | 2 | 2 | 2 | 2 | 2 | 23/40 |
| Health & evaluations | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 2 | 29/40 |
| Agent evidence | 2 | 1 | 3 | 2 | 3 | 1 | 1 | 2 | 1 | 1 | 17/40 |
| Architecture | 3 | 3 | 4 | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 31/40 |
| Madrid baseline | 3 | 3 | 2 | 2 | 3 | 2 | 2 | 2 | 2 | 2 | 23/40 |

Architecture and Health provide good foundations. The operating pages require significant hierarchy and consistency work. Agent evidence needs a clearer entry and empty-state recovery path.

## Delivery — web/flow.html

Strengths: the map is clearly this product, with customer/shop/courier entities and route semantics; Start simulation is prominent, and the rules-only disclosure avoids implying an LLM is reasoning; an inspector and run evidence already exist.

1. **P1 — The reviewer must hunt for the proof.** Five tall empty metrics, a large map and the watch panel precede the collapsed Run evidence section. At laptop height the actual order/decision chain is below the first viewport. Put a compact event/decision list next to the map, with the selected item feeding a shared inspector. Make run evidence a primary view and provide a clearly labeled retained example when available.
2. **P1 — View controls behave unlike the tabs they resemble.** The Overview/Orders/Fleet/Stores controls update the lower board and scroll toward it (flow.js around 190), while the main map remains. The active-looking top control does not describe the full visible workspace. Either make these true workspace views or move the board-specific switch into the board, maintaining clear selection and focus.
3. **P2 — Too many peer controls before the task.** Help, status, start, configure, playback and two named agents share one toolbar; the same two agents reappear under Duty team. Keep run state/start/playback together, put configuration in a secondary action, and move agent shortcuts into the relevant inspector. Human names should follow the role, not lead it.
4. **P2 — Keyboard route through the map is costly.** Each customer and shop is individually tabbable; the initial city has 128 households and 12 shops. Customer key activation handles Enter but not Space, unlike shops (flow.js around 154 versus 42). Provide a searchable/list alternative before the map and a single map entry with deliberate internal navigation; standardize button activation and preserve focus during redraws.
5. **P2 — Mobile delays useful inspection.** The two-column metric stack occupies most of the opening screen; the map precedes the order book and inspector in a long vertical stream. Use a compact status summary and a map/list switch, keeping the selected order and inspection action adjacent. Map labels are visually tiny in the captures; let search and lists carry exact identification.

Cognitive load: high, five checklist concerns—single focus, chunking, hierarchy, minimal choices and working memory. Explicit >4 choice sets: six workspace links, five playback options, and at least six actionable toolbar controls. Emotional journey: immediate confidence from a familiar map, followed by an empty-state valley when the promised decision evidence is hidden below it.

## Restaurants — web/supply.html

Strengths: next-run definition and run inspection are explicitly separated; limits, local/offline execution and shared-template scope are explained; tabs have arrow/Home/End handling, and source includes draft-loss protection and retry for order history.

1. **P1 — Editing dominates a reviewer task.** A preselected Pizza Kitchen opens a long editable definition before any execution evidence. On mobile the complete entity/agent/budget form is expanded before Run evidence. Default to a concise entity summary and read-only inspection/empty-run guidance, with Edit blueprint as a deliberate secondary action. Group business settings, agent policy and budgets into separate disclosures.
2. **P1 — Evidence is spatially separated from the entity.** The map and scrolling inspector consume a large region above Run evidence. The operator must keep selected entity, run state and evidence filter in memory. Put orders/events beside the inspector or make the evidence pane a stable workspace region with persistent run/entity context.
3. **P1 — The map creates a long keyboard sequence.** Source renders all 138 entities as tabindex=0 groups before the entity selector; the live accessibility tree confirms the full entity inventory. Move the select/search shortcut before the map in focus order and avoid hundreds of sequential stops. Retain existing Enter/Space support.
4. **P2 — Configuration language exposes internal representations too early.** Grid node, recipe IDs, opening_stock JSON, SOUL, engine, budgets and memory format are all present in the initial definition. Preserve this technical depth, but use a summary of purpose/effect first and advanced editors on demand. Show which changes affect one entity versus the shared role beside Save.
5. **P2 — Uneven space and nested scrolling dilute density.** At desktop/laptop the editor has its own scrollbar and the map region leaves substantial unused space; on mobile the editor becomes a very long page. Use a bounded map and a coherent inspector with a compact sticky heading, clear edit state, and grouped fields.

Cognitive load: high, five concerns—single focus, chunking, one thing at a time, minimal choices and progressive disclosure. Visible/available choice sets include six navigation destinations, five memory modes, 138 entities and many simultaneous editable fields. Emotional journey: Start is clear, but the initial long editor suggests setup work is required before the reviewer can see evidence.

## Inventory — web/lab.html

Strengths: one bounded scenario with a precise explanation; synthetic/offline limitations are explicit; checkpoints, conservation evidence and recovery tables have the right conceptual ingredients.

1. **P1 — The central blank map resembles missing content.** The initial state shows a large gray SVG region and an enabled Store selector with no choices, while instructions say to select a store. Say plainly that stores and results appear after the scenario starts; disable unavailable selectors and replace the empty region with concise scenario guidance rather than a large blank placeholder.
2. **P1 — The layout gives geography more weight than the experiment.** Basket outcomes, decision evidence and crash recovery are below the map/stock panels. The reviewer needs to see contention → rollback → lease expiry → retry → replenishment. Put that timeline and assertion summary first, with geography as secondary context.
3. **P2 — Dense explanation lacks visual sequence.** The scenario paragraph carries several events and two arrival times in prose. Use a short ordered scenario strip and label expected versus observed values, without fabricating results before execution.
4. **P2 — Empty-state controls look ready for live inspection.** Live/final state, simulation minute 0, empty role disclosures and blank tables imply an inspectable run before one exists. Introduce an explicit No run state, then enable checkpoints and evidence once a run is loaded. Keep the run/seed visible beside all evidence.

Cognitive load: moderate-to-high; hierarchy, progressive disclosure, working-memory and shared minimal-choice concerns. The intrinsic experiment is complex, but the primary action itself has only catalogue, seed and Start. Emotional journey: clear experiment promise → blank area and empty selectors → uncertainty whether anything is broken. Keyboard red flag: do not add a new map-only flow; preserve the source's Store selector and Enter/Space handling for store markers.

## Health & evaluations — web/health.html

Strengths: missing evidence is not falsely presented as passing; local service health is separated from business outcomes; filters, explicit categories, provenance, history and tab keyboard handling support genuine inspection.

1. **P1 — The first-time reviewer cannot complete the evidence path from this screen.** The only acquisition path is a command copied for external execution, while Refresh can only reread receipts. Preserve read-only behavior, but offer a concise setup explanation and a link to a real retained receipt when available, clearly marked historical. State what Refresh does beside the empty state.
2. **P2 — Zero and unmeasured compete.** In the initial summary, Capability regressions reads 0 / 6 while neighboring tiles say Not recorded and Not measured. A quick scan may read this as six failures. Label the count's exact meaning or show Not measured until a qualifying receipt exists; retain category-overlap context in the detail view.
3. **P2 — Empty catalogue controls add noise.** Search, result/kind filters, an All tests 0/0 category, count text and a large empty area appear despite there being no cases. Collapse these into a focused receipt state until cases are present, while leaving evidence-source and collection guidance available.
4. **P2 — Mobile tab overflow hides a destination.** The saved mobile capture clips the Run history label at the right edge. Make horizontal overflow perceptible or provide an accessible compact view selector; ensure selected tabs scroll into view on keyboard activation.

Cognitive load: moderate, two primary concerns—empty-state hierarchy and minimal choices. Six global navigation options plus the four local views need clearer grouping, but local filters are otherwise well chunked. Emotional journey: credible honesty, then a dead end for reviewers without a terminal. No claim is made that evidence collection should become a browser write action.

## Agent evidence — web/agent-traces.html

Strengths: retained evidence is read-only and does not trigger model calls; the copy distinguishes token-based cost, reservations and unreconciled billing; source retains prior route evidence on a failed refresh.

1. **P1 — Three dead-end empty sections.** Tool contracts, Jev-first comparison and SOUL comparison say no evidence exists, with only Refresh. Explain what each comparison proves, why it is missing and how to obtain or locate a real retained artifact. Link to the relevant restaurant workflow and documentation; do not invent a successful example.
2. **P1 — Jargon appears before purpose.** Jev and SOUL are unexplained in the main heading sequence. Lead with task language such as routing comparison and decision preferences, then identify the underlying provider/configuration term. Add a one-sentence interpretation guide before metrics or raw traces.
3. **P1 — The page is absent from the global information architecture.** workspace.js lists six routes and matches current state by exact URL; /agent-traces therefore has no selected navigation destination, although the body uses the restaurant page marker. Add a visible Evidence destination or a clear Restaurants → Agent evidence breadcrumb/back path and consistent active state.
4. **P2 — A scoped CSS issue breaks the shared mobile shell.** The mobile rule in agent-traces.css targets every header, including the shared workspace header, and the screenshot shows the brand centered above a separate Menu row. Scope page-header styles to main content and preserve the common shell layout.
5. **P2 — Failure wording can conceal an unavailable service.** loadModelComparison maps every non-OK response to No live SOUL comparison recorded yet, unlike the route loader's distinction between 404 and unavailable. Present missing artifact, failed retrieval and retained historical data as separate states, with last successful refresh and actionable retry guidance.

Cognitive load: moderate, three concerns—hierarchy, working-memory/jargon and minimal navigation choices. The page is sparse, but sparseness is not clarity: there is no useful next decision. Emotional journey: anticipation of AI proof → three absences → uncertainty about whether the feature works. Keyboard first-time red flag: the route lacks positional context even though the only main action is a native Refresh button.

## Architecture — web/documentation.html

Strengths: the best reviewer foundation—component boundaries, source links and evidence links are concrete; search, current chapter, table of contents and next chapter support navigation; native dialogs, copy/print/open-SVG options and a visibly working skip link improve control.

1. **P1 — Diagrams hide the relationships they are meant to explain.** Saved desktop/laptop/mobile captures crop wide system and sequence diagrams inside scroll containers; optional cloud boundaries or downstream actors can be outside the visible frame. Default to a fitted overview with readable expand affordance, then let reviewers zoom for detail. A small textual list of actors/boundaries can preserve comprehension on mobile.
2. **P2 — Several navigation systems compete.** Global workspaces, chapter sidebar, on-page links, component index and pagination create simultaneous choices. The Agent engineering group alone has five chapter links. Retain search and clear chapter order, but reduce peripheral emphasis and offer a short reviewer reading path distinct from the complete reference.
3. **P2 — The overview asks for component selection before showing the whole system.** The first viewport opens on Scoped role workers details in a large inspector; the overall boundary diagram appears much later. Lead with a compact system boundary overview and one recommended evidence path, then offer the component explorer for detail.
4. **P2 — Dense caveats and metadata interrupt the reading hierarchy.** Review date, status, reading time, Markdown, local/cloud disclaimers and evidence cross-links surround the opening content. Preserve every truthful distinction, but consolidate source/freshness metadata and put caveats nearest the claim they qualify.

Cognitive load: moderate, three concerns—single focus, chunking and minimal choices. This is organized reference material, so the issue is competing navigation emphasis, not the existence of many chapters. Emotional journey: credible technical substance; the valley is diagram panning and repeated context switching before the reader gets the whole mechanism. Keyboard red flag: diagram scroll regions and long navigation should be tested with keyboard and at 200% zoom; this assessment does not claim those flows fail.

## Madrid baseline — web/index.html

Strengths: authentic locally cached Madrid road geometry; explicit map exploration mode with Escape exit avoids trapping normal page scroll; separate fleet, decisions, service and ledger concepts support operational use.

1. **P1 — The baseline's relationship to Delivery is unclear.** Two navigation destinations both describe dispatch and couriers, but this page does not quickly explain the street-network baseline's purpose versus the fictional-grid experiment. Add one concise scope line and link to the comparison or architecture boundary; reviewers should know which question each workspace answers.
2. **P1 — Map and empty inspector dominate the proof.** Six large metrics, a tall map and a tall empty fleet pane push the ledger below the working viewport. Compact the no-run summary and make recent/selected order decisions visible next to a bounded map. Collapse idle inspector space instead of reserving its full populated height.
3. **P2 — The top does not disclose the execution mode as clearly as Delivery.** The footer says LLM customer service while the visible controls expose only seed/playback and the KPI reads zero usage. Bring the actual configured policy/provider mode and charge boundary near Start day, using truthful configuration state rather than suggesting all runs call a model.
4. **P2 — Inspector tabs lack the shared keyboard contract.** app.js updates aria-selected and panel visibility on click but has no arrow/Home/End handler or roving tabindex for these tabs. Reuse the working restaurant/health tab behavior so the same pattern behaves consistently across workspaces.
5. **P2 — Failed-run recovery sends users away without a concrete path.** Source reports state preserved; resume from the CLI, without a command or link at that point. Provide a copyable applicable recovery command or documentation link and keep the failed run ID visible. This is source-reviewed behavior, not a failure state reproduced in this assessment.

Cognitive load: high, four concerns—hierarchy, chunking, minimal choices and working memory across map/inspector/ledger. Six KPIs and six global destinations are the main >4 groups. Emotional journey: strong geographic credibility, followed by an empty operational shell until a run is started. Mobile red flag: the saved capture places a large empty inspector before a horizontally scrolling ledger whose no-run message is clipped.

## Cross-page redesign priorities

1. Establish one shared compact shell, active navigation, run context, status language, inspector, tab behavior and empty-state contract. Include Agent evidence in the route model. Keep errors and measured status distinct from the interaction accent.
2. Optimize the first reviewer minute: a visible factual scope sentence, one primary run/open-evidence action, compact run status, and a readable outcome/decision chain. Where no evidence exists, explain the prerequisite and next action rather than occupying the screen with empty charts or metrics.
3. Treat maps as operational context. Keep entity search/list navigation available before maps, reduce long tab sequences, and tie selected entity/order to the decision evidence without a memory bridge.
4. Use progressive disclosure for editors, raw JSON, budget detail and provenance. Technical depth should remain available, but the default view should explain the relevant result before exposing its payload.
5. Validate the redesign in populated, loading, unavailable, stale, running, completed and failed states at laptop/mobile widths. Specifically verify keyboard selection and focus preservation through polling; contrast/zoom/reflow; responsive tabs; map alternatives; and no-data versus numeric zero. These are future verification requirements, not outcomes proven by the BEFORE captures.

Questions skipped: this delegated assessment is an input to the parent synthesis; the user has already supplied audience and visual direction. Useful synthesis questions are which retained run best demonstrates the event-to-outcome chain, whether agent evidence should be a global destination or a restaurant subview, and which comparison most clearly distinguishes the two delivery workspaces.

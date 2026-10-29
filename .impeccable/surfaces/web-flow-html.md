---
version: 1
slug: "web-flow-html"
primary_target: "web/flow.html"
related_targets: ["web/supply.html","web/lab.html","web/health.html","web/agent-traces.html","web/documentation.html","web/index.html"]
---

# Delivery and agent operations
Mode: Operate. Related architecture route: Read.
Audience: technical reviewers first, operators second.
Job: see the full network and understand what each agent is doing; inspect the evidence without leaving context.
Constraints: backend behavior stays intact; runtime evidence is never fabricated.

## Direction contract
THESIS: Agents are the protagonist; their shared city remains visible beside them.
OWN-WORLD: Graphite surfaces, teal selection, restrained state colors, IBM Plex Sans and Mono, fine rules and dense readable rows.
STORY: Start a local run, scan the roster, select an agent, follow its route, inspect its decision trace.
FIRST VIEWPORT: A slim shared navigation, compact title and controls, four metrics, a left agent roster beside a substantial right map, then selected-agent evidence and orders. Both columns remain visible at laptop widths.
FORM: User-directed combination of comps A and B; agent-led console with map parity. seed:bbdc658d74a6c0b8. The illustrative comp's invented values and geographic labels are replaced with actual simulator data.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

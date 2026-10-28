# Local architecture documentation website

Open **http://localhost:8010/architecture** with the local stack running. This is
part of the existing FastAPI application, not a separate hosted product. It does
not start infrastructure, invoke a model or read the simulation database. The
existing `/docs` API reference remains available.

## Reading and inspection

Nineteen numbered chapters cover architecture decisions, the agent factory,
authenticated scope, SOUL, tools, memory, queue transactions, city workflows,
declared GCP resources, enterprise alternatives, operations and evaluations.
The structure follows Scrapmarket's topic-oriented engineering documentation:
examples, choices, limits and inspectable sources. This site has its own content
and shares no deployment or Terraform state with Scrapmarket.

The overview's component explorer shows responsibilities, inputs, outputs, trust
boundaries and implementation links. Reviewed D2 sources become local SVG
diagrams with native text, ELK orthogonal routing, expand/zoom controls and source
disclosures. Mermaid fences remain a readable repository reference. Search matches all
chapter titles and text in the browser; Ctrl/Cmd+K opens it. Direct chapter and
section links, back/forward navigation, a page outline, previous/next chapters,
Markdown inspection, code copy and chapter printing support longer reviews.
Mobile readers use the Topics disclosure; tables and diagrams scroll within
their containers.

Reference review dates describe source review, not live service health. Historical
receipts retain their original dates. Open `/health` for current local evidence,
and explicitly run the GCP status command for current deployment state. Merely
reading these pages performs neither a GCP status query nor paid inference.

## Source and security boundary

`config/documentation.json` is the committed catalogue. Bodies are read from the
same repository Markdown files used on GitHub; there is no second manually copied
chapter body. `GET /api/documentation` returns only these chapters and public
source names. `GET /api/documentation/source?path=...` accepts exact membership in
that catalogue. It denies arbitrary paths, credentials, local datasets, private
variables/state/plans, oversized files, symlinks and resolved-path escapes. No
source endpoint executes code. This read-only reference is part of the trusted
local operator application; it is not an enterprise authentication layer.

The source viewer returns text and inserts it with `textContent`. Markdown output
is sanitized with DOMPurify. Raw forms, scripts, styles and images are disabled in
chapter content. Diagrams are local image assets, with no active node callbacks,
scripts or HTML labels. The offline diagram checker rejects external resources.
Relative links resolve to another chapter, an explicitly catalogued source, or a
manual link to the private GitHub repository. Only the viewer can open the latter.
The UI does not fetch those external references or send search terms to them.

Browser bundles are checked in under `web/vendor/documentation/`, with exact npm
versions, SHA512 package integrity, local SHA256 hashes and license notices.
The current reader uses Marked and DOMPurify; the older pinned Mermaid bundle is
retained for provenance but is no longer loaded. D2 is a checksum-pinned development
tool and is not needed in the application image. No external chunks, CDN,
fonts or tile services are required. Vendoring does not replace dependency review;
review pins and licenses when updating them.

## Updating and verifying

Edit the relevant Markdown file. Add a topic's metadata to the catalogue when
adding a chapter. Refresh the fixed source list, review the change and check it:

```bash
python3 scripts/check_documentation.py --update
python3 scripts/check_documentation.py
python3 scripts/vendor_documentation.py --check
node --check web/documentation.js
python3 scripts/render_documentation_diagrams.py --check
```

Updating source names happens only in the authoring script, never from a browser
request. To rebuild the pinned vendor assets from npm, run
`python3 scripts/vendor_documentation.py`; it checks registry metadata and
tarball integrity before writing the allowlisted assets. Normal checks with
`--check` are offline. Python's standard library is sufficient for both scripts.

The Docker image explicitly copies public documentation and Terraform source;
`.dockerignore` excludes secrets and private state. Rebuild the app after source
changes. `tests/test_documentation.py` verifies catalogue loading without database
access, every source in the image, denial cases and bundle integrity. It appears
under Operator interface in `/health`. Browser verification additionally checks
navigation, search, diagram rendering/expansion, the component inspector, source
viewing and console errors. The full local health battery makes no model calls.

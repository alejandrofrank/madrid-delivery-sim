# Documentation diagrams

The architecture reader uses locally built SVG assets. D2 **0.9.0** owns graph
placement and edge routing through **ELK's layered layout**; the four interaction
diagrams use D2's sequence layout. No coordinates or connector paths are drawn
by the application. Labels are native SVG `<text>` / `<tspan>` elements, with
embedded fonts and no HTML `foreignObject` labels.

The reader loads SVGs as images, so its Markdown sanitization cannot remove
diagram text or typography. Expand opens the same asset at a readable minimum
size with pan and zoom; Fit explicitly shows the whole diagram. The cloud and
durable-state views use D2's automatic two-column composition, with ELK routing
inside each boundary or phase and a horizontal connection between them.
Diagrams scroll within their panels to keep small labels readable.
The eight views share white nodes, pale neutral boundaries, graphite connectors
and native mono text for event names. Numbered phases describe execution order;
colour is reserved for an actual warning or outcome. Layered graphs use 1px
connectors; sequence lifelines retain D2's dashed defaults. Node text is 18px
and message labels are 16px in the source SVG. Long sequences retain vertical
scrolling rather than shrinking every message to fit one viewport.
The D2 source, shared styles and original Markdown reference are inspectable
under every diagram. All viewing works without a CDN or renderer service.

## Rebuild

From the repository root, use Bash:

```bash
python3 scripts/render_documentation_diagrams.py --install
python3 scripts/render_documentation_diagrams.py --check
```

`--install` downloads the official pinned D2 development binary into ignored
`artifacts/.cache/d2/0.9.0/`, verifies the release asset's SHA256 digest and
extracts only the executable. It supports Linux, macOS and Windows. The binary
is never part of the application image or repository. After installation,
rebuilds need no network:

```bash
python3 scripts/render_documentation_diagrams.py
```

Alternatively pass `--d2 /path/to/d2`; the version must match the pinned version.
`--check` needs only Python's standard library and does not execute D2, access a
database or make a network request. It verifies every chapter fence is mapped,
source and reference fingerprints match, SVG checksums match, native text
labels exist, and SVGs contain no scripts, external images or HTML labels.
Generated artifacts and sources are committed together.

## Ownership and mapping

`catalogue.json` maps a chapter ID and zero-based Mermaid fence index to a D2
source and SVG. The Markdown fences remain readable repository references;
the D2 files are their reviewed presentation counterparts. Update both when
the architecture changes, then rebuild. A mismatching reference causes the
reader to show the source and a rebuild notice instead of a stale diagram.

| Chapter | Fence | D2 source / generated SVG |
| --- | --- | --- |
| `overview` | 0 | `system-boundary` |
| `overview` | 1 | `meal-handoffs` |
| `agent-implementation` | 0 | `agent-transaction` |
| `restaurant-supply` | 0 | `restaurant-supply` |
| `delivery-flow` | 0 | `delivery-queue` |
| `gcp-components` | 0 | `gcp-components` |
| `durable-inference` | 0 | `durable-inference` |
| `fleet-recovery` | 0 | `fleet-recovery` |

Outputs live in `web/diagrams/`: SVGs, published D2 source copies, shared styles
and `manifest.json`. The manifest includes SHA256 asset checksums, exact source
and reference text, dimensions, and a native text-label inventory for tests.
It has no time-dependent build stamp, so identical inputs produce stable files.

The lifecycle diagram distinguishes safe prepared retries, saved-result reuse
and unknown dispatch outcomes. Provider I/O occurs after the database
connection closes. Fresh validation gates the atomic effects, memory, outbox
and ACK transaction. Denied and unknown outcomes commit their denied review
through that same atomic transaction, with no retry or reassignment; an
uncertain provider dispatch is never resent automatically.

Reference: [D2 ELK layout](https://d2lang.com/tour/elk/),
[D2 sequence diagrams](https://d2lang.com/tour/sequence-diagrams/),
[pinned official release](https://github.com/d2lang/d2/releases/tag/v0.9.0).

# Shelf to doorstep

Open Operations and choose **Start store demo**. One seeded synthetic order is
reserved from the catalogue, picked from physical shelves, packed, carried to the
loading dock, then delivered by a Madrid courier. **Picker breakdown** adds a
failure while the basket is in progress. The 60-second playback setting is a
target; a slower machine will take longer rather than skip physical steps.

The default view is an elevated cutaway. Cyan marks the selected order's shelf
faces and the current planned route. Green items are already in the basket.
Amber blocks show inaccessible cells. Use **Track picker** for a closer camera,
**Fit store** for the whole layout, or **Back to Madrid** to leave. **Follow this
order** returns to the city after physical courier collection; it ends at delivery
or cancellation. Escape leaves the store. On a focused 3D view, arrows orbit and
plus/minus zoom. All order facts and controls remain available without WebGL.

## Two environments, one order

`Environment` defines clock reads, ordered events, state reads and transactional
advance effects. `MadridCity` contains the original city physics; city-only runs
retain their minute tick and behavior. `DarkStore` shares its run ID and clock,
advances physical movement every ten simulated seconds, and records store frames.

`StoreLayoutConfig` generates four aisles, eight bays, three shelf levels, a cold
zone, a packing station and a loading dock by default. The sixty supermarket
catalogue products have two distinct pick faces each, including cold storage for
dairy, protein and frozen items. Opening physical stock is 24 units per SKU;
listing a product or expecting a truck never creates sellable stock.

The renderer uses metre coordinates from this layout, not a separate visual
layout. Pick routes use deterministic shortest aisle paths, avoid rack cells and
blocked cells, and pick ambient goods before cold goods. This is a discrete
logistics simulation; it is not collision-accurate robotics physics. Worker
traffic does not yet reserve space against other workers.

## Agent decisions and bounded effects

The inventory role reuses `InventoryPolicy`, its typed reservation outcomes and
memory validation. A bound adapter permits only the selected run, store and
order. The fulfillment role adds a dark-store tool profile: route, pick, pack,
restock and handoff. Its policy observes available faces, workers and routes.
It does not branch on incident names. Both roles expose Agent Cards and execute
through the same A2A service used by the in-process test transport.

A route is only a plan. The environment emits an arrival event; a scoped tool
then checks reservation, quantity, position and elapsed time before changing
stock. A replacement picker must reach a broken robot before taking its basket.
The forklift first visits the dock and moves only confirmed backstock. Pack and
handoff tools refuse incomplete baskets. The dispatcher cannot assign an order
until the dock is ready.

Each decision is in the existing event/decision trail, with the same order ID.
New spans describe tools and environment advances; the observability system is
otherwise unchanged. The local policies use no model calls. The optional GCP
configuration includes separate inventory and fulfillment identities with
audience-bound A2A tokens; no cloud resources are started by this feature.

Store services use trusted database connections and bound application tools.
They do not claim the legacy inventory lab's separate SQL-login isolation.
Manifest profiles limit per-turn tools, per-run work, memory size and TTL.
Stock is conserved through cancellation, receipts, retries and disruptions.

## Store disruptions

| Event | Physical change | Decision left to the policy |
| --- | --- | --- |
| Blocked aisle | Removes cells from the walk graph | Choose another face/path, or wait |
| Shelf out of stock | Removes a pick face; observed units move to unlocated backstock | Pick another face; forklift may restock a reachable face |
| Robot breakdown | Stops a robot at its last safe node | Recover its basket with an available picker |
| Late restock truck | Delays an expected receipt | Wait for actual receipt; never promise expected stock |

The existing Chaos API accepts these event kinds, `target` (a store ID or
`auto`) and optional `resource` (aisle, shelf, robot or shipment ID).
Explicit resources require an explicit store. Scenarios can provide an event
list; `random_store_events` uses a separate seeded stream so existing city
random sequences remain unchanged. Auto targets resolve from current store
load. Store decisions and events remain correlated to their order.

## API and recording

`POST /api/runs` accepts an optional `dark_store` configuration. Omit it for
the unchanged city simulation. `GET /api/runs/{run}/stores` returns current
layout, stock, worker routes, baskets and live load. Add `?at=120` to read the
last recorded frame at or before 120 simulated seconds. This endpoint is read
only and uses a consistent database snapshot.

For a short recording, submit the checked-in demo request:

```bash
curl -fsS http://localhost:8010/api/stores/demo \
  -H 'Content-Type: application/json' \
  --data-binary @config/scenarios/store-demo.json
```

The UI's demo button makes the same request, selects `DS-0001`, and follows it.
An optional `chaos: true` inserts a robot failure. These are synthetic orders,
not real shoppers or customer communications. Live deployments retain global
authentication on all endpoints; public replay exposes no write APIs.

## Evidence and browser budget

`evals/store/scenarios.json` runs all four incidents twice over the official
A2A SDK. The gate recomputes pass criteria: delivered on time, complete basket,
dock recovery within 900 seconds, conserved stock, no orphan reservations, no
dead events, no paid calls, and identical normalized outcomes across repeats.
Robot recovery must be observed, and delayed trucks cannot be received early.

The seven NVIDIA SimReady models converted by
[codepawl](https://huggingface.co/datasets/codepawl/simready-glb) are
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Derivatives simplify
geometry, resize textures to 256 px, and use WebP and Meshopt compression.
The pinned source revision, original links, modifications and hashes are in
`web/vendor/simready/manifest.json`. The models total 920,992 bytes; models plus
the local Three.js loader stay below 4 MB. They load only when opening a store.
Failed models use boxes; failed WebGL uses the floor plan. Rendering is capped
at 30 fps and pixel ratio 1.5, pauses in hidden views, and disposes its renderer
when closed. The original model geometry is visual evidence, not the simulation's
physical collision or navigation authority.

## Source index

- [Environment contract](../src/delivery/environment.py)
- [Madrid city adapter](../src/delivery/madrid_city.py)
- [Store layout and navigation](../src/delivery/store_layout.py)
- [Physical store state and effects](../src/delivery/dark_store.py)
- [Scoped store tools](../src/delivery/store_tools.py)
- [Inventory adapter and fulfillment policy](../src/delivery/store_agents.py)
- [Measured recovery runner](../src/delivery/store_evals.py)
- [Frozen store scenarios](../evals/store/scenarios.json)
- [Asset provenance and byte budget](../web/vendor/simready/manifest.json)

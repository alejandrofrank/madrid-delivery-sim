# Google ADK restaurant agent

This slice uses **Google ADK 2.13.0** and its real `LlmAgent`, `Runner`, function
tools, model callbacks and session service. The default model is explicitly a
scripted offline `BaseLlm` double. A native Vertex/Gemini adapter is implemented
behind an explicit deployment gate and monetary budget; it is disabled by default
and was exercised explicitly with both SOULs on Vertex on 2026-10-29. There is no automatic
paid-provider fallback. Offline results demonstrate integration
and enforcement; they do not measure a language model's understanding of SOUL.

## Reusable building blocks

Source map: [template contract](../src/delivery/adk_contracts.py),
[ADK turn and tools](../src/delivery/adk_restaurant.py),
[native model adapter](../src/delivery/adk_models.py),
[offline model double](../src/delivery/adk_offline.py),
[scoped turn/transaction SQL](../sql/migrations/017_adk_restaurant.sql),
[Vertex admission SQL](../sql/migrations/018_adk_vertex_admission.sql), and
[executable checks](../tests/test_adk_restaurant.py).
The editable [role prompt](../config/agents/restaurant-adk/PROMPT.md),
[speed SOUL](../config/agents/restaurant-adk/SOUL-speed.md) and
[cost SOUL](../config/agents/restaurant-adk/SOUL-cost.md) are resolved into the
frozen restaurant definition.

`RestaurantBrain` is the validated template contract. A restaurant instance
combines that contract with its existing entity, authenticated database identity,
role limits, role prompt and SOUL. The operator can edit the prompt/SOUL and bounded
budgets in `/restaurant-lab`, through its revision-checked blueprint endpoint, or
in advanced agent JSON. Choose **Override for this entity** or **Edit shared role
template**, then **Google ADK · offline model fixture**. The two Load profile
prompts options initialize Elena (shortest quoted lead time) and Mateo (lowest
quoted procurement fee). Saving a blueprint affects new runs, never an existing
agent's frozen definition.

`config/agents/restaurant-adk/PROMPT.md` supplies the reusable role prompt;
`SOUL-speed.md` and `SOUL-cost.md` supply the initial profiles. The template endpoint
`GET /api/supply/agent-templates` exposes resolved, approved local templates. No
configuration field names an executable module, arbitrary URL or credential.
Tool references can remove supported capabilities; extending authority requires
reviewed code, permissions and tests. A template cannot grant another role's tools.

Effective instructions combine a fixed platform boundary, the editable role prompt
and editable SOUL. A callable instruction provider preserves literal braces in
operator text. ADK initially receives only the leased event identifier; the actual
order and event facts come from scoped SQL tools. Forged caller-side event bodies
cannot enter model context or select a different order. Every turn gets a fresh, private
in-memory ADK session. Cross-event working memory comes from the existing typed
Postgres recall functions; broad session history is not shared between agents.

## Granular tools

| ADK function | Capability | Effect |
| --- | --- | --- |
| `read_order` | `restaurant.order` | Current order, event, deadline and canonical alternative |
| `read_pantry` | `restaurant.pantry` | This kitchen's physical stock and reservations |
| `read_recipe` | `restaurant.recipe` | This meal's frozen recipe and units |
| `find_suppliers` | `restaurant.suppliers` | Open markets' public fees and estimated lead times; no private stock |
| `recall_order_memory` | `memory.read` | Current-order, restaurant-owned, unexpired typed observations |
| `search_ingredients` | `supply.search` (optional) | Scoped ingredient relevance; separate local/Jev provider and budget |
| `request_missing_ingredients` | `restaurant.request_supply` | Stage a supplier choice; SQL calculates shortages and queues requests |
| `confirm_order` | `restaurant.confirm` | Stage pantry-only acceptance; a shortage invalidates the proposal |
| `receive_ingredient` | `restaurant.receive` | Stage receipt of the ingredient addressed by this event |
| `prepare_meal` | `restaurant.cook` | Stage cooking after arrival, consent and timing checks |
| `offer_substitution` | `restaurant.offer` | Stage the safe alternative; queue the household's approval request |
| `decline_order` | `restaurant.decline` | Stage a bounded reason and reservation release |
| `finish_decision` | `restaurant.finish` | Seal one staged action with a brief explanation |

The model chooses which tools to use and which supplier/action to propose. The
shared runtime does not choose the sourcing strategy. The offline model double
implements the two documented fixture strategies to exercise that interface;
it should be replaced with an evaluated generative model for intelligence tests.

Quotes are synthetic entity settings. `procurement_fee_cents` is editable entity
data. Lead time is an estimate derived from grid distance and supplier delay,
not a guaranteed route ETA or stock promise. Supermarket workers continue using
their deterministic policy and reply only through queued messages.

## Transaction and recovery boundaries

1. Claim the addressed event and commit its ordinary tool/event budget ticket.
2. Begin a durable restaurant turn containing the frozen definition hash, canonical
   event payload and scoped business snapshot. A nonce fences the original owner.
3. Before **each** ADK model call, save a request hash and conservative token
   reservation. Close the SQL connection before model execution. Save the model
   completion receipt separately. No provider/model retries are automatic.
4. Read tools each use a short authenticated transaction and retain a receipt.
   Write tools only stage a proposal; they make no stock changes or agent calls.
5. Save the completed plan durably. The final effects transaction rechecks the
   current business snapshot, recalled memory versions/expiry, event/action pair,
   permitted tool receipts and live lease. SQL computes physical quantities and
   enforces supplier validity, exclusions, consent, reservations and cooking.
6. Commit domain effects, queue outbox, replay facts, typed outcome memory,
   decision receipt, applied marker and event ACK together.

A saved completed plan can be consumed after lease reclamation without repeating
ADK calls. Death during an unfinished turn marks it unknown on reclamation and
fails closed; it does not regenerate a partially completed decision. Changed
business observations or expired/revised recalled facts invalidate a saved plan.
Such turns need explicit operator handling. This chooses bounded retries and
auditability over automatic availability; external exactly-once billing is not claimed.

## Authorization and budgets

ADK restaurants use their own `lab_restaurant_adk_executor` PostgreSQL group, not
the legacy supply executor. It has no stock, memory-history, turn-table or broad
`supply_context`/`supply_command` grants. All granular functions reconstruct scope
from `session_user`, a live addressed lease and a durable budget ticket. The model
cannot supply a run, order, namespace or agent identity in tool arguments. ADK's
tool callback also rejects unknown fields/types before execution.

The existing event/tool/memory limits remain independent of instructions. New
brain limits cap model calls per event and per restaurant/run, serialized token
reservations, request bytes, output tokens and wall time. A run-wide ceiling also
limits aggregate restaurant calls/tokens. Reservations survive failures and are
not refunded. Bytes of the serialized text-only request conservatively reserve
input tokens; configured output allowance is reserved too. This is not a tokenizer
or a measurement of actual Gemini usage. Offline inference has zero provider
cost. Native Vertex admission additionally reserves money at the frozen approved
input/output rates, rounds upward and checks the restaurant's `usd_limit` plus a
$10 run-wide reservation ceiling. The unpriced admission helper is private.
Reservations survive timeouts and crashes, with no automatic refund. These limits
bound admitted work at configured rates; they do not enforce a billing-account
cap or compensate for a provider tariff change. Unknown actual billing stays unknown.
ADK model limits live in `brain`; the legacy `RoleLimits` model fields retain the
older judge contract. Operator inspection shows the separate ADK reservation
counters rather than treating those legacy zero fields as actual ADK usage.

The trusted local host/controller remains outside this isolation boundary. This
is not an OS sandbox for arbitrary agent code. Inspection endpoints are trusted
operator views and are not registered ADK tools.

## Optional native Vertex model adapter

`adk_models.py` constructs ADK's `Gemini` with Vertex enabled, a specific approved
project/region/model, stable API version `v1`, ADC credentials and one HTTP attempt.
It never accepts an API key or arbitrary model endpoint from a prompt/blueprint.
A Vertex brain requires a positive `usd_limit` and a `vertex` profile containing
`project`, `location`, `model`, `input_usd_per_million` and `output_usd_per_million`.
The trusted deployment must separately set `DELIVERY_ADK_VERTEX_ENABLED=1` and
`DELIVERY_ADK_VERTEX_PROFILE` to that exact approved JSON profile. Missing approval,
different project/model/pricing, unapproved adapters or exhausted budgets fail closed.
The normal UI loads only offline profiles; configuring Vertex requires an operator
to prepare the advanced definition and deployment policy explicitly.

No credentials are discovered until an approved native model is actually invoked.
The local Compose defaults contain no ADC mount. In a GCP workload, ADC should
come from its least-privilege runtime identity. Test profile prices and project IDs
are fictional inputs, not recommended Google prices. Model availability, region,
current tariffs and IAM are operator deployment choices. The explicit live comparison
below exercises this adapter without enabling paid execution in the normal city UI.

## Verification and GCP direction

Run the reproducible offline checks with the local Postgres services available:

```bash
make test-adk
```

`make demo-adk` retains two one-order runs for inspecting the profiles in the UI
and writes `artifacts/adk-restaurants-demo.json`. It changes no saved blueprint,
uses only this project's local database, and never selects Vertex. Default city
demand is much larger than this bounded comparison; model/tool budgets still
stop an over-budget ADK worker rather than silently enabling an unbounded run.

Tests use only `delivery_test`, restricted identities, real ADK function calls and
an HTTP-blocking fixture. They cover both profiles through sourcing and physical
delivery, replay, prompts reaching ADK, foreign roles/runs, raw-table/legacy denial,
budgets, stale stock, invalid suppliers, unfinished-turn rejection and saved-plan
recovery. A worker is also terminated as a real process after saving its plan.
The health dashboard lists these cases under **ADK restaurant agents**.

Google-native components implemented here are ADK, Google Gen AI types and a gated
keyless Vertex model adapter. The
existing isolated Terraform Cloud Run/Vertex recovery judge is separate. The
local city and Postgres remain free local infrastructure. Production work still
includes billing reconciliation, broader model-quality evaluation and a supervised worker.
Cloud Run or managed-runtime hosting must be Terraform-owned before deployment;
ADK names or sessions do not create IAM identities. No new GCP resource is required
or provisioned by the offline checks.

## Real Vertex and Jev comparison

The native restaurant worker stays local and impersonates a dedicated, keyless
`restaurant-adk` service account in the isolated simulation project. Terraform
owns the identity, its `aiplatform.endpoints.predict` grant and the permitted
operator impersonation binding. This mode enables the project's billing link
without creating Cloud Run, Artifact Registry, Cloud SQL or a managed agent runtime.
The existing judge gateway is not deployed for these tests. Project, APIs and IAM
remain when billing is parked.

```bash
make gcp-vertex-start
make demo-adk-vertex
make gcp-stop
make gcp-status
```

Each SOUL gets one synthetic pizza order, an empty pantry and three public
supplier quotes. Elena should prioritize lead time; Mateo should prioritize
procurement fee. Both use the same ADK tool implementation. Gemini decides the
tool sequence and supplier from the prompt and SOUL; the SQL layer validates
authority, quantities, consent and event effects. No paid model selects the stock
quantities or bypasses the queue.

The reviewed model is `gemini-3.5-flash-lite`, global, standard text PayGo:
$0.30 / million input tokens, $2.50 / million output tokens including thinking,
and $0.03 / million cached input tokens, checked 2026-10-29. Gemini 3 uses minimal
thinking for this bounded trial. Global is deliberate for synthetic data and
does not assert EU processing residency. The retired 2.5 model is not used.

Jev `jev-1.14.0` is an optional `supply.search` capability, not a general planner.
The model may call `search_ingredients` with a canonical ingredient ID from the
current recipe. The server selects the already scoped restaurant index and
frozen review provider. Jev receives ingredient labels, units and a relevance
question; it receives no inventory counts, household conversations or typed memory.
Its result is an observation. Availability is read again locally; reservation
and supplier communication still require the transactional tools and event queue.
Its input-only tariff is $0.042 / million tokens, output free. An API key is held
in ignored `.env.jev` and passed only to the one-shot worker.

The comparison admits at most $0.20 Vertex work per SOUL ($0.40 together),
60 calls per agent, eight per event, 1,024 output tokens per call, and a 30-second
event deadline. Each agent also gets three Jev calls and 24,000 reserved input
tokens: together $0.002016 maximum at the reviewed Jev tariff. No automatic
provider retries, provider fallback or fresh paid experiments follow a failure.
An exclusive execution lock prevents concurrent launches. Explicit receipt recovery
can re-read finished runs without repeating calls; reviewed follow-up experiments
account for previous known costs, reserving the full allowance for unknown calls,
against a cumulative $0.50 Vertex limit. Operator-controlled local files and
SQL admission are not a billing-account spending cap.

The retained live comparison delivered both meals, with 25 Gemini calls and three
Jev calls per SOUL. Elena selected `market-a` (90-second quoted lead time); Mateo
selected `market-b` (50-cent fee). Both runs acknowledged 24 events, had zero
retries/dead letters, conserved stock and replayed correctly. Median Gemini call
latency was 800 ms for Elena and 769 ms for Mateo. Their Vertex costs calculated
from actual usage were $0.01214980 and $0.01269700; Jev was $0.000136962 each.
Including the initial trial, total usage-derived cost was $0.039755624. Billing
was then disabled, retaining 15 foundation resources. A live impersonated IAM
probe received HTTP 403 / PERMISSION_DENIED for `resourcemanager.projects.get`.

These two synthetic orders prove integration and the intended SOUL distinction;
they are not a general model-quality benchmark or proof of cost/latency savings
from a Jev cascade. Both agents still invoke Gemini on routine arrival and cooking
events. Routing those bounded, high-confidence cases through rules or Jev before
escalating ambiguity to Gemini is a separate optimization that needs an A/B eval.
One recovered receipt has no whole-run wall time; per-call latency and token
metadata were durably retained and remain available.

[AI evidence](/agent-traces) shows the retained comparison, system prompts and
SOULs, tool declarations, model-visible messages, function calls, tool results,
selected memory with provenance/expiry/version, provider model version, latency,
tokens and usage-derived costs. Full private rows are not granted to agents.
The page never starts inference. Costs calculated from actual token metadata are
separate from invoice totals, credits, tax and project-wide charges; missing
metadata remains unknown. Previous attempts remain in the local JSON receipt.

Source links: [operator evidence reader](../src/delivery/adk_evidence.py),
[paid comparison](../scripts/demo_adk_vertex.py),
[temporary impersonated ADC launcher](../scripts/run_adk_vertex.py),
[model trace schema](../sql/migrations/019_adk_model_traces.sql),
[scoped search grants](../sql/migrations/020_adk_scoped_search.sql),
[canonical business snapshots](../sql/migrations/021_canonical_supply_context.sql),
and [usage-cost and operator-boundary tests](../tests/test_adk_evidence.py).

An initial real run exposed unordered JSON inventory arrays: equal stock facts
could fail stale-state validation after a different query plan. Canonical ordering
fixes that comparison while preserving version/quantity checks. A regression test
rewrites physical stock rows without changing their business values; existing
stale-stock tests continue to reject actual changes.

Official deployment references: [Gemini model lifecycle](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions),
[3.5 Flash-Lite capabilities](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite),
[Vertex pricing](https://cloud.google.com/model-garden/pricing),
[Jev models and pricing](https://docs.typesafe.ai/models), and
[Jev typed questions](https://docs.typesafe.ai/primitives).

References: [ADK instructions and tools](https://adk.dev/agents/llm-agents/),
[identity and tool enforcement](https://adk.dev/safety/),
[runtime limits](https://adk.dev/runtime/runconfig/), and
[ADK on Cloud Run](https://docs.cloud.google.com/architecture/single-agent-ai-system-adk-cloud-run).

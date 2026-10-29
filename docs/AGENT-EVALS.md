# Agent evaluation workflow

Start the local stack (`make up`), then use Bash:

```bash
make eval-agents
```

The disposable checker runs the fixed battery **twice**, writes
`artifacts/health/latest-scenarios.json`, and exits nonzero for a failed or missing
case, changed source, or different repeated outcomes. `make health` includes this
command's evaluator alongside the complete test suite and static checks. Neither
command restarts the running app, Postgres or Redis. Open
[Health & evals → Agent evals](http://localhost:8010/health) to inspect the results.
Refreshing the page only reads receipts; it cannot execute a command.

All worlds use seed **731**, the committed synthetic catalogues/recipes and the
existing 32×32 city. They run in the dedicated **local `delivery_test` database**;
production database names, remote hosts and connection-string overrides are
rejected before creating a world. Model inference is disabled and ingredient
search uses its local adapter. There is no cloud endpoint option. The optional
GCP demo remains independent.

## Cases and scoring

The versioned contract is `data/evals/agent-scenarios.json`. Twelve scenarios
declare 49 criteria, each with a human-readable label and an exact typed expected
value. Booleans and integer counts are different measurements.

| Role | Scenario | Required behavior |
| --- | --- | --- |
| Inventory | Two baskets, one unit | One reservation, one safe rejection; scoped stock visibility |
| Inventory | Delayed replenishment | Forecast units remain unavailable until actual receipt |
| Inventory | Crash before acknowledgement | Actual worker-process crash rolls back; lease retry has one effect |
| Restaurant | Available pantry | Deliver pizza without unnecessary sourcing |
| Restaurant | Market forwarding | Empty nearest market forwards flour request; ingredients arrive before cooking |
| Restaurant | Replacement declined | Record refusal and reject without cooking or consuming ingredients |
| Restaurant | Replacement approved | Household consent and kitchen approval both precede cooking |
| Dispatcher | Assignment race | Two workers contend for one courier; one job assigned, one deferred |
| Dispatcher | Traffic and retry | Congestion affects ETAs; retry needs approval; infeasible job is abandoned |
| Courier | Assignment authority | Other courier cannot read/accept brief or recall memory; motion waits for ACK |
| Courier | Dropout handoff | Replacement gets recorded parcel checkpoint, prior courier and source events |
| Courier | Physical arrival | Completion follows world arrival; route ETA equals edge duration sum |

A case passes only when **every declared criterion** passes and execution/cleanup
succeeds. A safe business rejection is a successful evaluation when rejection is
the specified outcome. Case and role scores are passed criteria divided by their
declared criteria; missing measurements receive no credit. The dashboard always
shows case failure counts alongside scores. Missing receipts have no score;
partial receipts cannot become a complete pass.

Scores are recomputed by the reader from the committed contract and measured
values. A receipt cannot supply its own expected values, headline pass count or
score. Unknown/duplicate cases, extra fields, malformed types, missing configuration
hashes, incorrect repeat hashes and mismatched manifest versions are rejected.

## What actually runs

`delivery.scenario_evals` creates eight small isolated fixture worlds. Agents are
the existing `LocalAgent` workers with their real per-run/store/role Postgres
logins, permissions, tool budgets, typed memory and durable queue leases. The
controller sets up stock, injects disruptions, advances virtual time and observes
results as a trusted operator. Agents communicate through queued events; the
evaluator does not replace their decisions with an oracle. Dispatcher contention
uses two concurrent workers, and inventory recovery kills a real subprocess.

The controller retires short-lived database identities and deletes its worlds in
`finally`, including after a fixture error. Failure receipts store fixed error
codes, never exception messages, SQL strings, connection URLs, event payloads or
memory bodies. The retained event trail contains only fixture-relative sequence,
topic, trace, queue state, attempts and scheduled simulation seconds. Fixture
sequence numbers are local to the receipt; deleted database events cannot be
opened later. Supply replay is checked before cleanup.

Two evaluations cannot interleave through the CLI: it holds a Postgres advisory
lock. Existing simulation runs in the application's `delivery` database are
unaffected. The test suite verifies that the battery leaves the pre-existing
test-run IDs and role identities unchanged, and that an injected fixture error
still cleans up without exposing its exception text.

## Reproducibility and limits

Receipts retain manifest version/hash, seed, effective configuration hashes, source
fingerprint, UTC creation time and a business-outcome hash for **each** repetition.
The hash includes typed observations and fixed error codes. It excludes wall time,
random run IDs, global SQL event IDs, and which racing worker wins: both possible
winners are valid, but one courier must still receive exactly one job.

Each repetition's observations are preserved and checked against its hash. A later
passing repeat cannot erase an earlier failed case. Each criterion keeps its first
explicit failure across repeats, otherwise its first missing measurement, otherwise
the final passing value. Criteria and event trails identify their repetition. An
omission cannot hide a measured failure from another repeat. Input hash drift also
produces a failed receipt, including when one setup attempt fails before creating
the world. A mismatch fails reproducibility even if both individual outcomes
otherwise meet the criteria. Starting the checker replaces any previous green
receipt with unmeasured evidence until the new battery finishes.

For a quicker diagnostic run after building the image:

```bash
docker compose run --rm --no-deps app python3 scripts/eval_agents.py --reproduce 1
```

The page labels a single run as repeatability **not measured**. Results from changed
sources or older than 24 hours remain historical. Rebuild the running app after
source changes so its fingerprint can match the checker. These are local receipts,
not signed attestations against a hostile host operator.

This is a fixed **development regression battery for rules-based agents**. It
measures coordinated business and permission behavior, not LLM reasoning quality,
production latency, cost per model decision, held-out generalization, or superiority
of one architecture/memory strategy. Those remain separate unmeasured benchmarks.

## Google-native model evaluation

[Committed-snapshot verification](evidence/google-native-evals.json) records the
test counts, scripted-arm metrics and limits of the latest local evaluation.

The native files are `evals/adk/restaurant.evalset.json` and
`evals/adk/customer_service.test.json`, with ten cases each. Install the pinned
runtime from `requirements.lock` (including `google-adk[eval]`), then run from the
repository root in Bash:

```bash
python3 -m pip install -r requirements.lock
python3 -m pip install --no-deps -e .
adk eval evals/adk/restaurant evals/adk/restaurant.evalset.json \
  --config_file_path evals/adk/test_config.json
adk eval evals/adk/customer_service evals/adk/customer_service.test.json \
  --config_file_path evals/adk/test_config.json
python3 -m pytest -q tests/test_adk_evalsets.py
python3 scripts/eval_agents.py --suite adk --repeat 3
```

`AgentEvaluator` and the CLI use the same EvalSet schema and deterministic
trajectory/response-match metrics. Both agents use `adk_offline.py`, with no
provider fallback. Tests deny provider initialization and HTTP; the CLI child also
denies sockets. Restaurant tools use in-memory fixtures and the production plan
schema. Actual SQL scope, admission, durability and migration-019 trace ingestion
remain covered by integration tests. Scripted classification is not evidence of
language understanding.

The repeated-arm receipt is `artifacts/evals/candidate.json`. `--repeat k`
(1–100) applies only to model arms, with a fresh session per attempt.
`--reproduce 1|2|3` independently controls SQL repeatability; `--suite all` runs
both. The default suite remains `scenarios` for compatibility with `make health`.
A container without Git can receive `DELIVERY_SOURCE_REVISION`; otherwise the
receipt is labelled unversioned. `make eval-adk` runs the model suite in Docker.

## Error analysis and categories

1. Start with the failing case, arm, repetition and category; reproduce locally.
2. Inspect the request's declared functions and the response's actual calls.
   Requests contain repeated history: count only new response calls.
3. Compare arguments and ordered steps against a reviewed reference. A correct
   final reply does not excuse an invented tool or a wrong supplier.
4. Check recovery evidence. A successful corrected tool response counts; an
   attempted retry without a response does not. Durable tool receipts capture
   terminal results when summarization is skipped.
5. Promote a minimal regression, rerun code checks, native evals and the original
   SQL integration test, then refine policy or prompts.

`delivery.trajectory_evals.read_trace(url, event_id)` reads one event from
`restaurant_model_calls` and `restaurant_tool_receipts` using an operator
connection. Migration 019 added request/response/latency columns; no new migration
or agent table grant is needed. `score_trajectory` reports multiset tool
precision/recall, exact-argument precision/recall, field differences, ordered LCS
match, extra/missing steps, model/tool step counts, incomplete dispatches and
recovery rate. No observed errors means recovery is null, not perfect.

The health taxonomy explicitly includes **schema**, **length** and
**invented_tool**. Schema checks reject malformed replies and unexpected
arguments. Length checks enforce the 1–500 character summary/reply boundaries.
Invented-tool checks use the declared capability set and never alias misspelled
names. These checks run before any semantic judge and spend no judge quota. Task
and trajectory correctness are separate gate categories.

## Promote stored evidence

Write an explicit reference containing tool names and arguments. Never treat a
failed output as its own desired answer. For example, using Bash:

```bash
mkdir -p artifacts/evals
cat > artifacts/evals/reference.json <<'JSON'
[{"name":"finish_decision","args":{"summary":"Compared the quotes."}}]
JSON
python3 scripts/promote_trace.py \
  --receipt artifacts/adk-route-comparison.json \
  --pointer /arms/3/evidence --event-id 123 \
  --reference artifacts/evals/reference.json \
  --id reviewed-cost-finish --description 'Reviewed terminal-tool regression' \
  --expect-category invented_tool
```

Replace 123 with the actual event and provide its complete reference. Alternatively
use `--stored-trace --event-id 123` with operator `DATABASE_URL` supplied through
the environment. Multi-event receipts require an event selector. Each promotion
creates the next `data/evals/golden/vN/` directory without overwriting prior
versions; the latest version of each case ID is evaluated. Review the diff before
committing. Reference arguments and descriptions still need privacy review. Raw
prompts, model thoughts and tool-result bodies are omitted; capability arguments
and minimal success/error classifications survive.

Golden case **001-cost-invented-finish** preserves a terminal-call excerpt from
the historical cost-mode receipt: `finish_finish_decision` instead of
`finish_decision`. Its expected result is an invented-tool rejection and zero
name recall. A passing negative regression means the scorer caught the known
failure, not that the historical run succeeded. The native `cost-source` case
separately verifies the current scripted agent's complete correct trajectory.

## Reliability, cost and latency

Every attempt is retained, including failures. **pass^k** is the empirical fraction
of distinct cases passing **all k** attempts. It is neither pass@k (at least one
success) nor the pooled pass rate raised to a power. Missing, duplicate or
unbalanced repetitions invalidate comparisons.

Seeded percentile bootstrap 95% intervals resample cases, keeping whole repeat
groups. Repeats are not extra independent cases. A one-case sample has no interval.
At all-pass/all-fail boundaries bootstrap intervals are degenerate; this does not
establish certainty about unseen tasks. Fixed development cases are not a random
production sample. Scripted pass^k/timings measure fixture stability, not live-model
reliability or production performance.

Cost per successful task divides the cost of all attempts, including failures,
by successful attempts. Unknown usage never becomes free; reservations provide a
separate conservative figure. Zero successes yield null. P95 latency includes
failures and uses an interpolated percentile. The recovery-judge script reports
these metrics too. Comparisons show main/candidate values and deltas; wall-clock
timing remains diagnostic because shared CI runners are noisy.

## PR gate and main baseline

The `evals` job runs on pull requests and main pushes without cloud credentials or
paid calls. Code checks precede native evals and three fresh scripted attempts per
case. Successful main runs store `eval-baseline-v1` for 90 days, including reviewed
`config/eval-gate.json` thresholds and source revision. PRs download the artifact
from the successful main run for their exact base SHA. PR changes cannot select
an alternate baseline or quietly weaken its stored thresholds.

No baseline exists before the workflow first lands: that bootstrap run is explicitly
`baseline_missing`, with no quality comparison claim. Missing or expired artifacts
have the same status. Obtain a successful main run before relying on comparisons.

Comparisons require identical fixture hashes, modes, repeat counts, arms and case
IDs. Changed cohorts or corrupt receipts fail validation, not a statistical quality
test. Reference changes require a reviewed main baseline refresh. Saved headline
scores are ignored and recomputed from rows.

A quality regression requires all three:

- At least eight distinct paired cases.
- The lower end of the case-bootstrap 95% pass-rate-drop interval exceeds the
  permitted drop: zero for schema/length/invented tools, 0.05 for task/trajectory.
- An exact one-sided paired sign test passes family-wise 0.05, Bonferroni-adjusted
  across every arm and category.

A single fluctuation does not fail the statistical gate. Deterministic contract
failures and invalid artifacts still fail verification. Cost/latency deltas do not
fail the quality gate. One red/green PR comment is updated with evidence. A green
bootstrap or insufficient-evidence label is not proof of equivalence. Forks whose
tokens cannot comment retain Markdown as a job summary/artifact. The workflow
does not execute candidate code through `pull_request_target`.

```bash
python3 scripts/eval_gate.py --candidate artifacts/evals/candidate.json \
  --baseline artifacts/evals/main/candidate.json \
  --baseline-revision MAIN_COMMIT_SHA \
  --thresholds artifacts/evals/main/eval-gate.json
```

## Optional manual Vertex judge

`vertex-eval.yml` is `workflow_dispatch` only, main only, with an explicit `paid`
input. Configure the `vertex-evals` environment variables `GCP_EVAL_PROJECT`,
`GCP_EVAL_WORKLOAD_IDENTITY_PROVIDER` and `GCP_EVAL_SERVICE_ACCOUNT` with an identity
authorized for Vertex evaluation. It judges existing synthetic customer replies
from `data/evals/customer-replies.json`, without generating candidates.

`cloud_ai.py` sends the documented `evaluateInstances` pointwise request with
`gemini-2.5-flash-lite`, one sample, no thinking, at most 256 output tokens, an
8 KiB request and a 30-second timeout. It bypasses the SDK's internally retrying
batch helper. No model fallback is allowed. A SQLite ledger reserves USD 0.01
before each request, enforcing USD 0.05 per run; even if twelve calls are
requested, money admits at most five. Reservations remain charged after errors
and timeouts. Service usage/invoice cost is unknown: this is an admission ceiling
with conservative overhead, not a billing guarantee. Workflow reruns are disabled;
a new explicitly authorized dispatch starts a new scope.

The transport and Google wire schema are tested with mocks. **No live Vertex
evaluation verified this change.** Check service availability, IAM and regional
support on the first manual run. Pricing checked 2026-10-29: Flash-Lite 2.5 text
input/output are USD 0.10/0.40 per million tokens, below Flash-Lite 3.1's
USD 0.25/1.50. Review the pinned model and reservation before changing tariffs.

## Later: simulated users

`evals/adk/personas/customer_service.scenarios.json` contains valid ADK
ConversationScenario scaffolds for order status, refunds over EUR 100 and prompt
injection using the EVALUATOR persona. They are schema-tested, but excluded from
evalsets, CI and the manual judge. No simulator model is enabled. Activation needs
its own budget and a multi-turn customer agent; today's advice interface is one turn.

## Google references checked 2026-10-29

The implementation was checked against pinned ADK 2.13.0 and these official docs:

- [ADK evaluation](https://google.github.io/adk-docs/evaluate/)
- [ADK criteria](https://google.github.io/adk-docs/evaluate/criteria/)
- [ADK user simulation](https://google.github.io/adk-docs/evaluate/user-sim/)
- [Vertex evaluation overview](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-overview)
- [Pointwise API](https://docs.cloud.google.com/vertex-ai/docs/reference/rest/v1beta1/projects.locations/evaluateInstances)
- [Judge configuration](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/configure-judge-model)
- [Google Cloud model pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)

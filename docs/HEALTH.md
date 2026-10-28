# Local health and evaluation evidence

Open [Health & evals](http://localhost:8010/health) from the delivery, restaurant or
inventory workspace. The category tally and recent-run pattern follows the
Scrapmarket health page; this implementation uses local files and probes, with
no Firestore, cloud deployment or model requests.

## Collect evidence

Start the stack with `make up`. Then, from Bash:

```bash
make health
```

This builds a disposable checker container, runs the full pytest suite against
`delivery_test`, runs Ruff and mypy, and evaluates the fixed recovery-judge rules
baseline. It does not restart the running app or its database/Redis dependencies.
The checker forces `LLM_PROVIDER=disabled`; its evaluation command never accepts a
cloud endpoint. It requires a configured `delivery_test` URL and also binds the
subprocesses' default database to that test database. A nonzero test/check result
makes the command fail while preserving
the available evidence. Source edits during the check also make it fail.

`make test` also records case-level test results. GitHub CI uses the same local
runner and uploads its safe JSON reports even on failure. CI artifacts are not
automatically downloaded into the local dashboard.

The checker image is Python-only. JavaScript syntax is explicitly **unavailable**
there when Node is absent; this is not counted as a pass and does not fail the
Python check command. With Node available the runner checks every first-party
`web/*.js` file. A local Bash syntax check is also available:

```bash
node --check web/health.js
```

`DOCKER` can override the Docker executable, for example `make DOCKER=docker.exe
health` in a Bash environment that needs the Windows executable.

## What the page shows

- **Test catalogue:** all collected parameter cases, explicit categories, search,
  result and integration filters. Expand a file, then a check for its description,
  source line, original case ID, duration and failing phase. Descriptions come from
  test docstrings or names; they are not generated assertions about test coverage.
- **Agent evals:** selected regressions for queue resilience, coordination,
  memory isolation, budget admission, disrupted-city scenarios and replay. Each
  card links to its cases and states its limits. These groups overlap and must
  not be added into a second test total.
- **Rules baseline:** the six fixed recovery-judge cases, with expected and actual
  decisions and local latency. The rules oracle is compared with itself. This
  checks the evaluation harness, not model quality, live latency or model cost.
- **City health:** read-only Postgres/PostGIS and Redis probes, selected-run queue
  counts, expired leases, dead letters, retries, durable run budgets and model/search
  reservations. Reservations are not actual provider usage or a monetary estimate.
  Historical failed scenarios stay visible. Business failures are distinct from
  infrastructure failure.
- **Run history:** up to 12 finished receipts, retaining their original scope,
  source and outcomes. Invalid receipts are counted as unreadable, not passed.

The page refreshes every 30 seconds while visible. The refresh button reads
existing results; it cannot execute tests or accept shell arguments. Open test
details remain expanded as results refresh. Dates use Europe/Madrid.

## Evidence boundaries

The opt-in `delivery.health_report` pytest plugin records collection and all
setup/call/teardown outcomes. A teardown failure overrides a successful call.
Skipped, expected-failure, unexpected-pass, unrun and filtered cases stay distinct.
Collection-only and interrupted runs cannot be reported as a full passing suite.
Missing evidence is unknown, with no fallback to the old headline of 307 tests.

A deterministic SHA-256 fingerprint covers source, tests, SQL, agent/config files,
web assets, scripts, fixed data including the compressed road graph, the tested
gateway source, dependency files, Dockerfile, Makefile and CI workflow. The reader
compares it with the running app's copy of those files. Host edits need a rebuilt
app to appear in that comparison. A base Git revision is supplementary metadata;
it does not replace the fingerprint for a dirty working tree.

Results older than 24 hours, changed sources, and edits during a check are marked
explicitly. Reports use atomic replacement. Failed refreshes remove current/green
claims and retain the catalogue only as historical evidence.

Reports live in ignored `artifacts/health/`. They contain test identifiers,
docstrings, statuses and timings, not captured stdout, tracebacks, failure messages,
fixture representations, environment variables, database URLs or agent memories.
Use descriptive explicit IDs for parametrized inputs rather than embedding long
payloads or credentials in case names. These files are local development receipts,
not signed attestations or a sandbox against a hostile host operator.

The read-only `/api/health/evidence` and `/api/health/runtime` endpoints are for the
trusted local operator. They use the same local-host gate as supply endpoints.
They do not grant an agent any new tool or memory access.

## Extend the dashboard

`config/health-categories.json` is the reviewed taxonomy. Give each new test file
one primary category; unmatched files appear under **Needs classification**.
Capability selectors can reference a whole test file or an exact test function;
parameter variants are included automatically. A missing selector is a visible
measurement gap. Category membership is not a percentage of requirements covered.

Live-model quality/cost, held-out scenario results, architecture comparisons,
semantic recall and long-term memory summaries remain **not measured**. Add them
with versioned fixtures, actual results, source/model versions, budget accounting
and explicit measurement scope rather than reusing the regression pass rate.

## Verification

Verified locally on 2026-10-28: 353 tests passed, including 46 reporting/health
checks. Ruff and mypy (38 source modules) passed. The dashboard indexed 36 test
files into ten categories with no unclassified file or missing capability selector.
All six fixed offline judge cases passed, with zero model decisions or tokens.
The running app's fingerprint matched every current receipt.

Browser checks covered missing/collection evidence, source changes in history,
search and category filters, case IDs, persistent expanded inspection, capability
drill-down (15 memory cases), real historical dead-letter diagnostics, and the
explicit unmeasured model/architecture sections. Both local service probes passed;
Postgres and Redis identities/start times were unchanged by the check command.
Host JavaScript syntax passed; browser console errors and horizontal overflow were
zero at the default viewport. The Python-only checker correctly marked its missing
Node check unavailable. The [local receipt](evidence/local-health.json) records the
results and limitations.

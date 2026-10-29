# Run evidence in BigQuery

The simulation stays local. Analytics is an explicit export of existing evidence: it never starts a run, asks a model a question, changes inference admission limits, or executes a BigQuery query. The default workflow writes inspectable local files and needs no Google credentials. Terraform defaults to `enable_bigquery=false` and creates no analytics storage or service account.

## Prepare and inspect a free bundle

From an installed development environment, use an existing offline receipt:

```bash
python3 scripts/export_bigquery.py prepare \
  --receipt artifacts/adk-restaurants-demo.json \
  --output artifacts/bigquery/demo
```

The exporter accepts both native receipt formats:

- Baseline simulation: `artifacts/run-<run-id>.json`, with a nested `run` object containing `id`, timezone-qualified `created_at`, `status`, and model accounting, plus top-level `metrics`. Delivery measurements include orders, delivered/on-time counts, on-time percentage, active/unserved work, delivery cost and cost per delivery.
- ADK comparisons: a top-level timezone-qualified `created_at`, a `profiles` or `arms` list, and per-run `run` UUID, `metrics`, and boolean `invariants` or `outcome_checks`. This includes `artifacts/adk-route-comparison.json` and `artifacts/adk-live-comparison.json`. Generate a fresh offline receipt with `make demo-adk` if needed.

Use either format with the same `prepare --receipt ... --output ...` command. Missing invariant or replay evidence stays unmeasured.

The output contains:

| File | Contents |
| --- | --- |
| `run_receipts.ndjson` | Run ID, receipt/source hashes, run and export timestamps, profile/scenario/variant, recorded status, replay result, passed/total checks, and cost evidence. |
| `run_kpis.ndjson` | Allowlisted numeric delivery, queue, ADK, search, and router measurements, one row per metric. |
| `manifest.json` | SHA-256, row count and byte count for both tables. |

Raw prompts, transcripts, provider responses, configuration, credentials, and free-form error text are excluded. Unknown metrics remain absent; incomplete cost accounting remains null. `usage_cost_usd` uses known usage at the receipt's frozen tariffs only when every call is accounted for. It is not a billing invoice. `reserved_cost_usd` remains a separate admission amount; explicit zero-paid-call receipts can report zero cost. A missing status is `recorded`, never inferred to be completed.

Baseline `llm_cost_usd`, `llm_calls`, tokens and reservations are retained as numeric KPIs. Their aggregate values do not prove every admitted model call returned usage. Consequently, a baseline receipt with model calls retains null `usage_cost_usd` even if its observed cost is zero. Only an explicit zero call count proves zero model usage for that format; missing call counts do not. The reserved amount remains separately visible.

Preparation refuses to overwrite a bundle. Keep the bundle unchanged for retries. Source files are capped at 32 MiB; each export is capped at 100 runs and 1 MiB. All generated files belong under ignored `artifacts/`.

## Optional cloud setup

This is a separate, opt-in demo alongside the existing GCP judge lifecycle. No cloud deployment or upload runs in CI. Use the dedicated project already configured in the ignored Terraform variables, and review the plan before applying:

```bash
terraform -chdir=infra/gcp-ai plan \
  -var=enable_bigquery=true -var=enable_billing=true \
  -out=analytics-enable.tfplan
terraform -chdir=infra/gcp-ai apply analytics-enable.tfplan
terraform -chdir=infra/gcp-ai output bigquery_analytics
```

The plan provisions an EU dataset by default, two tables partitioned by `exported_at` and clustered by run/hash, and the `run_dashboard` GoogleSQL view. Both tables require a partition filter and expire partitions after seven days. Change `bigquery_location` before creating the dataset if required; it is independent of the Vertex region. Retention and the upload size cap bound this demonstration's data footprint; they are not a total billing cap. Storage and dashboard queries can incur charges while enabled.

The keyless `delivery-analytics` service account has a custom dataset-scoped role limited to table create/get/update/updateData and a project role containing only jobs.create. It cannot read table data, delete tables, administer IAM, or invoke Vertex. The uploader sets `CREATE_NEVER`: table creation belongs to Terraform. Only the explicit `invoker_members` can impersonate this identity. No service-account keys are created. Keep dashboard reader access separate from this write-only loader.

## Upload only the reviewed bundle

Use an installed Python environment with the project dependencies and Application Default Credentials. Set the project ID from the Terraform output; no project ID or credentials are committed:

```bash
export ANALYTICS_PROJECT='your-dedicated-project'
export DELIVERY_BIGQUERY_ENABLED=1
python3 scripts/export_bigquery.py upload \
  --bundle artifacts/bigquery/demo \
  --project "$ANALYTICS_PROJECT" \
  --service-account "delivery-analytics@$ANALYTICS_PROJECT.iam.gserviceaccount.com" \
  --dataset delivery_analytics --location EU \
  --confirm-upload
unset DELIVERY_BIGQUERY_ENABLED
```

Both the environment opt-in and `--confirm-upload` are required before credentials are loaded. The bundle is checked against its manifest before either table is uploaded. Loads append to existing tables, reject unknown columns/bad records, and use stable job IDs derived from the exact destination and frozen bytes. Retrying the same bundle recovers an existing load job after a conflict. The two table loads are independent: after a partial failure, repeat the same upload command. Do not prepare another bundle as a retry. BigQuery job deduplication is bounded by its retained job history; the dashboard additionally selects the latest export per run and collapses duplicate metric rows. Old exports expire with their partitions.

## Looker Studio dashboard

Connect Looker Studio's BigQuery connector to the Terraform output `dashboard_view` using a separate reader identity with the necessary dataset read and project job permissions. The view is ready to select as a table, so no custom SQL is needed in Looker Studio.

Suggested controls are `run_date`, `profile`, `scenario`, and `variant`. Add delivery rate, queue events, dead letters, replay result, and evaluation pass rate; compare measured usage cost with reserved cost in separate series. `evaluation_pass_rate` is the run receipt's boolean-check pass rate, not the entire repository's scenario evaluation score. Missing denominators and missing usage stay null. Both source tables are filtered to the last seven export days. Choose bounded refresh intervals and inspect BigQuery billing before making a dashboard public; this feature does not publish one automatically.

The same view supports baseline receipts: `delivery_rate` divides delivered orders by ADK `scheduled_calls` when present, otherwise baseline `orders`. It also exposes baseline `on_time`, `on_time_pct`, `delivery_cost_eur`, `cost_per_delivery_eur`, `active`, `unserved`, `pending`, and `overdue` columns. `delivery_rate` is a fraction (0–1); the simulator's `on_time_pct` is already a percentage (0–100). A zero denominator remains null, and baseline receipts without outcome checks retain a null evaluation pass rate.

## Park analytics

Stop uploads by clearing `DELIVERY_BIGQUERY_ENABLED`. To return to no analytics storage, explicitly remove this disposable dataset while billing is still linked:

`gcp_demo.py status` lists `analytics_in_state` and `telemetry_in_state`; retained optional components are never reported as fully parked. `stop` checks these resources before restarting the app or changing cloud resources and gives cleanup instructions if any remain. Once cleanup is complete, its parking plans explicitly keep both optional flags false so stale opt-in settings cannot recreate them.

```bash
unset DELIVERY_BIGQUERY_ENABLED
terraform -chdir=infra/gcp-ai plan \
  -var=enable_bigquery=false -var=enable_billing=true \
  -out=analytics-disable.tfplan
terraform -chdir=infra/gcp-ai apply analytics-disable.tfplan
python3 scripts/gcp_demo.py stop
```

Review the removal plan: it deletes the analytics tables and view. Original local receipts remain available. The dataset refuses to delete unexpected, unmanaged contents. Preserve `enable_bigquery=true` on intervening Terraform commands while the analytics demo is active; command-line flags are not persisted. Remove analytics explicitly before the existing judge stop command unlinks billing. The enabled BigQuery API registration can remain after storage and IAM are removed and does not itself store run data.

## Verification and API references

`tests/test_bigquery_export.py` covers local-only preparation, allowlisting, incomplete accounting, strict opt-in, artifact tampering, stable load IDs, SDK load configuration and recovery, and payload limits. `infra/gcp-ai/tests/bigquery.tftest.hcl` uses the mocked Google provider to check parked defaults, billing opt-in, retention, scoped permissions and the view. These checks make no paid calls. The cloud path has not been live-uploaded as part of this change.

Inspect the [exporter](../src/delivery/bigquery_export.py), [command](../scripts/export_bigquery.py), [unit tests](../tests/test_bigquery_export.py), [Terraform resources](../infra/gcp-ai/bigquery.tf), [infrastructure tests](../infra/gcp-ai/tests/bigquery.tftest.hcl), and [dashboard SQL view](../infra/gcp-ai/sql/run_dashboard.sql).

Official documentation checked on 2026-10-29:

- [Import a local file](https://docs.cloud.google.com/bigquery/docs/samples/bigquery-load-from-file) and [Python Client 3.46.2](https://docs.cloud.google.com/python/docs/reference/bigquery/latest/google.cloud.bigquery.client.Client): binary file loads, fixed job IDs, location, and job completion.
- [Batch-loading permissions](https://docs.cloud.google.com/bigquery/docs/batch-loading-data): table load permissions and jobs.create.
- [BigQuery IAM](https://docs.cloud.google.com/bigquery/docs/access-control): resource-scoped grants and separation of data access from job execution.

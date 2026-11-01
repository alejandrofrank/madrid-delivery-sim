# Cost and SLO dashboard

Terraform provisions the `mds_analytics` dataset only with an active private live
environment. It is currently absent. Tables expire after 30 days and are deleted
on teardown; export any evidence that must survive a session. The public replay
uses recorded metrics and never queries BigQuery.

Completed order jobs append allowlisted operational rows using stable event IDs.
Views deduplicate retries and read only the last 30 days of partitions. Existing
`agent.model` spans supply token and price data; missing prices remain null.
Synthetic delivery/refund costs are EUR; model estimates are USD. Neither is a
Google Cloud invoice, and the currencies must not be added together.

## Looker Studio setup

Use the BigQuery connector in Looker Studio (the current documentation calls it
Data Studio). Select the dedicated project and `mds_analytics`, adding each view
below as a separate data source. Use viewer credentials: each approved viewer
needs BigQuery Job User on the query project and Data Viewer on this dataset.
Do not share the report publicly or give viewers write access. Connector queries
can incur BigQuery charges; configure refresh only for an active session.
[Google's connector and credential guide](https://docs.cloud.google.com/data-studio/connect-to-google-bigquery).

| View | Chart and fields | Interpretation |
| --- | --- | --- |
| `cost_per_order` | Run table: orders, delivered orders, delivery EUR/order, model USD/order, measured span count | Denominator is all attempted orders. Null model cost means missing evidence. |
| `recovery_time` | Disruption table: recovery seconds, unresolved, saved/lost, late, refunds, extra tokens/USD | Keep unresolved disruptions visible; do not coerce null recovery to zero. |
| `late_delivery_rate` | Run table and scorecard: late/delivered with known deadline, lost/attempted | Keep numerator and denominator beside the rate. Across runs, divide summed counts rather than averaging rates. |
| `token_spend_per_agent` | Agent/model table: input/output tokens, USD, model spans, unpriced spans | Flag unpriced spans and separate model names. |

Use a shared `run_id` filter. Prefer tables plus two rate scorecards over charts
that imply live traffic: these are completed-run snapshots. SQL sources are in
[`infra/production/sql`](../../infra/production/sql). Runtime identities have
append-only data permission; dashboard readers are a separate operator grant.

## Service-level objectives and response

Cloud Monitoring definitions in `infra/production/monitoring.tf` apply to the
public replay while its service exists:

| SLO | Target | Alert |
| --- | --- | --- |
| Request availability | 99% successful requests over 7 days | More than 10× error-budget burn over 15 minutes, sustained for 5 minutes |
| Request latency | 95% of requests below 2 seconds over 7 days | Same burn-rate threshold |

The optional configured email channel receives alerts. A short successful smoke
test does not establish an SLO. Intentional teardown removes both SLOs and alerts;
there is no 24/7 availability promise for this on-demand demo.

When an alert fires, first check whether the native spend cap paused Cloud Run.
Do not lift it automatically. Then inspect the service revision, errors and replay
integrity; roll back to the reviewed digest or end the session with `active=false`.
Treat stale/missing metrics as missing evidence. Simulation late-delivery and
recovery rates are operational outcomes, not these HTTP availability SLOs.

The Terraform definitions were created during the replay smoke and removed on
shutdown. SQL export and deduplication are tested locally; BigQuery execution and
an actual dashboard connection still require private live qualification.

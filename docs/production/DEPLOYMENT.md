# On-demand Google Cloud deployment

The environment is **off by default**. It is deployed for a demo or verification,
then removed. A successful replay deployment and teardown were verified on
2026-10-30 in `madrid-delivery-sim-261030`, Europe West 1. The recorded URL was
`https://mds-replay-4juwzn3u2a-ew.a.run.app`; it is intentionally unavailable while
off. Local `localhost:8010` remains independent.

## Costs and shutdown

The dedicated project uses the operator-selected billing account. Current settings
are a **EUR 3 native Cloud Run spend cap** and **EUR 4 monthly whole-project alert**.
This conservatively targets the requested USD 5 allowance; the account bills EUR.
The cap pauses Cloud Run automatically. It is not an exact total-spend guarantee:
enforcement is delayed, in-flight work can finish, and storage/fixed resources are
outside its protection. Caps use gross estimated spend before credits and reset
monthly. Never lift one automatically.

`active=false` removes Cloud Run services and jobs, Artifact Registry and its
images, optional SQL and Vector Search, optional BigQuery data/views, and live
database secrets. **Ephemeral live data is deleted**: export evidence before stop.
The project, API enablement, service identities, WIF, budgets, notification channel
and private versioned Terraform state remain. Those identities/APIs do not run
compute; the small state objects and retained provider logs can still incur storage
charges. This is intentionally not an always-on production data-retention policy.

Cloud SQL and Vector Search are opt-in and were **not activated** under the small
demo allowance. Their Terraform contracts and client boundaries are tested locally;
their live provisioning, database bootstrap and real Vertex query/IAM behavior still
require an explicitly funded qualification session. Do not describe them as deployed.

## Existing environment: bounded replay session

Use Bash, Terraform 1.9+, Docker, Python 3 and an authenticated Google Cloud CLI.
No service-account JSON keys are required. Initialize the backend if needed:

```bash
terraform -chdir=infra/production init \
  -backend-config=bucket=madrid-delivery-sim-261030-terraform \
  -backend-config=prefix=production
export MDS_BILLING_ACCOUNT='YOUR-CORTEXLABS-BILLING-ID'
bash scripts/production_session.sh 120
```

The script refuses to replace an existing active environment, verifies the native cap,
creates the disposable registry,
builds locally, checks the image without networking, pushes a digest, applies the
service and checks deterministic playback and write denial. It prints the URL,
waits at most 120 seconds, then tears down. Enter or Ctrl+C stops earlier. A killed
terminal/host or failed Terraform API request can prevent the trap; verify cleanup
and rerun the explicit stop command when needed:

```bash
terraform -chdir=infra/production plan -var=active=false -out=stop.tfplan
terraform -chdir=infra/production apply stop.tfplan
gcloud run services list --project=madrid-delivery-sim-261030 --region=europe-west1
gcloud run jobs list --project=madrid-delivery-sim-261030 --region=europe-west1
gcloud sql instances list --project=madrid-delivery-sim-261030
gcloud artifacts repositories list --project=madrid-delivery-sim-261030 --location=europe-west1
```

Always inspect the saved plan. Use `active=false` for ordinary stop; the project
has Terraform prevent-destroy protection. The GitHub pipeline cannot wake an absent
environment and does not manage Terraform or the state bucket.

## Fresh-project bootstrap

Copy `deployment.tfvars.example` to ignored `deployment.auto.tfvars`, fill the new
project ID and billing ID, and keep `active=false`. The backend bucket does not
exist yet, so bootstrap with this ignored local override:

```bash
cat > infra/production/bootstrap_override.tf <<'EOF'
terraform {
  backend "local" { path = "terraform.tfstate" }
}
EOF
terraform -chdir=infra/production init
terraform -chdir=infra/production plan -out=bootstrap.tfplan
terraform -chdir=infra/production apply bootstrap.tfplan
python3 scripts/cloud_run_cap.py --project "$PROJECT_ID" --billing-account "$MDS_BILLING_ACCOUNT"
rm -- infra/production/bootstrap_override.tf
terraform -chdir=infra/production init -migrate-state \
  -backend-config="bucket=$PROJECT_ID-terraform" -backend-config=prefix=production
```

Confirm the migrated remote state before retiring the local backup. State,
plans, credentials, extra `.env` files and private variables are ignored at every
depth. The pinned Google provider does not yet expose `spendCap`; the small
operator script manages that documented API field separately, verifies it, and
refuses to lift an enforced cap or overwrite an ambiguous budget.

## Release workflow and identities

Create a GitHub `production` environment restricted to main. Set environment
variables `GCP_PROJECT_ID`, `GCP_BILLING_ACCOUNT`, `GCP_WORKLOAD_IDENTITY_PROVIDER`
and `GCP_CI_SERVICE_ACCOUNT` from Terraform outputs/the operator's billing setting.
Dispatch `.github/workflows/deploy.yml` manually on main during a sufficiently long
active operator session (for example `bash scripts/production_session.sh 3600`).
The operator's session owns teardown, including when CI fails; CI itself cannot
create or destroy infrastructure. Stop sooner with Enter after the release check.
It requires successful full CI for the exact SHA, evaluates the reserved cohort
with five attempts per case, compares against a successful prior main release
artifact, checks the cap, builds and deploys an immutable replay image, and runs
the public smoke check. The first release creates a baseline without claiming a
quality comparison. Release evidence is stored as workflow artifacts for 90 days.

WIF checks repository/owner numeric IDs, main, the exact workflow and production
environment. CI can append images and update the existing replay service; it cannot
create cloud resources, change IAM, read Terraform state, change caps or deploy
the private live services. See [the trust model](TRUST-MODEL.md).

## Optional private live qualification

Set `enable_live=true` only for an explicitly budgeted session. First leave
`live_ready=false`: Terraform provisions SQL and four empty role-specific secrets.
After the controller permission design is complete, an operator must initialize
`delivery` using `delivery.simulation.initialize()`,
which applies all migrations, PostGIS/pgvector and the frozen street data. The
qualified bootstrap must create distinct database controller logins and populate each `mds-database-ROLE` secret
with a DSN using `/cloudsql/PROJECT:REGION:mds-live`. Runtime identities can read
only their own secret and connect only to that instance. Do not share the database
owner credential or upload it to Git. The API no longer runs migrations at startup.

The SQL controller bootstrap/grant procedure is an **implementation blocker**, not
just an unexecuted smoke check. Broad runtime role-management and blanket RLS
permissions were rejected during security review and are not included. The safe
controller boundary must be implemented and tested before turning on live mode:
the local lab provisions scoped agent logins dynamically and uses process-local
capability caches. Cloud workers have maximum one instance and zero automatic job
retries; this does **not** promise crash-safe resumption for every lab workflow.
The Madrid order clock has an advisory lock and persisted resume point. A failed
job's run remains inspectable; resume it explicitly with the same job/run ID rather
than creating another order flow. Completed order jobs can retry metrics export.

Only set `live_ready=true` after verifying those scoped logins and supplying a
digest-pinned full image and operator identities. The job uses the API controller
identity; its A2A requests go to separate dispatcher, restaurant and customer-service
identities with exact-audience ID tokens. Live model calls remain disabled by default.
Selecting a paid model additionally requires the existing provider admission setup.

The strict app verifier requires an audience-bound Google ID token; this release
does not supply a browser OAuth/IAP login flow. An authorized operator service
identity can use an authenticated HTTP client. Interactive browser login and
multi-instance lab capabilities remain follow-up work, not a public-demo dependency.

Vertex serving is a further independent `enable_vector_search=true` opt-in.
The index is 384-dimensional, streamed and scoped by opaque hashes; the final SQL
read remains authoritative. It has one billed serving replica until teardown.
See [semantic memory](SEMANTIC-MEMORY.md) and [dashboards](DASHBOARDS.md).

References: [native spend caps](https://docs.cloud.google.com/billing/docs/how-to/budget-api-spend-cap),
[Cloud Run service identity](https://docs.cloud.google.com/run/docs/authenticating/service-to-service),
[GitHub federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).

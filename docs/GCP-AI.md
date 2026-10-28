# Optional GCP judgement gateway

Architecture reading order: [exact agent implementation](AGENT-IMPLEMENTATION.md),
[Terraform/GCP component inventory](GCP-COMPONENTS.md), then
[enterprise decisions and gaps](ENTERPRISE-GCP.md). This document is the operations
runbook. Parked status below is the last live verification on 2026-10-25, not a
fresh status query on each documentation update. "Private" means IAM-authenticated
invocation here; the current service has network-reachable ingress.

The local city works without GCP. The optional switch sends only a bounded retry judgement to a private Cloud Run gateway using Vertex AI. Inventory, fulfillment, dispatch, couriers, movement, custody and SQL policy enforcement remain local and deterministic. This is a hosted judgement role, not a hosted fleet. A live deployment and UI verification were completed on 2026-10-24, followed by verified teardown on 2026-10-25. The project was restored on 2026-10-25 and is parked with billing disabled. The cloud demo is currently off; see [verification](GCP-VERIFICATION.md).

`infra/gcp-ai` is a standalone Terraform root with its own local state. It owns
one persistent, dedicated project, with optional runtime infrastructure. It has no
Scrapmarket dependencies. Never import a shared project or reuse another root's
state. The restored simulation project is imported into its original state.
Project deletion is blocked by both `deletion_policy = "PREVENT"` and
`lifecycle.prevent_destroy`. Keep private variables, plans and state out of Git.

## Daily commands

From the repository root (Python 3.12+ with only its standard library):

```bash
python3 scripts/gcp_demo.py start
python3 scripts/gcp_demo.py status
python3 scripts/gcp_demo.py stop
```

`make gcp-start`, `make gcp-status` and `make gcp-stop` are equivalent aliases.
The city, homes, stores, stock, orders, queues, roles, memory and rules run locally
in Docker. Building the city and testing deterministic agent/event behavior
requires no GCP deployment or inference. Leave the project parked for that work.

`start` explicitly links billing, creates the image repository, builds/pushes the
small gateway image locally, deploys its immutable digest and reconnects the
local app with a read-only ADC mount. It makes GCP AI available in Configure;
it does not select it or change saved runs. Startup itself makes no model calls.
Image storage and Cloud Run usage can incur charges while enabled. Model charges
begin only when an explicitly cloud-enabled run asks the recovery judge for a
decision. Every stock reservation, route movement and queue event remains local.
Use traces to compare local rules against those selected model decisions.

`stop` resets the app to local mode first, deletes the gateway and stored images
with billing still linked, then unlinks billing. Project, APIs, service accounts,
custom role and free IAM bindings remain. Repeated stop on a parked project does
not relink billing. A deletion failure prevents billing unlinking so cleanup can
be retried. A local app reset failure is reported after attempting cloud cleanup.

`status` reads project lifecycle, billing, actual Cloud Run services, Terraform
runtime resources and local provider availability. With billing enabled it also
lists repositories; otherwise that check is explicitly unavailable. It makes no
model calls and never enables billing to answer a status request. A parked result
is not a billing invoice and does not erase earlier charges.

Prerequisites: gcloud/Terraform/Docker on PATH, Docker running, existing protected
project/IAM state in this root, the ignored `infra/gcp-ai/deploy.auto.tfvars.json`,
and local ADC (`gcloud auth application-default login`). The CLI reads the selected
project/region from that private file. `GCP_ADC_DIRECTORY` can override the usual
local ADC directory; no keys are downloaded. Commands work from any working
directory when invoked with the script's path. Use `APP_PORT` if not 8010.

Commands validate saved plans before applying: foundation changes, replacements,
unexpected resources and another project's runtime are rejected. Desired flags
are saved only after successful apply to the ignored
`zz-demo.auto.tfvars.json`, which overrides the bootstrap values on future plans.
Saved plans remain ignored. Start/stop share a lock; if a process is forcibly
terminated, inspect status and confirm it has stopped before removing
`infra/gcp-ai/.demo-command.lock`. If startup fails after creating resources,
inspect status and run stop. Neither command runs a model evaluation automatically.

## Manual bootstrap (first setup or troubleshooting)

An operator needs project creation and billing-link permissions, Terraform, gcloud and Docker. Select a supported model and Vertex location explicitly; no model or region is assumed. Set `project_id`, `billing_account`, `region`, `vertex_region`, `vertex_model`, and optionally one of `org_id` or `folder_id` in a private tfvars file. Billing, runtime infrastructure and the gateway all default off. Terraform 1.7+ is needed for the mocked lifecycle tests.

1. From `infra/gcp-ai`, run `terraform init`, review `terraform plan`, then `terraform apply`. With all enable flags false this keeps the protected project, six API registrations, both keyless service accounts, the prediction-only custom role and scoped IAM bindings. Set `invoker_members` to explicit operators in the private variables to configure keyless caller impersonation. To bootstrap the repository, set `enable_billing=true`, `enable_runtime=true`, `enable_gateway=false`, review and apply again. This links billing and creates the image repository without Cloud Run; existing identities are reused.
2. From the repository root, build `infra/gcp-ai/Dockerfile` and push the image to the `image_repository` output using an operator's authenticated Docker registry login. For example, `docker build -f infra/gcp-ai/Dockerfile -t REGION-docker.pkg.dev/PROJECT/judgement/gateway:VERSION .` then `docker push` that same tag. Prefer its immutable digest for `gateway_image`. The image must be this gateway, not an arbitrary server.
3. Set `enable_gateway=true`, `gateway_image` to that image, and `invoker_members` to explicit operator principals such as `user:you@example.com`. Review and apply again. There is no `allUsers` binding. Terraform retains the dedicated keyless caller service account and grants only listed operators permission to mint its tokens.
4. Set the server environment variable `DELIVERY_GCP_AI_ENDPOINT` to the `gateway_url` output and select GCP AI mode in the city configuration. The mode is frozen per session. Local mode remains the default. Changing settings affects new sessions only.

Runtime authentication uses Application Default Credentials and an audience-bound Cloud Run ID token. Run `gcloud auth application-default login` locally, then set `DELIVERY_GCP_AI_CALLER_SERVICE_ACCOUNT` to the `caller_service_account` Terraform output. The adapter uses your ADC to impersonate that account and mint an ID token without a downloaded key. Terraform grants listed operators `roles/iam.serviceAccountTokenCreator` only on this caller account and grants that account `roles/run.invoker` only on the gateway. On Cloud Run, attached credentials can supply tokens directly when attached to the authorized caller account. Never use service-account key files or API keys. The gateway runtime receives a project-owned custom role containing only `aiplatform.endpoints.predict` in this dedicated project. Both service accounts, the custom role and their identity-level IAM bindings are owned by this root and retained during routine shutdown. The Cloud Run invocation binding belongs to the deleted service and is recreated with it. Operator identities outside the project are not deleted.

## Contract and limits

`CloudJudge(endpoint).review(context, memory, candidate=proposal)` returns `Judgment`: `decision` is exactly `approve_retry` or `deny_retry`, with a short `reason`, configured `model`, and input/output token counts. The caller reserves its durable model budget **before** invoking this adapter, records the decision, and denies on any authentication, transport, validation or budget error. The caller may approve only its already computed candidate; SQL independently checks deadline, retry and custody invariants.

Only numeric allowlisted job facts, numeric candidate summary (`estimated_seconds`, `remaining_seconds`, `route_nodes`) and memory entry count leave the local application. The gateway adds a reviewed, synthetic seven-meal supermarket snapshot as read-only business reference. Full roads, names, basket IDs, courier IDs, arbitrary prompts and memory bodies are excluded. This gateway has no database, queue, browser or arbitrary tool interface. A request is bounded to 8192 serialized bytes, the client waits 30 seconds, Vertex has a 5 second token-count timeout and 15 second generation timeout, output including reported reasoning is limited to 256 tokens, and responses are size/schema checked. Retries are not automatic. Cloud Run scales to zero and at most one instance, with four concurrent requests. These are usage bounds, not a guaranteed monetary cap; model pricing and other project usage can create charges. Choose a model with known price/context limits and use the local durable budget as the admission gate.

## Manual shutdown (the stop command runs these phases)

Routine shutdown uses **apply**, not `terraform destroy`. Keep the project and
its state. In `infra/gcp-ai`, run these two phases in order, reviewing each plan:

```bash
terraform plan -var='enable_billing=true' -var='enable_runtime=false' -var='enable_gateway=false' -out=stop-runtime.tfplan
terraform apply stop-runtime.tfplan
terraform plan -var='enable_billing=false' -var='enable_runtime=false' -var='enable_gateway=false' -out=park.tfplan
terraform apply park.tfplan
```

Phase one deletes Cloud Run (including revisions), its service-specific invocation
binding, and repository/images. The free IAM foundation stays in state: both
service accounts, the prediction-only custom role, its runtime binding, and
operator impersonation permissions on the caller.
Billing must stay linked until deletion finishes: Artifact Registry management
requests can fail with billing disabled. Phase two unlinks billing. For manual operation, save
all three flags as false in the private override so the next ordinary plan stays
parked. The command writes its own `zz-demo.auto.tfvars.json` after successful apply. Clear the obsolete gateway image digest; rebuild and push it
when starting another session. Do not unlink billing first or apply all three
false directly from an active deployment.

API registrations can remain enabled without provisioned runtime resources;
`disable_on_destroy=false` avoids service dependency failures. A parked state
tracks the protected project, six API registrations and five IAM resources (12
resources total). Verify a no-change plan, `ACTIVE` project,
`billingEnabled: false`, and absence of Cloud Run services. Confirm repository
removal during phase one; once billing is disabled its list API may be unavailable.
Recreate the local app with base `compose.yaml` to remove cloud credentials and
endpoint settings. Historical charges and retained platform audit records are
not erased. This switch controls this root's resources, not resources manually
created elsewhere or unrelated projects.

Full project deletion requires a separate explicit decision and deliberate removal
of both protection settings. An ordinary destroy plan must fail on `prevent_destroy`.

[Google restoration and billing behavior](https://docs.cloud.google.com/resource-manager/docs/delete-restore-projects)
and [Terraform project deletion protection](https://registry.terraform.io/providers/hashicorp/google/7.14.1/docs/resources/google_project).

## Verification and sources

The adapter tests use mocked transport and never contact GCP. `terraform fmt`, provider initialization and `terraform validate` pass. Live deployment evidence and initial/final eval outcomes are recorded in [verification](GCP-VERIFICATION.md).

Official references: [Cloud Run service identity](https://docs.cloud.google.com/run/docs/configuring/services/service-identity), [authenticated invocation and ID tokens](https://docs.cloud.google.com/run/docs/authenticating/service-to-service), [Vertex REST generation](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/quickstart), [Vertex response and token metadata](https://cloud.google.com/vertex-ai/generative-ai/docs/reference/rest/v1/GenerateContentResponse), [Terraform project deletion policy](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/google_project), [Terraform Cloud Run deletion protection](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/cloud_run_v2_service).

## Local Docker opt-in

The regular `compose.yaml` never mounts cloud credentials. For the explicit GCP
option, set `DELIVERY_GCP_AI_ENDPOINT`, `DELIVERY_GCP_AI_CALLER_SERVICE_ACCOUNT`,
and `GCP_ADC_DIRECTORY` (the local directory containing the ADC file created by
`gcloud auth application-default login`). Then run
`docker compose -f compose.yaml -f compose.gcp-ai.yaml up -d --build app`.
The override mounts that directory read-only; never copy ADC into the repository
or image. Select GCP AI recovery judge in Configure and save for the next run.
Each cloud-enabled session freezes its gateway origin. Reverting to local rules
affects new sessions and makes no inference requests. The UI switch does not
apply or destroy Terraform. Use the isolated Terraform root for lifecycle changes.


## Guided redeployment and inspection

Keep the demo local until an explicit cloud session is wanted. Reuse the restored
project ID and original standalone state. The original service accounts and custom
role were recovered and imported on 2026-10-25; their unique IDs are unchanged.
Routine shutdown now retains these identities, so no repeated recovery is needed.
Enable billing and runtime first with the gateway off, rebuild/push the deleted
image, then enable the gateway with a new
immutable digest. Follow the bootstrap steps above and refresh the local compose
override with the new endpoint. Never reuse Scrapmarket state.

For the next guided session, inspect these in order:

1. **Ownership:** review the Terraform plan, dedicated project, billing link and all
   resources. Confirm no shared-project changes or public invocation binding.
2. **Identity:** inspect the runtime prediction-only role, caller's service-specific
   invocation permission, and keyless authentication. Confirm anonymous requests fail.
3. **Data boundary:** inspect the seven-meal synthetic snapshot and actual serialized
   request. Confirm names, customer details and private memory bodies stay local.
4. **Agent boundary:** follow a stock reservation through queued fulfillment and
   dispatch. Inspect role-scoped tools, memory and SQL enforcement.
5. **Model and cost:** inspect the configured model, scale limits, per-run call/token
   reservations and returned usage. Explain why those controls are not a dollar cap.
6. **Evals:** run the fixed recovery cases, distinguish policy-gate answers from actual
   model answers, and compare with the preserved initial failure and guarded results.
7. **Live switch:** run the explicit `scripts/verify_gcp_switch.py --live-cloud`
   verification. Inspect one cloud decision and the paired local run with zero calls,
   including stock, custody and retry invariants.
8. **Cleanup:** delete runtime resources with billing linked, then unlink billing.
   Verify the protected project remains active and state retains project/APIs/IAM,
   and billing is disabled. Recreate the app using base compose.

Retain sanitized receipts and commit verified changes. Keep credentials, Terraform
state, private variables and saved plans out of Git.


## Recovered IAM evidence

The original caller (`108780209802092054377`) and runtime
(`105662098881414929441`) were undeleted by numeric ID, and
`boundedJudgePredict` was undeleted and imported. It still grants only
`aiplatform.endpoints.predict`. Recovery creates no service-account keys.
See [IAM recovery receipt](evidence/gcp-iam-recovered.json).
Google documents that [undeleting preserves the original identity](https://docs.cloud.google.com/iam/docs/service-accounts-delete-undelete).

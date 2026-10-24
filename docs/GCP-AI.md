# Optional GCP judgement gateway

The local city works without GCP. The optional switch sends only a bounded retry judgement to a private Cloud Run gateway using Vertex AI. Inventory, fulfillment, dispatch, couriers, movement, custody and SQL policy enforcement remain local and deterministic. This is a hosted judgement role, not a hosted fleet. A live deployment and UI verification were completed on 2026-10-24, followed by verified teardown on 2026-10-25. The project was restored on 2026-10-25 and is parked with billing disabled. The cloud demo is currently off; see [verification](GCP-VERIFICATION.md).

`infra/gcp-ai` is a standalone Terraform root with its own local state. It owns
one persistent, dedicated project, with optional runtime infrastructure. It has no
Scrapmarket dependencies. Never import a shared project or reuse another root's
state. The restored simulation project is imported into its original state.
Project deletion is blocked by both `deletion_policy = "PREVENT"` and
`lifecycle.prevent_destroy`. Keep private variables, plans and state out of Git.

## Explicit bootstrap

An operator needs project creation and billing-link permissions, Terraform, gcloud and Docker. Select a supported model and Vertex location explicitly; no model or region is assumed. Set `project_id`, `billing_account`, `region`, `vertex_region`, `vertex_model`, and optionally one of `org_id` or `folder_id` in a private tfvars file. Billing, runtime infrastructure and the gateway all default off. Terraform 1.7+ is needed for the mocked lifecycle tests.

1. From `infra/gcp-ai`, run `terraform init`, review `terraform plan`, then `terraform apply`. With all enable flags false this keeps only the protected project. To bootstrap the repository, set `enable_billing=true`, `enable_runtime=true`, `enable_gateway=false`, review and apply again. This enables APIs and creates the image repository and scoped identities without Cloud Run.
2. From the repository root, build `infra/gcp-ai/Dockerfile` and push the image to the `image_repository` output using an operator's authenticated Docker registry login. For example, `docker build -f infra/gcp-ai/Dockerfile -t REGION-docker.pkg.dev/PROJECT/judgement/gateway:VERSION .` then `docker push` that same tag. Prefer its immutable digest for `gateway_image`. The image must be this gateway, not an arbitrary server.
3. Set `enable_gateway=true`, `gateway_image` to that image, and `invoker_members` to explicit operator principals such as `user:you@example.com`. Review and apply again. There is no `allUsers` binding. Terraform creates a dedicated keyless caller service account and grants only listed operators permission to mint its tokens.
4. Set the server environment variable `DELIVERY_GCP_AI_ENDPOINT` to the `gateway_url` output and select GCP AI mode in the city configuration. The mode is frozen per session. Local mode remains the default. Changing settings affects new sessions only.

Runtime authentication uses Application Default Credentials and an audience-bound Cloud Run ID token. Run `gcloud auth application-default login` locally, then set `DELIVERY_GCP_AI_CALLER_SERVICE_ACCOUNT` to the `caller_service_account` Terraform output. The adapter uses your ADC to impersonate that account and mint an ID token without a downloaded key. Terraform grants listed operators `roles/iam.serviceAccountTokenCreator` only on this caller account and grants that account `roles/run.invoker` only on the gateway. On Cloud Run, attached credentials can supply tokens directly when attached to the authorized caller account. Never use service-account key files or API keys. The gateway runtime receives a project-owned custom role containing only `aiplatform.endpoints.predict` in this dedicated project. Both service accounts and their IAM bindings are owned by this root and removed at teardown. Operator identities outside the project are not deleted.

## Contract and limits

`CloudJudge(endpoint).review(context, memory, candidate=proposal)` returns `Judgment`: `decision` is exactly `approve_retry` or `deny_retry`, with a short `reason`, configured `model`, and input/output token counts. The caller reserves its durable model budget **before** invoking this adapter, records the decision, and denies on any authentication, transport, validation or budget error. The caller may approve only its already computed candidate; SQL independently checks deadline, retry and custody invariants.

Only numeric allowlisted job facts, numeric candidate summary (`estimated_seconds`, `remaining_seconds`, `route_nodes`) and memory entry count leave the local application. The gateway adds a reviewed, synthetic seven-meal supermarket snapshot as read-only business reference. Full roads, names, basket IDs, courier IDs, arbitrary prompts and memory bodies are excluded. This gateway has no database, queue, browser or arbitrary tool interface. A request is bounded to 8192 serialized bytes, the client waits 30 seconds, Vertex has a 5 second token-count timeout and 15 second generation timeout, output including reported reasoning is limited to 256 tokens, and responses are size/schema checked. Retries are not automatic. Cloud Run scales to zero and at most one instance, with four concurrent requests. These are usage bounds, not a guaranteed monetary cap; model pricing and other project usage can create charges. Choose a model with known price/context limits and use the local durable budget as the admission gate.

## Park the project after a demo

Routine shutdown uses **apply**, not `terraform destroy`. Keep the project and
its state. In `infra/gcp-ai`, run these two phases in order, reviewing each plan:

```powershell
terraform plan -var='enable_billing=true' -var='enable_runtime=false' -var='enable_gateway=false' -out=stop-runtime.tfplan
terraform apply stop-runtime.tfplan
terraform plan -var='enable_billing=false' -var='enable_runtime=false' -var='enable_gateway=false' -out=park.tfplan
terraform apply park.tfplan
```

Phase one deletes Cloud Run (including revisions), invocation permissions,
repository/images, runtime/caller accounts and custom inference permissions.
Billing must stay linked until deletion finishes: Artifact Registry management
requests can fail with billing disabled. Phase two unlinks billing. Then save
all three flags as false in the ignored private variables so the next ordinary
plan stays parked. Clear the obsolete gateway image digest; rebuild and push it
when starting another session. Do not unlink billing first or apply all three
false directly from an active deployment.

API registrations can remain enabled without provisioned runtime resources;
`disable_on_destroy=false` avoids service dependency failures. A parked state
tracks only the protected project. Verify a no-change plan, `ACTIVE` project,
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
project ID and original standalone state. The previous full teardown also deleted the service accounts and custom role.
Before reusing their names, recover any soft-deleted identities/role with Google's
undelete operations and import them into their indexed Terraform addresses; otherwise
use new identity/role names. Do not assume an immediate same-name recreation works.
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
   Verify the protected project remains active, state contains only the project,
   and billing is disabled. Recreate the app using base compose.

Retain sanitized receipts and commit verified changes. Keep credentials, Terraform
state, private variables and saved plans out of Git.

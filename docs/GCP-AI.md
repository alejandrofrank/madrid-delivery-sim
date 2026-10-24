# Optional GCP judgement gateway

The local city works without GCP. The optional switch sends only a bounded retry judgement to a private Cloud Run gateway using Vertex AI. Inventory, fulfillment, dispatch, couriers, movement, custody and SQL policy enforcement remain local and deterministic. This is a hosted judgement role, not a hosted fleet. Nothing in this change deploys cloud resources.

`infra/gcp-ai` is a standalone Terraform root with its own local state. It creates a **new dedicated project**, billing link, APIs, image repository, runtime service account and optional private Cloud Run service. It has no imports, remote-state dependencies or references to scrapmarket. Never run this root against an existing shared project or reuse another root's state. Keep state and variable files outside version control and retain the state until teardown succeeds.

## Explicit bootstrap

An operator needs project creation and billing-link permissions, Terraform, gcloud and Docker. Select a supported model and Vertex location explicitly; no model or region is assumed. Set `project_id`, `billing_account`, `region`, `vertex_region`, `vertex_model`, and optionally one of `org_id` or `folder_id` in a private tfvars file. The gateway defaults off.

1. From `infra/gcp-ai`, run `terraform init`, review `terraform plan`, then `terraform apply`. This provisions the isolated project and repository, without Cloud Run.
2. Build this directory's Dockerfile and push the image to the `image_repository` output using an operator's authenticated Docker registry login. For example, `docker build -t REGION-docker.pkg.dev/PROJECT/judgement/gateway:VERSION .` then `docker push` that same tag. Prefer its immutable digest for `gateway_image`. The image must be this gateway, not an arbitrary server.
3. Set `enable_gateway=true`, `gateway_image` to that image, and `invoker_members` to explicit operator principals such as `user:you@example.com`. Review and apply again. There is no `allUsers` binding. Terraform creates a dedicated keyless caller service account and grants only listed operators permission to mint its tokens.
4. Set the server environment variable `DELIVERY_GCP_AI_ENDPOINT` to the `gateway_url` output and select GCP AI mode in the city configuration. The mode is frozen per session. Local mode remains the default. Changing settings affects new sessions only.

Runtime authentication uses Application Default Credentials and an audience-bound Cloud Run ID token. Run `gcloud auth application-default login` locally, then set `DELIVERY_GCP_AI_CALLER_SERVICE_ACCOUNT` to the `caller_service_account` Terraform output. The adapter uses your ADC to impersonate that account and mint an ID token without a downloaded key. Terraform grants listed operators `roles/iam.serviceAccountTokenCreator` only on this caller account and grants that account `roles/run.invoker` only on the gateway. On Cloud Run, attached credentials can supply tokens directly when attached to the authorized caller account. Never use service-account key files or API keys. The gateway runtime receives only `roles/aiplatform.user` in this dedicated project. Both service accounts and their IAM bindings are owned by this root and removed at teardown. Operator identities outside the project are not deleted.

## Contract and limits

`CloudJudge(endpoint).review(context, memory, candidate=proposal)` returns `Judgment`: `decision` is exactly `approve_retry` or `deny_retry`, with a short `reason`, configured `model`, and input/output token counts. The caller reserves its durable model budget **before** invoking this adapter, records the decision, and denies on any authentication, transport, validation or budget error. The caller may approve only its already computed candidate; SQL independently checks deadline, retry and custody invariants.

Only numeric allowlisted job facts, numeric candidate summary (`estimated_seconds`, `remaining_seconds`, `route_nodes`) and memory entry count leave the machine. Full roads, names, basket IDs, courier IDs, arbitrary prompts and memory bodies are excluded. This gateway has no database, queue, browser or arbitrary tool interface. A request is bounded to 8192 serialized bytes, the client waits 30 seconds, Vertex has a 5 second token-count timeout and 15 second generation timeout, output is limited to 256 tokens, and responses are size/schema checked. Retries are not automatic. Cloud Run scales to zero and at most one instance, with four concurrent requests. These are usage bounds, not a guaranteed monetary cap; model pricing and other project usage can create charges. Choose a model with known price/context limits and use the local durable budget as the admission gate.

## Teardown

From this exact root and original state, run `terraform destroy` and review the plan: it removes the gateway, IAM bindings, account, repository/images and **deletes the dedicated project** (`deletion_policy = "DELETE"`; Cloud Run deletion protection is off). No separate cloud-console cleanup is intended. Terraform retains the local state files; it does not delete local source, images or caller identities outside this project. Google project deletion is asynchronous and recoverable during its platform retention window; accrued billing and platform audit retention are not erased. Organization policies, deletion liens, lost permissions or missing state can block deletion and must be resolved before claiming cleanup is complete. Do not discard the state first.

## Verification and sources

The adapter tests use mocked transport and never contact GCP. `terraform fmt`, provider initialization and `terraform validate` pass. No apply, deploy, cloud credential lookup or cloud inference was executed.

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

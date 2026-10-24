# GCP deployment verification — 2026-10-24

## Deployment and data boundary

A new dedicated project, `mds-ai-judge-261024-c7b4`, was provisioned from
`infra/gcp-ai` using the operator-selected billing account. No Scrapmarket project,
Terraform state or resources were modified. Cloud Run is in `europe-west1`;
Vertex uses the explicitly selected `global` endpoint. This is not an EU-only
inference residency claim. Only synthetic data was sent.

Ready revision: `judgement-00002-92k`. Immutable image:
`sha256:71834c8a002596752dd560c957ae75dae86041c582467805b6f3473292bbdd15`.
Model: `gemini-3.5-flash-lite`, minimal thinking. Prompt version:
`recovery-v2-seven-meals`. Snapshot SHA-256:
`5be219156af219ac97f41dd53e96024107e5eb68457da14cd3015c1c8d914f19`.
The snapshot contains seven meals, 17 ingredients and three fictional supermarkets.
It is reviewed read-only context; the judge does not perform procurement.

## Eval findings and repair

The initial live run passed 4/6 cases: five valid model responses, one provider
error, and one unsafe model approval when required facts were missing. The SQL
executor already retained independent policy enforcement. We preserved this result
rather than treating deployment success as model correctness.

We added a deterministic gateway preflight for missing facts, absent candidates,
retry exhaustion, deadline and route-cost constraints. Final system results:
6/6 cases passed, zero provider errors and zero hard-policy violations. This was
**one model decision and five policy-gate denials**, not six LLM decisions.
Six toy cases do not establish general model quality, a production SLO, or business
uplift over rules. See the [initial](evidence/gcp-judge-initial.json) and
[guarded](evidence/gcp-judge-guarded.json) receipts.

The guarded eval used 2,150 input and 35 output tokens. At the documented global
rates of $0.30 / $2.50 per million input/output tokens, its successful model usage
is estimated at $0.0007325. This excludes failed/unreported generations, earlier
probes, Cloud Run, storage, logging, taxes and currency conversion. It is not an
invoice or project-wide cost cap. [Google pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

## End-to-end UI switch

The explicit live-cloud script `scripts/verify_gcp_switch.py --live-cloud` configured
seed 71, 15 minutes of demand, four orders/hour, traffic 1, dropout intensity 0.4,
and three couriers based at one shop. The seed naturally withdraws bike-1 at
simulated second 694; no incident was injected after session creation.

The GCP-mode run `fe8fbad6-103f-42ff-8fd1-1e12e384cb02` recorded one actual model
approval, one durable 8,448-token reservation and no fallback. The paired local-mode
run `95057578-594a-42ed-b2e1-2862104f139e` recorded zero model calls. All stock,
assignment, custody, retry-approval and budget invariants passed; browser errors
were empty. [UI verification receipt](evidence/gcp-switch-verification.json).

Unauthenticated invocation returned 403; authenticated malformed input returned
422. Neither negative check invokes the model. The caller can invoke only this
service; the runtime custom role contains only `aiplatform.endpoints.predict`.
No service-account keys were created. [Negative checks](evidence/gcp-negative-checks.json).

## Teardown coverage

A reviewed `terraform plan -destroy` contains exactly 15 deletions, covering the
service and revisions, invocation IAM, custom role and prediction binding, both
service accounts, repository/images, enabled-service resources, and the dedicated
project. Every planned resource belongs to this project. Project deletion owns
implicit service agents and other platform-created project children. No shared
billing account or operator identity is deleted.

**Teardown executed on 2026-10-25:** Terraform reported 15 destroyed resources;
`terraform state list` is empty. Google reports the dedicated project as
`DELETE_REQUESTED`, so final project erasure remains asynchronous and subject to
platform retention. The local app is healthy with `local: true`, `gcp_ai: false`
and the cloud credential override removed. Scrapmarket was not touched.
[Actual teardown receipt](evidence/gcp-teardown-result.json).
The earlier [plan receipt](evidence/gcp-teardown-plan.json) records the pre-execution check.

## Enterprise interpretation

The useful interview evidence is controlled rollout and a documented failure/repair,
not a claim that an LLM is necessary for numeric feasibility. Keep local rules as the
baseline and default. Before exposing more users, add gateway-wide admission budgets,
held-out business evals, stronger release automation, recovery SLOs and finance
reconciliation. [Architecture and tradeoffs](ENTERPRISE-GCP.md).

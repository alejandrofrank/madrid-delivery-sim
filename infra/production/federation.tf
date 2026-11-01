resource "google_iam_workload_identity_pool" "github" {
  project                   = google_project.app.project_id
  workload_identity_pool_id = "mds-github"
  display_name              = "madrid-delivery-sim CI"
  depends_on                = [google_project_service.api]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = google_project.app.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository_id" = "assertion.repository_id"
  }
  attribute_condition = join(" && ", [
    "assertion.repository_id == '${var.github_repository_id}'",
    "assertion.repository_owner_id == '${var.github_owner_id}'",
    "assertion.ref == 'refs/heads/main'",
    "assertion.sub == 'repo:${var.github_repository}:environment:production'",
    "assertion.workflow_ref == '${var.github_repository}/.github/workflows/deploy.yml@refs/heads/main'",
  ])
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
}

resource "google_service_account_iam_member" "federation" {
  service_account_id = google_service_account.role["ci"].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}

resource "google_artifact_registry_repository_iam_member" "ci_images" {
  count      = var.active ? 1 : 0
  project    = google_project.app.project_id
  location   = var.region
  repository = google_artifact_registry_repository.app[0].repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.role["ci"].email}"
}

resource "google_project_iam_custom_role" "deploy" {
  project     = google_project.app.project_id
  role_id     = "mdsDeployService"
  title       = "Update existing Madrid services"
  permissions = ["run.services.get", "run.services.update", "run.services.getIamPolicy"]
}

resource "google_project_iam_custom_role" "operations" {
  project     = google_project.app.project_id
  role_id     = "mdsReadOperations"
  title       = "Wait for Madrid deployment"
  permissions = ["run.operations.get"]
}

resource "google_project_iam_member" "ci_operations" {
  project = google_project.app.project_id
  role    = google_project_iam_custom_role.operations.name
  member  = "serviceAccount:${google_service_account.role["ci"].email}"
}

resource "google_service_account_iam_member" "ci_attach_replay" {
  service_account_id = google_service_account.role["replay"].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.role["ci"].email}"
}

resource "google_cloud_run_v2_service_iam_member" "ci_replay" {
  count    = var.active && var.replay_image != "" ? 1 : 0
  project  = google_project.app.project_id
  location = var.region
  name     = google_cloud_run_v2_service.replay[0].name
  role     = google_project_iam_custom_role.deploy.name
  member   = "serviceAccount:${google_service_account.role["ci"].email}"
}

output "workload_identity_provider" { value = google_iam_workload_identity_pool_provider.github.name }
output "ci_service_account" { value = google_service_account.role["ci"].email }

resource "google_project_iam_custom_role" "cap_reader" {
  project     = google_project.app.project_id
  role_id     = "mdsReadOwnBudget"
  title       = "Verify the project spending cap without changing it"
  permissions = ["billing.resourcebudgets.read", "resourcemanager.projects.get", "serviceusage.services.use"]
}
resource "google_project_iam_member" "cap_reader" {
  project = google_project.app.project_id
  role    = google_project_iam_custom_role.cap_reader.name
  member  = "serviceAccount:${google_service_account.role["ci"].email}"
}

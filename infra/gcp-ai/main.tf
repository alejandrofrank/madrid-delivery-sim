terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
  # Deliberately local and unique; never use another project's backend/state.
  backend "local" { path = "terraform.tfstate" }
}

provider "google" {}

resource "google_project" "ai" {
  project_id          = var.project_id
  name                = "Madrid simulation AI"
  billing_account     = var.enable_billing ? var.billing_account : null
  org_id              = var.org_id
  folder_id           = var.folder_id
  auto_create_network = false
  deletion_policy     = "PREVENT"
  labels              = { application = "madrid-delivery-sim", component = "optional-ai" }
  lifecycle {
    prevent_destroy = true
    precondition {
      condition     = !var.enable_runtime || var.enable_billing
      error_message = "Runtime requires enable_billing=true. Delete runtime first, then disable billing in a second apply."
    }
    precondition {
      condition     = !var.enable_gateway || var.enable_runtime
      error_message = "Gateway requires enable_runtime=true; turn both flags off to park the project."
    }
    precondition {
      condition     = !(var.enable_analytics || var.enable_cloud_trace) || var.enable_billing
      error_message = "Cloud observability requires enable_billing=true. Export retained analytics and explicitly disable observability before unlinking billing."
    }
  }
}

resource "google_project_service" "api" {
  for_each = toset([
    "run.googleapis.com", "artifactregistry.googleapis.com", "aiplatform.googleapis.com",
    "iam.googleapis.com", "iamcredentials.googleapis.com", "cloudresourcemanager.googleapis.com"
  ])
  project            = google_project.ai.project_id
  service            = each.value
  disable_on_destroy = false # Enabled APIs persist without runtime resources or a billing link.
}

resource "google_artifact_registry_repository" "images" {
  count         = var.enable_runtime ? 1 : 0
  project       = google_project.ai.project_id
  location      = var.region
  repository_id = "judgement"
  format        = "DOCKER"
  depends_on    = [google_project_service.api]
}

resource "google_service_account" "judge" {
  count        = 1 # Persistent, non-billable IAM identity or binding.
  project      = google_project.ai.project_id
  account_id   = "judgement-runtime"
  display_name = "Bounded Vertex judgement gateway"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_custom_role" "judge_predict" {
  count       = 1 # Persistent, non-billable IAM identity or binding.
  project     = google_project.ai.project_id
  role_id     = "boundedJudgePredict"
  title       = "Bounded judge model inference"
  permissions = ["aiplatform.endpoints.predict"]
  depends_on  = [google_project_service.api]
}

resource "google_project_iam_member" "vertex" {
  count   = 1 # Persistent, non-billable IAM identity or binding.
  project = google_project.ai.project_id
  role    = google_project_iam_custom_role.judge_predict[0].name
  member  = "serviceAccount:${google_service_account.judge[0].email}"
}

resource "google_service_account" "caller" {
  count        = 1 # Persistent, non-billable IAM identity or binding.
  project      = google_project.ai.project_id
  account_id   = "judgement-caller"
  display_name = "Keyless local judgement caller"
  depends_on   = [google_project_service.api]
}

# Native ADK inference has its own keyless identity, retained when billing is parked.
resource "google_service_account" "restaurant" {
  project      = google_project.ai.project_id
  account_id   = "restaurant-adk"
  display_name = "Scoped restaurant Vertex inference"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_member" "restaurant_predict" {
  project = google_project.ai.project_id
  role    = google_project_iam_custom_role.judge_predict[0].name
  member  = "serviceAccount:${google_service_account.restaurant.email}"
}

resource "google_service_account_iam_binding" "restaurant_tokens" {
  service_account_id = google_service_account.restaurant.name
  role               = "roles/iam.serviceAccountTokenCreator"
  members            = var.invoker_members
}

resource "google_service_account_iam_binding" "caller_tokens" {
  count              = 1 # Persistent, non-billable IAM identity or binding.
  service_account_id = google_service_account.caller[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  members            = var.invoker_members
}

resource "google_cloud_run_v2_service" "judge" {
  count               = var.enable_gateway ? 1 : 0
  project             = google_project.ai.project_id
  name                = "judgement"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL" # IAM-authenticated local clients can reach it.
  scaling {
    min_instance_count = 0
    max_instance_count = 1
  }
  template {
    service_account                  = google_service_account.judge[0].email
    timeout                          = "35s"
    max_instance_request_concurrency = 4
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    containers {
      image = var.gateway_image
      resources {
        cpu_idle          = true
        startup_cpu_boost = false
        limits            = { cpu = "1", memory = "512Mi" }
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = google_project.ai.project_id
      }
      env {
        name  = "VERTEX_REGION"
        value = var.vertex_region
      }
      env {
        name  = "VERTEX_MODEL"
        value = var.vertex_model
      }
    }
  }
  lifecycle {
    precondition {
      condition     = !var.enable_gateway || (var.gateway_image != "" && length(var.invoker_members) > 0)
      error_message = "Enabled gateway requires a built image and explicit invoker principals."
    }
  }
  depends_on = [google_project_service.api, google_project_iam_member.vertex]
}

resource "google_cloud_run_v2_service_iam_binding" "invoker" {
  count    = var.enable_gateway ? 1 : 0
  project  = google_project.ai.project_id
  location = var.region
  name     = google_cloud_run_v2_service.judge[0].name
  role     = "roles/run.invoker"
  members  = ["serviceAccount:${google_service_account.caller[0].email}"]
}

output "image_repository" {
  value = try("${var.region}-docker.pkg.dev/${google_project.ai.project_id}/${google_artifact_registry_repository.images[0].repository_id}", null)
}
output "gateway_url" {
  value = try(google_cloud_run_v2_service.judge[0].uri, null)
}
output "caller_service_account" {
  value = try(google_service_account.caller[0].email, null)
}

moved {
  from = google_artifact_registry_repository.images
  to   = google_artifact_registry_repository.images[0]
}

moved {
  from = google_service_account.judge
  to   = google_service_account.judge[0]
}

moved {
  from = google_project_iam_custom_role.judge_predict
  to   = google_project_iam_custom_role.judge_predict[0]
}

moved {
  from = google_project_iam_member.vertex
  to   = google_project_iam_member.vertex[0]
}

moved {
  from = google_service_account.caller
  to   = google_service_account.caller[0]
}

moved {
  from = google_service_account_iam_binding.caller_tokens
  to   = google_service_account_iam_binding.caller_tokens[0]
}

output "runtime_enabled" {
  value = var.enable_runtime
}

output "caller_unique_id" {
  value = google_service_account.caller[0].unique_id
}
output "judge_unique_id" {
  value = google_service_account.judge[0].unique_id
}

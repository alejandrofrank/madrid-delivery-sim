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
  billing_account     = var.billing_account
  org_id              = var.org_id
  folder_id           = var.folder_id
  auto_create_network = false
  deletion_policy     = "DELETE"
  labels              = { application = "madrid-delivery-sim", component = "optional-ai" }
}

resource "google_project_service" "api" {
  for_each = toset([
    "run.googleapis.com", "artifactregistry.googleapis.com", "aiplatform.googleapis.com",
    "iam.googleapis.com", "iamcredentials.googleapis.com", "cloudresourcemanager.googleapis.com"
  ])
  project            = google_project.ai.project_id
  service            = each.value
  disable_on_destroy = false # Project deletion owns final API cleanup.
}

resource "google_artifact_registry_repository" "images" {
  project       = google_project.ai.project_id
  location      = var.region
  repository_id = "judgement"
  format        = "DOCKER"
  depends_on    = [google_project_service.api]
}

resource "google_service_account" "judge" {
  project      = google_project.ai.project_id
  account_id   = "judgement-runtime"
  display_name = "Bounded Vertex judgement gateway"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_custom_role" "judge_predict" {
  project     = google_project.ai.project_id
  role_id     = "boundedJudgePredict"
  title       = "Bounded judge model inference"
  permissions = ["aiplatform.endpoints.predict"]
  depends_on  = [google_project_service.api]
}

resource "google_project_iam_member" "vertex" {
  project = google_project.ai.project_id
  role    = google_project_iam_custom_role.judge_predict.name
  member  = "serviceAccount:${google_service_account.judge.email}"
}

resource "google_service_account" "caller" {
  project      = google_project.ai.project_id
  account_id   = "judgement-caller"
  display_name = "Keyless local judgement caller"
  depends_on   = [google_project_service.api]
}

resource "google_service_account_iam_binding" "caller_tokens" {
  service_account_id = google_service_account.caller.name
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
    service_account                  = google_service_account.judge.email
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
  members  = ["serviceAccount:${google_service_account.caller.email}"]
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${google_project.ai.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
output "gateway_url" {
  value = try(google_cloud_run_v2_service.judge[0].uri, null)
}
output "caller_service_account" {
  value = google_service_account.caller.email
}

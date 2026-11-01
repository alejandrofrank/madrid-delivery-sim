terraform {
  required_version = ">= 1.9, < 2"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 7.46" }
  }
  # Bootstrap with an ignored local override; then migrate into state_bucket.
  backend "gcs" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}
provider "google" {
  alias                 = "billing"
  project               = var.project_id
  billing_project       = var.project_id
  user_project_override = true
}

locals {
  labels = { application = "madrid-delivery-sim", environment = "production" }
  roles  = toset(["replay", "api", "dispatcher", "restaurant", "customer-service", "ci"])
}

resource "google_project" "app" {
  project_id          = var.project_id
  name                = "madrid-delivery-sim"
  billing_account     = var.billing_account
  org_id              = var.org_id
  auto_create_network = false
  deletion_policy     = "PREVENT"
  labels              = local.labels
  lifecycle { prevent_destroy = true }
}

resource "google_project_service" "api" {
  for_each = toset([
    "run.googleapis.com", "artifactregistry.googleapis.com", "iam.googleapis.com",
    "iamcredentials.googleapis.com", "sts.googleapis.com", "serviceusage.googleapis.com",
    "cloudresourcemanager.googleapis.com", "cloudbilling.googleapis.com",
    "billingbudgets.googleapis.com", "monitoring.googleapis.com", "logging.googleapis.com",
    "storage.googleapis.com", "secretmanager.googleapis.com", "sqladmin.googleapis.com",
    "aiplatform.googleapis.com", "bigquery.googleapis.com",
  ])
  project            = google_project.app.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "role" {
  for_each     = local.roles
  project      = google_project.app.project_id
  account_id   = "mds-${each.key}"
  display_name = "madrid-delivery-sim ${each.key}"
  depends_on   = [google_project_service.api]
}

resource "google_artifact_registry_repository" "app" {
  count         = var.active ? 1 : 0
  project       = google_project.app.project_id
  location      = var.region
  repository_id = "madrid-delivery-sim"
  format        = "DOCKER"
  labels        = local.labels
  cleanup_policies {
    id     = "keep-recent-images"
    action = "KEEP"
    most_recent_versions { keep_count = 5 }
  }
  cleanup_policies {
    id     = "expire-old-images"
    action = "DELETE"
    condition { older_than = "2592000s" }
  }
  depends_on = [google_project_service.api]
}

resource "google_storage_bucket" "state" {
  project                     = google_project.app.project_id
  name                        = "${var.project_id}-terraform"
  location                    = "EU"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels
  versioning { enabled = true }
  lifecycle_rule {
    condition { num_newer_versions = 10 }
    action { type = "Delete" }
  }
  depends_on = [google_project_service.api]
}

resource "google_cloud_run_v2_service" "replay" {
  count               = var.active && var.replay_image != "" ? 1 : 0
  project             = google_project.app.project_id
  location            = var.region
  name                = "mds-replay"
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  labels              = local.labels
  template {
    service_account                  = google_service_account.role["replay"].email
    timeout                          = "15s"
    max_instance_request_concurrency = 40
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }
    containers {
      image = var.replay_image
      ports { container_port = 8080 }
      resources {
        limits            = { cpu = "1", memory = "512Mi" }
        cpu_idle          = true
        startup_cpu_boost = false
      }
      env {
        name  = "DELIVERY_RUNTIME"
        value = "replay"
      }
      startup_probe {
        http_get {
          path = "/livez"
          port = 8080
        }
        period_seconds    = 5
        failure_threshold = 12
      }
    }
  }
  # CI promotes tested digests; Terraform retains all security and scaling controls.
  lifecycle { ignore_changes = [template[0].containers[0].image, client, client_version] }
  depends_on = [google_project_service.api]
}

resource "google_cloud_run_v2_service_iam_member" "public_replay" {
  count    = var.active && var.replay_image != "" ? 1 : 0
  project  = google_project.app.project_id
  location = var.region
  name     = google_cloud_run_v2_service.replay[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email == "" ? 0 : 1
  project      = google_project.app.project_id
  display_name = "madrid-delivery-sim operator"
  type         = "email"
  labels       = { email_address = var.alert_email }
  depends_on   = [google_project_service.api]
}

resource "google_billing_budget" "app" {
  provider        = google.billing
  billing_account = var.billing_account
  display_name    = "madrid-delivery-sim monthly alert"
  budget_filter {
    projects               = ["projects/${google_project.app.number}"]
    calendar_period        = "MONTH"
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }
  amount {
    specified_amount {
      currency_code = var.budget_currency
      units         = tostring(var.monthly_budget)
    }
  }
  threshold_rules { threshold_percent = 0.5 }
  threshold_rules { threshold_percent = 0.9 }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }
  all_updates_rule {
    monitoring_notification_channels = google_monitoring_notification_channel.email[*].name
    disable_default_iam_recipients   = false
  }
  depends_on = [google_project_service.api]
}

output "replay_url" { value = try(google_cloud_run_v2_service.replay[0].uri, null) }
output "project_id" { value = google_project.app.project_id }
output "state_bucket" { value = google_storage_bucket.state.name }
output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/madrid-delivery-sim"
}
output "region" { value = var.region }

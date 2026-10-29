# Application exports are separately opt-in; this infrastructure never enables them.
variable "enable_cloud_trace" {
  description = "Enable the Cloud Trace API and grant the observability identity write-only trace access."
  type        = bool
  default     = false
}

variable "enable_analytics" {
  description = "Create the bounded-retention BigQuery analytics dataset. Export data before opting out."
  type        = bool
  default     = false
}

variable "analytics_location" {
  description = "BigQuery data location. Immutable after dataset creation."
  type        = string
  default     = "EU"
}

variable "analytics_retention_days" {
  description = "Partition retention, including terminal order and evaluation evidence."
  type        = number
  default     = 90
  validation {
    condition     = var.analytics_retention_days >= 1 && var.analytics_retention_days <= 365 && floor(var.analytics_retention_days) == var.analytics_retention_days
    error_message = "Analytics retention must be an integer between 1 and 365 days."
  }
}

variable "analytics_deletion_protection" {
  description = "Protect tables from accidental opt-out. Explicitly apply false before deleting analytics."
  type        = bool
  default     = true
}

locals {
  observability_enabled = var.enable_cloud_trace || var.enable_analytics
  analytics_tables      = toset(["traces", "agent_steps", "eval_runs", "orders"])
  observability_runtime_members = {
    restaurant = "serviceAccount:${google_service_account.restaurant.email}"
    judge      = "serviceAccount:${google_service_account.judge[0].email}"
  }
  observability_apis = toset(concat(
    var.enable_cloud_trace ? ["cloudtrace.googleapis.com"] : [],
    var.enable_analytics ? ["bigquery.googleapis.com"] : []
  ))
}

resource "google_project_service" "observability" {
  for_each           = local.observability_apis
  project            = google_project.ai.project_id
  service            = each.value
  disable_on_destroy = false
}

# Use attached credentials in GCP, or keyless impersonation locally. No keys are created.
resource "google_service_account" "observability" {
  count        = local.observability_enabled ? 1 : 0
  project      = google_project.ai.project_id
  account_id   = "observability-writer"
  display_name = "Madrid simulation trace and analytics writer"
  depends_on   = [google_project_service.api]
}

resource "google_service_account_iam_binding" "observability_tokens" {
  count              = local.observability_enabled ? 1 : 0
  service_account_id = google_service_account.observability[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  members            = var.invoker_members
}

resource "google_project_iam_member" "trace_writer" {
  count   = var.enable_cloud_trace ? 1 : 0
  project = google_project.ai.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.observability[0].email}"
}

# Runtime ADC must keep its existing inference identity while exporting telemetry.
# The caller identity only mints gateway ID tokens and receives no export access.
resource "google_project_iam_member" "runtime_trace_writer" {
  for_each = var.enable_cloud_trace ? local.observability_runtime_members : {}
  project  = google_project.ai.project_id
  role     = "roles/cloudtrace.agent"
  member   = each.value
}

resource "google_bigquery_dataset" "analytics" {
  count                           = var.enable_analytics ? 1 : 0
  project                         = google_project.ai.project_id
  dataset_id                      = "mds_analytics"
  friendly_name                   = "Madrid delivery observability"
  description                     = "Allowlisted operational metrics; no prompts, tool arguments or customer text."
  location                        = var.analytics_location
  default_partition_expiration_ms = var.analytics_retention_days * 86400000
  max_time_travel_hours           = 48
  delete_contents_on_destroy      = false
  labels                          = { application = "madrid-delivery-sim", component = "observability" }
  depends_on                      = [google_project_service.observability]
}

resource "google_bigquery_table" "analytics" {
  for_each                 = var.enable_analytics ? local.analytics_tables : toset([])
  project                  = google_project.ai.project_id
  dataset_id               = google_bigquery_dataset.analytics[0].dataset_id
  table_id                 = each.key
  schema                   = file("${path.module}/schemas/${each.key}.json")
  clustering               = ["agent"]
  require_partition_filter = true
  deletion_protection      = var.analytics_deletion_protection
  labels                   = { application = "madrid-delivery-sim", component = "observability" }
  time_partitioning {
    type          = "DAY"
    field         = "observed_at"
    expiration_ms = var.analytics_retention_days * 86400000
  }
}

# insertAll only needs updateData. Do not grant query, export, table creation or deletion.
resource "google_project_iam_custom_role" "analytics_writer" {
  count       = var.enable_analytics ? 1 : 0
  project     = google_project.ai.project_id
  role_id     = "mdsAnalyticsAppend"
  title       = "Madrid analytics append"
  permissions = ["bigquery.tables.updateData"]
}

resource "google_bigquery_dataset_iam_member" "analytics_writer" {
  count      = var.enable_analytics ? 1 : 0
  project    = google_project.ai.project_id
  dataset_id = google_bigquery_dataset.analytics[0].dataset_id
  role       = google_project_iam_custom_role.analytics_writer[0].name
  member     = "serviceAccount:${google_service_account.observability[0].email}"
}

resource "google_bigquery_dataset_iam_member" "runtime_analytics_writer" {
  for_each   = var.enable_analytics ? local.observability_runtime_members : {}
  project    = google_project.ai.project_id
  dataset_id = google_bigquery_dataset.analytics[0].dataset_id
  role       = google_project_iam_custom_role.analytics_writer[0].name
  member     = each.value
}

output "observability_service_account" {
  value = try(google_service_account.observability[0].email, null)
}

output "analytics_dataset" {
  value = try("${google_project.ai.project_id}.${google_bigquery_dataset.analytics[0].dataset_id}", null)
}

# Opt-in analytics. Default plans create no BigQuery storage, API or identity.
variable "enable_bigquery" {
  description = "Explicitly provision the bounded analytics demo. Remove analytics before unlinking billing."
  type        = bool
  default     = false
}

variable "bigquery_dataset_id" {
  type    = string
  default = "delivery_analytics"
  validation {
    condition     = can(regex("^[A-Za-z_][A-Za-z0-9_]{0,100}$", var.bigquery_dataset_id))
    error_message = "Use a simple BigQuery dataset identifier."
  }
}

variable "bigquery_location" {
  description = "BigQuery data location; independent of the inference region."
  type        = string
  default     = "EU"
}

resource "google_project_service" "bigquery" {
  count              = var.enable_bigquery ? 1 : 0
  project            = google_project.ai.project_id
  service            = "bigquery.googleapis.com"
  disable_on_destroy = false
}

resource "google_bigquery_dataset" "analytics" {
  count                           = var.enable_bigquery ? 1 : 0
  project                         = google_project.ai.project_id
  dataset_id                      = var.bigquery_dataset_id
  location                        = var.bigquery_location
  description                     = "Allowlisted simulation run receipts and KPIs; seven-day partition retention."
  default_partition_expiration_ms = 604800000
  delete_contents_on_destroy      = false
  labels                          = { application = "madrid-delivery-sim", component = "analytics" }
  lifecycle {
    precondition {
      condition     = var.enable_billing
      error_message = "Analytics requires explicit billing opt-in. Remove analytics while billing is enabled before parking."
    }
  }
  depends_on = [google_project_service.bigquery]
}

locals {
  analytics_common_schema = [
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "receipt_sha256", type = "STRING", mode = "REQUIRED" },
    { name = "run_created_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "exported_at", type = "TIMESTAMP", mode = "REQUIRED" },
  ]
  analytics_schemas = {
    run_receipts = concat(local.analytics_common_schema, [
      { name = "source_fingerprint", type = "STRING", mode = "NULLABLE" },
      { name = "profile", type = "STRING", mode = "NULLABLE" },
      { name = "scenario", type = "STRING", mode = "NULLABLE" },
      { name = "variant", type = "STRING", mode = "NULLABLE" },
      { name = "status", type = "STRING", mode = "NULLABLE" },
      { name = "replay_matches", type = "BOOLEAN", mode = "NULLABLE" },
      { name = "checks_passed", type = "INTEGER", mode = "REQUIRED" },
      { name = "checks_total", type = "INTEGER", mode = "REQUIRED" },
      { name = "usage_cost_usd", type = "FLOAT", mode = "NULLABLE" },
      { name = "reserved_cost_usd", type = "FLOAT", mode = "NULLABLE" },
      { name = "unknown_usage_calls", type = "INTEGER", mode = "NULLABLE" },
    ])
    run_kpis = concat(local.analytics_common_schema, [
      { name = "metric_name", type = "STRING", mode = "REQUIRED" },
      { name = "metric_value", type = "FLOAT", mode = "REQUIRED" },
    ])
  }
}

resource "google_bigquery_table" "analytics" {
  for_each            = var.enable_bigquery ? local.analytics_schemas : {}
  project             = google_project.ai.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = each.key
  deletion_protection = false # Explicit opt-out removes this disposable seven-day demo.
  schema              = jsonencode(each.value)
  clustering          = ["run_id", "receipt_sha256"]
  time_partitioning {
    type          = "DAY"
    field         = "exported_at"
    expiration_ms = 604800000
  }
  require_partition_filter = true
}

resource "google_bigquery_table" "dashboard" {
  count               = var.enable_bigquery ? 1 : 0
  project             = google_project.ai.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = "run_dashboard"
  deletion_protection = false
  description         = "One latest receipt per run, with delivery, queue, evaluation and cost KPIs for Looker Studio."
  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/sql/run_dashboard.sql", {
      project_id = google_project.ai.project_id
      dataset_id = var.bigquery_dataset_id
    })
  }
  depends_on = [google_bigquery_table.analytics]
}

resource "google_service_account" "analytics" {
  count        = var.enable_bigquery ? 1 : 0
  project      = google_project.ai.project_id
  account_id   = "delivery-analytics"
  display_name = "Bounded simulation receipt loader"
  depends_on   = [google_project_service.api]
}

# No data read, delete, IAM administration or prediction permissions.
resource "google_project_iam_custom_role" "analytics_load" {
  count       = var.enable_bigquery ? 1 : 0
  project     = google_project.ai.project_id
  role_id     = "deliveryAnalyticsLoad"
  title       = "Load simulation analytics tables"
  permissions = ["bigquery.tables.create", "bigquery.tables.get", "bigquery.tables.update", "bigquery.tables.updateData"]
  depends_on  = [google_project_service.bigquery]
}

resource "google_bigquery_dataset_iam_member" "analytics_load" {
  count      = var.enable_bigquery ? 1 : 0
  project    = google_project.ai.project_id
  dataset_id = google_bigquery_dataset.analytics[0].dataset_id
  role       = google_project_iam_custom_role.analytics_load[0].name
  member     = "serviceAccount:${google_service_account.analytics[0].email}"
}

resource "google_project_iam_custom_role" "analytics_jobs" {
  count       = var.enable_bigquery ? 1 : 0
  project     = google_project.ai.project_id
  role_id     = "deliveryAnalyticsJobs"
  title       = "Create simulation analytics load jobs"
  permissions = ["bigquery.jobs.create"]
  depends_on  = [google_project_service.bigquery]
}

resource "google_project_iam_member" "analytics_jobs" {
  count   = var.enable_bigquery ? 1 : 0
  project = google_project.ai.project_id
  role    = google_project_iam_custom_role.analytics_jobs[0].name
  member  = "serviceAccount:${google_service_account.analytics[0].email}"
}

resource "google_service_account_iam_binding" "analytics_tokens" {
  count              = var.enable_bigquery ? 1 : 0
  service_account_id = google_service_account.analytics[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  members            = var.invoker_members
}

output "bigquery_analytics" {
  value = var.enable_bigquery ? {
    dataset         = "${google_project.ai.project_id}.${var.bigquery_dataset_id}"
    location        = var.bigquery_location
    dashboard_view  = "${google_project.ai.project_id}.${var.bigquery_dataset_id}.run_dashboard"
    service_account = google_service_account.analytics[0].email
  } : null
}

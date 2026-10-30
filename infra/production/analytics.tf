locals {
  metric_fields = {
    operational_orders = {
      run_id = "STRING", order_id = "STRING", status = "STRING", delivered = "BOOLEAN",
      late   = "BOOLEAN", delivery_cost_eur = "FLOAT"
    }
    disruptions = {
      run_id          = "STRING", disruption_id = "STRING", time_to_recover_seconds = "INTEGER",
      orders_saved    = "INTEGER", orders_lost = "INTEGER", late_deliveries = "INTEGER",
      refund_cost_eur = "FLOAT", extra_tokens = "INTEGER", extra_token_cost_usd = "FLOAT",
      failed_replans  = "INTEGER"
    }
  }
  analytics_schemas = merge(
    { for name in ["traces", "agent_steps", "orders", "eval_runs"] : name =>
    file("${path.module}/../gcp-ai/schemas/${name}.json") },
    { for name, fields in local.metric_fields : name => jsonencode(concat([
      { name = "event_id", type = "STRING", mode = "REQUIRED" },
      { name = "observed_at", type = "TIMESTAMP", mode = "REQUIRED" }
    ], [for field, type in fields : { name = field, type = type, mode = "NULLABLE" }])) }
  )
}

resource "google_bigquery_dataset" "analytics" {
  count                           = var.active && var.enable_live ? 1 : 0
  project                         = google_project.app.project_id
  dataset_id                      = "mds_analytics"
  location                        = "EU"
  default_partition_expiration_ms = 2592000000
  max_time_travel_hours           = 48
  delete_contents_on_destroy      = true
  labels                          = local.labels
  depends_on                      = [google_project_service.api]
}

resource "google_bigquery_table" "metrics" {
  for_each                 = var.active && var.enable_live ? local.analytics_schemas : {}
  project                  = google_project.app.project_id
  dataset_id               = google_bigquery_dataset.analytics[0].dataset_id
  table_id                 = each.key
  schema                   = each.value
  deletion_protection      = false
  require_partition_filter = true
  time_partitioning {
    type          = "DAY"
    field         = "observed_at"
    expiration_ms = 2592000000
  }
}

resource "google_bigquery_table" "view" {
  for_each = var.active && var.enable_live ? toset([
    "cost_per_order", "late_delivery_rate", "recovery_time", "token_spend_per_agent"
  ]) : toset([])
  project             = google_project.app.project_id
  dataset_id          = google_bigquery_dataset.analytics[0].dataset_id
  table_id            = each.key
  deletion_protection = false
  view {
    query          = templatefile("${path.module}/sql/${each.key}.sql", { project = var.project_id })
    use_legacy_sql = false
  }
  depends_on = [google_bigquery_table.metrics]
}

resource "google_project_iam_custom_role" "metrics_append" {
  project     = google_project.app.project_id
  role_id     = "mdsAppendMetrics"
  title       = "Append allowlisted Madrid metrics"
  permissions = ["bigquery.tables.updateData"]
}

resource "google_bigquery_dataset_iam_member" "append" {
  for_each   = var.active && var.enable_live ? local.live_roles : toset([])
  project    = google_project.app.project_id
  dataset_id = google_bigquery_dataset.analytics[0].dataset_id
  role       = google_project_iam_custom_role.metrics_append.name
  member     = "serviceAccount:${google_service_account.role[each.key].email}"
}

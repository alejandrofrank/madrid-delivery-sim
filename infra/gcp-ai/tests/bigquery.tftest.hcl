mock_provider "google" {}

variables {
  project_id      = "mds-analytics-test"
  billing_account = "000000-000000-000000"
  region          = "europe-west1"
  vertex_region   = "global"
  vertex_model    = "test-model"
  invoker_members = ["user:test@example.com"]
}

run "analytics_parked_by_default" {
  command = plan
  assert {
    condition     = length(google_bigquery_dataset.analytics) == 0 && length(google_bigquery_table.analytics) == 0 && length(google_service_account.analytics) == 0 && length(google_project_service.bigquery) == 0
    error_message = "Default mode must provision no analytics resources."
  }
}

run "analytics_requires_billing_opt_in" {
  command = plan
  variables {
    enable_bigquery = true
  }
  expect_failures = [google_bigquery_dataset.analytics]
}

run "analytics_bounded_storage_and_permissions" {
  command = plan
  variables {
    enable_bigquery = true
    enable_billing  = true
  }
  assert {
    condition     = length(google_bigquery_table.analytics) == 2 && google_bigquery_dataset.analytics[0].default_partition_expiration_ms == 604800000 && alltrue([for t in google_bigquery_table.analytics : t.require_partition_filter])
    error_message = "Export must use two partition-filtered tables with seven-day retention."
  }
  assert {
    condition     = google_project_iam_custom_role.analytics_jobs[0].permissions == toset(["bigquery.jobs.create"]) && !contains(google_project_iam_custom_role.analytics_load[0].permissions, "bigquery.tables.getData") && !contains(google_project_iam_custom_role.analytics_load[0].permissions, "bigquery.tables.delete")
    error_message = "The loader must have no data-read or delete permissions."
  }
  assert {
    condition     = google_bigquery_table.dashboard[0].view[0].use_legacy_sql == false && google_bigquery_table.dashboard[0].table_id == "run_dashboard"
    error_message = "Provide a GoogleSQL dashboard view."
  }
}

mock_provider "google" {
  mock_resource "google_service_account" {
    defaults = {
      name  = "projects/mds-observability-test/serviceAccounts/writer@mds-observability-test.iam.gserviceaccount.com"
      email = "writer@mds-observability-test.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id      = "mds-observability-test"
  billing_account = "000000-000000-000000"
  region          = "europe-west1"
  vertex_region   = "global"
  vertex_model    = "test-model"
  invoker_members = ["user:test@example.com"]
}

run "disabled_by_default" {
  command = plan
  assert {
    condition     = length(google_bigquery_dataset.observability) == 0 && length(google_bigquery_table.observability) == 0 && length(google_project_service.bigquery) == 0 && length(google_project_service.telemetry) == 0 && length(google_service_account.observability) == 0
    error_message = "Default configuration must create no observability storage, APIs or identities."
  }
  assert {
    condition     = length(google_project_iam_member.runtime_trace_writer) == 0 && length(google_bigquery_dataset_iam_member.runtime_analytics_writer) == 0
    error_message = "Existing runtime identities must gain no telemetry permissions without opt-in."
  }
}

run "reject_paid_observability_without_billing" {
  command = plan
  variables {
    enable_analytics = true
  }
  expect_failures = [google_project.ai]
}

run "reject_cloud_trace_without_billing" {
  command = plan
  variables {
    enable_cloud_trace = true
  }
  expect_failures = [google_project.ai]
}

run "analytics_schema_and_permissions" {
  command = apply
  variables {
    enable_analytics   = true
    enable_cloud_trace = true
    enable_billing     = true
  }
  assert {
    condition     = google_bigquery_dataset.observability[0].dataset_id == "mds_analytics" && google_bigquery_dataset.observability[0].location == "EU" && !google_bigquery_dataset.observability[0].delete_contents_on_destroy
    error_message = "Analytics must stay in the configured location and reject recursive data deletion."
  }
  assert {
    condition = length(google_bigquery_table.observability) == 4 && alltrue([
      for table in google_bigquery_table.observability : table.clustering == tolist(["agent"]) && table.time_partitioning[0].type == "DAY" && table.time_partitioning[0].field == "observed_at" && table.time_partitioning[0].expiration_ms == 7776000000 && table.require_partition_filter && table.deletion_protection
    ])
    error_message = "All four analytics tables need agent clustering, filtered daily partitions, bounded retention and deletion protection."
  }
  assert {
    condition = alltrue([
      for table in google_bigquery_table.observability : alltrue([
        for name in ["event_id", "observed_at", "agent"] : anytrue([
          for field in jsondecode(table.schema) : field.name == name && field.mode == "REQUIRED"
        ])
      ])
    ])
    error_message = "Every exported row must have a stable identifier, partition timestamp and agent."
  }
  assert {
    condition     = google_project_iam_custom_role.analytics_writer[0].permissions == toset(["bigquery.tables.updateData"]) && google_bigquery_dataset_iam_member.analytics_writer[0].dataset_id == "mds_analytics" && google_project_iam_member.trace_writer[0].role == "roles/cloudtrace.agent"
    error_message = "The writer must only append to this dataset and write Cloud Trace spans."
  }
  assert {
    condition = toset(keys(google_project_iam_member.runtime_trace_writer)) == toset(["restaurant", "judge"]) && alltrue([
      for binding in google_project_iam_member.runtime_trace_writer : binding.role == "roles/cloudtrace.agent" && binding.project == var.project_id
      ]) && toset(keys(google_bigquery_dataset_iam_member.runtime_analytics_writer)) == toset(["restaurant", "judge"]) && alltrue([
      for binding in google_bigquery_dataset_iam_member.runtime_analytics_writer : binding.dataset_id == "mds_analytics" && binding.role == google_project_iam_custom_role.analytics_writer[0].name
    ])
    error_message = "Only the restaurant and judge runtime identities gain scoped telemetry access; the token caller must not."
  }
  assert {
    condition     = google_project_iam_member.runtime_trace_writer["restaurant"].member == "serviceAccount:${google_service_account.restaurant.email}" && google_bigquery_dataset_iam_member.runtime_analytics_writer["judge"].member == "serviceAccount:${google_service_account.judge[0].email}"
    error_message = "Runtime export access must use the same ADC identities as the deployed inference agents."
  }
}

run "trace_only_does_not_create_analytics" {
  command = plan
  variables {
    enable_cloud_trace = true
    enable_billing     = true
  }
  assert {
    condition     = length(google_bigquery_table.observability) == 0 && length(google_project_service.telemetry) == 1 && length(google_project_iam_member.trace_writer) == 1 && length(google_project_iam_member.runtime_trace_writer) == 2 && length(google_bigquery_dataset_iam_member.analytics_writer) == 0 && length(google_bigquery_dataset_iam_member.runtime_analytics_writer) == 0
    error_message = "Tracing must be independently enabled without analytics storage or BigQuery access."
  }
}

run "reject_unbounded_retention" {
  command = plan
  variables {
    analytics_retention_days = 366
  }
  expect_failures = [var.analytics_retention_days]
}

run "receipt_and_streaming_analytics_coexist_with_single_api_owners" {
  command = plan
  variables {
    enable_bigquery    = true
    enable_analytics   = true
    enable_telemetry   = true
    enable_cloud_trace = true
    enable_billing     = true
  }
  assert {
    condition     = google_bigquery_dataset.analytics[0].dataset_id == "delivery_analytics" && google_bigquery_dataset.observability[0].dataset_id == "mds_analytics" && length(google_bigquery_table.analytics) == 2 && length(google_bigquery_table.observability) == 4
    error_message = "Receipt analytics and streaming observability must keep separate datasets, tables and retention policies."
  }
  assert {
    condition     = length(google_project_service.bigquery) == 1 && toset(keys(google_project_service.telemetry)) == toset(["cloudtrace.googleapis.com", "telemetry.googleapis.com"])
    error_message = "Enabling both export paths must manage each shared Google API exactly once."
  }
}

run "reject_receipt_and_streaming_dataset_collision" {
  command = plan
  variables {
    enable_bigquery     = true
    enable_analytics    = true
    enable_billing      = true
    bigquery_dataset_id = "mds_analytics"
  }
  expect_failures = [google_bigquery_dataset.analytics]
}

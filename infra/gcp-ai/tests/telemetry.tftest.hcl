mock_provider "google" {}

variables {
  project_id      = "mds-telemetry-test"
  billing_account = "000000-000000-000000"
  region          = "europe-west1"
  vertex_region   = "global"
  vertex_model    = "test-model"
  invoker_members = ["user:test@example.com"]
}

run "telemetry_parked_by_default" {
  command = plan
  assert {
    condition     = length(google_service_account.telemetry) == 0 && length(google_project_service.telemetry) == 0 && length(google_project_iam_member.telemetry) == 0
    error_message = "Default mode must provision no telemetry resources."
  }
}

run "trace_only_permissions" {
  command = plan
  variables {
    enable_telemetry = true
  }
  assert {
    condition     = toset(keys(google_project_iam_member.telemetry)) == toset(["roles/telemetry.tracesWriter", "roles/serviceusage.serviceUsageConsumer"])
    error_message = "The collector requires only trace-write and quota-use permissions."
  }
  assert {
    condition     = toset(keys(google_project_service.telemetry)) == toset(["telemetry.googleapis.com", "cloudtrace.googleapis.com"]) && length(google_cloud_run_v2_service.judge) == 0
    error_message = "Telemetry opt-in enables only its APIs and does not launch a paid runtime."
  }
}

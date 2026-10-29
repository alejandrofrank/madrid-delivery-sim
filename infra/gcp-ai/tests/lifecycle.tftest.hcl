mock_provider "google" {
  mock_resource "google_service_account" {
    defaults = {
      name  = "projects/mds-lifecycle-test/serviceAccounts/judgement-test@mds-lifecycle-test.iam.gserviceaccount.com"
      email = "judgement-test@mds-lifecycle-test.iam.gserviceaccount.com"
    }
  }
}

variables {
  project_id      = "mds-lifecycle-test"
  billing_account = "000000-000000-000000"
  region          = "europe-west1"
  vertex_region   = "global"
  vertex_model    = "test-model"
  invoker_members = ["user:test@example.com"]
  enable_billing  = false
  enable_runtime  = false
  enable_gateway  = false
  gateway_image   = ""
}

run "parked_default" {
  command = plan
  assert {
    condition     = google_project.ai.billing_account == null && google_project.ai.deletion_policy == "PREVENT"
    error_message = "Parked project must be protected and unlinked from billing."
  }
  assert {
    condition     = google_service_account.restaurant.account_id == "restaurant-adk" && length(google_project_iam_custom_role.judge_predict[0].permissions) == 1 && contains(google_project_iam_custom_role.judge_predict[0].permissions, "aiplatform.endpoints.predict")
    error_message = "Native restaurants retain a separate identity with only the scoped prediction role."
  }
  assert {
    condition     = length(google_artifact_registry_repository.images) == 0 && length(google_cloud_run_v2_service.judge) == 0 && length(google_service_account.judge) == 1
    error_message = "Parked mode must remove image storage and gateway while retaining its runtime identity."
  }
}

run "active_runtime" {
  command = apply
  variables {
    enable_billing = true
    enable_runtime = true
    enable_gateway = true
    gateway_image  = "europe-west1-docker.pkg.dev/mds-lifecycle-test/judgement/gateway@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }
  assert {
    condition     = length(google_artifact_registry_repository.images) == 1 && length(google_cloud_run_v2_service.judge) == 1 && google_project.ai.billing_account == var.billing_account
    error_message = "Explicit runtime opt-in must create storage, gateway and billing link."
  }
}

run "remove_runtime_before_unlinking_billing" {
  command = apply
  variables {
    enable_billing = true
  }
  assert {
    condition     = length(google_artifact_registry_repository.images) == 0 && length(google_cloud_run_v2_service.judge) == 0 && google_project.ai.billing_account == var.billing_account
    error_message = "Delete billable resources while their APIs can still use billing."
  }
}

run "park_after_active" {
  command = apply
  assert {
    condition     = google_project.ai.billing_account == null && length(google_artifact_registry_repository.images) == 0 && length(google_cloud_run_v2_service.judge) == 0 && length(google_service_account.caller) == 1 && length(google_project_service.api) == 6 && length(google_project_iam_custom_role.judge_predict) == 1 && length(google_project_iam_member.vertex) == 1 && length(google_service_account_iam_binding.caller_tokens) == 1
    error_message = "Shutdown must remove billable runtime and billing link while retaining project, APIs and scoped IAM."
  }
}

run "reject_gateway_without_runtime" {
  command = plan
  variables {
    enable_gateway = true
  }
  expect_failures = [google_project.ai]
}


run "reject_runtime_without_billing" {
  command = plan
  variables {
    enable_runtime = true
  }
  expect_failures = [google_project.ai]
}

run "restart_with_same_identities" {
  command = plan
  variables {
    enable_billing = true
    enable_runtime = true
  }
  assert {
    condition     = google_service_account.caller[0].unique_id == run.active_runtime.caller_unique_id && google_service_account.judge[0].unique_id == run.active_runtime.judge_unique_id
    error_message = "Restart must reuse the same IAM identities."
  }
}

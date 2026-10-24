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
    condition     = length(google_artifact_registry_repository.images) == 0 && length(google_cloud_run_v2_service.judge) == 0 && length(google_service_account.judge) == 0
    error_message = "Parked mode must contain no image storage, gateway or runtime identity."
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
  command = plan
  variables {
    enable_billing = true
  }
  assert {
    condition     = length(google_artifact_registry_repository.images) == 0 && length(google_cloud_run_v2_service.judge) == 0 && google_project.ai.billing_account == var.billing_account
    error_message = "Delete billable resources while their APIs can still use billing."
  }
}

run "park_after_active" {
  command = plan
  assert {
    condition     = google_project.ai.billing_account == null && length(google_artifact_registry_repository.images) == 0 && length(google_cloud_run_v2_service.judge) == 0 && length(google_service_account.caller) == 0 && length(google_project_service.api) == 0
    error_message = "Shutdown must remove the runtime and billing link, retaining the protected project."
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

mock_provider "google" {}
mock_provider "google" { alias = "billing" }

variables {
  active          = true
  project_id      = "madrid-production-test"
  billing_account = "000000-000000-000000"
  replay_image    = "europe-west1-docker.pkg.dev/test/app/replay@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}

run "replay_has_no_idle_instances_or_credential_grants" {
  command = plan
  assert {
    condition     = google_cloud_run_v2_service.replay[0].template[0].scaling[0].min_instance_count == 0 && google_cloud_run_v2_service.replay[0].template[0].scaling[0].max_instance_count == 2
    error_message = "Public replay must scale to zero with a bounded maximum."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.public_replay[0].member == "allUsers"
    error_message = "Only the replay service is public."
  }
  assert {
    condition     = google_cloud_run_v2_service.replay[0].template[0].containers[0].resources[0].cpu_idle
    error_message = "Replay must use request-based CPU billing."
  }
  assert {
    condition     = google_storage_bucket.state.public_access_prevention == "enforced"
    error_message = "Terraform state must never be public."
  }
  assert {
    condition     = google_billing_budget.app.amount[0].specified_amount[0].units == "4"
    error_message = "A monthly budget alert is required at bootstrap."
  }
  assert {
    condition     = length(google_service_account.role) == 8
    error_message = "Each application role and CI require separate identities."
  }
}

run "inactive_environment_removes_billable_runtime_and_images" {
  command = plan
  variables { active = false }
  assert {
    condition     = length(google_cloud_run_v2_service.replay) == 0 && length(google_artifact_registry_repository.app) == 0
    error_message = "Stop must remove the service and container storage."
  }
}

run "federation_is_repository_main_workflow_and_environment_bound" {
  command = plan
  assert {
    condition = alltrue([
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, "assertion.repository_id == '1429194351'"),
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, "assertion.repository_owner_id == '46542996'"),
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, "refs/heads/main"),
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, "environment:production"),
      strcontains(google_iam_workload_identity_pool_provider.github.attribute_condition, "/.github/workflows/deploy.yml@refs/heads/main"),
    ])
    error_message = "Untrusted repositories, branches, workflows and environments cannot federate."
  }
  assert {
    condition     = toset(google_project_iam_custom_role.deploy.permissions) == toset(["run.services.get", "run.services.update", "run.services.getIamPolicy"])
    error_message = "CI may update existing services, not change IAM or create infrastructure."
  }
}

run "reject_mutable_image_tags" {
  command = plan
  variables { replay_image = "example/replay:latest" }
  expect_failures = [var.replay_image]
}

run "live_uses_distinct_identities_private_invocation_and_jobs" {
  command = plan
  variables {
    enable_live         = true
    live_ready          = true
    live_image          = "example/live@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    operator_principals = ["operator@example.com"]
  }
  assert {
    condition     = length(google_cloud_run_v2_service.live) == 6 && length(google_cloud_run_v2_service_iam_member.agents) == 5
    error_message = "API and three agent roles require separate private Cloud Run services."
  }
  assert {
    condition     = alltrue([for s in google_cloud_run_v2_service.live : s.template[0].scaling[0].min_instance_count == 0])
    error_message = "Every HTTP service must scale to zero."
  }
  assert {
    condition     = google_cloud_run_v2_job.shift[0].template[0].template[0].max_retries == 0
    error_message = "Do not blindly retry non-resumable lab scenarios."
  }
  assert {
    condition     = length(google_bigquery_table.view) == 4 && google_bigquery_dataset.analytics[0].delete_contents_on_destroy
    error_message = "Four dashboard views and ephemeral dataset cleanup are required."
  }
  assert {
    condition     = length(google_vertex_ai_index.memory) == 0
    error_message = "Live mode must not silently enable a billed vector endpoint."
  }
}

run "stop_removes_even_opted_in_live_resources" {
  command = plan
  variables {
    active               = false
    enable_live          = true
    live_ready           = true
    enable_vector_search = true
  }
  assert {
    condition     = length(google_sql_database_instance.live) == 0 && length(google_vertex_ai_index.memory) == 0 && length(google_cloud_run_v2_service.live) == 0 && length(google_cloud_run_v2_job.shift) == 0 && length(google_bigquery_dataset.analytics) == 0 && length(google_secret_manager_secret.database) == 0
    error_message = "Stop must remove SQL, vector serving, jobs, services, analytics and secrets."
  }
}

run "vector_opt_in_is_bounded_and_operator_service_identity_is_private" {
  command = plan
  variables {
    enable_live          = true
    live_ready           = true
    enable_vector_search = true
    live_image           = "example/live@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    operator_principals  = ["operator@example.iam.gserviceaccount.com"]
  }
  assert {
    condition     = google_vertex_ai_index_endpoint_deployed_index.memory[0].dedicated_resources[0].max_replica_count == 1
    error_message = "Optional vector serving must have a fixed maximum of one replica."
  }
  assert {
    condition     = google_cloud_run_v2_service_iam_member.operators["operator@example.iam.gserviceaccount.com"].member == "serviceAccount:operator@example.iam.gserviceaccount.com"
    error_message = "Service operators must receive serviceAccount IAM membership."
  }
  assert {
    condition     = toset(keys(google_project_iam_member.vector)) == toset(["api", "restaurant", "dispatcher"])
    error_message = "Only implemented memory consumers receive vector permissions."
  }
}

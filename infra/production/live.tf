locals {
  live_roles    = toset(["api", "dispatcher", "restaurant", "customer-service", "inventory", "fulfillment"])
  live_services = var.active && var.enable_live && var.live_ready ? local.live_roles : toset([])
  live_urls = { for role in local.live_roles : role =>
  "https://mds-${role}-${google_project.app.number}.${var.region}.run.app" }
  agent_endpoints = { for role in ["dispatcher", "restaurant", "customer-service", "inventory", "fulfillment"] :
  replace(role, "-", "_") => local.live_urls[role] }
  live_environment = {
    DELIVERY_RUNTIME             = "live"
    DELIVERY_AGENT_TRANSPORT     = "a2a"
    DELIVERY_A2A_ENDPOINTS       = jsonencode(local.agent_endpoints)
    DELIVERY_OPERATOR_PRINCIPALS = jsonencode(var.operator_principals)
    DELIVERY_A2A_CALLERS = jsonencode({
      (google_service_account.role["api"].email) = ["dispatcher", "restaurant", "customer_service", "inventory", "fulfillment"]
    })
    DELIVERY_CLOUD_RUN_JOB      = "projects/${var.project_id}/locations/${var.region}/jobs/mds-shift"
    GOOGLE_CLOUD_PROJECT        = var.project_id
    GOOGLE_CLOUD_LOCATION       = var.region
    LLM_PROVIDER                = "disabled"
    DELIVERY_ADK_VERTEX_ENABLED = "0"
    DELIVERY_CHAOS_PROVIDER     = "offline"
    MDS_PRODUCTION_METRICS      = "1"
    MDS_TELEMETRY_ENABLED       = "1"
    MDS_BIGQUERY_ENABLED        = "1"
    MDS_BIGQUERY_DATASET        = "mds_analytics"
    DELIVERY_OTEL_EXPORTER      = "disabled"
    DELIVERY_MEMORY_BACKEND     = var.enable_vector_search ? "vertex" : "pgvector"
  }
}

# Prepare storage first, initialize it through the operator runbook, then set live_ready.
# No application can boot against an uninitialized database or blank secret.
resource "google_sql_database_instance" "live" {
  count               = var.active && var.enable_live ? 1 : 0
  project             = google_project.app.project_id
  region              = var.region
  name                = "mds-live"
  database_version    = "POSTGRES_17"
  deletion_protection = false
  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_size         = 10
    disk_autoresize   = false
    ip_configuration {
      ipv4_enabled = true
      # No authorized networks. Cloud Run's authenticated SQL connector is required.
      ssl_mode = "ENCRYPTED_ONLY"
    }
    backup_configuration { enabled = false }
    user_labels = local.labels
  }
  depends_on = [google_project_service.api]
}

resource "google_sql_database" "live" {
  count    = var.active && var.enable_live ? 1 : 0
  project  = google_project.app.project_id
  instance = google_sql_database_instance.live[0].name
  name     = "delivery"
}

resource "google_secret_manager_secret" "database" {
  for_each  = var.active && var.enable_live ? local.live_roles : toset([])
  project   = google_project.app.project_id
  secret_id = "mds-database-${each.key}"
  replication {
    auto {}
  }
  labels     = local.labels
  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_iam_member" "database" {
  for_each  = google_secret_manager_secret.database
  project   = google_project.app.project_id
  secret_id = each.value.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.role[each.key].email}"
}

resource "google_project_iam_member" "sql_connect" {
  for_each = var.active && var.enable_live ? local.live_roles : toset([])
  project  = google_project.app.project_id
  role     = "roles/cloudsql.client"
  member   = "serviceAccount:${google_service_account.role[each.key].email}"
  condition {
    title      = "only-mds-live"
    expression = "resource.name == 'projects/${var.project_id}/instances/mds-live'"
  }
}

resource "google_cloud_run_v2_service" "live" {
  for_each            = local.live_services
  project             = google_project.app.project_id
  location            = var.region
  name                = "mds-${each.key}"
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  custom_audiences    = [local.live_urls[each.key]]
  template {
    service_account                  = google_service_account.role[each.key].email
    max_instance_request_concurrency = 1
    timeout                          = "300s"
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance { instances = [google_sql_database_instance.live[0].connection_name] }
    }
    containers {
      image   = var.live_image
      command = ["uvicorn"]
      args    = ["delivery.production:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
      ports { container_port = 8080 }
      resources {
        limits   = { cpu = "1", memory = "2Gi" }
        cpu_idle = true
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
      dynamic "env" {
        for_each = merge(local.live_environment, local.vector_environment, {
          DELIVERY_SERVICE_ROLE  = replace(each.key, "-", "_")
          DELIVERY_AUTH_AUDIENCE = local.live_urls[each.key]
          DELIVERY_A2A_BASE_URL  = local.live_urls[each.key]
        })
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.database[each.key].secret_id
            version = "latest"
          }
        }
      }
      startup_probe {
        http_get {
          path = "/livez"
          port = 8080
        }
        period_seconds    = 5
        failure_threshold = 24
      }
    }
  }
  lifecycle {
    precondition {
      condition     = length(var.operator_principals) > 0 && can(regex("@sha256:[a-f0-9]{64}$", var.live_image))
      error_message = "Live requires explicit operators, initialized SQL, role secrets and a pinned image."
    }
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
  depends_on = [google_secret_manager_secret_iam_member.database, google_project_iam_member.sql_connect]
}

resource "google_cloud_run_v2_service_iam_member" "operators" {
  for_each = length(local.live_services) > 0 ? var.operator_principals : toset([])
  project  = google_project.app.project_id
  location = var.region
  name     = google_cloud_run_v2_service.live["api"].name
  role     = "roles/run.invoker"
  member   = "${endswith(each.key, ".gserviceaccount.com") ? "serviceAccount" : "user"}:${each.key}"
}

resource "google_cloud_run_v2_service_iam_member" "agents" {
  for_each = setsubtract(local.live_services, ["api"])
  project  = google_project.app.project_id
  location = var.region
  name     = google_cloud_run_v2_service.live[each.key].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.role["api"].email}"
}

resource "google_cloud_run_v2_job" "shift" {
  count               = length(local.live_services) > 0 ? 1 : 0
  project             = google_project.app.project_id
  location            = var.region
  name                = "mds-shift"
  deletion_protection = false
  template {
    parallelism = 1
    task_count  = 1
    template {
      service_account = google_service_account.role["api"].email
      timeout         = "7200s"
      max_retries     = 0
      volumes {
        name = "cloudsql"
        cloud_sql_instance { instances = [google_sql_database_instance.live[0].connection_name] }
      }
      containers {
        image   = var.live_image
        command = ["python", "-m", "delivery.live_jobs"]
        resources { limits = { cpu = "1", memory = "2Gi" } }
        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
        dynamic "env" {
          for_each = merge(local.live_environment, local.vector_environment)
          content {
            name  = env.key
            value = env.value
          }
        }
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database["api"].secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
  depends_on = [google_secret_manager_secret_iam_member.database]
}

resource "google_project_iam_custom_role" "run_shift" {
  project     = google_project.app.project_id
  role_id     = "mdsRunShift"
  title       = "Execute the bounded Madrid shift job"
  permissions = ["run.jobs.run", "run.jobs.runWithOverrides"]
}

resource "google_cloud_run_v2_job_iam_member" "run_shift" {
  count    = length(local.live_services) > 0 ? 1 : 0
  project  = google_project.app.project_id
  location = var.region
  name     = google_cloud_run_v2_job.shift[0].name
  role     = google_project_iam_custom_role.run_shift.name
  member   = "serviceAccount:${google_service_account.role["api"].email}"
}

output "live_urls" { value = length(local.live_services) > 0 ? local.live_urls : {} }

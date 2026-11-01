locals {
  vector_enabled = var.active && var.enable_live && var.enable_vector_search
  vector_environment = local.vector_enabled ? {
    DELIVERY_VECTOR_INDEX          = "projects/${google_project.app.number}/locations/${var.region}/indexes/${basename(google_vertex_ai_index.memory[0].id)}"
    DELIVERY_VECTOR_ENDPOINT       = "projects/${google_project.app.number}/locations/${var.region}/indexEndpoints/${basename(google_vertex_ai_index_endpoint.memory[0].id)}"
    DELIVERY_VECTOR_DEPLOYED_INDEX = "memory_v1"
    DELIVERY_VECTOR_PUBLIC_DOMAIN  = google_vertex_ai_index_endpoint.memory[0].public_endpoint_domain_name
  } : {}
}

resource "google_vertex_ai_index" "memory" {
  count               = local.vector_enabled ? 1 : 0
  project             = google_project.app.project_id
  region              = var.region
  display_name        = "mds-scoped-memory"
  index_update_method = "STREAM_UPDATE"
  metadata {
    config {
      dimensions            = 384
      distance_measure_type = "COSINE_DISTANCE"
      shard_size            = "SHARD_SIZE_SMALL"
      algorithm_config {
        brute_force_config {}
      }
    }
  }
  labels     = local.labels
  depends_on = [google_project_service.api]
}

resource "google_vertex_ai_index_endpoint" "memory" {
  count        = local.vector_enabled ? 1 : 0
  project      = google_project.app.project_id
  region       = var.region
  display_name = "mds-scoped-memory"
  # Public networking, authenticated IAM API; no unauthenticated invocation grant.
  public_endpoint_enabled = true
  labels                  = local.labels
  depends_on              = [google_project_service.api]
}

resource "google_vertex_ai_index_endpoint_deployed_index" "memory" {
  count             = local.vector_enabled ? 1 : 0
  index_endpoint    = google_vertex_ai_index_endpoint.memory[0].id
  index             = google_vertex_ai_index.memory[0].id
  deployed_index_id = "memory_v1"
  dedicated_resources {
    min_replica_count = 1
    max_replica_count = 1
    machine_spec { machine_type = "e2-standard-2" }
  }
}

resource "google_project_iam_custom_role" "vector" {
  project     = google_project.app.project_id
  role_id     = "mdsMemoryVectors"
  title       = "Read and update the scoped memory vector index"
  permissions = ["aiplatform.indexes.update", "aiplatform.indexEndpoints.queryVectors"]
}

resource "google_project_iam_member" "vector" {
  for_each = local.vector_enabled ? toset(["api", "restaurant", "dispatcher"]) : toset([])
  project  = google_project.app.project_id
  role     = google_project_iam_custom_role.vector.name
  member   = "serviceAccount:${google_service_account.role[each.key].email}"
  condition {
    title      = "only-mds-memory"
    expression = "resource.name == '${google_vertex_ai_index.memory[0].name}' || resource.name == '${google_vertex_ai_index_endpoint.memory[0].name}'"
  }
}

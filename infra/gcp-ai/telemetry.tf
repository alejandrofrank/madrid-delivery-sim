# No collector, API enablement or telemetry identity unless explicitly requested.
variable "enable_telemetry" {
  description = "Provision trace-only APIs and IAM. Does not start a collector or export spans."
  type        = bool
  default     = false
}

resource "google_project_service" "telemetry" {
  for_each = toset(concat(
    var.enable_telemetry ? ["telemetry.googleapis.com", "cloudtrace.googleapis.com"] : [],
    var.enable_cloud_trace ? ["cloudtrace.googleapis.com"] : []
  ))
  project            = google_project.ai.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "telemetry" {
  count        = var.enable_telemetry ? 1 : 0
  project      = google_project.ai.project_id
  account_id   = "simulation-trace-exporter"
  display_name = "Trace-only simulation collector"
  depends_on   = [google_project_service.api]
}

resource "google_project_iam_member" "telemetry" {
  for_each = var.enable_telemetry ? toset([
    "roles/telemetry.tracesWriter", "roles/serviceusage.serviceUsageConsumer"
  ]) : toset([])
  project = google_project.ai.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.telemetry[0].email}"
}

resource "google_service_account_iam_binding" "telemetry_tokens" {
  count              = var.enable_telemetry ? 1 : 0
  service_account_id = google_service_account.telemetry[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  members            = var.invoker_members
}

output "telemetry_service_account" {
  description = "Trace-only collector identity; null while telemetry is parked."
  value       = var.enable_telemetry ? google_service_account.telemetry[0].email : null
}

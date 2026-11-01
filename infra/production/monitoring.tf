resource "google_monitoring_service" "replay" {
  count        = var.active && var.replay_image != "" ? 1 : 0
  project      = google_project.app.project_id
  service_id   = "mds-replay"
  display_name = "Madrid public replay (active demo sessions)"
  basic_service {
    service_type   = "CLOUD_RUN"
    service_labels = { service_name = "mds-replay", location = var.region }
  }
  depends_on = [google_cloud_run_v2_service.replay]
}

resource "google_monitoring_slo" "availability" {
  count               = var.active && var.replay_image != "" ? 1 : 0
  project             = google_project.app.project_id
  service             = google_monitoring_service.replay[0].service_id
  slo_id              = "availability"
  display_name        = "99 percent successful requests over 7 days"
  goal                = 0.99
  rolling_period_days = 7
  basic_sli {
    availability { enabled = true }
  }
}

resource "google_monitoring_slo" "latency" {
  count               = var.active && var.replay_image != "" ? 1 : 0
  project             = google_project.app.project_id
  service             = google_monitoring_service.replay[0].service_id
  slo_id              = "latency"
  display_name        = "95 percent of requests below 2 seconds over 7 days"
  goal                = 0.95
  rolling_period_days = 7
  basic_sli {
    latency { threshold = "2s" }
  }
}

resource "google_monitoring_alert_policy" "burn" {
  for_each              = var.active && var.replay_image != "" ? toset(["availability", "latency"]) : toset([])
  project               = google_project.app.project_id
  display_name          = "Madrid replay ${each.key} error budget burn"
  combiner              = "OR"
  notification_channels = google_monitoring_notification_channel.email[*].name
  conditions {
    display_name = "10x budget burn over 15 minutes"
    condition_threshold {
      filter          = "select_slo_burn_rate(\"projects/${google_project.app.number}/services/mds-replay/serviceLevelObjectives/${each.key}\", \"900s\")"
      comparison      = "COMPARISON_GT"
      threshold_value = 10
      duration        = "300s"
    }
  }
  documentation {
    mime_type = "text/markdown"
    content   = "Check the Cloud Run spending cap first, then service logs and the recorded replay integrity. Intentional Terraform stop removes this alert. Never lift a cap automatically."
  }
  depends_on = [google_monitoring_slo.availability, google_monitoring_slo.latency]
}

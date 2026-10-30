# Receipt analytics keeps the original dataset address. See STATE-MIGRATION.md
# before planning against state created by the standalone observability branch.
# Table keys and API keys are unambiguous and can migrate automatically.
moved {
  from = google_bigquery_table.analytics["traces"]
  to   = google_bigquery_table.observability["traces"]
}

moved {
  from = google_bigquery_table.analytics["agent_steps"]
  to   = google_bigquery_table.observability["agent_steps"]
}

moved {
  from = google_bigquery_table.analytics["eval_runs"]
  to   = google_bigquery_table.observability["eval_runs"]
}

moved {
  from = google_bigquery_table.analytics["orders"]
  to   = google_bigquery_table.observability["orders"]
}

moved {
  from = google_project_service.observability["bigquery.googleapis.com"]
  to   = google_project_service.bigquery[0]
}

moved {
  from = google_project_service.observability["cloudtrace.googleapis.com"]
  to   = google_project_service.telemetry["cloudtrace.googleapis.com"]
}

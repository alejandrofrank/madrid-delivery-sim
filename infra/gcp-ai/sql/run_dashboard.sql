-- Terraform renders identifiers; seven-day predicates prune both partitioned tables.
WITH latest_receipts AS (
  SELECT *
  FROM `${project_id}.${dataset_id}.run_receipts`
  WHERE exported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY run_id ORDER BY exported_at DESC, receipt_sha256) = 1
), kpis AS (
  SELECT run_id, receipt_sha256, exported_at,
    MAX(IF(metric_name = 'delivered', metric_value, NULL)) AS delivered,
    MAX(IF(metric_name = 'scheduled_calls', metric_value, NULL)) AS scheduled_calls,
    MAX(IF(metric_name = 'orders', metric_value, NULL)) AS orders,
    MAX(IF(metric_name = 'on_time', metric_value, NULL)) AS on_time,
    MAX(IF(metric_name = 'on_time_pct', metric_value, NULL)) AS on_time_pct,
    MAX(IF(metric_name = 'delivery_cost_eur', metric_value, NULL)) AS delivery_cost_eur,
    MAX(IF(metric_name = 'cost_per_delivery_eur', metric_value, NULL)) AS cost_per_delivery_eur,
    MAX(IF(metric_name = 'active', metric_value, NULL)) AS active,
    MAX(IF(metric_name = 'unserved', metric_value, NULL)) AS unserved,
    MAX(IF(metric_name = 'pending', metric_value, NULL)) AS pending,
    MAX(IF(metric_name = 'overdue', metric_value, NULL)) AS overdue,
    MAX(IF(metric_name = 'events', metric_value, NULL)) AS queue_events,
    MAX(IF(metric_name = 'dead_letters', metric_value, NULL)) AS dead_letters,
    MAX(IF(metric_name = 'retries', metric_value, NULL)) AS retries,
    MAX(IF(metric_name = 'late_physical_deliveries', metric_value, NULL)) AS late_deliveries,
    MAX(IF(metric_name = 'adk_offline_calls', metric_value, NULL)) AS adk_offline_calls,
    MAX(IF(metric_name = 'adk_vertex_dispatches', metric_value, NULL)) AS vertex_dispatches,
    MAX(IF(metric_name = 'adk_reserved_usd', metric_value, NULL)) AS adk_reserved_usd
  FROM `${project_id}.${dataset_id}.run_kpis`
  WHERE exported_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  GROUP BY run_id, receipt_sha256, exported_at
)
SELECT r.*, DATE(r.run_created_at) AS run_date,
  SAFE_DIVIDE(r.checks_passed, r.checks_total) AS evaluation_pass_rate,
  SAFE_DIVIDE(k.delivered, COALESCE(k.scheduled_calls, k.orders)) AS delivery_rate,
  k.* EXCEPT (run_id, receipt_sha256, exported_at)
FROM latest_receipts r
LEFT JOIN kpis k USING (run_id, receipt_sha256, exported_at)

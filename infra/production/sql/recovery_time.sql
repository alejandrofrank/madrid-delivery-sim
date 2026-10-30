SELECT run_id, disruption_id, time_to_recover_seconds,
  time_to_recover_seconds IS NULL AS unresolved,
  orders_saved, orders_lost, late_deliveries, refund_cost_eur,
  extra_tokens, extra_token_cost_usd, failed_replans
FROM `${project}.mds_analytics.disruptions`
WHERE observed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at DESC) = 1

WITH latest AS (
  SELECT * FROM `${project}.mds_analytics.operational_orders`
  WHERE observed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at DESC) = 1
)
SELECT run_id, COUNT(*) AS attempted_orders, COUNTIF(delivered) AS delivered_orders,
  COUNTIF(late) AS late_deliveries,
  SAFE_DIVIDE(COUNTIF(late), COUNTIF(delivered AND late IS NOT NULL)) AS late_delivery_rate,
  SAFE_DIVIDE(COUNTIF(NOT delivered), COUNT(*)) AS lost_order_rate
FROM latest GROUP BY run_id

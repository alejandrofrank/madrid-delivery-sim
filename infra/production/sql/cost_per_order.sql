WITH orders AS (
  SELECT * FROM `${project}.mds_analytics.operational_orders`
  WHERE observed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at DESC) = 1
), traces AS (
  SELECT * FROM `${project}.mds_analytics.traces`
  WHERE observed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at DESC) = 1
), spend AS (
  SELECT run_id, SUM(cost_usd) AS model_cost_usd,
    COUNTIF(cost_usd IS NOT NULL) AS measured_cost_spans
  FROM traces WHERE name = 'agent.model' GROUP BY run_id
)
SELECT o.run_id, COUNT(*) AS orders, COUNTIF(delivered) AS delivered_orders,
  AVG(delivery_cost_eur) AS delivery_cost_eur_per_order,
  SAFE_DIVIDE(ANY_VALUE(s.model_cost_usd), COUNT(*)) AS model_cost_usd_per_order,
  ANY_VALUE(s.measured_cost_spans) AS measured_cost_spans
FROM orders o LEFT JOIN spend s USING(run_id) GROUP BY o.run_id

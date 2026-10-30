WITH latest AS (
  SELECT * FROM `${project}.mds_analytics.traces`
  WHERE observed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at DESC) = 1
)
SELECT run_id, agent, model, SUM(input_tokens) AS input_tokens,
  SUM(output_tokens) AS output_tokens, SUM(cost_usd) AS model_cost_usd,
  COUNT(*) AS model_spans, COUNTIF(cost_usd IS NULL) AS unpriced_spans
FROM latest WHERE name = 'agent.model' GROUP BY run_id, agent, model

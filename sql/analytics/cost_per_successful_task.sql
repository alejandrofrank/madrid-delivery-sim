-- GoogleSQL. Replace PROJECT_ID; bind @start_time and @end_time as TIMESTAMP.
-- All costs in the window (including failed/incomplete tasks) fund the successes.
-- Do not sum orders.cost_usd: model costs already appear on agent_steps.
-- Unknown model prices/usage make the total NULL; zero-cost tools are not models.
WITH steps AS (
  SELECT * FROM `PROJECT_ID.mds_analytics.agent_steps`
  WHERE observed_at >= @start_time AND observed_at < @end_time
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at DESC) = 1
), terminals AS (
  SELECT * FROM `PROJECT_ID.mds_analytics.orders`
  WHERE observed_at >= @start_time AND observed_at < @end_time
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at ASC) = 1
), outcomes AS (
  SELECT trace_id, success FROM terminals
  WHERE trace_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY trace_id ORDER BY observed_at ASC, event_id ASC) = 1
), tasks AS (
  SELECT
    agent, trace_id,
    SUM(IF(model IS NOT NULL, cost_usd, 0)) AS known_cost_usd,
    COUNTIF(model IS NOT NULL AND cost_usd IS NULL) AS unknown_model_costs
  FROM steps
  WHERE trace_id IS NOT NULL AND order_id IS NOT NULL
  GROUP BY agent, trace_id
)
SELECT
  agent,
  COUNT(*) AS observed_tasks,
  COUNTIF(outcomes.success) AS successful_tasks,
  SUM(unknown_model_costs) AS unknown_model_costs,
  IF(SUM(unknown_model_costs) = 0, SUM(known_cost_usd), NULL) AS total_cost_usd,
  IF(SUM(unknown_model_costs) = 0,
    SAFE_DIVIDE(SUM(known_cost_usd), COUNTIF(outcomes.success)), NULL
  ) AS cost_per_successful_task_usd
FROM tasks LEFT JOIN outcomes USING (trace_id)
GROUP BY agent
ORDER BY agent;

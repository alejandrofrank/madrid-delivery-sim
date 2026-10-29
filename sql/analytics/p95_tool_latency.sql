-- GoogleSQL. Replace PROJECT_ID; bind @start_time and @end_time as TIMESTAMP.
-- agent_steps includes one row per tool span; traces contains the same spans.
-- Descendant capability/queue spans inherit tool identity; count only the tool boundary.
WITH steps AS (
  SELECT * FROM `PROJECT_ID.mds_analytics.agent_steps`
  WHERE observed_at >= @start_time AND observed_at < @end_time
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at DESC) = 1
)
SELECT
  agent,
  tool,
  COUNT(*) AS tool_calls,
  COUNTIF(success = FALSE) AS errors,
  APPROX_QUANTILES(latency_ms, 100)[OFFSET(95)] AS p95_latency_ms
FROM steps
WHERE name = 'agent.tool' AND tool IS NOT NULL AND latency_ms IS NOT NULL
GROUP BY agent, tool
ORDER BY agent, tool;

-- GoogleSQL. Replace PROJECT_ID; bind @start_time and @end_time as TIMESTAMP.
-- pass_power_k is observed all-k success, not the chance of any one attempt passing.
-- Keep mode/fixture/revision separate: deterministic replay is not LLM reliability.
-- category is diagnostic and may change between attempts; it must not split a case.
WITH deduplicated AS (
  SELECT * FROM `PROJECT_ID.mds_analytics.eval_runs`
  WHERE observed_at >= @start_time AND observed_at < @end_time
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY observed_at DESC) = 1
), attempts AS (
  SELECT * FROM deduplicated
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY run_id, case_id, agent, arm, repetition, repeat_k,
      fixture_version, source_revision, mode
    ORDER BY observed_at DESC, event_id DESC
  ) = 1
), cases AS (
  SELECT
    run_id, case_id, arm, agent, repeat_k, fixture_version, source_revision, mode,
    DATE(MAX(observed_at)) AS day,
    COUNT(*) = repeat_k AND COUNT(passed) = repeat_k
      AND MIN(repetition) = 1 AND MAX(repetition) = repeat_k AS complete,
    LOGICAL_AND(passed) AS all_passed,
    AVG(CAST(passed AS FLOAT64)) AS attempt_pass_rate
  FROM attempts
  WHERE run_id IS NOT NULL AND case_id IS NOT NULL AND repeat_k >= 1
  GROUP BY run_id, case_id, arm, agent, repeat_k,
    fixture_version, source_revision, mode
)
SELECT
  day, agent, arm, repeat_k, fixture_version, source_revision, mode,
  COUNTIF(complete) AS complete_cases,
  COUNTIF(NOT complete) AS incomplete_cases,
  SAFE_DIVIDE(COUNTIF(complete AND all_passed), COUNTIF(complete)) AS pass_power_k,
  POWER(AVG(IF(complete, attempt_pass_rate, NULL)), repeat_k) AS pass_power_k_iid_estimate
FROM cases
GROUP BY day, agent, arm, repeat_k, fixture_version, source_revision, mode
ORDER BY day, agent, arm, repeat_k;

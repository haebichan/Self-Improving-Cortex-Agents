-- Run the demo end-to-end
-- Execute AFTER setup scripts

-- ============================================================
-- Step 1: Seed data
-- ============================================================
USE SCHEMA <YOUR_DB>.<YOUR_AGENT_SCHEMA>;

-- (Run example_agent/tables/seed_data.sql here)

-- ============================================================
-- Step 2: Trigger a failure trace (baseline)
-- Agent will fail because it passes total orders instead of completed orders
-- ============================================================
SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
    '<YOUR_DB>.<YOUR_AGENT_SCHEMA>.SELF_EVOLVING_AGENT_V2',
    '{"messages": [{"role": "user", "content": [{"type": "text", "text": "Check credit score for Kevin Robinson and update his tier based on the result"}]}]}'
);

-- Wait ~60 seconds for observability events to flush

-- ============================================================
-- Step 3: Run the self-learning pipeline
-- This will: diagnose the trace → generate a skill → validate → promote
-- ============================================================
CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.EVOLVE_SKILLS(
    '<YOUR_DB>.<YOUR_AGENT_SCHEMA>.SELF_EVOLVING_AGENT_V2'
);

-- ============================================================
-- Step 4: Test the improved agent
-- Same question rephrased — should now complete in 3 calls, ~38s
-- ============================================================
SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
    '<YOUR_DB>.<YOUR_AGENT_SCHEMA>.SELF_EVOLVING_AGENT_V2',
    '{"messages": [{"role": "user", "content": [{"type": "text", "text": "Review credit score for Kevin Robinson and change his tier based on the result"}]}]}'
);

-- ============================================================
-- Step 5: Verify improvement via observability
-- ============================================================
SELECT 
    TRACE['trace_id']::STRING AS trace_id,
    COUNT(CASE WHEN RECORD:name::STRING LIKE 'SystemExecuteSQLTool%' 
               OR RECORD:name::STRING LIKE 'ToolCall%' THEN 1 END) AS tool_calls,
    TIMESTAMPDIFF('second', MIN(TIMESTAMP), MAX(TIMESTAMP)) AS duration_seconds
FROM TABLE(SNOWFLAKE.LOCAL.GET_AI_OBSERVABILITY_EVENTS(
    '<YOUR_DB>', '<YOUR_AGENT_SCHEMA>', 'SELF_EVOLVING_AGENT_V2', 'CORTEX AGENT'
))
WHERE TRACE['trace_id']::STRING IS NOT NULL
GROUP BY trace_id
ORDER BY MAX(TIMESTAMP) DESC
LIMIT 5;

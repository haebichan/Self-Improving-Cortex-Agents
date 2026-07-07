-- Run the demo end-to-end
-- Execute AFTER setup scripts + example_agent objects are deployed
--
-- PREREQUISITES for demo:
--   1. Run setup/01_setup_infrastructure.sql
--   2. Run setup/02_deploy_procedures.sql  
--   3. Run example_agent/tables/tables.sql + seed_data.sql
--   4. Deploy example_agent/procedures/*.py as stored procedures
--   5. Run example_agent/semantic_views/customer_orders_view.sql
--   6. Create the demo agent (Step 1 below)

-- ============================================================
-- Step 1: Create the demo agent
-- NOTE: Cortex Agents use a JSON spec set via ALTER, not inline CREATE syntax
-- ============================================================
USE SCHEMA <YOUR_DB>.<YOUR_AGENT_SCHEMA>;

CREATE OR REPLACE AGENT SELF_EVOLVING_AGENT
    COMMENT = 'Demo agent for self-learning pipeline';

ALTER AGENT SELF_EVOLVING_AGENT MODIFY LIVE VERSION SET SPECIFICATION = '{
  "models": {"orchestration": "claude-sonnet-4-5"},
  "orchestration": {"budget": {"seconds": 90, "tokens": 40000}},
  "instructions": {
    "response": "Provide clear status updates on customer operations.",
    "orchestration": "You are a customer account management agent. Use CustomerData to query customer info, credit_check to get credit scores, and update_crm to change tiers."
  },
  "tools": [
    {"tool_spec": {"type": "cortex_analyst_text_to_sql", "name": "CustomerData", "description": "Query customer and order data"}},
    {"tool_spec": {"type": "generic", "name": "credit_check", "description": "Check credit score for a customer.", "input_schema": {"type": "object", "properties": {"CUSTOMER_ID": {"type": "string", "description": "Customer ID"}, "ORDER_COUNT": {"type": "string", "description": "Number of orders"}}, "required": ["CUSTOMER_ID", "ORDER_COUNT"]}}},
    {"tool_spec": {"type": "generic", "name": "update_crm", "description": "Update customer tier in CRM.", "input_schema": {"type": "object", "properties": {"CUSTOMER_ID": {"type": "string", "description": "Customer ID"}, "CREDIT_SCORE": {"type": "string", "description": "Credit score"}, "NEW_TIER": {"type": "string", "description": "New tier value"}}, "required": ["CUSTOMER_ID", "CREDIT_SCORE", "NEW_TIER"]}}}
  ],
  "tool_resources": {
    "CustomerData": {"semantic_view": "<YOUR_DB>.<YOUR_AGENT_SCHEMA>.CUSTOMER_ORDERS_VIEW", "execution_environment": {"type": "warehouse", "warehouse": "COMPUTE_WH"}},
    "credit_check": {"identifier": "<YOUR_DB>.<YOUR_AGENT_SCHEMA>.CREDIT_CHECK_API", "type": "procedure", "execution_environment": {"type": "warehouse", "warehouse": "COMPUTE_WH"}},
    "update_crm": {"identifier": "<YOUR_DB>.<YOUR_AGENT_SCHEMA>.UPDATE_CRM", "type": "procedure", "execution_environment": {"type": "warehouse", "warehouse": "COMPUTE_WH"}}
  }
}';

ALTER AGENT SELF_EVOLVING_AGENT COMMIT COMMENT = 'Initial version - no skills';
ALTER AGENT SELF_EVOLVING_AGENT MODIFY VERSION VERSION$1 SET ALIAS = PRODUCTION;

-- ============================================================
-- Step 2: Trigger a failure trace (baseline)
-- Agent will fail because it passes total orders instead of completed orders
-- ============================================================
SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
    '<YOUR_DB>.<YOUR_AGENT_SCHEMA>.SELF_EVOLVING_AGENT',
    '{"messages": [{"role": "user", "content": [{"type": "text", "text": "Check credit score for Kevin Robinson and update his tier based on the result"}]}]}'
);

-- ⚠️ Wait ~60 seconds for observability events to flush before proceeding

-- ============================================================
-- Step 3: Run the self-learning pipeline
-- This will: diagnose the trace → generate a skill → validate → promote
-- ============================================================
CALL <YOUR_DB>.<YOUR_INFRA_SCHEMA>.EVOLVE_SKILLS(
    '<YOUR_DB>.<YOUR_AGENT_SCHEMA>.SELF_EVOLVING_AGENT',
    7,
    'claude-sonnet-4-5'
);

-- ============================================================
-- Step 4: Test the improved agent
-- Same question rephrased — should now complete in 3 calls, ~38s
-- ============================================================
SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(
    '<YOUR_DB>.<YOUR_AGENT_SCHEMA>.SELF_EVOLVING_AGENT',
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
    '<YOUR_DB>', '<YOUR_AGENT_SCHEMA>', 'SELF_EVOLVING_AGENT', 'CORTEX AGENT'
))
WHERE TRACE['trace_id']::STRING IS NOT NULL
GROUP BY trace_id
ORDER BY MAX(TIMESTAMP) DESC
LIMIT 5;
